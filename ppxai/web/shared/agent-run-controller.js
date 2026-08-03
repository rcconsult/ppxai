/**
 * AgentRunController — web client driver for the /v1/agent/* run registry.
 *
 * Owns the /agentrun + /agentruns command behavior:
 *   - launches tool-free oneshot runs (POST /v1/agent/run),
 *   - renders each into its own right-panel AgentRunView (one pane per run_id),
 *   - chat-side navigation: clickable breadcrumbs + a clickable run list that
 *     focus or reopen panes by run_id (recreating from the server if a pane was
 *     LRU-evicted), and pins non-terminal runs so a running pane survives.
 *
 * Extracted from command-dispatcher.js in v1.19.0 Increment B so the dispatcher
 * stays a thin router and this feature has room to grow — the tool-capable
 * /task tier (its own design iteration) will live here too.
 *
 * @version 1.19.0
 */

/**
 * Parse a `/agentrun` argument line into `{task, provider, model}`.
 *
 * Unlike `/task`, the description does NOT have to lead: the two recognized
 * flags (`--provider` / `--model`) are pulled out wherever they appear and
 * everything else joins as the task. So these are equivalent:
 *   /agentrun weather today --provider perplexity
 *   /agentrun --provider perplexity weather today
 * An unrecognized `--flag` is left verbatim in the task text (no error), since
 * a one-shot task is free-form prose. `--provider`/`--model` with no following
 * value (or followed by another flag) are left in the task rather than eating it.
 */
function parseAgentRunArgs(argline) {
    const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
    const toks = [];
    let m;
    while ((m = re.exec((argline || '').trim())) !== null) {
        toks.push(m[1] !== undefined ? m[1] : (m[2] !== undefined ? m[2] : m[3]));
    }
    const out = { task: '', provider: null, model: null };
    const rest = [];
    for (let i = 0; i < toks.length; i += 1) {
        const t = toks[i];
        if ((t === '--provider' || t === '--model')
            && i + 1 < toks.length && !toks[i + 1].startsWith('--')) {
            if (t === '--provider') out.provider = toks[i + 1];
            else out.model = toks[i + 1];
            i += 1;
            continue;
        }
        rest.push(t);
    }
    out.task = rest.join(' ').trim();
    return out;
}

class AgentRunController {
    /** @param {PpxaiApp} app */
    constructor(app) {
        this.app = app;
        // Status-poll cadence for the detached watcher's fallback (overridable
        // in tests). Used only when the SSE stream ends/fails before the run
        // reaches a terminal state — see _pollUntilTerminal.
        // Degraded-path poll (used only after the live SSE tail drops). It polls
        // until the run is terminal — NO wall-clock ceiling, so a long run isn't
        // abandoned — backing off from _pollIntervalMs to _pollMaxIntervalMs, and
        // gives up ONLY after _pollMaxFailures consecutive GET failures (server
        // unreachable), a meaningful stop rather than an arbitrary duration.
        this._pollIntervalMs = 1500;
        this._pollMaxIntervalMs = 30000;
        this._pollMaxFailures = 20;
        // run_ids with an in-flight detached watcher — so focus() can restart a
        // watcher for a run the degraded path gave up on without double-watching.
        this._watching = new Set();
        // The pane class this controller renders into. Parameterized (was the
        // hardcoded AgentRunView) so the tool-capable /task tier can subclass
        // this controller and swap in a denser TaskRunView while reusing the
        // shared observe/watch/poll machinery. Null in Node (no window).
        this._viewClass = (typeof AgentRunView !== 'undefined') ? AgentRunView : null;
        // Empty-list hint — overridden by the /task subclass to point at its
        // own launch verb.
        this._emptyHint = 'No agent runs yet. Start one with /task "<desc>" --tools … or /run "<prompt>".';
        // The command that reopens a run's pane (used in recovery hints) — the
        // /task subclass overrides it, so a task run's "how to retry" message
        // names the right verb.
        this._reopenHint = '/task ls';
        // U3 (ADR 0011): command-family surface knobs. `_cmd` names the slash
        // command in usage/hint strings; `_kind` filters ls to this family's
        // runs (null = unfiltered). Subclasses override both.
        this._cmd = '/task';
        this._kind = null;
    }

    /**
     * Wire optional per-view affordances a subclass' view may expose (duck-typed
     * so the oneshot AgentRunView, which has neither, is unaffected):
     *   - setOnCancel(fn)  — a Cancel button that POSTs /runs/{id}/cancel.
     *   - setOnRespond(fn) — a consent card (T5) that POSTs /runs/{id}/respond
     *     with {token, approved, text}.
     *   - setOnAck(fn)     — a Collect button (T6) that POSTs /runs/{id}/ack
     *     to collect a held result (completed_pending_ack → finalized).
     *   - setOnResume(fn)  — a Resume button (T7) that POSTs /runs/{id}/resume
     *     to continue an interrupted/cancelled run.
     */
    _wireView(view, runId) {
        if (view && typeof view.setOnCancel === 'function') {
            view.setOnCancel(() => this.cancel(runId));
        }
        if (view && typeof view.setOnRespond === 'function') {
            view.setOnRespond((payload) => this.respond(runId, payload));
        }
        if (view && typeof view.setOnAck === 'function') {
            view.setOnAck(() => this.ack(runId));
        }
        if (view && typeof view.setOnResume === 'function') {
            view.setOnResume(() => this.resume(runId));
        }
    }

    /**
     * Error → transcript text. A 401 from the /v1 surface almost always
     * means "no bearer attached" — point at the in-chat fix instead of
     * only relaying the bare FastAPI detail (Item 40 trial feedback; the
     * VSCode taskController.errText carries the same hint).
     */
    _errText(e) {
        const msg = (e && e.message) || String(e);
        if (e && e.status === 401) {
            return `${msg} — 💡 no /v1 API token attached: run \`/token mint\` (local server) or \`/token set\` (paste one).`;
        }
        return msg;
    }

    // ── Commands ──────────────────────────────────────────────────────────────

    /** /agentrun <task> [--provider p] [--model m] — launch a background oneshot run. */
    async start(argline) {
        const parsed = parseAgentRunArgs(argline);
        const task = parsed.task;
        if (!task) {
            this.app.showSystemMessage('Usage: `/agentrun <task> [--provider <p>] [--model <m>]`');
            return;
        }
        // Explicit --provider/--model are the run's per-run intent; otherwise
        // inherit the UI's current selection. (Server falls back to
        // tools.agent.default_subagent if neither is present.)
        const provider = parsed.provider || this.app.state.currentProvider;
        // Model: an explicit --model always wins. Otherwise inherit the UI model
        // ONLY when the run uses the UI's provider — a UI model belongs to the
        // UI provider and is INVALID on a different --provider (e.g. a Qwen model
        // id sent to Perplexity → 400). When --provider overrides without --model,
        // send no model and let the server resolve that provider's default_model.
        let model = parsed.model;
        if (!model && (!parsed.provider || parsed.provider === this.app.state.currentProvider)) {
            model = this.app.state.currentModel;
        }
        const body = { task, tools: [] };
        if (provider) body.provider = provider;
        if (model) body.model = model;
        let started;
        try {
            started = await this.app.apiClient.post('/v1/agent/run', body);
        } catch (e) {
            this.app.showSystemMessage(`❌ Agent run rejected: ${this._errText(e)}`);
            return;
        }
        const runId = started.run_id;
        // Open a right-panel view for this run and drop a clickable breadcrumb in
        // chat so history records it; the live result renders into the pane.
        this._openPane(runId, task);
        this._breadcrumb(runId, task, `🤖 ${runId} — running… (in panel; chat stays usable)`);
        // Fire-and-forget: the run lives in the server's background registry, so
        // we do NOT await it here — returning frees the prompt. The watcher
        // resolves the run's CURRENT pane by run_id when it finishes (so a
        // reopened pane still receives the result).
        this._watchDetached(runId);
    }

    /** ls — list recent runs (kind-filtered per family) as clickable rows. */
    async list() {
        let data;
        try {
            const url = this._kind
                ? `/v1/agent/runs?kind=${this._kind}` : '/v1/agent/runs';
            data = await this.app.apiClient.get(url);
        } catch (e) {
            this.app.showSystemMessage(`❌ Could not list runs: ${this._errText(e)}`);
            return;
        }
        const runs = (data && data.runs) || [];
        if (runs.length === 0) {
            this.app.showSystemMessage(this._emptyHint);
            return;
        }
        const content = this._messageBody('Agent runs (newest first):');
        if (!content) return;
        const list = document.createElement('div');
        list.className = 'agent-runs-list';
        runs.slice(0, 20).forEach((r) => {
            const row = document.createElement('button');
            row.className = 'agent-run-row';
            const icon = {
                completed: '✅', completed_pending_ack: '📬', finalized: '✅',
                failed: '❌', running: '🤖', waiting: '✋',
            }[r.status] || 'ℹ️';
            row.textContent = `${icon} ${r.run_id}  ${r.status}  ${(r.task || '').slice(0, 50)}`;
            row.addEventListener('click', () => this.focus(r.run_id, r.task));
            list.appendChild(row);
        });
        content.appendChild(list);
    }

    /**
     * Focus a run's pane and refresh it from the server. Promotes the existing
     * pane (or recreates one if it was evicted), refetches the registry, and:
     *   - terminal run  → renders the result (or mirrors to chat if the pane was
     *                     closed mid-GET) via _renderTerminal.
     *   - otherwise     → marks the pane live and (re)starts the detached watcher
     *                     UNLESS the run is KNOWN terminal. A failed refresh GET
     *                     (status unknown) therefore still resumes the watcher —
     *                     whose poll-with-retry resolves the run — instead of
     *                     stranding the pane in a hard error (review fix).
     */
    async focus(runId, task) {
        const frame = this.app.rightPanelFrame;
        if (!frame || !this._viewClass) return;
        let view = frame.getViewByPath(`agent://run/${runId}`);
        if (view) {
            frame.push(view);   // dedup → promote + show
        } else {
            view = new this._viewClass(runId, task || '', this.app.state);
            this._wireView(view, runId);
            frame.push(view);
        }

        let run = null;
        try {
            run = await this.app.apiClient.get(`/v1/agent/runs/${runId}`);
        } catch (e) {
            run = null;  // transient read failure → unknown status, NOT terminal
        }

        // Hydrate the pane's grant/egress/budget from the registry record (a
        // reopened pane was constructed without them). Duck-typed: no-op on the
        // oneshot AgentRunView, which has no meta bar.
        if (run) {
            const v = this._liveView(runId);
            if (v && typeof v.setMeta === 'function') v.setMeta(run);
        }

        if (run && AgentRunController._TERMINAL.has(run.status)) {
            // Resolve live (the pane may have been closed during the GET) and
            // render — falling back to chat if it's gone. announce=false: the
            // run was already announced when it finished; reopening must not
            // re-emit the "✅ completed" chat breadcrumb.
            this._renderTerminal(runId, run, false);
            return;
        }
        // Non-terminal or unknown: keep the pane pinned + show status, and ensure
        // a watcher is running so the eventual result lands without another reopen.
        const live = this._liveView(runId);
        if (live) { live.setStatus(run ? run.status : 'reconnecting'); live.pin(); }
        if (!this._watching.has(runId)) this._watchDetached(runId);
    }

    // ── Internals ─────────────────────────────────────────────────────────────

    /** Push a new pane for a run; pin it so a running pane survives LRU eviction. */
    _openPane(runId, task, meta) {
        const frame = this.app.rightPanelFrame;
        if (!frame || !this._viewClass) return null;
        const view = new this._viewClass(runId, task, this.app.state, meta);
        this._wireView(view, runId);
        if (meta && typeof view.setMeta === 'function') view.setMeta(meta);
        view.pin();
        frame.push(view);
        return view;
    }

    /**
     * Cancel a run (POST /runs/{id}/cancel) and reflect it in the pane. Shared by
     * every tier; the oneshot UI simply never surfaces a Cancel control, while
     * the /task pane wires its Cancel button here via _wireView.
     */
    async cancel(runId) {
        if (!runId) { this.app.showSystemMessage(`Usage: \`${this._cmd} cancel <id>\``); return; }
        try {
            await this.app.apiClient.post(`/v1/agent/runs/${runId}/cancel`, {});
        } catch (e) {
            this.app.showSystemMessage(`❌ Could not cancel ${runId}: ${this._errText(e)}`);
            return;
        }
        this.app.showSystemMessage(`⏹️ ${runId} — cancel requested`);
        const view = this._liveView(runId);
        if (view) view.setStatus('cancelling');
    }

    /**
     * Answer a `waiting` park (T5): POST /runs/{id}/respond with
     * {token, approved?, text?}. Shared by the consent card (via _wireView)
     * and the `/task respond` verb. The 409 detail (token mismatch / not
     * parked / restarted) is surfaced verbatim — it says exactly why the
     * answer didn't land.
     */
    async respond(runId, payload) {
        try {
            await this.app.apiClient.post(`/v1/agent/runs/${runId}/respond`, payload);
        } catch (e) {
            this.app.showSystemMessage(`❌ Could not respond to ${runId}: ${this._errText(e)}`);
            return false;
        }
        const label = payload.approved === true ? 'approved'
            : (payload.approved === false ? 'denied' : 'answered');
        this.app.showSystemMessage(`✋ ${runId} — ${label}; run resumes`);
        const view = this._liveView(runId);
        if (view) {
            view.setStatus('running');
            if (typeof view.clearWaiting === 'function') view.clearWaiting();
        }
        return true;
    }

    /**
     * Collect a held result (T6): POST /runs/{id}/ack — the receipt that
     * flips completed_pending_ack → finalized. The result body stays on the
     * run record (ack only marks it collected / GC-eligible). Shared by the
     * pane's Collect button (via _wireView) and the `/task collect` verb
     * (U2 rename; `ack` stays as alias).
     */
    async ack(runId) {
        if (!runId) { this.app.showSystemMessage(`Usage: \`${this._cmd} collect <id>\``); return false; }
        try {
            await this.app.apiClient.post(`/v1/agent/runs/${runId}/ack`, {});
        } catch (e) {
            this.app.showSystemMessage(`❌ Could not ack ${runId}: ${this._errText(e)}`);
            return false;
        }
        this.app.showSystemMessage(`📬 ${runId} — result collected (finalized)`);
        const view = this._liveView(runId);
        if (view) view.setStatus('finalized');
        return true;
    }

    /**
     * Continue an interrupted/cancelled run (T7): POST /runs/{id}/resume.
     * The server refuses with a stated reason when the checkpoint is
     * inconclusive — surfaced verbatim. On success the run is `running`
     * again under the same run_id, so re-pin the pane and restart the
     * detached watcher (the old one broke at the interrupt).
     */
    async resume(runId) {
        if (!runId) { this.app.showSystemMessage(`Usage: \`${this._cmd} resume <id>\``); return false; }
        try {
            await this.app.apiClient.post(`/v1/agent/runs/${runId}/resume`, {});
        } catch (e) {
            this.app.showSystemMessage(`❌ Could not resume ${runId}: ${this._errText(e)}`);
            return false;
        }
        this.app.showSystemMessage(`▶️ ${runId} — resumed (running)`);
        const view = this._liveView(runId);
        if (view) {
            view.setStatus('running');
            view.pin();
        }
        if (!this._watching.has(runId)) this._watchDetached(runId);
        return true;
    }

    /** Append a chat message; return its `.message-content` element (or null). */
    _messageBody(text) {
        const el = this.app.addMessage('system', text);
        return el?.querySelector?.('.message-content') || null;
    }

    /** Breadcrumb with a clickable "open ▸" that focuses the run's pane. */
    _breadcrumb(runId, task, text) {
        const content = this._messageBody(text);
        if (!content) return;
        const btn = document.createElement('button');
        btn.className = 'agent-run-open';
        btn.textContent = 'open ▸';
        btn.addEventListener('click', () => this.focus(runId, task));
        content.appendChild(btn);
    }

    /** The run's CURRENT pane (resolved by run_id), or null if none is on the stack. */
    _liveView(runId) {
        const frame = this.app.rightPanelFrame;
        return (frame && typeof frame.getViewByPath === 'function')
            ? (frame.getViewByPath(`agent://run/${runId}`) || null)
            : null;
    }

    /**
     * Detached tail of a background run: follow the live SSE stream to a terminal
     * event (or poll if it drops), then render the result into the run's CURRENT
     * pane — resolved by run_id, so a closed-then-reopened run renders into the
     * NEW visible pane, not the instance captured at launch. Mirrors to chat only
     * when no pane exists for the run. NOT awaited by start().
     *
     * Deduped via _watching so focus() can safely (re)start a watcher for a run
     * the degraded path gave up on without ever double-watching.
     */
    async _watchDetached(runId) {
        if (this._watching.has(runId)) return;
        this._watching.add(runId);
        try {
            await this._runWatch(runId);
        } finally {
            this._watching.delete(runId);
        }
    }

    /** The tail → poll → render cycle. Wrapped by _watchDetached for dedup. */
    async _runWatch(runId) {
        try {
            for await (const ev of this._tailEvents(runId)) {
                // Forward every event to the run's CURRENT pane if it renders a
                // live log (duck-typed: no-op on the oneshot AgentRunView). Lets
                // the /task pane show tool_call / tool_denied / network_* / spawn_*
                // as they stream, reusing this one tail loop.
                const live = this._liveView(runId);
                if (live && typeof live.appendEvent === 'function') live.appendEvent(ev);
                // The live-events SSE stays open until the client disconnects —
                // it does NOT close when the run ends. Break on ANY terminal
                // run-event (complete/error AND cancelled/interrupted, emitted as
                // `agent_run_<status>`), otherwise a cancelled/interrupted run
                // parks the tail on an open stream forever.
                //
                // BUT the stream replays the persisted backlog first, so a
                // RESUMED run's tail sees the historical agent_run_interrupted
                // / _cancelled from before the resume — breaking on that stale
                // replay silently detaches the fresh tail (no live events, no
                // consent card; T7 live-trial bug). The run record is the
                // source of truth: break only when the run is REALLY terminal
                // right now. An unreachable server also breaks — the poll
                // fallback below owns that case.
                if (AgentRunController._TERMINAL_EVENTS.has(ev.type)) {
                    let now = null;
                    try {
                        now = await this.app.apiClient.get(`/v1/agent/runs/${runId}`);
                    } catch (e) { /* unreachable → fall through to poll */ }
                    if (!now || AgentRunController._TERMINAL.has(now.status)) break;
                }
            }
        } catch (e) {
            this.app.showSystemMessage(
                `⚠️ ${runId} — live stream unavailable (${e.message}); polling status…`
            );
        }
        // The stream can end/fail BEFORE the run is terminal (transient outage,
        // server-side SSE drop). A single status read would then leave a still-
        // running run permanently detached, so poll until it actually finishes.
        const run = await this._pollUntilTerminal(runId);
        if (!run || !AgentRunController._TERMINAL.has(run.status)) {
            // The poll gave up only after sustained GET failures (server
            // unreachable) — NOT a run-duration cutoff. Don't claim a result;
            // UNPIN so the pane isn't stuck pinned, and move it to a terminal
            // 'unreachable' state so the pane itself stops lying about being
            // "reconnecting" (the chat message alone left the pane visually
            // stuck — Gemini review). No data is lost: reopening (breadcrumb /
            // /agentruns / /task ls) calls focus(), which refreshes the pane AND
            // restarts this watcher.
            const stale = this._liveView(runId);
            if (stale) {
                stale.unpin();
                stale.setStatus('unreachable');
                if (typeof stale.setError === 'function') {
                    stale.setError(
                        `Monitoring stopped — server unreachable. Reopen via ${this._reopenHint} to retry.`
                    );
                }
            }
            this.app.showSystemMessage(
                `⚠️ ${runId} — lost contact with the server; reopen via ${this._reopenHint} to retry.`
            );
            return;
        }

        this._renderTerminal(runId, run, true);
    }

    /**
     * Render a terminal run into its CURRENT pane (resolved by run_id, NOT a
     * captured instance — covers close-then-reopen). If no pane exists for the
     * run (closed/evicted, incl. closed mid-GET), mirror the result into chat so
     * it isn't lost.
     *
     * `announce` controls the one-time chat breadcrumb (`✅ <run> — completed`):
     * the watcher passes true (the run just finished); focus() passes false so
     * reopening a finished run refreshes the pane WITHOUT re-spamming chat.
     */
    _renderTerminal(runId, run, announce) {
        const icon = {
            completed: '✅', completed_pending_ack: '📬', finalized: '✅',
            failed: '❌', cancelled: '⏹️', interrupted: '⏸️',
        }[run.status] || 'ℹ️';
        const view = this._liveView(runId);
        if (view) { view.unpin(); view.setStatus(run.status); }
        if (announce) this.app.showSystemMessage(`${icon} ${runId} — ${run.status}`);

        if (AgentRunController._SUCCESS.has(run.status)) {
            // completed / completed_pending_ack / finalized — all carry the
            // result body. A held run (T6) renders it too; collecting is the
            // pane's explicit Collect button / `/task collect`, never a silent
            // auto-ack (the user decides when the receipt is issued).
            if (view) view.setResult(run.result || '');
            else this.app.addMessage('assistant', run.result || '(empty result)');
        } else {
            // failed / cancelled / interrupted
            const msg = run.error || `Run ${run.status}`;
            if (view) view.setError(msg);
            else this.app.addMessage('assistant', `${runId} — ${run.status}: ${msg}`);
            if (announce && view && run.error) this.app.showSystemMessage(`   ${run.error}`);
        }
    }

    /**
     * Degraded-path poll (runs only after the live SSE tail drops): GET the run's
     * status until it is terminal, then return it. Backs off from _pollIntervalMs
     * to _pollMaxIntervalMs and keeps the run's current pane's status chip live.
     *
     * There is NO run-duration ceiling — a long run is followed to completion, so
     * a still-running run is never abandoned at an arbitrary time (the recurring
     * "watcher dies → unwatched" gap). It returns null ONLY after
     * _pollMaxFailures CONSECUTIVE GET failures (server unreachable) — a
     * meaningful give-up condition; a successful "still running" read resets the
     * counter. On give-up nothing is lost: reopening restarts the watcher.
     */
    async _pollUntilTerminal(runId) {
        let delay = this._pollIntervalMs;
        let failures = 0;
        for (;;) {
            let run = null;
            try {
                run = await this.app.apiClient.get(`/v1/agent/runs/${runId}`);
            } catch (e) {
                run = null;
            }
            if (run) {
                failures = 0;
                if (AgentRunController._TERMINAL.has(run.status)) return run;
                const view = this._liveView(runId);
                if (view) view.setStatus(run.status);
            } else if (++failures >= this._pollMaxFailures) {
                return null;  // server unreachable across many polls — give up
            }
            await new Promise((r) => setTimeout(r, delay));
            delay = Math.min(delay * 2, this._pollMaxIntervalMs);
        }
    }

    /** Async-iterate the parsed `data:` events of a run's live SSE stream. */
    async *_tailEvents(runId) {
        const api = this.app.apiClient;
        const path = `/v1/agent/runs/${runId}/events?live=1`;
        const resp = await fetch(
            `${api.serverUrl}${path}`,
            // headersFor attaches the bearer on /v1/* (Item 40); a raw
            // getHeaders() here would 401 the tail on auth-enforcing hosts.
            { headers: api.headersFor ? api.headersFor(path) : api.getHeaders() }
        );
        if (!resp.ok || !resp.body) throw new Error(`stream ${resp.status}`);
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) return;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try { yield JSON.parse(line.slice(6)); } catch (e) { /* skip */ }
                }
            }
        } finally {
            reader.cancel();
        }
    }
}

// Terminal run statuses (ADR 0003: cancelled/interrupted are resumable
// terminal states distinct from failed). Polling stops on any of these.
// T6: completed_pending_ack (result held, run exited) and finalized
// (collected) are both terminal for polling purposes.
AgentRunController._TERMINAL = new Set([
    'completed', 'completed_pending_ack', 'finalized',
    'failed', 'cancelled', 'interrupted',
]);

// Success statuses whose record carries a result body to render.
AgentRunController._SUCCESS = new Set([
    'completed', 'completed_pending_ack', 'finalized',
]);

// Terminal SSE run-event types — the registry emits `agent_run_<status>`
// (engine/agent_runs.py: complete/error explicitly, cancelled/interrupted via
// `f"agent_run_{stop.status}"`). The live stream stays open after these, so the
// tail loop must break on them. `agent_run_cancelling` is a transition, NOT
// terminal (the real `agent_run_cancelled` follows). T6: a held /task run
// emits `agent_result_ready` INSTEAD of `agent_run_complete`; the later
// `agent_run_finalized` (ack/retention) is also a stream-terminal marker for
// any tail that reattached to a held run.
AgentRunController._TERMINAL_EVENTS = new Set([
    'agent_run_complete', 'agent_result_ready', 'agent_run_finalized',
    'agent_run_error', 'agent_run_cancelled', 'agent_run_interrupted',
]);


// CommonJS export for tests; window-global for browser.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { AgentRunController, parseAgentRunArgs };
} else if (typeof window !== 'undefined') {
    window.AgentRunController = AgentRunController;
}

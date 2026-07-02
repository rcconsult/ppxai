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
        this._emptyHint = 'No agent runs yet. Start one with /agentrun <task>.';
    }

    /**
     * Wire optional per-view affordances a subclass' view may expose (duck-typed
     * so the oneshot AgentRunView, which has neither, is unaffected):
     *   - setOnCancel(fn) — a Cancel button that POSTs /runs/{id}/cancel.
     */
    _wireView(view, runId) {
        if (view && typeof view.setOnCancel === 'function') {
            view.setOnCancel(() => this.cancel(runId));
        }
    }

    // ── Commands ──────────────────────────────────────────────────────────────

    /** /agentrun <task> — launch a background oneshot run, render in a pane. */
    async start(task) {
        if (!task) {
            this.app.showSystemMessage('Usage: /agentrun <task>');
            return;
        }
        // Pass the UI's current provider/model as the run's explicit per-run
        // intent (server falls back to tools.agent.default_subagent if absent).
        const body = { task, tools: [] };
        if (this.app.state.currentProvider) body.provider = this.app.state.currentProvider;
        if (this.app.state.currentModel) body.model = this.app.state.currentModel;
        let started;
        try {
            started = await this.app.apiClient.post('/v1/agent/run', body);
        } catch (e) {
            this.app.showSystemMessage(`❌ Agent run rejected: ${e.message}`);
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

    /** /agentruns — list recent runs as clickable rows that focus their panes. */
    async list() {
        let data;
        try {
            data = await this.app.apiClient.get('/v1/agent/runs');
        } catch (e) {
            this.app.showSystemMessage(`❌ Could not list runs: ${e.message}`);
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
            const icon = { completed: '✅', failed: '❌', running: '🤖' }[r.status] || 'ℹ️';
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
        if (!runId) { this.app.showSystemMessage('Usage: /task cancel <id>'); return; }
        try {
            await this.app.apiClient.post(`/v1/agent/runs/${runId}/cancel`, {});
        } catch (e) {
            this.app.showSystemMessage(`❌ Could not cancel ${runId}: ${e.message}`);
            return;
        }
        this.app.showSystemMessage(`⏹️ ${runId} — cancel requested`);
        const view = this._liveView(runId);
        if (view) view.setStatus('cancelling');
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
                if (AgentRunController._TERMINAL_EVENTS.has(ev.type)) break;
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
                        'Monitoring stopped — server unreachable. Reopen via '
                        + '/agentruns (or /task ls) to retry.'
                    );
                }
            }
            this.app.showSystemMessage(
                `⚠️ ${runId} — lost contact with the server; reopen via /agentruns to retry.`
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
        const icon = { completed: '✅', failed: '❌', cancelled: '⏹️', interrupted: '⏸️' }[run.status] || 'ℹ️';
        const view = this._liveView(runId);
        if (view) { view.unpin(); view.setStatus(run.status); }
        if (announce) this.app.showSystemMessage(`${icon} ${runId} — ${run.status}`);

        if (run.status === 'completed') {
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
        const resp = await fetch(
            `${api.serverUrl}/v1/agent/runs/${runId}/events?live=1`,
            { headers: api.getHeaders() }
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
AgentRunController._TERMINAL = new Set(['completed', 'failed', 'cancelled', 'interrupted']);

// Terminal SSE run-event types — the registry emits `agent_run_<status>`
// (engine/agent_runs.py: complete/error explicitly, cancelled/interrupted via
// `f"agent_run_{stop.status}"`). The live stream stays open after these, so the
// tail loop must break on them. `agent_run_cancelling` is a transition, NOT
// terminal (the real `agent_run_cancelled` follows).
AgentRunController._TERMINAL_EVENTS = new Set([
    'agent_run_complete', 'agent_run_error', 'agent_run_cancelled', 'agent_run_interrupted',
]);


// CommonJS export for tests; window-global for browser.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { AgentRunController };
} else if (typeof window !== 'undefined') {
    window.AgentRunController = AgentRunController;
}

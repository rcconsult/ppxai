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
        const view = this._openPane(runId, task);
        this._breadcrumb(runId, task, `🤖 ${runId} — running… (in panel; chat stays usable)`);
        // Fire-and-forget: the run lives in the server's background registry, so
        // we do NOT await it here — returning frees the prompt. The result
        // renders out-of-band, addressed by run_id, when the run finishes.
        this._watchDetached(runId, view);
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
            this.app.showSystemMessage('No agent runs yet. Start one with /agentrun <task>.');
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
     * Focus a run's pane: if it's still on the stack, dedup-push promotes it;
     * otherwise recreate the view and hydrate it from the server (the run
     * survives in the registry even after its pane is evicted).
     */
    async focus(runId, task) {
        const frame = this.app.rightPanelFrame;
        if (!frame || typeof AgentRunView === 'undefined') return;
        const existing = frame.getViewByPath(`agent://run/${runId}`);
        if (existing) {
            frame.push(existing);   // dedup → promote + show
            return;
        }
        const view = new AgentRunView(runId, task || '', this.app.state);
        frame.push(view);
        try {
            const run = await this.app.apiClient.get(`/v1/agent/runs/${runId}`);
            view.setStatus(run.status);
            if (run.status === 'completed') view.setResult(run.result || '');
            else if (run.status === 'failed') view.setError(run.error || 'Run failed');
        } catch (e) {
            view.setError(`Could not load run: ${e.message}`);
        }
    }

    // ── Internals ─────────────────────────────────────────────────────────────

    /** Push a new pane for a run; pin it so a running pane survives LRU eviction. */
    _openPane(runId, task) {
        const frame = this.app.rightPanelFrame;
        if (!frame || typeof AgentRunView === 'undefined') return null;
        const view = new AgentRunView(runId, task, this.app.state);
        view.pin();
        frame.push(view);
        return view;
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

    /**
     * Detached tail of a background run: follow the live SSE stream to a terminal
     * event, then read meta once and render the result into the run's pane
     * (chat fallback if the pane was evicted). NOT awaited by start().
     */
    async _watchDetached(runId, view) {
        try {
            for await (const ev of this._tailEvents(runId)) {
                if (ev.type === 'agent_run_complete' || ev.type === 'agent_run_error') break;
            }
        } catch (e) {
            this.app.showSystemMessage(
                `⚠️ ${runId} — live stream unavailable (${e.message}); reading status…`
            );
        }
        let run;
        try {
            run = await this.app.apiClient.get(`/v1/agent/runs/${runId}`);
        } catch (e) {
            this.app.showSystemMessage(`⚠️ ${runId} — could not read final status: ${e.message}`);
            return;
        }
        const icon = { completed: '✅', failed: '❌' }[run.status] || 'ℹ️';
        // Terminal → unpin so the pane is eligible for LRU eviction again.
        if (view) { view.unpin(); view.setStatus(run.status); }
        this.app.showSystemMessage(`${icon} ${runId} — ${run.status}`);
        if (run.status === 'completed') {
            const rendered = view && view.setResult(run.result || '');
            if (!rendered) this.app.addMessage('assistant', run.result || '(empty result)');
        } else if (run.status === 'failed') {
            if (view) view.setError(run.error || 'Run failed');
            if (run.error) this.app.showSystemMessage(`   ${run.error}`);
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


// CommonJS export for tests; window-global for browser.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { AgentRunController };
} else if (typeof window !== 'undefined') {
    window.AgentRunController = AgentRunController;
}

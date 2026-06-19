/**
 * CommandDispatcher — thin shell over POST /command/<name> (v1.18.1).
 *
 * Pre-v1.18.1 this file was a 967-line switch with ~20 bespoke
 * `handleXCommand` methods that each duplicated the formatting and
 * REST-call logic that the Python `CommandFactory` already does
 * server-side. The factory and the JS list drifted; PyInstaller
 * silently dropped 9 of 10 command modules at v1.17.4 and nobody
 * noticed for six releases because only `/usage` actually exercised
 * `POST /command/`.
 *
 * v1.18.1 unifies dispatch:
 *   - Streaming commands (chat-message-shaped) keep using POST /chat.
 *   - The /agent toggle still goes to dedicated REST.
 *   - Every other command flows through `apiClient.executeCommand(name, args)`.
 *     The server returns the v1 envelope:
 *         {ok, result, side_effects, events, version}
 *     `result` → ResultRenderer.render
 *     `side_effects` → SideEffectsHandler.apply
 *     `events`       → SSE-shaped state mutations, fed back through
 *                      app.handleStateSync (state-sync Phase B).
 *
 * What used to be 35 case branches + 20 helper methods is now ~120
 * lines of pure dispatch + envelope unwrap.
 *
 * Usage:
 *   this.commandDispatcher = new CommandDispatcher(app);
 *   await this.commandDispatcher.dispatch(input);
 */

// Commands whose response IS the chat stream (factory just picks
// the system prompt; the streaming itself isn't a command result).
const STREAMING_COMMANDS = new Set([
    '/generate', '/explain', '/test', '/docs',
    '/debug', '/implement', '/convert', '/spec',
]);


class CommandDispatcher {
    /** @param {PpxaiApp} app */
    constructor(app) {
        this.app = app;
        this.renderer = new ResultRenderer(app);
        this.sideEffects = new SideEffectsHandler(app);
    }

    /**
     * Route a slash-command input to the right path.
     *
     * - Streaming commands → POST /chat (no envelope; the SSE
     *   stream IS the response).
     * - /agent <task>      → also chat-shaped (autonomous task).
     * - /agent on|off      → toggleAgent() (existing REST path).
     * - Everything else    → POST /command/<name> via the v1
     *   envelope.
     *
     * @param {string} input  - raw user input including the leading `/`
     */
    async dispatch(input) {
        if (this.app.state.isHandlingCommand) {
            console.warn('dispatch called while already handling:', input);
            return;
        }
        this.app.state.isHandlingCommand = true;
        try {
            const parts = input.trim().split(/\s+/);
            const cmd = parts[0].toLowerCase();
            const args = parts.slice(1).join(' ');

            this.app.showSystemMessage(`> ${input}`);

            if (STREAMING_COMMANDS.has(cmd)) {
                this.app.addMessage('user', input);
                await this.app.streamChat(input);
                return;
            }

            if (cmd === '/agent') {
                await this._dispatchAgent(args, input);
                return;
            }

            // Agent platform (v1.19.0 /v1/agent/* run registry — distinct from
            // the engine-side /agent above). /agentrun starts a background run
            // and live-polls it; /agentruns lists recent runs.
            if (cmd === '/agentrun') {
                await this._dispatchAgentRun(args);
                return;
            }
            if (cmd === '/agentruns') {
                await this._dispatchAgentRunsList();
                return;
            }

            // /help: render the server catalog, then append the web-only
            // experimental agent-platform commands the CommandFactory can't
            // see (they're client-side shims, not factory commands).
            if (cmd === '/help' && !args) {
                await this._dispatchToFactory('help', '');
                this._appendExperimentalHelp();
                return;
            }

            // Default: factory dispatch via POST /command/<name>.
            // Strip the leading slash; executeCommand adds nothing.
            await this._dispatchToFactory(cmd.slice(1), args);
        } finally {
            this.app.state.isHandlingCommand = false;
        }
    }

    /**
     * /agent has three shapes:
     *   /agent           → status query (no mutation)
     *   /agent on|off    → toggle (REST path; existing toggleAgent)
     *   /agent <task>    → autonomous task (chat-shaped, /chat path)
     *
     * The toggle path stays bespoke because it has UI state coupling
     * (the agent badge animation). The other two go through the
     * factory or the chat stream.
     */
    async _dispatchAgent(args, input) {
        if (args === 'on') {
            if (!this.app.state.agentMode) await this.app.toggleAgent();
            return;
        }
        if (args === 'off') {
            if (this.app.state.agentMode) await this.app.toggleAgent();
            return;
        }
        if (args) {
            // Autonomous task — feed the whole thing to /chat
            this.app.addMessage('user', input);
            await this.app.streamChat(`/agent ${args}`);
            return;
        }
        // No args — show status via factory
        await this._dispatchToFactory('agent', '');
    }

    /**
     * /agentrun <task> — start a background agent run (v1.19.0 /v1/agent/*,
     * distinct from /agent's engine-side loop) and tail it to terminal.
     */
    async _dispatchAgentRun(task) {
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
        // Open a right-panel view for this run (one per run_id) and keep a
        // one-line breadcrumb in chat so history records it; the live result
        // renders into the pane, leaving the main chat free.
        const view = this._openAgentRunPane(runId, task);
        this.app.showSystemMessage(`🤖 ${runId} — running… (in panel; chat stays usable)`);
        // Fire-and-forget: the run is in the server's background registry, so we
        // do NOT await its completion here — returning now frees the prompt. The
        // result renders out-of-band, addressed by run_id, when the run finishes.
        this._watchAgentRunDetached(runId, view);
    }

    /**
     * Open (push) the right-panel view for a run. Returns the view, or null if
     * the frame/component is unavailable (then the watcher falls back to chat).
     */
    _openAgentRunPane(runId, task) {
        const frame = this.app.rightPanelFrame;
        if (!frame || typeof AgentRunView === 'undefined') return null;
        const view = new AgentRunView(runId, task, this.app.state);
        frame.push(view);
        return view;
    }

    /**
     * Detached tail of a background run: follow the live SSE stream to a
     * terminal event, then read meta once and render the result into the run's
     * pane (falling back to chat if the pane was evicted). NOT awaited by the
     * caller — all errors surface as system messages.
     *
     * @param {string} runId
     * @param {AgentRunView|null} view  - the run's pane, or null (chat fallback)
     */
    async _watchAgentRunDetached(runId, view) {
        try {
            for await (const ev of this._tailRunEvents(runId)) {
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
        if (view) view.setStatus(run.status);
        this.app.showSystemMessage(`${icon} ${runId} — ${run.status}`);
        if (run.status === 'completed') {
            // Render into the pane; if it was evicted/unmounted, fall back to chat.
            const rendered = view && view.setResult(run.result || '');
            if (!rendered) this.app.addMessage('assistant', run.result || '(empty result)');
        } else if (run.status === 'failed') {
            if (view) view.setError(run.error || 'Run failed');
            if (run.error) this.app.showSystemMessage(`   ${run.error}`);
        }
    }

    /** Async-iterate the parsed `data:` events of a run's live SSE stream. */
    async *_tailRunEvents(runId) {
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

    /**
     * Append the web-only experimental agent-platform commands to /help.
     * The server's CommandFactory help (the canonical catalog) doesn't know
     * about these client-side shims, so list them from the shared catalog.
     */
    _appendExperimentalHelp() {
        const cat = this.app.slashCommands || {};
        const lines = ['/agentrun', '/agentruns']
            .filter((c) => cat[c])
            .map((c) => `  ${c} — ${cat[c].description}  (usage: ${cat[c].usage})`);
        if (lines.length) {
            this.app.showSystemMessage(
                `Experimental (web-only) agent-platform commands:\n${lines.join('\n')}`
            );
        }
    }

    /**
     * /agentruns — list recent agent runs (newest first).
     */
    async _dispatchAgentRunsList() {
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
        const lines = runs
            .slice(0, 20)
            .map((r) => {
                const task = (r.task || '').slice(0, 50);
                return `  ${r.run_id}  ${r.status.padEnd(9)}  ${task}`;
            })
            .join('\n');
        this.app.showSystemMessage(`Agent runs (newest first):\n${lines}`);
    }

    /**
     * Send to POST /command/<name>, render the result, apply
     * side-effects, drain events[] through the SSE dispatcher.
     */
    async _dispatchToFactory(name, args) {
        let envelope;
        try {
            envelope = await this.app.apiClient.executeCommand(name, args);
        } catch (e) {
            // 404 = unknown command, 500 = handler crashed, etc.
            const msg = e?.message || String(e);
            if (/404|Not Found|Unknown command/i.test(msg)) {
                this.app.showError(
                    `Unknown command: /${name}. Type /help for available commands.`
                );
            } else {
                this.app.showError(`Command failed: ${msg}`);
            }
            return;
        }

        // v1.18.1 envelope shape — but tolerate the legacy
        // CommandResult.to_dict() shape too in case some
        // intermediate proxy strips the wrapping.
        if (envelope && typeof envelope === 'object') {
            if ('result' in envelope) {
                this.renderer.render(envelope.result);
                this.sideEffects.apply(envelope.side_effects || []);
                this._drainEvents(envelope.events);
            } else {
                // Legacy: server returned the raw CommandResult dict
                this.renderer.render(envelope);
            }
        }
    }

    /**
     * Feed the envelope's events[] through the same handler the live SSE
     * stream uses (state-sync Phase B: REST mutations piggyback state_sync /
     * working_dir_changed immediately). Each event is {type, data, metadata?}.
     */
    _drainEvents(events) {
        if (!Array.isArray(events) || events.length === 0) return;
        for (const ev of events) {
            if (!ev || typeof ev !== 'object') continue;
            // state_sync → handleStateSync (AppState + DOM side-effects);
            // other types → best-effort processSseEvent if app exposes it.
            if (ev.type === 'state_sync' && ev.data) {
                if (typeof this.app.handleStateSync === 'function') {
                    this.app.handleStateSync(ev.data);
                }
            } else if (typeof this.app.processSseEvent === 'function') {
                this.app.processSseEvent(ev);
            }
        }
    }
}


// CommonJS export for tests; window-global for browser.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { CommandDispatcher, STREAMING_COMMANDS };
} else if (typeof window !== 'undefined') {
    window.CommandDispatcher = CommandDispatcher;
}

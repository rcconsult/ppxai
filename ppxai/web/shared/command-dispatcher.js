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
     * /agentrun <task> — start a background agent run (v1.19.0 Inc 2) and
     * live-poll it to terminal, updating one system line as it progresses.
     * Distinct from /agent (engine-side autonomous loop). Inc 1-2 surface:
     * POST /v1/agent/run -> {run_id, status:"running"}, then poll
     * GET /v1/agent/runs/<id> until completed/failed.
     */
    async _dispatchAgentRun(task) {
        if (!task) {
            this.app.showSystemMessage('Usage: /agentrun <task>');
            return;
        }
        // Pass the UI's CURRENT provider/model explicitly — for the human
        // /agentrun command, the active selection is the user's explicit
        // choice at spawn time (a legitimate per-run intent), not implicit
        // session inheritance. The server falls back to
        // tools.agent.default_subagent only if these are absent.
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
        this.app.showSystemMessage(`🤖 ${runId} — running…`);

        // Inc 3: live event stream (SSE) instead of polling. Tail
        // GET .../events?live=1; render lifecycle events; stop on terminal.
        // Falls back to one status fetch if the stream can't be opened.
        const api = this.app.apiClient;
        try {
            const resp = await fetch(
                `${api.serverUrl}/v1/agent/runs/${runId}/events?live=1`,
                { headers: api.getHeaders() }
            );
            if (!resp.ok || !resp.body) throw new Error(`stream ${resp.status}`);
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    let ev;
                    try { ev = JSON.parse(line.slice(6)); } catch (e) { continue; }
                    if (ev.type === 'agent_run_complete') {
                        // Result body isn't in the event payload — fetch the
                        // finished run's meta for the full result.
                        const run = await api.get(`/v1/agent/runs/${runId}`);
                        this.app.showSystemMessage(`✅ ${runId} — completed`);
                        this.app.addMessage('assistant', run.result || '(empty result)');
                        reader.cancel();
                        return;
                    }
                    if (ev.type === 'agent_run_error') {
                        this.app.showSystemMessage(
                            `❌ ${runId} — failed: ${(ev.data && ev.data.error) || 'unknown error'}`
                        );
                        reader.cancel();
                        return;
                    }
                }
            }
            // Stream ended without a terminal event — fall back to a status read.
            const run = await api.get(`/v1/agent/runs/${runId}`);
            this.app.showSystemMessage(`ℹ️ ${runId} — ${run.status}`);
            if (run.status === 'completed') {
                this.app.addMessage('assistant', run.result || '(empty result)');
            }
        } catch (e) {
            this.app.showSystemMessage(
                `⚠️ ${runId} — live stream unavailable (${e.message}); check /agentruns`
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
     * Feed the envelope's events[] through the same handler the
     * live SSE stream uses. State-sync Phase B: REST mutations
     * deliver state_sync / working_dir_changed / etc. immediately
     * via piggyback, not after the next chat.
     *
     * Each event has the shape {type, data, metadata?}, identical
     * to live SSE event objects.
     */
    _drainEvents(events) {
        if (!Array.isArray(events) || events.length === 0) return;
        for (const ev of events) {
            if (!ev || typeof ev !== 'object') continue;
            // state_sync routes through handleStateSync (which
            // updates AppState + fires DOM side-effects). Other
            // event types (working_dir_changed, etc.) get a
            // best-effort dispatch through processSseEvent if
            // app exposes it; otherwise the state_sync covers
            // everything that matters for the AppState mirror.
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

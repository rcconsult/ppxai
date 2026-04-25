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

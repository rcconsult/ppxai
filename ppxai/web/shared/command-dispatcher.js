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
        // v1.19.0: agent-platform run commands (/agentrun, /agentruns) live in
        // their own controller so this dispatcher stays a thin router.
        this.agentRuns = (typeof AgentRunController !== 'undefined')
            ? new AgentRunController(app)
            : null;
        // v1.19.x (T1): the tool-capable /task tier + sub-commands.
        this.tasks = (typeof TaskController !== 'undefined')
            ? new TaskController(app)
            : null;
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
            // the engine-side /agent above). Delegated to AgentRunController:
            // /agentrun starts a background run (rendered in a right-panel pane);
            // /agentruns lists recent runs as clickable rows that focus panes.
            if (cmd === '/agentrun') {
                await this.agentRuns?.start(args);
                return;
            }
            if (cmd === '/agentruns') {
                await this.agentRuns?.list();
                return;
            }

            // Tool-capable tier (T1): `/task <verb> …` — run/ls/show/watch/cancel.
            // The whole arg string (verb + rest, incl. quoted desc + flags) is
            // handed to the controller, which parses it.
            if (cmd === '/task') {
                await this.tasks?.handle(args);
                return;
            }

            // Item 40: `/token` — manage the /v1 API bearer this client
            // attaches (the agent/token API stays protected even on loopback).
            if (cmd === '/token') {
                await this._handleTokenCommand(args);
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
     * Item 40: `/token status|set|mint|clear` — bearer management for the
     * protected /v1 API surface.
     *
     * Security shape:
     * - `set` takes the value via a browser prompt(), NEVER inline — every
     *   dispatched command line is echoed as a system message AND forwarded
     *   to the server debug log (see `> ${input}` above), so an inline
     *   secret would land in ~/.ppxai/logs. An inline value is still
     *   accepted (it already echoed) but answered with a rotate warning.
     * - `mint` uses the loopback bootstrap: POST /v1/tokens is exempt from
     *   auth for a DIRECT local browser (server/auth.py::_is_bootstrap_mint),
     *   so a token-less local client can self-provision its first token.
     *   The raw material is returned exactly once; we store it and show
     *   only a masked tail.
     * - Storage: localStorage['ppxai-api-token'] — restored on app init.
     */
    async _handleTokenCommand(args) {
        const verb = (args.split(/\s+/, 1)[0] || 'status').toLowerCase();
        const inline = args.slice(verb.length).trim();
        const api = this.app.apiClient;
        const masked = (t) => (t && t.length > 4 ? `…${t.slice(-4)}` : '(set)');
        const store = (t) => {
            try { localStorage.setItem('ppxai-api-token', t); } catch (_e) { /* private mode */ }
            api.setApiToken(t);
        };
        switch (verb) {
            case 'status': {
                const t = api.apiToken;
                this.app.showSystemMessage(t
                    ? `🔑 API token attached to /v1 calls (${masked(t)}). \`/token clear\` to remove.`
                    : 'No API token stored. `/token mint` (local server) or `/token set` (paste one).');
                return;
            }
            case 'set': {
                let value = inline;
                if (!value) {
                    value = (typeof window !== 'undefined' && window.prompt)
                        ? (window.prompt('Paste the API token (stored locally, attached to /v1 calls):') || '').trim()
                        : '';
                    if (!value) { this.app.showSystemMessage('No token entered — nothing stored.'); return; }
                    store(value);
                    this.app.showSystemMessage(`🔑 Token stored (${masked(value)}).`);
                    return;
                }
                store(value);
                this.app.showSystemMessage(
                    `🔑 Token stored (${masked(value)}) — ⚠️ it was typed inline, so it was echoed ` +
                    'into the chat + debug log. Prefer `/token set` without a value (prompt), and ' +
                    'consider rotating this token.');
                return;
            }
            case 'mint': {
                try {
                    // A stale stored bearer would be validated (and rejected)
                    // even on the loopback-exempt mint — send this one bare.
                    const hadToken = api.apiToken;
                    api.setApiToken(null);
                    let resp;
                    try {
                        resp = await api.post('/v1/tokens', { owner: 'web-local', roles: [] });
                    } finally {
                        if (!resp) api.setApiToken(hadToken);
                    }
                    store(resp.token);
                    this.app.showSystemMessage(
                        `🔑 Minted + stored token ${masked(resp.token)} ` +
                        `(id ${resp.meta.token_id}, owner ${resp.meta.owner}). Attached to /v1 calls from now on.`);
                } catch (e) {
                    this.app.showSystemMessage(
                        `❌ Mint failed: ${e.message}. Minting needs a mint-capable token store ` +
                        '(server.secrets.providers type "file") and a DIRECT local connection; ' +
                        'remotely, ask the operator for a token and use `/token set`.');
                }
                return;
            }
            case 'clear': {
                try { localStorage.removeItem('ppxai-api-token'); } catch (_e) { /* ignore */ }
                api.setApiToken(null);
                this.app.showSystemMessage('🔑 Token cleared — /v1 calls are unauthenticated again.');
                return;
            }
            default:
                this.app.showSystemMessage('Usage: `/token [status|set|mint|clear]`');
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
     * Append the web-only experimental agent-platform commands to /help.
     * The server's CommandFactory help (the canonical catalog) doesn't know
     * about these client-side shims, so list them from the shared catalog.
     */
    _appendExperimentalHelp() {
        const cat = this.app.slashCommands || {};
        const lines = ['/agentrun', '/agentruns', '/task', '/token']
            .filter((c) => cat[c])
            .map((c) => `  ${c} — ${cat[c].description}  (usage: ${cat[c].usage})`);
        if (lines.length) {
            this.app.showSystemMessage(
                `Experimental (web-only) agent-platform commands:\n${lines.join('\n')}`
            );
        }
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

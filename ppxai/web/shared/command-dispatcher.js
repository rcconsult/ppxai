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
 *   - The /auto toggle (was /agent pre-v1.19.1) still goes to dedicated REST.
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
 * v1.19.3 (ADR 0007 step 3a) — routing became DATA.
 *   The five-branch `if (cmd === …)` chain over /auto, /run, /task,
 *   /token and /help is gone. `app.commandRoster` (fetched from
 *   `GET /commands?client=web`) says, per command, whether THIS client
 *   dispatches it (`dispatch === "client"`) and under which named
 *   `client_action`; `CommandDispatcher.CLIENT_ACTIONS` below maps those
 *   names to the implementations this client bundles. Python owns the
 *   binding, the client owns the code — no executable ever crosses the
 *   wire (ADR 0007, §Why this and not the alternatives).
 *
 *   With NO roster the dispatcher FAILS CLOSED: it refuses to dispatch
 *   any slash command rather than forwarding the ones it doesn't
 *   recognise. `/token set <value>` carries a secret, and forwarding it
 *   to `POST /command/token` would put that secret in a request body and
 *   in the server debug log (the leak fixed server-side in step 1b).
 *   There is deliberately NO hardcoded `/token` escape hatch — that
 *   would be a second roster again.
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

// Client id this dispatcher speaks as. Sent as `?client=` on the roster
// fetch and as the optional `client` field on POST /command/<name>, so
// the server gates `/help` and completion to what WEB can actually see
// (without it one HTTP surface serves both web and VSCode and has to
// over-list for the union — the step-1b limitation step 2 closed).
const WEB_CLIENT_ID = 'web';


class CommandDispatcher {
    /** @param {PpxaiApp} app */
    constructor(app) {
        this.app = app;
        this.renderer = new ResultRenderer(app);
        this.sideEffects = new SideEffectsHandler(app);
        // v1.19.x (T1): the tool-capable /task tier + sub-commands.
        this.tasks = (typeof TaskController !== 'undefined')
            ? new TaskController(app)
            : null;
        // U3 (ADR 0011): the /run one-off family — kind=oneshot runs on the
        // same gears; replaces the retired /agentrun + /agentruns.
        this.runs = (typeof RunController !== 'undefined')
            ? new RunController(app)
            : null;
    }

    /**
     * Route a slash-command input to the right path (roster-driven since
     * ADR 0007 step 3a).
     *
     * Order, and why:
     *   1. FAIL-CLOSED GATE — no roster, no dispatch. Comes first so that
     *      a client with a stale/unreachable server never forwards a
     *      slash command it cannot classify.
     *   2. Streaming commands → POST /chat. Chat-shaped, not command
     *      dispatch: the SSE stream IS the response, so they bypass the
     *      envelope entirely. (The server declares `coding.stream` for
     *      VSCode only; web keeps this set until ADR 0007 step 5 folds
     *      chat-shaped-ness into the roster.)
     *   3. `dispatch === "client"` → the bundled implementation named by
     *      the entry's `client_action` (CLIENT_ACTIONS below).
     *   4. Everything else → POST /command/<name> via the v1 envelope.
     *
     * @param {string} input  - raw user input including the leading `/`
     */
    async dispatch(input) {
        if (this.app.state.isHandlingCommand) {
            // Redacted: even a devtools line should not hold a bearer.
            console.warn('dispatch called while already handling:',
                         this._redactEcho(input));
            return;
        }
        this.app.state.isHandlingCommand = true;
        try {
            const parts = input.trim().split(/\s+/);
            const cmd = parts[0].toLowerCase();
            const args = parts.slice(1).join(' ');

            // ADR 0007 step 3a-sec: the echo is REDACTED before it is
            // rendered or mirrored to POST /client-log. `> /token set
            // <bearer>` used to reach ~/.ppxai/logs verbatim, on a path
            // that runs before routing is even consulted. The rule comes
            // from the roster (`sensitive` per subcommand), never from a
            // hardcoded name, and it fails closed with no roster.
            this.app.showSystemMessage(`> ${this._redactEcho(input)}`);

            // (1) Fail closed. Routing is server-declared data; without it
            // this client cannot tell a client-handled command from a
            // forwardable one, and guessing leaks secrets.
            const roster = await this._readyRoster();
            if (!roster) {
                this._explainMissingRoster(cmd);
                return;
            }

            // (2) Chat-shaped commands never touch command dispatch.
            if (STREAMING_COMMANDS.has(cmd)) {
                this.app.addMessage('user', input);
                await this.app.streamChat(input);
                return;
            }

            // (3)/(4) Data-driven routing. `resolve` handles aliases, so
            // `/cat` reaches `show`'s entry without a second alias table.
            const entry = roster.resolve(cmd);
            if (entry && entry.dispatch === 'client') {
                await this._dispatchClientAction(entry, args, input);
                return;
            }

            // Default: factory dispatch via POST /command/<name>. An entry
            // we resolved contributes its CANONICAL name; an unknown name
            // is sent as typed so the server produces the 404 whose message
            // the user is expecting.
            await this._dispatchToFactory(entry ? entry.name : cmd.slice(1), args);
        } finally {
            this.app.state.isHandlingCommand = false;
        }
    }

    /**
     * Redact the typed line for the chat echo (ADR 0007 step 3a-sec).
     *
     * Delegates to the roster, which owns the rule — loaded, it masks
     * only the value of a subcommand Python declared sensitive; NOT
     * loaded, it masks every argument of every slash command, the same
     * fail-closed posture as the dispatch gate below.
     */
    _redactEcho(input) {
        const roster = this.app.commandRoster;
        if (roster && typeof roster.redact === 'function') {
            return roster.redact(input);
        }
        if (typeof CommandRoster !== 'undefined') {
            return CommandRoster.redactWithoutRoster(input);
        }
        // No roster module at all — the page is broken; say nothing.
        return '\u2022\u2022\u2022\u2022';
    }

    /**
     * Return the loaded roster, or null.
     *
     * Retries the fetch once, inline, when nothing is loaded yet: a client
     * that started before the server was reachable should self-heal on the
     * next command rather than staying wedged until a page reload.
     */
    async _readyRoster() {
        const roster = this.app.commandRoster;
        if (!roster) return null;
        if (roster.isLoaded()) return roster;
        await roster.load();
        return roster.isLoaded() ? roster : null;
    }

    /**
     * Explain the fail-closed refusal, naming the version-skew case.
     *
     * The web assets are served from `~/.ppxai/web`, NOT from the running
     * binary's own tree (docs/lessons/web-assets-served-from-ppxai-home.md),
     * so an upgraded UI can easily be talking to an older server that has
     * no `GET /commands` at all and 404s it. That asymmetry is the most
     * likely reason a user sees this, so it is named explicitly.
     */
    _explainMissingRoster(cmd) {
        const err = this.app.commandRoster?.lastError;
        const why = err ? ` (last error: ${err})` : '';
        this.app.showError(
            `Refusing to run ${cmd}: the command roster (GET /commands) is unavailable${why}. ` +
            'Slash-command routing is server-declared data, so without it this client cannot ' +
            'tell which commands it must handle locally — and forwarding them blindly would ' +
            'send `/token set <value>` to the server, putting a secret in a request body and ' +
            'in the debug log. Most likely cause: VERSION SKEW — the web UI is served from ' +
            '~/.ppxai/web and can be newer than the running ppxai-server, which then has no ' +
            '/commands endpoint. Restart or upgrade the server and try again. Plain chat ' +
            'messages are unaffected.'
        );
    }

    /**
     * Run the bundled implementation of a roster-named `client_action`.
     *
     * An action the server names but this client does not implement is an
     * ERROR, never a silent forward: the whole point of `client_handled`
     * is that dispatch happens HERE (ADR 0007 §Decision).
     */
    async _dispatchClientAction(entry, args, input) {
        const action = CommandDispatcher.CLIENT_ACTIONS[entry.client_action];
        if (typeof action !== 'function') {
            this.app.showError(
                `/${entry.name} is declared client-handled (client_action ` +
                `"${entry.client_action}"), but this web client bundles no implementation ` +
                'for that action. Not forwarding it to the server — a client-handled ' +
                'command is never POSTed. Update the web client, or the server\'s ' +
                'CLIENT_ACTIONS declaration, so the two agree.'
            );
            return;
        }
        await action.call(this, { args, input, entry });
    }

    /**
     * Shared guard for the two controller-backed actions: the controller
     * classes are separate script tags, so a missing one must say so
     * rather than silently doing nothing (the old `this.tasks?.handle()`
     * swallowed the whole command).
     */
    async _viaController(controller, className, entry, args) {
        if (!controller) {
            this.app.showError(
                `/${entry.name} needs ${className}, which is not loaded in this page. ` +
                'Check that shared/' + className.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase() +
                '.js is present and loaded before shared/command-dispatcher.js.'
            );
            return;
        }
        await controller.handle(args);
    }

    /**
     * Item 40: `/token status|set|mint|clear` — bearer management for the
     * protected /v1 API surface.
     *
     * Security shape:
     * - `set` takes the value via a browser prompt(), which keeps the secret
     *   out of the composer entirely — out of the input history, out of the
     *   autocomplete buffer, and off the screen. An inline value is still
     *   accepted and, since ADR 0007 step 3a-sec, no longer leaks from this
     *   client: `set` is declared `sensitive` in Python, so the chat echo is
     *   masked before it is rendered or mirrored to POST /client-log, the
     *   composer buffer is never sent to POST /complete, and the line is not
     *   written to the persisted input history. The prompt form is still the
     *   one to recommend — it is the only one that never puts the secret on
     *   the screen or in a shoulder-surfable composer.
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
                    `🔑 Token stored (${masked(value)}) — typed inline. The value was masked in ` +
                    'the chat echo, kept out of the server debug log, out of autocomplete and out ' +
                    'of the input history, so it did not leave this page. Still prefer `/token ' +
                    'set` with no value (a prompt): it never puts the token on screen at all.');
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
     * /auto has three shapes (renamed from /agent in v1.19.1, ADR 0011):
     *   /auto            → status query (no mutation)
     *   /auto on|off     → toggle (REST path; existing toggleAgent)
     *   /auto <task>     → autonomous task (chat-shaped, /chat path)
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
            await this.app.streamChat(`/auto ${args}`);
            return;
        }
        // No args — show status via factory. The command is `auto`
        // (ADR 0011 renamed /agent with NO alias), so posting to
        // `/command/agent` here 404'd; fixed with ADR 0007 step 3a.
        await this._dispatchToFactory('auto', '');
    }

    /**
     * Send to POST /command/<name>, render the result, apply
     * side-effects, drain events[] through the SSE dispatcher.
     */
    async _dispatchToFactory(name, args) {
        let envelope;
        try {
            envelope = await this.app.apiClient.executeCommand(name, args, WEB_CLIENT_ID);
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


/**
 * The action registry — ADR 0007's "Python owns the NAME, the client
 * bundles the IMPLEMENTATION", in nine lines.
 *
 * Keys are `client_action` names from the Python `CLIENT_ACTIONS`
 * vocabulary (`ppxai/commands/factory.py`); values are the web
 * implementations. A name the roster sends that is absent here produces a
 * clear error (see `_dispatchClientAction`) — never a silent forward.
 *
 * Web implements the four actions the server declares for
 * `client_action_clients` including "web": token.manage, task.controller,
 * run.controller, auto.loop. The VSCode-only actions (`coding.stream`,
 * `coding.convert`, `preview.panel`, `help.augment`, `app.quit`) are
 * deliberately absent — the roster reports `dispatch === "server"` for
 * them when asked `?client=web`, so they never reach this table.
 *
 * `this` is the CommandDispatcher (each is invoked with `.call(this, …)`),
 * mirroring `SideEffectsHandler._handlers`.
 */
CommandDispatcher.CLIENT_ACTIONS = {
    // Item 40: the /v1 API bearer this client attaches. Its STATE is
    // client-side (localStorage + in-memory ApiClient), which is why the
    // command can only run here.
    'token.manage'({ args }) {
        return this._handleTokenCommand(args);
    },

    // Tool-capable tier: `/task …` — U2 direct launch + ls/get/watch/
    // respond/collect/resume/cancel. The whole arg string (verb + rest,
    // incl. quoted desc + flags) is handed to the controller, which
    // parses it; it drives /v1/agent/* directly.
    'task.controller'({ args, entry }) {
        return this._viaController(this.tasks, 'TaskController', entry, args);
    },

    // One-off tier (U3, ADR 0011): `/run …` — direct launch (grant decided
    // by server config) + kind-filtered lifecycle verbs. Replaced the
    // retired /agentrun + /agentruns (hard removal).
    'run.controller'({ args, entry }) {
        return this._viaController(this.runs, 'RunController', entry, args);
    },

    // The in-session autonomous loop (was /agent pre-v1.19.1). Three
    // shapes; see _dispatchAgent.
    'auto.loop'({ args, input }) {
        return this._dispatchAgent(args, input);
    },
};


// CommonJS export for tests; window-global for browser.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { CommandDispatcher, STREAMING_COMMANDS, WEB_CLIENT_ID };
} else if (typeof window !== 'undefined') {
    window.CommandDispatcher = CommandDispatcher;
}

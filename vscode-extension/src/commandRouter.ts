/**
 * CommandRouter — roster-driven slash-command routing (ADR 0007 step 3b).
 *
 * The VSCode counterpart of `ppxai/web/shared/command-dispatcher.js`'s
 * routing half. Before this module `chatPanel.ts::handleSlashCommand` was
 * a twelve-branch hardcoded `if (command === '…')` chain plus a
 * `CHAT_SHAPED_TASKS` map, and nothing anywhere recorded which client
 * handled what. Now the SERVER says, per command, whether THIS client
 * dispatches it (`dispatch === "client"`) and under which named
 * `client_action`; `RouterHost.actions` maps those names to the
 * implementations the extension bundles.
 *
 * Python owns the binding, the client owns the code — no executable ever
 * crosses the wire (ADR 0007, §Why this and not the alternatives; the
 * extension host runs with the developer's full privileges, so this is
 * the boundary that matters most in this client).
 *
 * Order inside `route()`, and why:
 *
 *   1. **ECHO**, redacted. The typed line reaches the transcript on a
 *      path that runs before routing is consulted, so the redaction has
 *      to be here, not inside a branch (ADR 0007 step 3a-sec).
 *   2. **FAIL-CLOSED GATE** — no roster, no dispatch. First thing
 *      `route()` can leave on, so a client talking to an unreachable or
 *      older server never forwards a slash command it cannot classify.
 *      `/token set <value>` carries a secret; forwarding it to
 *      `POST /command/token` would put that secret in a request body and
 *      in the server debug log (the leak fixed server-side in step 1b).
 *      There is deliberately NO hardcoded `/token` escape hatch — that
 *      would be a second roster again.
 *   3. `dispatch === "client"` → the bundled implementation named by the
 *      entry's `client_action`. An action the roster names that this
 *      client does not implement is an ERROR, never a silent forward.
 *   4. **LEGACY INTERCEPT** — see `LEGACY_INTERCEPTS` below.
 *   5. Everything else → `POST /command/<name>` via the v1 envelope.
 *
 * **No `vscode` import**, by design (same IoC shape as
 * `taskController.ts`): every collaborator arrives through `RouterHost`,
 * so the Node behavioural tests drive the REAL compiled module.
 */

import { CommandRoster, RosterEntry } from './commandRoster';


/** Client id this router speaks as — `?client=` and the POST body field. */
export const VSCODE_CLIENT_ID = 'vscode';


/**
 * Commands intercepted client-side WITHOUT a declared `client_action`,
 * by explicit owner decision ("do not bless debt").
 *
 * They hit bespoke REST endpoints through handlers extracted in the
 * v1.18.1 Phase-2 refactor; the code said *"full factory routing is a
 * later phase"* from then until ADR 0007 step 5. Declaring a
 * `client_action` for them would record the debt as architecture.
 * Instead they live here, named, so that step 5's parity fence can
 * baseline this exact list and only ever let it SHRINK — the same
 * discipline as `BASELINE` in tests/test_no_new_lazy_imports.py.
 *
 * **Step 5 (2026-09-21) shrank it from five to one.** `/tools`,
 * `/context`, `/ls` and `/tree` now route to `POST /command/<name>` like
 * every other server command, rendered by `CommandRenderer` and
 * reconciled by the envelope's `side_effects` + `events` — exactly what
 * the web client has always done with them.
 *
 * `/checkpoint` STAYS, and the reason is one subcommand:
 * `/checkpoint clear` irreversibly deletes every file-backend snapshot,
 * and this client is the only one that asks first
 * (`vscode.window.showWarningMessage(..., {modal: true})` in
 * `handlers/commands.ts`). `ppxai/commands/agent.py::_checkpoint_clear`
 * says so in a comment of its own — *"Interactive confirmation is handled
 * by old handler for now"* — and deletes unconditionally. Routing
 * `/checkpoint` through the envelope today would remove the only guard on
 * a destructive, unrecoverable operation. Expressing that guard on the
 * wire is possible in principle (`prompt_quick_pick` +
 * `command_to_resume` is already in the vocabulary and already handled by
 * `sideEffectsHandler.ts`), but neither TUI implements that side-effect,
 * so emitting it from Python would turn `/checkpoint clear` into a silent
 * no-op in Rich and Textual. That is a cross-client confirmation design,
 * not a VSCode routing change — owner's call, and until it is made this
 * row stays.
 *
 * DO NOT ADD TO THIS LIST. A new client-side command gets a
 * `client_action` in the Python registry.
 */
export const LEGACY_INTERCEPTS: readonly string[] = [
    'checkpoint',
];


/** What a bundled implementation receives. */
export interface ClientActionContext {
    /** Canonical command name from the roster (no leading slash). */
    name: string;
    /** Everything after the command, as one string. */
    args: string;
    /** Everything after the command, whitespace-split. */
    argv: string[];
    /** The raw typed line, including the leading slash. */
    input: string;
    /** The roster entry that selected this action. */
    entry: RosterEntry;
}

export type ClientAction = (ctx: ClientActionContext) => Promise<void> | void;

/** Everything the router needs from the panel. */
export interface RouterHost {
    /** The fetched roster (fail-closed when not loaded). */
    roster: CommandRoster;
    /**
     * `client_action` name → bundled implementation. Keys come from the
     * Python `CLIENT_ACTIONS` vocabulary (`ppxai/commands/factory.py`).
     */
    actions: Record<string, ClientAction>;
    /** Legacy name → implementation; keys must be `LEGACY_INTERCEPTS`. */
    legacy: Record<string, ClientAction>;
    /**
     * Render the typed line in the transcript. `text` is ALREADY
     * redacted; `sensitive` says whether anything was masked, and `raw`
     * is the unredacted line so the host can drop exactly that entry
     * from the input history. `raw` must never be rendered, logged or
     * sent anywhere — it exists only to identify what to forget.
     */
    echo(text: string, sensitive: boolean, raw: string): void;
    /** Show a refusal / routing error in the transcript. */
    showError(message: string): void;
    /** `POST /command/<name>` through the v1 envelope. */
    dispatchToFactory(name: string, args: string): Promise<void>;
}


/**
 * Everything the bundled implementations need from the chat panel.
 *
 * IoC, like `TaskBackend`/`TaskUi` in taskController.ts: the registry
 * below binds `client_action` NAMES to these operations, and
 * `chatPanel.ts` supplies the operations. That keeps the registry —
 * the thing ADR 0007 step 5's parity fence has to read — in a
 * `vscode`-free module the Node tests can drive directly.
 */
export interface PanelCommandOps {
    // --- declared client actions ---------------------------------------
    handleToken(args: string): Promise<void> | void;
    handleTask(args: string): Promise<void> | void;
    handleRun(args: string): Promise<void> | void;
    handleAuto(argv: string[]): Promise<void> | void;
    handleCodingTask(taskType: string, content: string): Promise<void> | void;
    handleConvert(argv: string[]): Promise<void> | void;
    handlePreview(argv: string[]): Promise<void> | void;
    showHelp(args: string): Promise<void> | void;

    // --- the acknowledged-legacy intercept (see LEGACY_INTERCEPTS) -----
    handleCheckpoint(argv: string[]): Promise<void> | void;

    // --- transcript + dispatch -----------------------------------------
    echo(text: string, sensitive: boolean, raw: string): void;
    showError(message: string): void;
    dispatchToFactory(name: string, args: string): Promise<void>;
}

type OpsAction = (ops: PanelCommandOps, ctx: ClientActionContext) => Promise<void> | void;

/**
 * The action registry — ADR 0007's "Python owns the NAME, the client
 * bundles the IMPLEMENTATION", in one table.
 *
 * Keys are `client_action` names from the Python `CLIENT_ACTIONS`
 * vocabulary (`ppxai/commands/factory.py`); values are the handlers this
 * extension already had, which used to sit behind a twelve-branch
 * `if (command === '…')` chain in `handleSlashCommand`. A name the roster
 * sends that is absent here produces a clear error — never a silent
 * forward. `app.quit` is deliberately absent: `/quit` is gated to
 * `clients={rich, textual}` (ending a GUI session is a UI workflow —
 * VSCode has Disconnect), so it is not served to this client at all and
 * the action can never be named.
 */
export const CLIENT_ACTIONS: Record<string, OpsAction> = {
    // Item 40: the /v1 API bearer this client attaches. Its STATE is
    // client-side (SecretStorage + the in-memory HttpClient), which is
    // why the command can only run here.
    'token.manage': (ops, ctx) => ops.handleToken(ctx.args),

    // Tool-capable tier (T8a): `/task …` drives /v1/agent/* directly and
    // never calls POST /command/task.
    'task.controller': (ops, ctx) => ops.handleTask(ctx.args),

    // One-off tier (U3, ADR 0011): `/run …`, same gears, kind=oneshot.
    'run.controller': (ops, ctx) => ops.handleRun(ctx.args),

    // The in-session autonomous loop (was /agent pre-v1.19.1).
    'auto.loop': (ops, ctx) => ops.handleAuto(ctx.argv),

    // ONE action shared by SIX commands (/generate /explain /test /docs
    // /debug /implement). The implementation receives the CANONICAL name
    // the roster resolved and passes it straight through as `task_type` —
    // which is what the deleted `CHAT_SHAPED_TASKS` map really did, since
    // every one of its entries was the identity `['x', 'x']`. Aliases
    // (`/g`, `/gen`, `/d`, `/impl`) now reach this path too; the map keyed
    // on canonical names only and silently forwarded them to the factory.
    'coding.stream': (ops, ctx) => ops.handleCodingTask(ctx.name, ctx.args),

    // Chat-shaped too, but with its own `<src> <dst> <code>` arg parsing,
    // which is why it keeps its own action name rather than folding into
    // coding.stream.
    'coding.convert': (ops, ctx) => ops.handleConvert(ctx.argv),

    // Client-native UX: /preview owns its own WebviewPanel.
    'preview.panel': (ops, ctx) => ops.handlePreview(ctx.argv),

    // Client-native UX: the factory's /help WRAPPED with this client's
    // keyboard shortcuts (see chatPanel.ts::showHelp for what it used to
    // do instead).
    'help.augment': (ops, ctx) => ops.showHelp(ctx.args),
};

/**
 * Implementations for `LEGACY_INTERCEPTS`. Keys must equal that list —
 * pinned by tests/test_client_handled_commands_contract.py and
 * tests/test_command_parity_fence.py.
 */
export const LEGACY_HANDLERS: Record<string, OpsAction> = {
    checkpoint: (ops, ctx) => ops.handleCheckpoint(ctx.argv),
};

/** Build the router for a chat panel: registry + roster + panel ops. */
export function buildCommandRouter(
    roster: CommandRoster, ops: PanelCommandOps,
): CommandRouter {
    const bind = (table: Record<string, OpsAction>): Record<string, ClientAction> => {
        const out: Record<string, ClientAction> = {};
        for (const name of Object.keys(table)) {
            out[name] = (ctx: ClientActionContext) => table[name](ops, ctx);
        }
        return out;
    };
    return new CommandRouter({
        roster,
        actions: bind(CLIENT_ACTIONS),
        legacy: bind(LEGACY_HANDLERS),
        echo: (text, sensitive, raw) => ops.echo(text, sensitive, raw),
        showError: (message) => ops.showError(message),
        dispatchToFactory: (name, args) => ops.dispatchToFactory(name, args),
    });
}


export class CommandRouter {
    private _host: RouterHost;

    constructor(host: RouterHost) {
        this._host = host;
    }

    /**
     * Route one slash-command line.
     *
     * @param input raw user input including the leading `/`
     */
    async route(input: string): Promise<void> {
        const trimmed = input.trim();
        const parts = trimmed.split(/\s+/);
        const typed = parts[0].replace(/^\/+/, '').toLowerCase();
        const argv = parts.slice(1);
        const args = argv.join(' ');

        // (1) The echo is REDACTED before it is rendered or remembered.
        // The rule comes from the roster (`sensitive` per subcommand),
        // never from a hardcoded name, and it fails closed with no roster.
        const verdict = this._host.roster.classify(input);
        this._host.echo(
            verdict.sensitive ? this._host.roster.redact(input) : input,
            verdict.sensitive,
            input,
        );

        // (2) Fail closed. Routing is server-declared data; without it
        // this client cannot tell a client-handled command from a
        // forwardable one, and guessing leaks secrets.
        const roster = await this._readyRoster();
        if (!roster) {
            this._explainMissingRoster(typed);
            return;
        }

        // (3)/(4)/(5) Data-driven routing. `resolve` handles aliases, so
        // `/cat` reaches `show`'s entry and `/gen` reaches `generate`'s
        // without a second alias table.
        const entry = roster.resolve(typed);
        const name = entry ? entry.name : typed;
        const ctx: ClientActionContext = {
            name, args, argv, input,
            entry: entry || { name },
        };

        if (entry && entry.dispatch === 'client') {
            await this._dispatchClientAction(entry, ctx);
            return;
        }

        const legacy = this._host.legacy[name];
        if (legacy && LEGACY_INTERCEPTS.indexOf(name) !== -1) {
            await legacy(ctx);
            return;
        }

        // Default: factory dispatch. A resolved entry contributes its
        // CANONICAL name; an unknown name is sent as typed so the server
        // produces the 404 whose message the user is expecting.
        await this._host.dispatchToFactory(name, args);
    }

    /**
     * Return the loaded roster, or null.
     *
     * Retries the fetch once, inline, when nothing is loaded yet: a
     * client that opened before the server was reachable should self-heal
     * on the next command rather than staying wedged until a reload.
     */
    private async _readyRoster(): Promise<CommandRoster | null> {
        const roster = this._host.roster;
        if (!roster) { return null; }
        if (roster.isLoaded()) { return roster; }
        await roster.load();
        return roster.isLoaded() ? roster : null;
    }

    /**
     * Explain the fail-closed refusal, naming the version-skew case.
     *
     * The extension and the server version independently — the VSIX comes
     * from the marketplace or a local install while `ppxai-server` is
     * whatever binary is on PATH — so an upgraded extension talking to an
     * older server that 404s `GET /commands` is a realistic production
     * state, and the most likely reason a user sees this.
     */
    private _explainMissingRoster(name: string): void {
        const err = this._host.roster?.lastError;
        const why = err ? ` (last error: ${err})` : '';
        this._host.showError(
            `Refusing to run /${name}: the command roster (GET /commands) is unavailable${why}. ` +
            'Slash-command routing is server-declared data, so without it this extension cannot ' +
            'tell which commands it must handle locally — and forwarding them blindly would ' +
            'send `/token set <value>` to the server, putting a secret in a request body and ' +
            'in the debug log. Most likely cause: VERSION SKEW — the ppxai extension and the ' +
            'ppxai-server binary upgrade independently, and a server older than v1.19.3 has no ' +
            '/commands endpoint at all. Start or upgrade the server (click the server badge) ' +
            'and try again. Plain chat messages are unaffected.',
        );
    }

    /**
     * Run the bundled implementation of a roster-named `client_action`.
     *
     * An action the server names but this client does not implement is an
     * ERROR, never a silent forward: the whole point of client dispatch is
     * that it happens HERE (ADR 0007 §Decision).
     */
    private async _dispatchClientAction(
        entry: RosterEntry, ctx: ClientActionContext,
    ): Promise<void> {
        const action = entry.client_action
            ? this._host.actions[entry.client_action]
            : undefined;
        if (typeof action !== 'function') {
            this._host.showError(
                `/${entry.name} is declared client-dispatched (client_action ` +
                `"${entry.client_action}"), but this VSCode extension bundles no ` +
                'implementation for that action. Not forwarding it to the server — a ' +
                'client-dispatched command is never POSTed. Update the extension, or the ' +
                "server's CLIENT_ACTIONS declaration, so the two agree.",
            );
            return;
        }
        await action(ctx);
    }
}

/**
 * CommandRoster — the server-declared command catalog (ADR 0007 step 3b).
 *
 * The VSCode half of what step 3a did for the web client. Before this
 * module the extension carried its OWN copy of every command:
 * `src/shared/commands.ts`, 31 hand-written entries — the SIXTH roster the
 * ADR counts, and the one with the worst drift: it listed neither `/run`,
 * `/task` nor `/token`, all three of which `chatPanel.ts` intercepted at
 * runtime, so VSCode's own `/help` and autocomplete never offered them.
 *
 * Now there is ONE declaration (the Python `CommandFactory`) and this is
 * its client-side cache: fetched from `GET /commands?client=vscode` once
 * the backend is reachable, refetched when the server signals a change
 * (`refresh_command_roster` side effect, emitted by `/reload`).
 *
 * Payload shape (`CommandFactory.roster("vscode")`):
 *
 *     {"version": <int>, "commands": [{
 *         name, aliases, description, usage, category, hidden,
 *         subcommands: [{name, description, sensitive}],
 *         clients, client_action, client_action_clients, client_handled,
 *         dispatch: "client" | "server"
 *     }, ...]}
 *
 * `dispatch` is computed FOR THIS CLIENT by the server, which is what
 * makes `CommandRouter` routing data rather than a hardcoded `if`-chain.
 * Nothing callable ever crosses the wire: Python owns the NAME→action
 * binding (`client_action`), the extension bundles the IMPLEMENTATION.
 * That split matters more here than on web — the extension host is a Node
 * process with the developer's full privileges, so server-supplied code
 * would be remote code execution by design (ADR 0007, §Why this and not
 * the alternatives).
 *
 * Failure posture is deliberate: a fetch that fails leaves `isLoaded()`
 * false and the router FAILS CLOSED (it refuses to dispatch rather than
 * forwarding slash commands blind — see commandRouter.ts). A fetch that
 * fails while a roster is already held keeps the held one; a transient
 * refresh must never downgrade a working client.
 *
 * ADR 0007 step 3a-sec — SECRETS. Each subcommand carries a `sensitive`
 * flag (Python's `CommandSpec.sensitive_subcommands`), so this module can
 * answer "does this typed line carry a secret?" WITHOUT any client ever
 * hardcoding `/token` or `set`. `isSensitive()` / `redact()` below are the
 * ONE client-side implementation of that rule; the webview echo, the
 * `POST /complete` call and the webview's ArrowUp history all go through
 * them. Same rule, same declaration, as the server's
 * `CommandFactory.redact_sensitive` and web's `CommandRoster` — the three
 * truth tables are pinned against each other by
 * tests/test_vscode_command_roster_behavior.py.
 *
 * **No `vscode` import.** Like `taskController.ts`, this module is
 * dependency-injected (the backend slice is an interface), which is what
 * lets the Node behavioural tests drive the REAL compiled module instead
 * of reading its source text.
 */

/** Fixed mask — never derived from the secret (a length would leak). */
export const SENSITIVE_MASK = '••••';

/** The `> ` echo marker a transcript may prepend. */
const ECHO_PREFIX = /^\s*>+\s*/;

/** `<ws>/<command><ws><first argument>` — token-based, so it is linear. */
const SLASH_HEAD = /^(\s*)\/(\S+)(\s+)(\S+)/;


/** One `subcommands[]` entry as the roster publishes it. */
export interface RosterSubcommand {
    name: string;
    description?: string;
    sensitive?: boolean;
}

/** One canonical command as the roster publishes it. */
export interface RosterEntry {
    name: string;
    aliases?: string[];
    description?: string;
    usage?: string;
    category?: string;
    hidden?: boolean;
    subcommands?: RosterSubcommand[];
    clients?: string[] | null;
    client_action?: string | null;
    client_action_clients?: string[] | null;
    client_handled?: boolean;
    dispatch?: 'client' | 'server';
}

/** `GET /commands` payload. */
export interface RosterPayload {
    version?: number;
    commands?: RosterEntry[];
}

/**
 * The httpClient slice this roster drives (IoC — see `TaskBackend` in
 * taskController.ts for the same idiom).
 */
export interface RosterBackend {
    getCommandRoster(client: string): Promise<RosterPayload>;
}

/** What `classify()` answers. */
export interface SensitivityVerdict {
    /** True when everything from `cut` on must not leave the client. */
    sensitive: boolean;
    /** Index the mask replaces from, or -1 when nothing is sensitive. */
    cut: number;
}

interface ParsedLine {
    name: string;
    sub: string;
    nameEnd: number;
    subEnd: number;
    hasValue: boolean;
}


/**
 * Split a typed line into the pieces the sensitivity rule needs.
 *
 * Mirrors `CommandFactory.redact_sensitive`'s parse exactly, including
 * its two decisions: the leading `> ` echo marker is tolerated, and the
 * separators are any run of whitespace (tabs included). Offsets are
 * computed from the group lengths rather than a `/d` regex so the module
 * runs on older engines.
 *
 * Returns null when the text is not a `/command <arg>` line at all
 * (plain chat, a bare `/token`, '').
 */
export function parseCommandLine(text: unknown): ParsedLine | null {
    if (typeof text !== 'string') { return null; }
    const body = text.replace(ECHO_PREFIX, '');
    const lead = text.length - body.length;
    const m = SLASH_HEAD.exec(body);
    if (!m) { return null; }
    const nameEnd = lead + m[1].length + 1 + m[2].length;
    const subEnd = nameEnd + m[3].length + m[4].length;
    return {
        name: m[2],
        sub: m[4],
        nameEnd,
        subEnd,
        hasValue: text.slice(subEnd).trim().length > 0,
    };
}

function maskFrom(text: string, cut: number): string {
    return `${text.slice(0, cut)} ${SENSITIVE_MASK}`;
}


export class CommandRoster {
    private _backend: RosterBackend;
    private _client: string;
    private _byName: Map<string, RosterEntry> = new Map();
    private _loaded = false;
    private _inflight: Promise<boolean> | null = null;

    /** Roster version as served, or null when nothing is held. */
    public version: number | null = null;
    /** Entries as served (already sorted by name). */
    public commands: RosterEntry[] = [];
    /** Message of the last failed fetch, for the refusal explanation. */
    public lastError: string | null = null;

    /**
     * @param backend httpClient slice exposing `getCommandRoster`
     * @param client  client id sent as `?client=` (vscode here)
     */
    constructor(backend: RosterBackend, client = 'vscode') {
        this._backend = backend;
        this._client = client;
    }

    /** True once a roster has been successfully fetched at least once. */
    isLoaded(): boolean {
        return this._loaded;
    }

    /**
     * Drop the held roster.
     *
     * Called when the backend connection goes away (server stopped or
     * disconnected): the roster describes a SERVER, and a reconnect may
     * reach a different one. Keeping a stale roster across a restart
     * would route by a snapshot nobody promised is still true — so the
     * client reverts to the fail-closed state until it refetches.
     */
    unload(): void {
        this._loaded = false;
        this.commands = [];
        this._byName = new Map();
        this.version = null;
    }

    /**
     * Fetch (or refetch) the roster.
     *
     * Concurrent calls share one in-flight request — backend init and a
     * `refresh_command_roster` side effect arriving together must not
     * produce two GETs.
     *
     * @returns whether a roster is held afterwards.
     */
    async load(): Promise<boolean> {
        if (this._inflight) { return this._inflight; }
        this._inflight = this._fetch();
        try {
            return await this._inflight;
        } finally {
            this._inflight = null;
        }
    }

    private async _fetch(): Promise<boolean> {
        try {
            const payload = await this._backend.getCommandRoster(this._client);
            this._ingest(payload);
            this.lastError = null;
            return true;
        } catch (e: any) {
            this.lastError = e?.message ?? String(e);
            console.warn('[ppxai CommandRoster] GET /commands failed:', this.lastError);
            // Keep whatever we already had — a failed REFRESH must not
            // un-load a working client (and must not open the fail-closed
            // gate either, which is why the flag is returned, not `false`).
            return this._loaded;
        }
    }

    private _ingest(payload: RosterPayload | null | undefined): void {
        const commands = Array.isArray(payload?.commands) ? payload!.commands! : [];
        const byName = new Map<string, RosterEntry>();
        for (const entry of commands) {
            if (!entry || typeof entry.name !== 'string') { continue; }
            byName.set(entry.name.toLowerCase(), entry);
            // Aliases are a FIELD on the canonical entry, never a row of
            // their own — restating them was the commands.ts duplication.
            for (const alias of (entry.aliases || [])) {
                if (typeof alias === 'string') { byName.set(alias.toLowerCase(), entry); }
            }
        }
        this.commands = commands;
        this._byName = byName;
        this.version = (payload && typeof payload.version === 'number')
            ? payload.version : null;
        this._loaded = true;
    }

    /**
     * Resolve a typed command name to its roster entry.
     *
     * Accepts `/cat`, `cat`, `/CAT` alike, and resolves ALIASES to their
     * canonical entry (the endpoint publishes `exit` inside `/quit`'s
     * `aliases`, not as a row). This is also why `/g`, `/gen`, `/d` and
     * `/impl` now reach the coding-task path at all — the hand-written
     * `CHAT_SHAPED_TASKS` map keyed on canonical names only and silently
     * forwarded the aliases to the factory.
     *
     * @returns the entry, or null when the roster does not declare it for
     *   this client.
     */
    resolve(name: unknown): RosterEntry | null {
        if (typeof name !== 'string') { return null; }
        const key = name.trim().replace(/^\/+/, '').toLowerCase();
        if (!key) { return null; }
        return this._byName.get(key) || null;
    }

    /** Every canonical entry, as served. */
    all(): RosterEntry[] {
        return this.commands;
    }

    /**
     * Classify a typed line: does it carry a secret, and where does the
     * secret start?
     *
     * The single place the rule lives on this client. Two modes:
     *
     * - **Roster loaded** — data-driven: resolve the command (aliases
     *   included), read which of its subcommands the SERVER flagged
     *   `sensitive`, and require an actual value after one of them. So
     *   `/token se` still completes to `set`, `/token set` alone is
     *   harmless, and `/token status x` is not touched.
     * - **No roster — FAIL CLOSED**, consistently with the router's
     *   gate: the args of ANY slash command are treated as secret,
     *   because without the declaration this client cannot tell which
     *   ones are. The COMMAND NAME is kept (it is not a secret and the
     *   refusal message needs it); everything after it is masked.
     *
     * Case-insensitive on both the command and the subcommand, matching
     * `CommandFactory.redact_sensitive` — and not cosmetically: the
     * router lowercases the command and `handleTokenCommand` lowercases
     * the verb, so `/TOKEN SET abc` really does store a token.
     */
    classify(input: unknown): SensitivityVerdict {
        const parsed = parseCommandLine(input);
        if (!parsed) { return { sensitive: false, cut: -1 }; }
        if (!this._loaded) { return { sensitive: true, cut: parsed.nameEnd }; }
        const entry = this.resolve(parsed.name);
        if (!entry) { return { sensitive: false, cut: -1 }; }
        const flagged = (entry.subcommands || [])
            .filter((s) => s && s.sensitive && typeof s.name === 'string')
            .map((s) => s.name.toLowerCase());
        if (flagged.indexOf(parsed.sub.toLowerCase()) === -1 || !parsed.hasValue) {
            return { sensitive: false, cut: -1 };
        }
        return { sensitive: true, cut: parsed.subEnd };
    }

    /** True when `input`'s arguments must not leave the client. */
    isSensitive(input: unknown): boolean {
        return this.classify(input).sensitive;
    }

    /**
     * `input` with any secret replaced by a fixed mask; unchanged when
     * there is none. `/token set abc` -> `/token set ••••`, and with the
     * echo marker `> /token set abc` -> `> /token set ••••`.
     */
    redact(input: unknown): string {
        const { sensitive, cut } = this.classify(input);
        if (!sensitive) { return typeof input === 'string' ? input : ''; }
        return maskFrom(input as string, cut);
    }

    /**
     * The fail-closed redaction for a client with no CommandRoster
     * INSTANCE at all (not merely an unloaded one). Same parse, same
     * mask — kept here so there is still exactly one implementation.
     */
    static redactWithoutRoster(input: unknown): string {
        const parsed = parseCommandLine(input);
        if (!parsed) { return typeof input === 'string' ? input : ''; }
        return maskFrom(input as string, parsed.nameEnd);
    }
}

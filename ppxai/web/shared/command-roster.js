/**
 * CommandRoster — the server-declared command catalog (ADR 0007 step 3a).
 *
 * Before this module the web client carried its OWN copy of every command:
 * `shared/commands.js` (376 hand-written lines) plus an inline fallback
 * catalog in `app.js`. Both drifted from the Python `CommandFactory` — nine
 * canonical commands were missing, `/token`'s description said something
 * different, and aliases (`/cat`, `/sh`, `/term`) were restated as
 * standalone entries instead of being fields on their canonical spec.
 *
 * Now there is ONE declaration (the Python registry) and this is its
 * client-side cache: fetched once at startup from
 * `GET /commands?client=web`, refetched when the server signals a change
 * (`refresh_command_roster` side effect, emitted by `/reload`).
 *
 * Payload shape (`CommandFactory.roster()`):
 *
 *     {"version": <int>, "commands": [{
 *         name, aliases, description, usage, category, hidden,
 *         subcommands: [{name, description}],
 *         clients, client_action, client_action_clients, client_handled,
 *         dispatch: "client" | "server"
 *     }, ...]}
 *
 * `dispatch` is computed FOR THIS CLIENT by the server, which is what makes
 * `CommandDispatcher` routing data rather than a hardcoded `if`-chain.
 * Nothing callable ever crosses the wire: Python owns the NAME→action
 * binding (`client_action`), the client bundles the IMPLEMENTATION.
 *
 * Failure posture is deliberate: a fetch that fails leaves `isLoaded()`
 * false and the dispatcher FAILS CLOSED (it refuses to dispatch rather
 * than forwarding slash commands blind — see command-dispatcher.js). A
 * fetch that fails while a roster is already held keeps the held one; a
 * transient refresh must never downgrade a working client.
 *
 * ADR 0007 step 3a-sec — SECRETS. Each subcommand carries a `sensitive`
 * flag (Python's `CommandSpec.sensitive_subcommands`), so this module can
 * answer "does this typed line carry a secret?" WITHOUT any client ever
 * hardcoding `/token` or `set`. `isSensitive()` / `redact()` below are the
 * ONE client-side implementation of that rule; the chat echo, the
 * `POST /client-log` mirror, `POST /complete` and the persisted input
 * history all go through them. Same rule, same declaration, as the
 * server's `CommandFactory.redact_sensitive`.
 */

/** Fixed mask — never derived from the secret (a length would leak). */
const SENSITIVE_MASK = '\u2022\u2022\u2022\u2022';

/** The `> ` chat-echo marker `app.showSystemMessage` prepends. */
const ECHO_PREFIX = /^\s*>+\s*/;

/** `<ws>/<command><ws><first argument>` — token-based, so it is linear. */
const SLASH_HEAD = /^(\s*)\/(\S+)(\s+)(\S+)/;

/**
 * Split a typed line into the pieces the sensitivity rule needs.
 *
 * Mirrors `CommandFactory.redact_sensitive`'s parse exactly, including
 * its two decisions: the leading `> ` echo marker is tolerated, and the
 * separators are any run of whitespace (tabs included). Offsets are
 * computed from the group lengths rather than a `/d` regex so the module
 * runs on older engines.
 *
 * @returns {{name: string, sub: string, nameEnd: number, subEnd: number,
 *            hasValue: boolean}|null} null when the text is not a
 *   `/command <arg>` line at all (plain chat, a bare `/token`, '').
 */
function parseCommandLine(text) {
    if (typeof text !== 'string') return null;
    const body = text.replace(ECHO_PREFIX, '');
    const lead = text.length - body.length;
    const m = SLASH_HEAD.exec(body);
    if (!m) return null;
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

function maskFrom(text, cut) {
    return `${text.slice(0, cut)} ${SENSITIVE_MASK}`;
}


class CommandRoster {
    /**
     * @param {object} apiClient - shared ApiClient (needs getCommandRoster)
     * @param {string} client    - client id sent as `?client=` (web here)
     */
    constructor(apiClient, client = 'web') {
        this.apiClient = apiClient;
        this.client = client;
        this.version = null;
        this.commands = [];
        this.lastError = null;
        this._byName = new Map();   // canonical AND alias -> entry
        this._loaded = false;
        this._inflight = null;
    }

    /** True once a roster has been successfully fetched at least once. */
    isLoaded() {
        return this._loaded;
    }

    /**
     * Fetch (or refetch) the roster.
     *
     * Concurrent calls share one in-flight request — app startup and a
     * `refresh_command_roster` side-effect arriving together must not
     * produce two GETs.
     *
     * @returns {Promise<boolean>} whether a roster is held afterwards.
     */
    async load() {
        if (this._inflight) return this._inflight;
        this._inflight = this._fetch();
        try {
            return await this._inflight;
        } finally {
            this._inflight = null;
        }
    }

    async _fetch() {
        try {
            const payload = await this.apiClient.getCommandRoster(this.client);
            this._ingest(payload);
            this.lastError = null;
            return true;
        } catch (e) {
            this.lastError = e?.message || String(e);
            console.warn('[CommandRoster] GET /commands failed:', this.lastError);
            // Keep whatever we already had — a failed REFRESH must not
            // un-load a working client (and must not open the fail-closed
            // gate either, which is why the flag is returned, not `false`).
            return this._loaded;
        }
    }

    _ingest(payload) {
        const commands = Array.isArray(payload?.commands) ? payload.commands : [];
        const byName = new Map();
        for (const entry of commands) {
            if (!entry || typeof entry.name !== 'string') continue;
            byName.set(entry.name.toLowerCase(), entry);
            // Aliases are a FIELD on the canonical entry, never a row of
            // their own — restating them was the commands.js duplication.
            for (const alias of (entry.aliases || [])) {
                if (typeof alias === 'string') byName.set(alias.toLowerCase(), entry);
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
     * `aliases`, not as a row).
     *
     * @param {string} name
     * @returns {object|null} the entry, or null when the roster does not
     *   declare it for this client.
     */
    resolve(name) {
        if (typeof name !== 'string') return null;
        const key = name.trim().replace(/^\/+/, '').toLowerCase();
        if (!key) return null;
        return this._byName.get(key) || null;
    }

    /** Every canonical entry, as served (already sorted by name). */
    all() {
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
     * - **No roster — FAIL CLOSED**, consistently with the dispatcher's
     *   gate (step 3a): the args of ANY slash command are treated as
     *   secret, because without the declaration this client cannot tell
     *   which ones are. The COMMAND NAME is kept (it is not a secret and
     *   the refusal message needs it); everything after it is masked.
     *
     * Case-insensitive on both the command and the subcommand, matching
     * `CommandFactory.redact_sensitive` — and not cosmetically: the
     * dispatcher lowercases the command and `_handleTokenCommand`
     * lowercases the verb, so `/TOKEN SET abc` really does store a token.
     *
     * @param {string} input
     * @returns {{sensitive: boolean, cut: number}}
     */
    classify(input) {
        const parsed = parseCommandLine(input);
        if (!parsed) return { sensitive: false, cut: -1 };
        if (!this._loaded) return { sensitive: true, cut: parsed.nameEnd };
        const entry = this.resolve(parsed.name);
        if (!entry) return { sensitive: false, cut: -1 };
        const flagged = (entry.subcommands || [])
            .filter((s) => s && s.sensitive && typeof s.name === 'string')
            .map((s) => s.name.toLowerCase());
        if (!flagged.includes(parsed.sub.toLowerCase()) || !parsed.hasValue) {
            return { sensitive: false, cut: -1 };
        }
        return { sensitive: true, cut: parsed.subEnd };
    }

    /** True when `input`'s arguments must not leave the page. */
    isSensitive(input) {
        return this.classify(input).sensitive;
    }

    /**
     * `input` with any secret replaced by a fixed mask; unchanged when
     * there is none. `/token set abc` -> `/token set ••••`, and with the
     * echo marker `> /token set abc` -> `> /token set ••••`.
     */
    redact(input) {
        const { sensitive, cut } = this.classify(input);
        return sensitive ? maskFrom(input, cut) : input;
    }
}

/**
 * The fail-closed redaction for a page with no CommandRoster INSTANCE at
 * all (not merely an unloaded one). Same parse, same mask — kept here so
 * there is still exactly one implementation.
 */
CommandRoster.redactWithoutRoster = function redactWithoutRoster(input) {
    const parsed = parseCommandLine(input);
    return parsed ? maskFrom(input, parsed.nameEnd) : input;
};


// CommonJS export for tests; window-global for browser.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { CommandRoster, SENSITIVE_MASK, parseCommandLine };
} else if (typeof window !== 'undefined') {
    window.CommandRoster = CommandRoster;
}

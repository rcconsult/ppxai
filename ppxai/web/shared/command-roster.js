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
 */
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
}


// CommonJS export for tests; window-global for browser.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { CommandRoster };
} else if (typeof window !== 'undefined') {
    window.CommandRoster = CommandRoster;
}

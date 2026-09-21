/**
 * SchemaGuard — does the SERVER we just connected to declare the AppState
 * shape this extension was COMPILED against?
 *
 * The data path has been derived from `ppxai/engine/app_state_schema.json`
 * since v1.17.4, and since 2026-09-21 so has the TYPE path
 * (`appState.generated.ts`). Both derivations happen at BUILD time. The
 * one case neither covers is the one that actually ships: extension
 * version X talking to `ppxai-server` version Y. The two version
 * independently — the extension is installed from a VSIX, the server from
 * pip/PyInstaller — so this is a realistic production state, not a
 * theoretical one.
 *
 * `GET /schema/app-state` has existed since v1.17.4 with no client
 * consumer at all (recorded as an open finding in ADR 0007). This module
 * is that consumer.
 *
 * **Posture — deliberately the OPPOSITE of `commandRoster.ts`.** The
 * roster fails CLOSED: with no roster the router refuses to dispatch,
 * because forwarding an unclassified slash command can leak a secret.
 * Nothing comparable is at stake here, and two facts make failing closed
 * actively wrong for state:
 *
 *   - `AppState` is constructed as a field initialiser on the chat panel,
 *     long before a server exists to ask. It already has a complete,
 *     correct bundled schema; there is nothing to withhold.
 *   - A server too old to serve the endpoint (404) is a perfectly usable
 *     server. Blocking chat over an unverifiable diagnostic would be a
 *     self-inflicted outage.
 *
 * So: a failure is logged once and the extension carries on with the
 * bundled schema.
 *
 * **`version` is NOT the signal.** The canonical schema's `version` string
 * has read `"1.0"` since the file was created (`86adf127`) and was not
 * bumped by any of the five commits that added or changed fields since —
 * `last_message_role`, `agent_beat`, `model_supports_vision`,
 * `background_agents`, `estimated_cost`. Treating a version difference as
 * the compatibility verdict would therefore report nothing at all. The
 * verdict is computed from the FIELDS; the versions are reported in the
 * message when they differ, as context for whoever has to fix it.
 *
 * **No `vscode` import**, same IoC shape as `commandRoster.ts` /
 * `taskController.ts`: the host injects the four things that touch the
 * editor or the store (adopt, reset, log, warnUser). That is what lets
 * `tests/test_vscode_schema_guard_behavior.py` drive the REAL compiled
 * module under plain Node.
 */

/** One field entry as the canonical schema declares it. */
export interface SchemaFieldSpec {
    client: string;
    type: string;
    default: unknown;
    group?: string;
    doc?: string;
}

/** `GET /schema/app-state` payload (and the bundled copy's shape). */
export interface SchemaLike {
    version?: string;
    description?: string;
    fields?: Record<string, SchemaFieldSpec>;
}

/**
 * What the comparison concluded.
 *
 * - `identical`    — same field names, same `client` names, same types.
 * - `extra-only`   — the server declares fields this build does not know.
 *                    Harmless skew (newer server): adopt and move on.
 * - `incompatible` — a field this build was COMPILED against is missing
 *                    on the server, or its `type`/`client` name differs.
 *                    This is the broken guarantee; the user is told.
 * - `unverified`   — the endpoint 404'd or the fetch failed. Says nothing
 *                    about compatibility either way.
 */
export type SchemaVerdict = 'identical' | 'extra-only' | 'incompatible' | 'unverified';

/** One compiled-against field whose declaration changed on the server. */
export interface ChangedField {
    /** Python (snake_case) field name. */
    field: string;
    /** What changed: 'type', 'client', or 'type+client'. */
    what: string;
    bundled: string;
    server: string;
}

export interface SchemaDiff {
    verdict: SchemaVerdict;
    /** Python names the server declares and this build does not know. */
    extra: string[];
    /** Python names this build was compiled against, absent on the server. */
    missing: string[];
    /** Compiled-against fields whose `type` or `client` name differs. */
    changed: ChangedField[];
    /** Server field specs for `extra`, ready to hand to `AppState.adoptFields`. */
    adoptable: Record<string, SchemaFieldSpec>;
    bundledVersion: string | null;
    serverVersion: string | null;
    /** True when the two `version` strings differ. Never the verdict — see header. */
    versionDiffers: boolean;
    /** Why the check could not run, when `verdict === 'unverified'`. */
    error: string | null;
}

/** The httpClient slice this guard drives (IoC — see `RosterBackend`). */
export interface SchemaGuardBackend {
    getAppStateSchema(): Promise<SchemaLike>;
}

/**
 * Everything that touches the editor or the store, injected.
 *
 * `serverVersion` is consulted ONLY when composing an incompatibility
 * message, so the happy path costs no extra request.
 */
export interface SchemaGuardHost {
    /** Teach the live store about fields a newer server declares. */
    adopt(fields: Record<string, SchemaFieldSpec>): string[];
    /** Forget every previously adopted field. */
    resetAdopted(): void;
    /** Developer-visible breadcrumb (console / output channel). */
    log(message: string): void;
    /** USER-visible, modal-ish notification. Reserved for `incompatible`. */
    warnUser(message: string): void;
    /** This build's version, for the message. */
    extensionVersion?: string;
    /** Lazily resolved server version, for the message. Never required. */
    serverVersion?(): Promise<string | null>;
}


function fieldsOf(schema: SchemaLike | null | undefined): Record<string, SchemaFieldSpec> {
    const fields = schema && schema.fields;
    return (fields && typeof fields === 'object') ? fields : {};
}

/**
 * Compare a bundled schema with a server's, field by field.
 *
 * Pure: no I/O, no logging, no side effects. `verdict` is derived from
 * field-level facts only — `versionDiffers` is reported, never decisive.
 */
export function compareSchemas(
    bundled: SchemaLike | null | undefined,
    server: SchemaLike | null | undefined,
): SchemaDiff {
    const mine = fieldsOf(bundled);
    const theirs = fieldsOf(server);

    const extra: string[] = [];
    const missing: string[] = [];
    const changed: ChangedField[] = [];
    const adoptable: Record<string, SchemaFieldSpec> = {};

    for (const name of Object.keys(mine)) {
        const ours = mine[name];
        const remote = theirs[name];
        if (!remote) {
            missing.push(name);
            continue;
        }
        const parts: string[] = [];
        if (String(ours.type) !== String(remote.type)) { parts.push('type'); }
        if (String(ours.client) !== String(remote.client)) { parts.push('client'); }
        if (parts.length > 0) {
            changed.push({
                field: name,
                what: parts.join('+'),
                bundled: `${ours.client}: ${ours.type}`,
                server: `${remote.client}: ${remote.type}`,
            });
        }
    }

    for (const name of Object.keys(theirs)) {
        if (!(name in mine)) {
            extra.push(name);
            adoptable[name] = theirs[name];
        }
    }

    extra.sort();
    missing.sort();
    changed.sort((a, b) => (a.field < b.field ? -1 : a.field > b.field ? 1 : 0));

    const bundledVersion = (bundled && typeof bundled.version === 'string')
        ? bundled.version : null;
    const serverVersion = (server && typeof server.version === 'string')
        ? server.version : null;

    const broken = missing.length > 0 || changed.length > 0;
    const verdict: SchemaVerdict =
        broken ? 'incompatible' : (extra.length > 0 ? 'extra-only' : 'identical');

    return {
        verdict,
        extra,
        missing,
        changed,
        adoptable,
        bundledVersion,
        serverVersion,
        versionDiffers: bundledVersion !== serverVersion,
        error: null,
    };
}

/** `a, b and c` — so the message reads as a sentence, not a dump. */
function listOf(names: string[]): string {
    if (names.length === 1) { return names[0]; }
    return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

/**
 * The USER-visible message for an incompatible schema.
 *
 * Names the two versions (so the reader knows which side to move), the
 * exact fields (so the report is actionable), and what still works (so
 * nobody restarts the editor hoping it helps).
 */
export function describeIncompatibility(
    diff: SchemaDiff,
    extensionVersion: string | null,
    serverVersion: string | null,
): string {
    const sides = [
        `extension ${extensionVersion || 'unknown'}`,
        `server ${serverVersion || 'unknown'}`,
    ].join(' vs ');
    const parts: string[] = [
        `ppxai: this server declares a different AppState shape than the ` +
        `extension was built against (${sides}).`,
    ];
    if (diff.missing.length > 0) {
        parts.push(
            `Missing on the server: ${listOf(diff.missing)}.`
        );
    }
    for (const c of diff.changed) {
        parts.push(
            `Changed: ${c.field} (${c.what}) — built against "${c.bundled}", ` +
            `server says "${c.server}".`
        );
    }
    if (diff.extra.length > 0) {
        parts.push(`Also new on the server: ${listOf(diff.extra)}.`);
    }
    if (diff.versionDiffers) {
        parts.push(
            `Schema version ${diff.bundledVersion || '?'} vs ` +
            `${diff.serverVersion || '?'}.`
        );
    }
    parts.push(
        `Those fields keep working with the extension's bundled defaults; ` +
        `update the extension or the server so the two match.`
    );
    return parts.join(' ');
}


/**
 * Fetches the connected server's schema once per connection and acts on
 * the diff. Stateful only in what it has already said — the diff itself
 * is recomputed from scratch every time.
 */
export class SchemaGuard {
    private _backend: SchemaGuardBackend;
    private _bundled: SchemaLike;
    private _host: SchemaGuardHost;

    /** Set once this connection has been reported on (any verdict). */
    private _announced = false;
    /** The last diff, for diagnostics and tests. */
    public last: SchemaDiff | null = null;

    constructor(backend: SchemaGuardBackend, bundled: SchemaLike, host: SchemaGuardHost) {
        this._backend = backend;
        this._bundled = bundled;
        this._host = host;
    }

    /**
     * Forget this connection: drop adopted fields and re-arm the
     * one-per-connection notification.
     *
     * Called when the server stops or the connection drops. `check()`
     * calls it too, so a reconnect to a server WITHOUT the previously
     * adopted field cannot leave that field behind.
     */
    reset(): void {
        this._host.resetAdopted();
        this._announced = false;
        this.last = null;
    }

    /**
     * Drop adopted fields without re-arming the notification.
     *
     * `check()` uses this rather than `reset()` so that calling it twice
     * inside ONE connection re-derives adoption (cheap, idempotent)
     * without telling the user the same thing twice. Only a real
     * connection boundary — `reset()` — re-arms.
     */
    private _clearAdoption(): void {
        this._host.resetAdopted();
        this.last = null;
    }

    /**
     * Fetch and classify. Never throws, never blocks the chat.
     *
     * @returns the diff (`verdict: 'unverified'` when the fetch failed).
     */
    async check(): Promise<SchemaDiff> {
        // Start from a clean slate: adoption belongs to ONE connection.
        this._clearAdoption();

        let served: SchemaLike;
        try {
            served = await this._backend.getAppStateSchema();
        } catch (e: any) {
            const message = e?.message ?? String(e);
            const diff: SchemaDiff = {
                verdict: 'unverified',
                extra: [], missing: [], changed: [], adoptable: {},
                bundledVersion: (typeof this._bundled.version === 'string')
                    ? this._bundled.version : null,
                serverVersion: null,
                versionDiffers: false,
                error: message,
            };
            this.last = diff;
            this._announce(
                `[ppxai SchemaGuard] could not verify the server's AppState ` +
                `shape — ${message}. Continuing with the extension's bundled ` +
                `schema; expected against a server older than v1.17.4, which ` +
                `has no /schema/app-state endpoint.`
            );
            return diff;
        }

        const diff = compareSchemas(this._bundled, served);
        this.last = diff;

        if (diff.verdict === 'extra-only') {
            // Harmless skew: a NEWER server. Adopt so `updateFromPython`
            // stores these instead of warning on every single push.
            const adopted = this._host.adopt(diff.adoptable);
            this._announce(
                `[ppxai SchemaGuard] server declares ${diff.extra.length} AppState ` +
                `field(s) this extension does not know: ${diff.extra.join(', ')}. ` +
                `Adopted for this connection (${adopted.join(', ')}) — state is ` +
                `stored, not rendered. Update the extension to use them.`
            );
        } else if (diff.verdict === 'incompatible') {
            // Adopt the extras anyway — they are orthogonal to the break.
            if (diff.extra.length > 0) { this._host.adopt(diff.adoptable); }
            await this._warnIncompatible(diff);
        }
        // `identical` is silent, by design: a matched pair is the normal
        // case and must not produce a line in anybody's log.

        return diff;
    }

    private async _warnIncompatible(diff: SchemaDiff): Promise<void> {
        if (this._announced) { return; }
        this._announced = true;
        let serverVersion: string | null = null;
        if (this._host.serverVersion) {
            try {
                serverVersion = await this._host.serverVersion();
            } catch {
                serverVersion = null;
            }
        }
        const message = describeIncompatibility(
            diff, this._host.extensionVersion ?? null, serverVersion,
        );
        this._host.log(message);
        this._host.warnUser(message);
    }

    /** Log at most one line per connection. */
    private _announce(message: string): void {
        if (this._announced) { return; }
        this._announced = true;
        this._host.log(message);
    }
}

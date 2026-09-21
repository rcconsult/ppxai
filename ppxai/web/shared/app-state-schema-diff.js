/**
 * AppState schema drift classification — the web mirror of
 * `vscode-extension/src/schemaGuard.ts::compareSchemas`.
 *
 * Background (Task 2, plan-adr-0007-completion-service.md, open owner
 * decision item 9, closed 2026-09-21 — "re-fetch if difference is
 * spot"): the web page gets `window.APP_STATE_SCHEMA` injected once at
 * serve time (`server/routes/static.py::serve_index`), but the client
 * recovers from a server restart WITHOUT a page reload — the heartbeat
 * watchdog's `connectToServer(true)` and the visibility/focus re-anchor
 * path both call `PpxaiApp._reanchorFromServer()`, which only ever
 * re-fetched `GET /state`, never the schema. A tab left open across a
 * server upgrade therefore kept comparing the OLD injected schema
 * against the NEW server's `state_sync` pushes: an unknown pushed field
 * gave a per-push `console.warn`; a removed/renamed field was silent.
 *
 * This module is the same classification `schemaGuard.ts` already does
 * for VSCode, reimplemented in plain JS rather than imported: the web
 * client never loads compiled TypeScript (every other `ppxai/web/**`
 * module is plain JS, loaded via a `<script>` tag or `require()`).
 * `tests/test_schema_diff_cross_language_parity.py` feeds the SAME
 * fixture schemas to both implementations and asserts identical
 * verdicts and field lists, so the two cannot drift from each other
 * silently.
 *
 * Pure: no fetch, no DOM, no console, no mutation of its inputs. Same
 * verdict semantics as the TS side:
 *
 *   - identical    — same field names, same client names, same types.
 *   - extra-only   — the server declares fields this schema doesn't
 *                    know. Harmless skew (a newer server): adopt.
 *   - incompatible — a field THIS schema has is missing on the server,
 *                    or its type or client name differs there.
 *
 * `unverified` (the endpoint 404s or the fetch throws) is NOT produced
 * here — like `schemaGuard.ts::check()`, that is the caller's job,
 * since it depends on the fetch outcome rather than on two schema
 * objects.
 *
 * Web has no compile-time field types to protect (unlike VSCode's
 * generated `AppStateFields` interface), so unlike `schemaGuard.ts`'s
 * conservative "only ADD the extra fields" adoption, `AppState.
 * adoptSchema()` (see `app-state.js`) fully re-derives the field map
 * from whatever schema this function was told to adopt — unaffected by
 * this module, which only classifies.
 */

/** `schema.fields`, or `{}` for a missing/malformed schema. */
function _fieldsOf(schema) {
    const fields = schema && schema.fields;
    return (fields && typeof fields === 'object') ? fields : {};
}

/**
 * Compare a `bundled` (currently-running) schema with a `server`
 * (freshly fetched) one, field by field.
 *
 * @param {object|null|undefined} bundled
 * @param {object|null|undefined} server
 * @returns {{
 *   verdict: 'identical'|'extra-only'|'incompatible',
 *   extra: string[], missing: string[],
 *   changed: {field: string, what: string, bundled: string, server: string}[],
 *   adoptable: object,
 *   bundledVersion: string|null, serverVersion: string|null,
 *   versionDiffers: boolean, error: null,
 * }}
 */
function compareSchemas(bundled, server) {
    const mine = _fieldsOf(bundled);
    const theirs = _fieldsOf(server);

    const extra = [];
    const missing = [];
    const changed = [];
    const adoptable = {};

    for (const name of Object.keys(mine)) {
        const ours = mine[name];
        const remote = theirs[name];
        if (!remote) {
            missing.push(name);
            continue;
        }
        const parts = [];
        if (String(ours.type) !== String(remote.type)) parts.push('type');
        if (String(ours.client) !== String(remote.client)) parts.push('client');
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
    const verdict = broken ? 'incompatible' : (extra.length > 0 ? 'extra-only' : 'identical');

    return {
        verdict, extra, missing, changed, adoptable,
        bundledVersion, serverVersion,
        versionDiffers: bundledVersion !== serverVersion,
        error: null,
    };
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { compareSchemas };
}
if (typeof window !== 'undefined') {
    window.compareAppStateSchemas = compareSchemas;
}

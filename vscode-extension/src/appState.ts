/**
 * AppState — canonical application state for the VSCode extension.
 *
 * **Schema-driven (v1.17.4).** AppState loads its field definitions,
 * defaults, and Python↔TS name mapping from the canonical JSON schema
 * at `../resources/app-state-schema.json`, which is kept in sync with
 * the Python source (`ppxai/engine/app_state_schema.json`) by the
 * `scripts/sync-schema.js` pre-compile hook.
 *
 *   Python: snake_case   (tools_enabled, is_streaming)
 *   JS/TS:  camelCase    (toolsEnabled, isStreaming)
 *
 * This class is the **cross-language facade** for the VSCode extension.
 * Callers never translate wire-format field names themselves — they
 * hand Python-shaped payloads (snake_case JSON from SSE state_sync
 * events or REST responses) to `updateFromPython()` and read camelCase
 * values via the typed `get()` / `snapshot()` methods.
 *
 * **The `AppStateFields` type is GENERATED** (`./appState.generated`), by
 * the same `scripts/sync-schema.js` run that copies the JSON. It used to
 * be a hand-written interface here and it drifted: the schema had 22
 * fields and the interface 20 (`lastMessageRole` and `modelSupportsVision`
 * were never added), while this comment claimed a constructor assertion
 * that did not exist. Nothing in the type layer is hand-maintained now
 * except the three container element interfaces in `./appStateTypes`.
 *
 * TypeScript enforces the remaining invariant at build time: the class
 * only reads and writes keys of the generated `AppStateFields`, so a
 * field removed from the canonical schema breaks compilation at every
 * call site that still names it.
 *
 * When Python adds a new canonical field:
 *   1. Add it to `ppxai/engine/app_state_schema.json`.
 *   2. Bump the `AppState.FIELDS` sentinel test in `tests/test_app_state.py`.
 *   3. Run `npm run sync-schema` (or just `npm run compile`, which does it)
 *      and commit the regenerated `src/appState.generated.ts` and
 *      `resources/app-state-schema.json`.
 * There is no step that types a field name by hand. `web/shared/app-state.js`
 * is fully dynamic and needs nothing at all.
 *
 * **Version skew is checked at run time** by `./schemaGuard`, which the
 * chat panel drives on connect: it fetches `GET /schema/app-state` from
 * the server actually connected to and compares it with the bundled copy
 * these types were generated from. Fields a NEWER server declares are
 * adopted for that connection (`adoptFields`) so `updateFromPython`
 * stores them instead of dropping them with a per-push warning; fields
 * this build was compiled against but the server does not have are
 * surfaced to the user once. Adoption is per-instance and cleared by
 * `resetAdoptedFields()` on disconnect, so reconnecting to a different
 * server cannot leave a stale field behind.
 */

import * as fs from 'fs';
import * as path from 'path';

import { AppStateFields } from './appState.generated';
import {
    AgentBeatSnapshot,
    BackgroundAgentSummary,
    ContextAttachment,
} from './appStateTypes';

export { AppStateFields };
export { AgentBeatSnapshot, BackgroundAgentSummary, ContextAttachment };

/** Raw schema file shape. */
export interface SchemaField {
    client: string;
    type: 'string' | 'boolean' | 'integer' | 'number' | 'array' | 'object';
    default: unknown;
    group: string;
    doc?: string;
}

export interface Schema {
    version: string;
    description?: string;
    fields: Record<string, SchemaField>;
}

/**
 * The minimum an adopted field must declare: where to store it and what
 * to seed it with. Structurally satisfied by both `SchemaField` here and
 * `SchemaFieldSpec` in `./schemaGuard`, which is the point — adoption
 * must not force the two shapes to be the same nominal type.
 */
export interface AdoptableField {
    client: string;
    default: unknown;
}

/** Listener callback type */
type Listener<T = any> = (value: T) => void;

/**
 * Load the canonical schema from the bundled resource file.
 *
 * At runtime `__dirname` points at the compiled output
 * (`<extension>/out/`), so `../resources/` resolves to the extension's
 * `resources/` directory where `sync-schema.js` placed the canonical
 * copy at build time.
 *
 * Loaded synchronously at module init — the file is ~3 KB and sits
 * next to the compiled extension JS on disk, so this is effectively
 * free. Using `readFileSync` rather than a TS JSON import avoids
 * having to relax the project `rootDir: "src"` constraint.
 */
function _loadSchema(): Schema {
    const candidates = [
        path.resolve(__dirname, '..', 'resources', 'app-state-schema.json'),
        path.resolve(__dirname, '..', '..', 'resources', 'app-state-schema.json'),
    ];
    for (const candidate of candidates) {
        if (fs.existsSync(candidate)) {
            const raw = fs.readFileSync(candidate, 'utf-8');
            return JSON.parse(raw) as Schema;
        }
    }
    throw new Error(
        `AppState: canonical schema not found. Looked in:\n  ${candidates.join('\n  ')}\n` +
        `Run 'node scripts/sync-schema.js' from the vscode-extension directory to copy ` +
        `ppxai/engine/app_state_schema.json into resources/. This is normally done ` +
        `automatically by the precompile hook in package.json.`
    );
}

const _SCHEMA: Schema = _loadSchema();

/** Clone a default value so mutable containers aren't shared between instances. */
function _cloneDefault(value: unknown): unknown {
    if (Array.isArray(value)) return [...value];
    if (value !== null && typeof value === 'object') return { ...(value as object) };
    return value;
}

/**
 * Observable AppState for the VSCode extension.
 *
 * Same API as Python (get/set/on/off/update/snapshot) and JavaScript
 * (on/snapshot) implementations, plus `updateFromPython()` for
 * ingesting snake_case payloads from the server.
 */
export class AppState {
    /** Raw schema (public for the schema endpoint, diagnostics, tests). */
    static readonly SCHEMA: Schema = _SCHEMA;

    /**
     * The schema `appState.generated.ts` was generated from — the same
     * object as `SCHEMA`, named for the one job that cares about the
     * distinction: `schemaGuard` compares a CONNECTED SERVER's schema
     * against what this build was COMPILED against.
     */
    static readonly BUNDLED_SCHEMA: Schema = _SCHEMA;

    /**
     * Python snake_case → TS camelCase map, derived from the bundled
     * schema at module load. The compile-time vocabulary; an instance
     * may hold a wider one after adopting a newer server's extra
     * fields (see `adoptFields`).
     */
    static readonly PYTHON_TO_TS: Readonly<Record<string, string>> = Object.freeze(
        Object.fromEntries(
            Object.entries(_SCHEMA.fields).map(([py, spec]) => [py, spec.client])
        )
    );

    /** Inverse map, computed lazily on first access. */
    private static _tsToPython: Readonly<Record<string, string>> | null = null;
    static get TS_TO_PYTHON(): Readonly<Record<string, string>> {
        if (!this._tsToPython) {
            const inv: Record<string, string> = {};
            for (const [py, ts] of Object.entries(this.PYTHON_TO_TS)) {
                inv[ts] = py;
            }
            this._tsToPython = Object.freeze(inv);
        }
        return this._tsToPython;
    }

    private _data: AppStateFields;
    private _listeners: Partial<Record<keyof AppStateFields, Listener[]>> = {};

    /**
     * Per-instance Python→TS map. Starts as a copy of the static
     * (compile-time) map and may GAIN entries for fields a newer server
     * declares. Per-instance, never static: a disconnect/reconnect to a
     * different server must not inherit the previous one's vocabulary.
     */
    private _pythonToTs: Record<string, string>;

    /** Client names adopted from a server this connection, in adoption order. */
    private _adopted: string[] = [];

    constructor(initial?: Partial<AppStateFields>) {
        // Build defaults from the schema. The cast is safe because
        // `AppStateFields` is GENERATED from this same schema file by
        // scripts/sync-schema.js — the two cannot disagree without
        // tests/test_app_state_generated_types.py failing.
        const defaults: Partial<AppStateFields> = {};
        for (const [, spec] of Object.entries(_SCHEMA.fields)) {
            (defaults as any)[spec.client] = _cloneDefault(spec.default);
        }
        this._data = { ...defaults, ...initial } as AppStateFields;
        this._pythonToTs = { ...AppState.PYTHON_TO_TS };
    }

    /** Get a state field value. */
    get<K extends keyof AppStateFields>(key: K): AppStateFields[K] {
        return this._data[key];
    }

    /**
     * Read a field by client name without the compile-time key
     * constraint. The only way to read a field ADOPTED from a newer
     * server — by definition this build has no type for it, so the
     * return type is `unknown` and the caller must narrow.
     */
    getRaw(key: string): unknown {
        return (this._data as unknown as Record<string, unknown>)[key];
    }

    /** Set a state field. Returns true if value changed. No-op if identical. */
    set<K extends keyof AppStateFields>(key: K, value: AppStateFields[K]): boolean {
        if (this._data[key] === value) {
            return false;
        }
        this._data[key] = value;
        this._dispatch(key, value);
        return true;
    }

    /** Set multiple fields atomically. Listeners fire after all fields set. */
    update(values: Partial<AppStateFields>): void {
        const changed: [keyof AppStateFields, any][] = [];
        for (const [key, value] of Object.entries(values) as [keyof AppStateFields, any][]) {
            if (key in this._data && this._data[key] !== value) {
                (this._data as any)[key] = value;
                changed.push([key, value]);
            }
        }
        for (const [key, value] of changed) {
            this._dispatch(key, value);
        }
    }

    /**
     * Teach this instance about fields a CONNECTED SERVER declares that
     * the bundled schema does not — the "newer server, older extension"
     * skew. Each adopted field gets its server-declared default and a
     * name-map entry, so `updateFromPython` STORES it (readable via
     * `getRaw` / `snapshot`) instead of dropping it with a warning on
     * every single push.
     *
     * Harmless by construction: nothing in this build reads an adopted
     * field by name, because no such code could have been compiled.
     * Fields already known are ignored, so calling this repeatedly with
     * the same payload is a no-op.
     *
     * @param fields  Python-keyed schema field specs (the server's).
     * @returns the client names newly adopted by THIS call.
     */
    adoptFields(fields: Record<string, AdoptableField>): string[] {
        const added: string[] = [];
        for (const [pyName, spec] of Object.entries(fields || {})) {
            if (!spec || typeof spec.client !== 'string' || !spec.client) { continue; }
            if (this._pythonToTs[pyName] !== undefined) { continue; }
            this._pythonToTs[pyName] = spec.client;
            (this._data as unknown as Record<string, unknown>)[spec.client] =
                _cloneDefault(spec.default);
            this._adopted.push(spec.client);
            added.push(spec.client);
        }
        return added;
    }

    /**
     * Forget every field adopted from a server — the name map reverts to
     * the compile-time vocabulary and the values are dropped.
     *
     * Called when the connection goes away. A reconnect may reach a
     * DIFFERENT server, and a field that server never declares must not
     * survive in this store as a ghost of the previous one.
     */
    resetAdoptedFields(): void {
        for (const clientName of this._adopted) {
            delete (this._data as unknown as Record<string, unknown>)[clientName];
            delete this._listeners[clientName as keyof AppStateFields];
        }
        this._adopted = [];
        this._pythonToTs = { ...AppState.PYTHON_TO_TS };
    }

    /** Client names currently adopted from a server, in adoption order. */
    adoptedFields(): string[] {
        return [...this._adopted];
    }

    /**
     * Ingest a Python-shaped payload (snake_case keys) and apply it
     * to the local camelCase state. This is the single cross-language
     * boundary — every SSE `state_sync` event and every REST response
     * that carries canonical state fields should go through this
     * method.
     *
     * @param payload - Python-shaped object (snake_case keys)
     * @returns The mapped camelCase object that was applied.
     */
    updateFromPython(payload: Record<string, unknown>): Partial<AppStateFields> {
        if (!payload || typeof payload !== 'object') {
            return {};
        }

        const mapped: Partial<AppStateFields> = {};
        for (const [pyKey, value] of Object.entries(payload)) {
            const tsKey = this._pythonToTs[pyKey];
            if (tsKey === undefined) {
                console.warn(
                    `[AppState] updateFromPython: unknown field '${pyKey}'. ` +
                    `Check ppxai/engine/app_state_schema.json and make sure ` +
                    `vscode-extension/resources/app-state-schema.json is current ` +
                    `(run 'npm run sync-schema').`
                );
                continue;
            }
            (mapped as any)[tsKey] = value;
        }

        this.update(mapped);
        return mapped;
    }

    /** Subscribe to changes on a field. Returns this for chaining. */
    on<K extends keyof AppStateFields>(key: K, fn: Listener<AppStateFields[K]>): this {
        if (!this._listeners[key]) {
            this._listeners[key] = [];
        }
        this._listeners[key]!.push(fn as Listener);
        return this;
    }

    /** Unsubscribe a listener. Returns this for chaining. */
    off<K extends keyof AppStateFields>(key: K, fn: Listener<AppStateFields[K]>): this {
        const fns = this._listeners[key];
        if (fns) {
            const idx = fns.indexOf(fn as Listener);
            if (idx >= 0) {
                fns.splice(idx, 1);
            }
        }
        return this;
    }

    /** Return a plain-object snapshot of current state. */
    snapshot(): AppStateFields {
        return { ...this._data };
    }

    private _dispatch<K extends keyof AppStateFields>(key: K, value: AppStateFields[K]): void {
        const fns = this._listeners[key];
        if (fns) {
            for (const fn of fns) {
                fn(value);
            }
        }
    }
}

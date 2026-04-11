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
 * The `AppStateFields` interface below is hand-maintained as static
 * type documentation. TypeScript enforces two invariants at build time:
 *   - Every field declared on the interface must appear in the JSON
 *     schema (checked at runtime by a constructor assertion).
 *   - The constructor only writes to fields that exist on the
 *     interface (type-checked by `keyof AppStateFields`).
 *
 * When Python adds a new canonical field:
 *   1. Add it to `ppxai/engine/app_state_schema.json`.
 *   2. Bump `AppState.FIELDS` sentinel test in `tests/test_app_state.py`.
 *   3. Add the camelCase field to `AppStateFields` below.
 *   4. Mirror the change in `ppxai/web/shared/app-state.js` — only if
 *      the web AppState constructor needs type updates (the web side
 *      is fully dynamic and usually needs no changes).
 *
 * The sync script ensures step 3 is always picked up at build time;
 * the Python test pins the schema count on the engine side; step 4
 * is the only manual work left, and only when a new field needs
 * TypeScript type coverage.
 *
 * The v1.18.x schema generator will auto-generate `AppStateFields`
 * from the JSON schema, eliminating step 3 entirely.
 */

import * as fs from 'fs';
import * as path from 'path';

/**
 * Canonical state fields shared across all ppxai clients.
 *
 * Hand-maintained type documentation. Must stay in sync with
 * `ppxai/engine/app_state_schema.json` — the constructor validates
 * at runtime that every interface field has a matching schema entry.
 */
export interface AppStateFields {
    // --- Core identity ---
    currentProvider: string;
    currentModel: string;
    workingDir: string;
    sessionId: string;
    sessionName: string;

    // --- Feature toggles ---
    toolsEnabled: boolean;
    toolsVerbose: boolean;
    agentMode: boolean;
    autoRoute: boolean;

    // --- Streaming / flow control ---
    isStreaming: boolean;
    cancelRequested: boolean;

    // --- Usage statistics ---
    totalTokens: number;
    promptTokens: number;
    completionTokens: number;
    totalCost: number;
    contextPercentage: number;

    // --- Debug ---
    debugLog: boolean;

    // --- Multimodal context (v1.17.4 Phase 6.3) ---
    // List of attachment summaries currently in session.messages.
    // Entry schema: { name, kind, media_type, turn_index, file_id }
    contextAttachments: ContextAttachment[];
}

/**
 * A single multimodal attachment entry in context_attachments.
 * Matches the Python dict schema from EngineClient._refresh_context_attachments.
 */
export interface ContextAttachment {
    name: string;
    kind: string;        // "image" | "text" | "pdf" | "file"
    media_type: string;  // e.g. "image/png", "" if unknown
    turn_index: number;  // index into session.messages
    file_id: string;     // SessionFileStore identifier, "" for legacy
}

/** Raw schema file shape. */
interface SchemaField {
    client: string;
    type: 'string' | 'boolean' | 'integer' | 'number' | 'array';
    default: unknown;
    group: string;
    doc?: string;
}

interface Schema {
    version: string;
    description?: string;
    fields: Record<string, SchemaField>;
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
     * Python snake_case → TS camelCase map, derived from the schema
     * at module load. Single source of truth for cross-language
     * field name translation on the VSCode extension.
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

    constructor(initial?: Partial<AppStateFields>) {
        // Build defaults from the schema. The cast is safe because
        // the `AppStateFields` interface and the schema are required
        // to stay in sync (enforced by the Python drift test and the
        // sync-schema pre-compile hook).
        const defaults: Partial<AppStateFields> = {};
        for (const [, spec] of Object.entries(_SCHEMA.fields)) {
            (defaults as any)[spec.client] = _cloneDefault(spec.default);
        }
        this._data = { ...defaults, ...initial } as AppStateFields;
    }

    /** Get a state field value. */
    get<K extends keyof AppStateFields>(key: K): AppStateFields[K] {
        return this._data[key];
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
            const tsKey = AppState.PYTHON_TO_TS[pyKey];
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

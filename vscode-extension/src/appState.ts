/**
 * AppState — canonical application state interface for the VSCode extension.
 *
 * Matches the Python AppState (ppxai/engine/app_state.py) and JavaScript
 * AppState (ppxai/web/shared/app-state.js) with language-appropriate naming:
 *
 *   Python: snake_case   (tools_enabled, is_streaming)
 *   JS/TS: camelCase     (toolsEnabled, isStreaming)
 *
 * All clients share the same semantic fields. The v1.18.x schema generator
 * will auto-generate this interface from a YAML schema.
 */

/**
 * Canonical state fields shared across all ppxai clients.
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
    // Pushed from server via state_sync SSE. Each entry mirrors the
    // Python AppState.context_attachments schema:
    //   { name, kind, media_type, turn_index, file_id }
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

/** Listener callback type */
type Listener<T = any> = (value: T) => void;

/**
 * Observable AppState for the VSCode extension.
 *
 * Same API as Python (get/set/on/off/update/snapshot) and JavaScript
 * (on/snapshot) implementations.
 */
export class AppState {
    private _data: AppStateFields;
    private _listeners: Partial<Record<keyof AppStateFields, Listener[]>> = {};

    constructor(initial?: Partial<AppStateFields>) {
        this._data = {
            currentProvider: '',
            currentModel: '',
            workingDir: '',
            sessionId: '',
            sessionName: '',
            toolsEnabled: false,
            toolsVerbose: false,
            agentMode: false,
            autoRoute: false,
            isStreaming: false,
            cancelRequested: false,
            totalTokens: 0,
            promptTokens: 0,
            completionTokens: 0,
            totalCost: 0,
            contextPercentage: 0,
            debugLog: false,
            contextAttachments: [],
            ...initial,
        };
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

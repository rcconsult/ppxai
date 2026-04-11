/**
 * AppState — centralized observable state for the ppxai web app.
 *
 * **Schema-driven (v1.17.4).** AppState loads its field definitions,
 * defaults, and Python↔JS name mapping from `window.APP_STATE_SCHEMA`,
 * which is injected into `index.html` by the FastAPI static route
 * before this script runs. The schema comes straight from
 * `ppxai/engine/app_state_schema.json` — the golden source of truth
 * shared by Python, Web, and VSCode clients.
 *
 * There are **zero hand-maintained field maps** in this file. Every
 * canonical field, default value, and snake_case↔camelCase mapping
 * is derived from the schema at construction time. Adding a field
 * is a one-line edit to the JSON schema.
 *
 * Consumers never touch the raw wire format. They always write
 * camelCase via the Proxy:
 *
 *   this.state.currentProvider                   // read
 *   this.state.currentProvider = 'openai'        // write (no-op if unchanged)
 *   this.state.on('currentProvider', v => updateBadge(v))  // subscribe
 *
 * The cross-language boundary goes through one method:
 *
 *   this.state.updateFromPython({provider: 'openai', total_tokens: 1234})
 *
 * which translates every snake_case key to its camelCase form via the
 * schema-derived `_pythonToJs` map, writes each field through the
 * Proxy (firing observers automatically), and returns the mapped
 * camelCase object so callers can iterate it for side-effect dispatch
 * without re-translating.
 *
 * Drift detection: unknown snake_case keys trigger a console.warn
 * pointing at the likely cause. Since the schema is loaded from the
 * server, "drift" here means the Python server is pushing a field
 * that the schema doesn't declare — which would mean the server is
 * running a newer version of ppxai than the web UI.
 */

class AppState {
    /**
     * @param {object} initial  - Initial state values (camelCase keys)
     *                            that override the schema defaults.
     */
    constructor(initial = {}) {
        const schema = (typeof window !== 'undefined') ? window.APP_STATE_SCHEMA : null;
        if (!schema || !schema.fields) {
            throw new Error(
                'AppState: window.APP_STATE_SCHEMA is missing or malformed. ' +
                'The FastAPI static route is responsible for injecting it into ' +
                'index.html before shared/app-state.js loads. Check ' +
                'ppxai/server/routes/static.py::serve_index and ' +
                'ppxai/engine/app_state_schema.json.'
            );
        }

        this._schema = schema;

        // Derive Python→JS mapping from the schema. This is the
        // single source of truth for cross-language field name
        // translation on the web client — nothing outside this class
        // needs to know about snake_case vs camelCase.
        const pythonToJs = {};
        const defaults = {};
        for (const [pyName, spec] of Object.entries(schema.fields)) {
            pythonToJs[pyName] = spec.client;
            defaults[spec.client] = _cloneDefault(spec.default);
        }
        this._pythonToJs = Object.freeze(pythonToJs);

        // Lazy inverse for callers that need to serialize camelCase
        // state back to Python snake_case (future REST PUT endpoints,
        // debug payloads, test fixtures).
        this._jsToPython = null;

        this._data = { ...defaults, ...initial };
        this._listeners = Object.create(null);

        // Return a Proxy so that `state.key` reads/writes go through
        // the no-op check and notification logic.
        return new Proxy(this, {
            get(target, key) {
                // Expose internal fields and prototype methods directly
                if (key === '_data' || key === '_listeners'
                    || key === '_schema' || key === '_pythonToJs'
                    || key === '_jsToPython') return target[key];
                if (typeof key === 'symbol' || key in AppState.prototype) return target[key];
                return target._data[key];
            },
            set(target, key, value) {
                // Internal fields bypass the state mechanism
                if (key === '_data' || key === '_listeners'
                    || key === '_schema' || key === '_pythonToJs'
                    || key === '_jsToPython') {
                    target[key] = value;
                    return true;
                }
                // No-op: skip identical values (prevents redundant renders/calls)
                if (target._data[key] === value) return true;
                target._data[key] = value;
                // Notify listeners
                const fns = target._listeners[key];
                if (fns) fns.forEach(fn => fn(value));
                return true;
            }
        });
    }

    /**
     * Return the inverse mapping (camelCase → snake_case). Computed
     * lazily on first access and cached.
     */
    get jsToPython() {
        if (!this._jsToPython) {
            const inv = {};
            for (const [py, js] of Object.entries(this._pythonToJs)) {
                inv[js] = py;
            }
            this._jsToPython = Object.freeze(inv);
        }
        return this._jsToPython;
    }

    /**
     * Ingest a Python-shaped payload (snake_case keys) and apply it
     * to the local camelCase state. This is the single cross-language
     * boundary — every SSE `state_sync` event and every REST response
     * that carries canonical state fields should go through this
     * method.
     *
     * Translation strategy:
     *   - Each snake_case key is looked up in the schema-derived
     *     `_pythonToJs` map
     *   - Mapped camelCase key is written through the Proxy, which
     *     fires `on()` observers automatically (no special casing)
     *   - Unknown snake_case keys log a drift warning naming the
     *     likely cause
     *
     * @param {object} payload - Python-shaped dict (snake_case keys)
     * @returns {object} The mapped camelCase object that was applied.
     */
    updateFromPython(payload) {
        if (!payload || typeof payload !== 'object') return {};

        const mapped = {};
        for (const [pyKey, value] of Object.entries(payload)) {
            const jsKey = this._pythonToJs[pyKey];
            if (jsKey === undefined) {
                console.warn(
                    `[AppState] updateFromPython: unknown field '${pyKey}'. ` +
                    `Check ppxai/engine/app_state_schema.json and make sure ` +
                    `the web UI was restarted after the schema changed.`
                );
                continue;
            }
            // Write through the Proxy — fires observers via the
            // existing machinery, honours no-op deduplication.
            this[jsKey] = value;
            mapped[jsKey] = value;
        }
        return mapped;
    }

    /**
     * Subscribe to changes on a state key.
     * The callback receives the new value.
     * Returns `this` for chaining.
     *
     * @param {string}   key
     * @param {function} fn  - Called with (newValue) on change
     * @returns {AppState}
     */
    on(key, fn) {
        if (!this._listeners[key]) this._listeners[key] = [];
        this._listeners[key].push(fn);
        return this;
    }

    /**
     * Return a plain-object snapshot of current state (for debugging).
     * @returns {object}
     */
    snapshot() {
        return { ...this._data };
    }
}

/**
 * Clone a default value from the schema so mutable containers
 * (lists, objects) aren't shared between AppState instances.
 */
function _cloneDefault(value) {
    if (Array.isArray(value)) return [...value];
    if (value !== null && typeof value === 'object') return { ...value };
    return value;
}

// Browser global export
if (typeof window !== 'undefined') {
    window.AppState = AppState;
}

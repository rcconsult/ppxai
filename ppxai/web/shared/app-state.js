/**
 * AppState — centralized observable state for the ppxai web app.
 *
 * Extracted from app.js v1.16.2.
 * All mutable application state lives here instead of as loose instance
 * variables on PpxaiApp. Provides no-op deduplication on writes and an
 * optional observer hook for reactive updates.
 *
 * Implemented as a JavaScript Proxy so state is accessed and set with
 * plain property syntax — no get()/set() method calls required:
 *
 *   this.state.currentProvider          // read
 *   this.state.currentProvider = 'openai'  // write (no-op if unchanged)
 *   this.state.on('currentProvider', v => updateBadge(v))  // subscribe
 *
 * Canonical field mapping (Python snake_case → JS camelCase):
 *   provider         → currentProvider
 *   model            → currentModel
 *   tools_enabled    → toolsEnabled
 *   tools_verbose    → toolsVerbose
 *   agent_mode       → agentMode
 *   is_streaming     → isStreaming
 *   cancel_requested → cancelRequested
 *   working_dir      → workingDir
 *   session_id       → sessionId
 *   session_name     → sessionName
 *   total_tokens     → totalTokens
 *   prompt_tokens    → promptTokens
 *   completion_tokens→ completionTokens
 *   total_cost       → totalCost
 *   context_percentage→ contextPercentage
 *   auto_route       → autoRoute
 *   debug_log        → debugLog
 */

class AppState {
    /**
     * @param {object} initial  - Initial state values
     */
    constructor(initial = {}) {
        this._data      = { ...initial };
        this._listeners = Object.create(null);

        // Return a Proxy so that `state.key` reads/writes go through
        // the no-op check and notification logic.
        return new Proxy(this, {
            get(target, key) {
                // Expose internal fields and prototype methods directly
                if (key === '_data' || key === '_listeners') return target[key];
                if (typeof key === 'symbol' || key in AppState.prototype) return target[key];
                return target._data[key];
            },
            set(target, key, value) {
                // Internal fields bypass the state mechanism
                if (key === '_data' || key === '_listeners') {
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

// Browser global export
if (typeof window !== 'undefined') {
    window.AppState = AppState;
}

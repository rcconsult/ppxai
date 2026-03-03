/**
 * BaseView — protocol base class for all RightPanelFrame views.
 *
 * Subclasses MUST override: getTitle(), getPath(), mount(), unmount(),
 * focus(), onKeyDown().
 *
 * Subclasses SHOULD override: isDirty(), getState(), setState(),
 * onActivate(), onDeactivate(), getIcon().
 *
 * @version 1.16.2
 */
class BaseView {
    constructor() {
        this._pinned       = false;
        this._pendingState = null;  // set by RightPanelFrame before mount; applied by view after load
    }

    // ── Required — subclasses MUST implement ─────────────────────────────────

    /** @returns {string} Display name shown in dropdown and frame header. */
    getTitle() { throw new Error(`${this.constructor.name}.getTitle() not implemented`); }

    /** @returns {string|null} Relative file path, or null for non-file views. */
    getPath() { throw new Error(`${this.constructor.name}.getPath() not implemented`); }

    /**
     * Render this view into the given container element.
     * Called exactly once when the view is pushed onto the stack.
     * @param {HTMLElement} container
     */
    mount(container) { throw new Error(`${this.constructor.name}.mount() not implemented`); }

    /**
     * Clean up DOM and any resources (editors, timers, event listeners).
     * Called when the view is evicted from the stack.
     */
    unmount() { throw new Error(`${this.constructor.name}.unmount() not implemented`); }

    /** Focus the primary interactive element within this view. */
    focus() {}

    /**
     * Handle a keydown event. Called only when this view is active (top of stack).
     * @param {KeyboardEvent} e
     * @returns {boolean} true if the event was consumed (stops propagation)
     */
    onKeyDown(e) { return false; }

    // ── State — override for dirty tracking and persistence ──────────────────

    /** @returns {boolean} True if this view has unsaved changes. */
    isDirty() { return false; }

    /**
     * Return a serializable snapshot of view-specific state
     * (e.g. scroll position, cursor offset) for stack persistence.
     * @returns {object}
     */
    getState() { return {}; }

    /**
     * Restore view-specific state from a previously saved snapshot.
     * @param {object} _state
     */
    setState(_state) {}

    // ── Lifecycle hooks — override as needed ─────────────────────────────────

    /** Called when this view becomes the top of the stack (gains focus). */
    onActivate() {}

    /** Called when another view is pushed on top (loses focus but stays mounted). */
    onDeactivate() {}

    // ── Metadata ─────────────────────────────────────────────────────────────

    /** @returns {string} Emoji or icon shown next to title in dropdown. */
    getIcon() { return '📄'; }

    /** @returns {boolean} True if this view is pinned (exempt from LRU eviction). */
    isPinned() { return this._pinned; }

    /** Pin this view so it is never evicted by LRU. */
    pin() { this._pinned = true; }

    /** Remove pin so this view is eligible for LRU eviction. */
    unpin() { this._pinned = false; }

    // ── Pending state (set by frame, applied by subclass after async mount) ───

    /**
     * Apply any pending state saved by the frame before this view was mounted.
     * Subclasses call this at the end of their async mount / build cycle.
     * Safe to call even if no pending state is set.
     */
    _applyPendingState() {
        if (!this._pendingState) return;
        const state = this._pendingState;
        this._pendingState = null;
        this.setState(state);
    }
}

// Browser global export
if (typeof window !== 'undefined') {
    window.BaseView = BaseView;
}

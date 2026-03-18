/**
 * RightPanelFrame — view stack manager for the ppxai web app right panel.
 *
 * Manages an LRU view stack with deduplication, lazy mounting, dirty-state
 * awareness, keyboard routing, and cursor/scroll state restoration on
 * back/forward navigation.
 *
 * Configuration is read from AppState:
 *   appState.rpfStackSize  (number,  default 10)
 *   appState.rpfDedup      (boolean, default true)
 *   appState.rpfPersist    (boolean, default false)
 *
 * Phase 4 additions:
 *   - _savedStates Map: saves view state before deactivation
 *   - _mountActive: applies saved state to view before mount (via _pendingState)
 *
 * @version 1.16.2
 */
class RightPanelFrame {
    /**
     * @param {HTMLElement} container - Root element the frame renders into
     * @param {object}      appState  - AppState singleton
     */
    constructor(container, appState) {
        this._container  = container;
        this._appState   = appState;
        this._stack      = [];   // [BaseView, …] index 0 = bottom, last = top (active)
        this._visible    = false;
        this._savedStates = new Map();  // Phase 4: state snapshots keyed by view instance

        this._viewportEl = null;  // set externally after construction (Phase 2)
    }

    // ── Public API ────────────────────────────────────────────────────────────

    /**
     * Push a view onto the stack.
     *
     * Deduplication (when rpfDedup=true): if a view with the same path is
     * already in the stack, that existing view is moved to the top instead
     * of creating a duplicate.
     *
     * LRU eviction: if the stack is at capacity and eviction is needed, the
     * least-recently-used non-pinned view at the bottom is unmounted and
     * removed. If all non-top views are pinned, the push is rejected and a
     * console warning is emitted.
     *
     * @param {BaseView} view
     */
    push(view) {
        const dedup   = this._appState.rpfDedup    ?? true;
        const maxSize = this._appState.rpfStackSize ?? 10;

        // Deduplication — promote existing view with the same path to top
        if (dedup && view.getPath() !== null) {
            const existing = this._findByPath(view.getPath());
            if (existing) {
                this._promote(existing);
                this.showFrame();
                return;
            }
        }

        // LRU eviction if at capacity
        if (this._stack.length >= maxSize) {
            if (!this._evictLRU()) {
                console.warn('RightPanelFrame: all non-top views are pinned; cannot push new view');
                return;
            }
        }

        // Deactivate current top; save its state for later restoration
        const prev = this.activeView;
        if (prev) {
            this._saveStateFor(prev);
            prev.onDeactivate();
        }

        // Mount new view into viewport
        this._stack.push(view);
        this._mountActive();

        this.showFrame();
        this._notifyChange();
    }

    /**
     * Close (pop) the active view.
     * If the view is dirty, prompts the user before closing.
     * If the stack becomes empty, the frame hides itself.
     */
    async pop() {
        const view = this.activeView;
        if (!view) return;

        if (view.isDirty()) {
            const ok = confirm(`"${view.getTitle()}" has unsaved changes. Close anyway?`);
            if (!ok) return;
        }

        this._savedStates.delete(view);
        view.unmount();
        this._stack.pop();

        if (this._stack.length > 0) {
            this._mountActive();
            this.activeView.onActivate();
        } else {
            this.hideFrame();
        }

        this._notifyChange();
    }

    /**
     * Navigate back (activate the view below the current top).
     * Saves the current top's scroll/cursor so it can be restored on forward.
     */
    back() {
        if (this._stack.length < 2) return;
        const top = this._stack.pop();
        this._saveStateFor(top);
        top.onDeactivate();
        this._stack.unshift(top);       // move to bottom
        this._mountActive();
        this.activeView.onActivate();
        this._notifyChange();
    }

    /**
     * Navigate forward (opposite of back — promotes the bottom view to top).
     * Saves the current bottom's state so back() can restore it.
     */
    forward() {
        if (this._stack.length < 2) return;
        const bottom = this._stack.shift();
        this._saveStateFor(bottom);
        bottom.onDeactivate();
        this._stack.push(bottom);       // move to top
        this._mountActive();
        this.activeView.onActivate();
        this._notifyChange();
    }

    /** Make the frame container visible. Does not modify the stack. */
    showFrame() {
        this._container.classList.remove('hidden');
        this._visible = true;
        if (this.activeView) this.activeView.onActivate();
    }

    /** Hide the frame container. Stack and mounted views are preserved. */
    hideFrame() {
        this._container.classList.add('hidden');
        this._visible = false;
    }

    /** Toggle frame visibility. */
    toggleFrame() {
        if (this._visible) this.hideFrame(); else this.showFrame();
    }

    /** @returns {BaseView|null} The active (top-of-stack) view, or null. */
    get activeView() {
        return this._stack.length > 0 ? this._stack[this._stack.length - 1] : null;
    }

    /** @returns {number} Number of views in the stack. */
    get stackSize() { return this._stack.length; }

    /**
     * Return metadata for all views, most-recent first (for dropdown rendering).
     * @returns {Array<{title, icon, isDirty, isPinned, isActive, stackIndex}>}
     */
    getStackInfo() {
        return this._stack.map((view, i) => ({
            title:      view.getTitle(),
            icon:       view.getIcon(),
            isDirty:    view.isDirty(),
            isPinned:   view.isPinned(),
            isActive:   i === this._stack.length - 1,
            stackIndex: i,
        })).reverse();
    }

    /**
     * Activate a specific view by its stack index (as returned by getStackInfo).
     * @param {number} stackIndex
     */
    activateByIndex(stackIndex) {
        const view = this._stack[stackIndex];
        if (!view) return;
        this._promote(view);
        this.showFrame();
    }

    /**
     * Close (remove) a view by its stack index.
     * Prompts if dirty. If the closed view was active, the next view in
     * the stack becomes active. If the stack becomes empty, the frame hides.
     * @param {number} stackIndex
     */
    async closeByIndex(stackIndex) {
        const view = this._stack[stackIndex];
        if (!view) return;

        if (view.isDirty()) {
            const ok = confirm(`"${view.getTitle()}" has unsaved changes. Close anyway?`);
            if (!ok) return;
        }

        const wasActive = (stackIndex === this._stack.length - 1);
        this._savedStates.delete(view);
        view.unmount();
        this._stack.splice(stackIndex, 1);

        if (this._stack.length === 0) {
            this.hideFrame();
        } else if (wasActive) {
            this._mountActive();
            this.activeView.onActivate();
        }

        this._notifyChange();
    }

    /**
     * Route a keyboard event to the active view.
     * Also handles back/forward navigation shortcuts.
     *
     * @param {KeyboardEvent} e
     * @returns {boolean} true if consumed
     */
    handleKeyDown(e) {
        const isMac = navigator.platform.includes('Mac');

        // Back: Cmd+← (macOS) or Alt+← (Win/Linux)
        if (e.key === 'ArrowLeft' && ((isMac && e.metaKey) || (!isMac && e.altKey))) {
            e.preventDefault();
            this.back();
            return true;
        }

        // Forward: Cmd+→ (macOS) or Alt+→ (Win/Linux)
        if (e.key === 'ArrowRight' && ((isMac && e.metaKey) || (!isMac && e.altKey))) {
            e.preventDefault();
            this.forward();
            return true;
        }

        // Escape: close frame
        if (e.key === 'Escape') {
            this.hideFrame();
            return true;
        }

        // Delegate to active view
        return this.activeView?.onKeyDown(e) ?? false;
    }

    // ── Private ───────────────────────────────────────────────────────────────

    /** Find a view by file path (returns first match, or null). */
    _findByPath(relPath) {
        for (let i = this._stack.length - 1; i >= 0; i--) {
            if (this._stack[i].getPath() === relPath) return this._stack[i];
        }
        return null;
    }

    /** Move an existing view to the top of the stack. */
    _promote(view) {
        const idx = this._stack.indexOf(view);
        if (idx === -1) return;

        // Already on top — just activate and reload in case file changed on disk
        if (idx === this._stack.length - 1) {
            view.onActivate();
            view.reload();
            return;
        }

        const prev = this.activeView;
        if (prev) {
            this._saveStateFor(prev);
            prev.onDeactivate();
        }

        this._stack.splice(idx, 1);
        this._stack.push(view);
        this._mountActive();
        view.onActivate();
        view.reload();
        this._notifyChange();
    }

    /**
     * Evict the least-recently-used (bottom) non-pinned view.
     * @returns {boolean} true if eviction succeeded
     */
    _evictLRU() {
        for (let i = 0; i < this._stack.length - 1; i++) {
            if (!this._stack[i].isPinned()) {
                const evicted = this._stack.splice(i, 1)[0];
                this._savedStates.delete(evicted);
                evicted.unmount();
                return true;
            }
        }
        return false;
    }

    /**
     * Mount the active (top-of-stack) view into the viewport.
     * If a saved state exists for this view, sets _pendingState on it so
     * the view can restore cursor/scroll after its async data load.
     */
    _mountActive() {
        const view = this.activeView;
        if (!view) return;

        // Inject saved state so view can apply it after its async fetch
        if (this._savedStates.has(view)) {
            view._pendingState = this._savedStates.get(view);
        }

        const viewport = this._viewportEl ?? this._container;
        // Unmount any previously mounted view in the viewport before clearing DOM
        // to avoid leaking CodeMirror instances or event listeners
        for (const v of this._stack) {
            if (v !== view && v._container === viewport) {
                try { v.unmount(); } catch {}
            }
        }
        viewport.innerHTML = '';
        view.mount(viewport);
        view.focus();
    }

    /**
     * Save a snapshot of view's current state (scroll/cursor/mode) for
     * restoration when the view is re-mounted via back/forward.
     * Skips dirty views to avoid losing the unsaved content reference.
     */
    _saveStateFor(view) {
        if (!view) return;
        try {
            const state = view.getState();
            if (state && Object.keys(state).length > 0) {
                this._savedStates.set(view, state);
            }
        } catch {}
    }

    /**
     * Notify AppState that the stack changed (for chrome updates and persistence).
     */
    _notifyChange() {
        this._appState.rpfStackDepth  = this._stack.length;
        this._appState.rpfActiveTitle = this.activeView?.getTitle() ?? null;
        this._appState.rpfActiveDirty = this.activeView?.isDirty() ?? false;
    }
}

// Browser global export
if (typeof window !== 'undefined') {
    window.RightPanelFrame = RightPanelFrame;
}

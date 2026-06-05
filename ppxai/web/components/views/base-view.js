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

    /**
     * Re-fetch content from disk if the file may have changed externally.
     * Override in file-backed views; default is a no-op.
     */
    async reload() {}

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

    // ── Toolbar template (v1.18.7) ─────────────────────────────────────────────
    //
    // Each view renders its own toolbar HTML in mount(). Pre-v1.18.7 every
    // subclass wrote the `<div class="rpf-view-toolbar">…</div>` literal
    // inline, which meant adding a shared button (like the download button
    // for v1.18.7) needed surgery in every view. _renderToolbar() centralises
    // the shape: subclasses pass the type-specific info text and any extra
    // buttons; the base class assembles the toolbar with the download button
    // appended when the view exposes a getPath().
    //
    // Convention: the returned HTML carries class `rpf-view-toolbar` (existing
    // CSS still applies) and the download button has class `bv-download-btn`
    // so _wireDownloadButton() can attach the click handler:
    //
    //     container.innerHTML = this._renderToolbar('Image • 12 KB',
    //         '<button class="rpf-btn">🔍 Zoom</button>') + viewBody;
    //     this._wireDownloadButton(container);
    //
    // Pass `download: false` to suppress the download button (e.g. for the
    // terminal view which isn't backed by a downloadable file).

    /**
     * Render the standard toolbar HTML.
     * @param {string} infoText     Short label rendered into <span class="rpf-view-info">. Pre-escaped.
     * @param {string} extras       HTML for view-specific extra buttons (zoom, slide nav, etc.). Pre-escaped.
     * @param {object} opts
     * @param {boolean} opts.download  Show the download button. Default: true when getPath() is non-null.
     * @returns {string} HTML for the toolbar (caller embeds it into container.innerHTML).
     */
    _renderToolbar(infoText, extras = '', opts = {}) {
        const path = this.getPath();
        const showDownload = opts.download ?? (path != null);
        const downloadBtn = showDownload
            ? `<button class="rpf-btn bv-download-btn" title="Download file">⬇ Download</button>`
            : '';
        return `<div class="rpf-view-toolbar">`
            + `<span class="rpf-view-info">${infoText}</span>`
            + extras
            + downloadBtn
            + `</div>`;
    }

    /**
     * Wire up the download button rendered by _renderToolbar().
     *
     * Caller (subclass mount()) calls this AFTER setting container.innerHTML.
     * Looks for `.bv-download-btn` inside the container and, on click,
     * delegates to PpxaiApp.onFileDownload(path, cwdAnchor) — the same
     * entry point the file-tree download icon uses. Single download
     * implementation, two call sites.
     *
     * @param {HTMLElement} container
     */
    _wireDownloadButton(container) {
        const btn = container?.querySelector?.('.bv-download-btn');
        if (!btn) return;
        const path = this.getPath();
        if (!path) return;
        btn.addEventListener('click', () => {
            const anchor = this._cwdAnchor ?? null;
            if (window.ppxai?.onFileDownload) {
                window.ppxai.onFileDownload(path, anchor);
            } else if (window.ppxai?.apiClient?.downloadFileUrl) {
                // Fallback: direct navigation. Browser-native download dialog.
                const url = window.ppxai.apiClient.downloadFileUrl(path, anchor);
                const a = document.createElement('a');
                a.href = url;
                a.download = path.split('/').pop();
                a.style.display = 'none';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            }
        });
    }
}

// Browser global export
if (typeof window !== 'undefined') {
    window.BaseView = BaseView;
}

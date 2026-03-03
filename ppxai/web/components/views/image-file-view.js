/**
 * ImageFileView — image preview for the RightPanelFrame.
 *
 * Fetches the file from the server and displays it as an <img>.
 * Supports basic zoom: click to toggle full-size / contain.
 *
 * @version 1.16.2
 */
class ImageFileView extends BaseView {
    /**
     * @param {string} relPath   - Relative path within the working directory
     * @param {object} appState  - AppState singleton (provides apiClient)
     */
    constructor(relPath, appState) {
        super();
        this._path     = relPath;
        this._appState = appState;
        this._container = null;
        this._zoomed   = false;
    }

    // ── BaseView protocol ─────────────────────────────────────────────────────

    getTitle() {
        const parts = this._path.split('/');
        return parts[parts.length - 1];
    }

    getPath() { return this._path; }

    getIcon() { return '🖼'; }

    async mount(container) {
        this._container = container;
        container.innerHTML = '<div class="rpf-loading">Loading image…</div>';

        try {
            const data = await this._appState.apiClient.readFile(this._path);
            if (data.type !== 'image') {
                container.innerHTML = `<div class="rpf-error">Not an image: ${_ifvEsc(this._path)}</div>`;
                return;
            }

            const sizeStr = data.size > 1024 * 1024
                ? `${(data.size / 1024 / 1024).toFixed(2)} MB`
                : `${(data.size / 1024).toFixed(1)} KB`;

            const dataUrl = `data:${data.mime_type};base64,${data.content}`;

            container.innerHTML = `
                <div class="rpf-view-toolbar">
                    <span class="rpf-view-info">Image • ${_ifvEsc(sizeStr)}</span>
                    <button class="rpf-btn ifv-zoom-btn" title="Toggle zoom">🔍 Zoom</button>
                </div>
                <div class="ifv-img-wrapper">
                    <img class="ifv-img" src="${_ifvEsc(dataUrl)}"
                         alt="${_ifvEsc(this.getTitle())}"
                         title="Click to toggle zoom">
                </div>
            `;

            const img = container.querySelector('.ifv-img');
            const zoomBtn = container.querySelector('.ifv-zoom-btn');

            const toggleZoom = () => {
                this._zoomed = !this._zoomed;
                img.style.maxWidth  = this._zoomed ? 'none' : '100%';
                img.style.maxHeight = this._zoomed ? 'none' : '100%';
                zoomBtn.textContent = this._zoomed ? '🔍 Fit' : '🔍 Zoom';
            };

            img.addEventListener('click', toggleZoom);
            zoomBtn.addEventListener('click', toggleZoom);
        } catch (err) {
            container.innerHTML = `<div class="rpf-error">Failed to load image: ${_ifvEsc(err.message)}</div>`;
        }
    }

    unmount() {
        if (this._container) {
            this._container.innerHTML = '';
            this._container = null;
        }
    }

    focus() {}
    onKeyDown(_e) { return false; }
}

function _ifvEsc(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

if (typeof window !== 'undefined') {
    window.ImageFileView = ImageFileView;
}

/**
 * PdfFileView — PDF preview for the RightPanelFrame.
 *
 * Fetches the file from the server and embeds it via <embed>.
 *
 * @version 1.16.2
 */
class PdfFileView extends BaseView {
    /**
     * @param {string} relPath   - Relative path within the working directory
     * @param {object} appState  - AppState singleton (provides apiClient)
     */
    constructor(relPath, appState) {
        super();
        this._path      = relPath;
        this._appState  = appState;
        this._container = null;
    }

    // ── BaseView protocol ─────────────────────────────────────────────────────

    getTitle() {
        const parts = this._path.split('/');
        return parts[parts.length - 1];
    }

    getPath() { return this._path; }

    getIcon() { return '📕'; }

    async mount(container) {
        this._container = container;
        container.innerHTML = '<div class="rpf-loading">Loading PDF…</div>';

        try {
            const data = await this._appState.apiClient.readFile(this._path);
            if (data.type !== 'pdf') {
                container.innerHTML = `<div class="rpf-error">Not a PDF: ${_pfvEsc(this._path)}</div>`;
                return;
            }

            const sizeStr = data.size > 1024 * 1024
                ? `${(data.size / 1024 / 1024).toFixed(2)} MB`
                : `${(data.size / 1024).toFixed(1)} KB`;

            const dataUrl = `data:application/pdf;base64,${data.content}`;

            container.innerHTML = `
                <div class="rpf-view-toolbar">
                    <span class="rpf-view-info">PDF • ${_pfvEsc(sizeStr)}</span>
                </div>
                <div class="pfv-embed-wrapper">
                    <embed src="${_pfvEsc(dataUrl)}"
                           type="application/pdf"
                           style="width:100%;height:100%;border:none;">
                </div>
            `;
        } catch (err) {
            container.innerHTML = `<div class="rpf-error">Failed to load PDF: ${_pfvEsc(err.message)}</div>`;
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

function _pfvEsc(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

if (typeof window !== 'undefined') {
    window.PdfFileView = PdfFileView;
}

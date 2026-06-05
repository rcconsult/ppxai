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
    constructor(relPath, appState, opts = {}) {
        super();
        this._path      = relPath;
        this._appState  = appState;
        // v1.18.1 Phase D: cwd_anchor for drift detection on read
        this._cwdAnchor = opts.cwdAnchor ?? null;
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
            const data = await this._appState.apiClient.readFile(this._path, this._cwdAnchor);
            if (data.type !== 'pdf') {
                container.innerHTML = `<div class="rpf-error">Not a PDF: ${_pfvEsc(this._path)}</div>`;
                return;
            }

            const sizeStr = data.size > 1024 * 1024
                ? `${(data.size / 1024 / 1024).toFixed(2)} MB`
                : `${(data.size / 1024).toFixed(1)} KB`;

            const dataUrl = `data:application/pdf;base64,${data.content}`;

            container.innerHTML = `
                ${this._renderToolbar(`PDF • ${_pfvEsc(sizeStr)}`)}
                <div class="pfv-embed-wrapper">
                    <embed src="${_pfvEsc(dataUrl)}"
                           type="application/pdf"
                           style="width:100%;height:100%;border:none;">
                </div>
            `;
            this._wireDownloadButton(container);
        } catch (err) {
            // v1.18.1 Phase D: 409 = stale cwd_anchor. Recover by
            // applying the drained events; user can click again.
            if (err.status === 409 && window.ppxai?.handleCwdAnchorMismatch) {
                if (window.ppxai.handleCwdAnchorMismatch(err)) {
                    container.innerHTML = '';
                    return;
                }
            }

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

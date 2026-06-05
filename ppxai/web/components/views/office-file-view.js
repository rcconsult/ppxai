/**
 * OfficeFileView — preview for Office documents (xlsx/csv/pptx/ppt/docx/doc).
 *
 * v1.18.7. Closes the file-tree office-preview regression. Pre-v1.18.7
 * a file-tree click on an Office file routed to CodeEditorView, which
 * called /files/read, got "Cannot read binary file" 400, and showed
 * the error in the preview pane.
 *
 * This view replaces that broken path with three rendering branches:
 *
 *   xlsx/xls/csv (kind=spreadsheet)
 *     → GET /files/read with the office_spreadsheet branch (v1.18.7)
 *       returns base64 + mime_type. Parse with SheetJS client-side,
 *       render via DataTableViewer per sheet. No server-side LibreOffice
 *       needed for spreadsheets.
 *
 *   pptx/ppt (kind=presentation)
 *     → GET /files/preview?path=...&total=true for slide count, then
 *       GET /files/preview?path=...&slide=N for each PNG. Server uses
 *       LibreOffice. If LibreOffice is missing, the metadata fetch
 *       returns `libreoffice_available: false` and we switch to
 *       text-fallback mode (per-slide JSON with extracted text).
 *
 *   docx/doc (kind=word)
 *     → GET /files/preview?path=... returns PDF bytes (LibreOffice
 *       converted server-side). Embed in <iframe>. If LibreOffice is
 *       missing, metadata fetch returns text_fallback and we render
 *       the extracted text inline.
 *
 * Design parallels the existing _renderSpreadsheetAttachment /
 * _renderPresentationAttachment / _renderWordAttachment renderers in
 * app.js — those will be refactored to delegate to this view in
 * Commit 3 (one rendering implementation, two entry points: tree
 * click + chat attachment click).
 *
 * Conventions:
 *   - extends BaseView so _renderToolbar() + _wireDownloadButton()
 *     give us the standard toolbar + download button for free
 *   - relies on apiClient.previewFileMetadata / previewFileSlideUrl /
 *     previewFileSlideJson / readFile / downloadFileUrl (all v1.18.7)
 *   - 409 cwd_anchor mismatch handled via window.ppxai.handleCwdAnchorMismatch
 *     (same pattern as ImageFileView / PdfFileView)
 *
 * @version 1.18.7
 */

const _OFV_SPREADSHEET_EXTS = new Set(['xlsx', 'xls', 'csv']);
const _OFV_PRESENTATION_EXTS = new Set(['pptx', 'ppt']);
const _OFV_WORD_EXTS = new Set(['docx', 'doc']);


class OfficeFileView extends BaseView {
    /**
     * @param {string} relPath   Relative path within the working directory
     * @param {object} appState  AppState singleton (provides apiClient)
     * @param {object} opts
     * @param {string} [opts.cwdAnchor]  cwd at click-time, for drift detection
     */
    constructor(relPath, appState, opts = {}) {
        super();
        this._path      = relPath;
        this._appState  = appState;
        this._cwdAnchor = opts.cwdAnchor ?? null;
        this._container = null;

        // Slide/page navigation state (PPTX). _kind decides which
        // render branch runs in mount().
        this._kind        = this._classify(relPath);
        this._slideCount  = 0;
        this._currentSlide = 1;

        // Track blob URLs we create so unmount() revokes them — without
        // this every slide click leaks a browser blob.
        this._blobUrls = [];
    }

    // ── BaseView protocol ─────────────────────────────────────────────────────

    getTitle() {
        const parts = this._path.split('/');
        return parts[parts.length - 1];
    }

    getPath() { return this._path; }

    getIcon() {
        if (this._kind === 'spreadsheet') return '📊';
        if (this._kind === 'presentation') return '📊';
        if (this._kind === 'word') return '📄';
        return '📄';
    }

    async mount(container) {
        this._container = container;
        container.innerHTML = '<div class="rpf-loading">Loading…</div>';

        try {
            if (this._kind === 'spreadsheet') {
                await this._mountSpreadsheet(container);
            } else if (this._kind === 'presentation') {
                await this._mountPresentation(container);
            } else if (this._kind === 'word') {
                await this._mountWord(container);
            } else {
                container.innerHTML = `<div class="rpf-error">Not an Office file: ${_ofvEsc(this._path)}</div>`;
            }
        } catch (err) {
            // v1.18.1 Phase D: 409 = stale cwd_anchor. Recover by
            // applying the drained events; user can click again.
            if (err.status === 409 && window.ppxai?.handleCwdAnchorMismatch) {
                if (window.ppxai.handleCwdAnchorMismatch(err)) {
                    container.innerHTML = '';
                    return;
                }
            }
            container.innerHTML = `<div class="rpf-error">Failed to load: ${_ofvEsc(err.message ?? String(err))}</div>`;
        }
    }

    unmount() {
        // Revoke any blob URLs we created for slide images / PDF iframe
        for (const url of this._blobUrls) {
            try { URL.revokeObjectURL(url); } catch (_) { /* ignore */ }
        }
        this._blobUrls = [];
        if (this._container) {
            this._container.innerHTML = '';
            this._container = null;
        }
    }

    focus() {}

    onKeyDown(e) {
        // Slide navigation: arrow keys page through PPTX presentations.
        if (this._kind !== 'presentation' || !this._slideCount) return false;
        if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
            if (this._currentSlide > 1) this._showSlide(this._currentSlide - 1);
            return true;
        }
        if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') {
            if (this._currentSlide < this._slideCount) this._showSlide(this._currentSlide + 1);
            return true;
        }
        return false;
    }

    // ── Branch: spreadsheet (xlsx/xls/csv) ───────────────────────────────────

    async _mountSpreadsheet(container) {
        const data = await this._appState.apiClient.readFile(this._path, this._cwdAnchor);
        if (data.type !== 'office_spreadsheet') {
            container.innerHTML = `<div class="rpf-error">Unexpected response type: ${_ofvEsc(data.type)}</div>`;
            return;
        }

        const sizeKB = (data.size / 1024).toFixed(1);
        container.innerHTML = `
            ${this._renderToolbar('Loading spreadsheet…')}
            <div class="xlsx-preview" style="flex:1; overflow:auto;"></div>
        `;
        this._wireDownloadButton(container);

        const previewEl = container.querySelector('.xlsx-preview');
        const infoEl = container.querySelector('.rpf-view-info');

        if (typeof window.XLSX === 'undefined') {
            previewEl.innerHTML = `<p style="padding:16px;color:var(--error-color);">
                SheetJS not loaded (window.XLSX missing). Check index.html script tag.</p>`;
            return;
        }

        try {
            // CSV path: SheetJS reads base64 as either ArrayBuffer or
            // text depending on extension hint; 'string' is safer for CSV.
            const isCsv = this._path.toLowerCase().endsWith('.csv');
            const wb = isCsv
                ? window.XLSX.read(atob(data.content), { type: 'string' })
                : window.XLSX.read(data.content, { type: 'base64' });

            infoEl.textContent = `${wb.SheetNames.length} sheet${wb.SheetNames.length > 1 ? 's' : ''} • ${sizeKB} KB`;

            const tabsEl = document.createElement('div');
            tabsEl.className = 'xlsx-tabs';
            previewEl.appendChild(tabsEl);

            const tableEl = document.createElement('div');
            tableEl.className = 'xlsx-table-wrapper';
            previewEl.appendChild(tableEl);

            const showSheet = (idx) => {
                tabsEl.querySelectorAll('.xlsx-tab').forEach((t, i) => {
                    t.classList.toggle('active', i === idx);
                });
                const ws = wb.Sheets[wb.SheetNames[idx]];
                const json = window.XLSX.utils.sheet_to_json(ws, { header: 1, defval: '' });
                if (!json.length) {
                    tableEl.innerHTML = '<p style="padding:16px;color:var(--text-muted);">Empty sheet</p>';
                    return;
                }
                const headers = json[0].map(h => String(h));
                const rows = json.slice(1).map(r => r.map(c => String(c)));
                tableEl.innerHTML = '';
                if (typeof DataTableViewer !== 'undefined') {
                    new DataTableViewer(tableEl, {
                        headers, rows, rowCount: rows.length,
                    }, {
                        maxHeight: 'none', pageSize: 200,
                        sortable: true, filterable: true, showRowNumbers: true,
                    });
                } else {
                    // Fallback: minimal HTML table if DataTableViewer absent.
                    tableEl.innerHTML = _ofvBuildTableHtml(headers, rows);
                }
            };

            wb.SheetNames.forEach((sn, i) => {
                const tab = document.createElement('button');
                tab.className = 'xlsx-tab';
                tab.textContent = sn;
                tab.addEventListener('click', () => showSheet(i));
                tabsEl.appendChild(tab);
            });
            showSheet(0);
        } catch (e) {
            previewEl.innerHTML = `<p style="padding:16px;color:var(--error-color);">
                Failed to parse spreadsheet: ${_ofvEsc(e.message)}</p>`;
        }
    }

    // ── Branch: presentation (pptx/ppt) ──────────────────────────────────────

    async _mountPresentation(container) {
        const meta = await this._appState.apiClient.previewFileMetadata(this._path, this._cwdAnchor);
        this._slideCount = meta.total;

        const navHtml = `
            <button class="rpf-btn ofv-nav-prev" title="Previous slide">◀</button>
            <span class="ofv-slide-counter">Slide <span class="ofv-current">1</span> / ${meta.total}</span>
            <button class="rpf-btn ofv-nav-next" title="Next slide">▶</button>
        `;
        const infoStr = `${meta.total} slide${meta.total !== 1 ? 's' : ''}`
            + (meta.libreoffice_available === false ? ' • text fallback' : '');

        container.innerHTML = `
            ${this._renderToolbar(_ofvEsc(infoStr), navHtml)}
            <div class="pptx-preview" style="flex:1; display:flex; flex-direction:column; overflow:hidden;">
                <div class="pptx-slide-container" style="flex:1; overflow:auto;"></div>
            </div>
        `;
        this._wireDownloadButton(container);

        const prevBtn = container.querySelector('.ofv-nav-prev');
        const nextBtn = container.querySelector('.ofv-nav-next');
        prevBtn.addEventListener('click', () => {
            if (this._currentSlide > 1) this._showSlide(this._currentSlide - 1);
        });
        nextBtn.addEventListener('click', () => {
            if (this._currentSlide < this._slideCount) this._showSlide(this._currentSlide + 1);
        });

        this._libreofficeOk = meta.libreoffice_available !== false;
        this._showSlide(1);
    }

    async _showSlide(n) {
        const container = this._container;
        if (!container) return;
        this._currentSlide = n;

        const counterEl = container.querySelector('.ofv-current');
        const prevBtn   = container.querySelector('.ofv-nav-prev');
        const nextBtn   = container.querySelector('.ofv-nav-next');
        const slideEl   = container.querySelector('.pptx-slide-container');
        if (!slideEl) return;

        if (counterEl) counterEl.textContent = n;
        if (prevBtn) prevBtn.disabled = n <= 1;
        if (nextBtn) nextBtn.disabled = n >= this._slideCount;

        slideEl.innerHTML = '<p style="padding:16px;color:var(--text-muted);">Rendering…</p>';

        if (this._libreofficeOk) {
            // PNG raster path. Construct the URL and fetch with auth
            // headers so we get bytes — then convert to a blob URL
            // for an <img>. Pre-v1.18.7 the attachment renderer used
            // .getHeaders() the same way; we keep that pattern.
            const url = this._appState.apiClient.previewFileSlideUrl(this._path, n, this._cwdAnchor);
            try {
                const resp = await fetch(url, { headers: this._appState.apiClient.getHeaders() });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const blob = await resp.blob();
                const blobUrl = URL.createObjectURL(blob);
                this._blobUrls.push(blobUrl);
                slideEl.innerHTML = '';
                const img = new Image();
                img.className = 'pptx-slide-img';
                img.alt = `Slide ${n}`;
                img.src = blobUrl;
                img.style.maxWidth = '100%';
                slideEl.appendChild(img);
            } catch (err) {
                slideEl.innerHTML = `<p style="padding:16px;color:var(--error-color);">
                    Failed to render slide ${n}: ${_ofvEsc(err.message ?? String(err))}</p>`;
            }
        } else {
            // Text-fallback path. JSON body carries markdown content.
            try {
                const data = await this._appState.apiClient.previewFileSlideJson(this._path, n, this._cwdAnchor);
                slideEl.innerHTML = `
                    <div class="ofv-text-fallback" style="padding:16px;">
                        <div class="ofv-fallback-note" style="margin-bottom:12px;padding:8px;background:var(--bg-tertiary);border-radius:4px;font-size:12px;color:var(--text-muted);">
                            LibreOffice not installed — showing extracted text. Install LibreOffice for raster slide previews.
                        </div>
                        <pre style="white-space:pre-wrap;font-family:var(--font-mono);font-size:13px;">${_ofvEsc(data.content || '(empty)')}</pre>
                    </div>
                `;
            } catch (err) {
                slideEl.innerHTML = `<p style="padding:16px;color:var(--error-color);">
                    Failed to load slide ${n} text: ${_ofvEsc(err.message ?? String(err))}</p>`;
            }
        }
    }

    // ── Branch: word (docx/doc) ──────────────────────────────────────────────

    async _mountWord(container) {
        const meta = await this._appState.apiClient.previewFileMetadata(this._path, this._cwdAnchor);
        const libreofficeOk = meta.libreoffice_available !== false;
        const infoStr = libreofficeOk ? 'Word Document' : 'Word Document • text fallback';

        container.innerHTML = `
            ${this._renderToolbar(_ofvEsc(infoStr))}
            <div class="docx-preview" style="flex:1; min-height:0;"></div>
        `;
        this._wireDownloadButton(container);

        const previewEl = container.querySelector('.docx-preview');

        if (libreofficeOk) {
            // PDF iframe path. Fetch with auth headers, blob it, embed.
            const url = this._appState.apiClient.previewFileSlideUrl(this._path, 1, this._cwdAnchor);
            try {
                const resp = await fetch(url, { headers: this._appState.apiClient.getHeaders() });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const blob = await resp.blob();
                const blobUrl = URL.createObjectURL(blob);
                this._blobUrls.push(blobUrl);
                previewEl.innerHTML = `<iframe src="${blobUrl}"
                    style="width:100%;height:100%;border:none;"></iframe>`;
            } catch (err) {
                previewEl.innerHTML = `<div style="padding:24px;color:var(--text-secondary);">
                    <h3 style="margin-bottom:12px;color:var(--text-primary);">${_ofvEsc(this.getTitle())}</h3>
                    <p style="font-size:13px;opacity:0.85;">PDF conversion unavailable: ${_ofvEsc(err.message ?? String(err))}</p>
                </div>`;
            }
        } else {
            // Text-fallback path. Metadata response from /files/preview?total=true
            // does NOT carry the extracted text — that comes from the
            // per-slide endpoint. For Word, slide=1 returns the whole doc.
            try {
                const data = await this._appState.apiClient.previewFileSlideJson(this._path, 1, this._cwdAnchor);
                previewEl.innerHTML = `
                    <div class="ofv-text-fallback" style="padding:16px;overflow:auto;height:100%;">
                        <div class="ofv-fallback-note" style="margin-bottom:12px;padding:8px;background:var(--bg-tertiary);border-radius:4px;font-size:12px;color:var(--text-muted);">
                            LibreOffice not installed — showing extracted text. Install LibreOffice for a rendered PDF preview.
                        </div>
                        <pre style="white-space:pre-wrap;font-family:var(--font-mono);font-size:13px;">${_ofvEsc(data.content || '(empty)')}</pre>
                    </div>
                `;
            } catch (err) {
                previewEl.innerHTML = `<p style="padding:16px;color:var(--error-color);">
                    Failed to load document text: ${_ofvEsc(err.message ?? String(err))}</p>`;
            }
        }
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    _classify(path) {
        const ext = (path.split('.').pop() || '').toLowerCase();
        if (_OFV_SPREADSHEET_EXTS.has(ext))  return 'spreadsheet';
        if (_OFV_PRESENTATION_EXTS.has(ext)) return 'presentation';
        if (_OFV_WORD_EXTS.has(ext))         return 'word';
        return 'unknown';
    }

    /**
     * Static helper: is the given path a kind OfficeFileView can render?
     * Used by displayFileFromEvent dispatcher (Commit 3) to choose this
     * view over CodeEditorView for office extensions.
     */
    static canRender(path) {
        const ext = (path.split('.').pop() || '').toLowerCase();
        return _OFV_SPREADSHEET_EXTS.has(ext)
            || _OFV_PRESENTATION_EXTS.has(ext)
            || _OFV_WORD_EXTS.has(ext);
    }
}

function _ofvEsc(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _ofvBuildTableHtml(headers, rows) {
    const head = '<tr>' + headers.map(h => `<th>${_ofvEsc(h)}</th>`).join('') + '</tr>';
    const body = rows.slice(0, 200).map(r =>
        '<tr>' + r.map(c => `<td>${_ofvEsc(c)}</td>`).join('') + '</tr>'
    ).join('');
    return `<table class="ofv-fallback-table" style="border-collapse:collapse;">
        <thead>${head}</thead><tbody>${body}</tbody></table>`;
}

if (typeof window !== 'undefined') {
    window.OfficeFileView = OfficeFileView;
}

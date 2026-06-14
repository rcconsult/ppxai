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
        // Static-helper revoke handles (PPTX slide nav, DOCX iframe).
        if (this._slideNavRevoke) { this._slideNavRevoke(); this._slideNavRevoke = null; }
        if (this._docxPdfRevoke)  { this._docxPdfRevoke();  this._docxPdfRevoke  = null; }
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
        const infoEl    = container.querySelector('.rpf-view-info');
        const isCsv     = this._path.toLowerCase().endsWith('.csv');
        // Delegate to the shared render helper so the chat-attachment
        // renderer in app.js produces an identical UI from its own
        // base64 fetch path. One render implementation, two entry points.
        OfficeFileView.renderSheetJsInto(previewEl, infoEl, data.content, isCsv, sizeKB);
    }

    // ── Branch: presentation (pptx/ppt) ──────────────────────────────────────

    async _mountPresentation(container) {
        const meta = await this._appState.apiClient.previewFileMetadata(this._path, this._cwdAnchor);
        this._slideCount = meta.total;
        this._libreofficeOk = meta.libreoffice_available !== false;

        const infoStr = `${meta.total} slide${meta.total !== 1 ? 's' : ''}`
            + (this._libreofficeOk ? '' : ' • text fallback');

        container.innerHTML = `
            ${this._renderToolbar(_ofvEsc(infoStr))}
            <div class="pptx-preview" style="flex:1; display:flex; flex-direction:column; overflow:hidden;"></div>
        `;
        this._wireDownloadButton(container);
        const previewEl = container.querySelector('.pptx-preview');

        if (this._libreofficeOk) {
            // Delegate slide-nav UI to the shared static helper. The
            // chat-attachment renderer in app.js uses the SAME helper
            // with a file_id-based fetchSlide closure; both paths get
            // an identical nav UI.
            const fetchSlide = async (n) => {
                const url = this._appState.apiClient.previewFileSlideUrl(this._path, n, this._cwdAnchor);
                const resp = await fetch(url, { headers: this._appState.apiClient.getHeaders() });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                return resp.blob();
            };
            const handle = OfficeFileView.renderSlideNavInto(previewEl, this._slideCount, fetchSlide);
            // Wire revoke into our unmount cleanup
            this._slideNavRevoke = handle.revoke;
            // Track current slide for keyboard nav (onKeyDown). The
            // shared helper owns the counter element directly, so we
            // observe via the DOM rather than threading state through.
            previewEl.addEventListener('click', () => {
                const counterEl = previewEl.querySelector('.ofv-current');
                if (counterEl) this._currentSlide = parseInt(counterEl.textContent, 10) || 1;
            });
        } else {
            // Text-fallback path — render a per-slide nav that fetches
            // JSON instead of binary PNG. Distinct UI from the static
            // helper because the rendering target is markdown text,
            // not an <img>.
            this._mountPresentationTextFallback(previewEl);
        }
    }

    _mountPresentationTextFallback(previewEl) {
        previewEl.innerHTML = `
            <div class="pptx-nav">
                <button class="rpf-btn ofv-nav-prev" title="Previous slide">◀</button>
                <span class="pptx-slide-counter">Slide <span class="ofv-current">1</span> / ${this._slideCount}</span>
                <button class="rpf-btn ofv-nav-next" title="Next slide">▶</button>
            </div>
            <div class="pptx-slide-container" style="flex:1; overflow:auto;"></div>
        `;
        const counterEl = previewEl.querySelector('.ofv-current');
        const prevBtn   = previewEl.querySelector('.ofv-nav-prev');
        const nextBtn   = previewEl.querySelector('.ofv-nav-next');
        const slideEl   = previewEl.querySelector('.pptx-slide-container');

        const showTextSlide = async (n) => {
            this._currentSlide = n;
            counterEl.textContent = n;
            prevBtn.disabled = n <= 1;
            nextBtn.disabled = n >= this._slideCount;
            slideEl.innerHTML = '<p style="padding:16px;color:var(--text-muted);">Loading…</p>';
            try {
                const data = await this._appState.apiClient.previewFileSlideJson(this._path, n, this._cwdAnchor);
                slideEl.innerHTML = `
                    <div class="ofv-text-fallback" style="padding:16px;">
                        <div class="ofv-fallback-note" style="margin-bottom:12px;padding:8px;background:var(--bg-tertiary);border-radius:4px;font-size:12px;color:var(--text-muted);">
                            LibreOffice not installed — showing extracted text. Install LibreOffice for raster slide previews.
                        </div>
                        <pre style="white-space:pre-wrap;font-family:var(--font-mono);font-size:13px;">${typeof data.content === 'string' ? _ofvEsc(data.content) : '⚠ preview response missing "content" key'}</pre>
                    </div>
                `;
            } catch (err) {
                slideEl.innerHTML = `<p style="padding:16px;color:var(--error-color);">
                    Failed to load slide ${n} text: ${_ofvEsc(err.message ?? String(err))}</p>`;
            }
        };
        prevBtn.addEventListener('click', () => {
            if (this._currentSlide > 1) showTextSlide(this._currentSlide - 1);
        });
        nextBtn.addEventListener('click', () => {
            if (this._currentSlide < this._slideCount) showTextSlide(this._currentSlide + 1);
        });
        this._showTextSlide = showTextSlide;  // used by onKeyDown
        showTextSlide(1);
    }

    _showSlide(n) {
        // Keyboard navigation entry. Branches the same way mount did:
        // when LibreOffice is OK, click the rendered nav buttons (the
        // static helper owns its handlers); when text-fallback, drive
        // the local showTextSlide closure.
        if (!this._libreofficeOk) {
            if (this._showTextSlide) this._showTextSlide(n);
            return;
        }
        const container = this._container;
        if (!container) return;
        if (n < this._currentSlide) {
            const prev = container.querySelector('.ofv-nav-prev');
            if (prev) prev.click();
        } else if (n > this._currentSlide) {
            const next = container.querySelector('.ofv-nav-next');
            if (next) next.click();
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
            // Fetch PDF blob, delegate iframe embed to the shared helper.
            const url = this._appState.apiClient.previewFileSlideUrl(this._path, 1, this._cwdAnchor);
            try {
                const resp = await fetch(url, { headers: this._appState.apiClient.getHeaders() });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const blob = await resp.blob();
                const handle = OfficeFileView.renderDocxPdfInto(previewEl, blob);
                this._docxPdfRevoke = handle.revoke;
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
                        <pre style="white-space:pre-wrap;font-family:var(--font-mono);font-size:13px;">${typeof data.content === 'string' ? _ofvEsc(data.content) : '⚠ preview response missing "content" key'}</pre>
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

    // ── Static render helpers (v1.18.7 Commit 3) ─────────────────────────────
    //
    // The chat-attachment renderers in PpxaiApp need the SAME visual output
    // as this view but get their data via a different fetch path
    // (SessionFileStore file_id, not a working-dir path). Extracting the
    // rendering primitives as static helpers lets both call sites share one
    // implementation. Each helper takes a pre-fetched data shape; the
    // caller decides how to fetch.

    /**
     * Render a SheetJS spreadsheet into the given content element.
     * @param {HTMLElement} contentEl    Element to fill with the rendered table.
     * @param {HTMLElement} infoEl       Element whose textContent will be updated with
     *                                   the "N sheets • size" label.
     * @param {string} b64               Base64-encoded file content.
     * @param {boolean} isCsv            Whether to read as CSV (string) vs binary.
     * @param {string} sizeKB            Pre-formatted size string (e.g. "12.3 KB").
     */
    static renderSheetJsInto(contentEl, infoEl, b64, isCsv, sizeKB) {
        if (typeof window.XLSX === 'undefined') {
            contentEl.innerHTML = `<p style="padding:16px;color:var(--error-color);">
                SheetJS not loaded (window.XLSX missing).</p>`;
            return;
        }
        try {
            const wb = isCsv
                ? window.XLSX.read(atob(b64), { type: 'string' })
                : window.XLSX.read(b64, { type: 'base64' });
            if (infoEl) {
                infoEl.textContent = `${wb.SheetNames.length} sheet${wb.SheetNames.length > 1 ? 's' : ''} • ${sizeKB} KB`;
            }
            const tabsEl = document.createElement('div');
            tabsEl.className = 'xlsx-tabs';
            contentEl.appendChild(tabsEl);
            const tableEl = document.createElement('div');
            tableEl.className = 'xlsx-table-wrapper';
            contentEl.appendChild(tableEl);

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
                    new DataTableViewer(tableEl, { headers, rows, rowCount: rows.length }, {
                        maxHeight: 'none', pageSize: 200,
                        sortable: true, filterable: true, showRowNumbers: true,
                    });
                } else {
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
            contentEl.innerHTML = `<p style="padding:16px;color:var(--error-color);">
                Failed to parse spreadsheet: ${_ofvEsc(e.message)}</p>`;
        }
    }

    /**
     * Render a slide-navigation UI into the given preview element.
     * @param {HTMLElement} previewEl    Element to fill with nav + slide container.
     * @param {number} total             Total slide count.
     * @param {Function} fetchSlideBlob  async (n) => Blob — caller's fetch implementation.
     * @returns {{revoke: Function}}    Object with a revoke() that revokes
     *                                   accumulated blob URLs. Caller wires this into
     *                                   AttachmentView.unmount to avoid leaks.
     */
    static renderSlideNavInto(previewEl, total, fetchSlideBlob) {
        const blobUrls = [];
        const nav = document.createElement('div');
        nav.className = 'pptx-nav';
        nav.innerHTML = `
            <button class="rpf-btn ofv-nav-prev" title="Previous slide">◀</button>
            <span class="pptx-slide-counter">Slide <span class="ofv-current">1</span> / ${total}</span>
            <button class="rpf-btn ofv-nav-next" title="Next slide">▶</button>`;
        previewEl.appendChild(nav);

        const imgContainer = document.createElement('div');
        imgContainer.className = 'pptx-slide-container';
        previewEl.appendChild(imgContainer);

        const counterEl = nav.querySelector('.ofv-current');
        const prevBtn = nav.querySelector('.ofv-nav-prev');
        const nextBtn = nav.querySelector('.ofv-nav-next');

        let current = 1;
        let disposed = false;  // set by revoke(); guards the await→createObjectURL race
        const showSlide = async (n) => {
            current = n;
            counterEl.textContent = n;
            prevBtn.disabled = n <= 1;
            nextBtn.disabled = n >= total;
            imgContainer.innerHTML = '<p style="padding:16px;color:var(--text-muted);">Rendering…</p>';
            try {
                const blob = await fetchSlideBlob(n);
                // If the view was revoked/unmounted while this fetch was in
                // flight, do NOT create an object URL — revoke() already ran
                // over an empty blobUrls list, so a URL made now would leak.
                if (disposed) return;
                const url = URL.createObjectURL(blob);
                blobUrls.push(url);
                const img = new Image();
                img.className = 'pptx-slide-img';
                img.alt = `Slide ${n}`;
                img.src = url;
                img.style.maxWidth = '100%';
                imgContainer.innerHTML = '';
                imgContainer.appendChild(img);
            } catch (err) {
                if (disposed) return;
                imgContainer.innerHTML = `<p style="padding:16px;color:var(--error-color);">
                    Failed to load slide ${n}: ${_ofvEsc(err.message ?? String(err))}</p>`;
            }
        };
        prevBtn.addEventListener('click', () => { if (current > 1) showSlide(current - 1); });
        nextBtn.addEventListener('click', () => { if (current < total) showSlide(current + 1); });
        showSlide(1);

        return {
            revoke: () => {
                disposed = true;
                for (const u of blobUrls) {
                    try { URL.revokeObjectURL(u); } catch (_) { /* ignore */ }
                }
                blobUrls.length = 0;
            },
        };
    }

    /**
     * Render a Word document as an iframe-embedded PDF.
     * @param {HTMLElement} previewEl    Element to fill with the iframe.
     * @param {Blob} pdfBlob             The PDF blob.
     * @returns {{revoke: Function}}    Caller wires revoke() into unmount.
     */
    static renderDocxPdfInto(previewEl, pdfBlob) {
        const url = URL.createObjectURL(pdfBlob);
        previewEl.innerHTML = `<iframe src="${url}"
            style="width:100%;height:100%;border:none;"></iframe>`;
        return {
            revoke: () => {
                try { URL.revokeObjectURL(url); } catch (_) { /* ignore */ }
            },
        };
    }

    /**
     * Render the LibreOffice-missing **text fallback** for an office doc:
     * a per-unit nav (hidden when total <= 1) that fetches extracted text.
     * Used by both the file-tree path and the chat-attachment path (app.js)
     * so they degrade identically once /files/preview returns text_fallback.
     *
     * Creates NO blob URLs, so the returned revoke() is a no-op — but it
     * keeps the same `{revoke}` contract as renderSlideNavInto/renderDocxPdfInto
     * so callers wire unmount cleanup uniformly.
     *
     * @param {HTMLElement} previewEl
     * @param {number} total                  Unit count (slides; 1 for Word).
     * @param {(n:number)=>Promise<string>} fetchUnitText  Resolves to the
     *        extracted text for unit n. MUST throw if the response is missing
     *        its `content` key (surfaces contract drift instead of "(empty)").
     * @returns {{revoke: Function}}
     */
    static renderTextFallbackInto(previewEl, total, fetchUnitText) {
        const unitTotal = total > 0 ? total : 1;
        previewEl.innerHTML = `
            <div class="pptx-nav"${unitTotal <= 1 ? ' style="display:none;"' : ''}>
                <button class="rpf-btn ofv-nav-prev" title="Previous">◀</button>
                <span class="pptx-slide-counter">Slide <span class="ofv-current">1</span> / ${unitTotal}</span>
                <button class="rpf-btn ofv-nav-next" title="Next">▶</button>
            </div>
            ${_ofvLibreOfficeInstallCard()}
            <div class="pptx-slide-container" style="flex:1; overflow:auto;"></div>`;
        const counterEl = previewEl.querySelector('.ofv-current');
        const prevBtn   = previewEl.querySelector('.ofv-nav-prev');
        const nextBtn   = previewEl.querySelector('.ofv-nav-next');
        const slideEl   = previewEl.querySelector('.pptx-slide-container');

        let current = 1;
        const show = async (n) => {
            current = n;
            if (counterEl) counterEl.textContent = n;
            if (prevBtn) prevBtn.disabled = n <= 1;
            if (nextBtn) nextBtn.disabled = n >= unitTotal;
            slideEl.innerHTML = '<p style="padding:16px;color:var(--text-muted);">Loading…</p>';
            try {
                const text = await fetchUnitText(n);
                slideEl.innerHTML = `<pre style="white-space:pre-wrap;font-family:var(--font-mono);font-size:13px;padding:16px;">${_ofvEsc(text)}</pre>`;
            } catch (err) {
                slideEl.innerHTML = `<p style="padding:16px;color:var(--error-color);">
                    Failed to load text: ${_ofvEsc(err.message ?? String(err))}</p>`;
            }
        };
        if (prevBtn) prevBtn.addEventListener('click', () => { if (current > 1) show(current - 1); });
        if (nextBtn) nextBtn.addEventListener('click', () => { if (current < unitTotal) show(current + 1); });
        show(1);

        return { revoke: () => { /* text fallback creates no blob URLs */ } };
    }
}

function _ofvEsc(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _ofvDetectOS() {
    const p = (navigator.userAgentData?.platform
        || navigator.platform || navigator.userAgent || '').toLowerCase();
    if (p.includes('mac')) return 'mac';
    if (p.includes('win')) return 'win';
    if (p.includes('linux') || p.includes('x11')) return 'linux';
    return 'other';
}

// Formatted, platform-aware "install LibreOffice" card shown above the
// text fallback when the server reports libreoffice_available:false. The
// rendered preview pipeline shells out to LibreOffice headless; a plain
// system install is enough (detection covers PATH + the macOS .app bundle).
function _ofvLibreOfficeInstallCard() {
    const os = _ofvDetectOS();
    const CMD = {
        mac:   { label: 'or via Homebrew', code: 'brew install --cask libreoffice' },
        linux: { label: 'or via your package manager (Debian/Ubuntu)', code: 'sudo apt install libreoffice' },
    };
    const c = CMD[os];
    const cmdBlock = c ? `
        <div style="font-size:11px;color:var(--text-muted);margin:10px 0 4px;">${c.label}:</div>
        <pre style="margin:0;padding:8px 10px;background:var(--bg-primary,rgba(0,0,0,0.25));border-radius:6px;
            font-family:var(--font-mono);font-size:12px;overflow:auto;"><code>${_ofvEsc(c.code)}</code></pre>` : '';
    return `
        <div class="ofv-install-card" style="margin:12px 16px;padding:14px 16px;
            background:var(--bg-tertiary);border:1px solid var(--border-color,rgba(255,255,255,0.10));border-radius:8px;">
            <div style="font-weight:600;font-size:13px;color:var(--text-primary);margin-bottom:6px;">
                📊 Install LibreOffice for rendered previews
            </div>
            <div style="font-size:12px;color:var(--text-muted);line-height:1.5;margin-bottom:12px;">
                Slides and documents are rendered to images by <strong>LibreOffice</strong>
                (free &amp; open-source, runs headless in the background). A plain system
                install is all that's needed.
            </div>
            <a href="https://www.libreoffice.org/download/" target="_blank" rel="noopener"
               style="display:inline-block;padding:8px 16px;background:var(--accent-color,#4ea1ff);
               color:#fff;font-size:13px;font-weight:600;border-radius:6px;text-decoration:none;">
                ⬇ Download LibreOffice
            </a>
            ${cmdBlock}
            <div style="font-size:11px;color:var(--text-muted);margin-top:12px;opacity:0.85;">
                Previews appear automatically after install — no restart needed. The extracted text is shown below meanwhile.
            </div>
        </div>`;
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

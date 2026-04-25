/**
 * MarkdownFileView — Markdown preview with rendered / source / edit toggle.
 *
 * Modes:
 *   rendered — parsed with marked.js, syntax-highlighted code blocks via hljs
 *   source   — read-only CodeMirror / <pre> with markdown highlighting
 *   edit     — editable CodeMirror / <textarea>, Ctrl/Cmd+S to save
 *
 * Switching from edit to rendered/source after an unsaved change prompts the
 * user. After a successful save, the rendered view re-parses from updated
 * content so it reflects the latest state.
 *
 * Relative link clicks navigate via window.ppxai.displayFileFromEvent().
 *
 * @version 1.16.2
 */
class MarkdownFileView extends BaseView {
    /**
     * @param {string} relPath   - Relative path within the working directory
     * @param {object} appState  - AppState singleton (provides apiClient, theme)
     */
    constructor(relPath, appState, opts = {}) {
        super();
        this._path     = relPath;
        this._appState = appState;
        // v1.18.1 Phase D: cwd_anchor for drift detection on read
        this._cwdAnchor = opts.cwdAnchor ?? null;
        this._mode     = 'rendered';  // 'rendered' | 'source' | 'edit'

        this._container      = null;
        this._editor         = null;  // cm6 view or shim
        this._content        = null;  // content as loaded / last saved
        this._originalContent = null;
        this._lines          = 0;
        this._statusEl       = null;
        this._saveKeyHandler = null;
    }

    // ── BaseView protocol ─────────────────────────────────────────────────────

    getTitle() { return this._path.split('/').pop(); }

    getPath() { return this._path; }

    getIcon() { return '📝'; }

    async mount(container) {
        this._container = container;
        container.innerHTML = '<div class="rpf-loading">Loading…</div>';
        try {
            const data = await this._appState.apiClient.readFile(this._path, this._cwdAnchor);
            this._content         = data.content ?? '';
            this._originalContent = this._content;
            this._lines           = data.lines ?? this._content.split('\n').length;
        } catch (err) {
            // v1.18.1 Phase D: 409 = stale cwd_anchor. Recover by
            // applying the drained events; user can click again.
            if (err.status === 409 && window.ppxai?.handleCwdAnchorMismatch) {
                if (window.ppxai.handleCwdAnchorMismatch(err)) {
                    container.innerHTML = '';
                    return;
                }
            }

            container.innerHTML = `<div class="rpf-error">Failed to load: ${_mfvEsc(err.message)}</div>`;
            return;
        }
        this._buildUI();
    }

    unmount() {
        if (this._saveKeyHandler) {
            document.removeEventListener('keydown', this._saveKeyHandler, true);
            this._saveKeyHandler = null;
        }
        this._destroyEditor();
        if (this._container) {
            this._container.innerHTML = '';
            this._container = null;
        }
    }

    focus()      { this._editor?.focus?.(); }
    onActivate() { if (this._mode !== 'rendered') this._editor?.focus?.(); }
    onKeyDown()  { return false; }

    getState() {
        const el = this._container?.querySelector('.mfv-content');
        // Store 'rendered' instead of 'edit' so re-mount opens in read mode
        const mode = this._mode === 'edit' ? 'rendered' : this._mode;
        return { mode, scrollTop: el?.scrollTop ?? 0 };
    }

    setState(state) {
        if (state.mode && state.mode !== this._mode) this._switchMode(state.mode);
        if (state.scrollTop > 0) {
            setTimeout(() => {
                const el = this._container?.querySelector('.mfv-content');
                if (el) el.scrollTop = state.scrollTop;
            }, 50);
        }
    }

    isDirty() {
        if (this._mode !== 'edit') return false;
        return this._currentContent() !== this._originalContent;
    }

    // ── Save ──────────────────────────────────────────────────────────────────

    async save() {
        if (this._mode !== 'edit') return;
        const content = this._currentContent();
        this._setStatus('Saving…');
        try {
            await this._appState.apiClient.writeFile(this._path, content);
            this._originalContent = content;
            this._content         = content;
            this._setStatus('✓ Saved', 2000);
        } catch (err) {
            this._setStatus(`✗ ${err.message}`, 4000);
        }
    }

    // ── Private ───────────────────────────────────────────────────────────────

    _buildUI() {
        if (!this._container) return;

        const isEdit     = this._mode === 'edit';
        const isSource   = this._mode === 'source';
        const isRendered = this._mode === 'rendered';

        this._container.innerHTML = `
            <div class="rpf-view-toolbar">
                <button class="rpf-btn${isRendered ? ' active' : ''} mfv-btn-rendered" title="Rendered view">📖 Rendered</button>
                <button class="rpf-btn${isSource   ? ' active' : ''} mfv-btn-source"   title="View source">📄 Source</button>
                <button class="rpf-btn${isEdit     ? ' active' : ''} mfv-btn-edit"     title="Edit source">✏️ Edit</button>
                ${isEdit ? '<button class="rpf-btn mfv-btn-save" title="Save (Ctrl+S)">💾 Save</button>' : ''}
                <span class="rpf-view-info">${_mfvEsc(this._lines + ' lines')}</span>
                <span class="ev-status mfv-status"></span>
            </div>
            <div class="mfv-content"></div>
        `;

        this._statusEl = this._container.querySelector('.mfv-status');
        const contentEl = this._container.querySelector('.mfv-content');

        this._container.querySelector('.mfv-btn-rendered').addEventListener('click', () => this._switchMode('rendered'));
        this._container.querySelector('.mfv-btn-source').addEventListener('click',   () => this._switchMode('source'));
        this._container.querySelector('.mfv-btn-edit').addEventListener('click',     () => this._switchMode('edit'));

        if (isEdit) {
            this._container.querySelector('.mfv-btn-save').addEventListener('click', () => this.save());
            this._saveKeyHandler = (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); this.save(); }
            };
            document.addEventListener('keydown', this._saveKeyHandler, true);
        }

        if (isRendered) {
            this._renderMarkdown(contentEl);
        } else {
            this._renderCode(contentEl, isEdit);
        }

        // Apply state saved by frame before this mount (scroll position, mode)
        this._applyPendingState();
    }

    _renderMarkdown(contentEl) {
        const content = this._content ?? '';
        let html;
        if (typeof marked !== 'undefined') {
            marked.setOptions({ gfm: true, breaks: true, mangle: false, headerIds: false });
            html = marked.parse(content);
        } else {
            html = `<pre>${_mfvEsc(content)}</pre>`;
        }
        contentEl.innerHTML = `<div class="mfv-markdown-body">${html}</div>`;

        if (typeof hljs !== 'undefined') {
            contentEl.querySelectorAll('pre code').forEach(block => {
                try { hljs.highlightElement(block); } catch {}
            });
        }

        // Relative link clicks → navigate in the frame
        contentEl.querySelectorAll('a').forEach(link => {
            const href = link.getAttribute('href');
            if (href && !href.startsWith('http') && !href.startsWith('mailto:') && !href.startsWith('#')) {
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    window.ppxai?.displayFileFromEvent?.(this._resolveRelative(href));
                });
            }
        });

        // Relative image src → rewrite to /files/image/<path> so the server
        // resolves against the working directory instead of the web root.
        const serverUrl = this._appState.apiClient?.serverUrl ?? '';
        contentEl.querySelectorAll('img').forEach(img => {
            const src = img.getAttribute('src');
            if (!src) return;
            if (src.startsWith('http://') || src.startsWith('https://')) return;
            if (src.startsWith('data:') || src.startsWith('blob:')) return;
            if (src.startsWith('/files/image/')) return;
            const resolved = this._resolveRelative(src);
            img.setAttribute('src', `${serverUrl}/files/image/${encodeURIComponent(resolved)}`);
        });
    }

    _resolveRelative(href) {
        const dir = this._path.includes('/') ? this._path.substring(0, this._path.lastIndexOf('/')) : '';
        const combined = dir ? `${dir}/${href}` : href;
        const parts = [];
        for (const seg of combined.split('/')) {
            if (seg === '' || seg === '.') continue;
            if (seg === '..') { parts.pop(); continue; }
            parts.push(seg);
        }
        return parts.join('/');
    }

    _renderCode(contentEl, editable) {
        const content = this._currentContent() || this._content || '';
        const lang = 'markdown';
        this._destroyEditor();

        if (!editable) {
            contentEl.innerHTML = `<pre class="rpf-code-pre" tabindex="0"><code class="language-markdown">${_mfvEsc(content)}</code></pre>`;
            const code = contentEl.querySelector('code');
            if (code && typeof hljs !== 'undefined') {
                try { hljs.highlightElement(code); } catch {}
            }
            this._editor = { state: { doc: { toString: () => content } }, focus: () => {}, destroy: () => {} };
        } else {
            const editorEl = document.createElement('div');
            editorEl.className = 'cev-codemirror';
            contentEl.appendChild(editorEl);

            // Shim editor during async CM load so isDirty() works correctly
            this._editor = { state: { doc: { toString: () => content } }, focus: () => {}, destroy: () => {} };

            const createCm = () => {
                try {
                    const isDark = this._resolveTheme() === 'dark';
                    this._editor = cm6.newEditor(editorEl, content, { lang, dark: isDark, lineWrapping: true, readOnly: false });
                    setTimeout(() => this._editor?.focus?.(), 50);
                } catch {
                    this._createFallback(editorEl, content);
                }
            };

            const loadLang = () => {
                if (cm6.langs && cm6.langs[lang]) { createCm(); return; }
                if (!window._cm6Loaded) window._cm6Loaded = {};
                if (window._cm6Loaded[lang]) { createCm(); return; }
                window._cm6Loaded[lang] = true;
                const s = document.createElement('script');
                s.src = `lib/codemirror/lang-${lang}.min.js`;
                s.onload  = createCm;
                s.onerror = () => this._createFallback(editorEl, content);
                document.head.appendChild(s);
            };

            if (typeof cm6 === 'undefined' || !cm6.newEditor) {
                const s = document.createElement('script');
                s.src = 'lib/codemirror/core.min.js';
                s.onload  = loadLang;
                s.onerror = () => this._createFallback(editorEl, content);
                document.head.appendChild(s);
            } else {
                loadLang();
            }
        }
    }

    _createFallback(parent, content) {
        const ta = document.createElement('textarea');
        ta.className = 'ev-fallback';
        ta.value = content;
        parent.appendChild(ta);
        ta.focus();
        this._editor = { state: { doc: { toString: () => ta.value } }, focus: () => ta.focus(), destroy: () => {} };
    }

    _switchMode(newMode) {
        if (newMode === this._mode) return;
        if (newMode !== 'edit' && this.isDirty()) {
            const ok = confirm('Unsaved changes. Switch mode and discard?');
            if (!ok) return;
        }
        if (this._saveKeyHandler) {
            document.removeEventListener('keydown', this._saveKeyHandler, true);
            this._saveKeyHandler = null;
        }
        // Preserve in-editor content before switching away from edit
        if (this._mode === 'edit') {
            this._content = this._currentContent() || this._content;
        }
        this._mode = newMode;
        this._destroyEditor();
        this._buildUI();
    }

    _currentContent() {
        try { return this._editor?.state?.doc?.toString() ?? ''; } catch { return ''; }
    }

    _destroyEditor() {
        try { this._editor?.destroy?.(); } catch {}
        this._editor = null;
    }

    _resolveTheme() {
        const t = this._appState.theme ?? 'dark';
        if (t === 'system') return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        return t === 'light' ? 'light' : 'dark';
    }

    _setStatus(msg, clearAfterMs = 0) {
        if (!this._statusEl) return;
        this._statusEl.textContent = msg;
        if (clearAfterMs > 0) setTimeout(() => { if (this._statusEl) this._statusEl.textContent = ''; }, clearAfterMs);
    }
}

// ── Module-level helpers ──────────────────────────────────────────────────────

function _mfvEsc(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Browser global export
if (typeof window !== 'undefined') {
    window.MarkdownFileView = MarkdownFileView;
}

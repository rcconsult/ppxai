/**
 * CodeEditorView — unified read-only preview / editable CodeMirror 6 view.
 *
 * A single class handles both the "preview" (read-only) and "edit" intents.
 * The mode can be toggled at any time via the View/Edit button without
 * re-fetching the file or losing scroll position.
 *
 * Reads from GET /files/read and writes via POST /files/write
 * using ApiClient (appState.apiClient).
 *
 * Mode toggle:
 *   view  — CodeMirror with readOnly: true; syntax highlighting via hljs fallback
 *           if cm6 is not loaded (plain <pre> with hljs)
 *   edit  — CodeMirror with readOnly: false; Ctrl/Cmd+S saves
 *
 * @version 1.16.2
 */
class CodeEditorView extends BaseView {
    /**
     * @param {string} relPath    - Relative path within the working directory
     * @param {object} appState   - AppState singleton (provides apiClient, theme)
     * @param {object} [opts]
     * @param {string}  [opts.mode='view']  - Initial mode: 'view' | 'edit'
     * @param {number}  [opts.line=1]       - Initial line (1-based)
     * @param {number}  [opts.col=1]        - Initial column (1-based)
     * @param {boolean} [opts.isNew=false]  - True when creating a new file
     */
    constructor(relPath, appState, opts = {}) {
        super();
        this._path     = relPath;
        this._appState = appState;
        this._mode     = opts.mode  ?? 'view';   // 'view' | 'edit'
        this._line     = opts.line  ?? 1;
        this._col      = opts.col   ?? 1;
        this._isNew    = opts.isNew ?? false;
        // v1.18.1 Phase D: working_dir at click time, sent as
        // cwd_anchor on read/write so the server can 409 on
        // engine-cwd drift instead of confusing 404.
        this._cwdAnchor = opts.cwdAnchor ?? null;

        this._container      = null;
        this._editor         = null;      // cm6 EditorView or fallback shim
        this._originalContent = null;     // content at last save (dirty baseline)
        this._loadedContent  = null;      // content as loaded from server
        this._statusEl       = null;
        this._modeBtn        = null;
        this._saveKeyHandler = null;
        this._langSelect     = null;
        this._currentLang    = null;
    }

    // ── BaseView protocol ─────────────────────────────────────────────────────

    getTitle() {
        const parts  = this._path.split('/');
        const name   = parts[parts.length - 1];
        const suffix = this._isNew ? ' (new)' : '';
        return name + suffix;
    }

    getPath() { return this._path; }

    getIcon() { return this._mode === 'edit' ? '✏️' : _cevFileIcon(this._path); }

    async mount(container) {
        // Clean up previous editor if re-mounted (e.g. via promote/back/forward)
        if (this._editor) {
            this._destroyEditor();
        }
        if (this._saveKeyHandler) {
            document.removeEventListener('keydown', this._saveKeyHandler, true);
            this._saveKeyHandler = null;
        }
        this._container = container;
        container.innerHTML = '<div class="rpf-loading">Loading…</div>';

        // Skip fetch if content was already loaded (re-mount via promote/back/forward)
        if (this._loadedContent === null) {
            if (!this._isNew) {
                try {
                    const data = await this._appState.apiClient.readFile(this._path, this._cwdAnchor);
                    if (data.type === 'image' || data.type === 'pdf') {
                        container.innerHTML = `<div class="rpf-error">Cannot display binary file: ${_cevEsc(this._path)}</div>`;
                        return;
                    }
                    this._loadedContent   = data.content ?? '';
                    this._originalContent = this._loadedContent;
                    this._lines           = data.lines ?? this._loadedContent.split('\n').length;
                    this._size            = data.size  ?? 0;
                } catch (err) {
                    // v1.18.1 Phase D: 409 means the relpath was
                    // anchored against a stale cwd. Recover: apply
                    // the drained events to AppState (file tree
                    // refreshes from new cwd via the subscriber),
                    // surface a notice, and bail out — user can
                    // click again from the refreshed tree.
                    if (err.status === 409 && window.ppxai?.handleCwdAnchorMismatch) {
                        if (window.ppxai.handleCwdAnchorMismatch(err)) {
                            container.innerHTML = '';
                            return;
                        }
                    }
                    if (err.status === 404 || err.message.includes('404') ||
                        err.message.includes('not found') ||
                        err.message.includes('does not exist')) {
                        this._isNew = true;
                        this._loadedContent   = '';
                        this._originalContent = '';
                    } else {
                        container.innerHTML = `<div class="rpf-error">Failed to load: ${_cevEsc(err.message)}</div>`;
                        return;
                    }
                }
            } else {
                this._loadedContent   = '';
                this._originalContent = '';
            }
        }

        const ext = this._path.split('.').pop().toLowerCase();
        this._currentLang = _cevExtToLang(ext);
        this._buildUI(this._loadedContent);
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

    focus() { this._editor?.focus?.(); }

    onKeyDown(_e) { return false; }

    onActivate() { this._editor?.focus?.(); }

    // ── Dirty tracking ────────────────────────────────────────────────────────

    isDirty() {
        if (this._mode !== 'edit' || this._editor === null) return false;
        return this._currentContent() !== this._originalContent;
    }

    // ── State persistence ─────────────────────────────────────────────────────

    getState() {
        let cursor = 0;
        let scrollTop = 0;
        try {
            cursor    = this._editor?.state?.selection?.main?.head ?? 0;
            const el  = this._container?.querySelector('.cev-codemirror');
            scrollTop = el?.scrollTop ?? 0;
        } catch {}
        return { cursor, scrollTop, mode: this._mode };
    }

    setState(state) {
        if (state.mode && state.mode !== this._mode) this._switchMode(state.mode);
        if (!(state.cursor > 0)) return;
        try {
            const len = this._editor?.state?.doc?.length ?? 0;
            this._editor?.dispatch?.({ selection: { anchor: Math.min(state.cursor, len) }, scrollIntoView: true });
        } catch {}
    }

    // ── Reload from disk ──────────────────────────────────────────────────────

    /**
     * Re-fetch file content from disk and update the editor.
     * Skips if the buffer has unsaved edits (dirty).
     * Called when the file may have been modified externally (e.g. by AI tools).
     */
    async reload() {
        if (this.isDirty()) return;  // don't clobber unsaved edits
        if (!this._path || this._isNew) return;
        try {
            const data = await this._appState.apiClient.readFile(this._path, this._cwdAnchor);
            if (data.type === 'image' || data.type === 'pdf') return;
            const newContent = data.content ?? '';
            if (newContent === this._loadedContent) return;  // no change on disk
            this._loadedContent   = newContent;
            this._originalContent = newContent;
            // Update editor in-place if mounted
            if (this._editor && this._editor.state) {
                const len = this._editor.state.doc.length;
                this._editor.dispatch({
                    changes: { from: 0, to: len, insert: newContent }
                });
            }
            this._setStatus('Reloaded', 2000);
        } catch {}
    }

    // ── Save API ──────────────────────────────────────────────────────────────

    async save() {
        if (!this._path || this._mode !== 'edit') return;
        const content = this._currentContent();
        this._setStatus('Saving…');
        try {
            const data = await this._appState.apiClient.writeFile(this._path, content, this._cwdAnchor);
            this._originalContent = content;
            this._isNew = false;
            this._setStatus(data.created ? '✓ Created' : '✓ Saved', 2000);
            if (this._modeBtn) this._updateDirtyIndicator();
        } catch (err) {
            // Phase D: 409 means the relpath was anchored against a
            // stale cwd. Refresh AppState; the user keeps their
            // edits and can re-save once the tree shows the new cwd.
            if (err.status === 409 && window.ppxai?.handleCwdAnchorMismatch) {
                if (window.ppxai.handleCwdAnchorMismatch(err)) {
                    this._setStatus('✗ Working dir changed — try save again', 4000);
                    return;
                }
            }
            this._setStatus(`✗ ${err.message}`, 4000);
        }
    }

    // ── Private ───────────────────────────────────────────────────────────────

    _buildUI(content) {
        if (!this._container) return;

        const isEdit  = this._mode === 'edit';
        const lineInfo = this._isNew ? 'new file' : `${this._lines ?? 0} lines`;

        this._container.innerHTML = `
            <div class="rpf-editor-toolbar">
                <button class="rpf-btn cev-mode-btn" title="${isEdit ? 'Switch to view mode' : 'Switch to edit mode'}">
                    ${isEdit ? '👁 View' : '✏️ Edit'}
                </button>
                ${isEdit ? `
                <button class="rpf-btn cev-save" title="Save (Ctrl+S)">💾 Save</button>
                <select class="rpf-syntax-select cev-lang" title="Syntax">
                    ${_cevSyntaxOptions(this._currentLang)}
                </select>` : ''}
                <span class="rpf-view-info">${_cevEsc(lineInfo)}</span>
                <span class="cev-status"></span>
            </div>
            <div class="cev-codemirror" style="flex:1;overflow:auto;"></div>
        `;

        this._statusEl  = this._container.querySelector('.cev-status');
        this._modeBtn   = this._container.querySelector('.cev-mode-btn');
        this._langSelect = this._container.querySelector('.cev-lang');
        const editorEl  = this._container.querySelector('.cev-codemirror');

        this._modeBtn.addEventListener('click', () => {
            this._switchMode(this._mode === 'view' ? 'edit' : 'view');
        });

        if (isEdit) {
            this._container.querySelector('.cev-save').addEventListener('click', () => this.save());
            this._langSelect?.addEventListener('change', e => this._reloadWithLang(e.target.value, editorEl));

            this._saveKeyHandler = (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                    e.preventDefault();
                    this.save();
                }
            };
            document.addEventListener('keydown', this._saveKeyHandler, true);
        }

        this._initCodeMirror(editorEl, content, this._currentLang, this._line, this._col, !isEdit);
    }

    /**
     * Toggle between 'view' and 'edit' mode without re-fetching the file.
     * Preserves cursor position and scroll.
     */
    _switchMode(newMode) {
        if (newMode === this._mode) return;

        if (newMode === 'view' && this.isDirty()) {
            const ok = confirm('You have unsaved changes. Switch to view mode and discard?');
            if (!ok) return;
        }

        // Capture cursor/scroll before destroying (strip mode to avoid re-entry)
        const { cursor, scrollTop } = this.getState();
        this._mode = newMode;

        // Detach old Ctrl+S handler if leaving edit
        if (this._saveKeyHandler) {
            document.removeEventListener('keydown', this._saveKeyHandler, true);
            this._saveKeyHandler = null;
        }

        // Rebuild UI with current content (not re-fetched)
        const content = this._currentContent() || this._loadedContent || '';
        this._destroyEditor();
        this._buildUI(content);

        // Restore cursor/scroll only — mode is already set, do NOT pass mode
        // to setState to avoid infinite _switchMode ↔ setState recursion
        this.setState({ cursor, scrollTop });
    }

    /**
     * Load the CodeMirror core (once) and the language addon, then create
     * the editor. Core is loaded from lib/codemirror/core.min.js (sets the
     * cm6 global with newEditor/registerLang/modules). Language addons are
     * lib/codemirror/lang-{name}.min.js — each calls cm6.registerLang().
     */
    _initCodeMirror(editorEl, content, lang, line, col, readOnly) {
        this._destroyEditor();

        const create = () => {
            if (typeof cm6 !== 'undefined' && cm6.newEditor) {
                this._createEditor(editorEl, content, lang, line, col, readOnly);
            } else {
                this._createFallback(editorEl, content, line, col, readOnly);
            }
        };

        const loadLang = () => {
            if (!lang || (cm6.langs && cm6.langs[lang])) {
                create();
                return;
            }
            // Track loaded scripts to avoid duplicate <script> tags
            if (!window._cm6Loaded) window._cm6Loaded = {};
            if (window._cm6Loaded[lang]) { create(); return; }
            window._cm6Loaded[lang] = true;
            const s = document.createElement('script');
            s.src = `lib/codemirror/lang-${lang}.min.js`;
            s.onload  = create;
            s.onerror = () => this._createFallback(editorEl, content, line, col, readOnly);
            document.head.appendChild(s);
        };

        if (typeof cm6 === 'undefined' || !cm6.newEditor) {
            const s = document.createElement('script');
            s.src = 'lib/codemirror/core.min.js';
            s.onload  = loadLang;
            s.onerror = () => this._createFallback(editorEl, content, line, col, readOnly);
            document.head.appendChild(s);
        } else {
            loadLang();
        }
    }

    _createEditor(editorEl, content, lang, line, col, readOnly) {
        try {
            const isDark = this._resolveTheme() === 'dark';
            const view = cm6.newEditor(editorEl, content, { lang, dark: isDark, lineWrapping: true, readOnly });
            this._editor = view;
            this._scrollToPosition(view, line, col);
            if (!readOnly) view.focus();
            this._applyPendingState();
        } catch (err) {
            console.error('CodeMirror init error:', err);
            this._createFallback(editorEl, content, line, col, readOnly);
        }
    }

    _createFallback(editorEl, content, line, col, readOnly) {
        if (readOnly) {
            // Read-only fallback: syntax-highlighted <pre>
            const ext  = this._path.split('.').pop().toLowerCase();
            const lang = _cevExtToHljsLang(ext);
            editorEl.innerHTML = `<pre class="rpf-code-pre" tabindex="0" style="margin:0;padding:8px;overflow:auto;height:100%;"><code class="${lang ? `language-${_cevEsc(lang)}` : ''}">${_cevEsc(content)}</code></pre>`;
            const codeEl = editorEl.querySelector('code');
            if (codeEl && typeof hljs !== 'undefined' && lang) {
                try { hljs.highlightElement(codeEl); } catch {}
            }
            this._editor = { state: { doc: { toString: () => content }, selection: { main: { head: 0 } } }, focus: () => {}, destroy: () => {} };
        } else {
            const ta = document.createElement('textarea');
            ta.className  = 'ev-fallback';
            ta.style.cssText = 'width:100%;height:100%;resize:none;font-family:monospace;font-size:13px;padding:8px;border:none;background:var(--bg-secondary);color:var(--text-primary);box-sizing:border-box;';
            ta.value = content;
            editorEl.appendChild(ta);
            const lines = content.split('\n');
            let pos = 0;
            for (let i = 0; i < Math.min(line - 1, lines.length); i++) pos += lines[i].length + 1;
            pos += Math.min(col - 1, lines[line - 1]?.length ?? 0);
            ta.setSelectionRange(pos, pos);
            ta.focus();
            this._editor = { state: { doc: { toString: () => ta.value }, selection: { main: { head: pos } } }, focus: () => ta.focus(), destroy: () => {} };
        }
        this._applyPendingState();
    }

    _scrollToPosition(view, line, col) {
        if (line <= 1 && col <= 1) return;
        try {
            const lineCount = view.state.doc.lines;
            const target    = Math.min(line, lineCount);
            const lineInfo  = view.state.doc.line(target);
            const pos       = lineInfo.from + Math.min(col - 1, lineInfo.length);
            view.dispatch({ selection: { anchor: pos }, scrollIntoView: true });
        } catch {}
    }

    _reloadWithLang(lang, editorEl) {
        const content = this._currentContent();
        let cursor = 0;
        try { cursor = this._editor?.state?.selection?.main?.head ?? 0; } catch {}
        this._currentLang = lang;
        this._destroyEditor();
        editorEl.innerHTML = '';
        this._initCodeMirror(editorEl, content, lang, 1, 1, this._mode === 'view');
        setTimeout(() => {
            try {
                if (this._editor && cursor > 0) {
                    const len = this._editor.state.doc.length;
                    this._editor.dispatch({ selection: { anchor: Math.min(cursor, len) } });
                }
            } catch {}
        }, 100);
    }

    _updateDirtyIndicator() {
        if (!this._modeBtn) return;
        // Dot indicator on mode button when dirty
        const dirty = this.isDirty();
        this._modeBtn.textContent = (this._mode === 'edit' ? '👁 View' : '✏️ Edit') + (dirty ? ' ●' : '');
    }

    _destroyEditor() {
        try { this._editor?.destroy?.(); } catch {}
        this._editor = null;
    }

    _currentContent() {
        try { return this._editor?.state?.doc?.toString() ?? ''; } catch { return ''; }
    }

    _resolveTheme() {
        const t = this._appState.theme ?? 'dark';
        if (t === 'system') return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        return t;
    }

    _setStatus(msg, clearAfterMs = 0) {
        if (!this._statusEl) return;
        this._statusEl.textContent = msg;
        if (clearAfterMs > 0) setTimeout(() => { if (this._statusEl) this._statusEl.textContent = ''; }, clearAfterMs);
    }
}

// ── Module-level helpers ──────────────────────────────────────────────────────

function _cevEsc(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _cevFileIcon(path) {
    const name = (path ?? '').split('/').pop().toLowerCase();
    const ext  = name.split('.').pop();
    const icons = {
        py: '🐍', js: '📜', ts: '📘', jsx: '⚛', tsx: '⚛',
        json: '{}', yaml: '📋', yml: '📋', toml: '📋',
        md: '📝', txt: '📄', rst: '📝',
        html: '🌐', css: '🎨', scss: '🎨',
        sh: '🔧', bash: '🔧', zsh: '🔧',
        go: '🐹', rs: '🦀', java: '☕', rb: '💎', php: '🐘',
        c: '🔷', cpp: '🔷', h: '🔷', cs: '🔷',
        sql: '🗄', lock: '🔒',
    };
    if (name === 'dockerfile') return '🐳';
    if (name === 'makefile')   return '🔧';
    if (name.startsWith('.env')) return '🔑';
    return icons[ext] || '📄';
}

function _cevExtToLang(ext) {
    const map = {
        // Native CodeMirror 6 lang packages
        py: 'python', python: 'python', pyw: 'python', pyi: 'python',
        js: 'javascript', mjs: 'javascript', cjs: 'javascript',
        ts: 'javascript', tsx: 'javascript', jsx: 'javascript',
        json: 'json', jsonl: 'json',
        yaml: 'yaml', yml: 'yaml',
        md: 'markdown', markdown: 'markdown',
        html: 'html', htm: 'html', svelte: 'html', vue: 'html',
        css: 'css', scss: 'css', less: 'css',
        sql: 'sql',
        rs: 'rust',
        go: 'go',
        java: 'java',
        c: 'cpp', cpp: 'cpp', cc: 'cpp', cxx: 'cpp', h: 'cpp', hpp: 'cpp',
        xml: 'xml', svg: 'xml', xsl: 'xml',
        php: 'php',
        // Legacy modes (StreamLanguage wrappers)
        sh: 'shell', bash: 'shell', zsh: 'shell', csh: 'shell', fish: 'shell', ksh: 'shell',
        toml: 'toml',
        kt: 'kotlin', kts: 'kotlin',
        scala: 'scala', sc: 'scala',
        rb: 'ruby', rake: 'ruby', gemspec: 'ruby',
        pl: 'perl', pm: 'perl',
        lua: 'lua',
        r: 'r',
        swift: 'swift',
        ps1: 'powershell', psm1: 'powershell', psd1: 'powershell',
        diff: 'diff', patch: 'diff',
        proto: 'protobuf',
        nginx: 'nginx', conf: 'nginx',
        cmake: 'cmake',
        properties: 'properties', env: 'properties', ini: 'properties',
    };
    if (map[ext]) return map[ext];
    // Filename-based detection (no extension or special names)
    const names = {
        makefile: 'shell', dockerfile: 'dockerfile',
        cmakelists: 'cmake', rakefile: 'ruby',
        gemfile: 'ruby', vagrantfile: 'ruby',
    };
    return names[ext] || null;
}

function _cevExtToHljsLang(ext) {
    const map = {
        py: 'python', js: 'javascript', ts: 'typescript',
        jsx: 'javascript', tsx: 'typescript',
        json: 'json', yaml: 'yaml', yml: 'yaml', toml: 'toml',
        md: 'markdown', rst: 'markdown',
        html: 'html', css: 'css', scss: 'scss',
        sh: 'bash', bash: 'bash', zsh: 'bash',
        go: 'go', rs: 'rust', java: 'java', rb: 'ruby',
        c: 'c', cpp: 'cpp', cs: 'csharp', sql: 'sql', xml: 'xml',
    };
    return map[ext] || null;
}

function _cevSyntaxOptions(activeLang) {
    const options = [
        ['markdown',   'Markdown'],
        ['yaml',       'YAML'],
        ['json',       'JSON'],
        ['toml',       'TOML'],
        ['python',     'Python'],
        ['javascript', 'JavaScript'],
        ['html',       'HTML'],
        ['css',        'CSS'],
        ['sql',        'SQL'],
        ['shell',      'Shell'],
        ['rust',       'Rust'],
        ['go',         'Go'],
        ['java',       'Java'],
        ['kotlin',     'Kotlin'],
        ['scala',      'Scala'],
        ['cpp',        'C/C++'],
        ['xml',        'XML'],
        ['php',        'PHP'],
        ['ruby',       'Ruby'],
        ['perl',       'Perl'],
        ['lua',        'Lua'],
        ['swift',      'Swift'],
        ['r',          'R'],
        ['dockerfile', 'Dockerfile'],
        ['diff',       'Diff'],
        ['powershell', 'PowerShell'],
        ['protobuf',   'Protobuf'],
        ['nginx',      'Nginx'],
    ];
    return options.map(([val, label]) =>
        `<option value="${val}"${val === activeLang ? ' selected' : ''}>${label}</option>`
    ).join('');
}

// Browser global export
if (typeof window !== 'undefined') {
    window.CodeEditorView = CodeEditorView;
}

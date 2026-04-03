/**
 * DataFileView — structured data viewer with tree / table / source / edit modes.
 *
 * Format detection (from file extension):
 *   table  — csv, tsv, tab  → DataTableViewer
 *   tree   — json, yaml, yml, toml, hcl, tf, tfvars  → DataTreeViewer
 *
 * Modes:
 *   rendered — tree or table view (DataTreeViewer / DataTableViewer)
 *   source   — read-only CodeMirror / <pre> with syntax highlighting
 *   edit     — editable CodeMirror / <textarea>, Ctrl/Cmd+S to save
 *              After save, re-parses and re-renders if returning to rendered mode.
 *
 * Switches away from edit that have unsaved changes prompt the user.
 *
 * @version 1.16.2
 */
class DataFileView extends BaseView {
    /**
     * @param {string} relPath   - Relative path within the working directory
     * @param {object} appState  - AppState singleton (provides apiClient, theme)
     */
    constructor(relPath, appState) {
        super();
        this._path     = relPath;
        this._appState = appState;
        this._format   = _dfvFormatFromExt(relPath.split('.').pop().toLowerCase()); // 'table' | 'tree'
        this._mode     = 'rendered';  // 'rendered' | 'source' | 'edit'

        this._container      = null;
        this._editor         = null;  // cm6 view or shim (source/edit modes)
        this._dataViewer     = null;  // DataTableViewer or DataTreeViewer instance
        this._content        = null;  // content as loaded / last saved
        this._originalContent = null;
        this._lines          = 0;
        this._size           = 0;
        this._statusEl       = null;
        this._saveKeyHandler = null;
    }

    // ── BaseView protocol ─────────────────────────────────────────────────────

    getTitle() { return this._path.split('/').pop(); }

    getPath() { return this._path; }

    getIcon() { return this._format === 'table' ? '📊' : '🌲'; }

    async mount(container) {
        this._container = container;
        container.innerHTML = '<div class="rpf-loading">Loading…</div>';
        try {
            const data = await this._appState.apiClient.readFile(this._path);
            this._content         = data.content ?? '';
            this._originalContent = this._content;
            this._lines           = data.lines ?? this._content.split('\n').length;
            this._size            = data.size  ?? 0;
        } catch (err) {
            container.innerHTML = `<div class="rpf-error">Failed to load: ${_dfvEsc(err.message)}</div>`;
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
        this._destroyDataViewer();
        if (this._container) {
            this._container.innerHTML = '';
            this._container = null;
        }
    }

    focus()      {}
    onActivate() {}
    onKeyDown()  { return false; }

    getState() {
        const el = this._container?.querySelector('.dfv-content');
        const mode = this._mode === 'edit' ? 'rendered' : this._mode;
        return { mode, scrollTop: el?.scrollTop ?? 0 };
    }

    setState(state) {
        if (state.mode && state.mode !== this._mode) this._switchMode(state.mode);
        if (state.scrollTop > 0) {
            setTimeout(() => {
                const el = this._container?.querySelector('.dfv-content');
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
        const renderLabel = this._format === 'table' ? '📊 Table' : '🌲 Tree';

        const sizeStr = this._size > 1024 * 1024
            ? `${(this._size / 1024 / 1024).toFixed(2)} MB`
            : `${(this._size / 1024).toFixed(1)} KB`;

        this._container.innerHTML = `
            <div class="rpf-view-toolbar">
                <button class="rpf-btn${isRendered ? ' active' : ''} dfv-btn-rendered">${_dfvEsc(renderLabel)}</button>
                <button class="rpf-btn${isSource   ? ' active' : ''} dfv-btn-source">📄 Source</button>
                <button class="rpf-btn${isEdit     ? ' active' : ''} dfv-btn-edit">✏️ Edit</button>
                ${isEdit ? '<button class="rpf-btn dfv-btn-save" title="Save (Ctrl+S)">💾 Save</button>' : ''}
                <span class="rpf-view-info">${_dfvEsc(this._lines + ' lines • ' + sizeStr)}</span>
                <span class="ev-status dfv-status"></span>
            </div>
            <div class="dfv-content"></div>
        `;

        this._statusEl = this._container.querySelector('.dfv-status');
        const contentEl = this._container.querySelector('.dfv-content');

        this._container.querySelector('.dfv-btn-rendered').addEventListener('click', () => this._switchMode('rendered'));
        this._container.querySelector('.dfv-btn-source').addEventListener('click',   () => this._switchMode('source'));
        this._container.querySelector('.dfv-btn-edit').addEventListener('click',     () => this._switchMode('edit'));

        if (isEdit) {
            this._container.querySelector('.dfv-btn-save').addEventListener('click', () => this.save());
            this._saveKeyHandler = (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); this.save(); }
            };
            document.addEventListener('keydown', this._saveKeyHandler, true);
        }

        if (isRendered) {
            this._renderData(contentEl);
        } else {
            this._renderCode(contentEl, isEdit);
        }

        // Apply state saved by frame before this mount (scroll position, mode)
        this._applyPendingState();
    }

    _renderData(contentEl) {
        const content = this._content ?? '';
        const ext     = this._path.split('.').pop().toLowerCase();
        this._destroyDataViewer();

        try {
            if (this._format === 'table') {
                const delim = (ext === 'tsv' || ext === 'tab') ? '\t' : _dfvDetectDelimiter(content);
                const data  = _dfvParseCSV(content, delim);
                if (typeof DataTableViewer !== 'undefined') {
                    this._dataViewer = new DataTableViewer(contentEl, data, { pageSize: 100 });
                } else {
                    contentEl.innerHTML = '<div class="rpf-error">DataTableViewer not loaded. Switch to Source view.</div>';
                }
            } else {
                const tree = _dfvParseStructured(content, ext);
                if (typeof DataTreeViewer !== 'undefined') {
                    this._dataViewer = new DataTreeViewer(contentEl, tree, { initialExpandDepth: 2 });
                } else {
                    contentEl.innerHTML = '<div class="rpf-error">DataTreeViewer not loaded. Switch to Source view.</div>';
                }
            }
        } catch (err) {
            contentEl.innerHTML = `<div class="rpf-error">Parse error: ${_dfvEsc(err.message)}<br><small>Switch to Source view to inspect.</small></div>`;
        }
    }

    _renderCode(contentEl, editable) {
        const content = this._currentContent() || this._content || '';
        const ext     = this._path.split('.').pop().toLowerCase();
        const cmLang  = _dfvExtToCmLang(ext);
        this._destroyEditor();
        this._destroyDataViewer();

        if (!editable) {
            const hljsLang = _dfvExtToHljsLang(ext);
            contentEl.innerHTML = `<pre class="rpf-code-pre" tabindex="0"><code class="${hljsLang ? `language-${_dfvEsc(hljsLang)}` : ''}">${_dfvEsc(content)}</code></pre>`;
            const code = contentEl.querySelector('code');
            if (code && typeof hljs !== 'undefined' && hljsLang) {
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
                    this._editor = cm6.newEditor(editorEl, content, { lang: cmLang, dark: isDark, lineWrapping: false, readOnly: false });
                    setTimeout(() => this._editor?.focus?.(), 50);
                } catch {
                    this._createFallback(editorEl, content);
                }
            };

            const loadLang = () => {
                if (!cmLang || (cm6.langs && cm6.langs[cmLang])) { createCm(); return; }
                if (!window._cm6Loaded) window._cm6Loaded = {};
                if (window._cm6Loaded[cmLang]) { createCm(); return; }
                window._cm6Loaded[cmLang] = true;
                const s = document.createElement('script');
                s.src = `lib/codemirror/lang-${cmLang}.min.js`;
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
        this._destroyDataViewer();
        this._buildUI();
    }

    _currentContent() {
        try { return this._editor?.state?.doc?.toString() ?? ''; } catch { return ''; }
    }

    _destroyEditor() {
        try { this._editor?.destroy?.(); } catch {}
        this._editor = null;
    }

    _destroyDataViewer() {
        try { this._dataViewer?.destroy?.(); } catch {}
        this._dataViewer = null;
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

/** Determine rendered format from file extension. */
function _dfvFormatFromExt(ext) {
    return new Set(['csv', 'tsv', 'tab']).has(ext) ? 'table' : 'tree';
}

function _dfvEsc(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _dfvExtToCmLang(ext) {
    const map = {
        json: 'json', jsonl: 'json',
        yaml: 'yaml', yml: 'yaml',
        toml: 'toml',
        xml: 'xml', svg: 'xml',
    };
    return map[ext] || null;
}

function _dfvExtToHljsLang(ext) {
    const map = {
        json: 'json', yaml: 'yaml', yml: 'yaml', toml: 'toml',
        hcl: 'hcl', tf: 'hcl', tfvars: 'hcl',
        csv: 'text', tsv: 'text', tab: 'text',
    };
    return map[ext] || null;
}

function _dfvDetectDelimiter(content) {
    const lines = content.split('\n').slice(0, 10);
    const candidates = [',', '\t', ';', '|'];
    const scores = {};
    candidates.forEach(d => {
        const counts = lines.filter(l => l.trim()).map(l => (l.match(new RegExp(d === '|' ? '\\|' : d, 'g')) || []).length);
        if (counts.length) {
            const unique = new Set(counts);
            scores[d] = (unique.size === 1 && counts[0] > 0)
                ? counts[0] * 10
                : counts.reduce((a, b) => a + b, 0) / counts.length;
        }
    });
    return Object.keys(scores).reduce((a, b) => scores[a] > scores[b] ? a : b, ',');
}

function _dfvParseCSV(content, delimiter = ',') {
    const lines = content.split('\n');
    const headers = [], rows = [];
    lines.forEach((line, i) => {
        if (!line.trim()) return;
        const cells = _dfvParseCSVLine(line, delimiter);
        if (i === 0) {
            cells.forEach((cell, j) => headers.push(cell.trim() || `Column ${j + 1}`));
        } else {
            while (cells.length < headers.length) cells.push('');
            rows.push(cells);
        }
    });
    return { headers, rows, rowCount: rows.length, columnCount: headers.length };
}

function _dfvParseCSVLine(line, delimiter) {
    const cells = [];
    let current = '', inQuotes = false;
    for (let i = 0; i < line.length; i++) {
        const char = line[i], next = line[i + 1];
        if (inQuotes) {
            if (char === '"' && next === '"') { current += '"'; i++; }
            else if (char === '"')             { inQuotes = false; }
            else                               { current += char; }
        } else {
            if (char === '"')            { inQuotes = true; }
            else if (char === delimiter) { cells.push(current); current = ''; }
            else                         { current += char; }
        }
    }
    cells.push(current);
    return cells;
}

function _dfvParseStructured(content, ext) {
    let data;
    if (ext === 'json') {
        data = JSON.parse(content);
    } else if (ext === 'yaml' || ext === 'yml') {
        if (typeof jsyaml !== 'undefined') { data = jsyaml.load(content); }
        else { throw new Error('YAML parsing requires js-yaml library'); }
    } else if (ext === 'toml') {
        if (typeof smolToml !== 'undefined') { data = smolToml.parse(content); }
        else { throw new Error('TOML parsing requires smol-toml library'); }
    } else if (ext === 'hcl' || ext === 'tf' || ext === 'tfvars') {
        if (typeof hcl2 !== 'undefined' && hcl2.parseToObject) {
            const result = hcl2.parseToObject(content);
            if (result[1]) throw new Error(`HCL parse error: ${result[1]}`);
            data = result[0];
        } else { throw new Error('HCL parsing requires hcl2-parser library'); }
    } else {
        data = JSON.parse(content);
    }
    return _dfvBuildTree('root', data, 0);
}

function _dfvBuildTree(key, value, depth) {
    const node = { key, value: null, node_type: 'null', children: [], depth };
    if      (value === null)              { node.node_type = 'null'; }
    else if (typeof value === 'boolean')  { node.node_type = 'boolean'; node.value = value; }
    else if (typeof value === 'number')   { node.node_type = 'number';  node.value = value; }
    else if (typeof value === 'string')   { node.node_type = 'string';  node.value = value; }
    else if (Array.isArray(value))        { node.node_type = 'array';   node.children = value.map((v, i) => _dfvBuildTree(`[${i}]`, v, depth + 1)); }
    else if (typeof value === 'object')   { node.node_type = 'object';  node.children = Object.keys(value).map(k => _dfvBuildTree(k, value[k], depth + 1)); }
    return node;
}

// Browser global export
if (typeof window !== 'undefined') {
    window.DataFileView = DataFileView;
}

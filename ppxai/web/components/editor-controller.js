/**
 * EditorController — CodeMirror 6 lifecycle for the ppxai web editor panel.
 *
 * Extracted from app.js v1.14.1–v1.16.2.
 * Encapsulates all editor state, DOM manipulation, and file I/O for the
 * right-side panel editor so that PpxaiApp only needs to call open/close.
 *
 * Usage:
 *   this.editorController = new EditorController({ apiClient, panels, getTheme, onMessage, onError });
 *   await this.editorController.open(filepath);
 */

class EditorController {
    /**
     * @param {object} opts
     * @param {ApiClient} opts.apiClient - Shared API client for file operations
     * @param {object}    opts.panels   - DOM element references:
     *   { panel, resizeHandle, filename, info, viewToggle,
     *     codeWrapper, markdown, dataViewer }
     * @param {function}  opts.getTheme  - () => 'dark'|'light'|'system'
     * @param {function}  opts.onMessage - (msg) => void — system message
     * @param {function}  opts.onError   - (msg) => void — error message
     */
    constructor({ apiClient, panels, getTheme, onMessage, onError }) {
        this.apiClient = apiClient;
        this.panels = panels;
        this.getTheme = getTheme;
        this.onMessage = onMessage;
        this.onError = onError;

        // Internal state
        this._editor = null;
        this._filename = null;
        this._originalContent = null;
        this._language = 'markdown';
        this._isNewFile = false;
    }

    // ─── Public API ──────────────────────────────────────────────────────────

    /**
     * Open a file in the editor panel.
     * Reads from server; if file not found, creates a new empty file.
     *
     * @param {string} filepath  - Server path (may include :line:col suffix)
     */
    async open(filepath) {
        if (!filepath || !filepath.trim()) {
            this.onError('Usage: /edit <filepath[:line[:col]]>');
            return;
        }

        // Parse optional :line:col suffix
        const input = filepath.trim();
        let path = input, line = 1, col = 1;
        const match = input.match(/^(.+?):(\d+)(?::(\d+))?$/);
        if (match) {
            path = match[1];
            line = parseInt(match[2], 10);
            col  = match[3] ? parseInt(match[3], 10) : 1;
        }

        try {
            let data;
            try {
                data = await this.apiClient.readFile(path);
            } catch (readError) {
                // File not found — allow creating a new file
                if (readError.message.includes('Not Found') || readError.message.includes('not found') ||
                    readError.message.includes('does not exist') || readError.message === 'HTTP 404') {
                    this._showPanel(path, '', line, col, true);
                } else {
                    this.onError(`Failed to read file: ${readError.message}`);
                }
                return;
            }

            if (data.type === 'image' || data.type === 'pdf') {
                this.onError(`Cannot edit binary file: ${path}`);
                return;
            }

            this._showPanel(data.filename || path, data.content, line, col, false);
        } catch (error) {
            this.onError(`Failed to open file: ${error.message}`);
        }
    }

    /** Return current editor content (empty string if no editor active). */
    getContent() {
        return this._editor?.state?.doc?.toString() ?? '';
    }

    /** True if the editor has unsaved changes. */
    hasUnsavedChanges() {
        return this.getContent() !== this._originalContent;
    }

    /** Save the currently open file to the server. */
    async save() {
        if (!this._editor || !this._filename) return;

        const content = this.getContent();
        const statusEl = document.querySelector('.editor-status');

        try {
            if (statusEl) statusEl.textContent = 'Saving...';

            const data = await this.apiClient.writeFile(this._filename, content);
            this._originalContent = content;
            this._isNewFile = false;

            this.panels.filename.textContent = this._filename;

            if (statusEl) {
                statusEl.textContent = data.created ? '✓ Created' : '✓ Saved';
                setTimeout(() => { statusEl.textContent = ''; }, 2000);
            }

            this.onMessage(`✓ Saved: ${this._filename}`);
        } catch (error) {
            if (statusEl) statusEl.textContent = '✗ Error';
            this.onError(`Failed to save: ${error.message}`);
        }
    }

    /** Prompt for a new path and save content there. */
    async saveAs() {
        const newPath = prompt('Save as (enter file path):', this._filename);
        if (!newPath || !newPath.trim()) return;

        const content = this.getContent();
        const statusEl = document.querySelector('.editor-status');

        try {
            if (statusEl) statusEl.textContent = 'Saving...';

            const data = await this.apiClient.writeFile(newPath.trim(), content);
            this._filename = newPath.trim();
            this._originalContent = content;
            this._isNewFile = false;

            this.panels.filename.textContent = this._filename;

            if (statusEl) {
                statusEl.textContent = data.created ? '✓ Created' : '✓ Saved';
                setTimeout(() => { statusEl.textContent = ''; }, 2000);
            }

            this.onMessage(`✓ Saved as: ${this._filename}`);
        } catch (error) {
            if (statusEl) statusEl.textContent = '✗ Error';
            this.onError(`Failed to save: ${error.message}`);
        }
    }

    /** Prompt user for a file path and open it for editing. */
    async openDialog() {
        if (this.hasUnsavedChanges()) {
            if (!confirm('You have unsaved changes. Open a different file?')) return;
        }
        const filepath = prompt('Open file (enter path):');
        if (!filepath || !filepath.trim()) return;
        await this.open(filepath.trim());
    }

    /** Reload the editor with a different syntax language. */
    setSyntax(language) {
        if (this._language === language) return;

        const content = this.getContent();
        let cursorPos = 0;
        try { cursorPos = this._editor?.state?.selection?.main?.head || 0; } catch {}

        this._destroyEditor();
        this._language = language;

        const previewContentEl = this.panels.codeWrapper.parentElement;
        const editorContainer  = previewContentEl.querySelector('.editor-container');
        const editorEl         = editorContainer?.querySelector('.codemirror-editor');
        if (!editorEl) return;

        editorEl.innerHTML = '';

        const script = document.createElement('script');
        script.src = `lib/codemirror/${language}.min.js`;
        script.onload = () => {
            this._createCodeMirrorEditor(editorEl, content, 1, 1);
            try {
                if (this._editor && cursorPos > 0) {
                    this._editor.dispatch({ selection: { anchor: Math.min(cursorPos, content.length) } });
                }
            } catch {}
        };
        script.onerror = () => {
            this.onError(`Failed to load syntax: ${language}`);
            this._createFallbackEditor(editorEl, content, 1, 1);
        };
        document.head.appendChild(script);
    }

    /** Ask confirmation if there are unsaved changes, then close the panel. */
    discard() {
        if (this.hasUnsavedChanges()) {
            if (!confirm('Discard unsaved changes?')) return;
        }
        this.close();
    }

    /** Destroy the editor and hide the panel without asking. */
    close() {
        this._destroyEditor();

        // Hide editor container
        const previewContentEl = this.panels.codeWrapper.parentElement;
        const editorContainer  = previewContentEl.querySelector('.editor-container');
        if (editorContainer) editorContainer.classList.add('hidden');

        // Reset panel state
        this._filename        = null;
        this._originalContent = null;
        this._isNewFile       = false;

        // Restore panel elements that were hidden
        this.panels.codeWrapper.classList.remove('hidden');
        this.panels.panel.classList.add('hidden');
        this.panels.resizeHandle.classList.add('hidden');
    }

    // ─── Private helpers ─────────────────────────────────────────────────────

    _showPanel(filename, content, line, col, isNewFile) {
        this._filename        = filename;
        this._originalContent = content;
        this._isNewFile       = isNewFile;

        // Update panel header
        this.panels.filename.textContent = filename + (isNewFile ? ' (new)' : '');
        this.panels.info.textContent     = isNewFile ? 'New file' : `${content.split('\n').length} lines`;

        // Hide view toggle (not for editor mode)
        if (this.panels.viewToggle) this.panels.viewToggle.classList.add('hidden');

        // Hide other preview containers
        this.panels.codeWrapper.classList.add('hidden');
        if (this.panels.markdown)   this.panels.markdown.classList.add('hidden');
        if (this.panels.dataViewer) this.panels.dataViewer.classList.add('hidden');

        // Get or create editor container
        const previewContentEl = this.panels.codeWrapper.parentElement;
        let editorContainer = previewContentEl.querySelector('.editor-container');
        if (!editorContainer) {
            editorContainer = document.createElement('div');
            editorContainer.className  = 'editor-container';
            editorContainer.style.cssText = 'height: 100%; display: flex; flex-direction: column;';
            previewContentEl.appendChild(editorContainer);
        }
        editorContainer.classList.remove('hidden');
        editorContainer.innerHTML = '';

        // Detect syntax from extension
        const ext = filename.split('.').pop().toLowerCase();
        const langMap = {
            'py': 'python', 'python': 'python',
            'js': 'javascript', 'mjs': 'javascript', 'cjs': 'javascript', 'ts': 'javascript', 'tsx': 'javascript',
            'json': 'json',
            'yaml': 'yaml', 'yml': 'yaml',
            'md': 'markdown', 'markdown': 'markdown'
        };
        this._language = langMap[ext] || 'markdown';

        // Build toolbar
        const toolbar = document.createElement('div');
        toolbar.className  = 'editor-toolbar';
        toolbar.innerHTML = `
            <button class="editor-btn editor-save" title="Save (Ctrl+S)">💾 Save</button>
            <button class="editor-btn editor-save-as" title="Save As...">📄 Save As</button>
            <button class="editor-btn editor-open" title="Open file...">📂 Open</button>
            <select class="editor-syntax-select" title="Syntax highlighting">
                <option value="markdown"   ${this._language === 'markdown'   ? 'selected' : ''}>Markdown</option>
                <option value="yaml"       ${this._language === 'yaml'       ? 'selected' : ''}>YAML</option>
                <option value="json"       ${this._language === 'json'       ? 'selected' : ''}>JSON</option>
                <option value="python"     ${this._language === 'python'     ? 'selected' : ''}>Python</option>
                <option value="javascript" ${this._language === 'javascript' ? 'selected' : ''}>JavaScript</option>
            </select>
            <button class="editor-btn editor-discard" title="Close editor">✗ Close</button>
            <span class="editor-status"></span>
        `;
        editorContainer.appendChild(toolbar);

        // Wire toolbar
        toolbar.querySelector('.editor-save').addEventListener('click', () => this.save());
        toolbar.querySelector('.editor-save-as').addEventListener('click', () => this.saveAs());
        toolbar.querySelector('.editor-open').addEventListener('click', () => this.openDialog());
        toolbar.querySelector('.editor-syntax-select').addEventListener('change', (e) => this.setSyntax(e.target.value));
        toolbar.querySelector('.editor-discard').addEventListener('click', () => this.discard());

        // Editor element
        const editorEl = document.createElement('div');
        editorEl.className     = 'codemirror-editor';
        editorEl.style.cssText = 'flex: 1; overflow: auto;';
        editorContainer.appendChild(editorEl);

        // Load CodeMirror
        this._initCodeMirror(editorEl, content, filename, line, col);

        // Show the panel
        this.panels.resizeHandle.classList.remove('hidden');
        this.panels.panel.classList.remove('hidden');
    }

    _initCodeMirror(element, content, filename, line, col) {
        this._destroyEditor();

        if (typeof cm6 === 'undefined') {
            const ext = filename.split('.').pop().toLowerCase();
            const langMap = {
                'py': 'python', 'python': 'python',
                'js': 'javascript', 'mjs': 'javascript', 'cjs': 'javascript',
                'json': 'json',
                'yaml': 'yaml', 'yml': 'yaml',
                'md': 'markdown', 'markdown': 'markdown'
            };
            const lang = langMap[ext] || 'markdown';

            const script = document.createElement('script');
            script.src = `lib/codemirror/${lang}.min.js`;
            script.onload  = () => this._createCodeMirrorEditor(element, content, line, col);
            script.onerror = () => this._createFallbackEditor(element, content, line, col);
            document.head.appendChild(script);
        } else {
            this._createCodeMirrorEditor(element, content, line, col);
        }
    }

    _createCodeMirrorEditor(element, content, line, col) {
        try {
            const isDark = this.getTheme() === 'dark';
            const api  = cm6.load();
            const view = api.newEditor(element, content, { dark: isDark, lineWrapping: true });

            this._editor = view;

            if (line > 1 || col > 1) {
                try {
                    const lineCount  = view.state.doc.lines;
                    const targetLine = Math.min(line, lineCount);
                    const lineInfo   = view.state.doc.line(targetLine);
                    const pos        = lineInfo.from + Math.min(col - 1, lineInfo.length);
                    view.dispatch({ selection: { anchor: pos }, scrollIntoView: true });
                } catch {}
            }

            view.focus();

            element.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                    e.preventDefault();
                    this.save();
                }
            });

        } catch (error) {
            console.error('CodeMirror init error:', error);
            this._createFallbackEditor(element, content, line, col);
        }
    }

    _createFallbackEditor(element, content, line, col) {
        const textarea = document.createElement('textarea');
        textarea.className     = 'fallback-editor';
        textarea.style.cssText = 'width: 100%; height: 100%; resize: none; font-family: monospace; font-size: 13px; padding: 8px; border: none; background: var(--bg-secondary); color: var(--text-primary);';
        textarea.value = content;
        element.appendChild(textarea);

        this._editor = {
            state: { doc: { toString: () => textarea.value } },
            destroy: () => {}
        };

        const lines = content.split('\n');
        let pos = 0;
        for (let i = 0; i < Math.min(line - 1, lines.length); i++) pos += lines[i].length + 1;
        pos += Math.min(col - 1, lines[line - 1]?.length || 0);
        textarea.setSelectionRange(pos, pos);
        textarea.focus();

        textarea.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                this.save();
            }
        });
    }

    _destroyEditor() {
        if (this._editor) {
            this._editor.destroy();
            this._editor = null;
        }
    }
}

// Browser global export
if (typeof window !== 'undefined') {
    window.EditorController = EditorController;
}

/**
 * FileTreeComponent - Collapsible file browser sidebar
 *
 * Features:
 * - Lazy-loads directory contents via /files/list
 * - Expand/collapse directories
 * - Persists expanded state to localStorage
 * - Left-click file → preview/edit callback
 * - Right-click file → inject @file:path into chat
 * - Refresh button to reload current view
 *
 * @version 1.16.2
 */

class FileTreeComponent {
    /**
     * @param {HTMLElement} container - Element to render into
     * @param {Object} options
     * @param {string} options.serverUrl - Base server URL
     * @param {Function} options.getHeaders - Returns headers object for fetch calls
     * @param {Function} options.onFileClick - Called with relative path on left-click
     * @param {Function} options.onFileInject - Called with relative path on right-click
     */
    constructor(container, options = {}) {
        this.container = container;
        this.serverUrl = options.serverUrl || '';
        this.getHeaders = options.getHeaders || (() => ({}));
        this.onFileClick = options.onFileClick || (() => {});
        this.onFileInject = options.onFileInject || (() => {});

        // Expanded dirs: Set of relative paths ('' = root is always loaded)
        this.expandedDirs = new Set(this._loadState('ftExpandedDirs', []));
        // Cached dir contents: Map<relPath, entries[]>
        this.dirContents = new Map();
        // Loading indicator per path
        this.loadingDirs = new Set();
        // Error per path
        this.errors = new Map();

        this._render();
        this.refresh();
    }

    // ── Persistence ─────────────────────────────────────────────────────────

    _loadState(key, defaultValue) {
        try {
            const raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : defaultValue;
        } catch {
            return defaultValue;
        }
    }

    _saveState(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
        } catch {
            // quota exceeded or private mode — ignore
        }
    }

    _persistExpanded() {
        this._saveState('ftExpandedDirs', Array.from(this.expandedDirs));
    }

    // ── Data loading ─────────────────────────────────────────────────────────

    /**
     * Reload root (and any already-expanded subdirs).
     */
    async refresh() {
        this.dirContents.clear();
        this.errors.clear();
        await this._loadDir('');
        // Eagerly reload previously expanded dirs
        for (const dir of this.expandedDirs) {
            if (dir !== '') {
                await this._loadDir(dir);
            }
        }
        this._renderTree();
    }

    async _loadDir(relPath) {
        this.loadingDirs.add(relPath);
        this._renderTree();
        try {
            const url = relPath
                ? `${this.serverUrl}/files/list?path=${encodeURIComponent(relPath)}`
                : `${this.serverUrl}/files/list`;
            const resp = await fetch(url, { headers: this.getHeaders() });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({ detail: resp.statusText }));
                this.errors.set(relPath, err.detail || 'Error');
            } else {
                const data = await resp.json();
                this.dirContents.set(relPath, data.files || []);
                this.errors.delete(relPath);
            }
        } catch (e) {
            this.errors.set(relPath, e.message);
        } finally {
            this.loadingDirs.delete(relPath);
            this._renderTree();
        }
    }

    // ── Rendering ────────────────────────────────────────────────────────────

    _render() {
        this.container.innerHTML = `
            <div class="ft-header">
                <span class="ft-title">FILES</span>
                <button class="ft-refresh-btn" title="Refresh">⟳</button>
            </div>
            <div class="ft-body" id="ftBody"></div>
        `;
        this.container.querySelector('.ft-refresh-btn').addEventListener('click', () => this.refresh());
        this._treeEl = this.container.querySelector('#ftBody');
    }

    _renderTree() {
        if (!this._treeEl) return;
        this._treeEl.innerHTML = this._renderDir('', 0);
        this._attachListeners(this._treeEl);
    }

    _renderDir(relPath, depth) {
        if (this.loadingDirs.has(relPath)) {
            return `<div class="ft-loading" style="padding-left:${8 + depth * 14}px">Loading…</div>`;
        }
        const errMsg = this.errors.get(relPath);
        if (errMsg) {
            return `<div class="ft-error" style="padding-left:${8 + depth * 14}px" title="${_ftEscHtml(errMsg)}">⚠ ${_ftEscHtml(errMsg)}</div>`;
        }
        const entries = this.dirContents.get(relPath);
        if (!entries) return '';

        let html = '';
        for (const entry of entries) {
            html += this._renderEntry(entry, relPath, depth);
        }
        return html;
    }

    _renderEntry(entry, parentRelPath, depth) {
        const name = entry.is_dir ? entry.name.replace(/\/$/, '') : entry.name;
        const entryRelPath = parentRelPath ? `${parentRelPath}/${name}` : name;
        const indent = 8 + depth * 14;

        if (entry.is_dir) {
            const isExpanded = this.expandedDirs.has(entryRelPath);
            const chevron = isExpanded ? '▾' : '▸';
            let html = `
                <div class="ft-node ft-dir ${isExpanded ? 'ft-expanded' : ''}"
                     data-path="${_ftEscHtml(entryRelPath)}"
                     data-is-dir="1"
                     style="padding-left:${indent}px"
                     title="${_ftEscHtml(entryRelPath)}">
                    <span class="ft-chevron">${chevron}</span>
                    <span class="ft-icon">📁</span>
                    <span class="ft-name">${_ftEscHtml(name)}</span>
                </div>`;
            if (isExpanded) {
                html += this._renderDir(entryRelPath, depth + 1);
            }
            return html;
        } else {
            const icon = _ftFileIcon(name);
            return `
                <div class="ft-node ft-file"
                     data-path="${_ftEscHtml(entryRelPath)}"
                     data-is-dir="0"
                     style="padding-left:${indent + 18}px"
                     title="${_ftEscHtml(entryRelPath)}">
                    <span class="ft-icon">${icon}</span>
                    <span class="ft-name">${_ftEscHtml(name)}</span>
                </div>`;
        }
    }

    _attachListeners(treeEl) {
        treeEl.querySelectorAll('.ft-node').forEach(node => {
            node.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const path = node.dataset.path;
                const isDir = node.dataset.isDir === '1';
                if (isDir) {
                    this._toggleDir(path);
                } else {
                    this.onFileClick(path);
                }
            });

            node.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                const path = node.dataset.path;
                const isDir = node.dataset.isDir === '1';
                if (!isDir) {
                    this.onFileInject(path);
                }
            });
        });
    }

    async _toggleDir(relPath) {
        if (this.expandedDirs.has(relPath)) {
            this.expandedDirs.delete(relPath);
            this._persistExpanded();
            this._renderTree();
        } else {
            this.expandedDirs.add(relPath);
            this._persistExpanded();
            if (!this.dirContents.has(relPath)) {
                await this._loadDir(relPath);
            } else {
                this._renderTree();
            }
        }
    }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function _ftEscHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function _ftFileIcon(name) {
    const ext = name.split('.').pop().toLowerCase();
    const icons = {
        py: '🐍', js: '📜', ts: '📘', jsx: '⚛', tsx: '⚛',
        json: '{}', yaml: '📋', yml: '📋', toml: '📋',
        md: '📝', txt: '📄', rst: '📝',
        html: '🌐', css: '🎨', scss: '🎨',
        sh: '🔧', bash: '🔧', zsh: '🔧',
        go: '🐹', rs: '🦀', java: '☕', rb: '💎', php: '🐘',
        c: '🔷', cpp: '🔷', h: '🔷', cs: '🔷',
        sql: '🗄', db: '🗄',
        png: '🖼', jpg: '🖼', jpeg: '🖼', gif: '🖼', svg: '🖼', webp: '🖼',
        pdf: '📕', zip: '📦', tar: '📦', gz: '📦',
        dockerfile: '🐳', 'docker-compose': '🐳',
        lock: '🔒', env: '🔑',
    };
    // Special filenames
    const lower = name.toLowerCase();
    if (lower === 'dockerfile') return '🐳';
    if (lower === '.env' || lower.startsWith('.env.')) return '🔑';
    if (lower === 'makefile') return '🔧';
    return icons[ext] || '📄';
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = FileTreeComponent;
}

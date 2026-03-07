/**
 * FileTreeComponent - Collapsible file browser sidebar
 *
 * Features:
 * - Lazy-loads directory contents via /files/list
 * - Expand/collapse directories (single-click)
 * - Double-click directory → cd into it (new working dir root)
 * - Right-click directory → "cd here" context action
 * - ".." parent entry at tree top → cd to parent directory
 * - Persists expanded state to localStorage
 * - Left-click file → preview callback (read-only)
 * - Double-click file → edit callback (editable)
 * - Right-click file → inject @file:path into chat
 * - Refresh button to reload current view
 *
 * Interaction model:
 *   Folders:
 *     single-click   → expand / collapse
 *     double-click   → cd into directory (becomes new working dir root)
 *     right-click    → cd here (same as double-click, for discoverability)
 *   Files:
 *     single-click   → preview (read-only in right panel)
 *     double-click   → open for editing
 *     right-click    → inject @file:path into chat input
 *   ".." entry:
 *     single-click   → cd to parent directory
 *
 * @version 1.16.3
 */

class FileTreeComponent {
    /**
     * @param {HTMLElement} container - Element to render into
     * @param {Object} options
     * @param {string} options.serverUrl - Base server URL
     * @param {Function} options.getHeaders - Returns headers object for fetch calls
     * @param {Function} options.onFileClick - Called with relative path on left-click (preview)
     * @param {Function} options.onFileEdit - Called with relative path on double-click (edit)
     * @param {Function} options.onFileInject - Called with relative path on right-click (files)
     * @param {Function} options.onDirCd - Called with target path string when user cds into a dir
     */
    constructor(container, options = {}) {
        this.container = container;
        this.serverUrl = options.serverUrl || '';
        this.getHeaders = options.getHeaders || (() => ({}));
        this.onFileClick = options.onFileClick || (() => {});
        this.onFileEdit = options.onFileEdit || (() => {});
        this.onFileInject = options.onFileInject || (() => {});
        this.onDirCd = options.onDirCd || (() => {});
        this._clickTimer = null;

        // Expanded dirs: Set of relative paths ('' = root is always loaded)
        this.expandedDirs = new Set(this._loadState('ftExpandedDirs', []));
        // Cached dir contents: Map<relPath, entries[]>
        this.dirContents = new Map();
        // Loading indicator per path
        this.loadingDirs = new Set();
        // Error per path
        this.errors = new Map();
        // Whether cwd is filesystem root (no ".." available)
        this._atFsRoot = false;

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
     * @param {boolean} [clearExpanded=false] - When true, collapse all expanded dirs
     *   first (used when working directory changes to avoid stale 404 paths).
     */
    async refresh(clearExpanded = false) {
        if (clearExpanded) {
            this.expandedDirs.clear();
            this._persistExpanded();
        }
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
                // Prune stale paths (404) — path doesn't exist in current working dir
                if (resp.status === 404 && relPath) {
                    this.expandedDirs.delete(relPath);
                    this._persistExpanded();
                }
            } else {
                const data = await resp.json();
                this.dirContents.set(relPath, data.files || []);
                this.errors.delete(relPath);
                // Detect whether we're at filesystem root by checking if parent exists
                if (relPath === '') {
                    this._atFsRoot = data.at_fs_root === true;
                }
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
        let html = '';
        // ".." parent entry — always first, unless we're at filesystem root
        if (!this._atFsRoot) {
            html += `
                <div class="ft-node ft-parent-dir" data-path=".." data-is-dir="1" data-is-parent="1"
                     style="padding-left:8px" title="Go to parent directory">
                    <span class="ft-chevron" style="visibility:hidden">▸</span>
                    <span class="ft-icon">📁</span>
                    <span class="ft-name ft-parent-label">..</span>
                </div>`;
        }
        html += this._renderDir('', 0);
        this._treeEl.innerHTML = html;
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
                     title="Click: expand  |  Dbl-click: cd here  |  ${_ftEscHtml(entryRelPath)}">
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
            const path = node.dataset.path;
            const isDir = node.dataset.isDir === '1';
            const isParent = node.dataset.isParent === '1';

            node.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (isParent) {
                    // ".." — always cd to parent
                    this.onDirCd('..');
                } else if (isDir) {
                    // Regular dir: single-click = expand/collapse
                    this._toggleDir(path);
                } else {
                    // File: delay single-click so dblclick can cancel it
                    clearTimeout(this._clickTimer);
                    this._clickTimer = setTimeout(() => this.onFileClick(path), 150);
                }
            });

            node.addEventListener('dblclick', (e) => {
                e.preventDefault();
                e.stopPropagation();
                clearTimeout(this._clickTimer);
                if (isDir && !isParent) {
                    // Double-click dir → cd into it (becomes new working dir root)
                    this.onDirCd(path);
                } else if (!isDir) {
                    // Double-click file → open for editing
                    this.onFileEdit(path);
                }
            });

            node.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                if (isDir && !isParent) {
                    // Right-click dir → cd here
                    this.onDirCd(path);
                } else if (!isDir) {
                    // Right-click file → inject @file ref
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

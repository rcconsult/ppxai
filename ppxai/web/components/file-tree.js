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
     * @param {Function} options.onFileClick - (relPath, cwdAnchor) → preview file (single-click)
     * @param {Function} options.onFileEdit  - (relPath, cwdAnchor) → open editor (double-click)
     * @param {Function} options.onFileInject - (relPath) → inject @file ref (right-click)
     * @param {Function} options.onFileDownload - (relPath, cwdAnchor) → download file (download icon click) [v1.18.7]
     * @param {Function} options.onFileUpload   - (destRelPath, fileList, cwdAnchor) → upload files INTO that directory [v1.18.7]
     * @param {Function} options.onDirCd     - (path) → cd into directory
     *
     *   `cwdAnchor` (v1.18.1 Phase D) is the working_dir the most
     *   recent /files/list was anchored against. Click handlers
     *   pass it to apiClient.readFile/writeFile so the server can
     *   return 409 if engine cwd has drifted since the tree
     *   loaded. Caller can ignore (omit the second param) for
     *   backward-compat — anchor is optional on the server side.
     */
    constructor(container, options = {}) {
        this.container = container;
        this.serverUrl = options.serverUrl || '';
        this.getHeaders = options.getHeaders || (() => ({}));
        this.onFileClick = options.onFileClick || (() => {});
        this.onFileEdit = options.onFileEdit || (() => {});
        this.onFileInject = options.onFileInject || (() => {});
        this.onFileDownload = options.onFileDownload || (() => {});  // v1.18.7
        this.onFileUpload = options.onFileUpload || (() => {});      // v1.18.7
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
        // v1.18.1 Phase D: working_dir reported by the most recent
        // /files/list response. Click actions pass this as
        // `cwd_anchor` so the server can return 409 on drift.
        this.workingDirAtLoad = null;

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
                ? `${this.serverUrl}/files/list?path=${encodeURIComponent(relPath)}&a=true`
                : `${this.serverUrl}/files/list?a=true`;
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
                // v1.18.1 Phase D: record the cwd this listing was
                // anchored against. Subsequent click actions on this
                // entry pass `working_dir` as `cwd_anchor` so the
                // server can detect drift if engine cwd has moved.
                if (data.working_dir) {
                    this.workingDirAtLoad = data.working_dir;
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
        // v1.18.7: Upload affordances. A header button picks files via the
        // OS dialog; container-level drag/drop accepts files dropped
        // anywhere in the sidebar background — both land at working_dir
        // root. Per-directory drop happens on the row itself (wired in
        // _attachListeners). Same UI ships to ppxai-desktop and the
        // coder.internal per-user pod — the latter is the use case that
        // actually motivated this (pods start with empty /workspace, and
        // not every user is comfortable using git from the terminal).
        this.container.innerHTML = `
            <div class="ft-header">
                <span class="ft-title">FILES</span>
                <button class="ft-upload-btn" title="Upload file(s) to current working directory">⬆ Upload</button>
                <button class="ft-refresh-btn" title="Refresh">⟳</button>
            </div>
            <div class="ft-body" id="ftBody"></div>
            <input type="file" class="ft-upload-input" multiple style="display:none" />
        `;
        this.container.querySelector('.ft-refresh-btn').addEventListener('click', () => this.refresh());

        const uploadBtn = this.container.querySelector('.ft-upload-btn');
        const uploadInput = this.container.querySelector('.ft-upload-input');
        uploadBtn.addEventListener('click', () => uploadInput.click());
        uploadInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files.length > 0) {
                // Empty destRelPath = upload to working_dir root.
                this.onFileUpload('', Array.from(e.target.files), this.workingDirAtLoad);
                // Reset so re-selecting the same file fires `change` again.
                e.target.value = '';
            }
        });

        this._treeEl = this.container.querySelector('#ftBody');

        // Container-level drag/drop. Lets users drop a file onto the
        // sidebar background (between rows / below the tree) and have
        // it upload to working_dir root. Per-row drops bubble up to
        // here and are short-circuited at the row handler with
        // stopPropagation so they don't double-fire.
        this._treeEl.addEventListener('dragover', (e) => {
            // Only handle if the drag carries files (not text drags within the tree).
            if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) {
                e.preventDefault();
                this._treeEl.classList.add('ft-drag-over');
            }
        });
        this._treeEl.addEventListener('dragleave', (e) => {
            // Only clear when leaving the container itself, not when
            // moving between child rows.
            if (e.target === this._treeEl) {
                this._treeEl.classList.remove('ft-drag-over');
            }
        });
        this._treeEl.addEventListener('drop', (e) => {
            e.preventDefault();
            this._treeEl.classList.remove('ft-drag-over');
            const files = e.dataTransfer && e.dataTransfer.files;
            if (files && files.length > 0) {
                this.onFileUpload('', Array.from(files), this.workingDirAtLoad);
            }
        });
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
            // v1.18.7: inline download icon. data-action="download" lets the
            // click handler distinguish it from the row click (preview). The
            // icon stays hidden until row-hover via CSS (.ft-download-btn
            // opacity 0 → 1 on .ft-node:hover) so the tree stays uncluttered.
            return `
                <div class="ft-node ft-file"
                     data-path="${_ftEscHtml(entryRelPath)}"
                     data-is-dir="0"
                     style="padding-left:${indent + 18}px"
                     title="${_ftEscHtml(entryRelPath)}">
                    <span class="ft-icon">${icon}</span>
                    <span class="ft-name">${_ftEscHtml(name)}</span>
                    <button class="ft-download-btn"
                            data-action="download"
                            title="Download file">⬇</button>
                </div>`;
        }
    }

    _attachListeners(treeEl) {
        treeEl.querySelectorAll('.ft-node').forEach(node => {
            const path = node.dataset.path;
            const isDir = node.dataset.isDir === '1';
            const isParent = node.dataset.isParent === '1';

            // v1.18.1 Phase D: snapshot the cwd this listing was
            // anchored against at click time. The handler passes
            // it through to readFile/writeFile as `cwd_anchor` so
            // the server can return 409 if engine cwd has drifted
            // since the tree was loaded.
            const anchor = this.workingDirAtLoad;

            node.addEventListener('click', (e) => {
                // v1.18.7: download-icon clicks short-circuit before
                // any of the row dispatch logic, so the preview never
                // fires alongside the download.
                if (e.target && e.target.dataset && e.target.dataset.action === 'download') {
                    e.preventDefault();
                    e.stopPropagation();
                    clearTimeout(this._clickTimer);
                    if (!isDir) this.onFileDownload(path, anchor);
                    return;
                }

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
                    this._clickTimer = setTimeout(() => this.onFileClick(path, anchor), 150);
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
                    this.onFileEdit(path, anchor);
                }
            });

            // v1.18.7: per-directory drop target. Dropping files on a
            // directory row uploads them INTO that directory. The
            // dragover handler highlights the row so users see where
            // their drop will land. Parent ("..") doesn't accept drops
            // because the relative-path semantics get confusing.
            if (isDir && !isParent) {
                node.addEventListener('dragover', (e) => {
                    if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) {
                        e.preventDefault();
                        e.stopPropagation();
                        node.classList.add('ft-drag-target');
                    }
                });
                node.addEventListener('dragleave', (e) => {
                    // Use relatedTarget to avoid flicker as cursor crosses
                    // child spans inside the row.
                    if (!node.contains(e.relatedTarget)) {
                        node.classList.remove('ft-drag-target');
                    }
                });
                node.addEventListener('drop', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    node.classList.remove('ft-drag-target');
                    const files = e.dataTransfer && e.dataTransfer.files;
                    if (files && files.length > 0) {
                        this.onFileUpload(path, Array.from(files), anchor);
                    }
                });
            }

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

/**
 * DataTreeViewer - Interactive JSON/YAML/TOML/HCL tree viewer component
 *
 * Features:
 * - Collapsible/expandable nodes
 * - Expand all / Collapse all controls
 * - Syntax-colored values by type
 * - Copy path on click
 * - Search within tree
 *
 * @version 1.13.8
 */

class DataTreeViewer {
    /**
     * Create a new DataTreeViewer
     * @param {HTMLElement} container - Container element to render into
     * @param {Object} data - Parsed tree data (TreeNode structure)
     * @param {Object} options - Configuration options
     */
    constructor(container, data, options = {}) {
        this.container = container;
        this.data = data;
        this.options = {
            initialExpandDepth: options.initialExpandDepth || 2,
            maxDisplayDepth: options.maxDisplayDepth || 20,
            maxValueLength: options.maxValueLength || 200,
            searchable: options.searchable !== false,
            ...options
        };

        // State
        this.expandedPaths = new Set();
        this.searchText = '';
        this.searchMatches = new Set();
        this.searchRegex = false;  // Regex mode toggle
        this.searchJq = false;     // jq expression mode

        this.initializeExpanded();
        this.render();
    }

    /**
     * Get placeholder text based on search mode
     */
    getSearchPlaceholder() {
        if (this.searchJq) {
            return 'jq expression... (Enter to apply)';
        } else if (this.searchRegex) {
            return 'Regex pattern... (Enter to apply)';
        }
        return 'Search keys/values... (Enter to apply)';
    }

    /**
     * Initialize expanded state based on initialExpandDepth
     */
    initializeExpanded() {
        this.traverseTree(this.data, '', 0, (path, depth, node) => {
            if (depth < this.options.initialExpandDepth && node.children && node.children.length > 0) {
                this.expandedPaths.add(path);
            }
        });
    }

    /**
     * Traverse tree and call callback for each node
     * @param {Object} node - Current node
     * @param {string} path - Current path
     * @param {number} depth - Current depth
     * @param {Function} callback - Callback function(path, depth, node)
     */
    traverseTree(node, path, depth, callback) {
        callback(path, depth, node);
        if (node.children) {
            node.children.forEach((child, i) => {
                const childPath = path ? `${path}.${child.key}` : child.key;
                this.traverseTree(child, childPath, depth + 1, callback);
            });
        }
    }

    /**
     * Render the tree viewer
     */
    render() {
        this.container.innerHTML = `
            <div class="data-tree-viewer">
                <div class="tree-controls">
                    <button type="button" class="tree-btn expand-all" title="Expand All">Expand All</button>
                    <button type="button" class="tree-btn collapse-all" title="Collapse All">Collapse All</button>
                    ${this.options.searchable ? `
                        <input type="text"
                               class="tree-search"
                               placeholder="${this.getSearchPlaceholder()}"
                               value="${this.escapeHtml(this.searchText)}">
                        <button type="button" class="tree-btn search-regex-btn ${this.searchRegex ? 'active' : ''}" title="Regex mode">.*</button>
                        <button type="button" class="tree-btn search-jq-btn ${this.searchJq ? 'active' : ''}" title="jq expression mode">.jq</button>
                        <button type="button" class="tree-btn search-help-btn" title="Search help">?</button>
                        <button type="button" class="tree-btn search-btn">Search</button>
                        ${this.searchText ? '<button type="button" class="tree-btn search-clear-btn">Clear</button>' : ''}
                        ${this.searchMatches.size > 0 ? `<span class="search-count">${this.searchMatches.size} matches</span>` : ''}
                    ` : ''}
                </div>
                <div class="tree-content">
                    ${this.renderNode(this.data, '', 0)}
                </div>
            </div>
        `;

        this.attachEventListeners();
    }

    /**
     * Render a tree node
     * @param {Object} node - Node to render
     * @param {string} path - Current path
     * @param {number} depth - Current depth
     * @returns {string} HTML string
     */
    renderNode(node, path, depth) {
        if (depth > this.options.maxDisplayDepth) {
            return '<span class="tree-truncated">... (max depth reached)</span>';
        }

        const hasChildren = node.children && node.children.length > 0;
        const expanded = this.expandedPaths.has(path);
        const isMatch = this.searchMatches.has(path);

        let html = `<div class="tree-node ${isMatch ? 'search-match' : ''}" data-path="${this.escapeHtml(path)}" data-depth="${depth}">`;

        // Toggle indicator
        if (hasChildren) {
            html += `<span class="tree-toggle ${expanded ? 'expanded' : 'collapsed'}">${expanded ? '\u25BC' : '\u25B6'}</span>`;
        } else {
            html += '<span class="tree-toggle-spacer"></span>';
        }

        // Key
        html += `<span class="tree-key" title="Click to copy path">${this.escapeHtml(node.key)}</span>`;

        if (hasChildren) {
            // Object/Array indicator
            const typeIndicator = node.node_type === 'array'
                ? `<span class="tree-type-indicator">[${node.children.length}]</span>`
                : `<span class="tree-type-indicator">{${node.children.length}}</span>`;
            html += typeIndicator;

            if (expanded) {
                html += '<div class="tree-children">';
                node.children.forEach(child => {
                    const childPath = path ? `${path}.${child.key}` : child.key;
                    html += this.renderNode(child, childPath, depth + 1);
                });
                html += '</div>';
            } else {
                // Show preview when collapsed
                html += this.renderCollapsedPreview(node);
            }
        } else {
            // Leaf node - show value
            html += '<span class="tree-separator">: </span>';
            html += this.renderValue(node.value, node.node_type);
        }

        html += '</div>';
        return html;
    }

    /**
     * Render a preview for collapsed nodes
     * @param {Object} node - Node to preview
     * @returns {string} HTML string
     */
    renderCollapsedPreview(node) {
        if (!node.children || node.children.length === 0) return '';

        // Show first few keys/items as preview
        const maxPreview = 3;
        const items = node.children.slice(0, maxPreview).map(child => {
            if (child.children && child.children.length > 0) {
                return child.key;
            }
            return `${child.key}: ${this.truncateValue(child.value, 20)}`;
        });

        if (node.children.length > maxPreview) {
            items.push('...');
        }

        return `<span class="tree-preview">${this.escapeHtml(items.join(', '))}</span>`;
    }

    /**
     * Render a value with type-based styling
     * @param {*} value - Value to render
     * @param {string} nodeType - Type of the value
     * @returns {string} HTML string
     */
    renderValue(value, nodeType) {
        let displayValue;
        let className = `tree-value type-${nodeType}`;

        switch (nodeType) {
            case 'string':
                displayValue = `"${this.truncateValue(value, this.options.maxValueLength)}"`;
                break;
            case 'number':
                displayValue = String(value);
                break;
            case 'boolean':
                displayValue = String(value).toLowerCase();
                break;
            case 'null':
                displayValue = 'null';
                break;
            default:
                displayValue = String(value);
        }

        return `<span class="${className}">${this.escapeHtml(displayValue)}</span>`;
    }

    /**
     * Truncate a value for display
     * @param {*} value - Value to truncate
     * @param {number} maxLength - Maximum length
     * @returns {string} Truncated string
     */
    truncateValue(value, maxLength) {
        const str = String(value ?? '');
        if (str.length > maxLength) {
            return str.substring(0, maxLength - 3) + '...';
        }
        return str;
    }

    /**
     * Attach event listeners
     */
    attachEventListeners() {
        // Toggle on click
        this.container.querySelectorAll('.tree-toggle').forEach(toggle => {
            toggle.addEventListener('click', (e) => {
                e.stopPropagation();
                const node = toggle.closest('.tree-node');
                const path = node.dataset.path;
                this.toggleNode(path);
            });
        });

        // Copy path on key click
        this.container.querySelectorAll('.tree-key').forEach(key => {
            key.addEventListener('click', (e) => {
                e.stopPropagation();
                const node = key.closest('.tree-node');
                const path = node.dataset.path;
                this.copyPath(path);
            });
        });

        // Expand/Collapse all buttons
        const expandBtn = this.container.querySelector('.expand-all');
        if (expandBtn) {
            expandBtn.onclick = () => this.expandAll();
        }
        const collapseBtn = this.container.querySelector('.collapse-all');
        if (collapseBtn) {
            collapseBtn.onclick = () => this.collapseAll();
        }

        // Search input - apply on Enter key
        const searchInput = this.container.querySelector('.tree-search');
        if (searchInput) {
            searchInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    this.search(e.target.value);
                }
            });
        }

        // Search button
        const searchBtn = this.container.querySelector('.search-btn');
        if (searchBtn) {
            searchBtn.onclick = () => {
                const input = this.container.querySelector('.tree-search');
                if (input) this.search(input.value);
            };
        }

        // Clear search button
        const clearBtn = this.container.querySelector('.search-clear-btn');
        if (clearBtn) {
            clearBtn.onclick = () => this.search('');
        }

        // Regex toggle button
        const regexBtn = this.container.querySelector('.search-regex-btn');
        if (regexBtn) {
            regexBtn.onclick = () => {
                this.searchRegex = !this.searchRegex;
                if (this.searchRegex) this.searchJq = false;  // Mutually exclusive
                this.render();
                // Re-apply search if active
                if (this.searchText) this.search(this.searchText);
            };
        }

        // jq toggle button
        const jqBtn = this.container.querySelector('.search-jq-btn');
        if (jqBtn) {
            jqBtn.onclick = () => {
                this.searchJq = !this.searchJq;
                if (this.searchJq) this.searchRegex = false;  // Mutually exclusive
                this.render();
                // Re-apply search if active
                if (this.searchText) this.search(this.searchText);
            };
        }

        // Help button
        const helpBtn = this.container.querySelector('.search-help-btn');
        if (helpBtn) {
            helpBtn.onclick = () => this.showSearchHelp();
        }
    }

    /**
     * Show search help popup
     */
    showSearchHelp() {
        // Remove existing popup if any
        const existing = document.querySelector('.tree-help-popup');
        if (existing) {
            existing.remove();
            return;  // Toggle off
        }

        const popup = document.createElement('div');
        popup.className = 'tree-help-popup regex-help-popup';
        popup.innerHTML = `
            <div class="regex-help-header">
                <span>Search Reference</span>
                <button type="button" class="regex-help-close">&times;</button>
            </div>
            <div style="margin-bottom: 12px; font-weight: 600;">Plain Text</div>
            <table class="regex-help-table">
                <tr><td>foo</td><td colspan="2">Match keys or values containing "foo"</td></tr>
            </table>
            <div style="margin: 12px 0 8px; font-weight: 600;">Regex Mode <code>.*</code></div>
            <table class="regex-help-table">
                <tr><td><code>.</code></td><td>Any character</td><td>A.ice → Alice</td></tr>
                <tr><td><code>.*</code></td><td>Zero or more</td><td>foo.* → foobar</td></tr>
                <tr><td><code>^</code></td><td>Start of string</td><td>^id → id, id_</td></tr>
                <tr><td><code>$</code></td><td>End of string</td><td>_id$ → user_id</td></tr>
                <tr><td><code>\\d+</code></td><td>Digits</td><td>Match numbers</td></tr>
                <tr><td><code>|</code></td><td>OR</td><td>foo|bar</td></tr>
            </table>
            <div style="margin: 12px 0 8px; font-weight: 600;">jq Mode <code>.jq</code></div>
            <table class="regex-help-table">
                <tr><td><code>.foo</code></td><td colspan="2">Select field "foo"</td></tr>
                <tr><td><code>.foo.bar</code></td><td colspan="2">Nested path foo → bar</td></tr>
                <tr><td><code>.[0]</code></td><td colspan="2">First array element</td></tr>
                <tr><td><code>.foo[0]</code></td><td colspan="2">First element of foo array</td></tr>
                <tr><td><code>.foo[]</code></td><td colspan="2">All elements of foo array</td></tr>
                <tr><td><code>.*</code></td><td colspan="2">All top-level keys</td></tr>
            </table>
            <div class="regex-help-footer">Case-insensitive matching (plain/regex)</div>
        `;

        // Position fixed relative to viewport
        const btnRect = this.container.querySelector('.search-help-btn').getBoundingClientRect();
        popup.style.position = 'fixed';
        popup.style.top = (btnRect.bottom + 4) + 'px';
        popup.style.left = Math.max(10, btnRect.left - 200) + 'px';
        popup.style.zIndex = '1000';

        document.body.appendChild(popup);

        // Close button
        popup.querySelector('.regex-help-close').onclick = () => popup.remove();

        // Close on click outside
        setTimeout(() => {
            document.addEventListener('click', function closePopup(e) {
                if (!popup.contains(e.target) && !e.target.closest('.search-help-btn')) {
                    popup.remove();
                    document.removeEventListener('click', closePopup);
                }
            });
        }, 100);
    }

    /**
     * Toggle a node's expanded state
     * @param {string} path - Path to toggle
     */
    toggleNode(path) {
        if (this.expandedPaths.has(path)) {
            this.expandedPaths.delete(path);
        } else {
            this.expandedPaths.add(path);
        }
        this.render();
    }

    /**
     * Expand all nodes
     */
    expandAll() {
        this.traverseTree(this.data, '', 0, (path, depth, node) => {
            if (node.children && node.children.length > 0 && depth < this.options.maxDisplayDepth) {
                this.expandedPaths.add(path);
            }
        });
        this.render();
    }

    /**
     * Collapse all nodes
     */
    collapseAll() {
        this.expandedPaths.clear();
        this.render();
    }

    /**
     * Search tree for matching keys/values
     * @param {string} text - Search text
     */
    search(text) {
        this.searchText = text;
        this.searchMatches.clear();

        if (!text.trim()) {
            this.render();
            return;
        }

        if (this.searchJq) {
            // jq expression mode
            this.searchWithJq(text);
        } else if (this.searchRegex) {
            // Regex mode
            this.searchWithRegex(text);
        } else {
            // Plain text mode
            this.searchWithText(text);
        }

        this.render();
    }

    /**
     * Plain text search
     */
    searchWithText(text) {
        const searchLower = text.toLowerCase();

        this.traverseTree(this.data, '', 0, (path, depth, node) => {
            // Check key match
            if (node.key.toLowerCase().includes(searchLower)) {
                this.searchMatches.add(path);
                this.expandParents(path);
            }
            // Check value match (for leaf nodes)
            if (node.value !== null && node.value !== undefined) {
                if (String(node.value).toLowerCase().includes(searchLower)) {
                    this.searchMatches.add(path);
                    this.expandParents(path);
                }
            }
        });
    }

    /**
     * Regex search
     */
    searchWithRegex(pattern) {
        try {
            const regex = new RegExp(pattern, 'i');

            this.traverseTree(this.data, '', 0, (path, depth, node) => {
                // Check key match
                if (regex.test(node.key)) {
                    this.searchMatches.add(path);
                    this.expandParents(path);
                }
                // Check value match
                if (node.value !== null && node.value !== undefined) {
                    if (regex.test(String(node.value))) {
                        this.searchMatches.add(path);
                        this.expandParents(path);
                    }
                }
            });
        } catch (e) {
            // Invalid regex - no matches
        }
    }

    /**
     * jq-style expression search
     * Supports: .foo, .foo.bar, .[0], .foo[0], .foo[], .*
     */
    searchWithJq(expr) {
        if (!expr.startsWith('.')) {
            return;  // jq expressions must start with .
        }

        // Parse the jq expression into path segments
        const segments = this.parseJqExpression(expr);
        if (!segments) return;

        // Find matching paths
        this.findJqMatches(this.data, '', 0, segments);
    }

    /**
     * Parse jq expression into segments
     * @param {string} expr - jq expression like .foo.bar[0]
     * @returns {Array|null} Array of segments or null if invalid
     */
    parseJqExpression(expr) {
        const segments = [];
        let remaining = expr.slice(1);  // Remove leading .

        while (remaining.length > 0) {
            if (remaining.startsWith('.')) {
                remaining = remaining.slice(1);
                continue;
            }

            // Match array index [n] or [] for all
            const arrayMatch = remaining.match(/^\[(\d*)\]/);
            if (arrayMatch) {
                segments.push({
                    type: arrayMatch[1] === '' ? 'array_all' : 'array_index',
                    index: arrayMatch[1] === '' ? null : parseInt(arrayMatch[1])
                });
                remaining = remaining.slice(arrayMatch[0].length);
                continue;
            }

            // Match wildcard *
            if (remaining.startsWith('*')) {
                segments.push({ type: 'wildcard' });
                remaining = remaining.slice(1);
                continue;
            }

            // Match key name (up to next . or [ or end)
            const keyMatch = remaining.match(/^([^.\[]+)/);
            if (keyMatch) {
                segments.push({ type: 'key', name: keyMatch[1] });
                remaining = remaining.slice(keyMatch[0].length);
                continue;
            }

            // Invalid expression
            return null;
        }

        return segments.length > 0 ? segments : null;
    }

    /**
     * Find nodes matching jq path segments
     */
    findJqMatches(node, path, segmentIndex, segments) {
        if (segmentIndex >= segments.length) {
            // Reached end of expression - this is a match
            this.searchMatches.add(path);
            this.expandParents(path);
            return;
        }

        const segment = segments[segmentIndex];

        if (!node.children) {
            return;  // Leaf node, can't go deeper
        }

        switch (segment.type) {
            case 'key':
                // Find child with matching key
                const child = node.children.find(c => c.key.toLowerCase() === segment.name.toLowerCase());
                if (child) {
                    const childPath = path ? `${path}.${child.key}` : child.key;
                    this.findJqMatches(child, childPath, segmentIndex + 1, segments);
                }
                break;

            case 'array_index':
                // Find child at specific index
                const indexChild = node.children[segment.index];
                if (indexChild) {
                    const indexPath = path ? `${path}.${indexChild.key}` : indexChild.key;
                    this.findJqMatches(indexChild, indexPath, segmentIndex + 1, segments);
                }
                break;

            case 'array_all':
            case 'wildcard':
                // Match all children
                node.children.forEach(child => {
                    const childPath = path ? `${path}.${child.key}` : child.key;
                    this.findJqMatches(child, childPath, segmentIndex + 1, segments);
                });
                break;
        }
    }

    /**
     * Expand all parent nodes of a path
     * @param {string} path - Path to expand parents for
     */
    expandParents(path) {
        const parts = path.split('.');
        let currentPath = '';
        for (let i = 0; i < parts.length - 1; i++) {
            currentPath = currentPath ? `${currentPath}.${parts[i]}` : parts[i];
            this.expandedPaths.add(currentPath);
        }
    }

    /**
     * Copy a path to clipboard
     * @param {string} path - Path to copy
     */
    copyPath(path) {
        navigator.clipboard.writeText(path).then(() => {
            // Show brief feedback
            const key = this.container.querySelector(`[data-path="${path}"] .tree-key`);
            if (key) {
                const original = key.textContent;
                key.textContent = 'Copied!';
                key.classList.add('copied');
                setTimeout(() => {
                    key.textContent = original;
                    key.classList.remove('copied');
                }, 1000);
            }
        }).catch(err => {
            console.error('Failed to copy path:', err);
        });
    }

    /**
     * Escape HTML special characters
     * @param {string} str - String to escape
     * @returns {string} Escaped string
     */
    escapeHtml(str) {
        if (str === null || str === undefined) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    /**
     * Destroy the viewer and clean up
     */
    destroy() {
        this.container.innerHTML = '';
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DataTreeViewer;
}

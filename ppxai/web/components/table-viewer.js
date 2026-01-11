/**
 * DataTableViewer - Interactive CSV/TSV table viewer component
 *
 * Features:
 * - Sortable columns (click header to sort)
 * - Pagination for large datasets
 * - Scrollable container
 * - Search/filter
 * - Row highlighting on hover
 *
 * @version 1.13.8
 */

class DataTableViewer {
    /**
     * Create a new DataTableViewer
     * @param {HTMLElement} container - Container element to render into
     * @param {Object} data - Parsed table data {headers: string[], rows: string[][], rowCount: number}
     * @param {Object} options - Configuration options
     */
    constructor(container, data, options = {}) {
        this.container = container;
        this.data = data;
        this.options = {
            pageSize: options.pageSize || 100,
            maxHeight: options.maxHeight || '500px',
            showRowNumbers: options.showRowNumbers !== false,
            sortable: options.sortable !== false,
            filterable: options.filterable !== false,
            ...options
        };

        // State
        this.currentPage = 0;
        this.sortColumn = null;
        this.sortAsc = true;
        this.filterText = '';
        this.filterRegex = false;  // Regex mode toggle
        this.filterColumn = -1;    // -1 = all columns
        this.filteredRows = [...this.data.rows];

        this.render();
    }

    /**
     * Render the table viewer
     */
    render() {
        const totalPages = Math.ceil(this.filteredRows.length / this.options.pageSize);

        this.container.innerHTML = `
            <div class="data-table-viewer">
                ${this.options.filterable ? this.renderFilter() : ''}
                <div class="data-table-wrapper" style="max-height: ${this.options.maxHeight}; overflow: auto;">
                    <table class="data-table">
                        <thead>${this.renderHeader()}</thead>
                        <tbody>${this.renderRows()}</tbody>
                    </table>
                </div>
                ${totalPages > 1 ? this.renderPagination() : ''}
                <div class="data-table-info">
                    ${this.renderInfo()}
                </div>
            </div>
        `;

        this.attachEventListeners();
    }

    /**
     * Render filter/search input
     */
    renderFilter() {
        const regexActive = this.filterRegex ? 'active' : '';
        const placeholder = this.filterRegex
            ? 'Regex pattern... (Enter to apply)'
            : 'Filter rows... (Enter to apply)';

        // Build column options
        const columnOptions = this.data.headers.map((header, i) => {
            const selected = this.filterColumn === i ? 'selected' : '';
            return `<option value="${i}" ${selected}>${this.escapeHtml(header)}</option>`;
        }).join('');

        return `
            <div class="data-table-filter">
                <select class="filter-column-select">
                    <option value="-1" ${this.filterColumn === -1 ? 'selected' : ''}>All columns</option>
                    ${columnOptions}
                </select>
                <input type="text" class="data-table-search" placeholder="${placeholder}" value="${this.escapeHtml(this.filterText)}">
                <button type="button" class="filter-regex-btn ${regexActive}">.*</button>
                <button type="button" class="filter-help-btn">?</button>
                <button type="button" class="filter-btn">Filter</button>
                ${this.filterText ? '<button type="button" class="filter-clear-btn">Clear</button>' : ''}
                <span class="filter-count">${this.filteredRows.length} rows</span>
            </div>
        `;
    }

    /**
     * Render table header row
     */
    renderHeader() {
        let html = '<tr>';

        if (this.options.showRowNumbers) {
            html += '<th class="row-num-header">#</th>';
        }

        this.data.headers.forEach((header, i) => {
            const sortClass = this.sortColumn === i
                ? (this.sortAsc ? 'sort-asc' : 'sort-desc')
                : '';
            const sortableClass = this.options.sortable ? 'sortable' : '';

            html += `<th data-col="${i}" class="${sortableClass} ${sortClass}">
                ${this.escapeHtml(header)}
                ${this.options.sortable ? '<span class="sort-indicator"></span>' : ''}
            </th>`;
        });

        html += '</tr>';
        return html;
    }

    /**
     * Render table body rows for current page
     */
    renderRows() {
        const start = this.currentPage * this.options.pageSize;
        const end = Math.min(start + this.options.pageSize, this.filteredRows.length);
        const pageRows = this.filteredRows.slice(start, end);

        if (pageRows.length === 0) {
            const colSpan = this.data.headers.length + (this.options.showRowNumbers ? 1 : 0);
            return `<tr><td colspan="${colSpan}" class="no-data">No data to display</td></tr>`;
        }

        return pageRows.map((row, i) => {
            const rowNum = start + i + 1;
            let html = '<tr>';

            if (this.options.showRowNumbers) {
                html += `<td class="row-num">${rowNum}</td>`;
            }

            row.forEach(cell => {
                html += `<td>${this.escapeHtml(cell)}</td>`;
            });

            html += '</tr>';
            return html;
        }).join('');
    }

    /**
     * Render pagination controls
     */
    renderPagination() {
        const totalPages = Math.ceil(this.filteredRows.length / this.options.pageSize);
        const page = this.currentPage + 1;

        return `
            <div class="data-table-pagination">
                <button class="page-btn page-first" ${this.currentPage === 0 ? 'disabled' : ''}>First</button>
                <button class="page-btn page-prev" ${this.currentPage === 0 ? 'disabled' : ''}>Prev</button>
                <span class="page-info">Page ${page} of ${totalPages}</span>
                <button class="page-btn page-next" ${this.currentPage >= totalPages - 1 ? 'disabled' : ''}>Next</button>
                <button class="page-btn page-last" ${this.currentPage >= totalPages - 1 ? 'disabled' : ''}>Last</button>
            </div>
        `;
    }

    /**
     * Render info line
     */
    renderInfo() {
        const start = this.currentPage * this.options.pageSize + 1;
        const end = Math.min(start + this.options.pageSize - 1, this.filteredRows.length);
        const total = this.data.rows.length;
        const filtered = this.filteredRows.length;

        if (filtered < total) {
            return `Showing ${start}-${end} of ${filtered} rows (filtered from ${total})`;
        }
        return `Showing ${start}-${end} of ${total} rows`;
    }

    /**
     * Attach event listeners
     */
    attachEventListeners() {
        // Sort on header click
        if (this.options.sortable) {
            this.container.querySelectorAll('th.sortable').forEach(th => {
                th.addEventListener('click', () => {
                    const col = parseInt(th.dataset.col);
                    this.sortBy(col);
                });
            });
        }

        // Pagination buttons
        this.container.querySelector('.page-first')?.addEventListener('click', () => this.goToPage(0));
        this.container.querySelector('.page-prev')?.addEventListener('click', () => this.goToPage(this.currentPage - 1));
        this.container.querySelector('.page-next')?.addEventListener('click', () => this.goToPage(this.currentPage + 1));
        this.container.querySelector('.page-last')?.addEventListener('click', () => {
            const totalPages = Math.ceil(this.filteredRows.length / this.options.pageSize);
            this.goToPage(totalPages - 1);
        });

        // Filter input - apply on Enter key
        const filterInput = this.container.querySelector('.data-table-search');
        if (filterInput) {
            filterInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    this.filter(e.target.value);
                }
            });
        }

        // Filter button - apply filter
        const filterBtn = this.container.querySelector('.filter-btn');
        if (filterBtn) {
            filterBtn.onclick = () => {
                const input = this.container.querySelector('.data-table-search');
                if (input) this.filter(input.value);
            };
        }

        // Clear filter button
        const clearBtn = this.container.querySelector('.filter-clear-btn');
        if (clearBtn) {
            clearBtn.onclick = () => this.filter('');
        }

        // Regex toggle button
        const regexBtn = this.container.querySelector('.filter-regex-btn');
        if (regexBtn) {
            regexBtn.onclick = () => {
                this.filterRegex = !this.filterRegex;
                regexBtn.classList.toggle('active', this.filterRegex);
                const input = this.container.querySelector('.data-table-search');
                if (input) {
                    input.placeholder = this.filterRegex
                        ? 'Regex pattern... (Enter to apply)'
                        : 'Filter rows... (Enter to apply)';
                    if (this.filterText) this.filter(this.filterText);
                }
            };
        }

        // Column selector
        const columnSelect = this.container.querySelector('.filter-column-select');
        if (columnSelect) {
            columnSelect.onchange = (e) => {
                this.filterColumn = parseInt(e.target.value);
                if (this.filterText) this.filter(this.filterText);
            };
        }

        // Regex help button - show popup with help table
        const helpBtn = this.container.querySelector('.filter-help-btn');
        if (helpBtn) {
            helpBtn.onclick = () => {
                this.showRegexHelp();
            };
        }
    }

    /**
     * Show regex help popup
     */
    showRegexHelp() {
        // Remove existing popup if any
        const existing = document.querySelector('.regex-help-popup');
        if (existing) {
            existing.remove();
            return;  // Toggle off
        }

        const popup = document.createElement('div');
        popup.className = 'regex-help-popup';
        popup.innerHTML = `
            <div class="regex-help-header">
                <span>Regex Quick Reference</span>
                <button type="button" class="regex-help-close">&times;</button>
            </div>
            <table class="regex-help-table">
                <tr><td><code>.</code></td><td>Any character</td><td>A.ice → Alice</td></tr>
                <tr><td><code>*</code></td><td>Zero or more</td><td>A.* → Alice, A</td></tr>
                <tr><td><code>+</code></td><td>One or more</td><td>A.+ → Alice</td></tr>
                <tr><td><code>?</code></td><td>Optional</td><td>colou?r → color, colour</td></tr>
                <tr><td><code>^</code></td><td>Start of string</td><td>^A → starts with A</td></tr>
                <tr><td><code>$</code></td><td>End of string</td><td>e$ → ends with e</td></tr>
                <tr><td><code>[abc]</code></td><td>Character class</td><td>[aeiou] → vowels</td></tr>
                <tr><td><code>[^ab]</code></td><td>Negated class</td><td>[^0-9] → non-digits</td></tr>
                <tr><td><code>\\d</code></td><td>Digit</td><td>\\d+ → numbers</td></tr>
                <tr><td><code>\\w</code></td><td>Word character</td><td>\\w+ → words</td></tr>
                <tr><td><code>|</code></td><td>OR</td><td>NY|CA → NY or CA</td></tr>
                <tr><td><code>()</code></td><td>Group</td><td>(ab)+ → abab</td></tr>
            </table>
            <div class="regex-help-footer">Case-insensitive matching enabled</div>
        `;

        // Position fixed relative to viewport
        const btnRect = this.container.querySelector('.filter-help-btn').getBoundingClientRect();
        popup.style.position = 'fixed';
        popup.style.top = (btnRect.bottom + 4) + 'px';
        popup.style.left = Math.max(10, btnRect.left - 150) + 'px';

        document.body.appendChild(popup);

        // Close button
        popup.querySelector('.regex-help-close').onclick = () => popup.remove();

        // Close on click outside
        setTimeout(() => {
            document.addEventListener('click', function closePopup(e) {
                if (!popup.contains(e.target) && e.target !== this.container?.querySelector('.filter-help-btn')) {
                    popup.remove();
                    document.removeEventListener('click', closePopup);
                }
            });
        }, 100);
    }

    /**
     * Sort table by column
     * @param {number} columnIndex - Column index to sort by
     */
    sortBy(columnIndex) {
        if (this.sortColumn === columnIndex) {
            this.sortAsc = !this.sortAsc;
        } else {
            this.sortColumn = columnIndex;
            this.sortAsc = true;
        }

        this.filteredRows.sort((a, b) => {
            let valA = a[columnIndex] || '';
            let valB = b[columnIndex] || '';

            // Try numeric sort first
            const numA = parseFloat(valA);
            const numB = parseFloat(valB);
            if (!isNaN(numA) && !isNaN(numB)) {
                return this.sortAsc ? numA - numB : numB - numA;
            }

            // String sort
            valA = valA.toString().toLowerCase();
            valB = valB.toString().toLowerCase();
            if (valA < valB) return this.sortAsc ? -1 : 1;
            if (valA > valB) return this.sortAsc ? 1 : -1;
            return 0;
        });

        this.currentPage = 0;
        this.render();
    }

    /**
     * Go to specific page
     * @param {number} page - Page number (0-indexed)
     */
    goToPage(page) {
        const totalPages = Math.ceil(this.filteredRows.length / this.options.pageSize);
        this.currentPage = Math.max(0, Math.min(page, totalPages - 1));
        this.render();
    }

    /**
     * Filter rows by text or regex
     * @param {string} text - Filter text (plain text or regex pattern based on mode)
     */
    filter(text) {
        this.filterText = text;

        if (!text.trim()) {
            this.filteredRows = [...this.data.rows];
        } else {
            // Determine which cells to check
            const getCellsToCheck = (row) => {
                if (this.filterColumn === -1) {
                    return row;  // All columns
                }
                return [row[this.filterColumn] || ''];  // Specific column
            };

            if (this.filterRegex) {
                // Regex filter mode
                try {
                    const regex = new RegExp(text, 'i');
                    this.filteredRows = this.data.rows.filter(row =>
                        getCellsToCheck(row).some(cell => regex.test(cell.toString()))
                    );
                } catch (e) {
                    // Invalid regex - show no results
                    this.filteredRows = [];
                }
            } else {
                // Plain text filter (case-insensitive)
                const searchLower = text.toLowerCase();
                this.filteredRows = this.data.rows.filter(row =>
                    getCellsToCheck(row).some(cell => cell.toString().toLowerCase().includes(searchLower))
                );
            }
        }

        // Re-apply sort if active
        if (this.sortColumn !== null) {
            this.filteredRows.sort((a, b) => {
                let valA = a[this.sortColumn] || '';
                let valB = b[this.sortColumn] || '';
                const numA = parseFloat(valA);
                const numB = parseFloat(valB);
                if (!isNaN(numA) && !isNaN(numB)) {
                    return this.sortAsc ? numA - numB : numB - numA;
                }
                valA = valA.toString().toLowerCase();
                valB = valB.toString().toLowerCase();
                if (valA < valB) return this.sortAsc ? -1 : 1;
                if (valA > valB) return this.sortAsc ? 1 : -1;
                return 0;
            });
        }

        this.currentPage = 0;
        this.updateTableContent();
    }

    /**
     * Update table body and pagination without re-rendering filter input
     * (Prevents focus loss during filtering)
     */
    updateTableContent() {
        // Update tbody
        const tbody = this.container.querySelector('tbody');
        if (tbody) {
            tbody.innerHTML = this.renderRows();
        }

        // Update pagination
        const totalPages = Math.ceil(this.filteredRows.length / this.options.pageSize);
        const paginationContainer = this.container.querySelector('.data-table-pagination');
        if (totalPages > 1) {
            if (paginationContainer) {
                paginationContainer.outerHTML = this.renderPagination();
            } else {
                // Insert pagination before info
                const info = this.container.querySelector('.data-table-info');
                if (info) {
                    info.insertAdjacentHTML('beforebegin', this.renderPagination());
                }
            }
            // Re-attach pagination event listeners
            this.container.querySelector('.page-first')?.addEventListener('click', () => this.goToPage(0));
            this.container.querySelector('.page-prev')?.addEventListener('click', () => this.goToPage(this.currentPage - 1));
            this.container.querySelector('.page-next')?.addEventListener('click', () => this.goToPage(this.currentPage + 1));
            this.container.querySelector('.page-last')?.addEventListener('click', () => {
                const pages = Math.ceil(this.filteredRows.length / this.options.pageSize);
                this.goToPage(pages - 1);
            });
        } else if (paginationContainer) {
            paginationContainer.remove();
        }

        // Update info
        const info = this.container.querySelector('.data-table-info');
        if (info) {
            info.innerHTML = this.renderInfo();
        }

        // Update filter count
        const filterCount = this.container.querySelector('.filter-count');
        if (filterCount) {
            filterCount.textContent = `${this.filteredRows.length} rows`;
        }
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
    module.exports = DataTableViewer;
}

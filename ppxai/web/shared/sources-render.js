/**
 * ADR 0019 step 4: render a turn's or a run's numbered sources under the
 * answer, the same way in the web UI and the VSCode webview.
 *
 * ONE FILE, TWO COPIES: this file and
 * `vscode-extension/media/webview/sources-render.js` are byte-identical
 * (pinned by tests/test_citation_sources_clients.py). Edit one, copy it to
 * the other.
 *
 * Input: the engine's rows `[{n, url, title, backend, query}]`, as found in
 * a chat `stream_end`'s `metadata.sources`, on a stored message's
 * `sources`, or on a run's `sources`. The answer text cites them as `[n]`.
 *
 * DOM-free and dependency-free so it runs under plain Node in the tests:
 * `sourcesHtml()` returns an HTML string with every value escaped, and only
 * http(s) URLs become links. `attachSources()` is the one DOM helper: it
 * puts the list after a message's content element, replacing any earlier
 * list, so a re-render of the content does not wipe it.
 */
(function (root, factory) {
    const api = factory();
    if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
    if (root) { root.PpxaiSources = api; }
}(typeof self !== 'undefined' ? self : (typeof window !== 'undefined' ? window : null), function () {
    'use strict';

    const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

    function esc(value) {
        return String(value).replace(/[&<>"']/g, (c) => ESCAPES[c]);
    }

    function parseUrl(url) {
        try { return new URL(url); } catch (e) { return null; }
    }

    /** Well-formed rows only, ordered by `n`. */
    function normalize(sources) {
        if (!Array.isArray(sources)) { return []; }
        return sources
            .filter((s) => s && typeof s.url === 'string' && s.url && Number.isInteger(s.n) && s.n > 0)
            .slice()
            .sort((a, b) => a.n - b.n);
    }

    function sourcesHtml(sources) {
        const rows = normalize(sources);
        if (!rows.length) { return ''; }
        const items = rows.map((s) => {
            const u = parseUrl(s.url);
            const web = u && (u.protocol === 'http:' || u.protocol === 'https:');
            const host = u && u.hostname ? u.hostname.replace(/^www\./, '') : '';
            const title = typeof s.title === 'string' && s.title.trim() ? s.title.trim() : '';
            const label = title || host || s.url;
            const hint = title && host && title !== host ? ` <span class="source-host">${esc(host)}</span>` : '';
            const body = web
                ? `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer" title="${esc(s.url)}">${esc(label)}</a>${hint}`
                : `<span title="${esc(s.url)}">${esc(label)}</span>`;
            return `<li value="${s.n}" data-source-n="${s.n}">${body}</li>`;
        });
        return '<div class="message-sources"><div class="message-sources-title">Sources</div>'
            + `<ol>${items.join('')}</ol></div>`;
    }

    /**
     * Put the list after `contentEl` (a message's content element), or
     * remove a stale one when there is nothing to show. Returns the element
     * or null.
     */
    function attachSources(contentEl, sources) {
        if (!contentEl || !contentEl.parentNode) { return null; }
        const parent = contentEl.parentNode;
        const old = parent.querySelector(':scope > .message-sources');
        const html = sourcesHtml(sources);
        if (!html) { return null; }
        const holder = contentEl.ownerDocument.createElement('div');
        holder.innerHTML = html;
        const el = holder.firstElementChild;
        if (old) { parent.replaceChild(el, old); } else { contentEl.insertAdjacentElement('afterend', el); }
        return el;
    }

    return { sourcesHtml, attachSources, normalize };
}));

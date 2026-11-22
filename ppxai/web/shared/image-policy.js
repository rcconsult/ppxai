/**
 * Which markdown images the web UI loads, and when it asks first.
 *
 * An image in an answer is fetched as soon as the answer renders, with no
 * click. A model that read a prompt injection (a fetched page, a file, a
 * tool result) can put conversation data into an image URL, and rendering
 * would send it to that host. So:
 *
 * - an image the ppxai server itself serves loads: a relative path, the
 *   page's own origin, `data:image/...` and `blob:`. The one exception is
 *   the server's `/files/remote-image` route, which fetches other hosts;
 * - an HTTPS image from another host is a link until the user allows web
 *   images for the conversation (the bar `app.js` puts on the message
 *   names the hosts and how many URLs carry a query). Once allowed, it
 *   loads through `/files/remote-image`, which fetches public addresses
 *   only (`ppxai/server/routes/remote_image.py`);
 * - any other image (plain http, other schemes) stays a link.
 *
 * The server backs this with `img-src 'self' data: blob:` on the page
 * (`ppxai/server/routes/static.py`), which also covers images this renderer
 * never sees.
 *
 * DOM-free and dependency-free so it runs under plain Node in the tests
 * (tests/test_web_image_policy.py). `app.js::setupMarkdown` installs
 * `imageHtml` as marked's image renderer; marked is global, so the
 * markdown file preview uses it too.
 */
(function (root, factory) {
    const api = factory();
    if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
    if (root) { root.PpxaiImagePolicy = api; }
}(typeof self !== 'undefined' ? self : (typeof window !== 'undefined' ? window : null), function () {
    'use strict';

    const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

    function esc(value) {
        return String(value).replace(/[&<>"']/g, (c) => ESCAPES[c]);
    }

    const SCHEME_RE = /^[a-zA-Z][a-zA-Z0-9+.-]*:/;
    const PROXY_PATH_RE = /(^|[\\/])files[\\/]remote-image[\\/]?$/i;

    /** True when the browser may load `src` without asking. */
    function isLoadable(src, pageOrigin) {
        const s = String(src || '').trim();
        if (!s) { return false; }
        if (/^data:image\//i.test(s) || /^blob:/i.test(s)) { return true; }
        if (!pageOrigin || pageOrigin === 'null') {
            // No origin to compare with: only a plain relative path.
            // `//host/x` is another host, and browsers read `\` as `/`.
            if (SCHEME_RE.test(s) || /^[\\/]{2}/.test(s)) { return false; }
            try {
                return !PROXY_PATH_RE.test(decodeURIComponent(s.split(/[?#]/)[0]));
            } catch (e) {
                return false;
            }
        }
        // Resolve the way the browser will, then compare origins.
        try {
            const url = new URL(s, pageOrigin + '/');
            let path = url.pathname;
            try { path = decodeURIComponent(path); } catch (e) { return false; }
            return url.origin === pageOrigin && !PROXY_PATH_RE.test(path);
        } catch (e) {
            return false;
        }
    }

    /** The URL as an https URL the server may fetch on request, or null. */
    function remoteUrl(src) {
        try {
            const url = new URL(String(src || '').trim());
            if (url.protocol !== 'https:' || !url.host || url.username || url.password) { return null; }
            return url;
        } catch (e) {
            return null;
        }
    }

    function linkHtml(href, alt, note) {
        const label = alt || 'image';
        const url = remoteUrl(href);
        if (url) {
            const why = note || 'Image not loaded';
            return `<a class="external-image" data-src="${esc(url.href)}" data-alt="${esc(label)}"`
                + ` href="${esc(url.href)}" target="_blank" rel="noopener noreferrer"`
                + ` title="${esc(why)}: ${esc(url.href)}">[image: ${label} — ${esc(url.host)}]</a>`;
        }
        let shown = null;
        try { shown = new URL(String(href)); } catch (e) { shown = null; }
        if (shown && shown.protocol === 'http:') {
            return `<a class="external-image" href="${esc(shown.href)}" target="_blank"`
                + ` rel="noopener noreferrer" title="Not loaded (not HTTPS): ${esc(shown.href)}">`
                + `[image: ${label} — ${esc(shown.host)}]</a>`;
        }
        return `<span class="external-image">[image: ${label}]</span>`;
    }

    function proxiedImgHtml(href, alt, title, proxyUrl) {
        const url = remoteUrl(href);
        const titleAttr = title ? ` title="${title}"` : '';
        return `<img class="remote-image" src="${esc(proxyUrl(url.href))}" data-src="${esc(url.href)}"`
            + ` alt="${alt || ''}"${titleAttr} referrerpolicy="no-referrer">`;
    }

    /**
     * marked v11 image renderer body. `title` and `text` arrive escaped by
     * marked; `href` arrives raw. `options.allowRemote` is the user's
     * answer for this conversation; `options.proxyUrl(url)` builds the
     * `/files/remote-image` URL.
     */
    function imageHtml(href, title, text, pageOrigin, options) {
        const opts = options || {};
        const alt = text || '';
        if (isLoadable(href, pageOrigin)) {
            const titleAttr = title ? ` title="${title}"` : '';
            return `<img src="${esc(href)}" alt="${alt}"${titleAttr}>`;
        }
        if (opts.allowRemote && typeof opts.proxyUrl === 'function' && remoteUrl(href)) {
            return proxiedImgHtml(href, alt, title, opts.proxyUrl);
        }
        return linkHtml(href, alt);
    }

    /** What the consent bar says about a set of image URLs. */
    function summarize(urls) {
        const hosts = [];
        let withQuery = 0;
        for (const raw of urls) {
            const url = remoteUrl(raw);
            if (!url) { continue; }
            if (!hosts.includes(url.host)) { hosts.push(url.host); }
            if (url.search && url.search !== '?') { withQuery++; }
        }
        return { count: urls.length, hosts, withQuery };
    }

    /** The bar's text (escaped HTML), from `summarize()`. */
    function consentText(summary) {
        const n = summary.count;
        let text = `${n} web image${n === 1 ? '' : 's'} not loaded, from ${summary.hosts.map(esc).join(', ')}.`;
        if (summary.withQuery) {
            text += ` ${summary.withQuery} of them ${summary.withQuery === 1 ? 'has' : 'have'} a query string,`
                + ' which can carry data from this conversation to that host.';
        } else {
            text += ' Loading an image sends its URL to that host.';
        }
        return text;
    }

    return { isLoadable, remoteUrl, imageHtml, linkHtml, proxiedImgHtml, summarize, consentText };
}));

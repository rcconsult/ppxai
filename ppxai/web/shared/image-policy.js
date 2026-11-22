/**
 * Which markdown images the web UI loads on its own.
 *
 * An image in an answer is fetched as soon as the answer renders, with no
 * click. A model that read a prompt injection (a fetched page, a file, a
 * tool result) can put conversation data into an image URL, and rendering
 * would send it to that host. So only images the ppxai server itself serves
 * are loaded: a relative path, the page's own origin, `data:image/...` and
 * `blob:`. Any other image becomes a link the user can open by hand.
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

    /** True when the browser may load `src` without asking. */
    function isLoadable(src, pageOrigin) {
        const s = String(src || '').trim();
        if (!s) { return false; }
        if (/^data:image\//i.test(s) || /^blob:/i.test(s)) { return true; }
        if (!pageOrigin || pageOrigin === 'null') {
            // No origin to compare with: only a plain relative path.
            // `//host/x` is another host, and browsers read `\` as `/`.
            return !SCHEME_RE.test(s) && !/^[\\/]{2}/.test(s);
        }
        // Resolve the way the browser will, then compare origins.
        try {
            return new URL(s, pageOrigin + '/').origin === pageOrigin;
        } catch (e) {
            return false;
        }
    }

    /**
     * marked v11 image renderer body. `title` and `text` arrive escaped by
     * marked; `href` arrives raw.
     */
    function imageHtml(href, title, text, pageOrigin) {
        const alt = text || '';
        const titleAttr = title ? ` title="${title}"` : '';
        if (isLoadable(href, pageOrigin)) {
            return `<img src="${esc(href)}" alt="${alt}"${titleAttr}>`;
        }
        let url = null;
        try { url = new URL(String(href)); } catch (e) { url = null; }
        const label = alt || 'image';
        if (url && (url.protocol === 'https:' || url.protocol === 'http:')) {
            return `<a class="external-image" href="${esc(url.href)}" target="_blank"`
                + ` rel="noopener noreferrer" title="Image not loaded: ${esc(url.href)}">`
                + `[image: ${label} — ${esc(url.host)}]</a>`;
        }
        return `<span class="external-image">[image: ${label}]</span>`;
    }

    return { isLoadable, imageHtml };
}));

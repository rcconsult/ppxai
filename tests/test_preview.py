"""
Tests for HTML preview functionality.

Tests cover:
- Shared utility: inject_reload_script()
- Shared utility: resolve_preview_path()
- PreviewServer: starts, serves HTML, serves poll, stops
"""

import json
import pytest
from pathlib import Path
from urllib.request import urlopen


class TestInjectReloadScript:
    """Tests for inject_reload_script()."""

    def test_injects_before_body_close(self):
        from ppxai.common.preview import inject_reload_script
        html = '<html><body><p>Hello</p></body></html>'
        result = inject_reload_script(html, '/poll')
        assert '/poll' in result
        assert result.index('<script>') < result.index('</body>')
        assert 'Hello' in result

    def test_appends_when_no_body_close(self):
        from ppxai.common.preview import inject_reload_script
        html = '<p>Hello</p>'
        result = inject_reload_script(html, '/poll')
        assert '/poll' in result
        assert '<script>' in result
        assert 'Hello' in result

    def test_case_insensitive_body(self):
        from ppxai.common.preview import inject_reload_script
        html = '<html><body><p>Hi</p></BODY></html>'
        result = inject_reload_script(html, '/poll')
        assert '<script>' in result

    def test_poll_url_preserved(self):
        from ppxai.common.preview import inject_reload_script
        html = '<body></body>'
        result = inject_reload_script(html, 'http://localhost:12345/poll')
        assert 'http://localhost:12345/poll' in result

    def test_empty_html(self):
        from ppxai.common.preview import inject_reload_script
        result = inject_reload_script('', '/poll')
        assert '<script>' in result
        assert '/poll' in result


class TestRewriteAssetPaths:
    """Tests for rewrite_asset_paths()."""

    def test_rewrites_css_href(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<link href="styles.css" rel="stylesheet">'
        result = rewrite_asset_paths(html, '/preview/static/')
        assert '/preview/static/styles.css' in result

    def test_rewrites_js_src(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<script src="app.js"></script>'
        result = rewrite_asset_paths(html, '/preview/static/')
        assert '/preview/static/app.js' in result

    def test_rewrites_image_src(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<img src="images/logo.png">'
        result = rewrite_asset_paths(html, '/preview/static/')
        assert '/preview/static/images/logo.png' in result

    def test_skips_absolute_urls(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<link href="https://cdn.example.com/style.css">'
        result = rewrite_asset_paths(html, '/preview/static/')
        assert 'https://cdn.example.com/style.css' in result
        assert '/preview/static/' not in result

    def test_skips_data_uris(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<img src="data:image/png;base64,abc">'
        result = rewrite_asset_paths(html, '/preview/static/')
        assert 'data:image/png;base64,abc' in result

    def test_skips_anchors(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<a href="#section">Link</a>'
        result = rewrite_asset_paths(html, '/preview/static/')
        assert 'href="#section"' in result

    def test_preserves_session_query_param(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<link href="styles.css">'
        result = rewrite_asset_paths(html, '/preview/static/?session=abc123')
        assert '/preview/static/styles.css?session=abc123' in result

    def test_handles_subdirectory_base(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<link href="theme.css"><script src="main.js"></script>'
        result = rewrite_asset_paths(html, '/preview/static/subdir/')
        assert '/preview/static/subdir/theme.css' in result
        assert '/preview/static/subdir/main.js' in result

    def test_handles_dot_slash_paths(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<link href="./styles.css">'
        result = rewrite_asset_paths(html, '/preview/static/')
        assert '/preview/static/./styles.css' in result

    def test_single_quotes(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = "<link href='styles.css'>"
        result = rewrite_asset_paths(html, '/preview/static/')
        assert '/preview/static/styles.css' in result

    def test_skips_protocol_relative(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<script src="//cdn.example.com/lib.js"></script>'
        result = rewrite_asset_paths(html, '/preview/static/')
        assert '//cdn.example.com/lib.js' in result

    def test_cache_buster_appended_no_query(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<script src="app.js"></script>'
        result = rewrite_asset_paths(html, '/preview/static/', cache_buster='12345')
        assert '/preview/static/app.js?_t=12345' in result

    def test_cache_buster_appended_with_session(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<link href="styles.css">'
        result = rewrite_asset_paths(html, '/preview/static/?session=abc', cache_buster='99')
        assert '/preview/static/styles.css?session=abc&_t=99' in result

    def test_cache_buster_empty_string_ignored(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<script src="app.js"></script>'
        result = rewrite_asset_paths(html, '/preview/static/', cache_buster='')
        assert '_t=' not in result
        assert '/preview/static/app.js' in result

    def test_cache_buster_skips_absolute_urls(self):
        from ppxai.common.preview import rewrite_asset_paths
        html = '<script src="https://cdn.example.com/lib.js"></script>'
        result = rewrite_asset_paths(html, '/preview/static/', cache_buster='999')
        assert '_t=' not in result


class TestResolvePreviewPath:
    """Tests for resolve_preview_path()."""

    def test_resolves_relative_html(self, tmp_path):
        (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
        from ppxai.common.preview import resolve_preview_path
        result = resolve_preview_path("index.html", str(tmp_path))
        assert result == (tmp_path / "index.html").resolve()

    def test_rejects_non_html(self, tmp_path):
        (tmp_path / "data.json").write_text("{}", encoding="utf-8")
        from ppxai.common.preview import resolve_preview_path
        with pytest.raises(ValueError, match="Not an HTML file"):
            resolve_preview_path("data.json", str(tmp_path))

    def test_rejects_missing_file(self, tmp_path):
        from ppxai.common.preview import resolve_preview_path
        with pytest.raises(FileNotFoundError):
            resolve_preview_path("missing.html", str(tmp_path))

    def test_blocks_path_traversal(self, tmp_path):
        from ppxai.common.preview import resolve_preview_path
        with pytest.raises((FileNotFoundError, ValueError)):
            resolve_preview_path("../../../etc/passwd", str(tmp_path))

    def test_accepts_htm_extension(self, tmp_path):
        (tmp_path / "page.htm").write_text("<html></html>", encoding="utf-8")
        from ppxai.common.preview import resolve_preview_path
        result = resolve_preview_path("page.htm", str(tmp_path))
        assert result.name == "page.htm"

    def test_accepts_absolute_path(self, tmp_path):
        html_file = tmp_path / "abs.html"
        html_file.write_text("<html></html>", encoding="utf-8")
        from ppxai.common.preview import resolve_preview_path
        result = resolve_preview_path(str(html_file), str(tmp_path))
        assert result == html_file.resolve()

    def test_no_extension_restriction(self, tmp_path):
        (tmp_path / "styles.css").write_text("body {}", encoding="utf-8")
        from ppxai.common.preview import resolve_preview_path
        result = resolve_preview_path(
            "styles.css", str(tmp_path), restrict_extension=False
        )
        assert result.name == "styles.css"


class TestPreviewServer:
    """Tests for PreviewServer stdlib server."""

    def test_starts_on_free_port(self, tmp_path):
        (tmp_path / "test.html").write_text("<html><body>Hello</body></html>", encoding="utf-8")
        from ppxai.preview_server import PreviewServer
        server = PreviewServer(str(tmp_path / "test.html"), str(tmp_path))
        try:
            url = server.start(open_browser=False)
            assert server.port > 0
            assert f":{server.port}" in url
            assert server.is_running
        finally:
            server.stop()

    def test_serves_html_with_reload_script(self, tmp_path):
        (tmp_path / "test.html").write_text(
            "<html><body><h1>Hello World</h1></body></html>",
            encoding="utf-8",
        )
        from ppxai.preview_server import PreviewServer
        server = PreviewServer(str(tmp_path / "test.html"), str(tmp_path))
        try:
            url = server.start(open_browser=False)
            response = urlopen(url)
            html = response.read().decode('utf-8')
            assert '<script>' in html
            assert '/poll' in html
            assert 'Hello World' in html
        finally:
            server.stop()

    def test_poll_returns_mtime(self, tmp_path):
        html_file = tmp_path / "test.html"
        html_file.write_text("<html></html>", encoding="utf-8")
        from ppxai.preview_server import PreviewServer
        server = PreviewServer(str(html_file), str(tmp_path))
        try:
            server.start(open_browser=False)
            response = urlopen(f"http://localhost:{server.port}/poll")
            data = json.loads(response.read())
            assert "mtime" in data
            assert isinstance(data["mtime"], float)
            assert data["mtime"] > 0
        finally:
            server.stop()

    def test_stop_shuts_down(self, tmp_path):
        (tmp_path / "test.html").write_text("<html></html>", encoding="utf-8")
        from ppxai.preview_server import PreviewServer
        server = PreviewServer(str(tmp_path / "test.html"), str(tmp_path))
        server.start(open_browser=False)
        assert server.is_running
        server.stop()
        # Give the thread a moment to finish
        import time
        time.sleep(0.2)
        assert not server.is_running

    def test_serves_static_assets(self, tmp_path):
        (tmp_path / "test.html").write_text("<html><body>Hi</body></html>", encoding="utf-8")
        (tmp_path / "style.css").write_text("body { color: red; }", encoding="utf-8")
        from ppxai.preview_server import PreviewServer
        server = PreviewServer(str(tmp_path / "test.html"), str(tmp_path))
        try:
            server.start(open_browser=False)
            response = urlopen(f"http://localhost:{server.port}/style.css")
            css = response.read().decode('utf-8')
            assert 'color: red' in css
            # Static assets must have no-cache to support live-reload of CSS/JS
            assert response.headers.get('Cache-Control') == 'no-cache'
        finally:
            server.stop()

    def test_serves_json_data_files(self, tmp_path):
        (tmp_path / "test.html").write_text("<html><body>Hi</body></html>", encoding="utf-8")
        (tmp_path / "data.json").write_text('[{"id": 1, "name": "test"}]', encoding="utf-8")
        from ppxai.preview_server import PreviewServer
        server = PreviewServer(str(tmp_path / "test.html"), str(tmp_path))
        try:
            server.start(open_browser=False)
            response = urlopen(f"http://localhost:{server.port}/data.json")
            data = json.loads(response.read())
            assert data[0]["name"] == "test"
        finally:
            server.stop()

    def test_relative_filepath(self, tmp_path):
        (tmp_path / "index.html").write_text("<html><body>Rel</body></html>", encoding="utf-8")
        from ppxai.preview_server import PreviewServer
        server = PreviewServer("index.html", str(tmp_path))
        try:
            url = server.start(open_browser=False)
            response = urlopen(url)
            html = response.read().decode('utf-8')
            assert 'Rel' in html
        finally:
            server.stop()

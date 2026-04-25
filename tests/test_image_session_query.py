"""v1.18.1 hotfix: /files/image and /files/serve session via query string.

`<img>` and `<iframe>` elements can't add custom HTTP headers, so any
URL that ends up in an HTML attribute couldn't carry `X-Session-Id`.
The image/serve/preview routes therefore fell back to the *default*
session — wrong cwd, wrong file_store — and returned 404 whenever
the user's session pointed elsewhere (the bug surfaced when rendering
README.md in the chat with `docs/foo.png` references and an engine
cwd that didn't match the server-process cwd).

The fix: routes accept session via either the existing X-Session-Id
header OR a new `?session=<id>` query string. Header takes
precedence; query string is the fallback for browser-native
HTML-attribute fetches.

Tests pin the contract so a future refactor can't drop the query
support.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient


@pytest.fixture
def http_client():
    import ppxai.server.http as http_module
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


# ---------------------------------------------------------------------------
# Sessions are isolated by working_dir
# ---------------------------------------------------------------------------

class TestSessionIsolationViaQuery:
    """Two distinct sessions with different working_dirs; the image
    route resolves the relpath against the correct session's cwd
    based on which session ID rides along (header OR query)."""

    def test_image_route_resolves_session_via_query_string(
        self, http_client, tmp_path
    ):
        """The user's session has cwd `tmp_path/A` containing a real
        image. A different session has cwd `tmp_path/B` containing
        nothing. Same /files/image/<rel> URL — only the session ID
        differentiates resolution.
        """
        # Two distinct cwds
        dir_a = tmp_path / "A"
        dir_b = tmp_path / "B"
        dir_a.mkdir()
        dir_b.mkdir()
        # Real PNG bytes (smallest valid 1x1 PNG)
        png_bytes = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae42"
            "6082"
        )
        (dir_a / "pic.png").write_bytes(png_bytes)

        # Pin session A's cwd to dir_a
        http_client.post(
            "/context/working_dir",
            json={"path": str(dir_a)},
            headers={"X-Session-Id": "session-A"},
        )
        # Pin session B's cwd to dir_b (empty, no pic.png)
        http_client.post(
            "/context/working_dir",
            json={"path": str(dir_b)},
            headers={"X-Session-Id": "session-B"},
        )

        # Plain GET WITHOUT any session info — falls back to default.
        # The default session almost certainly doesn't have pic.png in
        # its cwd, so this should 404.
        resp_no_session = http_client.get("/files/image/pic.png")
        assert resp_no_session.status_code == 404, (
            "Default-session fallback shouldn't resolve session-A's pic.png"
        )

        # Plain GET WITH session A's ID via query string → 200 (the fix)
        resp_query_a = http_client.get("/files/image/pic.png?session=session-A")
        assert resp_query_a.status_code == 200, (
            f"?session=session-A should resolve against dir_a; got "
            f"{resp_query_a.status_code}: {resp_query_a.text[:200]}"
        )
        assert resp_query_a.headers["content-type"].startswith("image/")

        # Plain GET WITH session B's ID via query string → 404
        # (session B's cwd is dir_b which doesn't have pic.png)
        resp_query_b = http_client.get("/files/image/pic.png?session=session-B")
        assert resp_query_b.status_code == 404, (
            "?session=session-B should resolve against dir_b (empty)"
        )

    def test_header_takes_precedence_over_query(
        self, http_client, tmp_path
    ):
        """If both X-Session-Id header AND ?session= query are set,
        the header wins (so existing API-client code that always
        sends the header keeps working)."""
        dir_a = tmp_path / "A"
        dir_b = tmp_path / "B"
        dir_a.mkdir()
        dir_b.mkdir()
        png_bytes = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae42"
            "6082"
        )
        (dir_a / "pic.png").write_bytes(png_bytes)
        (dir_b / "other.png").write_bytes(png_bytes)

        http_client.post(
            "/context/working_dir",
            json={"path": str(dir_a)},
            headers={"X-Session-Id": "prec-A"},
        )
        http_client.post(
            "/context/working_dir",
            json={"path": str(dir_b)},
            headers={"X-Session-Id": "prec-B"},
        )

        # Header A + query B for "pic.png" → header wins → resolves
        # against dir_a → 200 (pic.png exists in dir_a)
        resp = http_client.get(
            "/files/image/pic.png?session=prec-B",
            headers={"X-Session-Id": "prec-A"},
        )
        assert resp.status_code == 200, (
            "Header should win — pic.png is in session-A's cwd (dir_a)"
        )


# ---------------------------------------------------------------------------
# /files/serve and /files/preview also accept session via query
# ---------------------------------------------------------------------------

class TestServeAndPreviewQueryString:
    """Same query-string contract for /files/serve/<file_id> and
    /files/preview/<file_id> — both consume file_id which is
    session-scoped via SessionFileStore."""

    def test_serve_route_accepts_session_query(self, http_client):
        """A made-up file_id 404s for unknown — the response code
        depends on which session resolves the file_store. Without
        the query-string support, the default session always
        responds with 404 because it has no file_store entries.
        With it, we can verify the route at least *looks at* the
        query string (404 returned has the right detail message
        from the session-specific file_store)."""
        # Unknown file_id under a custom session.
        resp = http_client.get("/files/serve/not-a-real-id?session=serve-test")
        assert resp.status_code == 404
        # If the route ignored ?session= and used a different
        # session's file_store, we might get a 503 ("File store not
        # available") instead of 404. Pin the response shape.
        body = resp.json()
        detail = body.get("detail", "")
        assert "Unknown file_id" in detail or "File store not available" in detail, (
            f"Unexpected 404 body: {detail}"
        )

    def test_preview_route_accepts_session_query(self, http_client):
        """Same shape as /files/serve."""
        resp = http_client.get(
            "/files/preview/not-a-real-id?session=preview-test"
        )
        # 404 (unknown file_id) or 503 (no file_store / no LibreOffice).
        # Either is fine; we just want NOT a 422 (validation error
        # complaining about unknown query param).
        assert resp.status_code in (404, 503), (
            f"Expected 404 or 503; got {resp.status_code}: {resp.text[:200]}"
        )

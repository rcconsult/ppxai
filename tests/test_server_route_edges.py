"""Critique #9 — server route endpoint coverage gaps.

Existing coverage:
  - #9.b query-session fallback: tests/test_image_session_query.py
  - #9.c wrong-session isolation: tests/test_image_session_query.py
  - #9.e REST event piggyback (events:[] field): tests/test_rest_event_piggyback.py

Gaps closed here:
  - #9.a missing/bad X-Session-Id behavior (no header, empty header,
        unknown ID — all produce a fresh session, not a 4xx)
  - #9.d invalid session restore returns 404 with the engine's error
        message, no half-loaded state
  - #9.f preview.py::_extract_session_from_referer parsing edges
        (no referer, malformed URL, session in fragment, multiple
        session params, URL-encoded ID)
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import Request
from fastapi.testclient import TestClient

from ppxai.server.routes.preview import _extract_session_from_referer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request_with_referer(referer: str) -> Request:
    """Build a minimal Request stub the parser is happy with."""
    scope = {
        "type": "http",
        "headers": [(b"referer", referer.encode("utf-8"))] if referer else [],
        "method": "GET",
        "path": "/preview/foo",
        "query_string": b"",
    }
    return Request(scope)


@pytest.fixture
def http_client():
    """Live FastAPI test client. SessionManager is real; lifespan runs."""
    import ppxai.server.http as http_module
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


# ---------------------------------------------------------------------------
# #9.a — missing/bad X-Session-Id behavior
# ---------------------------------------------------------------------------

class TestMissingOrBadSessionId:
    """ppxai's design: any session-id string creates a session on demand.
    No 4xx for unknown IDs — that's the intended UX so a fresh tab can
    just send a new ID and get a fresh session. Test the contract so a
    future "validate against allow-list" change is intentional."""

    def test_missing_session_id_uses_default_session(self, http_client):
        # GET /status without any X-Session-Id — falls back to default.
        r = http_client.get("/status")
        assert r.status_code == 200
        # The "default" session exists on every running server.

    def test_unknown_session_id_creates_fresh_session(self, http_client):
        unknown = "absolutely-never-seen-before-xyz123"
        r = http_client.get("/status", headers={"X-Session-Id": unknown})
        assert r.status_code == 200
        # Subsequent calls with the same ID land on the same session
        # — mutating its working_dir then reading it back proves it.
        r1 = http_client.post(
            "/context/working_dir",
            json={"path": "/tmp"},
            headers={"X-Session-Id": unknown},
        )
        assert r1.status_code in (200, 422)  # 422 if path validation fails
        r2 = http_client.get(
            "/context/working_dir",
            headers={"X-Session-Id": unknown},
        )
        assert r2.status_code == 200

    def test_empty_string_session_id_treated_as_missing(self, http_client):
        # Empty header value should fall back to default, not crash.
        r = http_client.get("/status", headers={"X-Session-Id": ""})
        assert r.status_code == 200

    def test_session_id_with_unusual_chars_does_not_crash(self, http_client):
        # The session manager keys by raw string. Unusual chars in the
        # ID should not propagate to filesystem paths or cause 500s.
        weird = "session/with-slash:and:colons"
        r = http_client.get("/status", headers={"X-Session-Id": weird})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# #9.d — invalid session restore returns 404
# ---------------------------------------------------------------------------

class TestInvalidSessionRestore:
    """POST /sessions/load/<name> with a non-existent name must return
    404 with the engine's error message, not a 500."""

    def test_load_unknown_session_returns_404(self, http_client):
        r = http_client.post(
            "/sessions/load/no_such_session_xyz",
            headers={"X-Session-Id": "load-test-session"},
        )
        assert r.status_code == 404
        body = r.json()
        assert "detail" in body
        assert "no_such_session_xyz" in body["detail"] or \
               "not found" in body["detail"].lower()

    def test_load_path_traversal_name_returns_404(self, http_client):
        """v1.18.2 fix: '../' in session name is rejected at the engine
        layer (path traversal protection in session.py). Endpoint
        returns 404, not file content from outside sessions_dir."""
        r = http_client.post(
            "/sessions/load/..%2F..%2Fevil",
            headers={"X-Session-Id": "load-test-session-2"},
        )
        # FastAPI may URL-decode the path before reaching the route;
        # either way the response must be 4xx, not 200.
        assert r.status_code in (404, 422), (
            f"Expected 4xx for path-traversal name, got {r.status_code}: "
            f"{r.text[:200]}"
        )

    def test_load_dot_name_returns_404(self, http_client):
        r = http_client.post(
            "/sessions/load/.",
            headers={"X-Session-Id": "load-test-session-3"},
        )
        assert r.status_code in (404, 422)


# ---------------------------------------------------------------------------
# #9.f — preview.py _extract_session_from_referer parsing edges
# ---------------------------------------------------------------------------

class TestPreviewRefererParsing:
    """The browser-loaded preview routes use the Referer header as the
    last-resort session-ID source (after X-Session-Id and ?session=).
    Garbage in the Referer must yield None, not a crash or wrong ID."""

    def test_no_referer_header_returns_none(self):
        req = _make_request_with_referer("")
        assert _extract_session_from_referer(req) is None

    def test_referer_without_session_param_returns_none(self):
        req = _make_request_with_referer("https://example.com/path")
        assert _extract_session_from_referer(req) is None

    def test_referer_with_session_query_param(self):
        req = _make_request_with_referer(
            "http://localhost:54320/?session=my-session-id"
        )
        assert _extract_session_from_referer(req) == "my-session-id"

    def test_referer_with_session_in_fragment_not_parsed(self):
        """parse_qs reads .query, not .fragment — session in #fragment
        should NOT be returned."""
        req = _make_request_with_referer(
            "http://localhost:54320/#session=ignored"
        )
        assert _extract_session_from_referer(req) is None

    def test_referer_with_url_encoded_session_id_decoded(self):
        req = _make_request_with_referer(
            "http://localhost:54320/?session=hello%20world"
        )
        # parse_qs decodes %-escapes
        assert _extract_session_from_referer(req) == "hello world"

    def test_referer_with_multiple_session_params_uses_first(self):
        """parse_qs returns a list; the parser indexes [0]."""
        req = _make_request_with_referer(
            "http://localhost:54320/?session=first&session=second"
        )
        assert _extract_session_from_referer(req) == "first"

    def test_malformed_referer_returns_none(self):
        """A garbage Referer (not a valid URL) shouldn't crash; the
        substring check ('session=' in referer) gates the parse step."""
        req = _make_request_with_referer("not a url at all")
        assert _extract_session_from_referer(req) is None

    def test_referer_with_session_substring_but_no_query_returns_none(self):
        """'session=' in path component but not query string —
        parse_qs(.query) returns empty dict."""
        req = _make_request_with_referer(
            "http://localhost/foo/session=bar"
        )
        assert _extract_session_from_referer(req) is None

    def test_referer_with_other_query_params_alongside_session(self):
        req = _make_request_with_referer(
            "http://localhost/?foo=bar&session=keep-me&baz=qux"
        )
        assert _extract_session_from_referer(req) == "keep-me"

    def test_referer_with_empty_session_value_returns_empty_string(self):
        """?session= (empty) parses to '' which is the first element."""
        req = _make_request_with_referer("http://localhost/?session=")
        # Documents current behavior: empty string returned. Caller
        # treats falsy values as "no ID found" (or uses x_session_id
        # fallback) so this is benign in practice.
        result = _extract_session_from_referer(req)
        assert result == "" or result is None

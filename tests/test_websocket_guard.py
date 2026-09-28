"""Websocket handshakes get the same Host, Origin and auth rules as HTTP.

Found 2026-09-28 while building ADR 0013's hub: `@app.middleware("http")`
never sees a websocket scope, so the Host check, the bearer gate and CORS
did not apply to `/ws/terminal`. A page on any origin could open it and run a
shell, with or without PPXAI_API_TOKEN. `TestTheAttack` is that exploit;
`_WebSocketGuard` in ppxai/server/http.py closes it.

The deployment cases are pinned too, because the fix must not break them:
the desktop/web UI (same-origin loopback), the k8s coder pods (wide bind,
PPXAI_TRUSTED_HOSTS + PPXAI_ALLOWED_ORIGINS set by the session-manager), and
a gateway that binds wide without either variable (same-origin must work).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocketDisconnect

from ppxai.server import http as http_module

LOOPBACK = ("127.0.0.1", 50123)
POD_PEER = ("10.1.2.3", 50123)    # ingress-nginx, as a coder pod sees it
TOKEN = "guard-test-token"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("PPXAI_TRUSTED_HOSTS", "PPXAI_ALLOWED_ORIGINS", "PPXAI_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(http_module, "_BIND_HOST", "127.0.0.1")
    monkeypatch.setattr(http_module, "_warned_wide_bind", False)


def _client(peer=LOOPBACK):
    return TestClient(http_module.app, client=peer)


def _opens(client, *, host, origin=None, bearer=None, path="/ws/terminal") -> bool:
    """True if the handshake is accepted, False if the guard refused it."""
    headers = {"host": host}
    if origin:
        headers["origin"] = origin
    if bearer:
        headers["authorization"] = f"Bearer {bearer}"
    try:
        with client.websocket_connect(path, headers=headers):
            return True
    except WebSocketDisconnect as exc:
        assert exc.code == 1008, f"refused with {exc.code}, expected the guard's 1008"
        return False


class TestTheAttack:
    """A page on another origin must not get a terminal."""

    def test_a_foreign_origin_is_refused(self):
        with _client() as c:
            assert not _opens(c, host="127.0.0.1:54320", origin="http://evil.example")

    def test_a_foreign_origin_is_refused_with_a_token_configured(self, monkeypatch):
        monkeypatch.setenv("PPXAI_API_TOKEN", TOKEN)
        with _client() as c:
            assert not _opens(c, host="127.0.0.1:54320", origin="http://evil.example")

    def test_dns_rebinding_is_refused_by_the_host_check(self):
        # The rebound page is "same-origin" with itself; its Host is not ours.
        with _client() as c:
            assert not _opens(c, host="evil.example:54320", origin="http://evil.example:54320")

    def test_every_websocket_route_is_guarded(self):
        routes = [r.path for r in http_module.app.routes if isinstance(r, WebSocketRoute)]
        assert routes, "no websocket routes found -- is the app wired?"
        with _client() as c:
            for path in routes:
                assert not _opens(c, host="127.0.0.1:54320",
                                  origin="http://evil.example", path=path), path


class TestDesktop:
    """The local web UI opens the terminal from its own loopback origin."""

    @pytest.mark.parametrize("origin", ["http://127.0.0.1:54320", "http://localhost:54320"])
    def test_the_ui_origin_is_accepted(self, origin):
        with _client() as c:
            assert _opens(c, host="127.0.0.1:54320", origin=origin)

    def test_a_non_browser_client_without_origin_is_accepted(self):
        with _client() as c:
            assert _opens(c, host="127.0.0.1:54320")

    def test_with_a_token_the_loopback_ui_stays_exempt_like_http(self, monkeypatch):
        monkeypatch.setenv("PPXAI_API_TOKEN", TOKEN)
        with _client() as c:
            assert _opens(c, host="127.0.0.1:54320", origin="http://127.0.0.1:54320")


class TestTokenFromElsewhere:
    """With a token configured, a non-loopback peer needs it -- same as HTTP."""

    @pytest.fixture(autouse=True)
    def _wide(self, monkeypatch):
        monkeypatch.setenv("PPXAI_API_TOKEN", TOKEN)
        monkeypatch.setattr(http_module, "_BIND_HOST", "0.0.0.0")
        monkeypatch.setenv("PPXAI_TRUSTED_HOSTS", "gw.example.com")

    def test_no_bearer_is_refused(self):
        with _client(POD_PEER) as c:
            assert not _opens(c, host="gw.example.com", origin="https://gw.example.com")

    def test_a_wrong_bearer_is_refused(self):
        with _client(POD_PEER) as c:
            assert not _opens(c, host="gw.example.com", bearer="nope")

    def test_the_right_bearer_is_accepted(self):
        with _client(POD_PEER) as c:
            assert _opens(c, host="gw.example.com", bearer=TOKEN)


class TestCoderPods:
    """The env the session-manager sets on every coder pod (deploy/images/
    session-manager/main.py): wide bind, trusted ingress host, explicit origin."""

    @pytest.fixture(autouse=True)
    def _coder(self, monkeypatch):
        monkeypatch.setattr(http_module, "_BIND_HOST", "0.0.0.0")
        monkeypatch.setenv("PPXAI_TRUSTED_HOSTS", "coder.example.com")
        monkeypatch.setenv("PPXAI_ALLOWED_ORIGINS", "https://coder.example.com")

    def test_the_coder_ui_opens_its_terminal(self):
        with _client(POD_PEER) as c:
            assert _opens(c, host="coder.example.com", origin="https://coder.example.com")

    def test_a_same_site_sibling_app_is_refused(self):
        # The Lax session cookie IS sent from a sibling *.example.com page;
        # the Origin check is what stops it.
        with _client(POD_PEER) as c:
            assert not _opens(c, host="coder.example.com", origin="https://openwebui.example.com")

    def test_a_foreign_host_is_refused(self):
        with _client(POD_PEER) as c:
            assert not _opens(c, host="evil.example", origin="https://coder.example.com")


class TestPermissiveGateway:
    """Wide bind, no PPXAI_TRUSTED_HOSTS / PPXAI_ALLOWED_ORIGINS: the pre-(u)
    fallback. Its own same-origin UI must keep its terminal."""

    @pytest.fixture(autouse=True)
    def _gateway(self, monkeypatch):
        monkeypatch.setattr(http_module, "_BIND_HOST", "0.0.0.0")

    def test_the_same_origin_ui_is_accepted(self):
        with _client(POD_PEER) as c:
            assert _opens(c, host="gw.example.com", origin="https://gw.example.com")

    def test_another_origin_is_refused(self):
        with _client(POD_PEER) as c:
            assert not _opens(c, host="gw.example.com", origin="https://evil.example")


class TestHttpIsUnchanged:
    def test_the_host_check_still_rejects_http(self):
        with _client() as c:
            r = c.get("/state", headers={"host": "evil.example"})
        assert r.status_code == 400 and r.json()["error"] == "invalid_host"

    def test_health_is_still_exempt_from_the_host_check(self):
        with _client() as c:
            assert c.get("/health", headers={"host": "10.0.0.7:54320"}).status_code == 200

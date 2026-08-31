"""Tests for ppxai-server bearer-token auth middleware (v1.18.3).

The middleware is opt-in: when `PPXAI_API_TOKEN` is unset, every
request passes through. When set, every non-OPTIONS request needs
`Authorization: Bearer <token>` matching the value, or it gets a
401 with `WWW-Authenticate: Bearer ...`.

Tests use `monkeypatch.setenv` per-test so each runs in isolation.
The TestClient is rebuilt per test to ensure middleware sees the
current env state (the middleware reads the env var per-request,
so this isn't strictly required, but it prevents inter-test bleed).
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _env_only_secret_provider(monkeypatch):
    """Pin the secret-provider chain to env-only for these tests.

    These tests assert the documented PPXAI_API_TOKEN env-var behavior
    ("unset => auth off"). The v1.19.0 chain otherwise resolves the
    host's ppxai-config.json, which on a dev box may configure a `file`
    provider — that would (correctly) enforce auth and break the
    env-only assumptions here. Reset to a single EnvSecretProvider so the
    suite is host-independent.
    """
    import ppxai.server.state as state
    from ppxai.server.secrets import EnvSecretProvider, ProviderChain

    monkeypatch.setattr(
        state, "_secret_provider", ProviderChain([EnvSecretProvider()])
    )
    yield
    state._secret_provider = None


@pytest.fixture
def http_client():
    """Fresh TestClient per test."""
    import importlib

    import ppxai.server.http as http_module
    importlib.reload(http_module)  # ensure fresh app state per test
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def http_client_clean_env(monkeypatch):
    """TestClient with PPXAI_API_TOKEN guaranteed unset."""
    monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
    import ppxai.server.http as http_module
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def http_client_with_token(monkeypatch):
    """TestClient with PPXAI_API_TOKEN set to a known value."""
    monkeypatch.setenv("PPXAI_API_TOKEN", "test-secret-token")
    import ppxai.server.http as http_module
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


# We probe the auth gate via /v1/oneshot — it exists, requires only
# a JSON body, and the 422 vs 401 distinction tells us whether auth
# fired (401) or whether validation fired (422). A non-existent path
# would also surface 401 vs 404; both are useful signals.
PROBE_PATH = "/v1/oneshot"
PROBE_BODY = {"prompt": "hi"}


class TestAuthDisabled:
    """When the env var is unset, every request passes through."""

    def test_no_header_passes_when_token_unset(self, http_client_clean_env):
        r = http_client_clean_env.post(PROBE_PATH, json=PROBE_BODY)
        # Either 422 (validation), 400 (no provider), 502 (provider
        # failed), or 200 — anything but 401 proves the gate didn't
        # fire. We just check NOT-401.
        assert r.status_code != 401

    def test_random_header_passes_when_token_unset(self, http_client_clean_env):
        r = http_client_clean_env.post(
            PROBE_PATH,
            json=PROBE_BODY,
            headers={"Authorization": "Bearer junk"},
        )
        assert r.status_code != 401

    def test_empty_token_disables_auth(self, monkeypatch):
        """`PPXAI_API_TOKEN=` (empty string) is treated as auth disabled.

        Prevents lockout from a stray empty-string in a config file.
        """
        monkeypatch.setenv("PPXAI_API_TOKEN", "")
        import ppxai.server.http as http_module
        with TestClient(http_module.app, raise_server_exceptions=False) as c:
            r = c.post(PROBE_PATH, json=PROBE_BODY)
            assert r.status_code != 401

    def test_whitespace_only_token_disables_auth(self, monkeypatch):
        """`PPXAI_API_TOKEN=   ` (whitespace) → auth disabled."""
        monkeypatch.setenv("PPXAI_API_TOKEN", "   ")
        import ppxai.server.http as http_module
        with TestClient(http_module.app, raise_server_exceptions=False) as c:
            r = c.post(PROBE_PATH, json=PROBE_BODY)
            assert r.status_code != 401


class TestAuthEnabled:
    """When the env var is set, every request needs the right header."""

    def test_missing_header_returns_401(self, http_client_with_token):
        r = http_client_with_token.post(PROBE_PATH, json=PROBE_BODY)
        assert r.status_code == 401
        assert "Authorization" in r.json()["detail"]

    def test_malformed_scheme_returns_401(self, http_client_with_token):
        r = http_client_with_token.post(
            PROBE_PATH,
            json=PROBE_BODY,
            headers={"Authorization": "Basic test-secret-token"},
        )
        assert r.status_code == 401

    def test_missing_token_value_returns_401(self, http_client_with_token):
        r = http_client_with_token.post(
            PROBE_PATH,
            json=PROBE_BODY,
            headers={"Authorization": "Bearer"},
        )
        assert r.status_code == 401

    def test_wrong_token_returns_401(self, http_client_with_token):
        r = http_client_with_token.post(
            PROBE_PATH,
            json=PROBE_BODY,
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "Invalid token"

    def test_correct_token_passes_gate(self, http_client_with_token):
        """Right token → not 401. Whatever happens after (validation,
        provider call, etc.) is the route's business, not auth's."""
        r = http_client_with_token.post(
            PROBE_PATH,
            json=PROBE_BODY,
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert r.status_code != 401

    def test_lowercase_bearer_scheme_accepted(self, http_client_with_token):
        """Authorization scheme is case-insensitive per RFC 7235."""
        r = http_client_with_token.post(
            PROBE_PATH,
            json=PROBE_BODY,
            headers={"Authorization": "bearer test-secret-token"},
        )
        assert r.status_code != 401

    def test_uppercase_bearer_scheme_accepted(self, http_client_with_token):
        r = http_client_with_token.post(
            PROBE_PATH,
            json=PROBE_BODY,
            headers={"Authorization": "BEARER test-secret-token"},
        )
        assert r.status_code != 401


class TestErrorResponseShape:
    """The 401 must carry WWW-Authenticate so well-behaved clients
    (httpx, browsers, k8s probes that grok auth) can react correctly."""

    def test_401_carries_www_authenticate_header(self, http_client_with_token):
        r = http_client_with_token.post(PROBE_PATH, json=PROBE_BODY)
        assert r.status_code == 401
        assert r.headers.get("www-authenticate", "").lower().startswith("bearer")

    def test_401_body_is_json(self, http_client_with_token):
        r = http_client_with_token.post(PROBE_PATH, json=PROBE_BODY)
        assert r.status_code == 401
        body = r.json()  # raises on non-JSON
        assert "detail" in body


class TestPreflightExemption:
    """OPTIONS preflight must pass without the Authorization header.

    CORS preflight by spec does NOT carry the Authorization header —
    browsers send the actual request with the header only after the
    preflight succeeds. If we 401 the preflight, the actual request
    never fires."""

    def test_options_passes_without_token(self, http_client_with_token):
        r = http_client_with_token.options(
            PROBE_PATH,
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        # 200 (CORS handler), 204, or 405 — anything but 401.
        assert r.status_code != 401


class TestAuthHelpers:
    """Direct unit tests for ppxai.server.auth helpers."""

    def test_get_required_token_returns_none_when_unset(self, monkeypatch):
        from ppxai.server.auth import get_required_token
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        assert get_required_token() is None

    def test_get_required_token_returns_none_when_empty(self, monkeypatch):
        from ppxai.server.auth import get_required_token
        monkeypatch.setenv("PPXAI_API_TOKEN", "")
        assert get_required_token() is None

    def test_get_required_token_strips_whitespace(self, monkeypatch):
        from ppxai.server.auth import get_required_token
        monkeypatch.setenv("PPXAI_API_TOKEN", "  abc  ")
        assert get_required_token() == "abc"

    def test_is_auth_enabled_false_when_unset(self, monkeypatch):
        from ppxai.server.auth import is_auth_enabled
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        assert is_auth_enabled() is False

    def test_is_auth_enabled_true_when_set(self, monkeypatch):
        from ppxai.server.auth import is_auth_enabled
        monkeypatch.setenv("PPXAI_API_TOKEN", "abc")
        assert is_auth_enabled() is True


class TestLoopbackHardening:
    """v1.19.x: the loopback exemption (bootstrap mint + desktop UI) must not be
    spoofable via X-Forwarded-For behind a local reverse proxy. `_is_loopback`
    requires BOTH a loopback peer IP AND the absence of any forwarding header —
    a genuine local browser connects directly and sends none.
    """

    @staticmethod
    def _req(host, headers=None):
        from types import SimpleNamespace
        return SimpleNamespace(
            client=SimpleNamespace(host=host), headers=headers or {}
        )

    def test_direct_loopback_no_headers_is_loopback(self):
        from ppxai.server.auth import _is_loopback
        assert _is_loopback(self._req("127.0.0.1")) is True
        assert _is_loopback(self._req("::1")) is True

    def test_remote_peer_is_not_loopback(self):
        from ppxai.server.auth import _is_loopback
        assert _is_loopback(self._req("10.0.0.5")) is False

    def test_forwarded_header_disqualifies_even_if_ip_is_loopback(self):
        # the spoof: a proxy (or uvicorn XFF rewrite) presents client.host as
        # 127.0.0.1, but the forwarding header betrays that it was proxied.
        from ppxai.server.auth import _is_loopback
        for hdr in ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded"):
            assert _is_loopback(self._req("127.0.0.1", {hdr: "127.0.0.1"})) is False, hdr

    def test_forwarded_allow_ips_defaults_to_trust_no_proxy(self):
        import os

        from ppxai.server.http import _forwarded_allow_ips
        os.environ.pop("PPXAI_FORWARDED_ALLOW_IPS", None)
        assert _forwarded_allow_ips() == ""   # uvicorn trusts no proxy client-IP

    def test_forwarded_allow_ips_env_override(self, monkeypatch):
        from ppxai.server.http import _forwarded_allow_ips
        monkeypatch.setenv("PPXAI_FORWARDED_ALLOW_IPS", "10.0.0.1")
        assert _forwarded_allow_ips() == "10.0.0.1"

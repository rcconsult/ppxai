"""Debt (u): local-transport security — CORS origin allowlist + Host-header
validation (anti-DNS-rebinding), bind-conditional so the gateway/coder
deployment (0.0.0.0 bind) is not broken.

See ppxai/server/http.py and docs/research/2026-07-05-http-server-attack-surface-
and-transport-options.md §"Point 1".
"""

import pytest
from fastapi.testclient import TestClient

from ppxai.server import http as http_module


def _err(r):
    """Return the JSON `error` field, or None if the body isn't our JSON error."""
    try:
        return (r.json() or {}).get("error")
    except Exception:
        return None


def _is_host_reject(r):
    return r.status_code == 400 and _err(r) == "invalid_host"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # Deterministic default: loopback bind, no operator overrides.
    monkeypatch.delenv("PPXAI_TRUSTED_HOSTS", raising=False)
    monkeypatch.delenv("PPXAI_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setattr(http_module, "_BIND_HOST", "127.0.0.1")
    monkeypatch.setattr(http_module, "_warned_wide_bind", False)
    yield


class TestHostAllowlist:
    """Unit tests for the bind-conditional allowlist policy."""

    def test_loopback_bind_default_is_loopback_plus_testserver(self):
        al = http_module._host_allowlist()
        assert al is not None
        assert {"127.0.0.1", "localhost", "::1"} <= al
        assert "testserver" in al  # TestClient default Host, added under pytest

    def test_trusted_hosts_env_extends(self, monkeypatch):
        monkeypatch.setenv("PPXAI_TRUSTED_HOSTS", "coder.example.com, other.host")
        al = http_module._host_allowlist()
        assert "coder.example.com" in al and "other.host" in al
        assert "127.0.0.1" in al  # loopback still allowed (local clients)

    def test_wildcard_disables_validation(self, monkeypatch):
        monkeypatch.setenv("PPXAI_TRUSTED_HOSTS", "*")
        assert http_module._host_allowlist() is None

    def test_wide_bind_without_extras_is_permissive(self, monkeypatch):
        # Non-breaking fallback: a server-image-only upgrade on a gateway that
        # hasn't set PPXAI_TRUSTED_HOSTS yet must not start 400ing.
        monkeypatch.setattr(http_module, "_BIND_HOST", "0.0.0.0")
        assert http_module._host_allowlist() is None

    def test_wide_bind_with_extras_is_strict(self, monkeypatch):
        monkeypatch.setattr(http_module, "_BIND_HOST", "0.0.0.0")
        monkeypatch.setenv("PPXAI_TRUSTED_HOSTS", "coder.example.com")
        al = http_module._host_allowlist()
        assert al is not None
        assert "coder.example.com" in al and "127.0.0.1" in al


class TestCorsKwargs:
    def test_default_is_loopback_regex_not_wildcard(self):
        kw = http_module._cors_kwargs()
        assert "allow_origin_regex" in kw
        assert "allow_origins" not in kw  # no "*" reflection

    def test_explicit_origins_env(self, monkeypatch):
        monkeypatch.setenv("PPXAI_ALLOWED_ORIGINS", "https://coder.example.com")
        assert http_module._cors_kwargs() == {
            "allow_origins": ["https://coder.example.com"]
        }

    def test_wildcard_origin_is_dropped_to_loopback_default(self, monkeypatch):
        # "*" + allow_credentials=True would make Starlette reflect ANY
        # origin — the wildcard must be ignored, not honored. Spy on the
        # module logger directly (the project Logger noops when debug
        # logging is off, so caplog can't see it).
        warnings: list[str] = []
        monkeypatch.setattr(http_module.logger, "warning", warnings.append)
        monkeypatch.setenv("PPXAI_ALLOWED_ORIGINS", "*")
        kw = http_module._cors_kwargs()
        assert "allow_origin_regex" in kw
        assert "allow_origins" not in kw
        assert any("PPXAI_ALLOWED_ORIGINS" in w for w in warnings)

    def test_wildcard_dropped_but_explicit_origins_kept(self, monkeypatch):
        warnings: list[str] = []
        monkeypatch.setattr(http_module.logger, "warning", warnings.append)
        monkeypatch.setenv(
            "PPXAI_ALLOWED_ORIGINS", "*, https://coder.example.com"
        )
        kw = http_module._cors_kwargs()
        assert kw == {"allow_origins": ["https://coder.example.com"]}
        assert any("PPXAI_ALLOWED_ORIGINS" in w for w in warnings)


class TestHostMiddleware:
    def _client(self):
        return TestClient(http_module.app, raise_server_exceptions=False)

    def test_foreign_host_rejected(self):
        r = self._client().get("/status", headers={"host": "evil.com"})
        assert _is_host_reject(r)

    def test_loopback_host_not_rejected(self):
        r = self._client().get("/status", headers={"host": "127.0.0.1:54320"})
        assert not _is_host_reject(r)

    def test_testserver_default_not_rejected(self):
        r = self._client().get("/status")  # Host: testserver
        assert not _is_host_reject(r)

    def test_ipv6_loopback_literal_not_rejected(self):
        r = self._client().get("/status", headers={"host": "[::1]:54320"})
        assert not _is_host_reject(r)

    def test_health_path_exempt(self):
        # kubelet /health probes send Host=<pod IP>; must not be 400'd.
        r = self._client().get("/health", headers={"host": "evil.com"})
        assert r.status_code != 400

    def test_options_preflight_exempt(self):
        r = self._client().options(
            "/status",
            headers={
                "host": "evil.com",
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert not _is_host_reject(r)

    def test_wide_bind_with_trusted_host_allows_it(self, monkeypatch):
        monkeypatch.setattr(http_module, "_BIND_HOST", "0.0.0.0")
        monkeypatch.setenv("PPXAI_TRUSTED_HOSTS", "coder.example.com")
        r = self._client().get("/status", headers={"host": "coder.example.com"})
        assert not _is_host_reject(r)

    def test_wide_bind_with_trusted_host_rejects_foreign(self, monkeypatch):
        monkeypatch.setattr(http_module, "_BIND_HOST", "0.0.0.0")
        monkeypatch.setenv("PPXAI_TRUSTED_HOSTS", "coder.example.com")
        r = self._client().get("/status", headers={"host": "evil.com"})
        assert _is_host_reject(r)

    def test_wide_bind_permissive_allows_any(self, monkeypatch):
        monkeypatch.setattr(http_module, "_BIND_HOST", "0.0.0.0")
        r = self._client().get("/status", headers={"host": "anything.example"})
        assert not _is_host_reject(r)

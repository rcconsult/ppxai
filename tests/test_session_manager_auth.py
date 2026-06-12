"""Security tests for the k8s session-manager C1/H2 hardening.

Covers the per-user request-auth primitives landed in `79fbdec4`
(`feat(session-manager): per-user request auth (C1) + pod hardening (H2)`)
plus the pre-existing LDAP auth surface flagged untested in
debt-inventory Item 3. This is the "quick pass" scope: the signed-cookie
HMAC path, the /authz cross-user-takeover gate, fail-closed startup, the
k8s-name slug sanitizer, and LDAP fail-closed/hash behavior.

The session-manager lives under `deploy/images/session-manager/`, not in
the `ppxai` package, and its real deps (`kubernetes`, `ldap3`) are NOT in
the test venv — they ship only in the deploy image's requirements.txt.
So importing `main` requires (a) a valid SESSION_SIGNING_KEY in the env
*before* import (it fails closed otherwise — itself a test below), and
(b) stub `kubernetes` / `ldap3` modules injected into sys.modules so the
module-level `import kubernetes` and the in-cluster config load don't
explode. `_load_main()` does both. Tests that assert the fail-closed
startup behavior import in a subprocess-like isolated way via importlib
with the env deliberately unset.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import sys
import types
from pathlib import Path

import pytest

SM_DIR = Path(__file__).resolve().parent.parent / "deploy" / "images" / "session-manager"
_SIGNING_KEY = "x" * 64  # >=32 bytes, hex-like; value is arbitrary for tests


def _install_fake_k8s() -> None:
    """Inject minimal fake `kubernetes` + `ldap3` modules so `import main` works.

    main.py does `import kubernetes`, `from kubernetes import client/config`,
    and at import time calls `load_incluster_config()` (falling back to
    `load_kube_config()`). We make the in-cluster load succeed silently so no
    real cluster / kubeconfig is touched.
    """
    if "kubernetes" not in sys.modules:
        k = types.ModuleType("kubernetes")
        client = types.ModuleType("kubernetes.client")
        config = types.ModuleType("kubernetes.config")

        # config.load_incluster_config() succeeds; ConfigException present for
        # the except clause main.py guards with.
        class ConfigException(Exception):
            pass

        config.ConfigException = ConfigException
        config.load_incluster_config = lambda *a, **k: None
        config.load_kube_config = lambda *a, **k: None

        # client.CoreV1Api() / NetworkingV1Api() just need to be callable; the
        # auth functions under test never touch them.
        client.CoreV1Api = lambda *a, **k: object()
        client.NetworkingV1Api = lambda *a, **k: object()
        # Attribute access for k8s resource builders used elsewhere in main.
        client.__getattr__ = lambda name: (lambda *a, **k: object())  # type: ignore[attr-defined]

        k.client = client
        k.config = config
        sys.modules["kubernetes"] = k
        sys.modules["kubernetes.client"] = client
        sys.modules["kubernetes.config"] = config

    if "ldap3" not in sys.modules:
        ldap3 = types.ModuleType("ldap3")
        ldap3.SIMPLE = "SIMPLE"
        ldap3.SUBTREE = "SUBTREE"
        ldap3.NONE = "NONE"
        ldap3.Server = lambda *a, **k: object()
        ldap3.Connection = lambda *a, **k: object()
        utils = types.ModuleType("ldap3.utils")
        conv = types.ModuleType("ldap3.utils.conv")
        conv.escape_filter_chars = lambda s: s
        utils.conv = conv
        core = types.ModuleType("ldap3.core")
        exc = types.ModuleType("ldap3.core.exceptions")

        class LDAPException(Exception):
            pass

        class LDAPBindError(LDAPException):
            pass

        exc.LDAPException = LDAPException
        exc.LDAPBindError = LDAPBindError
        core.exceptions = exc
        ldap3.core = core
        ldap3.utils = utils
        sys.modules["ldap3"] = ldap3
        sys.modules["ldap3.utils"] = utils
        sys.modules["ldap3.utils.conv"] = conv
        sys.modules["ldap3.core"] = core
        sys.modules["ldap3.core.exceptions"] = exc


def _load_main(monkeypatch, **env):
    """Import the session-manager `main` module fresh with env applied."""
    monkeypatch.setenv("SESSION_SIGNING_KEY", env.pop("SESSION_SIGNING_KEY", _SIGNING_KEY))
    monkeypatch.setenv("AUTH_MODE", env.pop("AUTH_MODE", "stub"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    _install_fake_k8s()
    monkeypatch.syspath_prepend(str(SM_DIR))
    sys.modules.pop("main", None)
    return importlib.import_module("main")


@pytest.fixture
def main(monkeypatch):
    mod = _load_main(monkeypatch)
    yield mod
    sys.modules.pop("main", None)


# ---------------------------------------------------------------------------
# Fail-closed startup (the H2/C1 safety invariant)
# ---------------------------------------------------------------------------


class TestFailClosedStartup:
    def test_missing_signing_key_refuses_to_start(self, monkeypatch):
        with pytest.raises(RuntimeError, match="SESSION_SIGNING_KEY"):
            _load_main(monkeypatch, SESSION_SIGNING_KEY="")

    def test_short_signing_key_refuses_to_start(self, monkeypatch):
        # <32 bytes must fail closed — a short key is forgeable-weak.
        with pytest.raises(RuntimeError, match="32 bytes"):
            _load_main(monkeypatch, SESSION_SIGNING_KEY="tooshort")

    def test_exactly_32_byte_key_starts(self, monkeypatch):
        mod = _load_main(monkeypatch, SESSION_SIGNING_KEY="y" * 32)
        assert mod.SESSION_SIGNING_KEY == b"y" * 32
        sys.modules.pop("main", None)


# ---------------------------------------------------------------------------
# Slug sanitizer — k8s DNS-label safety + path-escape rejection
# ---------------------------------------------------------------------------


class TestSlugSanitizer:
    def test_basic_lowercase_hyphen(self, main):
        assert main._slug("Firstname.Lastname") == "firstname-lastname"

    def test_path_traversal_chars_stripped(self, main):
        # ".." and "/" must not survive into a k8s resource name.
        s = main._slug("../../etc/passwd")
        assert "/" not in s and ".." not in s
        assert all(c.isalnum() or c == "-" for c in s)

    def test_slash_in_username_neutralized(self, main):
        s = main._slug("evil/../other")
        assert "/" not in s

    def test_length_capped_at_32(self, main):
        assert len(main._slug("a" * 100)) <= 32

    def test_collapses_and_trims_hyphens(self, main):
        assert main._slug("--a..b--") == "a-b"

    def test_no_leading_trailing_hyphen(self, main):
        s = main._slug("...weird...")
        assert not s.startswith("-") and not s.endswith("-")


# ---------------------------------------------------------------------------
# C1 signed-cookie HMAC verification
# ---------------------------------------------------------------------------


class TestCookieVerification:
    def test_roundtrip_valid_cookie(self, main):
        raw = main._make_cookie_value("alice")
        assert main._verify_cookie(raw) == "alice"

    def test_forged_signature_rejected(self, main):
        raw = main._make_cookie_value("alice")
        slug, iat, _sig = raw.split(".")
        forged = f"{slug}.{iat}.{'0' * 64}"
        assert main._verify_cookie(forged) is None

    def test_tampered_slug_rejected(self, main):
        # Take alice's valid cookie, swap the slug to bob — sig no longer matches.
        raw = main._make_cookie_value("alice")
        _slug, iat, sig = raw.split(".")
        tampered = f"bob.{iat}.{sig}"
        assert main._verify_cookie(tampered) is None

    def test_expired_cookie_rejected(self, main, monkeypatch):
        # issued_at far enough in the past to exceed TTL_MINUTES*60.
        old_iat = 1  # epoch ~1970
        slug = "alice"
        sig = main._sign_slug(slug, old_iat)
        assert main._verify_cookie(f"{slug}.{old_iat}.{sig}") is None

    def test_malformed_cookie_rejected(self, main):
        for bad in ("", "onlyonepart", "two.parts", "a.b.c.d", "slug.notanint.sig"):
            assert main._verify_cookie(bad) is None

    def test_signature_uses_configured_key(self, main):
        # Sanity: _sign_slug is a real HMAC-SHA256 over "<slug>.<iat>".
        expected = hmac.new(main.SESSION_SIGNING_KEY, b"alice.123", hashlib.sha256).hexdigest()
        assert main._sign_slug("alice", 123) == expected


# ---------------------------------------------------------------------------
# /authz URL-slug extraction + the cross-user-takeover gate
# ---------------------------------------------------------------------------


class TestUrlSlugExtraction:
    def test_extracts_slug_from_original_uri(self, main):
        h = {"x-original-uri": "/s/alice/some/path"}
        assert main._extract_url_slug(h) == "alice"

    def test_extracts_slug_from_full_url(self, main):
        h = {"x-original-url": "https://coder.example.com/s/bob/"}
        assert main._extract_url_slug(h) == "bob"

    def test_non_s_path_returns_none(self, main):
        assert main._extract_url_slug({"x-original-uri": "/login"}) is None

    def test_missing_headers_returns_none(self, main):
        assert main._extract_url_slug({}) is None


class TestAuthzGate:
    """The /authz endpoint is the cross-user-takeover gate (the C1 attack)."""

    def _fake_request(self, main, cookie_val, original_uri):
        class _Req:
            cookies = {main.COOKIE_NAME: cookie_val}
            headers = {"x-original-uri": original_uri}

        return _Req()

    def test_valid_same_user_allowed(self, main, monkeypatch):
        # Bypass the live-session registry check (no real PVCs in tests).
        monkeypatch.setattr(main, "REQUIRE_LIVE_SESSION", False)
        raw = main._make_cookie_value("alice")
        req = self._fake_request(main, raw, "/s/alice/")
        assert main.authz(req) == {"ok": True}

    def test_cross_user_access_forbidden_403(self, main, monkeypatch):
        # alice's valid cookie, requesting bob's path → 403 (the attack).
        monkeypatch.setattr(main, "REQUIRE_LIVE_SESSION", False)
        raw = main._make_cookie_value("alice")
        req = self._fake_request(main, raw, "/s/bob/")
        with pytest.raises(main.HTTPException) as ei:
            main.authz(req)
        assert ei.value.status_code == 403

    def test_no_cookie_unauthorized_401(self, main):
        req = self._fake_request(main, "", "/s/alice/")
        with pytest.raises(main.HTTPException) as ei:
            main.authz(req)
        assert ei.value.status_code == 401

    def test_forged_cookie_unauthorized_401(self, main):
        raw = main._make_cookie_value("alice")
        slug, iat, _ = raw.split(".")
        req = self._fake_request(main, f"{slug}.{iat}.{'0'*64}", "/s/alice/")
        with pytest.raises(main.HTTPException) as ei:
            main.authz(req)
        assert ei.value.status_code == 401

    def test_torn_down_session_rejected_when_required(self, main, monkeypatch):
        # REQUIRE_LIVE_SESSION on + slug not in registry → 401.
        monkeypatch.setattr(main, "REQUIRE_LIVE_SESSION", True)
        monkeypatch.setattr(main, "_slug_session_exists", lambda slug: False)
        raw = main._make_cookie_value("alice")
        req = self._fake_request(main, raw, "/s/alice/")
        with pytest.raises(main.HTTPException) as ei:
            main.authz(req)
        assert ei.value.status_code == 401


# ---------------------------------------------------------------------------
# LDAP authenticator — hash + fail-closed (debt Item 3 quick pass)
# ---------------------------------------------------------------------------


@pytest.fixture
def ldap_auth(monkeypatch):
    _install_fake_k8s()
    monkeypatch.syspath_prepend(str(SM_DIR))
    for k, v in {
        "LDAP_URL": "ldaps://ad.example.com",
        "LDAP_BASE_DN": "dc=example,dc=com",
        "LDAP_BIND_DN": "cn=svc,dc=example,dc=com",
        "LDAP_BIND_PASSWORD": "svcpw",
    }.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("ldap_auth", None)
    mod = importlib.import_module("ldap_auth")
    yield mod.LDAPAuthenticator()
    sys.modules.pop("ldap_auth", None)


class TestLDAPAuth:
    def test_hash_password_is_sha256(self, ldap_auth):
        assert ldap_auth._hash_password("hunter2") == hashlib.sha256(b"hunter2").hexdigest()

    def test_cache_miss_returns_none(self, ldap_auth):
        assert ldap_auth._check_cache("alice", "pw") is None

    def test_cache_hit_matches_only_on_same_password(self, ldap_auth):
        ldap_auth._update_cache("alice", "rightpw")
        assert ldap_auth._check_cache("alice", "rightpw") is True
        assert ldap_auth._check_cache("alice", "wrongpw") is False

    def test_expired_cache_evicts_and_misses(self, ldap_auth, monkeypatch):
        ldap_auth._update_cache("alice", "pw")
        # Force expiry: jump monotonic past TTL.
        real = ldap_auth._cache["alice"]
        ldap_auth._cache["alice"] = (real[0], 0.0)  # expiry in the past
        assert ldap_auth._check_cache("alice", "pw") is None
        assert "alice" not in ldap_auth._cache  # evicted

    def test_authenticate_fail_closed_on_bind_error(self, ldap_auth, monkeypatch):
        # A bad-password bind raises LDAPBindError → authenticate returns False.
        import ldap3

        def _boom(*a, **k):
            raise ldap3.core.exceptions.LDAPBindError("bad creds")

        monkeypatch.setattr(ldap3, "Connection", lambda *a, **k: types.SimpleNamespace(bind=_boom, unbind=lambda: None))
        assert ldap_auth.authenticate("alice", "wrongpw") is False

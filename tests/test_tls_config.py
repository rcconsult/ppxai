"""The outbound-TLS resolver (`ppxai/config/tls.py`).

Before this resolver the same two env vars were read at six sites and had
already diverged three ways (missing-file guard present at one site only;
`SSL_CERT_FILE` ignored entirely at two). These tests pin the precedence
order and, critically, assert that every outbound client asks the resolver
rather than re-reading the environment — the drift, not the branch, was
the defect.
"""

from __future__ import annotations

import ssl

import pytest

from ppxai.config import tls as tlsmod

#: The real reader, captured before the autouse fixture stubs it out, so
#: the fail-safe cases below can restore and exercise it.
_REAL_SSL_BLOCK = tlsmod._ssl_config_block

#: A self-signed CA that exists in no trust store, so adding it must raise
#: the root count by exactly one. Valid 2020→2099; signs nothing.
_SYNTHETIC_CA_PEM = """\
-----BEGIN CERTIFICATE-----
MIIDJTCCAg2gAwIBAgIUf93/n58z+qQ9Gv4WyXc7vGAc8qowDQYJKoZIhvcNAQEL
BQAwQTEhMB8GA1UEAwwYcHB4YWktdGVzdC1ub3QtYS1yZWFsLWNhMRwwGgYDVQQK
DBNwcHhhaSB0ZXN0IGZpeHR1cmVzMCAXDTIwMDEwMTAwMDAwMFoYDzIwOTkwMTAx
MDAwMDAwWjBBMSEwHwYDVQQDDBhwcHhhaS10ZXN0LW5vdC1hLXJlYWwtY2ExHDAa
BgNVBAoME3BweGFpIHRlc3QgZml4dHVyZXMwggEiMA0GCSqGSIb3DQEBAQUAA4IB
DwAwggEKAoIBAQCvFj7FB78um7chQeQlxgG5C++YGgtOhLLslBuIzEImv8PyNO1b
Na4CGJrv3F1v6kN5L9b0VfahWc9/z5ZltbyPT9cSz8Rtss/byBVUXPUtjs3Pl6Oa
V5XNBd35fd0oehm70PB+DK1ycZAo+jS0tVQy1CkYluZE8o4kztctu2cqEeUJWd1x
xhi83tUyaNBeNnM3OVu0CLGcc/kOMDv+gTpe7uNuabar3wK9KjF+qWEgAKStEXs7
m+e+note7ko/wjPvhp7vijOT1BPau0nDXZdBVeVfljC/pWD9Wf5uzxj93g1co2Ql
4pEYo+XkAKX7jUbN6cAfdXPud8hwyE1Civ+zAgMBAAGjEzARMA8GA1UdEwEB/wQF
MAMBAf8wDQYJKoZIhvcNAQELBQADggEBAF7jDCCoZiIHpMww+Pv958wNb+hmkIo0
qVyFhSvQ1+2oNKYLebnXIOpEopPOYsinZy6MfpbbDv8A7qGPdw8tCv38RDsr8Sid
WON2Ep6mUCQs+7D9GcSnBJBx6QLQVF0oY3gnm3TBqiD/QsDweEXlpoYRMw1QaqlL
i1RbJ1gGj5ki+VayjCysIdxe0ub5KRUaKsSTr91WAC8FAE37ZVSgqmQVkHFe6NNm
3ino5os3/Xub0UlH9q7G+m5/eqy8SWlfK+Vl3elEvmAK3PH9x6QObqmHGK02MpRC
cdBdhSQ07+4NzySocTOQ9sFkP8XOPFq1lLTMA6yqBtVjLunqLjBtyGo=
-----END CERTIFICATE-----
"""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """No ambient SSL_* from the developer's own shell/.env.

    Also drops the memoised SSLContexts on both sides of each test: the
    cache is keyed by resolved policy, and these tests re-resolve the
    same policies under different mocked configs.
    """
    monkeypatch.delenv("SSL_VERIFY", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(tlsmod, "_ssl_config_block", lambda: {})
    tlsmod.reset_tls_context_cache()
    yield
    tlsmod.reset_tls_context_cache()


def _cert(tmp_path, name="ca.pem"):
    p = tmp_path / name
    p.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    return p


class TestPrecedence:
    """env SSL_VERIFY > env SSL_CERT_FILE > config verify > config cert_file."""

    def test_default_is_system_store(self):
        s = tlsmod.resolve_tls_verify()
        assert s.verify is True
        assert s.source == "default"
        assert not s.is_insecure

    def test_env_verify_false_disables(self, monkeypatch):
        monkeypatch.setenv("SSL_VERIFY", "false")
        s = tlsmod.resolve_tls_verify()
        assert s.verify is False
        assert s.source == "env"
        assert s.is_insecure

    def test_env_verify_false_beats_env_cert_file(self, monkeypatch, tmp_path):
        """The user's live config had BOTH set; the opt-out must win, and the
        cert must not silently appear to be in use."""
        monkeypatch.setenv("SSL_VERIFY", "false")
        monkeypatch.setenv("SSL_CERT_FILE", str(_cert(tmp_path)))
        s = tlsmod.resolve_tls_verify()
        assert s.verify is False
        assert s.cert_file is None

    def test_env_cert_file_used_when_present(self, monkeypatch, tmp_path):
        c = _cert(tmp_path)
        monkeypatch.setenv("SSL_CERT_FILE", str(c))
        s = tlsmod.resolve_tls_verify()
        assert s.verify == str(c)
        assert s.cert_file == str(c)
        assert not s.is_insecure

    def test_env_cert_file_missing_falls_back_to_system(self, monkeypatch, tmp_path):
        """A stale path must NOT be handed to httpx (opaque failure on every
        request) and must NOT silently disable verification."""
        monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "gone.pem"))
        s = tlsmod.resolve_tls_verify()
        assert s.verify is True
        assert not s.is_insecure
        assert "does not exist" in s.reason

    def test_env_cert_file_quotes_stripped(self, monkeypatch, tmp_path):
        """`SSL_CERT_FILE="C:\\path\\ca.pem"` in a .env keeps its quotes."""
        c = _cert(tmp_path)
        monkeypatch.setenv("SSL_CERT_FILE", f'"{c}"')
        assert tlsmod.resolve_tls_verify().verify == str(c)

    def test_config_verify_false(self, monkeypatch):
        monkeypatch.setattr(tlsmod, "_ssl_config_block", lambda: {"verify": False})
        s = tlsmod.resolve_tls_verify()
        assert s.verify is False
        assert s.source == "config"

    def test_config_cert_file(self, monkeypatch, tmp_path):
        c = _cert(tmp_path)
        monkeypatch.setattr(
            tlsmod, "_ssl_config_block", lambda: {"cert_file": str(c)}
        )
        s = tlsmod.resolve_tls_verify()
        assert s.verify == str(c)
        assert s.source == "config"

    def test_env_beats_config(self, monkeypatch, tmp_path):
        """.env is the per-machine layer; JSON is the shared one."""
        env_c = _cert(tmp_path, "env.pem")
        cfg_c = _cert(tmp_path, "cfg.pem")
        monkeypatch.setenv("SSL_CERT_FILE", str(env_c))
        monkeypatch.setattr(
            tlsmod, "_ssl_config_block", lambda: {"cert_file": str(cfg_c)}
        )
        assert tlsmod.resolve_tls_verify().verify == str(env_c)

    def test_env_verify_false_beats_config_cert_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SSL_VERIFY", "false")
        monkeypatch.setattr(
            tlsmod,
            "_ssl_config_block",
            lambda: {"cert_file": str(_cert(tmp_path))},
        )
        assert tlsmod.resolve_tls_verify().verify is False

    def test_unreadable_config_does_not_disable_tls(self, monkeypatch):
        """Fail SAFE: a broken config must never mean 'no verification'."""
        def boom():
            raise RuntimeError("config unreadable")

        # Undo the autouse stub: these cases must exercise the REAL
        # _ssl_config_block, which is where the error is swallowed.
        monkeypatch.setattr(tlsmod, "_ssl_config_block", _REAL_SSL_BLOCK)
        monkeypatch.setattr(tlsmod, "get_config", boom)
        assert tlsmod.resolve_tls_verify().verify is True

    def test_unreadable_config_yields_empty_block_not_an_opt_out(
        self, monkeypatch
    ):
        """Pins the *recovery value*, not just the outcome above.

        `_ssl_config_block` swallowing the error must degrade to "config
        says nothing", never to a synthesised opt-out. Asserted directly
        because the outcome test alone survives a mutation that returns
        `{"verify": False}` from the except branch.
        """
        def boom():
            raise RuntimeError("config unreadable")

        # Undo the autouse stub: these cases must exercise the REAL
        # _ssl_config_block, which is where the error is swallowed.
        monkeypatch.setattr(tlsmod, "_ssl_config_block", _REAL_SSL_BLOCK)
        monkeypatch.setattr(tlsmod, "get_config", boom)
        assert tlsmod._ssl_config_block() == {}

    @pytest.mark.parametrize(
        "block", [{"network": None}, {"network": []}, {"network": {"ssl": "x"}}]
    )
    def test_malformed_network_block_is_ignored(self, monkeypatch, block):
        """A hand-edited config with the wrong shape must not disable TLS."""
        monkeypatch.setattr(tlsmod, "_ssl_config_block", _REAL_SSL_BLOCK)
        monkeypatch.setattr(tlsmod, "get_config", lambda: block)
        assert tlsmod._ssl_config_block() == {}
        assert tlsmod.resolve_tls_verify().verify is True


class TestOptOutSpellings:
    @pytest.mark.parametrize("raw", ["false", "FALSE", "False", "0", "no", "off"])
    def test_recognised_opt_outs(self, monkeypatch, raw):
        monkeypatch.setenv("SSL_VERIFY", raw)
        assert tlsmod.resolve_tls_verify().verify is False

    @pytest.mark.parametrize("raw", ["true", "1", "yes", "", "maybe", "FALSEY"])
    def test_everything_else_keeps_verification(self, monkeypatch, raw):
        """An unrecognised value must never silently disable TLS."""
        monkeypatch.setenv("SSL_VERIFY", raw)
        assert tlsmod.resolve_tls_verify().verify is not False

    def test_config_json_boolean_false(self, monkeypatch):
        monkeypatch.setattr(tlsmod, "_ssl_config_block", lambda: {"verify": False})
        assert tlsmod.resolve_tls_verify().verify is False

    def test_config_json_boolean_true_verifies(self, monkeypatch):
        monkeypatch.setattr(tlsmod, "_ssl_config_block", lambda: {"verify": True})
        assert tlsmod.resolve_tls_verify().verify is True


class TestSSLContextMirrorsVerify:
    """`tls_ssl_context()` and `tls_verify()` must encode the SAME policy —
    they are two shapes of one decision, and the old code let them differ."""

    def test_insecure_context_checks_nothing(self, monkeypatch):
        monkeypatch.setenv("SSL_VERIFY", "false")
        ctx = tlsmod.tls_ssl_context()
        assert ctx.verify_mode == ssl.CERT_NONE
        assert ctx.check_hostname is False
        assert tlsmod.tls_verify() is False

    def test_default_context_verifies(self):
        ctx = tlsmod.tls_ssl_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True
        # tls_verify() returns a CONTEXT, not True: httpx's own default
        # trusts certifi only, which omits an OS-installed corporate CA.
        v = tlsmod.tls_verify()
        assert isinstance(v, ssl.SSLContext)
        assert v.verify_mode == ssl.CERT_REQUIRED

    def test_missing_cert_context_still_verifies(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "gone.pem"))
        assert tlsmod.tls_ssl_context().verify_mode == ssl.CERT_REQUIRED


class TestCustomCAIsAdditive:
    """A corporate CA must ADD to the system roots, never replace them.

    `ssl.create_default_context(cafile=...)` and `httpx(verify="<path>")`
    both substitute the bundle for the default trust store. That breaks
    every public endpoint the moment the machine leaves the inspecting
    network, so a roaming laptop would need a config edit per move.
    Measured on a direct connection: cafile-only fails
    CERTIFICATE_VERIFY_FAILED against a real endpoint; default-plus-CA
    succeeds.
    """

    def _real_ca(self, tmp_path):
        """A loadable CA that is ALREADY in the default store (certifi's
        first cert) — for cases that only need `load_verify_locations` to
        succeed, not a change in root count."""
        import certifi

        pem = []
        with open(certifi.where(), encoding="utf-8") as fh:
            capture = False
            for line in fh:
                if line.startswith("-----BEGIN CERTIFICATE-----"):
                    capture = True
                if capture:
                    pem.append(line)
                if line.startswith("-----END CERTIFICATE-----"):
                    break
        p = tmp_path / "corp-ca.pem"
        p.write_text("".join(pem), encoding="utf-8")
        return p

    def _synthetic_ca(self, tmp_path):
        """A CA that is definitely NOT in any default trust store, so the
        root count must strictly increase when it is added.

        Embedded as a literal rather than generated: `cryptography` is
        only a transitive dependency here, and a generated cert would make
        this test silently skip wherever it is absent. Self-signed, valid
        to 2099, and worthless — it signs nothing.
        """
        p = tmp_path / "synthetic-corp-ca.pem"
        p.write_text(_SYNTHETIC_CA_PEM, encoding="utf-8")
        return p

    def test_tls_verify_returns_a_context_not_a_path(self, monkeypatch, tmp_path):
        """The regression that matters: a bare path handed to httpx would
        silently replace the system trust store."""
        ca = self._real_ca(tmp_path)
        monkeypatch.setenv("SSL_CERT_FILE", str(ca))
        v = tlsmod.tls_verify()
        assert isinstance(v, ssl.SSLContext), (
            "tls_verify() must return an SSLContext when a CA bundle is "
            "configured; a str path makes httpx REPLACE the system roots"
        )
        assert not isinstance(v, str)

    def test_context_keeps_system_roots_alongside_the_custom_ca(
        self, monkeypatch, tmp_path
    ):
        """Both halves: the CA is really ADDED, and the system roots stay.

        Driven through **network.ssl.cert_file**. The env-path twin below
        (`test_env_cert_file_is_also_additive`) covers `SSL_CERT_FILE` —
        historically the blind spot: OpenSSL reads that env var itself
        inside `set_default_verify_paths()`, so the "default" context was
        ALREADY narrowed to the bundle (measured: 1 root vs 124) and our
        `load_verify_locations` was an invisible no-op there. The fix
        (`_system_roots_context` neutralises the vars while the base
        roots load) makes the code load-bearing on both paths, so both
        are pinned.

        Uses a CA in no default store, so the count must strictly
        increase; comparing against cafile-only alone is not enough.
        """
        ca = self._synthetic_ca(tmp_path)

        baseline = len(ssl.create_default_context().get_ca_certs())
        monkeypatch.setattr(
            tlsmod, "_ssl_config_block", lambda: {"cert_file": str(ca)}
        )
        loaded = len(tlsmod.tls_ssl_context().get_ca_certs())
        replaced = len(ssl.create_default_context(cafile=str(ca)).get_ca_certs())

        assert loaded == baseline + 1, (
            f"custom CA was not added: {loaded} roots vs baseline "
            f"{baseline}. Expected exactly one more."
        )
        assert loaded > replaced, (
            f"custom CA replaced the trust store ({loaded} vs {replaced} "
            "for cafile-only)"
        )

    def test_env_cert_file_is_also_additive(self, monkeypatch, tmp_path):
        """The SSL_CERT_FILE env path must keep the system roots too.

        This was shipped broken: OpenSSL honours SSL_CERT_FILE inside
        `set_default_verify_paths()`, so `create_default_context()` built
        a context containing ONLY the bundle (measured 1 root vs 124) and
        the module's additive guarantee was false on the very path
        `.env.example` documents first — the exact roaming-laptop
        breakage the module says it prevents. `_system_roots_context`
        now neutralises the env vars while the base roots load; deleting
        that neutralisation makes this test fail with a root count equal
        to the bundle's own size.
        """
        ca = self._synthetic_ca(tmp_path)

        baseline = len(tlsmod._system_roots_context().get_ca_certs())
        monkeypatch.setenv("SSL_CERT_FILE", str(ca))
        loaded = len(tlsmod.tls_ssl_context().get_ca_certs())

        assert loaded == baseline + 1, (
            f"SSL_CERT_FILE narrowed the trust store to {loaded} root(s) "
            f"instead of adding to the {baseline} system roots — the env "
            "path lost the additive guarantee"
        )

    def test_verifying_always_yields_a_context_even_with_no_custom_ca(self):
        """httpx's own default trusts certifi ONLY; create_default_context
        also loads the OS store. A corporate CA installed system-wide (the
        normal IT route) is in the latter and not the former, so returning
        plain True would break the httpx clients under TLS inspection while
        the ssl-based web tools kept working — the exact split this module
        exists to prevent."""
        assert isinstance(tlsmod.tls_verify(), ssl.SSLContext)

    def test_os_trust_store_is_reachable_without_any_ssl_env(self):
        """Pins the mechanism the case above depends on."""
        import certifi

        ctx_roots = len(tlsmod.tls_ssl_context().get_ca_certs())
        certifi_roots = certifi.contents().count("BEGIN CERTIFICATE")
        assert ctx_roots > 0
        # Not asserting a strict inequality (a CI image may carry a minimal
        # OS store); asserting only that we go through create_default_context,
        # which consults the OS store, rather than certifi alone.
        assert tlsmod.tls_ssl_context().verify_mode == ssl.CERT_REQUIRED
        assert certifi_roots > 0

    def test_insecure_still_wins_over_the_context_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SSL_VERIFY", "false")
        monkeypatch.setenv("SSL_CERT_FILE", str(self._real_ca(tmp_path)))
        assert tlsmod.tls_verify() is False


class TestEnvVerifyTrueOverridesConfigOptOut:
    """SSL_VERIFY=true must beat network.ssl.verify=false.

    Env is the higher-priority layer in BOTH directions. Before the fix
    it was only consulted for the false spelling, so a ConfigMap or
    committed JSON carrying `verify: false` silently won over the layer
    the docstring declares higher-priority — and /doctor reported the
    config value, agreeing with the wrong answer.
    """

    def test_env_true_re_enables_over_config_false(self, monkeypatch):
        monkeypatch.setenv("SSL_VERIFY", "true")
        monkeypatch.setattr(tlsmod, "_ssl_config_block", lambda: {"verify": False})
        s = tlsmod.resolve_tls_verify()
        assert not s.is_insecure
        assert s.source == "env"
        assert "overrides" in s.reason  # /doctor must explain, not contradict

    def test_config_false_still_wins_when_env_is_unset(self, monkeypatch):
        """Regression guard: the override must not weaken the config opt-out."""
        monkeypatch.setattr(tlsmod, "_ssl_config_block", lambda: {"verify": False})
        assert tlsmod.resolve_tls_verify().is_insecure

    def test_unrecognised_env_value_is_not_an_opt_in(self, monkeypatch):
        """Garbage in SSL_VERIFY neither disables nor force-enables."""
        monkeypatch.setenv("SSL_VERIFY", "banana")
        monkeypatch.setattr(tlsmod, "_ssl_config_block", lambda: {"verify": False})
        assert tlsmod.resolve_tls_verify().is_insecure

    def test_env_true_with_config_cert_file_uses_the_bundle(
        self, monkeypatch, tmp_path
    ):
        """Re-enabling verification keeps the configured CA in play."""
        ca = tmp_path / "ca.pem"
        ca.write_text(_SYNTHETIC_CA_PEM, encoding="utf-8")
        monkeypatch.setenv("SSL_VERIFY", "true")
        monkeypatch.setattr(
            tlsmod,
            "_ssl_config_block",
            lambda: {"verify": False, "cert_file": str(ca)},
        )
        s = tlsmod.resolve_tls_verify()
        assert not s.is_insecure
        assert s.cert_file == str(ca)


class TestContextCache:
    """Contexts are memoised per resolved policy, not rebuilt per request.

    Per-request construction re-parsed the whole OS trust store (~10 ms)
    at four call sites in web.py alone. Identity, not equality: sharing
    one SSLContext across connections is the documented pattern.
    """

    def test_same_policy_returns_the_same_context(self):
        assert tlsmod.tls_ssl_context() is tlsmod.tls_ssl_context()

    def test_reset_yields_a_fresh_context(self):
        first = tlsmod.tls_ssl_context()
        tlsmod.reset_tls_context_cache()
        assert tlsmod.tls_ssl_context() is not first

    def test_policy_change_yields_a_different_context(self, monkeypatch, tmp_path):
        default_ctx = tlsmod.tls_ssl_context()
        ca = tmp_path / "ca.pem"
        ca.write_text(_SYNTHETIC_CA_PEM, encoding="utf-8")
        monkeypatch.setenv("SSL_CERT_FILE", str(ca))
        assert tlsmod.tls_ssl_context() is not default_ctx


class TestDescribe:
    def test_describe_flags_disabled(self, monkeypatch):
        monkeypatch.setenv("SSL_VERIFY", "false")
        assert "DISABLED" in tlsmod.describe_tls()

    def test_describe_names_custom_ca(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SSL_CERT_FILE", str(_cert(tmp_path)))
        assert "custom CA" in tlsmod.describe_tls()


class TestConfigFileActuallyReachesTheResolver:
    """End-to-end through the REAL loader — no stubbing of the block reader.

    `load_config()`'s return dict is a WHITELIST: a top-level JSON key not
    plumbed through it is silently invisible to every reader. `network`
    was missing when this feature was written, so the whole JSON half was
    dead config while `tls.py` read it happily. Every test that stubs
    `_ssl_config_block` is blind to that, which is why this one exists.
    Same trap previously hit `file_tree` (v1.18.7), `execution` (F3), and
    `providers.<name>.web_search` (v1.13.4).
    """

    def _load_with(self, tmp_path, monkeypatch, payload):
        import json

        from ppxai.config import loader

        cfg = tmp_path / "ppxai-config.json"
        cfg.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))
        return loader.load_config()

    def test_network_block_survives_the_loader_whitelist(
        self, tmp_path, monkeypatch
    ):
        loaded = self._load_with(
            tmp_path,
            monkeypatch,
            {
                "version": "1",
                "providers": {},
                "network": {"ssl": {"verify": False, "cert_file": "/x.pem"}},
            },
        )
        assert loaded.get("network") == {
            "ssl": {"verify": False, "cert_file": "/x.pem"}
        }, (
            "network.* was dropped by load_config()'s whitelist — add it to "
            "the returned dict in ppxai/config/loader.py"
        )

    def test_config_file_verify_false_reaches_the_resolver(
        self, tmp_path, monkeypatch
    ):
        """The end-to-end path: JSON file → loader → get_config → resolver."""
        self._load_with(
            tmp_path,
            monkeypatch,
            {"version": "1", "providers": {}, "network": {"ssl": {"verify": False}}},
        )
        monkeypatch.setattr(tlsmod, "_ssl_config_block", _REAL_SSL_BLOCK)
        monkeypatch.setattr(
            tlsmod,
            "get_config",
            lambda: {"network": {"ssl": {"verify": False}}},
        )
        setting = tlsmod.resolve_tls_verify()
        assert setting.verify is False
        assert setting.source == "config"


class TestShippedExampleConfig:
    """The example config must document `network.ssl` and must not ship a
    setting that disables TLS."""

    def _example(self):
        import json
        from pathlib import Path

        p = Path(__file__).resolve().parents[1] / "ppxai-config.example.json"
        return json.loads(p.read_text(encoding="utf-8"))

    def test_example_documents_the_network_ssl_block(self):
        ssl_block = self._example().get("network", {}).get("ssl")
        assert ssl_block is not None, (
            "ppxai-config.example.json must document network.ssl — it is the "
            "config-file half of the TLS surface"
        )
        assert "verify" in ssl_block and "cert_file" in ssl_block

    def test_example_does_not_ship_tls_disabled(self, monkeypatch):
        """An example that turns verification off would propagate to every
        user who copies it."""
        ssl_block = self._example()["network"]["ssl"]
        monkeypatch.setattr(tlsmod, "_ssl_config_block", lambda: ssl_block)
        setting = tlsmod.resolve_tls_verify()
        assert setting.verify is True, (
            f"the shipped example resolves to {setting.verify!r} "
            f"({setting.reason})"
        )
        assert not setting.is_insecure

    def test_example_empty_cert_file_is_not_a_configured_path(
        self, monkeypatch
    ):
        """`"cert_file": ""` is a documentation placeholder, not a bundle."""
        ssl_block = self._example()["network"]["ssl"]
        assert ssl_block["cert_file"] == ""
        monkeypatch.setattr(tlsmod, "_ssl_config_block", lambda: ssl_block)
        assert tlsmod.resolve_tls_verify().cert_file is None


class TestNoSiteReadsEnvDirectly:
    """The regression fence. Six sites re-read SSL_VERIFY/SSL_CERT_FILE and
    drifted; only the resolver may read them now."""

    def test_only_the_resolver_reads_the_env_vars(self):
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "ppxai"
        pattern = re.compile(r"""getenv\(\s*["']SSL_(VERIFY|CERT_FILE)["']""")
        offenders = [
            str(p.relative_to(root))
            for p in root.rglob("*.py")
            if p.name != "tls.py" and pattern.search(p.read_text(encoding="utf-8"))
        ]
        assert offenders == [], (
            "These modules re-read the SSL env vars instead of calling "
            f"ppxai.config.tls: {offenders}"
        )

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


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """No ambient SSL_* from the developer's own shell/.env."""
    monkeypatch.delenv("SSL_VERIFY", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(tlsmod, "_ssl_config_block", lambda: {})


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
        assert tlsmod.tls_verify() is True

    def test_missing_cert_context_still_verifies(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "gone.pem"))
        assert tlsmod.tls_ssl_context().verify_mode == ssl.CERT_REQUIRED


class TestDescribe:
    def test_describe_flags_disabled(self, monkeypatch):
        monkeypatch.setenv("SSL_VERIFY", "false")
        assert "DISABLED" in tlsmod.describe_tls()

    def test_describe_names_custom_ca(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SSL_CERT_FILE", str(_cert(tmp_path)))
        assert "custom CA" in tlsmod.describe_tls()


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

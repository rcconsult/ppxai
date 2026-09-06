"""
Tests for web tools SSL context, HTTP fallback, and configurable timeouts.

Covers fixes from BUGFIX-WEB-TOOLS-CORPORATE-SSL.md:
- _create_ssl_context() respects SSL_VERIFY and SSL_CERT_FILE env vars
- get_weather HTTP fallback when HTTPS fails behind corporate proxies
- _get_web_timeout() reads from config
"""

import os
import ssl
import tempfile
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.tools.builtin.web import (
    _create_ssl_context,
    _get_web_timeout,
    get_weather,
)


class TestCreateSSLContext:
    """Tests for _create_ssl_context() helper."""

    def test_default_uses_system_certs(self):
        """Default config returns a context with verification enabled."""
        with patch.dict(os.environ, {}, clear=True):
            ctx = _create_ssl_context()
            assert ctx.verify_mode == ssl.CERT_REQUIRED
            assert ctx.check_hostname is True

    def test_ssl_verify_false_disables_verification(self):
        """SSL_VERIFY=false returns a context with CERT_NONE."""
        with patch.dict(os.environ, {"SSL_VERIFY": "false"}, clear=True):
            ctx = _create_ssl_context()
            assert ctx.verify_mode == ssl.CERT_NONE
            assert ctx.check_hostname is False

    def test_ssl_verify_false_case_insensitive(self):
        """SSL_VERIFY=FALSE (uppercase) also disables verification."""
        with patch.dict(os.environ, {"SSL_VERIFY": "FALSE"}, clear=True):
            ctx = _create_ssl_context()
            assert ctx.verify_mode == ssl.CERT_NONE

    def test_ssl_cert_file_is_added_to_the_system_roots(self):
        """SSL_CERT_FILE ADDS a CA; it must not replace the trust store.

        Retargeted 2026-08-13. This test used to patch
        `web.ssl.create_default_context` and assert it was called with
        `cafile=<path>` — i.e. it pinned the *replace* semantics. Two
        things changed: `_create_ssl_context` now delegates to
        `ppxai.config.tls`, so the patched symbol is no longer reached,
        and a bundle passed as `cafile=` SUBSTITUTES for the default
        roots, which breaks every public endpoint once the machine
        leaves a TLS-inspecting network. Asserting the observable
        outcome (root count grows) instead of the call shape also stops
        the test from re-breaking on the next refactor.
        """
        from tests.test_tls_config import _SYNTHETIC_CA_PEM, CAPATH_SKIP_REASON

        with tempfile.NamedTemporaryFile(
            suffix=".pem", delete=False, mode="w", encoding="utf-8"
        ) as f:
            cert_path = f.name
            f.write(_SYNTHETIC_CA_PEM)

        try:
            # Drive the CONFIG path, not SSL_CERT_FILE: OpenSSL honours that
            # env var itself, so create_default_context() would pick the CA
            # up regardless and the assertion could not tell whether our own
            # code added it (a mutation proved this exact blind spot).
            #
            # Baseline is measured INSIDE the same cleared-env block as the
            # subject. tests/conftest.py loads the developer's real
            # ~/.ppxai/.env (for SSL_VERIFY), so a baseline taken outside
            # can be computed under different ambient TLS env than the
            # value it is compared with — that made this test pass alone
            # and fail in the full suite.
            with patch.dict(os.environ, {}, clear=True):
                baseline = len(ssl.create_default_context().get_ca_certs())
                with patch(
                    "ppxai.config.tls._ssl_config_block",
                    lambda: {"cert_file": cert_path},
                ):
                    additive = len(_create_ssl_context().get_ca_certs())
                replaced = len(
                    ssl.create_default_context(cafile=cert_path).get_ca_certs()
                )
            # Strictly added — comparing only against cafile-only would also
            # pass if the CA were dropped entirely (a mutation proved it).
            assert additive == baseline + 1, (
                f"custom CA was not added: {additive} roots vs baseline "
                f"{baseline}"
            )

            # The second half only has a truth value where the OS default
            # store enumerates. `baseline == 0` IS that test, and it is the
            # right one to use here because it was measured inside the same
            # cleared-env block as `additive` — see the rationale block at
            # the top of tests/test_tls_config.py for the mechanism (a
            # capath store is read lazily, so it counts 0 while verifying
            # normally, and an additive context is then indistinguishable
            # from a replacing one without a real handshake).
            if baseline == 0:
                pytest.skip(CAPATH_SKIP_REASON)

            assert additive > replaced, (
                f"custom CA replaced the trust store ({additive} roots vs "
                f"{replaced} for cafile-only) — a roaming laptop would lose "
                "every public endpoint off the corporate network"
            )
        finally:
            os.unlink(cert_path)

    def test_ssl_cert_file_nonexistent_falls_back_to_system(self):
        """SSL_CERT_FILE with non-existent path falls back to system certs."""
        with patch.dict(os.environ, {"SSL_CERT_FILE": "/nonexistent/cert.pem"}, clear=True):
            ctx = _create_ssl_context()
            # Should fall through to default context (system certs)
            assert ctx.verify_mode == ssl.CERT_REQUIRED
            assert ctx.check_hostname is True

    def test_ssl_verify_true_with_cert_file(self):
        """SSL_VERIFY=true + SSL_CERT_FILE still verifies, with the CA added.

        Retargeted alongside the case above — same reason: it asserted
        `cafile=` on a now-unreached patch target.
        """
        import certifi

        pem = []
        with open(certifi.where(), encoding="utf-8") as fh:
            for line in fh:
                pem.append(line)
                if line.startswith("-----END CERTIFICATE-----"):
                    break

        with tempfile.NamedTemporaryFile(
            suffix=".pem", delete=False, mode="w", encoding="utf-8"
        ) as f:
            cert_path = f.name
            f.write("".join(pem))

        try:
            with patch.dict(
                os.environ,
                {"SSL_VERIFY": "true", "SSL_CERT_FILE": cert_path},
                clear=True,
            ):
                ctx = _create_ssl_context()
                assert ctx.verify_mode == ssl.CERT_REQUIRED
                assert ctx.check_hostname is True
                assert len(ctx.get_ca_certs()) > 0
        finally:
            os.unlink(cert_path)


class TestGetWebTimeout:
    """Tests for _get_web_timeout() config reader."""

    def test_returns_default_when_no_config(self):
        """Returns default timeout when config import fails."""
        with patch("ppxai.engine.tools.builtin.web.get_tool_config", side_effect=Exception("no config")):
            timeout = _get_web_timeout("get_weather", default=15)
            assert timeout == 15

    def test_reads_timeout_from_config(self):
        """Reads timeout from tools.<name>.timeout config."""
        mock_config = {"timeout": 30}
        with patch("ppxai.engine.tools.builtin.web.get_tool_config", return_value=mock_config):
            timeout = _get_web_timeout("get_weather", default=15)
            assert timeout == 30

    def test_returns_default_when_timeout_not_in_config(self):
        """Returns default when config exists but has no timeout key."""
        mock_config = {"some_other_key": "value"}
        with patch("ppxai.engine.tools.builtin.web.get_tool_config", return_value=mock_config):
            timeout = _get_web_timeout("fetch_url", default=15)
            assert timeout == 15

    def test_different_defaults_per_tool(self):
        """Each tool can have its own default timeout."""
        with patch("ppxai.engine.tools.builtin.web.get_tool_config", return_value={}):
            assert _get_web_timeout("get_weather", default=15) == 15
            assert _get_web_timeout("fetch_url", default=20) == 20


class TestGetWeatherHTTPSOnly:
    """`get_weather` is HTTPS-only (v1.19.1, ADR 0009 §2 — debt Item 52).

    These tests previously asserted the OPPOSITE: an https→plain-http retry
    added for corporate proxies. That fallback put an always-denied scheme
    into the tool's egress superset, and the per-run NetworkPolicy grants
    all-or-nothing — so `get_weather` could never be allowlisted for a
    sandboxed run. The scheme downgrade was removed; reliability fallback is
    now a *different host over https* (`get_weather_openmeteo`) selected by
    the tool chain, which the allowlist can express.

    A stalled corporate-proxy handshake therefore surfaces as an error string
    from this tool and the chain moves on — it must never silently retry in
    cleartext.
    """

    def test_https_success_makes_exactly_one_request(self):
        mock_response = MagicMock()
        mock_response.read.return_value = b"Lausanne: +5C"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("ppxai.engine.tools.builtin.web.urllib.request.urlopen", return_value=mock_response) as mock_open, \
             patch("ppxai.engine.tools.builtin.web._get_web_timeout", return_value=15):
            result = get_weather("Lausanne")
            assert "Lausanne" in result
            assert mock_open.call_count == 1
            req = mock_open.call_args[0][0]
            assert req.full_url.startswith("https://")

    def test_timeout_errors_out_without_a_cleartext_retry(self):
        """The Item 52 contract: a failed HTTPS call is the END of this tool."""
        schemes = []

        def mock_urlopen(req, timeout=None, context=None):
            schemes.append(req.full_url.split(":", 1)[0])
            raise urllib.error.URLError("timed out")

        with patch("ppxai.engine.tools.builtin.web.urllib.request.urlopen", side_effect=mock_urlopen), \
             patch("ppxai.engine.tools.builtin.web._get_web_timeout", return_value=15):
            result = get_weather("Lausanne")
            assert schemes == ["https"]
            assert "Error" in result and "timed out" in result

    def test_ssl_error_errors_out_without_a_cleartext_retry(self):
        """An SSL failure is exactly the case the old fallback downgraded on —
        the strongest signal that a proxy is intercepting. Never retry."""
        schemes = []

        def mock_urlopen(req, timeout=None, context=None):
            schemes.append(req.full_url.split(":", 1)[0])
            raise ssl.SSLError("certificate verify failed")

        with patch("ppxai.engine.tools.builtin.web.urllib.request.urlopen", side_effect=mock_urlopen), \
             patch("ppxai.engine.tools.builtin.web._get_web_timeout", return_value=15):
            result = get_weather("Geneva")
            assert schemes == ["https"]
            assert "Error" in result

    def test_every_request_carries_an_ssl_context(self):
        """No code path may pass context=None — that was the plain-http leg."""
        contexts = []

        def mock_urlopen(req, timeout=None, context=None):
            contexts.append(context)
            raise urllib.error.URLError("timed out")

        with patch("ppxai.engine.tools.builtin.web.urllib.request.urlopen", side_effect=mock_urlopen), \
             patch("ppxai.engine.tools.builtin.web._get_web_timeout", return_value=15):
            get_weather("Test")
            assert len(contexts) == 1
            assert contexts[0] is not None

    def test_connection_failure_returns_error_string_never_raises(self):
        """Chainable contract: callers fall through to the next weather
        backend on an 'Error: ...' string, so this must not raise."""
        def mock_urlopen(req, timeout=None, context=None):
            raise urllib.error.URLError("connection refused")

        with patch("ppxai.engine.tools.builtin.web.urllib.request.urlopen", side_effect=mock_urlopen), \
             patch("ppxai.engine.tools.builtin.web._get_web_timeout", return_value=15):
            result = get_weather("Nowhere")
            assert "Error" in result

    def test_http_404_reports_location_not_found(self):
        def mock_urlopen(req, timeout=None, context=None):
            raise urllib.error.HTTPError(
                req.full_url, 404, "Not Found", {}, None
            )

        with patch("ppxai.engine.tools.builtin.web.urllib.request.urlopen", side_effect=mock_urlopen), \
             patch("ppxai.engine.tools.builtin.web._get_web_timeout", return_value=15):
            result = get_weather("InvalidCity123")
            assert "not found" in result.lower()

    def test_source_carries_no_plain_http_url(self):
        """Sentinel: the egress superset for this tool is https-only, so a
        reintroduced `http://wttr.in` would silently make the tool
        un-allowlistable again (the failure mode Item 52 documented)."""
        from pathlib import Path

        src = (Path(__file__).parent.parent / "ppxai" / "engine" / "tools"
               / "builtin" / "web.py").read_text(encoding="utf-8")
        assert "http://wttr.in" not in src


class TestPerplexityClientLifecycle:
    """web_search_perplexity must close the httpx client it creates.

    tls_verify() never returns True (always False or an SSLContext), so
    the old `None if verify is True else AsyncClient(...)` ternary built
    a client on EVERY call — and AsyncOpenAI never closes a
    caller-supplied http_client (no __del__; verified on openai 2.11.0).
    In a long-lived server each web_search leaked a connection pool.
    The fix wraps the client in `async with`, same as web_search_gemini.
    """

    @staticmethod
    def _canned_response():
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "answer"
        response.citations = ["https://example.com"]
        response.usage.prompt_tokens = 10
        response.usage.completion_tokens = 20
        return response

    @pytest.mark.asyncio
    async def test_http_client_is_closed_after_the_call(self, monkeypatch):
        from ppxai.engine.tools.builtin import web_premium

        monkeypatch.setenv("PERPLEXITY_API_KEY", "test-key")
        captured = {}

        class FakeAsyncOpenAI:
            def __init__(self, api_key, base_url=None, http_client=None):
                captured["http_client"] = http_client
                self.chat = MagicMock()
                create = MagicMock()

                async def _create(**kwargs):
                    return TestPerplexityClientLifecycle._canned_response()

                create.create = _create
                self.chat.completions = create

        with patch.object(web_premium, "AsyncOpenAI", FakeAsyncOpenAI):
            await web_premium.web_search_perplexity("q")

        assert captured["http_client"] is not None, (
            "an explicit http_client must be supplied (tls_verify() "
            "never returns True)"
        )
        assert captured["http_client"].is_closed, (
            "the AsyncClient was not closed after the call — connection "
            "pool leaks on every web_search in a long-lived server"
        )

    @pytest.mark.asyncio
    async def test_http_client_is_closed_when_the_request_raises(self, monkeypatch):
        from ppxai.engine.tools.builtin import web_premium

        monkeypatch.setenv("PERPLEXITY_API_KEY", "test-key")
        captured = {}

        class FakeAsyncOpenAI:
            def __init__(self, api_key, base_url=None, http_client=None):
                captured["http_client"] = http_client
                self.chat = MagicMock()
                create = MagicMock()

                async def _create(**kwargs):
                    raise RuntimeError("provider down")

                create.create = _create
                self.chat.completions = create

        with patch.object(web_premium, "AsyncOpenAI", FakeAsyncOpenAI):
            with pytest.raises(RuntimeError):
                await web_premium.web_search_perplexity("q")

        assert captured["http_client"].is_closed, (
            "the AsyncClient must be closed on the error path too"
        )

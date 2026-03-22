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
from unittest.mock import patch, MagicMock

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

    def test_ssl_cert_file_loads_custom_ca(self):
        """SSL_CERT_FILE pointing to a real file loads it as CA."""
        # Create a temp file to act as cert (we just check the path is accepted)
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as f:
            cert_path = f.name
            # Write a minimal (invalid but parseable-path) cert file
            f.write(b"dummy")

        try:
            with patch.dict(os.environ, {"SSL_CERT_FILE": cert_path}, clear=True):
                # ssl.create_default_context(cafile=...) will raise if file is invalid,
                # but we're testing the branching logic, so mock the ssl call
                with patch("ppxai.engine.tools.builtin.web.ssl.create_default_context") as mock_ctx:
                    mock_ctx.return_value = MagicMock(spec=ssl.SSLContext)
                    ctx = _create_ssl_context()
                    mock_ctx.assert_called_once_with(cafile=cert_path)
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
        """SSL_VERIFY=true + SSL_CERT_FILE uses the cert file."""
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as f:
            cert_path = f.name
            f.write(b"dummy")

        try:
            with patch.dict(os.environ, {"SSL_VERIFY": "true", "SSL_CERT_FILE": cert_path}, clear=True):
                with patch("ppxai.engine.tools.builtin.web.ssl.create_default_context") as mock_ctx:
                    mock_ctx.return_value = MagicMock(spec=ssl.SSLContext)
                    ctx = _create_ssl_context()
                    mock_ctx.assert_called_once_with(cafile=cert_path)
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


class TestGetWeatherHTTPFallback:
    """Tests for get_weather HTTP fallback when HTTPS fails."""

    def test_https_success_no_fallback(self):
        """When HTTPS works, HTTP fallback is not attempted."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"Lausanne: +5C"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("ppxai.engine.tools.builtin.web.urllib.request.urlopen", return_value=mock_response) as mock_open, \
             patch("ppxai.engine.tools.builtin.web._get_web_timeout", return_value=15):
            result = get_weather("Lausanne")
            assert "Lausanne" in result
            # Should have been called once (HTTPS only)
            assert mock_open.call_count == 1
            call_args = mock_open.call_args
            req = call_args[0][0]
            assert req.full_url.startswith("https://")

    def test_https_timeout_falls_back_to_http(self):
        """When HTTPS times out, falls back to HTTP."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"Lausanne: +5C"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        call_count = 0

        def mock_urlopen(req, timeout=None, context=None):
            nonlocal call_count
            call_count += 1
            if req.full_url.startswith("https://"):
                raise urllib.error.URLError("timed out")
            return mock_response

        with patch("ppxai.engine.tools.builtin.web.urllib.request.urlopen", side_effect=mock_urlopen), \
             patch("ppxai.engine.tools.builtin.web._get_web_timeout", return_value=15):
            result = get_weather("Lausanne")
            assert "Lausanne" in result
            assert call_count == 2  # HTTPS failed, HTTP succeeded

    def test_https_ssl_error_falls_back_to_http(self):
        """When HTTPS has SSL error, falls back to HTTP."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"Geneva: +3C"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        def mock_urlopen(req, timeout=None, context=None):
            if req.full_url.startswith("https://"):
                raise ssl.SSLError("certificate verify failed")
            return mock_response

        with patch("ppxai.engine.tools.builtin.web.urllib.request.urlopen", side_effect=mock_urlopen), \
             patch("ppxai.engine.tools.builtin.web._get_web_timeout", return_value=15):
            result = get_weather("Geneva")
            assert "Geneva" in result

    def test_both_schemes_fail_returns_error(self):
        """When both HTTPS and HTTP fail, returns error."""
        def mock_urlopen(req, timeout=None, context=None):
            raise urllib.error.URLError("connection refused")

        with patch("ppxai.engine.tools.builtin.web.urllib.request.urlopen", side_effect=mock_urlopen), \
             patch("ppxai.engine.tools.builtin.web._get_web_timeout", return_value=15):
            result = get_weather("Nowhere")
            assert "Error" in result

    def test_http_404_does_not_retry(self):
        """HTTP 404 is not a connection issue — don't fall back."""
        def mock_urlopen(req, timeout=None, context=None):
            raise urllib.error.HTTPError(
                req.full_url, 404, "Not Found", {}, None
            )

        with patch("ppxai.engine.tools.builtin.web.urllib.request.urlopen", side_effect=mock_urlopen), \
             patch("ppxai.engine.tools.builtin.web._get_web_timeout", return_value=15):
            result = get_weather("InvalidCity123")
            assert "not found" in result.lower()

    def test_http_context_is_none_for_plain_http(self):
        """HTTP fallback passes context=None (no SSL for plain HTTP)."""
        call_contexts = []

        def mock_urlopen(req, timeout=None, context=None):
            call_contexts.append(context)
            if req.full_url.startswith("https://"):
                raise urllib.error.URLError("timed out")
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"Test: +1C"
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("ppxai.engine.tools.builtin.web.urllib.request.urlopen", side_effect=mock_urlopen), \
             patch("ppxai.engine.tools.builtin.web._get_web_timeout", return_value=15):
            get_weather("Test")
            assert len(call_contexts) == 2
            assert call_contexts[0] is not None  # HTTPS has SSL context
            assert call_contexts[1] is None  # HTTP has no SSL context

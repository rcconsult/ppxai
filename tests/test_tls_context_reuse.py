"""Building a provider must not load a CA bundle.

Root cause of a 45-minute Windows suite (2026-09-27): the Windows CPython
build bundles OpenSSL 3.0, where `load_verify_locations(cafile=certifi)`
costs ~0.75s of CPU per call. google-genai builds its own async and
websocket contexts from certifi whenever `client_args`/`async_client_args`
carry none -- even with `httpx_client` set -- so every GeminiProvider cost
~1.5s, and every server startup (every `with TestClient(app)`) ~2s.

The fix hands the SDK the resolved, cached context from
`ppxai.config.tls`. These tests assert the MECHANISM -- after the shared
context exists, building providers loads no CA bundle and every SDK slot
holds the shared value -- not a timing threshold: on macOS (OpenSSL 3.6)
the slow path costs 14 ms, so a timing test would pass there with the bug
still present. Both TLS policies are covered: verification on (a context)
and off (`False`, e.g. SSL_VERIFY=false on an inspecting network).
"""

import ssl

import pytest

from ppxai.config.tls import reset_tls_context_cache, tls_verify

pytest.importorskip("google.genai")

from ppxai.engine.providers.gemini import GeminiProvider  # noqa: E402


@pytest.fixture(params=["true", "false"], ids=["verify-on", "verify-off"])
def tls_policy(request, monkeypatch):
    monkeypatch.setenv("SSL_VERIFY", request.param)
    reset_tls_context_cache()
    yield request.param
    reset_tls_context_cache()


@pytest.fixture
def ca_loads(tls_policy, monkeypatch):
    """Count the EXPENSIVE operations: building a default context (loads the
    system or certifi roots) and loading a CA file. A bare
    `SSLContext(PROTOCOL_TLS_CLIENT)` loads nothing and is not counted."""
    tls_verify()  # the one legitimate build: the shared, cached context
    # conftest shares one context across default-TLS httpx clients to keep
    # the suite fast; that cache would hide exactly the regression this file
    # guards (the SDK building its own default context), so bypass it here.
    import httpx._transports.default as transport

    from tests.conftest import REAL_CREATE_SSL_CONTEXT
    monkeypatch.setattr(transport, "create_ssl_context", REAL_CREATE_SSL_CONTEXT)
    calls = []
    real_create = ssl.create_default_context
    real_load = ssl.SSLContext.load_verify_locations

    def create(*args, **kwargs):
        calls.append(("create_default_context", kwargs.get("cafile")))
        return real_create(*args, **kwargs)

    def load(self, *args, **kwargs):
        calls.append(("load_verify_locations", kwargs.get("cafile")))
        return real_load(self, *args, **kwargs)

    monkeypatch.setattr(ssl, "create_default_context", create)
    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", load)
    return calls


def test_gemini_provider_loads_no_ca_bundle(ca_loads):
    GeminiProvider(api_key="test-key", provider_id="gemini")
    GeminiProvider(api_key="test-key", provider_id="gemini")
    assert ca_loads == [], (
        f"constructing two GeminiProviders loaded CA roots {len(ca_loads)} "
        f"time(s): {ca_loads}. Each load costs ~0.75s under OpenSSL 3.0. Pass "
        "the cached tls_verify() value in client_args and async_client_args "
        "(verify + ssl) so google-genai builds no context of its own.")


def test_every_gemini_sdk_slot_holds_the_shared_value(tls_policy):
    shared = tls_verify()
    api = GeminiProvider(api_key="test-key", provider_id="gemini").client._api_client
    assert api._async_httpx_client_args["verify"] is shared
    assert api._websocket_ssl_ctx["ssl"] is shared


def test_the_shared_context_is_reused_across_calls(tls_policy):
    assert tls_verify() is tls_verify()

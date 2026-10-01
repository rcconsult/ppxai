"""Loopback HTTP clients must not go through HTTP_PROXY.

httpx and urllib send requests for 127.0.0.1/localhost to HTTP_PROXY when it
is set (docs/lessons/loopback-http-hops-must-not-read-proxy-env.md). Behind a
corporate proxy that made the preview readiness poll report "up" on the
proxy's own reply, sent every /preview request to the proxy, and kept
ppxai-desktop and the gateway scripts from ever seeing the local server.

Each client below is pointed at a real local server while HTTP_PROXY names a
recording stand-in proxy that answers 502. The client must reach the server
and the proxy must see nothing.
"""

from __future__ import annotations

import asyncio
import http.server
import importlib.util
import threading
import urllib.request
from pathlib import Path

import pytest

from ppxai.commands import doctor
from ppxai.config.network import is_loopback_url
from ppxai.engine import multimodal_ops, preview_backend
from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

REPO = Path(__file__).resolve().parents[1]


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


def _serve(handler) -> tuple[_Server, int]:
    srv = _Server(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


@pytest.fixture
def backend():
    class Ok(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"status": "healthy", "version": "test"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv, port = _serve(Ok)
    yield port
    srv.shutdown()


@pytest.fixture
def proxy(monkeypatch):
    """A stand-in corporate proxy that records every request and answers 502."""
    seen: list[str] = []

    class Proxy(http.server.BaseHTTPRequestHandler):
        def _any(self):
            seen.append(self.path)
            self.send_response(502)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_POST = do_CONNECT = _any  # noqa: N815 -- BaseHTTPRequestHandler's names

        def log_message(self, *a):
            pass

    srv, port = _serve(Proxy)
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    for var in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(var, f"http://127.0.0.1:{port}")
    yield seen
    srv.shutdown()


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_stand_in_proxy_really_catches_a_default_client(backend, proxy):
    # Control: without the fixes' opt-out, urllib DOES go to the proxy here,
    # so the tests below prove something. A FRESH opener, not urlopen():
    # urlopen caches a global opener on its first call and ProxyHandler reads
    # the environment only then, so after any earlier urlopen in this worker
    # the cached opener has no proxy and the control would go direct.
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.build_opener().open(f"http://127.0.0.1:{backend}/health", timeout=5)
    assert err.value.code == 502
    assert proxy, "the stand-in proxy saw nothing: the control is broken"


def test_preview_backend_readiness_poll_bypasses_the_proxy(backend, proxy):
    assert asyncio.run(preview_backend.wait_for_port(backend, timeout=5)) is True
    assert proxy == []


def test_a_dead_backend_is_not_reported_ready_by_the_proxy(proxy):
    # Nothing listens on this port; the proxy would answer 502, which the old
    # poll counted as "up".
    with _Server(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler) as tmp:
        dead = tmp.server_address[1]
    assert asyncio.run(preview_backend.wait_for_port(dead, timeout=1.0)) is False
    assert proxy == []


def test_desktop_wait_for_server_bypasses_the_proxy(backend, proxy):
    desktop = _load_script(REPO / "ppxai-desktop.py", "_ppxai_desktop_under_test")
    assert desktop.wait_for_server(backend, timeout=5) is True
    assert proxy == []


@pytest.mark.parametrize("script", ["gateway-smoke.py", "trial-task-lifecycle.py"])
def test_gateway_scripts_skip_the_proxy_only_for_loopback(script, backend, proxy, monkeypatch):
    mod = _load_script(REPO / "scripts" / script, "_script_" + script.replace("-", "_")[:-3])
    req = urllib.request.Request(f"http://127.0.0.1:{backend}/health")
    with mod._urlopen(req, timeout=5) as resp:
        assert resp.status == 200
    assert proxy == []

    # A remote gateway keeps the environment's proxy.
    used = []
    monkeypatch.setattr(mod.urllib.request, "urlopen",
                        lambda r, data=None, timeout=30: used.append(r.full_url) or "via-env")
    assert mod._urlopen(urllib.request.Request("http://gateway.example.test/health")) == "via-env"
    assert used == ["http://gateway.example.test/health"]


def test_the_preview_proxy_route_does_not_read_the_proxy_env():
    # The /preview route's client is built inside a request handler that needs
    # a live preview session; pin its construction instead.
    src = (REPO / "ppxai" / "server" / "routes" / "preview.py").read_text(encoding="utf-8")
    body = src[src.index('target_url = f"http://localhost:{port}/{path}"'):]
    body = body[:body.index("except httpx.ConnectError")]
    assert "trust_env=False" in body


# ---------------------------------------------------------------------------
# Clients whose URL comes from config: skip the proxy for loopback ONLY
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("url", "loopback"), [
    ("http://127.0.0.1:8000/v1", True),
    ("http://127.8.9.10/v1", True),
    ("http://localhost:11434/v1", True),
    ("http://LOCALHOST/v1", True),
    ("http://[::1]:8000/v1", True),
    ("https://api.openai.com/v1", False),
    ("http://10.0.0.5:8000/v1", False),
    ("http://localhost.example.com/v1", False),
    ("http://[not-an-ip/v1", False),
    ("", False),
    (None, False),
])
def test_is_loopback_url(url, loopback):
    assert is_loopback_url(url) is loopback


def test_a_loopback_provider_base_url_bypasses_the_proxy(backend, proxy):
    # A local vLLM / Ollama / LM Studio, or an SSH forward. The SDK's own
    # httpx client is the one base.py built, so this is the real path.
    provider = OpenAICompatibleProvider(api_key="k", base_url=f"http://127.0.0.1:{backend}/v1",
                                        provider_id="local")
    assert provider.client._client.get(f"http://127.0.0.1:{backend}/health").status_code == 200
    assert proxy == []


def test_a_hosted_provider_keeps_the_proxy_env():
    provider = OpenAICompatibleProvider(api_key="k", base_url="https://api.example.test/v1",
                                        provider_id="hosted")
    assert provider.client._client.trust_env is True


def test_the_doctor_probe_of_a_loopback_provider_bypasses_the_proxy(backend, proxy):
    result = doctor._probe_provider_endpoint("local", {"base_url": f"http://127.0.0.1:{backend}/v1"})
    assert result["reachable"] is True, result
    assert proxy == []


def test_a_loopback_vision_sidecar_bypasses_the_proxy(proxy, monkeypatch):
    class Completion(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = (b'{"id": "c", "object": "chat.completion", "created": 0, "model": "vl",'
                    b' "choices": [{"index": 0, "finish_reason": "stop",'
                    b' "message": {"role": "assistant", "content": "a cat"}}]}')
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv, port = _serve(Completion)
    try:
        monkeypatch.setattr(multimodal_ops, "get_vision_model_config", lambda: {
            "enabled": True, "endpoint": f"http://127.0.0.1:{port}", "model": "vl"})
        caption = multimodal_ops.caption_image(None, "x.png", "image/png", b"\x89PNG")
    finally:
        srv.shutdown()
    assert caption == "a cat"
    assert proxy == []

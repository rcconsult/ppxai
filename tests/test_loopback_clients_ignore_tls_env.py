"""Loopback HTTP clients must not read the TLS environment either.

An httpx client's `trust_env=False` does not reach a transport passed in as
`transport=`: the transport keeps its own `trust_env=True` and loads
`SSL_CERT_FILE` when it is built, even for a plain-HTTP hop. With the
variable naming a missing file (a CA bundle path copied from another
machine) that raised FileNotFoundError, and:

- the hub proxy (`remote_hub.Hub.client_for`) answered 500 to every
  proxied request -- found live on Windows, 2026-09-30;
- the hub's unix-socket probe (`remote.manager.http_request`) and the
  registry's `socket_answers` caught it as an OSError and reported a live
  server as not answering -- the registry would prune it as dead.

Each client is pointed at a real local server with SSL_CERT_FILE set to a
path that does not exist.
"""

from __future__ import annotations

import asyncio
import http.server
import os
import socketserver
import tempfile
import threading

import httpx
import pytest

from ppxai.remote import LocalEndpoint
from ppxai.remote.manager import http_request
from ppxai.server import registry
from ppxai.server.routes import remote_hub

_HAS_UDS = hasattr(socketserver, "UnixStreamServer")


class _Ok(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status": "healthy"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def address_string(self):  # a unix-socket peer has no address tuple
        return "local"

    def log_message(self, *a):
        pass


class _TcpServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture
def missing_ca(monkeypatch, tmp_path):
    path = tmp_path / "no-such-ca.pem"
    monkeypatch.setenv("SSL_CERT_FILE", str(path))
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    return path


@pytest.fixture
def tcp_backend():
    srv = _TcpServer(("127.0.0.1", 0), _Ok)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def uds_backend():
    if not _HAS_UDS:
        pytest.skip("unix sockets are POSIX-only")

    class Srv(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    # A short directory: AF_UNIX paths are capped near 104 bytes on macOS.
    tmp = tempfile.mkdtemp(prefix="ppx-")
    path = os.path.join(tmp, "s.sock")
    srv = Srv(path, _Ok)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield path
    srv.shutdown()
    srv.server_close()
    os.unlink(path)
    os.rmdir(tmp)


class _NoManager:
    """`Hub.__init__` only subscribes; the proxy client needs nothing else."""

    def subscribe(self, _listener):
        return lambda: None


def test_the_missing_ca_really_breaks_a_transport_that_trusts_the_env(missing_ca):
    # Control: without the opt-out, building the transport raises here, so the
    # tests below prove something.
    with pytest.raises(FileNotFoundError):
        httpx.AsyncHTTPTransport()
    with pytest.raises(FileNotFoundError):
        httpx.AsyncHTTPTransport(uds="/nonexistent.sock")
    with pytest.raises(FileNotFoundError):
        httpx.HTTPTransport(uds="/nonexistent.sock")


def test_the_hub_proxy_client_reaches_a_tcp_forward(missing_ca, tcp_backend):
    hub = remote_hub.Hub(_NoManager())
    client = hub.client_for("h", "s", LocalEndpoint("tcp", tcp_backend))

    async def get():
        try:
            return (await client.get("/health")).status_code
        finally:
            await client.aclose()

    assert asyncio.run(get()) == 200


def test_the_hub_proxy_client_builds_for_a_uds_forward(missing_ca):
    # Construction is where the env was read; it needs no socket to exist.
    hub = remote_hub.Hub(_NoManager())
    client = hub.client_for("h", "s", LocalEndpoint("uds", "/nonexistent.sock"))
    asyncio.run(client.aclose())


def test_the_hub_probe_reaches_a_tcp_forward(missing_ca, tcp_backend):
    status = asyncio.run(http_request(LocalEndpoint("tcp", tcp_backend), "t", "GET", "/health"))
    assert status == 200


def test_the_hub_probe_reaches_a_uds_forward(missing_ca, uds_backend):
    status = asyncio.run(http_request(LocalEndpoint("uds", uds_backend), "t", "GET", "/health"))
    assert status == 200


def test_the_registry_does_not_read_a_live_server_as_dead(missing_ca, uds_backend):
    assert registry.socket_answers(uds_backend, token="t") is True

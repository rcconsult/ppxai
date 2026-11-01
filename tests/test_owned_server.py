"""`ppxai-server --owned` (ADR 0017): a server its parent process owns.

The contract a parent such as tai relies on:
- the parent's PPXAI_API_TOKEN is required and honoured even when the
  user's auth chain is a file store alone;
- no loopback exemption: every route but CORS preflight needs the bearer,
  /health included;
- port 0, reported as ONE JSON line, the first line on stdout;
- misuse is refused before anything binds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import httpx
import pytest
from starlette.requests import Request

from ppxai.server import auth, state
from ppxai.server import http as server_http
from ppxai.server.auth import check_request
from ppxai.server.secrets import EnvSecretProvider, FileSecretProvider, ProviderChain

POSIX = sys.platform != "win32"
TOKEN = "owned-parent-token"


def _refused(monkeypatch, capsys, *args, env_token: str | None = TOKEN) -> str:
    """Run the CLI in-process; it must exit 2 before binding anything."""
    if env_token is None:
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("PPXAI_API_TOKEN", env_token)
    monkeypatch.setattr(sys, "argv", ["ppxai-server", "--owned", *args])
    with pytest.raises(SystemExit) as exc:
        server_http.run_server()
    assert exc.value.code == 2
    return capsys.readouterr().err


class TestMisuseIsRefused:
    def test_no_parent_token(self, monkeypatch, capsys):
        assert "PPXAI_API_TOKEN" in _refused(monkeypatch, capsys, env_token=None)

    def test_an_empty_parent_token(self, monkeypatch, capsys):
        assert "PPXAI_API_TOKEN" in _refused(monkeypatch, capsys, env_token="  ")

    def test_a_wide_bind(self, monkeypatch, capsys):
        assert "loopback" in _refused(monkeypatch, capsys, "--host", "0.0.0.0")

    def test_with_uds(self, monkeypatch, capsys):
        assert "--uds" in _refused(monkeypatch, capsys, "--uds")

    def test_with_reload(self, monkeypatch, capsys):
        assert "--reload" in _refused(monkeypatch, capsys, "--reload")


class TestTheParentTokenIsHonoured:
    def test_a_file_only_chain_gets_the_env_provider_first(self, monkeypatch, tmp_path):
        chain = ProviderChain([FileSecretProvider(path=str(tmp_path / "t.json"))])
        monkeypatch.setattr(state, "_secret_provider", chain)
        server_http._force_env_token_provider()
        assert isinstance(chain.providers[0], EnvSecretProvider)
        assert len(chain.providers) == 2

    def test_an_env_provider_already_present_is_not_doubled(self, monkeypatch):
        chain = ProviderChain([EnvSecretProvider()])
        monkeypatch.setattr(state, "_secret_provider", chain)
        server_http._force_env_token_provider()
        assert len(chain.providers) == 1


def _request(method="GET", path="/", header=None) -> Request:
    return Request({
        "type": "http", "method": method, "path": path, "raw_path": path.encode(),
        "query_string": b"", "scheme": "http",
        "headers": [(b"authorization", header.encode())] if header else [],
        "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 54320),
    })


class TestNoLoopbackExemption:
    """Loopback, no bearer: exempt by default, refused on an owned server."""

    @pytest.fixture
    def owned_chain(self, monkeypatch, tmp_path):
        # A file store with a token: the default exempts loopback UI + mint here.
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        fp.mint(owner="alice")
        monkeypatch.setenv("PPXAI_API_TOKEN", TOKEN)
        monkeypatch.setattr(state, "_secret_provider",
                            ProviderChain([EnvSecretProvider(), fp]))

    @pytest.mark.parametrize("method, path", [
        ("POST", "/chat"), ("GET", "/health"), ("GET", "/status"),
        ("GET", "/"), ("POST", "/v1/oneshot"), ("POST", "/v1/tokens"),
    ])
    def test_refused_without_a_bearer(self, owned_chain, monkeypatch, method, path):
        monkeypatch.setattr(auth, "_bearer_required_everywhere", True)
        r = check_request(_request(method, path))
        assert r is not None and r.status_code == 401

    @pytest.mark.parametrize("method, path", [("POST", "/chat"), ("POST", "/v1/tokens")])
    def test_control_the_default_still_exempts_them(self, owned_chain, method, path):
        """Pins that the flag, not the fixture, is what closes them."""
        assert check_request(_request(method, path)) is None

    def test_the_parent_bearer_passes(self, owned_chain, monkeypatch):
        monkeypatch.setattr(auth, "_bearer_required_everywhere", True)
        assert check_request(_request("GET", "/health", f"Bearer {TOKEN}")) is None

    def test_cors_preflight_stays_exempt(self, owned_chain, monkeypatch):
        monkeypatch.setattr(auth, "_bearer_required_everywhere", True)
        assert check_request(_request("OPTIONS", "/chat")) is None

    def test_the_switch_sets_the_flag(self, monkeypatch):
        monkeypatch.setattr(auth, "_bearer_required_everywhere", False)
        auth.require_bearer_everywhere()
        assert auth._bearer_required_everywhere is True


class TestARealOwnedServer:
    """One subprocess through the real entry point: the line a parent reads."""

    @pytest.fixture
    def server(self):
        env = dict(os.environ, PPXAI_API_TOKEN=TOKEN)
        proc = subprocess.Popen(
            [sys.executable, "-m", "ppxai.server.http", "--owned"], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True)
        try:
            yield proc
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=30)

    def _wait_ready(self, base: str) -> None:
        for _ in range(300):
            try:
                if httpx.get(f"{base}/health", timeout=2,
                             headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.2)
        pytest.fail("owned server never answered /health")

    def test_first_stdout_line_is_the_address_and_auth_is_closed(self, server):
        line = server.stdout.readline()
        info = json.loads(line)
        assert set(info) == {"host", "port", "pid", "version"}
        assert info["host"] == "127.0.0.1" and info["port"] > 0
        # Not compared with proc.pid: a Windows venv python.exe is a redirector.
        assert isinstance(info["pid"], int) and info["pid"] > 0
        base = f"http://127.0.0.1:{info['port']}"
        self._wait_ready(base)
        assert httpx.get(f"{base}/health", timeout=5).status_code == 401
        assert httpx.post(f"{base}/chat", json={}, timeout=5).status_code == 401

    @pytest.mark.skipif(not POSIX, reason="stdin-EOF exit is POSIX only (ADR 0017)")
    def test_closing_stdin_stops_it(self, server):
        info = json.loads(server.stdout.readline())
        self._wait_ready(f"http://127.0.0.1:{info['port']}")
        server.stdin.close()
        assert server.wait(timeout=60) == 0

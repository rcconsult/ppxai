"""The desktop launcher opens the SSH hub's unlock URL when the hub is on.

Seen 2026-11-22: with `remote.hosts` configured, `ppxai-desktop` opened the
plain URL, so the SSH Launcher said "The SSH hub is locked" — the hub cookie
is set only by `/hub/auth?token=...`. The launcher (repo-root
`ppxai-desktop.py`, stdlib only) now probes `GET /hub/hosts` and, on 401/200,
opens the unlock URL with the token the server keeps on disk.
"""

from __future__ import annotations

import http.server
import importlib.util
import os
import sys
import threading
from pathlib import Path

import pytest

from ppxai.server.routes import remote_hub

_LAUNCHER = Path(__file__).resolve().parents[1] / "ppxai-desktop.py"
TOKEN = "t" * 43


@pytest.fixture()
def launcher(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("ppxai_desktop_hub", _LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(mod.Path, "home", classmethod(lambda cls: home))
    mod._test_home = home
    return mod


def _write_token(home: Path, mode: int = 0o600, text: str = TOKEN) -> Path:
    path = home.joinpath(".ppxai", "run", "hub-token")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    os.chmod(path, mode)
    return path


def _server(status: int):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler's name
            self.send_response(status if self.path == "/hub/hosts" else 404)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_the_token_path_matches_the_servers(launcher, monkeypatch):
    home = launcher._test_home
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert remote_hub.token_path() == home.joinpath(*launcher.HUB_TOKEN_RELPATH)


@pytest.mark.parametrize("status", [401, 200])
def test_a_hub_gets_the_unlock_url(launcher, status):
    _write_token(launcher._test_home)
    srv = _server(status)
    try:
        port = srv.server_address[1]
        assert launcher.hub_unlock_url(port) == \
            f"http://127.0.0.1:{port}/hub/auth?token={TOKEN}&next=/"
    finally:
        srv.shutdown()


def test_no_hub_means_the_plain_url(launcher):
    _write_token(launcher._test_home)
    srv = _server(404)
    try:
        assert launcher.hub_unlock_url(srv.server_address[1]) is None
    finally:
        srv.shutdown()


def test_no_server_means_the_plain_url(launcher):
    _write_token(launcher._test_home)
    srv = _server(401)
    port = srv.server_address[1]
    srv.shutdown()
    srv.server_close()
    assert launcher.hub_unlock_url(port) is None


def test_no_token_file_means_the_plain_url(launcher):
    srv = _server(401)
    try:
        assert launcher.hub_unlock_url(srv.server_address[1]) is None
    finally:
        srv.shutdown()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_a_group_readable_token_is_not_used(launcher):
    _write_token(launcher._test_home, mode=0o644)
    srv = _server(401)
    try:
        assert launcher.hub_unlock_url(srv.server_address[1]) is None
    finally:
        srv.shutdown()

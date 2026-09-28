"""ADR 0013 end to end: two real `ppxai-server` processes, the production code
path in between.

The hub is a real `ppxai-server` reading `remote.hosts` from a real config
file. It launches the remote -- a second real `ppxai-server --uds --announce
--detach` -- through the production `OpenSSHTransport`, whose `ssh` is a PATH
shim around `tests/fake_ssh.py` (runs commands through a real `sh`, relays
`-L` forwards). Everything else is the shipped code: loader, lifespan hook,
manager, proxy, websocket bridge, the remote's own UI and terminal.

Slow and POSIX-only (the remote contract is unix-socket only).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest
from websockets.asyncio.client import connect as ws_connect

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(sys.platform == "win32", reason="the remote side is POSIX-only"),
]

FAKE_SSH = Path(__file__).with_name("fake_ssh.py")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def hub_process(tmp_path):
    runtime = Path(tempfile.mkdtemp(prefix="ppx-e2e-", dir="/tmp"))  # short AF_UNIX paths
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    ssh = shim_dir / "ssh"
    ssh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_SSH}" "$@"\n')
    ssh.chmod(ssh.stat().st_mode | stat.S_IXUSR)
    remote_bin = shim_dir / "remote-ppxai-server"
    remote_bin.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m ppxai.server.http "$@"\n')
    remote_bin.chmod(remote_bin.stat().st_mode | stat.S_IXUSR)
    workdir = tmp_path / "proj"
    workdir.mkdir()

    config = tmp_path / "ppxai-config.json"
    base = json.loads(Path(os.environ["PPXAI_CONFIG_FILE"]).read_text(encoding="utf-8")) \
        if os.environ.get("PPXAI_CONFIG_FILE") else {"version": "1", "providers": {}}
    base["remote"] = {"hosts": [{"id": "lab", "ssh": "lab", "ppxai_server": str(remote_bin)}]}
    config.write_text(json.dumps(base), encoding="utf-8")

    port = _free_port()
    env = dict(os.environ, PATH=f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
               PPXAI_CONFIG_FILE=str(config), XDG_RUNTIME_DIR=str(runtime))
    env.pop("PPXAI_API_TOKEN", None)
    proc = subprocess.Popen([sys.executable, "-m", "ppxai.server.http", "--port", str(port)],
                            env=env, cwd=str(tmp_path), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=90)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if client.get("/health").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if proc.poll() is not None:
            raise AssertionError("hub server exited:\n" + proc.stdout.read())
        time.sleep(0.25)
    launched: list[dict] = []
    try:
        yield {"client": client, "port": port, "workdir": workdir, "launched": launched}
    finally:
        for server in launched:  # never leave a detached remote running
            try:
                os.kill(server["pid"], 15)
            except (ProcessLookupError, KeyError):
                pass
        client.close()
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        proc.stdout.close()
        shutil.rmtree(runtime, ignore_errors=True)


def test_launch_proxy_terminal_and_stop_through_a_real_hub(hub_process):
    c = hub_process["client"]
    base = f"http://127.0.0.1:{hub_process['port']}"

    hosts = c.get("/hub/hosts").json()["hosts"]
    assert [h["id"] for h in hosts] == ["lab"], "remote.hosts did not reach the hub"

    r = c.post("/hub/hosts/lab/servers", json={"workdir": str(hub_process["workdir"]),
                                               "label": "e2e"})
    assert r.status_code == 201, r.text
    server = r.json()
    hub_process["launched"].append(server)
    assert "token" not in server
    prefix = f"/h/lab/{server['id']}"

    # The remote's own web UI, served through the proxy (auto-attach).
    page = c.get(f"{prefix}/")
    assert page.status_code == 200, page.text[:300]
    assert "APP_STATE_SCHEMA" in page.text, "not the ppxai web UI"

    health = c.get(f"{prefix}/health").json()
    assert health["status"] == "healthy"
    assert c.get("/hub/hosts").json()["hosts"][0]["attachments"][0]["state"] == "healthy"

    # The remote's terminal, through the websocket bridge.
    async def terminal():
        async with ws_connect(f"ws://127.0.0.1:{hub_process['port']}{prefix}/ws/terminal",
                              origin=base, proxy=None) as ws:
            await ws.send(json.dumps({"type": "input", "data": "echo HUB-$((6*7))\n"}))
            out = ""
            deadline = time.monotonic() + 15
            while "HUB-42" not in out and time.monotonic() < deadline:
                message = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if isinstance(message.get("data"), str):
                    out += message["data"]
            return out
    assert "HUB-42" in asyncio.run(terminal())

    r = c.post(f"/hub/hosts/lab/servers/{server['id']}/stop", json={})
    assert r.status_code == 200, r.text
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        listed = c.get("/hub/hosts/lab/servers").json()["servers"]
        if server["id"] not in [s["id"] for s in listed]:
            break
        time.sleep(0.5)
    else:
        raise AssertionError("the remote was still announced 30s after stop")
    hub_process["launched"].clear()

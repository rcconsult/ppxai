"""ADR 0013 Phase 4 -- S5, the hub proxy and its control API.

Two real uvicorn servers per run, no ssh and no network:

- a **fake remote** (a small Starlette app standing in for a remote
  ppxai-server) on a unix socket or a loopback port -- the two shapes a real
  forward's local end takes;
- the **hub** (the real `remote_hub` router) on a loopback port, with a
  `RemoteSessionManager` whose transport is `FakeTransport`: listing returns
  one entry, and `forward()` returns the fake remote's endpoint. Health
  checks, the proxy and the websocket bridge all run for real.

Real servers rather than TestClient because the point of several tests is
streaming: the test client collects a response before handing it over, so
it cannot tell an unbuffered SSE stream from a buffered one.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import InvalidStatus

from ppxai.remote import LocalEndpoint, RemoteSessionManager, RunResult
from ppxai.remote.manager import _DEFAULT_CANDIDATES, _DISCOVER_SCRIPT
from ppxai.server.routes import remote_hub
from tests.remote_fakes import FakeTransport

TOKEN = "remote-token-7f3a"
SID = "9f2c0000aaaa1111"          # healthy
SID_BAD_TOKEN = "9f2c0000bbbb2222"  # its entry carries a token the remote refuses
BIN = "/home/u/.local/bin/ppxai-server"


# ---------------------------------------------------------------------------
# The fake remote
# ---------------------------------------------------------------------------

class RemoteLog:
    def __init__(self):
        self.requests: list[dict] = []
        self.shutdowns = 0


def _fake_remote(log: RemoteLog) -> Starlette:
    def authed(request) -> bool:
        return request.headers.get("authorization") == f"Bearer {TOKEN}"

    async def health(request: Request):
        return JSONResponse({"status": "healthy"}) if authed(request) else \
            JSONResponse({"detail": "no"}, status_code=401)

    async def echo(request: Request):
        body = await request.body()
        seen = {"method": request.method, "path": request.url.path,
                "query": request.url.query, "headers": dict(request.headers),
                "body_len": len(body), "body_sha": hashlib.sha256(body).hexdigest()}
        log.requests.append(seen)
        if not authed(request):
            return JSONResponse({"detail": "no"}, status_code=401)
        return JSONResponse(seen)

    async def sse(request: Request):
        async def events():
            yield b"data: one\n\n"
            await asyncio.sleep(1.2)
            yield b"data: two\n\n"
        return StreamingResponse(events(), media_type="text/event-stream")

    async def redirect(request: Request):
        return RedirectResponse("/target?x=1", status_code=307)

    async def cookies(request: Request):
        response = PlainTextResponse("ok")
        response.raw_headers.append((b"set-cookie", b"a=1; Path=/"))
        response.raw_headers.append((b"set-cookie", b"b=2; Path=/sub; HttpOnly"))
        return response

    async def shutdown(request: Request):
        log.shutdowns += 1
        return JSONResponse({"shutdown": True})

    async def ws_echo(websocket):
        if websocket.headers.get("authorization") != f"Bearer {TOKEN}":
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                text = await websocket.receive_text()
                await websocket.send_text("echo:" + text)
        except Exception:
            pass

    return Starlette(routes=[
        Route("/health", health),
        Route("/echo", echo, methods=["GET", "POST", "PUT", "DELETE"]),
        Route("/sse", sse),
        Route("/redirect", redirect),
        Route("/cookies", cookies),
        Route("/shutdown", shutdown, methods=["POST"]),
        WebSocketRoute("/ws/echo", ws_echo),
    ])


class Served:
    """A uvicorn server on a daemon thread."""

    def __init__(self, app, *, uds: str | None = None):
        config = uvicorn.Config(app, uds=uds, host="127.0.0.1", port=0,
                                log_level="warning", lifespan="on", ws="websockets")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 20
        while not self.server.started:
            if time.monotonic() > deadline or not self.thread.is_alive():
                raise RuntimeError("uvicorn did not start")
            time.sleep(0.02)
        self.uds = uds
        self.port = None if uds else self.server.servers[0].sockets[0].getsockname()[1]

    def endpoint(self) -> LocalEndpoint:
        return LocalEndpoint("uds", self.uds) if self.uds else \
            LocalEndpoint("tcp", f"127.0.0.1:{self.port}")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(15)


def _entry(sid, token):
    return {"contract": 2, "id": sid, "pid": 4242, "socket": f"/r/{sid}.sock",
            "token": token, "version": "1.19.4", "app_state_schema": "1.1",
            "workdir": "/home/u/src", "started_at": "2026-09-28T10:00:00Z", "label": None}


class HubRig:
    def __init__(self, remote_endpoint: LocalEndpoint):
        self.runs: dict = {}
        self.forwards: dict = {}
        self.made: list[FakeTransport] = []
        self.runs[("sh", "-c", _DISCOVER_SCRIPT, "sh", *_DEFAULT_CANDIDATES)] = \
            [RunResult(0, BIN + "\n", "")]
        self.runs[(BIN, "--list", "--json")] = [RunResult(0, json.dumps(
            [_entry(SID, TOKEN), _entry(SID_BAD_TOKEN, "stale-token")]), "")]
        self.forwards[f"/r/{SID}.sock"] = [remote_endpoint]
        self.forwards[f"/r/{SID_BAD_TOKEN}.sock"] = [remote_endpoint]

    def factory(self, hosts):
        def transport(host):
            t = FakeTransport(runs=self.runs, forwards=self.forwards)
            self.made.append(t)
            return t
        return RemoteSessionManager(hosts, transport_factory=transport)

    def run_calls(self):
        return [argv for t in self.made for argv, _ in t.run_calls]


def _hub_app(rig: HubRig) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        await remote_hub.start_hub({"hosts": [{"id": "gpu01", "ssh": "gpu01"}]},
                                   manager_factory=rig.factory, monitor_interval_s=3600)
        yield
        await remote_hub.stop_hub()

    app = FastAPI(lifespan=lifespan)
    app.include_router(remote_hub.router)
    return app


KINDS = ["tcp"] + ([] if sys.platform == "win32" else ["uds"])


@pytest.fixture(scope="module", params=KINDS)
def env(request):
    log = RemoteLog()
    sock_dir = None
    if request.param == "uds":
        sock_dir = tempfile.mkdtemp(prefix="ppx-hub-", dir="/tmp")
        remote = Served(_fake_remote(log), uds=os.path.join(sock_dir, "r.sock"))
    else:
        remote = Served(_fake_remote(log))
    rig = HubRig(remote.endpoint())
    hub_server = Served(_hub_app(rig))
    base = f"http://127.0.0.1:{hub_server.port}"
    client = httpx.Client(base_url=base, trust_env=False, timeout=15)
    yield {"client": client, "base": base, "log": log, "rig": rig, "port": hub_server.port}
    client.close()
    hub_server.stop()
    remote.stop()
    if sock_dir:
        shutil.rmtree(sock_dir, ignore_errors=True)


P = f"/h/gpu01/{SID}"


# ---------------------------------------------------------------------------
# The proxy
# ---------------------------------------------------------------------------

class TestProxy:
    def test_path_query_and_the_injected_token(self, env):
        r = env["client"].get(f"{P}/echo?a=1&b=two", headers={
            "cookie": "session=browser", "authorization": "Bearer browser-token",
            "referer": "http://127.0.0.1/x", "x-session-id": "s-1"})
        assert r.status_code == 200, r.text
        seen = r.json()
        assert (seen["path"], seen["query"]) == ("/echo", "a=1&b=two")
        headers = seen["headers"]
        assert headers["authorization"] == f"Bearer {TOKEN}"
        assert headers["host"] == "localhost"
        assert headers["x-session-id"] == "s-1", "application headers pass through"
        for dropped in ("cookie", "referer", "origin", "x-forwarded-for", "forwarded"):
            assert dropped not in headers, dropped

    def test_the_token_never_reaches_the_browser(self, env):
        r = env["client"].get(f"{P}/echo")
        assert TOKEN not in json.dumps(dict(r.headers))
        hosts = env["client"].get("/hub/hosts").text
        servers = env["client"].get("/hub/hosts/gpu01/servers").text
        assert TOKEN not in hosts and TOKEN not in servers

    def test_a_large_post_body_arrives_intact(self, env):
        body = os.urandom(2 * 1024 * 1024)
        r = env["client"].post(f"{P}/echo", content=body,
                               headers={"origin": env["base"], "content-type": "application/octet-stream"})
        assert r.status_code == 200, r.text
        assert r.json()["body_len"] == len(body)
        assert r.json()["body_sha"] == hashlib.sha256(body).hexdigest()

    def test_sse_is_streamed_not_buffered(self, env):
        started = time.monotonic()
        with env["client"].stream("GET", f"{P}/sse") as r:
            chunks = r.iter_raw()
            first = next(chunks)
            first_at = time.monotonic() - started
            rest = b"".join(chunks)
        assert b"data: one" in first
        assert b"data: two" in rest
        assert first_at < 1.0, f"first event took {first_at:.2f}s: the proxy buffered the stream"
        assert r.headers["content-type"].startswith("text/event-stream")

    def test_a_relative_redirect_stays_inside_the_prefix(self, env):
        r = env["client"].get(f"{P}/redirect", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == f"{P}/target?x=1"

    def test_every_cookie_survives_with_its_path_prefixed(self, env):
        r = env["client"].get(f"{P}/cookies")
        cookies = r.headers.get_list("set-cookie")
        assert cookies == [f"a=1; Path={P}/", f"b=2; Path={P}/sub; HttpOnly"]

    def test_the_bare_prefix_redirects_to_the_trailing_slash(self, env):
        r = env["client"].get(f"{P}?q=1", follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == f"{P}/?q=1"

    def test_the_websocket_is_bridged(self, env):
        async def go():
            async with ws_connect(f"ws://127.0.0.1:{env['port']}{P}/ws/echo",
                                  origin=env["base"], proxy=None) as ws:
                await ws.send("hi")
                return await asyncio.wait_for(ws.recv(), 5)
        assert asyncio.run(go()) == "echo:hi"

    def test_a_dead_forward_is_a_502_not_a_hang(self, env, monkeypatch):
        # A port the OS just handed out and we released: connects are refused
        # at once. Not a well-known "closed" port: Windows' optional Simple
        # TCP/IP Services listens on 9 and never answers, so the proxy hangs.
        # (Holding a bound, unlistened socket instead refuses on Linux but
        # makes macOS sit out the 10 s connect timeout.)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        dead = LocalEndpoint("tcp", f"127.0.0.1:{port}")
        hub_ = remote_hub.hub()
        monkeypatch.setattr(hub_.manager, "route", lambda h, s: (dead, TOKEN))
        r = env["client"].get(f"{P}/echo")
        assert r.status_code == 502 and r.json()["error"] == "remote_unreachable"


class TestRefusals:
    def test_a_cross_site_write_is_refused(self, env):
        r = env["client"].post(f"{P}/echo", content=b"x", headers={"origin": "http://evil.example"})
        assert r.status_code == 403

    def test_a_same_site_fetch_marker_is_refused(self, env):
        r = env["client"].post(f"{P}/echo", content=b"x", headers={"sec-fetch-site": "same-site"})
        assert r.status_code == 403

    def test_a_cross_site_websocket_is_refused(self, env):
        async def go():
            async with ws_connect(f"ws://127.0.0.1:{env['port']}{P}/ws/echo",
                                  origin="http://evil.example", proxy=None):
                pass
        with pytest.raises(InvalidStatus) as exc:
            asyncio.run(go())
        assert exc.value.response.status_code == 403

    def test_a_forwarded_request_is_not_loopback_and_sees_nothing(self, env):
        r = env["client"].get(f"{P}/echo", headers={"x-forwarded-for": "203.0.113.9"})
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
        assert env["client"].get("/hub/hosts", headers={"forwarded": "for=1.2.3.4"}).status_code == 404

    @pytest.mark.parametrize("path", ["/h/nope/9f2c0000aaaa1111/echo",
                                      "/h/GPU01/9f2c0000aaaa1111/echo",
                                      "/h/gpu01/bad!id/echo"])
    def test_unknown_hosts_and_bad_ids_never_reach_ssh(self, env, path):
        before = len(env["rig"].run_calls())
        r = env["client"].get(path)
        assert r.status_code == 404
        assert len(env["rig"].run_calls()) == before

    def test_a_degraded_server_is_a_503_with_retry_after(self, env):
        r = env["client"].get(f"/h/gpu01/{SID_BAD_TOKEN}/echo")
        assert r.status_code == 503
        assert r.headers["retry-after"] == "5"
        assert r.json()["state"] == "degraded"


class TestObserveOnly:
    """`X-Ppxai-Hub-Attach: no` (the SSH Launcher's count reads) never attaches.

    Found live (2026-09-28): a launcher refresh whose host list predated a
    Detach read counts through the proxy afterwards, and auto-attach undid
    the Detach."""

    NO = {"x-ppxai-hub-attach": "no"}

    def _attached(self, env):
        hosts = env["client"].get("/hub/hosts").json()["hosts"]
        return {a["server_id"] for h in hosts for a in h["attachments"]}

    def test_a_detached_server_stays_detached(self, env):
        c = env["client"]
        c.post(f"/hub/hosts/gpu01/servers/{SID}/detach", json={})
        r = c.get(f"{P}/echo", headers=self.NO)
        assert r.status_code == 503 and r.headers["retry-after"] == "5"
        assert SID not in self._attached(env)

    def test_an_attached_server_answers_and_the_header_stays_local(self, env):
        c = env["client"]
        assert c.post(f"/hub/hosts/gpu01/servers/{SID}/attach", json={}).json()["state"] == "healthy"
        r = c.get(f"{P}/echo", headers=self.NO)
        assert r.status_code == 200, r.text
        assert "x-ppxai-hub-attach" not in r.json()["headers"]

    def test_any_other_value_still_auto_attaches(self, env):
        c = env["client"]
        c.post(f"/hub/hosts/gpu01/servers/{SID}/detach", json={})
        assert c.get(f"{P}/echo", headers={"x-ppxai-hub-attach": "yes"}).status_code == 200
        assert SID in self._attached(env)


class TestControlApi:
    def test_hosts_lists_the_inventory(self, env):
        hosts = env["client"].get("/hub/hosts").json()["hosts"]
        assert [h["id"] for h in hosts] == ["gpu01"]

    def test_servers_lists_public_entries(self, env):
        body = env["client"].get("/hub/hosts/gpu01/servers").json()
        assert {s["id"] for s in body["servers"]} == {SID, SID_BAD_TOKEN}
        assert all("token" not in s for s in body["servers"])

    def test_an_unknown_host_is_404(self, env):
        assert env["client"].get("/hub/hosts/nope/servers").status_code == 404

    def test_a_control_post_needs_json(self, env):
        r = env["client"].post(f"/hub/hosts/gpu01/servers/{SID}/attach", content=b"{}",
                               headers={"content-type": "text/plain"})
        assert r.status_code == 415

    def test_a_cross_site_control_post_is_refused(self, env):
        r = env["client"].post(f"/hub/hosts/gpu01/servers/{SID}/attach", json={},
                               headers={"origin": "http://evil.example"})
        assert r.status_code == 403

    def test_attach_then_detach_leaves_the_server_running(self, env):
        c = env["client"]
        shutdowns = env["log"].shutdowns
        assert c.post(f"/hub/hosts/gpu01/servers/{SID}/attach", json={}).json()["state"] == "healthy"
        assert c.post(f"/hub/hosts/gpu01/servers/{SID}/detach", json={}).json()["ok"] is True
        assert env["log"].shutdowns == shutdowns

    def test_stop_asks_the_remote_to_shut_down(self, env):
        shutdowns = env["log"].shutdowns
        r = env["client"].post(f"/hub/hosts/gpu01/servers/{SID}/stop", json={})
        assert r.status_code == 200 and r.json()["ok"] is True
        assert env["log"].shutdowns == shutdowns + 1

    def test_an_unknown_action_is_404(self, env):
        assert env["client"].post(f"/hub/hosts/gpu01/servers/{SID}/reboot", json={}).status_code == 404

"""ADR 0013 S5 -- the hub: remote ppxai servers under `/h/<host>/<server-id>/`.

The local `ppxai-server` becomes a hub when `remote.hosts` names at least one
host (ADR 0013 Q1). It then reverse-proxies `/h/<host>/<id>/...` to that
remote server's SSH forward, and exposes a small control API under `/hub/`
for the picker (S6):

    GET  /hub/hosts                                  hosts + attachments
    GET  /hub/hosts/<host>/servers                   the host's announced servers
    POST /hub/hosts/<host>/servers                   launch {"workdir"?, "label"?}
    POST /hub/hosts/<host>/servers/<id>/attach|detach|stop

**Off means absent.** With no `remote.hosts`, every hub path answers exactly
as an unknown path does today (404 `{"detail": "Not Found"}`; a websocket is
refused), no manager exists and no `ssh` is ever started. The k8s coder pods
have no `remote` block, so nothing changes for them; tests/
test_remote_hub_coder_fence.py pins that.

**Loopback only.** The hub hands out shells on other machines, so it answers
only a direct loopback peer (no forwarding headers), and anything that
changes state -- a proxied non-GET, a websocket, a control POST -- must also
be same-origin: `Origin`, when present, must equal this server's own origin,
and `Sec-Fetch-Site` must not say cross-site. A non-loopback or cross-site
request sees the same 404/403 as if the hub were off.

**Proxy rules (S5):** streamed both ways, never buffered (SSE, chunked
bodies, uploads); websockets bridged; the remote's bearer token injected from
its registry entry and never sent to the browser; `Host: localhost`; the
browser's `Authorization`, `Cookie`, `Origin`, `Referer` and forwarding
headers dropped. Bodies are never rewritten; a relative `Location` and a
cookie `Path` get the `/h/<host>/<id>` prefix so they stay inside it.

**Auto-attach** happens on a proxied request to a server that has no
attachment, so a reload after a hub restart works. A caller that only
OBSERVES (the SSH Launcher reading session/run counts) sends
`X-Ppxai-Hub-Attach: no` and gets the 503 instead: otherwise a read made from
a snapshot taken just before a Detach would silently re-attach the server.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Callable, Sequence
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from starlette.requests import HTTPConnection
from websockets.asyncio.client import connect as ws_connect
from websockets.asyncio.client import unix_connect as ws_unix_connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from ...remote import (
    InventoryError,
    LocalEndpoint,
    MalformedEntryError,
    RemoteHost,
    RemoteHubError,
    RemoteSessionManager,
    RemoteTransportError,
    ServerNotInstalledError,
    State,
    StateChange,
    UnknownContractError,
    UnknownHostError,
    UnknownServerError,
    UnsupportedServerError,
    parse_hosts,
)
from ...remote.contract import SERVER_ID_RE
from ...remote.inventory import HOST_ID_RE
from ..auth import _is_loopback

logger = logging.getLogger(__name__)

router = APIRouter()

ManagerFactory = Callable[[Sequence[RemoteHost]], RemoteSessionManager]

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_PROXY_METHODS = ["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"]

# A request carrying `X-Ppxai-Hub-Attach: no` never attaches (module doc).
_NO_ATTACH_HEADER = "x-ppxai-hub-attach"

# Never forwarded upstream: hop-by-hop headers, the browser's own
# credentials and identity, and anything that would make the remote think the
# request was proxied (its Host check and loopback rules then pass unchanged).
_DROP_UPSTREAM = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "transfer-encoding", "upgrade", "host",
    "authorization", "cookie", "origin", "referer", "forwarded",
    "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
    "x-forwarded-port", "x-forwarded-prefix", "x-real-ip",
    _NO_ATTACH_HEADER,
})
_DROP_DOWNSTREAM = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "transfer-encoding", "upgrade",
})
_COOKIE_PATH_RE = re.compile(r"(?i)(;\s*path=)(/[^;]*)")

_UPSTREAM_TIMEOUT = httpx.Timeout(10.0, read=None, write=None, pool=None)


class Hub:
    """The manager plus one pooled HTTP client per attached server.

    ADR 0013 Q4 measured ~120 ms per new SSH channel against ~6-60 ms on a
    reused one, so connections to a forward are kept alive and reused.
    """

    def __init__(self, manager: RemoteSessionManager):
        self.manager = manager
        self._clients: dict[tuple[str, str], tuple[LocalEndpoint, httpx.AsyncClient]] = {}
        self._unsubscribe = manager.subscribe(self._on_change)

    def client_for(self, host: str, server_id: str, endpoint: LocalEndpoint) -> httpx.AsyncClient:
        key = (host, server_id)
        current = self._clients.get(key)
        if current is not None and current[0] == endpoint:
            return current[1]
        if current is not None:
            self._retire(current[1])
        if endpoint.kind == "uds":
            transport = httpx.AsyncHTTPTransport(uds=endpoint.address)
            base = "http://localhost"
        else:
            transport = httpx.AsyncHTTPTransport()
            base = f"http://{endpoint.address}"
        client = httpx.AsyncClient(transport=transport, base_url=base,
                                   timeout=_UPSTREAM_TIMEOUT, trust_env=False)
        self._clients[key] = (endpoint, client)
        return client

    def _on_change(self, change: StateChange) -> None:
        if change.state is not State.HEALTHY:
            current = self._clients.pop((change.host, change.server_id), None)
            if current is not None:
                self._retire(current[1])

    @staticmethod
    def _retire(client: httpx.AsyncClient) -> None:
        with contextlib.suppress(RuntimeError):  # no running loop: nothing to close on
            asyncio.get_running_loop().create_task(client.aclose())

    def host_ids(self) -> set[str]:
        return {h["id"] for h in self.manager.hosts()}

    async def close(self) -> None:
        self._unsubscribe()
        clients, self._clients = self._clients, {}
        for _, client in clients.values():
            with contextlib.suppress(Exception):
                await client.aclose()
        await self.manager.close()


_hub: Hub | None = None


def hub() -> Hub | None:
    return _hub


async def start_hub(remote_config, *, manager_factory: ManagerFactory | None = None,
                    monitor_interval_s: float = 5.0) -> Hub | None:
    """Turn the hub on if `remote.hosts` names any host. Never raises.

    A malformed `remote` block is logged and leaves the hub off: a config
    mistake must not stop the server from starting.
    """
    global _hub
    if _hub is not None:
        return _hub
    try:
        hosts = parse_hosts(remote_config)
    except InventoryError as exc:
        logger.error(f"remote.hosts is invalid, remote hub disabled: {exc}")
        print(f"Remote hub: disabled -- {exc}")
        return None
    if not hosts:
        return None
    factory = manager_factory or (lambda hs: RemoteSessionManager(hs))
    manager = factory(hosts)
    manager.start_monitor(monitor_interval_s)
    _hub = Hub(manager)
    names = ", ".join(h.id for h in hosts)
    logger.info(f"Remote hub enabled for {len(hosts)} host(s): {names}")
    print(f"Remote hub: {names} (under /h/<host>/<server>/)")
    return _hub


async def stop_hub() -> None:
    """Drop every forward. Remote servers keep running (detach, not stop)."""
    global _hub
    current, _hub = _hub, None
    if current is not None:
        with contextlib.suppress(Exception):
            await current.close()


# -- gates ------------------------------------------------------------------

def _not_found() -> JSONResponse:
    # Byte-identical to Starlette's own 404 for an unknown path.
    return JSONResponse({"detail": "Not Found"}, status_code=404)


def _gate(conn: HTTPConnection) -> Hub | None:
    """The hub, if it is on and this is a direct loopback peer; else None."""
    if _hub is None or not _is_loopback(conn):
        return None
    return _hub


def _cross_site(conn: HTTPConnection) -> bool:
    if conn.headers.get("sec-fetch-site", "").lower() in ("cross-site", "same-site"):
        return True
    origin = conn.headers.get("origin")
    if origin is None:
        return False  # not a browser request
    netloc = urlsplit(origin).netloc.lower()
    return not netloc or netloc != (conn.headers.get("host") or "").strip().lower()


def _error(exc: Exception) -> JSONResponse:
    if isinstance(exc, (UnknownHostError, UnknownServerError)):
        status = 404
    elif isinstance(exc, (UnsupportedServerError, ServerNotInstalledError,
                          UnknownContractError, MalformedEntryError)):
        status = 409
    else:
        status = 502
    return JSONResponse({"error": type(exc).__name__, "detail": str(exc)}, status_code=status)


# -- control API ------------------------------------------------------------

@router.get("/hub/hosts")
async def hub_hosts(request: Request):
    hub_ = _gate(request)
    if hub_ is None:
        return _not_found()
    return {"hosts": hub_.manager.hosts()}


@router.get("/hub/hosts/{host}/servers")
async def hub_servers(request: Request, host: str):
    hub_ = _gate(request)
    if hub_ is None:
        return _not_found()
    try:
        listing = await hub_.manager.servers(host)
    except (RemoteHubError, RemoteTransportError) as exc:
        return _error(exc)
    return {"servers": [s.public() for s in listing.servers], "refused": listing.refused}


def _control_refusal(request: Request) -> JSONResponse | None:
    if _cross_site(request):
        return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
    if not request.headers.get("content-type", "").startswith("application/json"):
        # Forces a CORS preflight for any browser caller.
        return JSONResponse({"detail": "Content-Type must be application/json"}, status_code=415)
    return None


@router.post("/hub/hosts/{host}/servers")
async def hub_launch(request: Request, host: str):
    hub_ = _gate(request)
    if hub_ is None:
        return _not_found()
    refusal = _control_refusal(request)
    if refusal is not None:
        return refusal
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return JSONResponse({"detail": "body must be a JSON object"}, status_code=400)
    workdir, label = body.get("workdir"), body.get("label")
    for name, value in (("workdir", workdir), ("label", label)):
        if value is not None and (not isinstance(value, str) or "\n" in value or "\x00" in value):
            return JSONResponse({"detail": f"{name} must be a single-line string"}, status_code=400)
    try:
        server = await hub_.manager.launch(host, workdir=workdir or None, label=label or None)
    except (RemoteHubError, RemoteTransportError) as exc:
        return _error(exc)
    return JSONResponse(server.public(), status_code=201)


@router.post("/hub/hosts/{host}/servers/{server_id}/{action}")
async def hub_action(request: Request, host: str, server_id: str, action: str):
    hub_ = _gate(request)
    if hub_ is None or action not in ("attach", "detach", "stop"):
        return _not_found()
    refusal = _control_refusal(request)
    if refusal is not None:
        return refusal
    try:
        if action == "attach":
            return await hub_.manager.attach(host, server_id)
        if action == "detach":
            await hub_.manager.detach(host, server_id)
        else:
            await hub_.manager.stop(host, server_id)
    except (RemoteHubError, RemoteTransportError) as exc:
        return _error(exc)
    return {"host": host, "server_id": server_id, "action": action, "ok": True}


# -- the proxy --------------------------------------------------------------

def _prefix(host: str, server_id: str) -> str:
    return f"/h/{host}/{server_id}"


async def _route(hub_: Hub, host: str, server_id: str, *, may_attach: bool = True):
    """(endpoint, token) for a healthy attachment -- attaching on first use
    unless `may_attach` is False -- or the JSONResponse to send instead."""
    if not HOST_ID_RE.match(host) or host not in hub_.host_ids() \
            or not SERVER_ID_RE.match(server_id):
        return _not_found()
    route = hub_.manager.route(host, server_id)
    if route is not None:
        return route
    if may_attach and hub_.manager.attachment(host, server_id) is None:
        try:
            await hub_.manager.attach(host, server_id)
        except (RemoteHubError, RemoteTransportError) as exc:
            return _error(exc)
        route = hub_.manager.route(host, server_id)
        if route is not None:
            return route
    view = hub_.manager.attachment(host, server_id) or {}
    state = view.get("state", "disconnected")
    return JSONResponse(
        {"detail": f"{host}/{server_id} is {state}", "state": state, "why": view.get("detail")},
        status_code=503, headers={"Retry-After": "5"})


def _upstream_headers(request: Request, token: str) -> list[tuple[str, str]]:
    headers = [(k, v) for k, v in request.headers.items() if k.lower() not in _DROP_UPSTREAM]
    headers.append(("Host", "localhost"))
    headers.append(("Authorization", f"Bearer {token}"))
    return headers


def _downstream_headers(upstream: httpx.Response, prefix: str) -> list[tuple[str, str]]:
    out = []
    for key, value in upstream.headers.multi_items():
        lower = key.lower()
        if lower in _DROP_DOWNSTREAM:
            continue
        if lower == "location" and value.startswith("/") and not value.startswith("//"):
            value = prefix + value
        elif lower == "set-cookie":
            value = _COOKIE_PATH_RE.sub(lambda m: m.group(1) + prefix + m.group(2), value)
        out.append((key, value))
    return out


@router.get("/h/{host}/{server_id}")
async def proxy_root_redirect(request: Request, host: str, server_id: str):
    """`/h/<host>/<id>` -> `/h/<host>/<id>/`: the remote UI's relative URLs
    only resolve inside the prefix with the trailing slash."""
    if _gate(request) is None:
        return _not_found()
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"{_prefix(host, server_id)}/{query}", status_code=307)


@router.api_route("/h/{host}/{server_id}/{path:path}", methods=_PROXY_METHODS)
async def proxy_http(request: Request, host: str, server_id: str, path: str):
    hub_ = _gate(request)
    if hub_ is None:
        return _not_found()
    if request.method not in _SAFE_METHODS and _cross_site(request):
        return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
    may_attach = request.headers.get(_NO_ATTACH_HEADER, "").strip().lower() != "no"
    route = await _route(hub_, host, server_id, may_attach=may_attach)
    if isinstance(route, Response):
        return route
    endpoint, token = route
    client = hub_.client_for(host, server_id, endpoint)
    url = "/" + path + (f"?{request.url.query}" if request.url.query else "")
    has_body = request.method not in ("GET", "HEAD") or "content-length" in request.headers \
        or "transfer-encoding" in request.headers
    upstream_request = client.build_request(
        request.method, url, headers=_upstream_headers(request, token),
        content=request.stream() if has_body else None)
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        logger.warning(f"hub: {host}/{server_id} {request.method} /{path} failed: {exc!r}")
        return JSONResponse({"error": "remote_unreachable",
                             "detail": f"{host}/{server_id} did not answer: {type(exc).__name__}"},
                            status_code=502)
    response = StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code,
                                 background=BackgroundTask(upstream.aclose))
    # raw_headers, not a dict: a repeated header (Set-Cookie) must survive.
    response.raw_headers = [
        (k.encode("latin-1"), v.encode("latin-1"))
        for k, v in _downstream_headers(upstream, _prefix(host, server_id))]
    return response


@router.websocket("/h/{host}/{server_id}/{path:path}")
async def proxy_websocket(websocket: WebSocket, host: str, server_id: str, path: str):
    hub_ = _gate(websocket)
    if hub_ is None or _cross_site(websocket):
        await websocket.close(code=1008)
        return
    route = await _route(hub_, host, server_id)
    if isinstance(route, Response):
        await websocket.close(code=1008 if route.status_code == 404 else 1011)
        return
    endpoint, token = route
    query = f"?{websocket.url.query}" if websocket.url.query else ""
    headers = [("Authorization", f"Bearer {token}")]
    try:
        if endpoint.kind == "uds":
            upstream = await ws_unix_connect(endpoint.address, uri=f"ws://localhost/{path}{query}",
                                             additional_headers=headers, proxy=None)
        else:
            upstream = await ws_connect(f"ws://{endpoint.address}/{path}{query}",
                                        additional_headers=headers, proxy=None)
    except (OSError, WebSocketException, asyncio.TimeoutError) as exc:
        logger.warning(f"hub: websocket {host}/{server_id} /{path} failed: {exc!r}")
        await websocket.close(code=1011)
        return
    await websocket.accept()

    async def to_browser():
        async for message in upstream:
            if isinstance(message, str):
                await websocket.send_text(message)
            else:
                await websocket.send_bytes(message)

    async def to_remote():
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("text") is not None:
                await upstream.send(message["text"])
            elif message.get("bytes") is not None:
                await upstream.send(message["bytes"])

    tasks = [asyncio.create_task(to_browser()), asyncio.create_task(to_remote())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, ConnectionClosed, RuntimeError):
                await task
        with contextlib.suppress(Exception):
            await upstream.close()
        with contextlib.suppress(Exception):
            await websocket.close()

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

**Hub token (Jupyter model).** Loopback alone is not a credential: any local
process, any OS user, is a loopback peer. So every `/hub/*` and `/h/*` request
(all methods, and the websocket) must also carry the hub token, as the
`ppxai_hub` cookie or the `X-Ppxai-Hub-Token` header. The token lives in
`~/.ppxai/run/hub-token` (0600, directory 0700), is created on first use and
kept across restarts, and is printed by `ppxai-server` as
`/hub/auth?token=...`: opening that URL sets the cookie (HttpOnly,
SameSite=Strict) and redirects. The token and the cookie are never forwarded
to a remote, and a remote cannot set a cookie of that name. The check order
is: hub off -> 404, non-loopback -> 404, then auth -> 401.

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
import hmac
import logging
import os
import re
import secrets
import stat
import sys
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
from .. import registry
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
    _NO_ATTACH_HEADER, "x-ppxai-hub-token",
})
_DROP_DOWNSTREAM = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "transfer-encoding", "upgrade",
})

HUB_COOKIE = "ppxai_hub"
HUB_TOKEN_HEADER = "x-ppxai-hub-token"
_COOKIE_MAX_AGE_S = 30 * 24 * 3600
_LOCKED_HINT = ("open the hub URL printed by ppxai-server (.../hub/auth?token=...), "
                "or send X-Ppxai-Hub-Token from ~/.ppxai/run/hub-token")
_COOKIE_PATH_RE = re.compile(r"(?i)(;\s*path=)(/[^;]*)")

_UPSTREAM_TIMEOUT = httpx.Timeout(10.0, read=None, write=None, pool=None)
# `read=None` keeps SSE streams and long bodies open, but alone it lets a remote
# that accepts and never answers hold a request forever. This bounds only the
# wait for the response HEADERS. A plain `/v1/oneshot` sends none until its
# provider call returns, and the OpenAI SDK's read timeout is 600 s, so the
# deadline sits past that: the remote's own provider error (a 502 with its
# message) arrives first, and only a wedged remote meets this 504.
_UPSTREAM_HEADERS_TIMEOUT_S = 660.0


def token_path():
    return registry.run_dir() / "hub-token"


def _reusable(path) -> str | None:
    """The token in `path`, if it is a regular file this user owns with no
    group/other access (POSIX; on Windows the profile ACL decides)."""
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            return None
        if sys.platform != "win32" and (st.st_uid != os.getuid() or st.st_mode & 0o077):
            return None
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text if len(text) >= 32 and text.isascii() and text.isprintable() \
        and not any(c.isspace() for c in text) else None


def load_hub_token() -> str:
    """The hub token: reuse the file's, or create it atomically (0600 from
    creation, temp + rename). Idempotent; never deleted on stop."""
    path = token_path()
    existing = _reusable(path)
    if existing is not None:
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(path.parent, 0o700)
    token = secrets.token_urlsafe(32)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with contextlib.suppress(FileNotFoundError):
        tmp.unlink()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    os.replace(tmp, path)
    return token


def hub_enabled(remote_config) -> bool:
    """Would `start_hub` turn the hub on for this `remote` block?"""
    try:
        return bool(parse_hosts(remote_config))
    except InventoryError:
        return False


def hub_auth_url(host: str, port: int, remote_config, *, next_path: str | None = None) -> str | None:
    """`http://<host>:<port>/hub/auth?token=...` when the hub will be on, else None."""
    if not hub_enabled(remote_config):
        return None
    shown = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    if ":" in shown:
        shown = f"[{shown}]"
    url = f"http://{shown}:{port}/hub/auth?token={load_hub_token()}"
    return url + (f"&next={next_path}" if next_path else "")


class Hub:
    """The manager plus one pooled HTTP client per attached server.

    ADR 0013 Q4 measured ~120 ms per new SSH channel against ~6-60 ms on a
    reused one, so connections to a forward are kept alive and reused.
    """

    def __init__(self, manager: RemoteSessionManager, token: str):
        self.manager = manager
        self.token = token
        self._clients: dict[tuple[str, str], tuple[LocalEndpoint, httpx.AsyncClient]] = {}
        self._unsubscribe = manager.subscribe(self._on_change)

    def client_for(self, host: str, server_id: str, endpoint: LocalEndpoint) -> httpx.AsyncClient:
        key = (host, server_id)
        current = self._clients.get(key)
        if current is not None and current[0] == endpoint:
            return current[1]
        if current is not None:
            self._retire(current[1])
        # trust_env=False on the TRANSPORT too: the client's flag does not
        # reach a transport passed in, and a transport that trusts the env
        # loads SSL_CERT_FILE at construction -- a missing file made every
        # proxied request a 500, though this hop is plain HTTP.
        if endpoint.kind == "uds":
            transport = httpx.AsyncHTTPTransport(uds=endpoint.address, trust_env=False)
            base = "http://localhost"
        else:
            transport = httpx.AsyncHTTPTransport(trust_env=False)
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
                    monitor_interval_s: float = 5.0, token: str | None = None) -> Hub | None:
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
    hub_token = token or load_hub_token()
    manager = factory(hosts)
    manager.start_monitor(monitor_interval_s)
    _hub = Hub(manager, hub_token)
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


def _presented(conn: HTTPConnection) -> list[str]:
    out = [conn.cookies.get(HUB_COOKIE, ""), conn.headers.get(HUB_TOKEN_HEADER, "")]
    return [v for v in out if v]


def _authorized(conn: HTTPConnection, hub_: Hub) -> bool:
    expected = hub_.token.encode("utf-8")
    ok = False
    for value in _presented(conn):
        # No short-circuit: every presented value is compared.
        try:
            ok |= hmac.compare_digest(value.encode("utf-8"), expected)
        except UnicodeEncodeError:
            pass
    return ok


def _locked() -> JSONResponse:
    return JSONResponse({"detail": "hub_auth_required", "hint": _LOCKED_HINT}, status_code=401)


def _guard(conn: HTTPConnection) -> Hub | JSONResponse:
    """The hub for an authenticated loopback request, else the response to send."""
    hub_ = _gate(conn)
    if hub_ is None:
        return _not_found()
    if not _authorized(conn, hub_):
        return _locked()
    return hub_


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

def _safe_next(value: str | None) -> str:
    """`value` if it is a same-origin relative path, else "/"."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in value):
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return "/"
    return value


@router.get("/hub/auth")
async def hub_auth(request: Request, token: str = "", next: str = "/"):
    """Exchange the hub token for the cookie (the only unauthenticated hub path)."""
    hub_ = _gate(request)
    if hub_ is None:
        return _not_found()
    try:
        good = hmac.compare_digest(token.encode("utf-8"), hub_.token.encode("utf-8"))
    except UnicodeEncodeError:
        good = False
    if not good:
        return _locked()
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(HUB_COOKIE, hub_.token, max_age=_COOKIE_MAX_AGE_S, path="/",
                        httponly=True, samesite="strict", secure=False)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/hub/hosts")
async def hub_hosts(request: Request):
    hub_ = _guard(request)
    if isinstance(hub_, Response):
        return hub_
    return {"hosts": hub_.manager.hosts()}


@router.get("/hub/hosts/{host}/servers")
async def hub_servers(request: Request, host: str):
    hub_ = _guard(request)
    if isinstance(hub_, Response):
        return hub_
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
    hub_ = _guard(request)
    if isinstance(hub_, Response):
        return hub_
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
    hub_ = _guard(request)
    if isinstance(hub_, Response):
        return hub_
    if action not in ("attach", "detach", "stop"):
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
            if value.split("=", 1)[0].strip().lower() == HUB_COOKIE:
                continue  # a remote cannot set, clear or shadow the hub cookie
            value = _COOKIE_PATH_RE.sub(lambda m: m.group(1) + prefix + m.group(2), value)
        out.append((key, value))
    return out


@router.get("/h/{host}/{server_id}")
async def proxy_root_redirect(request: Request, host: str, server_id: str):
    """`/h/<host>/<id>` -> `/h/<host>/<id>/`: the remote UI's relative URLs
    only resolve inside the prefix with the trailing slash."""
    denied = _guard(request)
    if isinstance(denied, Response):
        return denied
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"{_prefix(host, server_id)}/{query}", status_code=307)


@router.api_route("/h/{host}/{server_id}/{path:path}", methods=_PROXY_METHODS)
async def proxy_http(request: Request, host: str, server_id: str, path: str):
    hub_ = _guard(request)
    if isinstance(hub_, Response):
        return hub_
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
        upstream = await asyncio.wait_for(client.send(upstream_request, stream=True),
                                          timeout=_UPSTREAM_HEADERS_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.warning(f"hub: {host}/{server_id} {request.method} /{path} sent no response "
                       f"headers in {_UPSTREAM_HEADERS_TIMEOUT_S:g}s")
        return JSONResponse({"error": "remote_timeout",
                             "detail": f"{host}/{server_id} accepted the request but sent no "
                                       f"response in {_UPSTREAM_HEADERS_TIMEOUT_S:g}s"},
                            status_code=504)
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
    if hub_ is None or not _authorized(websocket, hub_) or _cross_site(websocket):
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

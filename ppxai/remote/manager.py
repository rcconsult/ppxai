"""S4 -- `RemoteSessionManager`, the hub's view of remote servers (ADR 0013).

It lists the announced servers on each configured host, launches new ones,
and holds a forward to every server the user attached. Each attachment runs
the ADR's state machine::

    disconnected --connect--> connecting --forward ok--> tunneled --/health ok--> healthy
          ^                       |                          |                      |
          |                transport error              health fails          health fails
          +------------ close <---+--------------------------+-----> degraded <-----+
                                                                   (retry with backoff)

plus one terminal state the ADR's 2026-09-26 trial asked for: **gone** -- the
server is no longer in the host's registry (stopped, crashed, rebooted).
That is a normal end, not a fault, so it is not `degraded`.

Rules that are the point of this module:

- **Detach never stops a server.** `detach()` drops the forward and leaves
  the remote running; `stop()` is the only verb that ends one, and it asks
  the server itself (`POST /shutdown`) -- never a signal to a pid, which on a
  PyInstaller binary is the launcher, not the server.
- **Every transition is an event** (`subscribe()`), so the picker (S6)
  renders state instead of polling for it.
- **A token never leaves this module in a public shape.** `public()` views
  omit it; S5's proxy asks for it explicitly.

It moves bytes and never interprets a chat: nothing here imports the engine
or the command layer (Guard 3b in tests/test_no_new_lazy_imports.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

from .contract import (
    MalformedEntryError,
    RemoteServer,
    ServerNotInstalledError,
    UnknownContractError,
    UnknownHostError,
    UnknownServerError,
    UnsupportedServerError,
    parse_contract,
    parse_entry,
    upgrade_hint,
)
from .inventory import RemoteHost
from .openssh import OpenSSHTransport
from .transport import (
    LocalEndpoint,
    RemoteCommandFailedError,
    RemoteTransport,
    RemoteTransportError,
)

logger = logging.getLogger(__name__)


class State(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    TUNNELED = "tunneled"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    GONE = "gone"


#: Every legal transition. Anything else is a bug in this module.
ALLOWED_TRANSITIONS: dict[State, frozenset[State]] = {
    State.DISCONNECTED: frozenset({State.CONNECTING}),
    State.CONNECTING: frozenset({State.TUNNELED, State.DISCONNECTED, State.DEGRADED}),
    State.TUNNELED: frozenset({State.HEALTHY, State.DEGRADED, State.DISCONNECTED}),
    State.HEALTHY: frozenset({State.DEGRADED, State.DISCONNECTED, State.GONE}),
    State.DEGRADED: frozenset({State.CONNECTING, State.GONE, State.DISCONNECTED}),
    State.GONE: frozenset(),
}


@dataclass(frozen=True)
class StateChange:
    host: str
    server_id: str
    previous: State
    state: State
    detail: str | None = None


#: `(endpoint, token, method, path) -> HTTP status`, 0 when nothing answered.
HttpRequester = Callable[[LocalEndpoint, str, str, str], Awaitable[int]]
TransportFactory = Callable[[RemoteHost], RemoteTransport]
Listener = Callable[[StateChange], None]

_HTTP_TIMEOUT_S = 5.0


async def http_request(endpoint: LocalEndpoint, token: str, method: str, path: str) -> int:
    """One request through a forward, named as `localhost` with the server's
    bearer token -- the S5 header rules, applied to the hub's own probes."""
    if endpoint.kind == "uds":
        transport = httpx.AsyncHTTPTransport(uds=endpoint.address)
        base = "http://localhost"
    else:
        transport = None
        base = f"http://{endpoint.address}"
    headers = {"Authorization": f"Bearer {token}", "Host": "localhost"}
    try:
        # trust_env=False: an HTTP(S)_PROXY in the environment must never
        # route a request meant for a local forward through a proxy.
        async with httpx.AsyncClient(transport=transport, timeout=_HTTP_TIMEOUT_S,
                                     trust_env=False) as client:
            response = await client.request(method, base + path, headers=headers)
            return response.status_code
    except (httpx.HTTPError, OSError):
        return 0


@dataclass(frozen=True)
class ServerListing:
    """`servers(host)`: readable entries, plus one message per refused entry."""

    servers: list[RemoteServer]
    refused: list[str] = field(default_factory=list)


@dataclass
class _Attachment:
    server: RemoteServer
    state: State = State.DISCONNECTED
    endpoint: LocalEndpoint | None = None
    transport: RemoteTransport | None = None
    detail: str | None = None
    failures: int = 0
    next_retry_at: float = 0.0

    def public(self) -> dict[str, Any]:
        return {"host": self.server.host, "server_id": self.server.id,
                "state": self.state.value, "detail": self.detail,
                "server": self.server.public()}


# Finds ppxai-server on the remote: the configured path, else the login
# PATH, else the documented install location. A leading `~/` is the remote
# $HOME (the argv is quoted, so the shell would not expand it itself).
_DISCOVER_SCRIPT = (
    'for c in "$@"; do '
    'case $c in "~/"*) c="$HOME/${c#"~/"}";; esac; '
    'if command -v "$c" >/dev/null 2>&1; then command -v "$c"; exit 0; fi; '
    "done; exit 127"
)
_DEFAULT_CANDIDATES = ("ppxai-server", "~/.local/bin/ppxai-server")

# `cd` into the workdir (tilde = remote $HOME), then exec the launch argv.
_CD_EXEC_SCRIPT = (
    'd=$1; shift; '
    'case $d in "~") d=$HOME;; "~/"*) d="$HOME/${d#"~/"}";; esac; '
    'cd -- "$d" && exec "$@"'
)


class RemoteSessionManager:
    def __init__(
        self,
        hosts: Sequence[RemoteHost],
        *,
        transport_factory: TransportFactory | None = None,
        http: HttpRequester = http_request,
        clock: Callable[[], float] = time.monotonic,
        run_timeout_s: float = 30.0,
        launch_timeout_s: float = 90.0,
        retry_base_s: float = 1.0,
        retry_max_s: float = 30.0,
    ):
        self._hosts = {h.id: h for h in hosts}
        self._factory = transport_factory or (lambda h: OpenSSHTransport(h.ssh))
        self._http = http
        self._clock = clock
        self._run_timeout_s = run_timeout_s
        self._launch_timeout_s = launch_timeout_s
        self._retry_base_s = retry_base_s
        self._retry_max_s = retry_max_s
        self._control: dict[str, RemoteTransport] = {}
        self._binary: dict[str, str] = {}
        self._host_error: dict[str, str | None] = {}
        self._attachments: dict[tuple[str, str], _Attachment] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._listeners: list[Listener] = []
        self._monitor: asyncio.Task[None] | None = None

    # -- events -----------------------------------------------------------

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Call `listener` on every transition; returns an unsubscribe."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def _transition(self, att: _Attachment, state: State, detail: str | None = None) -> None:
        previous = att.state
        if state not in ALLOWED_TRANSITIONS[previous]:
            raise AssertionError(f"illegal transition {previous.value} -> {state.value}")
        att.state = state
        att.detail = detail
        change = StateChange(att.server.host, att.server.id, previous, state, detail)
        for listener in list(self._listeners):
            try:
                listener(change)
            except Exception:  # a broken listener must not break the hub
                logger.exception("remote state listener failed")

    # -- hosts and commands ----------------------------------------------

    def _host(self, host_id: str) -> RemoteHost:
        host = self._hosts.get(host_id)
        if host is None:
            raise UnknownHostError(f"no remote host {host_id!r} in remote.hosts")
        return host

    def hosts(self) -> list[dict[str, Any]]:
        """Configured hosts, the last transport error seen on each, and
        the attachments to each (public shapes, no tokens)."""
        return [{
            "id": h.id, "ssh": h.ssh, "error": self._host_error.get(h.id),
            "attachments": [a.public() for (hid, _), a in self._attachments.items()
                            if hid == h.id],
        } for h in self._hosts.values()]

    async def _run(self, host: RemoteHost, argv: list[str], timeout: float):
        transport = self._control.get(host.id)
        if transport is None:
            transport = self._control[host.id] = self._factory(host)
        try:
            result = await transport.run(argv, timeout=timeout)
        except RemoteTransportError as exc:
            self._host_error[host.id] = str(exc)
            raise
        self._host_error[host.id] = None
        return result

    async def _resolve_binary(self, host: RemoteHost) -> str:
        if host.id in self._binary:
            return self._binary[host.id]
        candidates = [host.ppxai_server] if host.ppxai_server else list(_DEFAULT_CANDIDATES)
        result = await self._run(host, ["sh", "-c", _DISCOVER_SCRIPT, "sh", *candidates],
                                 self._run_timeout_s)
        path = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        if result.rc != 0 or not path:
            raise ServerNotInstalledError(
                f"{host.id}: ppxai-server not found (looked for {', '.join(candidates)}); "
                "install ppxai there or set ppxai_server for this host")
        self._binary[host.id] = path
        return path

    async def _server_version(self, host: RemoteHost, binary: str) -> str:
        probe = await self._run(host, [binary, "--version"], self._run_timeout_s)
        if probe.rc == 0 and probe.stdout.strip():
            return probe.stdout.strip().split()[-1]
        return "of an unknown version"

    async def _refuse_if_unsupported(self, host: RemoteHost, binary: str, result) -> None:
        """A non-zero `--list`/`--uds`/`--registry-contract`: an old server
        (argparse's usage error, exit 2) is refused by name and version (ADR
        0013 Q5); anything else is a plain command failure. Classified on
        the exit code alone: a wrapper may print the usage to stdout."""
        if result.rc == 2:
            version = await self._server_version(host, binary)
            raise UnsupportedServerError(
                f"{host.id}: ppxai-server {version} cannot be driven by this hub; "
                f"{upgrade_hint(host.id)}")
        result.check()

    async def _check_contract(self, host: RemoteHost, binary: str) -> None:
        """Refuse a remote whose server this hub cannot use BEFORE starting
        one: a server that writes a retired contract would start, answer
        /health, and then fail every chat. Not cached: the remote binary can
        be upgraded while the hub runs."""
        result = await self._run(host, [binary, "--registry-contract"], self._run_timeout_s)
        if result.rc != 0:
            await self._refuse_if_unsupported(host, binary, result)
        try:
            contract = int(result.stdout.strip())
        except ValueError:
            raise MalformedEntryError(
                f"{host.id}: --registry-contract did not print a number") from None
        parse_contract(host.id, contract, f"ppxai-server at {binary}")

    async def servers(self, host_id: str) -> ServerListing:
        """The host's live announced servers (S3 `--list --json`)."""
        host = self._host(host_id)
        binary = await self._resolve_binary(host)
        result = await self._run(host, [binary, "--list", "--json"], self._run_timeout_s)
        if result.rc != 0:
            await self._refuse_if_unsupported(host, binary, result)
        try:
            raw = json.loads(result.stdout)
        except ValueError:
            raise MalformedEntryError(f"{host.id}: --list --json did not print JSON") from None
        if not isinstance(raw, list):
            raise MalformedEntryError(f"{host.id}: --list --json did not print a list")
        listing = ServerListing([])
        for entry in raw:
            try:
                listing.servers.append(parse_entry(host.id, entry))
            except (UnknownContractError, MalformedEntryError) as exc:
                listing.refused.append(str(exc))
        return listing

    async def launch(self, host_id: str, workdir: str | None = None,
                     label: str | None = None) -> RemoteServer:
        """Start a detached announced server on the host and return its entry."""
        host = self._host(host_id)
        binary = await self._resolve_binary(host)
        await self._check_contract(host, binary)
        argv = [binary, "--uds", "--announce", "--detach"]
        if label:
            argv += ["--label", label]
        if workdir:
            argv = ["sh", "-c", _CD_EXEC_SCRIPT, "sh", workdir, *argv]
        result = await self._run(host, argv, self._launch_timeout_s)
        payload: Any = None
        with contextlib.suppress(ValueError):
            payload = json.loads(result.stdout)
        if result.rc != 0:
            if isinstance(payload, dict) and payload.get("error"):
                raise RemoteCommandFailedError(
                    f"{host.id}: ppxai-server refused to start: {payload['error']}",
                    stderr=result.stderr, rc=result.rc)
            await self._refuse_if_unsupported(host, binary, result)
        if payload is None:
            raise MalformedEntryError(f"{host.id}: the launch did not print its registry entry")
        return parse_entry(host.id, payload)

    # -- attachments -----------------------------------------------------

    def _lock(self, key: tuple[str, str]) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    def attachment(self, host_id: str, server_id: str) -> dict[str, Any] | None:
        att = self._attachments.get((host_id, server_id))
        return att.public() if att else None

    def route(self, host_id: str, server_id: str) -> tuple[LocalEndpoint, str] | None:
        """For S5's proxy: the forward's endpoint and the bearer token to
        inject, or None unless the attachment is healthy."""
        att = self._attachments.get((host_id, server_id))
        if att is None or att.state is not State.HEALTHY or att.endpoint is None:
            return None
        return att.endpoint, att.server.token

    async def _find(self, host_id: str, server_id: str) -> RemoteServer:
        for server in (await self.servers(host_id)).servers:
            if server.id == server_id:
                return server
        raise UnknownServerError(f"{host_id}: no live announced server {server_id!r}")

    async def attach(self, host_id: str, server_id: str) -> dict[str, Any]:
        """Forward to the server and health-check it. Re-attaching is a no-op.

        A forward that cannot be set up leaves nothing behind and raises; a
        forward that works but whose `/health` fails is kept as `degraded`
        and retried by the monitor.
        """
        key = (host_id, server_id)
        async with self._lock(key):
            existing = self._attachments.get(key)
            if existing is not None:
                return existing.public()
            att = _Attachment(await self._find(host_id, server_id))
            await self._connect(att, initial=True)
            self._attachments[key] = att
            return att.public()

    async def _connect(self, att: _Attachment, *, initial: bool) -> None:
        self._transition(att, State.CONNECTING)
        transport = self._factory(self._host(att.server.host))
        try:
            endpoint = await transport.forward(att.server.socket)
        except RemoteTransportError as exc:
            await transport.close()
            if initial:
                self._transition(att, State.DISCONNECTED, str(exc))
                raise
            self._degrade(att, str(exc))
            return
        att.transport, att.endpoint = transport, endpoint
        self._transition(att, State.TUNNELED)
        status = await self._http(endpoint, att.server.token, "GET", "/health")
        if status == 200:
            att.failures = 0
            self._transition(att, State.HEALTHY)
        else:
            self._degrade(att, f"/health answered {status or 'nothing'}")

    def _degrade(self, att: _Attachment, detail: str) -> None:
        delay = min(self._retry_max_s, self._retry_base_s * (2 ** att.failures))
        att.failures += 1
        att.next_retry_at = self._clock() + delay
        self._transition(att, State.DEGRADED, detail)

    async def _drop_forward(self, att: _Attachment) -> None:
        transport, att.transport, att.endpoint = att.transport, None, None
        if transport is not None:
            with contextlib.suppress(RemoteTransportError, OSError):
                await transport.close()

    async def detach(self, host_id: str, server_id: str) -> None:
        """Drop the forward. The remote server keeps running."""
        key = (host_id, server_id)
        async with self._lock(key):
            att = self._attachments.pop(key, None)
            if att is None:
                return
            await self._drop_forward(att)
            self._transition(att, State.DISCONNECTED, "detached")

    async def stop(self, host_id: str, server_id: str) -> None:
        """Ask the server to shut down (`POST /shutdown`), then forget it.

        Attaches first if needed -- the request goes through the server's
        own forward, never as a signal to a pid.
        """
        if (host_id, server_id) not in self._attachments:
            await self.attach(host_id, server_id)
        key = (host_id, server_id)
        async with self._lock(key):
            att = self._attachments.get(key)
            if att is None:
                return
            if att.state is not State.HEALTHY or att.endpoint is None:
                raise RemoteCommandFailedError(
                    f"{host_id}: server {server_id} is {att.state.value}; "
                    "it cannot be asked to stop right now")
            status = await self._http(att.endpoint, att.server.token, "POST", "/shutdown")
            if status != 200:
                raise RemoteCommandFailedError(
                    f"{host_id}: server {server_id} did not accept /shutdown "
                    f"(answered {status or 'nothing'})")
            self._attachments.pop(key, None)
            await self._drop_forward(att)
            self._transition(att, State.GONE, "stopped")

    # -- monitoring ------------------------------------------------------

    async def tick(self) -> None:
        """One monitoring pass: probe healthy attachments, retry degraded ones
        whose backoff has elapsed."""
        for key in list(self._attachments):
            async with self._lock(key):
                att = self._attachments.get(key)
                if att is None:
                    continue
                if att.state is State.HEALTHY and att.endpoint is not None:
                    status = await self._http(att.endpoint, att.server.token, "GET", "/health")
                    if status != 200:
                        att.failures = 0
                        self._degrade(att, f"/health answered {status or 'nothing'}")
                elif att.state is State.DEGRADED and self._clock() >= att.next_retry_at:
                    await self._recover(key, att)

    async def _recover(self, key: tuple[str, str], att: _Attachment) -> None:
        try:
            listing = await self.servers(att.server.host)
        except (RemoteTransportError, UnknownHostError, UnsupportedServerError,
                ServerNotInstalledError, MalformedEntryError) as exc:
            self._degrade_again(att, str(exc))
            return
        fresh = next((s for s in listing.servers if s.id == att.server.id), None)
        await self._drop_forward(att)
        if fresh is None:
            self._attachments.pop(key, None)
            self._transition(att, State.GONE, "no longer in the host's registry")
            return
        att.server = fresh
        await self._connect(att, initial=False)

    def _degrade_again(self, att: _Attachment, detail: str) -> None:
        """Still degraded, with a longer wait. (Not a transition: the state
        does not change, so no event -- only the detail and the backoff.)"""
        delay = min(self._retry_max_s, self._retry_base_s * (2 ** att.failures))
        att.failures += 1
        att.next_retry_at = self._clock() + delay
        att.detail = detail

    def start_monitor(self, interval_s: float = 5.0) -> None:
        if self._monitor is not None and not self._monitor.done():
            return

        async def loop() -> None:
            while True:
                try:
                    await self.tick()
                except Exception:
                    logger.exception("remote monitor pass failed")
                await asyncio.sleep(interval_s)

        self._monitor = asyncio.create_task(loop())

    async def close(self) -> None:
        """Stop monitoring and drop every forward. Remote servers keep running."""
        if self._monitor is not None:
            self._monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor
            self._monitor = None
        for host_id, server_id in list(self._attachments):
            await self.detach(host_id, server_id)
        control, self._control = self._control, {}
        for transport in control.values():
            with contextlib.suppress(RemoteTransportError, OSError):
                await transport.close()

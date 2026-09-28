"""
FastAPI HTTP Server with SSE streaming for ppxai.

This module creates the FastAPI app, manages its lifespan, and registers
all route modules. Route handlers are defined in ppxai/server/routes/.

Usage:
    uv run ppxai-server
    uv run ppxai-server --port 8080
    uv run ppxai-server --host 0.0.0.0 --port 8080
"""

import argparse
import asyncio
import concurrent.futures
import json
import logging
import os
import signal
import sys
import threading
import time

# Backward-compat proxy: tests do `http_module.session_manager = mock_manager`.
# We need reads/writes of `session_manager` on this module to proxy through to
# the state module so route handlers (which import from state) see the same value.
import types as _types  # noqa: E402
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import ppxai.config.loader as _loader

from ..common.logger import get_logger
from ..config import get_idle_timeout, get_shutdown_grace_s, initialize
from ..version import __version__
from . import registry
from . import state as _state  # noqa: F401 — backing store for session_manager
from .auth import check_request as _auth_check_request
from .routes import all_routers
from .secrets import EnvSecretProvider
from .session_manager import SessionManager

# Re-export for backward compatibility (tests, PyInstaller specs, entry points)
from .state import (  # noqa: F401
    all_preview_backends,
    get_agent_run_registry,
    get_or_create_session,
    get_secret_provider,
    get_server_start_time,
    is_path_allowed,
    kill_preview_backend,
    remove_preview_backend,
    set_server_start_time,
    set_session_manager,
    set_shutdown_event,
    update_activity,
)
from .streaming import sse_coding_task_generator, sse_event_generator  # noqa: F401

_this = sys.modules[__name__]
_original_getattr = None


def __getattr__(name):
    if name == "session_manager":
        return _state.session_manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Intercept `http_module.session_manager = X` and forward to state module
_orig_class = type(_this)
if _orig_class is _types.ModuleType:
    class _ProxyModule(_types.ModuleType):
        def __setattr__(self, name, value):
            if name == "session_manager":
                _state.session_manager = value
                return
            super().__setattr__(name, value)

        def __getattr__(self, name):
            if name == "session_manager":
                return _state.session_manager
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    _this.__class__ = _ProxyModule

# Server logger (v1.11.2)
logger = get_logger("server")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 54320


def _format_uptime(seconds: float) -> str:
    """Format uptime in human-readable format."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"


async def http_consent_handler(file_path: str) -> tuple[bool, str]:
    """Handle file edit consent request via HTTP (Phase 1C: v1.11.0)."""
    return await _state.session_manager._handle_consent("default", file_path)


async def http_shell_consent_handler(command: str, working_dir: str, risk_level: str) -> tuple[bool, str]:
    """Handle shell command consent request via HTTP (v1.11.2)."""
    return await _state.session_manager._handle_shell_consent("default", command, working_dir, risk_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan (startup/shutdown).

    v1.13.10: Refactored to use SessionManager for thread-safe state management.
    v1.13.10: Added graceful shutdown via _shutdown_event.
    v1.13.10: Added startup/shutdown logging with uptime tracking.
    """
    startup_start = time.time()

    # Initialize shutdown event for graceful termination (v1.13.10)
    _shutdown_event = asyncio.Event()
    set_shutdown_event(_shutdown_event)

    # Initialize SessionManager singleton (v1.13.10)
    logger.info("Server starting up - initializing SessionManager")
    sm = SessionManager.get_instance()
    set_session_manager(sm)

    # Initialize with consent callbacks
    await sm.initialize(
        consent_callback=http_consent_handler,
        shell_consent_callback=http_shell_consent_handler
    )

    default_engine = sm.default_engine
    logger.info(f"EngineClient initialized - provider: {default_engine.provider_name}, model: {default_engine.model}")
    logger.info("Session management initialized (v1.13.10, v1.13.10 thread-safe)")

    # Start idle shutdown monitor (v1.13.10). An announced server (ADR 0013)
    # overrides it to 0: a remote server that exits after 5 idle minutes
    # would vanish from the hub's view on its own.
    idle_timeout = (get_idle_timeout() if _IDLE_TIMEOUT_OVERRIDE is None
                    else _IDLE_TIMEOUT_OVERRIDE)

    def idle_shutdown_callback():
        """Callback to trigger graceful shutdown from idle monitor."""
        if _shutdown_event:
            _shutdown_event.set()

    await sm.start_idle_monitor(idle_timeout, idle_shutdown_callback)

    # Build the run registry now, not on the first /v1 call: building it runs
    # the restart sweep, so runs this host's previous server left `running`
    # read `interrupted` from the moment the server is up. The sweep skips
    # runs another live server owns (RunMeta.server_pid).
    get_agent_run_registry()

    startup_time = time.time() - startup_start
    set_server_start_time(time.time())

    # Log startup with timestamp
    start_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"Server started at {start_timestamp} (startup took {startup_time:.2f}s)")
    print(f"ppxai HTTP server started ({startup_time:.2f}s)")
    print(f"Provider: {default_engine.provider_name}")
    print(f"Model: {default_engine.model}")
    print("Session isolation: enabled (X-Session-Id header)")
    if idle_timeout > 0:
        print(f"Auto-shutdown: {idle_timeout // 60} minutes of inactivity")
    else:
        print("Auto-shutdown: disabled")

    yield

    # Shutdown: Kill preview backends (v1.17.1)
    for sid, backend in list(all_preview_backends().items()):
        logger.info(f"Stopping preview backend for session {sid} (pid {backend.process.pid})")
        await kill_preview_backend(backend)
        remove_preview_backend(sid)

    # Shutdown: Cleanup via SessionManager (v1.13.10)
    uptime = time.time() - get_server_start_time()
    uptime_str = _format_uptime(uptime)
    shutdown_reason = sm.shutdown_reason if sm else "unknown"
    stop_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"Server stopped at {stop_timestamp} (uptime: {uptime_str}, reason: {shutdown_reason})")
    logger.info("Server shutting down - cleaning up SessionManager")
    await sm.shutdown()
    global _stopped_line
    _stopped_line = f"ppxai HTTP server stopped (uptime: {uptime_str}, reason: {shutdown_reason})"
    if not _serving_via_entry_point:
        print(_stopped_line)  # TestClient etc.: nothing else will print it


# Create FastAPI app with lifespan
app = FastAPI(
    title="ppxai HTTP Server",
    description="HTTP + SSE server for ppxai AI chat",
    version=__version__,
    lifespan=lifespan,
)

# Local-transport security (debt (u), v1.19.x) ------------------------------
# By default the server is a LOOPBACK transport for the local clients (Rich /
# Textual TUI, web, VSCode). Two controls stop a malicious website — or a
# DNS-rebinding attacker — from driving the local engine over 127.0.0.1:
#   * CORS is restricted to the app's own loopback origins, NOT "*". The old
#     `allow_origins=["*"] + allow_credentials=True` made Starlette REFLECT any
#     Origin (it can't legally send `*` with credentials), i.e. it trusted every
#     website the user visited — combined with default-off auth, any page could
#     script credentialed calls to the engine.
#   * Host-header validation rejects a request whose Host isn't a loopback name
#     (anti-rebinding), UNLESS the operator bound the server wide (gateway/k8s)
#     and declared its real host(s).
# Both are overridable by env for the gateway/coder deployment (which binds
# 0.0.0.0 and fronts the server with its own ingress auth — see docs and
# deploy/). Desktop needs no env: the secure loopback default applies. The
# wiring is intentionally non-breaking: a WIDE bind with no PPXAI_TRUSTED_HOSTS
# stays permissive (pre-(u) behavior) + warns, so upgrading the server image
# alone never 400s an existing gateway before its env is set.

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_HEALTH_PATHS = frozenset({"/health", "/healthz"})

# Effective bind host, set by run_server()/run_desktop() before serving so the
# Host-validation middleware can relax for a deliberately-wide bind. Defaults to
# the loopback bind (secure) for any path that never sets it (tests, embedding).
_BIND_HOST = DEFAULT_HOST
_warned_wide_bind = False


def _set_bind_host(host: str) -> None:
    global _BIND_HOST
    _BIND_HOST = (host or DEFAULT_HOST).strip()


def _env_list(name: str) -> list:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


def _cors_kwargs() -> dict:
    """CORS origins: explicit PPXAI_ALLOWED_ORIGINS, else loopback-any-port.

    The desktop web UI is same-origin with the server, so CORS never blocks it,
    while a third-party website is refused (no wildcard reflection). A gateway
    with a genuinely cross-origin browser client sets PPXAI_ALLOWED_ORIGINS to
    its UI origin(s).
    """
    origins = _env_list("PPXAI_ALLOWED_ORIGINS")
    if "*" in origins:
        # A literal "*" combined with allow_credentials=True (set below) makes
        # Starlette REFLECT any Origin — the exact wildcard-reflection hole the
        # loopback default exists to close. Fail closed: drop the wildcard,
        # keep any explicit origins, and say so loudly.
        logger.warning(
            'PPXAI_ALLOWED_ORIGINS contains "*", which would reflect ANY '
            "origin with credentials enabled - ignoring the wildcard. "
            "List the UI origin(s) explicitly instead."
        )
        origins = [o for o in origins if o != "*"]
    if origins:
        return {"allow_origins": origins}
    return {"allow_origin_regex": r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$"}


def _host_allowlist() -> "set | None":
    """Allowed HTTP Host names, or None to accept any (permissive).

    - Always includes loopback (+ "testserver" under pytest so the Starlette
      TestClient default Host passes).
    - PPXAI_TRUSTED_HOSTS extends it; "*" disables validation (returns None).
    - Loopback bind      -> loopback (+ extras): strict — the desktop default.
    - Wide bind + extras -> loopback + extras: the hardened gateway/coder case.
    - Wide bind, no extras -> None (permissive) + one-time warn: preserves
      pre-(u) behavior so a server-image-only upgrade never breaks a gateway.
    """
    extras = _env_list("PPXAI_TRUSTED_HOSTS")
    if "*" in extras:
        return None
    base = set(_LOOPBACK_HOSTS)
    if "pytest" in sys.modules:
        base.add("testserver")
    if _BIND_HOST in _LOOPBACK_HOSTS or extras:
        return base | set(extras)
    global _warned_wide_bind
    if not _warned_wide_bind:
        _warned_wide_bind = True
        logger.warning(
            f"Server bound to non-loopback host {_BIND_HOST!r} without "
            "PPXAI_TRUSTED_HOSTS - Host-header validation DISABLED (permissive). "
            "Set PPXAI_TRUSTED_HOSTS to your external host(s) to enable "
            "anti-rebinding protection."
        )
    return None


# Add CORS middleware for webview/browser access
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Session-Id"],  # Allow clients to see session ID
    **_cors_kwargs(),
)


@app.exception_handler(Exception)
async def log_unhandled_route_error(request: Request, exc: Exception):
    """Write every exception that escapes a route to ppxai's OWN log (v1.19.2).

    Before this, such an exception reached only uvicorn's stderr. The debug
    log at ~/.ppxai/logs showed the request line and then nothing, and the
    client saw a bare "Internal Server Error" -- the Windows /preview 500
    (a backslash path handed to FileResponse) had to be diagnosed from the
    browser console instead of the log this project keeps for exactly that.

    Starlette runs this inside its `except` block and RE-RAISES after the
    response is sent, so uvicorn's own logging and TestClient's
    `raise_server_exceptions` are unchanged. The traceback goes to the log;
    the wire body stays generic -- a gateway deployment must not leak
    internals to the client.
    """
    logger.error(
        f"Unhandled {type(exc).__name__} on {request.method} {request.url.path}: {exc}",
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "detail": (
                "Internal server error. The traceback is in the ppxai log "
                "(enable it with /debug-log on)."
            ),
        },
    )



@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Bearer-token auth gate (v1.18.3).

    No-op when `PPXAI_API_TOKEN` is unset. Returns 401 with
    `WWW-Authenticate: Bearer ...` when set and the request is
    missing/malformed/wrong-token. OPTIONS preflight is exempted.

    See ppxai/server/auth.py and docs/api-gateway.md for the policy.
    """
    rejected = _auth_check_request(request)
    if rejected is not None:
        return rejected
    return await call_next(request)


@app.middleware("http")
async def activity_tracking_middleware(request: Request, call_next):
    """Track client activity for idle shutdown (v1.13.10).

    Also intercepts 404s from preview iframes: when a previewed HTML page
    makes API calls (e.g. fetch('/tasks')), they hit ppxai's server instead
    of the user's backend. Return a helpful JSON error so the user sees
    "preview-only" instead of a confusing ppxai 404.

    Skips WebSocket upgrade requests — they bypass HTTP middleware.
    """
    # Skip WebSocket upgrades — they must not be intercepted by HTTP middleware
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)

    update_activity()
    response = await call_next(request)

    if response.status_code == 404:
        referer = request.headers.get("referer", "")
        if "/preview/" in referer:
                    return JSONResponse(
                status_code = 404,
                content = {
                    "error": "preview_only",
                    "detail": (
                        f"Route '{request.url.path}' does not exist on ppxai's server. "
                        f"The preview serves static HTML only — start your backend "
                        f"separately to handle API calls."
                    ),
                },
            )

    return response


@app.middleware("http")
async def host_validation_middleware(request: Request, call_next):
    """Anti-DNS-rebinding Host check (debt (u)).

    Defined LAST so it is the OUTERMOST http middleware — a bad Host is rejected
    before auth / activity do any work. Exemptions:
      * CORS preflight (OPTIONS) — let CORSMiddleware decide the origin; blocking
        preflight here would mask the real (origin) reason.
      * kubelet liveness/readiness probes hit `/health` with Host=<pod IP>, which
        isn't in the allowlist — same footgun class as the (v) NetworkPolicy
        probe rule. Exempt the health paths so a hardened gateway pod stays Ready.
    Permissive (`_host_allowlist()` -> None) short-circuits to no check.
    """
    if request.method != "OPTIONS" and request.url.path not in _HEALTH_PATHS:
        allowed = _host_allowlist()
        if allowed is not None:
            raw = (request.headers.get("host") or "").strip()
            # Strip port; handle IPv6 literal "[::1]:port" -> "::1".
            host = raw.rsplit(":", 1)[0] if raw.count(":") <= 1 else raw
            if host.startswith("[") and "]" in host:
                host = host[1:host.index("]")]
            host = host.strip().lower()
            if host and host not in allowed:
                            return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_host",
                        "detail": (
                            f"Host {host!r} is not allowed. This server accepts "
                            "loopback Hosts by default; set PPXAI_TRUSTED_HOSTS for "
                            "a non-loopback (gateway) deployment."
                        ),
                    },
                )
    return await call_next(request)


# Register all route modules
for router in all_routers:
    app.include_router(router)


# === CLI Entry Point ===

def _forwarded_allow_ips() -> str:
    """Which proxy IPs uvicorn trusts for ``X-Forwarded-*`` (client-IP rewrite).

    Default ``""`` — trust NO proxy — so ``request.client.host`` is always the
    real TCP peer. This closes a loopback-auth bypass: with uvicorn's default
    ``proxy_headers=True`` + ``forwarded_allow_ips=127.0.0.1``, a server behind a
    LOCAL reverse proxy would let a client-supplied ``X-Forwarded-For: 127.0.0.1``
    rewrite ``client.host`` to loopback, spoofing the bootstrap/desktop
    exemptions (see server/auth.py::_is_loopback). Operators genuinely behind a
    TRUSTED proxy who want real-client-IP propagation set
    ``PPXAI_FORWARDED_ALLOW_IPS`` (the proxy's IP, or ``*``) — and are then
    responsible for their proxy sanitizing inbound ``X-Forwarded-For``.
    """
    return os.environ.get("PPXAI_FORWARDED_ALLOW_IPS", "")


#: Set by `--announce` (ADR 0013): the idle monitor's timeout, 0 = never.
_IDLE_TIMEOUT_OVERRIDE: int | None = None


class _PpxaiServer(uvicorn.Server):
    """uvicorn's server, with ppxai's stop rules in its signal handler.

    uvicorn installs `handle_exit` for SIGINT/SIGTERM for the whole of
    `serve()`, so a handler registered beforehand never sees a signal while
    the server runs. Here the first signal records why ppxai stopped. A
    second signal of EITHER kind forces the stop (uvicorn forces on a second
    SIGINT only) and cancels in-flight requests: on Python 3.12+
    `Server.wait_closed()` waits for every open connection, so without the
    cancel a request stuck in a provider call kept even a forced stop
    waiting for the full grace.
    """

    _loop: asyncio.AbstractEventLoop | None = None
    _first_signal_at: float | None = None

    #: A repeat within this window is the SAME stop delivered twice, not a
    #: request to force: a terminal's Ctrl+C reaches the whole process group,
    #: and the PyInstaller bootloader also forwards it to this child
    #: (`bootloader_ignore_signals=False` in ppxai-server.spec).
    DUPLICATE_SIGNAL_S = 0.5

    async def serve(self, sockets=None):
        self._loop = asyncio.get_running_loop()
        await super().serve(sockets)

    def handle_exit(self, sig, frame):
        now = time.monotonic()
        first = not self.should_exit
        if first:
            self._first_signal_at = now
        elif (self._first_signal_at is not None
              and now - self._first_signal_at < self.DUPLICATE_SIGNAL_S):
            return
        super().handle_exit(sig, frame)
        try:
            name = signal.Signals(sig).name
        except (AttributeError, ValueError):
            name = str(sig)
        if first:
            logger.info(f"Received {name}, initiating shutdown")
            if _state.session_manager:
                _state.session_manager.request_shutdown(
                    "ctrl_c" if sig == signal.SIGINT else "signal")
            return
        _warn_console(f"Received {name} again, forcing shutdown")
        self.force_exit = True
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._cancel_requests)

    def _cancel_requests(self) -> None:
        for task in list(self.server_state.tasks):
            task.cancel()

    async def shutdown(self, sockets=None):
        await super().shutdown(sockets)
        if not self.force_exit:
            return
        # uvicorn skips the app's lifespan shutdown on a forced stop, so
        # sessions were not saved, preview backends not stopped, and the
        # "stopped" line never printed; the orphaned lifespan task was then
        # cancelled with a traceback. Run it anyway, bounded.
        try:
            await asyncio.wait_for(self.lifespan.shutdown(),
                                   timeout=self.config.timeout_graceful_shutdown or 10)
        except asyncio.TimeoutError:
            _warn_console("Application shutdown did not finish; exiting anyway")


class _AbandonedRequestFilter(logging.Filter):
    """At shutdown, a cancelled in-flight request is expected, not a crash.

    uvicorn logs it as "Exception in ASGI application" with a CancelledError
    traceback, which read like a crash to operators. While the server is
    stopping, that record becomes one warning line; any other error passes
    through unchanged.
    """

    def __init__(self, server: uvicorn.Server):
        super().__init__()
        self._server = server

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if self._server.should_exit and isinstance(exc, asyncio.CancelledError):
            record.levelno, record.levelname = logging.WARNING, "WARNING"
            record.msg = "Abandoned an in-flight request at shutdown (it never finished)"
            record.args, record.exc_info, record.exc_text = (), None, None
        return True


async def _run_server_with_graceful_shutdown(app_ref, host: str, port: int, log_level: str = "info",
                                             fd: int | None = None):
    """Run uvicorn server with graceful shutdown support (v1.13.10).

    This uses uvicorn.Server directly to enable graceful shutdown via
    the _shutdown_event, avoiding os._exit() which bypasses cleanup handlers.

    Args:
        app_ref: The FastAPI app (object or string for --reload)
        host: Host to bind to
        port: Port to bind to
        log_level: Logging level
        fd: An already-listening socket to serve on instead of host/port
            (the `--uds` path binds it itself, 0600 before the first accept).
    """
    grace_s = get_shutdown_grace_s()
    config = uvicorn.Config(
        app_ref,
        host=host,
        port=port,
        fd=fd,
        log_level=log_level,
        # Don't trust proxy client-IP headers by default — see _forwarded_allow_ips.
        forwarded_allow_ips=_forwarded_allow_ips(),
        # Bound the wait for in-flight requests. uvicorn's default (None)
        # waited for ever, so one provider call that never answered held the
        # server past SIGTERM until SIGKILL (2026-09-28, WSL, kimi-k3).
        timeout_graceful_shutdown=grace_s,
    )
    server = _PpxaiServer(config)

    # Outside `serve()` (startup, and when uvicorn re-raises the signals it
    # captured after `serve()` returns) signals come here. During `serve()`
    # uvicorn installs `server.handle_exit` itself, so the logic lives there.
    def handle_signal(signum, frame):
        if not server.should_exit:
            server.handle_exit(signum, frame)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Create shutdown listener task
    async def shutdown_listener():
        # Wait for shutdown event to be created (happens in lifespan)
        _shutdown_event = _state.get_shutdown_event()
        while _shutdown_event is None:
            await asyncio.sleep(0.1)
            _shutdown_event = _state.get_shutdown_event()
        # Wait for shutdown signal
        await _shutdown_event.wait()
        logger.info("Shutdown event received, stopping server")
        server.should_exit = True

    # Run both server and shutdown listener concurrently
    workers = _install_worker_executor()
    # Installed for the rest of the process, deliberately never removed: a
    # request cancelled at the grace timeout logs its CancelledError when the
    # task finally unwinds, which can be AFTER serve() returns (seen on macOS;
    # removing the filter in `finally` let that traceback through).
    logging.getLogger("uvicorn.error").addFilter(_AbandonedRequestFilter(server))
    global _serving_via_entry_point
    _serving_via_entry_point = True
    shutdown_task = asyncio.create_task(shutdown_listener())
    try:
        await server.serve()
    finally:
        shutdown_task.cancel()
        try:
            await shutdown_task
        except asyncio.CancelledError:
            pass
        await _release_worker_threads(workers, 0.0 if server.force_exit else grace_s)
        if _stopped_line:
            print(_stopped_line, flush=True)


#: Set when provider calls were still running in worker threads at shutdown.
#: The caller then finishes its own cleanup and calls `_exit_if_workers_hung`.
_workers_hung = False

#: The lifespan's "ppxai HTTP server stopped (...)" line. Under the server
#: entry point it is printed LAST, after the worker-thread release, whose
#: warnings and the cancelled request's 500 used to follow it.
_stopped_line: str | None = None
_serving_via_entry_point = False


def _install_worker_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Give the running loop a default executor this module holds.

    `asyncio.to_thread` (every provider call) runs on the loop's default
    executor. Owning it lets shutdown wait for it with a real bound instead
    of through `loop.shutdown_default_executor()`, which on Python 3.10/3.11
    ends in an UNBOUNDED `thread.join()` on the loop thread, so no
    `wait_for` around it could ever time out (found on macOS 3.11).
    """
    executor = concurrent.futures.ThreadPoolExecutor(thread_name_prefix="ppxai-worker")
    asyncio.get_running_loop().set_default_executor(executor)
    return executor


async def _release_worker_threads(executor: concurrent.futures.ThreadPoolExecutor,
                                  grace_s: float) -> None:
    """Wait at most `grace_s` for `executor`'s work, then let go of it.

    A call that never returns used to keep the process alive after the
    server stopped: `asyncio.run` joins the default executor without a
    limit on exit. The join here runs in a daemon thread the loop polls, so
    the bound holds on every supported Python (>= 3.10).
    """
    global _workers_hung
    joined = threading.Event()

    def _join():
        executor.shutdown(wait=True)
        joined.set()

    threading.Thread(target=_join, name="ppxai-worker-join", daemon=True).start()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(grace_s, 0.05)
    while not joined.is_set() and loop.time() < deadline:
        await asyncio.sleep(0.05)
    if joined.is_set():
        return
    _workers_hung = True
    _warn_console(
        f"Provider call(s) still running {grace_s:.0f}s after shutdown; "
        "exiting without waiting for them"
    )
    # A fresh, idle executor so asyncio.run's own final join returns at once.
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=1))


def _warn_console(message: str) -> None:
    """Warn where an operator stopping the server sees it: uvicorn's console
    logger (ppxai's own log is a file, off by default) and the debug log."""
    logging.getLogger("uvicorn.error").warning(message)
    logger.warning(message)


def _exit_if_workers_hung() -> None:
    """Exit now if hung worker threads would otherwise block interpreter exit.

    Called by each entry point AFTER its own cleanup (the announced server
    removes its registry entry and socket first). Logs are flushed first.
    """
    if _workers_hung:
        logging.shutdown()
        os._exit(0)


def run_server():
    """Run the HTTP server (CLI entry point)."""
    parser = argparse.ArgumentParser(description="ppxai HTTP Server")
    parser.add_argument("--version", "-v", action="version", version=f"ppxai-server {__version__}")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind to")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    # ADR 0013 S3 -- the remote-side contract a hub drives over SSH.
    parser.add_argument("--uds", nargs="?", const="", metavar="PATH",
                        help="Serve on a private unix socket (0600, POSIX) instead of TCP; "
                             "no PATH = $XDG_RUNTIME_DIR/ppxai/<id>.sock")
    parser.add_argument("--announce", action="store_true",
                        help="With --uds: generate a per-launch token, write a registry "
                             "entry (~/.ppxai/run/servers/<id>.json) and print it as JSON")
    parser.add_argument("--detach", action="store_true",
                        help="With --announce: run in the background (POSIX)")
    parser.add_argument("--label", default=None, help="Human label stored in the registry entry")
    parser.add_argument("--list", action="store_true", dest="list_servers",
                        help="List live announced servers (pruning dead entries) and exit")
    parser.add_argument("--json", action="store_true", help="With --list: print JSON")

    args = parser.parse_args()

    if args.list_servers:
        sys.exit(_list_servers(as_json=args.json))
    if args.uds is not None or args.announce or args.detach:
        sys.exit(_run_announced(args))

    # Tell the Host-validation middleware the real bind host (debt (u)): a
    # loopback bind stays strict; a wide bind relaxes per PPXAI_TRUSTED_HOSTS.
    _set_bind_host(args.host)

    # Initialize configuration system (v1.13.10: explicit initialization)
    initialize()

    print(f"Starting ppxai HTTP server on http://{args.host}:{args.port}")
    print("Endpoints:")
    print("  POST /chat          - Chat with SSE streaming")
    print("  POST /coding_task   - Coding task with SSE streaming")
    print("  GET  /providers     - List providers")
    print("  GET  /models        - List models")
    print("  GET  /tools         - List tools")
    print("  POST /tools/config  - Configure tool settings")
    print("  GET  /agent/status  - Get agent mode status")
    print("  POST /agent/enable  - Enable agent mode")
    print("  POST /agent/disable - Disable agent mode")
    print("  GET  /usage         - Token usage statistics")
    print("  GET  /debug-log     - Get debug logging status")
    print("  POST /debug-log     - Enable/disable debug logging")
    print("  GET  /health        - Health check")
    print("  GET  /status        - Current status")
    print("  GET  /sessions/list - List active sessions (v1.13.10)")
    print()
    print("Session isolation: Use X-Session-Id header for isolated sessions")
    print()

    # Surface which config file is authoritative + the secret-provider
    # chain. The config source is easy to get wrong: PPXAI_CONFIG_FILE
    # (often set via ./.env) overrides ./ppxai-config.json, so editing
    # the obvious project file can silently have no effect. Print it.
    try:

        _cfg_src = _loader.find_config_file()
        print(f"Config: {_cfg_src or '(builtin defaults — no config file found)'}")
        _names = [p.name for p in get_secret_provider().providers]
        print(f"Auth providers: {', '.join(_names) if _names else '(none)'}")
        print()
    except Exception as _exc:  # never let banner introspection break startup
        print(f"Config: (could not resolve: {_exc})")
        print()

    # Check if running as frozen executable (PyInstaller)
    if getattr(sys, 'frozen', False):
        # Running as bundled executable - use app object directly
        asyncio.run(_run_server_with_graceful_shutdown(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
        ))
    else:
        # Running from source - use string import
        if args.reload:
            uvicorn.run(
                "ppxai.server.http:app",
                host=args.host,
                port=args.port,
                reload=True,
                log_level="info",
                forwarded_allow_ips=_forwarded_allow_ips(),
            )
        else:
            asyncio.run(_run_server_with_graceful_shutdown(
                "ppxai.server.http:app",
                host=args.host,
                port=args.port,
                log_level="info",
            ))
    _exit_if_workers_hung()


def _list_servers(as_json: bool) -> int:
    """`--list`: live registry entries only; dead ones are deleted."""
    live = registry.list_live(prune=True)
    if as_json:
        print(json.dumps(live, indent=2))
    elif not live:
        print("No announced ppxai servers are running.")
    else:
        for e in live:
            label = f"  [{e['label']}]" if e.get("label") else ""
            print(f"{e['id']}  pid {e['pid']}  {e['socket']}  {e['workdir']}{label}")
    return 0


def _usage_error(message: str) -> int:
    print(f"ppxai-server: {message}", file=sys.stderr)
    return 2


def _run_announced(args) -> int:
    """`--uds [PATH] [--announce [--detach]]` (ADR 0013 S3).

    Order matters and is the contract:
    1. (--detach) fork away from the launcher, which waits for step 5's JSON;
    2. bind the socket 0600 in a 0700 dir -- before anything can connect;
    3. (--announce) put a fresh token in THIS process's PPXAI_API_TOKEN and
       make sure the auth chain reads it, so auth is on even though every
       request arrives over the socket;
    4. write the registry entry with THIS process's pid;
    5. print the entry (or hand it to the waiting launcher), then serve.
    The entry and socket are removed when the server exits.
    """
    if args.detach and not args.announce:
        return _usage_error("--detach needs --announce (otherwise nothing can find the server)")
    if args.announce and args.uds is None:
        return _usage_error("--announce needs --uds: the contract is socket-only, never TCP")
    if args.reload:
        return _usage_error("--reload cannot be combined with --uds/--announce")
    if sys.platform == "win32":
        return _usage_error("--uds/--announce/--detach need a POSIX host; "
                            "use --host/--port on Windows")

    server_id = registry.new_server_id()
    socket_path = (registry.default_socket_path(server_id) if args.uds == ""
                   else Path(os.path.abspath(os.path.expanduser(args.uds))))
    report_fd = _detach() if args.detach else None
    try:
        sock = registry.bind_uds(socket_path)
    except OSError as exc:
        _report(report_fd, {"error": str(exc)})
        return 1

    global _IDLE_TIMEOUT_OVERRIDE
    token = None
    if args.announce:
        token = registry.new_token()
        os.environ["PPXAI_API_TOKEN"] = token
        _IDLE_TIMEOUT_OVERRIDE = 0

    # Loopback bind semantics for Host validation: the hub forwards to the
    # socket and names the server as localhost.
    _set_bind_host("127.0.0.1")
    initialize()
    if args.announce:
        chain = get_secret_provider()
        if not any(isinstance(p, EnvSecretProvider) and p.var == "PPXAI_API_TOKEN"
                   for p in chain.providers):
            chain.providers.insert(0, EnvSecretProvider())

    entry = None
    if args.announce:
        entry = registry.build_entry(server_id=server_id, socket_path=socket_path,
                                     token=token, workdir=os.getcwd(), label=args.label)
        registry.write_entry(entry)
    _report(report_fd, entry or {"socket": str(socket_path), "pid": os.getpid()})

    try:
        app_ref = app if getattr(sys, "frozen", False) else "ppxai.server.http:app"
        asyncio.run(_run_server_with_graceful_shutdown(
            app_ref, host="127.0.0.1", port=0, log_level="info", fd=sock.fileno()))
    finally:
        if entry is not None:
            registry.remove_entry(server_id)
        try:
            socket_path.unlink()
        except OSError:
            pass
    _exit_if_workers_hung()
    return 0


def _report(fd: int | None, payload: dict) -> None:
    """Print the entry JSON, or hand it to the detached launcher's pipe."""
    text = json.dumps(payload, indent=2)
    if fd is None:
        print(text, flush=True)
        return
    with os.fdopen(fd, "w", encoding="utf-8") as pipe:
        pipe.write(text)


def _detach() -> int:
    """Double-fork away from the launcher (POSIX). Returns, in the daemon, the
    write end of a pipe; the launcher prints what arrives on it and exits
    (1 if the daemon reported an error or died without announcing).
    """
    read_fd, write_fd = os.pipe()
    if os.fork() > 0:  # the launcher
        os.close(write_fd)
        with os.fdopen(read_fd, encoding="utf-8") as pipe:
            payload = pipe.read()
        if not payload:
            print("ppxai-server: the detached server exited before announcing", file=sys.stderr)
            os._exit(1)
        print(payload, flush=True)
        os._exit(1 if "error" in json.loads(payload) else 0)
    os.close(read_fd)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    # The daemon: no controlling terminal; stdio goes to a server log.
    log_dir = Path.home() / ".ppxai" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_fd = os.open(log_dir / f"server-detached-{os.getpid()}.log",
                     os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    null_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null_fd, 0)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    return write_fd


def run_desktop():
    """Run desktop web app - starts server and opens browser (CLI entry point)."""
    parser = argparse.ArgumentParser(description="ppxai Desktop Web App")
    parser.add_argument("--version", "-v", action="version", version=f"ppxai-desktop {__version__}")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind to")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind to")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser")

    args = parser.parse_args()

    # Host-validation bind context (debt (u)) — desktop binds loopback by default.
    _set_bind_host(args.host)

    url = f"http://{args.host}:{args.port}"

    # Open browser after short delay (let server start)
    if not args.no_browser:
        def open_browser():
            time.sleep(1.5)  # Wait for server to start
            print(f"Opening browser: {url}")
            webbrowser.open(url)

        threading.Thread(target=open_browser, daemon=True).start()

    print(f"Starting ppxai Desktop Web App on {url}")
    print("Press Ctrl+C to stop")
    print()

    if getattr(sys, 'frozen', False):
        asyncio.run(_run_server_with_graceful_shutdown(
            app,
            host=args.host,
            port=args.port,
            log_level="warning",
        ))
    else:
        asyncio.run(_run_server_with_graceful_shutdown(
            "ppxai.server.http:app",
            host=args.host,
            port=args.port,
            log_level="warning",
        ))
    _exit_if_workers_hung()


if __name__ == "__main__":
    run_server()

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
import os
import signal
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from ..common.logger import get_logger
from ..config import get_idle_timeout, initialize
from ..version import __version__
from .routes import all_routers
from .session_manager import SessionManager
from .state import (
    get_server_start_time,
    set_server_start_time,
    set_session_manager,
    set_shutdown_event,
    update_activity,
)

# Re-export for backward compatibility (tests, PyInstaller specs, entry points)
from .state import get_or_create_session, is_path_allowed  # noqa: F401
from .streaming import sse_event_generator, sse_coding_task_generator  # noqa: F401
from . import state as _state  # noqa: F401 — backing store for session_manager


# Backward-compat proxy: tests do `http_module.session_manager = mock_manager`.
# We need reads/writes of `session_manager` on this module to proxy through to
# the state module so route handlers (which import from state) see the same value.
import types as _types  # noqa: E402

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

    # Start idle shutdown monitor (v1.13.10)
    idle_timeout = get_idle_timeout()

    def idle_shutdown_callback():
        """Callback to trigger graceful shutdown from idle monitor."""
        if _shutdown_event:
            _shutdown_event.set()

    await sm.start_idle_monitor(idle_timeout, idle_shutdown_callback)

    startup_time = time.time() - startup_start
    set_server_start_time(time.time())

    # Log startup with timestamp
    start_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"Server started at {start_timestamp} (startup took {startup_time:.2f}s)")
    print(f"ppxai HTTP server started ({startup_time:.2f}s)")
    print(f"Provider: {default_engine.provider_name}")
    print(f"Model: {default_engine.model}")
    print(f"Session isolation: enabled (X-Session-Id header)")
    if idle_timeout > 0:
        print(f"Auto-shutdown: {idle_timeout // 60} minutes of inactivity")
    else:
        print(f"Auto-shutdown: disabled")

    yield

    # Shutdown: Kill preview backends (v1.17.1)
    from .state import all_preview_backends, remove_preview_backend, kill_preview_backend
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
    print(f"ppxai HTTP server stopped (uptime: {uptime_str}, reason: {shutdown_reason})")


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


from .auth import check_request as _auth_check_request


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
            from fastapi.responses import JSONResponse
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
                from fastapi.responses import JSONResponse
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


async def _run_server_with_graceful_shutdown(app_ref, host: str, port: int, log_level: str = "info"):
    """Run uvicorn server with graceful shutdown support (v1.13.10).

    This uses uvicorn.Server directly to enable graceful shutdown via
    the _shutdown_event, avoiding os._exit() which bypasses cleanup handlers.

    Args:
        app_ref: The FastAPI app (object or string for --reload)
        host: Host to bind to
        port: Port to bind to
        log_level: Logging level
    """
    config = uvicorn.Config(
        app_ref,
        host=host,
        port=port,
        log_level=log_level,
        # Don't trust proxy client-IP headers by default — see _forwarded_allow_ips.
        forwarded_allow_ips=_forwarded_allow_ips(),
    )
    server = uvicorn.Server(config)

    # Set up signal handlers to capture shutdown reason
    def handle_signal(signum, frame):
        try:
            sig_name = signal.Signals(signum).name
        except (AttributeError, ValueError):
            sig_name = str(signum)
        reason = "ctrl_c" if signum == signal.SIGINT else "signal"
        logger.info(f"Received {sig_name}, initiating shutdown")
        if _state.session_manager:
            _state.session_manager.request_shutdown(reason)
        server.should_exit = True

    # Install signal handlers (uvicorn's defaults will be overridden)
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
    shutdown_task = asyncio.create_task(shutdown_listener())
    try:
        await server.serve()
    finally:
        shutdown_task.cancel()
        try:
            await shutdown_task
        except asyncio.CancelledError:
            pass


def run_server():
    """Run the HTTP server (CLI entry point)."""
    parser = argparse.ArgumentParser(description="ppxai HTTP Server")
    parser.add_argument("--version", "-v", action="version", version=f"ppxai-server {__version__}")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind to")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    args = parser.parse_args()

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
        from ..config.loader import find_config_file
        from .state import get_secret_provider

        _cfg_src = find_config_file()
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


if __name__ == "__main__":
    run_server()

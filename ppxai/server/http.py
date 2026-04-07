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

# Add CORS middleware for webview/browser access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Session-Id"],  # Allow clients to see session ID
)


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


# Register all route modules
for router in all_routers:
    app.include_router(router)


# === CLI Entry Point ===

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

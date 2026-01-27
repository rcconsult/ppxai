# Server Refactoring Plan: Separate Entry Points and Reusable Code

**Date:** 2026-01-27
**Goal:** Separate server reusable code from entry points for standalone and embedded use cases

---

## Current Structure Issues

### File: `ppxai/server/http.py` (2,479 lines)

**Problems:**
1. ❌ **Global app instance** - Created at module load time (line 214)
2. ❌ **Global state** - session_manager, _shutdown_event, _server_start_time
3. ❌ **Mixed concerns** - Routes + CLI entry points + deployment logic
4. ❌ **67 routes** - All in one massive file
5. ❌ **Hard to test** - Globals make unit testing difficult
6. ❌ **Can't reuse** - Embedded use case requires different lifespan/config

**Current module structure:**
```
ppxai/server/
├── __init__.py           # Exports jsonrpc (outdated)
├── __main__.py           # CLI for jsonrpc (not used)
├── jsonrpc.py            # Legacy JSON-RPC server
├── session_manager.py    # ✅ Already well-designed (reusable)
└── http.py               # ❌ Monolithic (2479 lines, globals)
```

---

## Proposed New Structure

### Organization by Concern

```
ppxai/
├── server/                      # Reusable server core
│   ├── __init__.py              # Export factory, not app instance
│   ├── core/                    # Core reusable components
│   │   ├── __init__.py
│   │   ├── app.py               # FastAPI app factory (no globals)
│   │   ├── config.py            # Server-specific config
│   │   ├── middleware.py        # CORS, activity tracking
│   │   ├── lifespan.py          # Startup/shutdown logic
│   │   └── events.py            # SSE event helpers
│   ├── routes/                  # Route modules (break up 67 routes)
│   │   ├── __init__.py
│   │   ├── chat.py              # /chat, /coding_task
│   │   ├── providers.py         # /providers, /models
│   │   ├── tools.py             # /tools/*
│   │   ├── agent.py             # /agent/*
│   │   ├── sessions.py          # /sessions/*
│   │   ├── files.py             # /files/*
│   │   ├── context.py           # /context/*
│   │   ├── usage.py             # /usage/*
│   │   ├── status.py            # /status, /health, /metrics
│   │   └── debug.py             # /debug-log
│   ├── session_manager.py       # ✅ Keep as-is (already good)
│   └── types.py                 # Request/response models (Pydantic)
│
├── server_cli/                  # Entry points (CLI wrappers)
│   ├── __init__.py
│   ├── standalone.py            # ppxai-server entry point
│   ├── desktop.py               # ppxai-desktop entry point
│   └── embedded.py              # NEW: Embedded thread helper
│
└── client/                      # NEW: Shared HTTP client code
    ├── __init__.py
    ├── http_client.py           # Base HTTP + SSE client
    ├── models.py                # Request/response types
    └── events.py                # SSE event parsing
```

---

## Phase 1: Extract Core App Factory

### Current (http.py):

```python
# Line 214: Global app instance
app = FastAPI(
    title="ppxai HTTP Server",
    description="HTTP + SSE server for ppxai AI chat",
    version=__version__,
    lifespan=lifespan,  # Uses global state
)

# Routes defined on global app
@app.post("/chat")
async def chat_endpoint(...):
    global session_manager  # Uses global
    ...
```

### After Refactor (server/core/app.py):

```python
"""FastAPI app factory - no global state."""

from fastapi import FastAPI
from ..session_manager import SessionManager
from .lifespan import create_lifespan
from .middleware import setup_middleware
from ..routes import chat, providers, tools, agent, sessions, files, context, usage, status, debug

def create_app(
    *,
    title: str = "ppxai HTTP Server",
    enable_cors: bool = True,
    enable_idle_shutdown: bool = True,
    idle_timeout: int = 0,
    enable_static_files: bool = False,
    web_dir: Optional[Path] = None,
) -> FastAPI:
    """
    Factory function to create FastAPI app instance.

    No global state - each call creates independent app.

    Args:
        title: API title
        enable_cors: Enable CORS middleware
        enable_idle_shutdown: Enable auto-shutdown on idle
        idle_timeout: Idle timeout in seconds (0 = disabled)
        enable_static_files: Serve static web UI files
        web_dir: Path to web UI files

    Returns:
        Configured FastAPI app instance
    """
    # Create session manager instance (not singleton!)
    session_manager = SessionManager()

    # Create lifespan context manager with config
    lifespan_ctx = create_lifespan(
        session_manager=session_manager,
        enable_idle_shutdown=enable_idle_shutdown,
        idle_timeout=idle_timeout,
    )

    # Create app instance
    app = FastAPI(
        title=title,
        description="HTTP + SSE server for ppxai AI chat",
        version=__version__,
        lifespan=lifespan_ctx,
    )

    # Store session manager in app state (not global!)
    app.state.session_manager = session_manager

    # Setup middleware
    setup_middleware(app, enable_cors=enable_cors)

    # Register routes
    app.include_router(chat.router, prefix="", tags=["chat"])
    app.include_router(providers.router, prefix="", tags=["providers"])
    app.include_router(tools.router, prefix="/tools", tags=["tools"])
    app.include_router(agent.router, prefix="/agent", tags=["agent"])
    app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
    app.include_router(files.router, prefix="/files", tags=["files"])
    app.include_router(context.router, prefix="/context", tags=["context"])
    app.include_router(usage.router, prefix="/usage", tags=["usage"])
    app.include_router(status.router, prefix="", tags=["status"])
    app.include_router(debug.router, prefix="/debug-log", tags=["debug"])

    # Serve static files if enabled
    if enable_static_files and web_dir:
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="static")

    return app
```

---

## Phase 2: Extract Routes to Modules

### Example: server/routes/chat.py

```python
"""Chat routes - /chat, /coding_task."""

from fastapi import APIRouter, Request, Header
from fastapi.responses import StreamingResponse
from typing import Optional
from pydantic import BaseModel

from ..core.events import create_sse_stream
from ..session_manager import SessionManager

# Create router (not app!)
router = APIRouter()


class ChatRequest(BaseModel):
    """Chat request model."""
    message: str
    stream: bool = True


@router.post("/chat")
async def chat_endpoint(
    request: Request,
    body: ChatRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id"),
):
    """Chat with SSE streaming."""
    # Get session manager from app state (not global!)
    session_manager: SessionManager = request.app.state.session_manager

    # Get or create session
    session_id, engine, lock = await session_manager.get_or_create_session(x_session_id)

    # Create SSE stream
    return StreamingResponse(
        create_sse_stream(engine, body.message, lock),
        media_type="text/event-stream",
        headers={"X-Session-Id": session_id}
    )


@router.post("/coding_task")
async def coding_task_endpoint(
    request: Request,
    body: ChatRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id"),
):
    """Handle coding task with SSE streaming."""
    # Similar to chat_endpoint...
    ...
```

**Benefits:**
- ✅ No globals - gets session_manager from `request.app.state`
- ✅ Modular - one file per domain
- ✅ Testable - can test router in isolation
- ✅ Reusable - same router works in any FastAPI app

---

## Phase 3: Create Entry Points

### server_cli/standalone.py (ppxai-server)

```python
"""Standalone server entry point (CLI)."""

import argparse
import asyncio
import sys
import uvicorn
from pathlib import Path

from ppxai.version import __version__
from ppxai.config import initialize, get_idle_timeout
from ppxai.server.core.app import create_app


async def _run_with_graceful_shutdown(app_or_path, *, host, port, log_level):
    """Run uvicorn with graceful shutdown on idle timeout."""
    config = uvicorn.Config(
        app=app_or_path,
        host=host,
        port=port,
        log_level=log_level,
    )
    server = uvicorn.Server(config)

    # Run server with shutdown signal handling
    async def serve():
        await server.serve()

    # Start server
    await serve()


def main():
    """Entry point for ppxai-server CLI."""
    parser = argparse.ArgumentParser(description="ppxai HTTP Server")
    parser.add_argument("--version", "-v", action="version", version=f"ppxai-server {__version__}")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=54320, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--no-idle-shutdown", action="store_true", help="Disable idle shutdown")

    args = parser.parse_args()

    # Initialize configuration
    initialize()

    # Get idle timeout from config
    idle_timeout = 0 if args.no_idle_shutdown else get_idle_timeout()

    print(f"Starting ppxai HTTP server on http://{args.host}:{args.port}")
    print("Endpoints:")
    print("  POST /chat          - Chat with SSE streaming")
    print("  POST /coding_task   - Coding task with SSE streaming")
    # ... more endpoints ...
    print()
    print("Session isolation: Use X-Session-Id header for isolated sessions")
    if idle_timeout > 0:
        print(f"Auto-shutdown: {idle_timeout // 60} minutes of inactivity")
    print()

    # Create app instance
    app = create_app(
        enable_idle_shutdown=not args.no_idle_shutdown,
        idle_timeout=idle_timeout,
    )

    # Run server
    if getattr(sys, 'frozen', False):
        # PyInstaller binary - use app object directly
        asyncio.run(_run_with_graceful_shutdown(
            app, host=args.host, port=args.port, log_level="info"
        ))
    else:
        # Source code - use string import for reload
        if args.reload:
            # Reload requires module path, not instance
            # Need to export app at module level for reload
            print("Warning: --reload with factory pattern requires PPXAI_SERVER_APP env var")
            uvicorn.run(
                "ppxai.server.core.app:create_app",  # Factory function
                host=args.host,
                port=args.port,
                reload=True,
                log_level="info",
                factory=True,  # Tell uvicorn it's a factory
            )
        else:
            asyncio.run(_run_with_graceful_shutdown(
                app, host=args.host, port=args.port, log_level="info"
            ))


if __name__ == "__main__":
    main()
```

### server_cli/desktop.py (ppxai-desktop)

```python
"""Desktop web app entry point (server + browser)."""

import argparse
import webbrowser
import threading
import time
import uvicorn
from pathlib import Path

from ppxai.version import __version__
from ppxai.config import initialize, get_web_dir
from ppxai.server.core.app import create_app


def main():
    """Entry point for ppxai-desktop CLI."""
    parser = argparse.ArgumentParser(description="ppxai Desktop Web App")
    parser.add_argument("--version", "-v", action="version", version=f"ppxai-desktop {__version__}")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=54320, help="Port to bind to")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser")

    args = parser.parse_args()

    # Initialize configuration
    initialize()

    # Get web directory
    web_dir = get_web_dir()

    url = f"http://{args.host}:{args.port}"

    # Open browser after delay
    if not args.no_browser:
        def open_browser():
            time.sleep(1.5)  # Wait for server to start
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()

    print(f"Starting ppxai desktop app at {url}")
    print("Opening browser...")

    # Create app with static files
    app = create_app(
        enable_static_files=True,
        web_dir=web_dir,
        enable_idle_shutdown=False,  # Desktop stays running
    )

    # Run server
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="warning",  # Quieter for desktop
    )


if __name__ == "__main__":
    main()
```

### server_cli/embedded.py (NEW - For ppxaide)

```python
"""Embedded server for in-process use (ppxaide)."""

import asyncio
import threading
import time
import uvicorn
from typing import Optional
from pathlib import Path

from ppxai.server.core.app import create_app
from ppxai.common.logger import get_logger

logger = get_logger("embedded_server")


class EmbeddedServer:
    """
    Run FastAPI server in background thread.

    For use with ppxaide TUI - provides same HTTP/SSE API as standalone server
    but runs in-process without subprocess coordination.

    Usage:
        server = EmbeddedServer(port=0)  # Random port
        port = server.start()
        # ... use http://127.0.0.1:{port} ...
        server.stop()
    """

    def __init__(
        self,
        *,
        port: int = 0,
        host: str = "127.0.0.1",
        unix_socket: Optional[str] = None,
        enable_idle_shutdown: bool = False,
    ):
        """
        Initialize embedded server.

        Args:
            port: Port to bind (0 = random, OS assigns)
            host: Host to bind
            unix_socket: Unix socket path (Linux/Mac only, overrides port)
            enable_idle_shutdown: Enable auto-shutdown on idle
        """
        self.host = host
        self.port = port
        self.unix_socket = unix_socket
        self.enable_idle_shutdown = enable_idle_shutdown

        self._thread: Optional[threading.Thread] = None
        self._server: Optional[uvicorn.Server] = None
        self._started = threading.Event()
        self._actual_port: Optional[int] = None

    def start(self, timeout: float = 5.0) -> int:
        """
        Start server in background thread.

        Args:
            timeout: Max seconds to wait for startup

        Returns:
            Actual port number (useful if port=0 was passed)

        Raises:
            TimeoutError: Server didn't start in time
            RuntimeError: Server already running
        """
        if self._thread and self._thread.is_alive():
            raise RuntimeError("Server already running")

        # Create app instance
        app = create_app(
            title="ppxai Embedded Server",
            enable_cors=False,  # Not needed for loopback
            enable_idle_shutdown=self.enable_idle_shutdown,
            idle_timeout=0,  # TUI manages lifetime
            enable_static_files=False,  # TUI doesn't need web UI
        )

        # Create uvicorn config
        if self.unix_socket:
            config = uvicorn.Config(
                app=app,
                uds=self.unix_socket,
                log_level="error",  # Quiet
                loop="asyncio",
            )
        else:
            config = uvicorn.Config(
                app=app,
                host=self.host,
                port=self.port,
                log_level="error",  # Quiet
                loop="asyncio",
            )

        self._server = uvicorn.Server(config)

        # Run in thread
        def run_server():
            """Thread target."""
            try:
                # Store actual port after binding
                # Note: This is available after server.startup()
                asyncio.run(self._server.serve())
            except Exception as e:
                logger.error(f"Embedded server error: {e}")

        self._thread = threading.Thread(
            target=run_server,
            daemon=True,
            name="ppxai-embedded-server"
        )
        self._thread.start()

        # Wait for server to be ready
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check if server bound to port
            if self._server.started:
                self._started.set()
                # Get actual port (important if port=0)
                if not self.unix_socket:
                    # uvicorn server stores bound port in servers list
                    if self._server.servers:
                        for server in self._server.servers:
                            # Get socket from server
                            for socket in server.sockets:
                                self._actual_port = socket.getsockname()[1]
                                break
                            if self._actual_port:
                                break
                    if not self._actual_port:
                        self._actual_port = self.port
                logger.info(f"Embedded server started on port {self._actual_port}")
                return self._actual_port
            time.sleep(0.1)

        raise TimeoutError(f"Server didn't start within {timeout}s")

    def stop(self, timeout: float = 2.0):
        """
        Stop server gracefully.

        Args:
            timeout: Max seconds to wait for shutdown
        """
        if not self._thread or not self._thread.is_alive():
            return

        if self._server:
            self._server.should_exit = True

        # Wait for thread to finish
        self._thread.join(timeout=timeout)

        if self._thread.is_alive():
            logger.warning("Embedded server didn't stop gracefully")

        self._thread = None
        self._server = None
        self._started.clear()
        logger.info("Embedded server stopped")

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def actual_port(self) -> Optional[int]:
        """Get actual bound port (useful if port=0 was used)."""
        return self._actual_port

    @property
    def base_url(self) -> str:
        """Get base URL for HTTP client."""
        if self.unix_socket:
            return f"http+unix://{self.unix_socket}"
        else:
            port = self._actual_port or self.port
            return f"http://{self.host}:{port}"
```

---

## Phase 4: Create Shared HTTP Client

### client/http_client.py

```python
"""Shared HTTP client for ppxai server (web, VSCode, ppxaide)."""

import httpx
import json
from typing import AsyncIterator, Optional, Dict, Any
from pydantic import BaseModel


class SSEEvent(BaseModel):
    """SSE event from server."""
    type: str
    data: Optional[Dict[str, Any]] = None


class PpxaiHttpClient:
    """
    HTTP + SSE client for ppxai server.

    Can be used by web app, VSCode extension, and ppxaide TUI.
    Provides unified API for server communication.

    Usage:
        client = PpxaiHttpClient("http://127.0.0.1:54320")

        # Streaming chat
        async for event in client.stream_chat("Hello"):
            if event.type == "chunk":
                print(event.data["content"])

        # Commands
        providers = await client.get_providers()
        models = await client.get_models()
    """

    def __init__(
        self,
        base_url: str,
        session_id: Optional[str] = None,
        timeout: float = 300.0,
    ):
        """
        Initialize HTTP client.

        Args:
            base_url: Server base URL (e.g., "http://127.0.0.1:54320")
            session_id: Session ID for server session isolation
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self.client = httpx.AsyncClient(timeout=timeout)

    def _get_headers(self) -> Dict[str, str]:
        """Get headers with session ID."""
        headers = {}
        if self.session_id:
            headers["X-Session-Id"] = self.session_id
        return headers

    async def stream_chat(
        self,
        message: str,
        stream: bool = True,
    ) -> AsyncIterator[SSEEvent]:
        """
        Stream chat response via SSE.

        Args:
            message: User message
            stream: Enable streaming (always True for SSE)

        Yields:
            SSEEvent objects
        """
        async with self.client.stream(
            "POST",
            f"{self.base_url}/chat",
            json={"message": message, "stream": stream},
            headers=self._get_headers(),
        ) as response:
            response.raise_for_status()

            # Store session ID from response
            if "X-Session-Id" in response.headers:
                self.session_id = response.headers["X-Session-Id"]

            # Parse SSE stream
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        yield SSEEvent(**data)
                    except json.JSONDecodeError:
                        # Skip invalid JSON
                        continue

    async def send_consent_response(
        self,
        filepath: Optional[str] = None,
        command: Optional[str] = None,
        approved: bool = False,
        reason: str = "",
    ) -> None:
        """
        Send consent response to server.

        Args:
            filepath: File path (for file consent)
            command: Shell command (for shell consent)
            approved: Whether consent was approved
            reason: Reason for approval/denial
        """
        response = await self.client.post(
            f"{self.base_url}/consent",
            json={
                "filepath": filepath,
                "command": command,
                "approved": approved,
                "reason": reason,
            },
            headers=self._get_headers(),
        )
        response.raise_for_status()

    async def get_providers(self) -> Dict[str, Any]:
        """Get available providers."""
        response = await self.client.get(
            f"{self.base_url}/providers",
            headers=self._get_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def get_models(self, provider: Optional[str] = None) -> Dict[str, Any]:
        """Get available models."""
        params = {"provider": provider} if provider else {}
        response = await self.client.get(
            f"{self.base_url}/models",
            params=params,
            headers=self._get_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def get_status(self) -> Dict[str, Any]:
        """Get server status."""
        response = await self.client.get(
            f"{self.base_url}/status",
            headers=self._get_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
```

---

## Migration Timeline

### Phase 1: Factory Pattern (2 days) - v1.15.1

**Changes:**
- [ ] Create `server/core/app.py` with `create_app()` factory
- [ ] Move lifespan logic to `server/core/lifespan.py`
- [ ] Move middleware to `server/core/middleware.py`
- [ ] Update `server_cli/standalone.py` to use factory
- [ ] Update `server_cli/desktop.py` to use factory
- [ ] Keep backward compatibility: `server/http.py` imports from core

**Testing:**
- [ ] Standalone server works (`ppxai-server`)
- [ ] Desktop app works (`ppxai-desktop`)
- [ ] All routes work
- [ ] Session isolation works
- [ ] Idle shutdown works

**Risk:** Low - mostly moving code, not changing logic

---

### Phase 2: Extract Routes (3 days) - v1.15.1

**Changes:**
- [ ] Create `server/routes/` module
- [ ] Split routes into 10 files (chat, providers, tools, etc.)
- [ ] Each route uses `request.app.state.session_manager`
- [ ] Register routers in `create_app()`

**Testing:**
- [ ] All 67 routes work
- [ ] Session management works
- [ ] Consent handling works

**Risk:** Medium - touching all routes, need thorough testing

---

### Phase 3: Entry Points (1 day) - v1.15.1

**Changes:**
- [ ] Create `server_cli/` package
- [ ] Move `run_server()` to `server_cli/standalone.py`
- [ ] Move `run_desktop()` to `server_cli/desktop.py`
- [ ] Update pyproject.toml entry points

**Testing:**
- [ ] CLI args work
- [ ] Binary builds work
- [ ] Auto-reload works

**Risk:** Low - mostly moving CLI code

---

### Phase 4: Embedded Server (1 day) - v1.16.0

**Changes:**
- [ ] Create `server_cli/embedded.py` with `EmbeddedServer` class
- [ ] Test thread startup/shutdown
- [ ] Test random port allocation
- [ ] Test Unix socket (Linux/Mac)

**Testing:**
- [ ] Server starts in thread
- [ ] HTTP requests work across threads
- [ ] Clean shutdown works
- [ ] Multiple start/stop cycles work

**Risk:** Low - new code, doesn't affect existing

---

### Phase 5: Shared HTTP Client (2 days) - v1.16.0

**Changes:**
- [ ] Create `client/` package
- [ ] Implement `PpxaiHttpClient` class
- [ ] Port SSE parsing from web app
- [ ] Add request/response models

**Testing:**
- [ ] Streaming chat works
- [ ] Consent handling works
- [ ] All endpoints work
- [ ] Session isolation works

**Risk:** Low - new code, can test independently

---

### Phase 6: Integrate with ppxaide (2 days) - v1.16.0

**Changes:**
- [ ] Add `EmbeddedServer` to ppxaide
- [ ] Replace EngineClient with PpxaiHttpClient
- [ ] Port SSE event handling
- [ ] Simplify consent dialogs

**Testing:**
- [ ] ppxaide chat works via embedded server
- [ ] Consent dialogs work
- [ ] All commands work
- [ ] Performance acceptable

**Risk:** Medium - changes core ppxaide architecture

---

### Total Effort: 11 days across 2 releases

**v1.15.1 (6 days):**
- Phase 1: Factory pattern (2 days)
- Phase 2: Extract routes (3 days)
- Phase 3: Entry points (1 day)

**v1.16.0 (5 days):**
- Phase 4: Embedded server (1 day)
- Phase 5: Shared HTTP client (2 days)
- Phase 6: Integrate ppxaide (2 days)

---

## Benefits After Refactoring

### Code Organization

**Before:**
```
ppxai/server/http.py       # 2479 lines, 67 routes, global state
```

**After:**
```
ppxai/server/core/         # ~400 lines - app factory, config
ppxai/server/routes/       # ~1500 lines - 10 modules, ~150 lines each
ppxai/server_cli/          # ~300 lines - 3 entry points
ppxai/client/              # ~400 lines - shared HTTP client
```

**Improvement:**
- ✅ Smaller files (150 lines vs 2479)
- ✅ Clear separation of concerns
- ✅ Reusable components
- ✅ No global state

### Testability

**Before:**
```python
# Can't test routes without globals
def test_chat():
    # Globals make this hard!
    global session_manager
    ...
```

**After:**
```python
# Test routes in isolation
def test_chat():
    app = create_app()  # Fresh instance
    client = TestClient(app)
    response = client.post("/chat", ...)
    assert response.status_code == 200
```

### Reusability

**Use Cases Enabled:**

1. **Standalone server** - `ppxai-server` (existing)
2. **Desktop app** - `ppxai-desktop` (existing)
3. **Embedded in ppxaide** - `EmbeddedServer` (NEW)
4. **Testing** - `create_app()` for unit tests (NEW)
5. **Custom deployments** - Import factory, customize config (NEW)

### Client Code Sharing

**Before:**
- Web app: Custom JS HTTP client
- VSCode: Custom TS HTTP client
- ppxaide: Direct EngineClient (different architecture)

**After:**
- Web app: Port `PpxaiHttpClient` to JS (same API)
- VSCode: Port `PpxaiHttpClient` to TS (same API)
- ppxaide: Use `PpxaiHttpClient` in Python (same API)

**Benefit:** Same logic in 3 languages, easier to maintain

---

## Backward Compatibility

### During Migration

Keep `ppxai/server/http.py` as compatibility shim:

```python
"""Backward compatibility shim - imports from new structure."""

# Re-export factory
from .core.app import create_app

# For PyInstaller frozen apps that import "ppxai.server.http:app"
# Create default app instance
app = create_app()

# Re-export entry points (deprecated)
from ..server_cli.standalone import main as run_server
from ..server_cli.desktop import main as run_desktop

__all__ = ["create_app", "app", "run_server", "run_desktop"]
```

### After Migration (v1.17.0)

Remove `ppxai/server/http.py`, document new imports:

```python
# Old (deprecated)
from ppxai.server.http import app, run_server

# New
from ppxai.server.core.app import create_app
from ppxai.server_cli.standalone import main as run_server
```

---

## Risk Assessment

| Phase | Risk Level | Mitigation |
|-------|-----------|------------|
| **Phase 1: Factory** | Low | Keep http.py shim, gradual migration |
| **Phase 2: Routes** | Medium | Thorough testing of all 67 routes |
| **Phase 3: Entry Points** | Low | Move CLI code without logic changes |
| **Phase 4: Embedded** | Low | New code, doesn't affect existing |
| **Phase 5: Client** | Low | New code, testable independently |
| **Phase 6: ppxaide** | Medium | Changes core architecture, needs testing |

**Overall Risk:** Medium-Low with phased approach

---

## Success Criteria

**v1.15.1 (Refactored Server):**
- ✅ All existing functionality works
- ✅ No performance regression
- ✅ Code split into logical modules
- ✅ No global state in core
- ✅ Factory pattern works
- ✅ Tests pass

**v1.16.0 (Embedded + Client):**
- ✅ ppxaide works with embedded server
- ✅ Thin client architecture functional
- ✅ Shared HTTP client reusable
- ✅ Performance acceptable (latency < 10ms loopback)
- ✅ All 1105 tests pass

---

## Next Steps

1. **Review this plan** - Get feedback on structure
2. **Start Phase 1** - Create factory pattern
3. **Test thoroughly** - Ensure backward compatibility
4. **Iterate** - Adjust based on findings

**Recommended:** Start with Phase 1 (factory pattern) as standalone improvement, even if embedded server is deferred.

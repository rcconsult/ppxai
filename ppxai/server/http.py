"""
FastAPI HTTP Server with SSE streaming for ppxai.

This server provides:
- SSE streaming for chat responses (POST /chat)
- REST endpoints for configuration (providers, models, tools)
- Health and readiness endpoints for container orchestration
- Session isolation for multi-client support (v1.13.10)

Usage:
    uv run ppxai-server
    uv run ppxai-server --port 8080
    uv run ppxai-server --host 0.0.0.0 --port 8080
"""

import argparse
import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..common.logger import get_logger
from ..common.preview import inject_reload_script, resolve_preview_path, rewrite_asset_paths
from ..engine import EngineClient, EventType
from ..version import __version__
from .session_manager import SessionManager

# Server logger (v1.11.2)
logger = get_logger("server")

# Session manager singleton (v1.13.10)
# Replaces global variables for thread-safe session management
# All state is now managed by SessionManager class
session_manager: SessionManager = None

# Shutdown event for graceful termination (v1.13.10)
# Used by /shutdown endpoint to signal uvicorn to stop
_shutdown_event: asyncio.Event = None

# Server start time for uptime tracking (v1.13.10)
_server_start_time: float = 0


async def get_or_create_session(session_id: Optional[str]) -> tuple[str, EngineClient, asyncio.Lock]:
    """Get existing session or create new one (v1.13.10, v1.13.10 refactored).

    Args:
        session_id: Session ID from X-Session-Id header, or None for default

    Returns:
        tuple: (session_id, engine, lock)

    Note: v1.13.10 - Now delegates to SessionManager for thread-safe operation.
    """
    global session_manager

    if session_manager is None or not session_manager.is_initialized:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    try:
        return await session_manager.get_or_create_session(session_id)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


async def cleanup_expired_sessions():
    """Remove sessions that haven't been used recently (v1.13.10).

    Note: v1.13.10 - Now delegates to SessionManager.
    """
    global session_manager
    if session_manager:
        await session_manager.cleanup_expired_sessions()


def update_activity():
    """Update last activity timestamp (v1.13.10).

    Note: v1.13.10 - Now delegates to SessionManager.
    """
    global session_manager
    if session_manager:
        session_manager.update_activity()


async def check_idle_shutdown():
    """Background task to check for idle shutdown (v1.13.10).

    Note: v1.13.10 - This function is now a no-op as idle shutdown
    is handled by SessionManager.start_idle_monitor().
    Kept for backward compatibility.
    """
    # Idle shutdown is now managed by SessionManager
    pass


async def http_consent_handler(file_path: str) -> tuple[bool, str]:
    """
    Handle file edit consent request via HTTP (Phase 1C: v1.11.0).
    Used by default engine (backward compatibility).

    Note: v1.13.10 - Now delegates to SessionManager.
    """
    global session_manager
    return await session_manager._handle_consent("default", file_path)


async def http_shell_consent_handler(command: str, working_dir: str, risk_level: str) -> tuple[bool, str]:
    """
    Handle shell command consent request via HTTP (v1.11.2).
    Used by default engine (backward compatibility).

    Note: v1.13.10 - Now delegates to SessionManager.
    """
    global session_manager
    return await session_manager._handle_shell_consent("default", command, working_dir, risk_level)


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan (startup/shutdown).

    v1.13.10: Refactored to use SessionManager for thread-safe state management.
    v1.13.10: Added graceful shutdown via _shutdown_event.
    v1.13.10: Added startup/shutdown logging with uptime tracking.
    """
    global session_manager, _shutdown_event, _server_start_time
    startup_start = time.time()

    # Initialize shutdown event for graceful termination (v1.13.10)
    _shutdown_event = asyncio.Event()

    # Initialize SessionManager singleton (v1.13.10)
    logger.info("Server starting up - initializing SessionManager")
    session_manager = SessionManager.get_instance()

    # Initialize with consent callbacks
    await session_manager.initialize(
        consent_callback=http_consent_handler,
        shell_consent_callback=http_shell_consent_handler
    )

    default_engine = session_manager.default_engine
    logger.info(f"EngineClient initialized - provider: {default_engine.provider_name}, model: {default_engine.model}")
    logger.info("Session management initialized (v1.13.10, v1.13.10 thread-safe)")

    # Start idle shutdown monitor (v1.13.10)
    # Pass shutdown callback for graceful shutdown instead of os._exit
    from ..config import get_idle_timeout
    idle_timeout = get_idle_timeout()

    def idle_shutdown_callback():
        """Callback to trigger graceful shutdown from idle monitor."""
        if _shutdown_event:
            _shutdown_event.set()

    await session_manager.start_idle_monitor(idle_timeout, idle_shutdown_callback)

    startup_time = time.time() - startup_start
    _server_start_time = time.time()

    # Log startup with timestamp
    from datetime import datetime
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

    # Shutdown: Cleanup via SessionManager (v1.13.10)
    # Calculate and log uptime
    uptime = time.time() - _server_start_time
    uptime_str = _format_uptime(uptime)
    shutdown_reason = session_manager.shutdown_reason if session_manager else "unknown"
    stop_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"Server stopped at {stop_timestamp} (uptime: {uptime_str}, reason: {shutdown_reason})")
    logger.info("Server shutting down - cleaning up SessionManager")
    await session_manager.shutdown()
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

    Updates the last_activity timestamp on every request to reset
    the idle shutdown timer.
    """
    update_activity()
    response = await call_next(request)
    return response


# Web UI directory (installed by ppxai-desktop or manually)
WEB_UI_DIR = Path.home() / '.ppxai' / 'web'


# === Request/Response Models ===

class ChatRequest(BaseModel):
    """Chat request body."""
    message: str
    provider: Optional[str] = None
    model: Optional[str] = None


class CodingTaskRequest(BaseModel):
    """Coding task request body."""
    message: str
    task_type: str = "generate"  # generate, debug, explain, test, docs, implement
    provider: Optional[str] = None
    model: Optional[str] = None


class SetProviderRequest(BaseModel):
    """Set provider request body."""
    provider: str
    model: Optional[str] = None


class SetModelRequest(BaseModel):
    """Set model request body."""
    model: str


class ToolsRequest(BaseModel):
    """Tools configuration request body."""
    enabled: bool


class ToolsConfigRequest(BaseModel):
    """Tools config request body."""
    setting: str
    value: str


class WorkingDirRequest(BaseModel):
    """Set working directory request body."""
    path: str


class AutoInjectRequest(BaseModel):
    """Set auto-inject context request body."""
    enabled: bool


class ConsentRequest(BaseModel):
    """File edit consent response (Phase 1C: v1.11.0)."""
    file_path: str
    response: str  # 'y', 'n', 'always', 'never'


class ShellConsentRequest(BaseModel):
    """Shell command consent response (v1.11.2)."""
    command: str
    working_dir: str = "."
    response: str  # 'y', 'n', 'always', 'never'



# === SSE Streaming ===

async def sse_event_generator(prompt: str, engine: EngineClient, session_id: str = "default") -> AsyncGenerator[str, None]:
    """Generate SSE events from engine chat.

    SSE format: data: {json}\n\n
    Each event is yielded immediately with a sleep(0) to force flush.
    Phase 1C: Also checks consent_event_queue for pending consent requests.
    v1.11.2: Added debug logging for troubleshooting.
    v1.13.10: Takes engine as parameter for session isolation.
    v1.13.9: Added explicit [DONE] termination for robust stream completion.
             Helps prevent aiohttp ClientPayloadError in downstream clients.
    """
    if not engine:
        logger.error("SSE event generator called but engine not initialized")
        yield f"data: {json.dumps({'type': 'error', 'data': 'Engine not initialized'})}\n\n"
        return

    logger.log_user_message(prompt)

    try:
        async for event in engine.chat(prompt):
            # Phase 1C: Check for pending consent requests before each event
            while engine._consent_event_queue:
                consent_event = engine._consent_event_queue.pop(0)
                logger.log_event("CONSENT_REQUEST", str(consent_event.data))
                consent_data = {
                    "type": consent_event.type.value,
                    "data": consent_event.data,
                }
                if consent_event.metadata:
                    consent_data["metadata"] = consent_event.metadata
                logger.log_sse_event("consent_request", str(consent_event.data)[:100])
                yield f"data: {json.dumps(consent_data)}\n\n"
                await asyncio.sleep(0)

            # Log specific event types
            if event.type == EventType.TOOL_CALL:
                tool_data = event.data if isinstance(event.data, dict) else {}
                logger.log_tool_call(tool_data.get('tool', 'unknown'), tool_data.get('arguments', {}))
            elif event.type == EventType.STREAM_END:
                logger.log_assistant_message(str(event.data)[:200] if event.data else "")
            elif event.type == EventType.ERROR:
                logger.error(f"Engine error: {event.data}")

            # Emit regular event
            event_data = {
                "type": event.type.value,
                "data": event.data,
            }
            if event.metadata:
                event_data["metadata"] = event.metadata
            logger.log_sse_event(event.type.value, str(event.data)[:100] if event.data else "")
            yield f"data: {json.dumps(event_data)}\n\n"
            # Force event loop to flush the response immediately
            await asyncio.sleep(0)
    except Exception as e:
        logger.error(f"Exception in SSE event generator: {e}")
        error_str = str(e)
        yield f"data: {json.dumps({'type': 'error', 'data': error_str})}\n\n"

        # Session cleanup for message alternation errors
        # When we get a 400 error about message alternation, it means the session
        # has consecutive user messages. Clean up by removing the last user message.
        if "alternation" in error_str.lower() or "alternate" in error_str.lower():
            try:
                messages = engine.session.messages
                # Find and remove orphan user messages (consecutive user messages at the end)
                while len(messages) > 1 and messages[-1].role == "user" and messages[-2].role == "user":
                    removed = messages.pop()
                    logger.info(f"Session cleanup: removed orphan user message (len={len(removed.content)})")
                logger.info(f"Session cleaned up, now has {len(messages)} messages")
            except Exception as cleanup_error:
                logger.error(f"Session cleanup failed: {cleanup_error}")

    # Auto-save usage and session to persistent storage after each chat
    # This ensures usage is never lost even if server crashes
    # v1.14.1: Also saves session with validate_and_fix_alternation()
    try:
        if engine and engine.session:
            engine.session.save_usage_to_persistent_storage()
            engine.session.save_dirty()  # v1.14.1: autosave with alternation fix
    except Exception as save_error:
        logger.warning(f"Failed to auto-save: {save_error}")

    # Send explicit [DONE] termination signal
    # This follows OpenAI's SSE convention and helps prevent ClientPayloadError
    # in aiohttp-based clients (like Open WebUI) by signaling clean stream end
    logger.log_sse_event("done", "[DONE]")
    yield "data: [DONE]\n\n"
    await asyncio.sleep(0)  # Ensure final event is flushed


async def sse_coding_task_generator(
    prompt: str,
    task_type: str,
    engine: EngineClient
) -> AsyncGenerator[str, None]:
    """Generate SSE events from engine coding task.

    v1.13.10: Takes engine as parameter for session isolation.
    v1.13.9: Added explicit [DONE] termination for robust stream completion.
    """
    if not engine:
        yield f"data: {json.dumps({'type': 'error', 'data': 'Engine not initialized'})}\n\n"
        return

    try:
        async for event in engine.coding_task(prompt, task_type):
            event_data = {
                "type": event.type.value,
                "data": event.data,
            }
            if event.metadata:
                event_data["metadata"] = event.metadata
            yield f"data: {json.dumps(event_data)}\n\n"
            # Force event loop to flush the response immediately
            await asyncio.sleep(0)
    except Exception as e:
        error_str = str(e)
        yield f"data: {json.dumps({'type': 'error', 'data': error_str})}\n\n"

        # Session cleanup for message alternation errors
        if "alternation" in error_str.lower() or "alternate" in error_str.lower():
            try:
                messages = engine.session.messages
                while len(messages) > 1 and messages[-1].role == "user" and messages[-2].role == "user":
                    removed = messages.pop()
                    logger.info(f"Session cleanup: removed orphan user message (len={len(removed.content)})")
            except Exception as cleanup_error:
                logger.error(f"Session cleanup failed: {cleanup_error}")

    # Auto-save usage and session to persistent storage after each coding task
    # v1.14.1: Also saves session with validate_and_fix_alternation()
    try:
        if engine and engine.session:
            engine.session.save_usage_to_persistent_storage()
            engine.session.save_dirty()  # v1.14.1: autosave with alternation fix
    except Exception as save_error:
        logger.warning(f"Failed to auto-save: {save_error}")

    # Send explicit [DONE] termination signal
    logger.log_sse_event("done", "[DONE]")
    yield "data: [DONE]\n\n"
    await asyncio.sleep(0)  # Ensure final event is flushed


# === API Endpoints ===

@app.get("/health")
async def health_check():
    """Health check endpoint for container orchestration.

    Returns basic server status. Use /ready for detailed readiness checks.

    v1.13.10: Updated to use SessionManager and enhanced for Kubernetes.
    """
    global session_manager
    from ..config import get_idle_timeout
    idle_timeout = get_idle_timeout()

    last_activity = session_manager.last_activity if session_manager else 0

    return {
        "status": "healthy",
        "version": __version__,
        "engine": session_manager.is_initialized if session_manager else False,
        "sessions": session_manager.session_count if session_manager else 0,
        "idle_timeout": idle_timeout,
        "idle_since": int(time.time() - last_activity) if last_activity > 0 else 0,
    }


@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint for container orchestration (v1.13.10).

    Returns detailed readiness status. Use for Kubernetes readiness probes.
    Returns 503 if server is not ready to accept traffic.

    Checks:
    - SessionManager initialized
    - Default engine available
    - Provider configured
    """
    global session_manager

    # Check if session manager is ready
    if session_manager is None or not session_manager.is_initialized:
        raise HTTPException(
            status_code=503,
            detail="Server not ready: SessionManager not initialized"
        )

    default_engine = session_manager.default_engine
    if default_engine is None:
        raise HTTPException(
            status_code=503,
            detail="Server not ready: Default engine not available"
        )

    # Get available providers
    from ..config import get_available_providers
    providers = get_available_providers()

    return {
        "status": "ready",
        "version": __version__,
        "provider": default_engine.provider_name,
        "model": default_engine.model,
        "providers_available": len(providers),
        "sessions_active": session_manager.session_count,
        "shutdown_requested": session_manager.shutdown_requested,
    }


@app.post("/shutdown")
async def shutdown_server():
    """Gracefully shutdown the server (v1.13.6).

    This endpoint allows clients to request server shutdown.
    Useful for web app UI to stop the server via a button.

    Returns:
        JSON: {"shutdown": true, "message": "Server shutting down..."}

    Note: v1.13.10 - Uses graceful shutdown via asyncio event instead of os._exit().
    This allows cleanup handlers (atexit) to run properly.
    """
    global session_manager, _shutdown_event

    logger.info("Shutdown requested via /shutdown endpoint")

    # Mark shutdown as requested via SessionManager
    if session_manager:
        session_manager.request_shutdown("api_request")

    # Schedule graceful shutdown after response is sent (v1.13.10)
    async def delayed_shutdown():
        await asyncio.sleep(0.5)  # Give time for response to be sent
        logger.info("Initiating graceful shutdown")
        if _shutdown_event:
            _shutdown_event.set()
        else:
            # Fallback for edge cases where event wasn't initialized
            import signal
            signal.raise_signal(signal.SIGTERM)

    asyncio.create_task(delayed_shutdown())

    return {
        "shutdown": True,
        "message": "Server shutting down...",
    }


@app.get("/config/paths")
async def get_paths_config():
    """Get paths configuration for binary and data locations (v1.13.2).

    Returns:
        bin_search_paths: List of directories to search for binaries
        data_dir: Directory for sessions, exports, usage data
    """
    from ..config import get_paths_config as _get_paths_config
    return _get_paths_config()


@app.get("/config/path")
async def get_config_path():
    """Get the current config file path (v1.15.2).

    Returns:
        path: Path to the config file, or null if not found
    """
    from ..config import find_config_file

    config_path = find_config_file()
    return {"path": str(config_path) if config_path else None}


@app.post("/config/reload")
async def reload_config_endpoint():
    """Reload configuration from file without restarting server.

    This allows hot-reloading of provider prompts, settings, and other
    configuration changes from ppxai-config.json.

    Note: This updates PROVIDERS/MODELS module-level dicts in-place (v1.15.3),
    so all engine clients will see fresh provider data immediately via the
    providers_config property. Individual sessions' shell/agent configs remain
    cached until the session explicitly calls engine.reload_config().

    Returns:
        success: Whether reload succeeded
        message: Status message
        config_path: Path to loaded config file
    """
    from ..config import reload_config, find_config_file

    try:
        reload_config()  # Updates PROVIDERS/MODELS in place via initialize()
        config_path = find_config_file()
        logger.info(f"Configuration reloaded from {config_path}")
        return {
            "success": True,
            "message": "Configuration reloaded successfully",
            "config_path": str(config_path) if config_path else None
        }
    except Exception as e:
        logger.error(f"Failed to reload config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reload config: {e}")


@app.get("/status")
async def get_status(x_session_id: Optional[str] = Header(None)):
    """Get current engine status.

    v1.13.10: Supports X-Session-Id header for session isolation.
    v1.14.0: Added bootstrap context status.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    return {
        "provider": engine.provider_name,
        "model": engine.model,
        "tools_enabled": engine.tools_enabled,
        "agent_mode": engine.agent_mode,
        "auto_inject_context": engine.auto_inject_context,
        "session_id": session_id,
        "bootstrap": engine.get_bootstrap_status(),  # v1.14.0
    }


@app.get("/sessions/list")
async def list_active_sessions():
    """List all active sessions (v1.13.10).

    Returns information about currently active sessions for debugging/monitoring.

    Note: v1.13.10 - Now uses SessionManager.list_sessions().
    """
    global session_manager

    # Get sessions via SessionManager (includes cleanup)
    session_list = await session_manager.list_sessions()

    return {
        "sessions": session_list,
        "count": len(session_list),
        "default_engine_active": session_manager.is_initialized,
    }


@app.post("/chat")
async def chat(
    request: ChatRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Chat endpoint with SSE streaming (v1.11.2: added logging, v1.12.0: added request locking).

    Returns Server-Sent Events stream with chat response chunks.

    v1.12.0: Serializes chat requests to prevent concurrent execution from
    corrupting conversation state. If agent is running, subsequent requests
    will wait for completion.

    v1.13.10: Supports X-Session-Id header for session isolation.
    Each session has its own conversation history, working directory, and state.
    """
    session_id, engine, chat_lock = await get_or_create_session(x_session_id)

    logger.log_http_request("POST", "/chat", f"session={session_id}")

    # Acquire lock to serialize chat requests (v1.12.0)
    async with chat_lock:
        logger.info(f"Chat lock acquired for session {session_id} - processing request")

        # Set provider/model if specified
        if request.provider:
            logger.info(f"Switching provider to: {request.provider}")
            engine.set_provider(request.provider)
        if request.model:
            logger.info(f"Switching model to: {request.model}")
            engine.set_model(request.model)

        # Wrap generator to ensure lock is held during streaming
        async def locked_generator():
            """Generator that streams events while holding the lock."""
            async for event in sse_event_generator(request.message, engine, session_id):
                yield event
            logger.info(f"Chat request completed for session {session_id} - releasing lock")

        return StreamingResponse(
            locked_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
                "X-Session-Id": session_id,  # Return session ID
            }
        )


@app.post("/coding_task")
async def coding_task(
    request: CodingTaskRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Coding task endpoint with SSE streaming (v1.12.0: added request locking).

    Supports task types: generate, debug, explain, test, docs, implement

    v1.12.0: Serializes coding task requests to prevent concurrent execution.
    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, chat_lock = await get_or_create_session(x_session_id)

    # Acquire lock to serialize requests (v1.12.0)
    async with chat_lock:
        logger.info(f"Coding task lock acquired for session {session_id} - processing request")

        # Set provider/model if specified
        if request.provider:
            engine.set_provider(request.provider)
        if request.model:
            engine.set_model(request.model)

        # Wrap generator to ensure lock is held during streaming
        async def locked_generator():
            """Generator that streams events while holding the lock."""
            async for event in sse_coding_task_generator(request.message, request.task_type, engine):
                yield event
            logger.info(f"Coding task completed for session {session_id} - releasing lock")

        return StreamingResponse(
            locked_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Session-Id": session_id,
            }
        )


# === Provider/Model Management ===

@app.get("/providers")
async def get_providers(x_session_id: Optional[str] = Header(None)):
    """Get list of available providers.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    # Reload config to pick up external changes (e.g., new providers added)
    engine.reload_config()

    providers = engine.list_providers()
    return {
        "providers": [
            {
                "id": p.id,
                "name": p.name,
                "has_api_key": p.has_api_key,
                "default_model": p.default_model,
                "capabilities": {
                    "web_search": p.capabilities.web_search,
                    "citations": p.capabilities.citations,
                    "streaming": p.capabilities.streaming,
                }
            }
            for p in providers
        ],
        "current": engine.provider_name,
    }


@app.post("/providers")
async def set_provider(
    request: SetProviderRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Set the active provider.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    # Reload config to pick up external changes before switching
    engine.reload_config()

    success = engine.set_provider(request.provider)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to set provider: {request.provider}")

    # Optionally set model
    if request.model:
        engine.set_model(request.model)

    return {
        "provider": engine.provider_name,
        "model": engine.model,
    }


@app.get("/models")
async def get_models(x_session_id: Optional[str] = Header(None)):
    """Get list of models for current provider.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    # Reload config to pick up external changes (e.g., new models added)
    engine.reload_config()

    models = engine.list_models()
    return {
        "models": [
            {
                "id": m.id,
                "name": m.name,
                "description": m.description,
            }
            for m in models
        ],
        "current": engine.model,
        "provider": engine.provider_name,
    }


@app.post("/models")
async def set_model(
    request: SetModelRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Set the active model.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    # Reload config to pick up external changes before switching
    engine.reload_config()

    success = engine.set_model(request.model)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to set model: {request.model}")

    return {
        "model": engine.model,
        "provider": engine.provider_name,
    }


# === Tools Management ===

@app.get("/tools")
async def get_tools(x_session_id: Optional[str] = Header(None)):
    """Get list of available tools.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    tools = engine.list_tools()

    # Get consent mode from session (v1.11.9)
    consent_mode = "default"
    try:
        if hasattr(engine, 'session') and hasattr(engine.session, 'edit_consent_mode'):
            consent_mode = engine.session.edit_consent_mode
    except Exception as e:
        logger.debug(f"Failed to get consent mode from session: {e}")

    # Get full status including auto_retry_empty
    status = engine.get_tools_status()

    return {
        "tools": tools,  # Already list of {"name": ..., "description": ...}
        "enabled": engine.tools_enabled,
        "max_iterations": status.get('max_iterations', 15),
        "auto_retry_empty": status.get('auto_retry_empty', 2),
        "consent_mode": consent_mode,
        "verbose": status.get('verbose', False),
    }


@app.post("/tools")
async def set_tools(
    request: ToolsRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Enable or disable tools.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    if request.enabled:
        engine.enable_tools()
    else:
        engine.disable_tools()

    return {
        "enabled": engine.tools_enabled,
    }


@app.post("/tools/config")
async def set_tools_config(
    request: ToolsConfigRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Configure tool settings (e.g., max_iterations).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    success = engine.set_tool_config(request.setting, request.value)
    if not success:
        raise HTTPException(status_code=400, detail=f"Unknown setting: {request.setting}")

    return {
        "setting": request.setting,
        "value": request.value,
        "success": True,
    }


@app.get("/tools/help/{tool_name}")
async def get_tool_help(
    tool_name: str,
    x_session_id: Optional[str] = Header(None)
):
    """Get detailed help for a specific tool.

    Returns tool definition including parameters, description, and usage examples.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    if not engine.tools_enabled or not engine.tool_manager:
        raise HTTPException(status_code=400, detail="Tools not enabled")

    tool = engine.tool_manager.get_tool(tool_name)
    if not tool:
        available_tools = engine.tool_manager.list_tools()
        tool_names = [t['name'] for t in available_tools]
        raise HTTPException(
            status_code=404,
            detail=f"Tool not found: {tool_name}. Available: {', '.join(sorted(tool_names))}"
        )

    tool_info = tool.get_definition()
    return {
        "name": tool_name,
        "description": tool_info.get("function", {}).get("description", ""),
        "parameters": tool_info.get("function", {}).get("parameters", {}),
    }


# === Usage Statistics ===

@app.get("/usage")
async def get_usage(x_session_id: Optional[str] = Header(None)):
    """Get token usage statistics for current session.

    Returns full usage including per-model breakdown (v1.12.2).
    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    return engine.get_usage()


class UsageDisplayModeRequest(BaseModel):
    """Request body for setting usage display mode."""
    mode: str  # "session", "provider", "model", or "off"


@app.post("/usage/display")
async def set_usage_display_mode(
    request: UsageDisplayModeRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Set usage display mode for status line (v1.12.2).

    Args:
        mode: One of "session", "provider", "model", "off"
            - session: Show session totals
            - provider: Show current provider totals
            - model: Show current model totals
            - off: Hide usage from status line

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    valid_modes = {"session", "provider", "model", "off"}
    if request.mode not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {request.mode}. Valid modes: {', '.join(valid_modes)}"
        )

    success = engine.session.set_usage_display_mode(request.mode)
    return {"mode": request.mode, "success": success}


@app.get("/usage/display")
async def get_usage_display_mode(x_session_id: Optional[str] = Header(None)):
    """Get current usage display mode (v1.12.2).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    return {"mode": engine.session.usage_display_mode}


@app.post("/usage/reset")
async def reset_usage(x_session_id: Optional[str] = Header(None)):
    """Reset all usage statistics to zero (v1.12.2).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    engine.session.reset_usage()
    return {"success": True}


@app.get("/usage/report")
async def get_usage_report(period: str = "all"):
    """Get aggregated usage report for a time period (v1.12.3).

    Query params:
        period: One of "24h", "week", "month", "year", "all" (default: "all")

    Returns aggregated usage stats across all sessions:
        - total_tokens: Total tokens used
        - total_cost: Estimated total cost
        - session_count: Number of sessions
        - by_provider: Usage breakdown by provider
        - by_model: Usage breakdown by model
        - sessions: Recent session summaries
    """
    from ..usage import get_usage_report as get_report

    valid_periods = {"24h", "week", "month", "year", "all"}
    if period not in valid_periods:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period: {period}. Valid periods: {', '.join(valid_periods)}"
        )

    return get_report(period)


@app.get("/usage/sessions")
async def get_usage_sessions(limit: int = 20, offset: int = 0):
    """Get list of recorded sessions with usage data (v1.12.3).

    Query params:
        limit: Maximum sessions to return (default: 20, max: 100)
        offset: Number of sessions to skip (default: 0)

    Returns:
        sessions: List of session records (newest first)
        total: Total number of recorded sessions
    """
    from ..usage import get_usage_storage

    # Clamp limit to reasonable range
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    storage = get_usage_storage()
    sessions = storage.get_sessions(limit=limit, offset=offset)
    total = storage.get_session_count()

    return {
        "sessions": sessions,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# === Context Settings ===

@app.get("/context/working_dir")
async def get_working_dir(x_session_id: Optional[str] = Header(None)):
    """Get the current working directory.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    import os
    path = engine.get_working_dir() or os.getcwd()
    return {"path": path, "session_id": session_id}


@app.post("/context/working_dir")
async def set_working_dir(
    request: WorkingDirRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Set the working directory for file path resolution.

    v1.13.10: Supports X-Session-Id header for session isolation.
    Each session maintains its own working directory.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    import os
    # Expand tilde and resolve to absolute path
    path = os.path.expanduser(request.path)

    # If relative path, resolve relative to session's current working dir (not server cwd)
    if not os.path.isabs(path):
        current_wd = engine.get_working_dir() or os.getcwd()
        path = os.path.normpath(os.path.join(current_wd, path))

    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=f"Not a valid directory: {path}")

    engine.set_working_dir(path)
    logger.info(f"Session {session_id} working directory set to: {path}")
    return {"path": path, "success": True, "session_id": session_id}


@app.post("/context/auto_inject")
async def set_auto_inject(
    request: AutoInjectRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Enable or disable automatic context injection.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    engine.set_auto_inject(request.enabled)
    return {"enabled": request.enabled, "success": True}


@app.get("/context/auto_inject")
async def get_auto_inject(x_session_id: Optional[str] = Header(None)):
    """Get auto-inject context status.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    return {"enabled": engine.get_auto_inject()}


@app.get("/context/info")
async def get_context_info(x_session_id: Optional[str] = Header(None)):
    """Get context usage information.

    v1.13.9: Returns token usage, context limit, and injected files.

    Returns:
        - estimated_tokens: Estimated total tokens in conversation
        - context_limit: Model's context window limit
        - usage_percent: Percentage of context used
        - injected_contexts: List of injected @file/@git/@tree references
        - injected_tokens: Tokens used by injections
        - message_count: Number of messages in history
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    info = engine.get_context_info()
    return {**info, "session_id": session_id}


@app.post("/context/clear")
async def clear_context_injections(x_session_id: Optional[str] = Header(None)):
    """Clear injected @file/@git/@tree content from conversation history.

    v1.13.9: Removes injection blocks from messages to free context space.
    The conversation flow is preserved, only the injected content is removed.

    Returns:
        - removed_count: Number of injections removed
        - success: True if operation completed
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    removed_count = engine.clear_injected_contexts()
    return {
        "removed_count": removed_count,
        "success": True,
        "session_id": session_id
    }


@app.get("/context/hints")
async def get_active_hints(x_session_id: Optional[str] = Header(None)):
    """Get active bootstrap hints for current provider/model.

    v1.14.0: Returns detailed breakdown of which hints from AGENTS.md/CLAUDE.md
    are currently active based on the provider and model.

    Returns:
        - loaded: bool - whether bootstrap context is loaded
        - source: str - path to bootstrap file
        - provider: str - current provider
        - model: str - current model
        - provider_hints: List of [source, hint] tuples
        - model_hints: List of [pattern, hint] tuples
        - inherited_local: bool - whether 'local' hints were inherited
        - matched_patterns: List of matched model patterns
        - all_provider_keys: List of all provider hint keys in file
        - all_model_patterns: List of all model patterns in file
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    hints_info = engine.get_active_hints()
    return {
        **hints_info,
        "session_id": session_id
    }


@app.get("/context/bootstrap")
async def get_bootstrap_status(x_session_id: Optional[str] = Header(None)):
    """Get bootstrap context hierarchy with scope information (v1.14.2).

    Returns detailed information about loaded bootstrap files including
    their scopes (global, project, subdir).

    Returns:
        - loaded: bool - whether bootstrap context is loaded
        - sources: List[Dict] - scoped sources with path, scope, size
        - source_paths: List[str] - simple list of paths (backwards compat)
        - char_count: int - total characters
        - has_hints: bool - whether hints are defined
        - provider_hints: List[str] - providers with hints
        - model_hints: List[str] - model patterns with hints
        - total_size: int - total size in bytes
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    status = engine.get_bootstrap_status()
    return {
        **status,
        "session_id": session_id
    }


@app.post("/context/reload")
async def reload_bootstrap_context(x_session_id: Optional[str] = Header(None)):
    """Reload bootstrap context from disk (v1.14.1, v1.14.2 scopes).

    Reloads bootstrap context files from all scopes (global, project, subdir).
    Useful after editing bootstrap files to pick up changes without restarting.

    Returns:
        JSON: {"success", "loaded", "sources": [...], "char_count", ...}

    v1.14.1: Added for VSCode /context reload command.
    v1.14.2: Returns full scoped source info.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    logger.info(f"HTTP POST /context/reload - session: {session_id}")

    success = engine.reload_bootstrap_context()
    status = engine.get_bootstrap_status()

    return {
        "success": success,
        **status,
        "session_id": session_id
    }


# === Session Management ===

@app.get("/sessions")
async def get_sessions(x_session_id: Optional[str] = Header(None)):
    """Get list of saved sessions.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    sessions_list = engine.session.list_sessions()
    return {
        "sessions": [
            {
                "name": s.name,
                "created_at": s.created_at,
                "saved_at": s.saved_at,
                "provider": s.provider,
                "model": s.model,
                "message_count": s.message_count,
            }
            for s in sessions_list
        ]
    }


@app.post("/sessions/save")
async def save_session(
    name: Optional[str] = None,
    x_session_id: Optional[str] = Header(None)
):
    """Save current session.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    saved_name = engine.session.save(name)
    return {"name": saved_name}


@app.post("/export")
async def export_answer(
    request: Request,
    x_session_id: Optional[str] = Header(None)
):
    """Export last answer to markdown.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    try:
        body = await request.json()
        filename = body.get("filename")
    except Exception:
        filename = None

    try:
        filepath = engine.export_answer(filename)
        return {"filepath": str(filepath)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/sessions/load/{name}")
async def load_session(
    name: str,
    x_session_id: Optional[str] = Header(None)
):
    """Load a saved session.

    v1.13.10: Supports X-Session-Id header for session isolation.
    v1.15.3: Now restores provider and model from session metadata.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    # Reload config from disk to pick up any external changes (v1.15.3)
    engine.reload_config()

    success = engine.session.load(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Session not found: {name}")

    # Apply restored session state to engine
    # Session.load() now loads working_dir and tools_enabled

    # Restore provider/model from session metadata (v1.15.3)
    # Matches TUI (tui/app.py:644-677) and Rich (rich/main.py:583-603)
    from ppxai.config import PROVIDERS, get_default_model
    stored_provider = engine.session.metadata.get("provider")
    stored_model = engine.session.metadata.get("model")

    if stored_provider and stored_provider in PROVIDERS:
        try:
            engine.set_provider(stored_provider)
            logger.info(f"Session restore - provider: {stored_provider}")
        except Exception as e:
            logger.debug(f"Failed to restore provider '{stored_provider}': {e}")

    if stored_model:
        # Use strict mode to validate model exists before restoring
        if engine.set_model(stored_model, strict=True):
            logger.info(f"Session restore - model: {stored_model}")
        else:
            # Model not available - use provider's default model
            provider_name = engine.provider_name if engine.provider else stored_provider
            default_model = get_default_model(provider_name) if provider_name else None
            if default_model:
                engine.set_model(default_model)
                logger.warning(f"Model '{stored_model}' not available, using default: {default_model}")
            else:
                logger.error(f"Model '{stored_model}' not available and no default found for {provider_name}")

    if engine.session.working_dir and os.path.isdir(engine.session.working_dir):
        engine.set_working_dir(engine.session.working_dir)
    if engine.session.tools_enabled:
        engine.enable_tools()

    return {
        "name": name,
        "loaded": True,
        "provider": engine.provider_name if engine.provider else None,
        "model": engine.model,
        "working_dir": engine.get_working_dir(),
        "tools_enabled": engine.tools_enabled,
        "message_count": len(engine.session.messages)
    }


@app.post("/sessions/clear")
async def clear_session(x_session_id: Optional[str] = Header(None)):
    """Clear current session.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    engine.session.clear()
    return {"cleared": True}


@app.get("/sessions/last")
async def get_last_session(x_session_id: Optional[str] = Header(None)):
    """Get last session state from state file.

    v1.13.9: Returns info about the last session for auto-restore prompts.

    Returns:
        JSON with last session info or null if no state file exists
    """
    from ..engine.session import SessionManager

    state = SessionManager.get_last_session_state()
    if not state:
        return {"last_session": None}

    return {
        "last_session": {
            "name": state.get("name"),
            "dirty": state.get("dirty", False),
            "provider": state.get("provider"),
            "model": state.get("model"),
            "working_dir": state.get("working_dir"),
            "tools_enabled": state.get("tools_enabled", False),
            "message_count": state.get("message_count", 0)
        }
    }


@app.post("/sessions/restore")
async def restore_last_session(x_session_id: Optional[str] = Header(None)):
    """Restore the last session automatically.

    v1.13.9: Auto-restore last session including working_dir and tools state.
    v1.15.3: Now restores provider and model from session metadata.

    Returns:
        JSON with restored session info
    """
    from ..engine.session import SessionManager

    session_id, engine, _ = await get_or_create_session(x_session_id)

    state = SessionManager.get_last_session_state()
    if not state or not state.get("name"):
        raise HTTPException(status_code=404, detail="No last session found")

    session_name = state["name"]

    # Reload config from disk to pick up any external changes since last run
    engine.reload_config()

    # Load the session
    success = engine.session.load(session_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_name}")

    # Apply restored session state to engine

    # Restore provider/model from session metadata (v1.15.3)
    # Matches TUI (tui/app.py:644-677) and Rich (rich/main.py:583-603)
    from ppxai.config import PROVIDERS, get_default_model
    stored_provider = engine.session.metadata.get("provider")
    stored_model = engine.session.metadata.get("model")

    if stored_provider and stored_provider in PROVIDERS:
        try:
            engine.set_provider(stored_provider)
            logger.info(f"Session restore - provider: {stored_provider}")
        except Exception as e:
            logger.debug(f"Failed to restore provider '{stored_provider}': {e}")

    if stored_model:
        # Use strict mode to validate model exists before restoring
        if engine.set_model(stored_model, strict=True):
            logger.info(f"Session restore - model: {stored_model}")
        else:
            # Model not available - use provider's default model
            provider_name = engine.provider_name if engine.provider else stored_provider
            default_model = get_default_model(provider_name) if provider_name else None
            if default_model:
                engine.set_model(default_model)
                logger.warning(f"Model '{stored_model}' not available, using default: {default_model}")
            else:
                logger.error(f"Model '{stored_model}' not available and no default found for {provider_name}")

    if engine.session.working_dir and os.path.isdir(engine.session.working_dir):
        engine.set_working_dir(engine.session.working_dir)
    if engine.session.tools_enabled:
        engine.enable_tools()

    return {
        "name": session_name,
        "restored": True,
        "provider": engine.provider_name if engine.provider else None,
        "model": engine.model,
        "working_dir": engine.get_working_dir(),
        "tools_enabled": engine.tools_enabled,
        "message_count": len(engine.session.messages)
    }


class FileReadRequest(BaseModel):
    """Request to read a file."""
    path: str


class FileSearchRequest(BaseModel):
    """Request to search for files."""
    query: str = ""
    max_results: int = 50


# Directories to ignore when searching for files (same as TUI completer)
IGNORE_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox', 'dist', 'build', '.eggs', '.mypy_cache'}


@app.post("/files/search")
async def search_files(
    request: FileSearchRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Search for files in working directory (v1.13.8 - for @file autocomplete).

    Searches files recursively in the working directory, filtering by query.
    Returns list of matching files with relative paths.

    Args:
        request: FileSearchRequest with query and max_results

    Returns:
        JSON: {"files": [{"name": "file.py", "path": "src/file.py"}, ...]}
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    from pathlib import Path
    import os

    logger.info(f"HTTP POST /files/search - query: {request.query}")

    working_dir = Path(engine.get_working_dir() or os.getcwd())
    query = request.query.lower()
    results = []

    try:
        for path in working_dir.rglob('*'):
            if len(results) >= request.max_results:
                break
            try:
                # Check if file - can fail on network paths (WinError 4350)
                if path.is_file():
                    # Skip files in ignored directories
                    if any(ignored in path.parts for ignored in IGNORE_DIRS):
                        continue
                    try:
                        rel_path = str(path.relative_to(working_dir))
                        filename = path.name
                        # Match query against filename or path
                        if not query or query in filename.lower() or query in rel_path.lower():
                            results.append({
                                "name": filename,
                                "path": rel_path
                            })
                    except ValueError:
                        pass
            except OSError:
                # Network file unavailable, skip it
                pass
    except (PermissionError, OSError):
        pass

    # Also add special @ references
    special_refs = [
        {"name": "@git", "path": "Include git diff"},
        {"name": "@tree", "path": "Include project structure"},
    ]

    # Filter special refs by query
    if query:
        special_refs = [ref for ref in special_refs if query in ref["name"].lower()]

    return {"files": special_refs + results}


class FileWriteRequest(BaseModel):
    """Request to write a file."""
    path: str
    content: str


@app.post("/files/write")
async def write_file(
    request: FileWriteRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Write file contents (v1.14.1 - for /edit command).

    Writes content to a file, creating it if it doesn't exist.
    Path validation ensures writes only to allowed directories.

    Args:
        request: FileWriteRequest with path and content

    Returns:
        JSON: {"path", "success", "created", "size"}

    v1.14.1: Added for VSCode /edit command.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    logger.info(f"HTTP POST /files/write - path: {request.path}")

    filepath = request.path.strip()

    # Resolve path - handle tilde expansion
    if filepath.startswith('~'):
        filepath = os.path.expanduser(filepath)

    path = Path(filepath)
    if not path.is_absolute():
        working_dir = Path(engine.get_working_dir() or os.getcwd())
        path = working_dir / filepath

    path = path.resolve()
    logger.debug(f"  Resolved path: {path}")

    # Security: ensure path is within working directory tree or home directory
    working_dir = Path(engine.get_working_dir() or os.getcwd()).resolve()
    home_dir = Path.home().resolve()

    def is_path_allowed(target: Path, base: Path) -> bool:
        """Check if target is within base's tree (parent or child)."""
        try:
            target.relative_to(base)
            return True
        except ValueError:
            pass
        try:
            base.relative_to(target)
            return True
        except ValueError:
            pass
        return False

    # Allow files in working directory tree or home directory tree
    if not (is_path_allowed(path, working_dir) or str(path).startswith(str(home_dir))):
        logger.warning(f"  Access denied: {path} not in {working_dir} tree or {home_dir}")
        raise HTTPException(
            status_code=403, detail="Access denied: path outside allowed directories"
        )

    # Check if file exists (to report 'created' vs 'updated')
    created = not path.exists()

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        path.write_text(request.content, encoding='utf-8')
        size = path.stat().st_size

        logger.info(f"  File {'created' if created else 'updated'}: {path} ({size} bytes)")

        return {
            "path": str(path),
            "success": True,
            "created": created,
            "size": size
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {filepath}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error writing file: {str(e)}")


# === HTML Preview Endpoints (v1.15.4) ===
# Route order matters: poll and static must be defined BEFORE the catch-all


def _extract_session_from_referer(request: Request) -> Optional[str]:
    """Extract session ID from the Referer header's query string.

    When JS inside a preview iframe does fetch('recipes.json'), the browser
    resolves it to /preview/recipes.json with no session param.  But the
    Referer header still points to the parent page URL which *does* contain
    ?session=xxx.  This lets us recover the correct working directory.
    """
    referer = request.headers.get('referer', '')
    if 'session=' in referer:
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(referer).query)
        ids = qs.get('session', [])
        if ids:
            return ids[0]
    return None


@app.get("/preview/poll/{filepath:path}")
async def preview_poll(
    request: Request,
    filepath: str,
    x_session_id: Optional[str] = Header(None),
    session: Optional[str] = None
):
    """Return file modification time for preview reload polling.

    v1.15.4: Used by the injected reload script to detect file changes.
    Accepts session ID via header (X-Session-Id) or query param (?session=).

    Returns:
        JSON: {"mtime": float}
    """
    sid = x_session_id or session or _extract_session_from_referer(request)
    session_id, engine, _ = await get_or_create_session(sid)
    working_dir = engine.get_working_dir() or os.getcwd()

    try:
        path = resolve_preview_path(filepath, working_dir)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="File not found")

    # Return the newest mtime of HTML file + sibling assets (CSS/JS/images)
    # so that changes to linked stylesheets/scripts also trigger a reload
    mtime = path.stat().st_mtime
    try:
        for sibling in path.parent.iterdir():
            if sibling.is_file() and sibling.suffix.lower() in (
                '.css', '.js', '.html', '.htm', '.json', '.svg', '.png', '.jpg'
            ):
                sib_mtime = sibling.stat().st_mtime
                if sib_mtime > mtime:
                    mtime = sib_mtime
    except OSError:
        pass  # Network/permission errors — fall back to HTML mtime only
    return {"mtime": mtime}


@app.get("/preview/static/{filepath:path}")
async def preview_static(
    request: Request,
    filepath: str,
    x_session_id: Optional[str] = Header(None),
    session: Optional[str] = None
):
    """Serve static assets (CSS/JS/images) referenced by preview HTML.

    v1.15.4: Resolves paths relative to the working directory.
    Accepts session ID via header (X-Session-Id), query param (?session=),
    or extracted from Referer header.

    Returns:
        FileResponse for the static asset with no-cache headers
    """
    sid = x_session_id or session or _extract_session_from_referer(request)
    session_id, engine, _ = await get_or_create_session(sid)
    working_dir = engine.get_working_dir() or os.getcwd()

    try:
        # No extension restriction for static assets
        path = resolve_preview_path(filepath, working_dir, restrict_extension=False)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    # no-cache ensures browser revalidates on every request so live-reload
    # picks up CSS/JS changes immediately instead of serving stale cache
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@app.get("/preview/{filepath:path}")
async def preview_html(
    request: Request,
    filepath: str,
    x_session_id: Optional[str] = Header(None),
    session: Optional[str] = None
):
    """Serve HTML file with injected reload script, or static assets.

    v1.15.4: The reload script polls /preview/poll/{filepath} for mtime
    changes and triggers a page reload when the file is modified.

    Non-HTML files (e.g., recipes.json fetched by JS in the page) are
    served as static assets so that fetch() calls with relative URLs work
    inside the preview iframe.

    Accepts session ID via header (X-Session-Id), query param (?session=),
    or extracted from Referer header (for JS fetch() calls inside iframe).

    Returns:
        HTMLResponse with injected reload script, or FileResponse for non-HTML
    """
    sid = x_session_id or session or _extract_session_from_referer(request)
    session_id, engine, _ = await get_or_create_session(sid)
    working_dir = engine.get_working_dir() or os.getcwd()

    # First resolve without extension restriction to check if file exists
    try:
        path = resolve_preview_path(filepath, working_dir, restrict_extension=False)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filepath}")
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    # Non-HTML files: serve as static assets (supports JS fetch() calls)
    if path.suffix.lower() not in ('.html', '.htm'):
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    content = path.read_text(encoding='utf-8')
    # Include session in poll URL so reload script uses the right working dir
    poll_url = f'/preview/poll/{filepath}?session={session_id}' if session_id else f'/preview/poll/{filepath}'

    # Compute cache buster from newest sibling mtime so browser re-fetches
    # changed CSS/JS instead of using stale cached versions
    cache_ts = str(int(path.stat().st_mtime))
    try:
        for sibling in path.parent.iterdir():
            if sibling.is_file() and sibling.suffix.lower() in (
                '.css', '.js', '.json', '.svg', '.png', '.jpg'
            ):
                sib_ts = str(int(sibling.stat().st_mtime))
                if sib_ts > cache_ts:
                    cache_ts = sib_ts
    except OSError:
        pass

    # Rewrite relative CSS/JS/image paths to use /preview/static/ endpoint
    # e.g., <link href="styles.css"> → <link href="/preview/static/styles.css?session=...&_t=123">
    file_dir = str(PurePosixPath(filepath).parent)
    if file_dir == '.':
        static_base = '/preview/static/'
    else:
        static_base = f'/preview/static/{file_dir}/'
    if session_id:
        static_base = f'{static_base}?session={session_id}'
    content = rewrite_asset_paths(content, static_base, cache_buster=cache_ts)

    html = inject_reload_script(content, poll_url)
    return HTMLResponse(content=html)


@app.post("/files/read")
async def read_file(
    request: FileReadRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Read file contents (v1.13.1 - for /show command).

    Reads a file from the working directory or absolute path.
    Supports @search-query format for fuzzy file matching.

    Args:
        request: FileReadRequest with path

    Returns:
        JSON: {"filename", "content", "size", "lines"}

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    from pathlib import Path
    import os

    logger.info(f"HTTP POST /files/read - path: {request.path}")
    logger.debug(f"  Working directory: {engine.get_working_dir()}")

    filepath = request.path.strip()

    # Handle @search-query by searching for files
    if filepath.startswith('@'):
        query = filepath[1:]  # Remove @
        # Simple file search in working directory
        working_dir = Path(engine.get_working_dir() or os.getcwd())
        matches = []

        try:
            for path in working_dir.rglob('*'):
                try:
                    # Check if file - can fail on network paths (WinError 4350)
                    if path.is_file():
                        if query.lower() in path.name.lower():
                            matches.append(path)
                            if len(matches) >= 1:  # Just get first match
                                break
                except OSError:
                    # Network file unavailable, skip it
                    pass
        except (PermissionError, OSError):
            pass

        if not matches:
            raise HTTPException(status_code=404, detail=f"No files found matching: {query}")

        filepath = str(matches[0])

    # Resolve path - handle tilde expansion
    if filepath.startswith('~'):
        filepath = os.path.expanduser(filepath)

    path = Path(filepath)
    if not path.is_absolute():
        working_dir = Path(engine.get_working_dir() or os.getcwd())
        path = working_dir / filepath

    path = path.resolve()
    logger.debug(f"  Resolved path: {path}")

    # Security: ensure path is within working directory tree or home directory
    working_dir = Path(engine.get_working_dir() or os.getcwd()).resolve()
    home_dir = Path.home().resolve()

    # Find common ancestor - allow any path that shares a common root with working_dir
    # This allows accessing parent directories (e.g., ../sample.yaml from temp/)
    # as long as they're within the same project tree
    def is_path_allowed(target: Path, base: Path) -> bool:
        """Check if target is within base's tree (parent or child)."""
        try:
            # Check if target is a child of base
            target.relative_to(base)
            return True
        except ValueError:
            pass
        try:
            # Check if base is a child of target (target is parent)
            base.relative_to(target)
            return True
        except ValueError:
            pass
        return False

    # Allow files in working directory tree (parent or child) or home directory tree
    if not (is_path_allowed(path, working_dir) or str(path).startswith(str(home_dir))):
        logger.warning(f"  Access denied: {path} not in {working_dir} tree or {home_dir}")
        raise HTTPException(
            status_code=403, detail="Access denied: path outside allowed directories"
        )

    if not path.exists():
        logger.warning(f"  File not found: {path}")
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {filepath} (resolved: {path})"
        )

    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {filepath}")

    # Image and PDF preview support
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico'}
    ext = path.suffix.lower()
    size = path.stat().st_size

    if ext in image_extensions or ext == '.pdf':
        # Return base64-encoded binary for preview
        import base64
        try:
            content_bytes = path.read_bytes()
            content_b64 = base64.b64encode(content_bytes).decode('ascii')

            # Determine MIME type and file type
            mime_types = {
                '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml',
                '.bmp': 'image/bmp', '.ico': 'image/x-icon', '.pdf': 'application/pdf'
            }
            mime_type = mime_types.get(ext, 'application/octet-stream')
            file_type = 'pdf' if ext == '.pdf' else 'image'

            return {
                "filename": path.name,
                "path": str(path),
                "type": file_type,
                "mime_type": mime_type,
                "content": content_b64,
                "size": size
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading {file_type}: {str(e)}")

    try:
        content = path.read_text(encoding='utf-8')
        lines = content.count('\n') + 1

        return {
            "filename": path.name,
            "path": str(path),
            "type": "text",
            "content": content,
            "size": size,
            "lines": lines
        }
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Cannot read binary file")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")


@app.post("/interrupt")
async def interrupt_stream(x_session_id: Optional[str] = Header(None)):
    """Interrupt the current streaming response.

    This sets a flag that the engine will check during streaming.
    The stream will stop at the next chunk and return partial results.

    Returns:
        JSON: {"interrupted": true}

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    engine.interrupt_stream()
    return {"interrupted": True}


@app.post("/consent")
async def respond_to_consent(
    request: ConsentRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Respond to a file edit consent request (Phase 1C: v1.11.0).

    This endpoint is called by the VSCode extension when the user
    responds to a consent dialog. It resolves the pending Future
    that the consent callback is waiting on.

    Args:
        request: ConsentRequest with file_path and response

    Returns:
        JSON: {"file_path": str, "response": str, "resolved": bool}

    v1.13.10: Supports X-Session-Id header for session isolation.
    v1.13.10: Now uses SessionManager.resolve_consent().
    """
    global session_manager

    # Determine session ID (use default if not provided)
    session_id = x_session_id or "default"

    from ppxai.common.consent import normalize_consent_response

    file_path = request.file_path

    # Normalize response to standard enum value (handles yes/Yes/YES/y/etc.)
    response = normalize_consent_response(request.response)

    # Resolve via SessionManager (v1.13.10)
    resolved = await session_manager.resolve_consent(session_id, file_path, response)
    if resolved:
        return {
            "file_path": file_path,
            "response": response,
            "resolved": True
        }

    # No pending request found
    raise HTTPException(status_code=404, detail=f"No pending consent request for: {file_path}")


@app.post("/shell-consent")
async def respond_to_shell_consent(
    request: ShellConsentRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Respond to a shell command consent request (v1.11.2).

    This endpoint is called by the VSCode extension when the user
    responds to a shell consent dialog. It resolves the pending Future
    that the shell consent callback is waiting on.

    Args:
        request: ShellConsentRequest with command, working_dir, and response

    Returns:
        JSON: {"command": str, "response": str, "resolved": bool}

    v1.13.10: Supports X-Session-Id header for session isolation.
    v1.13.10: Now uses SessionManager.resolve_shell_consent().
    """
    global session_manager

    # Determine session ID (use default if not provided)
    session_id = x_session_id or "default"

    from ppxai.common.consent import normalize_consent_response

    command = request.command

    # Normalize response to standard enum value (handles yes/Yes/YES/y/etc.)
    response = normalize_consent_response(request.response)

    # Resolve via SessionManager (v1.13.10)
    resolved = await session_manager.resolve_shell_consent(session_id, command, response)
    if resolved:
        return {
            "command": command,
            "response": response,
            "resolved": True
        }

    # No pending request found
    raise HTTPException(status_code=404, detail=f"No pending shell consent request for: {command}")


# === Agent Mode (v1.11.8) ===

@app.get("/agent/status")
async def get_agent_status(x_session_id: Optional[str] = Header(None)):
    """Get agent mode status (v1.11.8, v1.12.0).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    # Include checkpoint status in v1.12.0+
    checkpoint_status = engine.get_checkpoint_status()

    return {
        "agent_mode": engine.agent_mode,
        "tools_enabled": engine.tools_enabled,
        "checkpoint": checkpoint_status,
    }


@app.get("/agent/config")
async def get_agent_config(x_session_id: Optional[str] = Header(None)):
    """Get agent configuration (v1.11.9).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    return engine.get_agent_config()


@app.post("/agent/enable")
async def enable_agent_mode(x_session_id: Optional[str] = Header(None)):
    """Enable agent mode for autonomous task execution (v1.11.8).

    Agent mode automatically enables tools if not already enabled.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    engine.enable_agent_mode()
    logger.info(f"Agent mode enabled via API for session {session_id}")

    return {
        "ok": True,
        "agent_mode": True,
        "tools_enabled": engine.tools_enabled,
    }


@app.post("/agent/disable")
async def disable_agent_mode(x_session_id: Optional[str] = Header(None)):
    """Disable agent mode (v1.11.8).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    engine.disable_agent_mode()
    logger.info(f"Agent mode disabled via API for session {session_id}")

    return {
        "ok": True,
        "agent_mode": False,
    }


# === Checkpoint Management (v1.12.0) ===

@app.get("/checkpoint/status")
async def get_checkpoint_status(x_session_id: Optional[str] = Header(None)):
    """Get checkpoint system status (v1.12.0).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    return engine.get_checkpoint_status()


@app.post("/checkpoint/undo")
async def undo_last_checkpoint(x_session_id: Optional[str] = Header(None)):
    """Undo the last checkpoint (revert agent task changes) (v1.12.0).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    # Allow undo regardless of agent mode - checkpoints from previous sessions should be undoable
    # Check if checkpoints are enabled
    status = engine.get_checkpoint_status()
    if not status.get("enabled"):
        raise HTTPException(
            status_code=400,
            detail="Checkpoints are not enabled (no git repo or checkpoint backend disabled)"
        )

    # Check if there's a checkpoint to undo
    if not status.get("last_checkpoint"):
        raise HTTPException(
            status_code=400,
            detail="No checkpoint to undo (run an agent task first)"
        )

    # Check if checkpoint is still valid (not stale)
    # CRITICAL: Prevents reverting wrong commit when newer commits exist
    if not status.get("is_valid", True):  # Default to True for backward compat
        validity_reason = status.get("validity_reason", "Checkpoint is stale")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot undo: {validity_reason}. New commits have been made since the agent task. "
                   f"Use 'git revert {status.get('last_checkpoint', '')[:8]}' manually if you still want to revert."
        )

    # Check for uncommitted changes before undo (git revert requires clean working tree)
    if status.get("backend") == "git":
        import subprocess
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=engine.context_injector.working_dir,
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                raise HTTPException(
                    status_code=400,
                    detail="Cannot undo: uncommitted changes in working directory. Commit or stash changes first."
                )
        except subprocess.CalledProcessError:
            pass  # If git status fails, let the undo attempt proceed

    # Perform undo
    success = engine.undo_last_checkpoint()
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to undo checkpoint (git revert may have failed)"
        )

    logger.info(f"Checkpoint undo successful via API for session {session_id}")

    return {
        "success": True,
        "message": f"Checkpoint {status.get('last_checkpoint', '')[:8]} reverted successfully",
        "backend": status.get("backend"),
        "checkpoint_id": status.get("last_checkpoint"),
    }


@app.get("/checkpoint/list")
async def list_checkpoints(
    limit: int = 10,
    x_session_id: Optional[str] = Header(None)
):
    """List recent checkpoints (v1.12.4).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    checkpoints = engine.list_checkpoints(limit=limit)
    return {
        "checkpoints": checkpoints,
        "count": len(checkpoints),
    }


@app.post("/checkpoint/backend")
async def set_checkpoint_backend(
    request: dict,
    x_session_id: Optional[str] = Header(None)
):
    """Set the checkpoint backend (v1.12.4).

    Body: {"backend": "git" | "file" | "auto" | "none"}

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    backend = request.get("backend")
    if not backend:
        raise HTTPException(status_code=400, detail="Missing 'backend' field")

    valid_backends = ('git', 'file', 'auto', 'none')
    if backend not in valid_backends:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid backend: {backend}. Valid options: {', '.join(valid_backends)}"
        )

    success = engine.set_checkpoint_backend(backend)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to set checkpoint backend")

    # Return the new status
    status = engine.get_checkpoint_status()
    return {
        "success": True,
        "backend": status.get("backend"),
        "enabled": status.get("enabled"),
    }


@app.post("/checkpoint/clear")
async def clear_file_checkpoints(
    request: dict = None,
    x_session_id: Optional[str] = Header(None)
):
    """Clear old file-based checkpoint snapshots (v1.12.4).

    Body (optional): {"keep_last": 0}

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    keep_last = 0
    if request:
        keep_last = request.get("keep_last", 0)

    status = engine.get_checkpoint_status()
    if status.get("backend") != "file":
        raise HTTPException(
            status_code=400,
            detail=f"Clear only applies to file-based checkpoints. Current backend: {status.get('backend', 'none')}"
        )

    removed = engine.clear_file_checkpoints(keep_last=keep_last)
    return {
        "success": True,
        "removed": removed,
        "message": f"Cleared {removed} checkpoint(s)",
    }


@app.get("/checkpoint/info/{checkpoint_id}")
async def get_checkpoint_info(
    checkpoint_id: str,
    x_session_id: Optional[str] = Header(None)
):
    """Get details about a specific checkpoint.

    Supports prefix matching - e.g., "abc123" matches "abc123def456".

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    checkpoints = engine.list_checkpoints(limit=20)

    # Find matching checkpoint (prefix match)
    matching = [cp for cp in checkpoints if cp.get("id", "").startswith(checkpoint_id)]

    if not matching:
        raise HTTPException(
            status_code=404,
            detail=f"Checkpoint not found: {checkpoint_id}"
        )

    cp = matching[0]

    # Check if this is the current checkpoint
    status = engine.get_checkpoint_status()
    is_current = status.get("last_checkpoint", "").startswith(checkpoint_id)

    return {
        "id": cp.get("id", ""),
        "description": cp.get("description", ""),
        "timestamp": cp.get("timestamp", ""),
        "is_current": is_current,
        "is_valid": status.get("is_valid") if is_current else False,
        "status": "current" if is_current else "historical",
    }


# === Debug Logging (v1.11.2) ===

@app.get("/debug-log")
async def get_debug_log_status():
    """Get server debug logging status."""
    return {
        "enabled": logger.enabled,
        "log_file": str(logger.log_file) if logger.log_file else None,
    }


@app.post("/debug-log")
async def set_debug_log(request: dict):
    """Enable or disable server debug logging.

    Body: {"enabled": true/false}
    """
    enabled = request.get("enabled", False)

    if enabled:
        logger.enable()
        logger.info("Debug logging enabled via API")
    else:
        logger.info("Debug logging disabled via API")
        logger.disable()

    return {
        "enabled": logger.enabled,
        "log_file": str(logger.log_file) if logger.log_file else None,
    }


# === Web UI Static Files (must be after all API routes) ===

@app.get("/")
async def serve_index():
    """Serve the web UI index.html."""
    index_file = WEB_UI_DIR / 'index.html'
    if index_file.exists():
        return FileResponse(index_file, media_type='text/html')
    return HTMLResponse(
        content="<h1>ppxai Web UI not found</h1><p>Install web UI to ~/.ppxai/web/</p>",
        status_code=404
    )


@app.get("/app.js")
async def serve_app_js():
    """Serve app.js with no-cache headers to ensure fresh content."""
    return FileResponse(
        WEB_UI_DIR / 'app.js',
        media_type='application/javascript',
        headers={"Cache-Control": "no-cache, must-revalidate"}
    )


@app.get("/styles.css")
async def serve_styles_css():
    """Serve styles.css with no-cache headers."""
    return FileResponse(
        WEB_UI_DIR / 'styles.css',
        media_type='text/css',
        headers={"Cache-Control": "no-cache, must-revalidate"}
    )


@app.get("/lib/{filename:path}")
async def serve_lib(filename: str):
    """Serve library files."""
    file_path = WEB_UI_DIR / 'lib' / filename
    if file_path.exists() and file_path.is_file():
        suffix = file_path.suffix.lower()
        content_types = {
            '.js': 'application/javascript',
            '.css': 'text/css',
            '.json': 'application/json',
        }
        media_type = content_types.get(suffix, 'application/octet-stream')
        return FileResponse(file_path, media_type=media_type)
    raise HTTPException(status_code=404, detail=f"Library file not found: {filename}")


@app.get("/shared/{filename:path}")
async def serve_shared(filename: str):
    """Serve shared module files (v1.13.10)."""
    file_path = WEB_UI_DIR / 'shared' / filename
    if file_path.exists() and file_path.is_file():
        suffix = file_path.suffix.lower()
        content_types = {
            '.js': 'application/javascript',
            '.css': 'text/css',
            '.json': 'application/json',
        }
        media_type = content_types.get(suffix, 'application/octet-stream')
        return FileResponse(file_path, media_type=media_type)
    raise HTTPException(status_code=404, detail=f"Shared file not found: {filename}")


@app.get("/components/{filename:path}")
async def serve_components(filename: str):
    """Serve component files (v1.13.8 data viewers)."""
    file_path = WEB_UI_DIR / 'components' / filename
    if file_path.exists() and file_path.is_file():
        suffix = file_path.suffix.lower()
        content_types = {
            '.js': 'application/javascript',
            '.css': 'text/css',
            '.json': 'application/json',
        }
        media_type = content_types.get(suffix, 'application/octet-stream')
        return FileResponse(file_path, media_type=media_type)
    raise HTTPException(status_code=404, detail=f"Component file not found: {filename}")


@app.get("/styles/{filename:path}")
async def serve_styles(filename: str):
    """Serve additional style files (v1.13.8 data viewers)."""
    file_path = WEB_UI_DIR / 'styles' / filename
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path, media_type='text/css')
    raise HTTPException(status_code=404, detail=f"Style file not found: {filename}")


@app.get("/favicon.ico")
async def serve_favicon_ico():
    """Serve favicon.ico (redirect to favicon.png)."""
    file_path = WEB_UI_DIR / 'favicon.png'
    if file_path.exists():
        return FileResponse(file_path, media_type='image/png')
    raise HTTPException(status_code=404, detail="Favicon not found")


@app.get("/favicon.png")
async def serve_favicon_png():
    """Serve favicon.png."""
    file_path = WEB_UI_DIR / 'favicon.png'
    if file_path.exists():
        return FileResponse(file_path, media_type='image/png')
    raise HTTPException(status_code=404, detail="Favicon not found")


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
    import uvicorn
    import signal
    global _shutdown_event, session_manager

    config = uvicorn.Config(
        app_ref,
        host=host,
        port=port,
        log_level=log_level,
    )
    server = uvicorn.Server(config)

    # Set up signal handlers to capture shutdown reason
    def handle_signal(signum, frame):
        sig_name = signal.Signals(signum).name
        reason = "ctrl_c" if signum == signal.SIGINT else "signal"
        logger.info(f"Received {sig_name}, initiating shutdown")
        if session_manager:
            session_manager.request_shutdown(reason)
        server.should_exit = True

    # Install signal handlers (uvicorn's defaults will be overridden)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Create shutdown listener task
    async def shutdown_listener():
        global _shutdown_event
        # Wait for shutdown event to be created (happens in lifespan)
        while _shutdown_event is None:
            await asyncio.sleep(0.1)
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
    import uvicorn

    parser = argparse.ArgumentParser(description="ppxai HTTP Server")
    parser.add_argument("--version", "-v", action="version", version=f"ppxai-server {__version__}")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=54320, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    args = parser.parse_args()

    # Initialize configuration system (v1.13.10: explicit initialization)
    from ..config import initialize
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
        # (string import doesn't work in frozen apps)
        # Use graceful shutdown handler
        asyncio.run(_run_server_with_graceful_shutdown(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
        ))
    else:
        # Running from source - use string import
        # Note: --reload requires uvicorn.run() directly, not our custom wrapper
        if args.reload:
            uvicorn.run(
                "ppxai.server.http:app",
                host=args.host,
                port=args.port,
                reload=True,
                log_level="info",
            )
        else:
            # Use graceful shutdown handler
            asyncio.run(_run_server_with_graceful_shutdown(
                "ppxai.server.http:app",
                host=args.host,
                port=args.port,
                log_level="info",
            ))


def run_desktop():
    """Run desktop web app - starts server and opens browser (CLI entry point).

    This is the development-friendly entry point that:
    1. Starts the HTTP server (Python via uvicorn)
    2. Opens the default web browser to the UI

    Usage:
        uv run ppxai-desktop        # Development
        ./ppxai-desktop             # Production binary
    """
    import webbrowser
    import threading
    import time
    import uvicorn

    parser = argparse.ArgumentParser(description="ppxai Desktop Web App")
    parser.add_argument("--version", "-v", action="version", version=f"ppxai-desktop {__version__}")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=54320, help="Port to bind to")
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

    # Check if running as frozen executable (PyInstaller)
    # Use graceful shutdown handler
    if getattr(sys, 'frozen', False):
        asyncio.run(_run_server_with_graceful_shutdown(
            app,
            host=args.host,
            port=args.port,
            log_level="warning",  # Less verbose for desktop app
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

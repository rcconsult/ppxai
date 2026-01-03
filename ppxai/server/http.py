"""
FastAPI HTTP Server with SSE streaming for ppxai.

This server provides:
- SSE streaming for chat responses (POST /chat)
- REST endpoints for configuration (providers, models, tools)
- Health check endpoint

Usage:
    uv run ppxai-server
    uv run ppxai-server --port 8080
    uv run ppxai-server --host 0.0.0.0 --port 8080
"""

import argparse
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from ..engine import EngineClient, EventType
from ..common.logger import get_logger
from .. import __version__

# Global engine instance (managed by lifespan)
engine: Optional[EngineClient] = None

# Server logger (v1.11.2)
logger = get_logger("server")

# Request serialization lock (v1.12.0)
# Prevents concurrent chat requests from corrupting conversation state
chat_lock: asyncio.Lock = None

# Consent request tracking (Phase 1C: v1.11.0, v1.11.2)
# Maps file_path -> asyncio.Future[tuple[bool, str]]
pending_consent_requests: dict[str, asyncio.Future] = {}
# Maps command -> asyncio.Future[tuple[bool, str]]
pending_shell_consent_requests: dict[str, asyncio.Future] = {}


async def http_consent_handler(file_path: str) -> tuple[bool, str]:
    """
    Handle file edit consent request via HTTP (Phase 1C: v1.11.0).

    This function:
    1. Creates a Future to wait for user response
    2. Stores it in pending_consent_requests
    3. Returns when /consent endpoint resolves the Future

    The consent request event is emitted via SSE in the event generator.

    Args:
        file_path: Path to file that needs editing

    Returns:
        tuple: (approved: bool, response: str)
    """
    global pending_consent_requests

    # Create a future for this consent request
    future = asyncio.Future()
    pending_consent_requests[file_path] = future

    # Wait for response from /consent endpoint (with timeout)
    try:
        approved, response = await asyncio.wait_for(future, timeout=300.0)  # 5 min timeout
        return (approved, response)
    except asyncio.TimeoutError:
        # Timeout - deny for safety
        pending_consent_requests.pop(file_path, None)
        return (False, 'n')
    finally:
        # Cleanup
        pending_consent_requests.pop(file_path, None)


async def http_shell_consent_handler(command: str, working_dir: str, risk_level: str) -> tuple[bool, str]:
    """
    Handle shell command consent request via HTTP (v1.11.2).

    This function:
    1. Creates a Future for the consent decision
    2. Stores it in pending_shell_consent_requests
    3. Returns when /shell-consent endpoint resolves the Future

    The consent request event is emitted via SSE in the event generator.

    Args:
        command: Shell command to execute
        working_dir: Working directory for the command
        risk_level: Risk level classification

    Returns:
        tuple: (approved: bool, response: str)
    """
    global pending_shell_consent_requests

    # Create a future for this consent request
    future: asyncio.Future[tuple[bool, str]] = asyncio.Future()
    pending_shell_consent_requests[command] = future

    # Wait for response from /shell-consent endpoint (with timeout)
    try:
        # Wait up to 60 seconds for user response
        approved, response = await asyncio.wait_for(future, timeout=60.0)
        return (approved, response)
    except asyncio.TimeoutError:
        # Timeout - deny for safety
        pending_shell_consent_requests.pop(command, None)
        return (False, 'n')
    finally:
        # Cleanup
        pending_shell_consent_requests.pop(command, None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan (startup/shutdown)."""
    global engine, chat_lock

    # Startup: Initialize engine with consent callbacks (v1.11.0, v1.11.2)
    logger.info("Server starting up - initializing EngineClient")
    engine = EngineClient(
        consent_callback=http_consent_handler,
        shell_consent_callback=http_shell_consent_handler
    )
    logger.info(f"EngineClient initialized - provider: {engine.provider_name}, model: {engine.model}")

    # Initialize chat lock (v1.12.0)
    chat_lock = asyncio.Lock()
    logger.info("Chat request lock initialized")

    # Set default provider (tries perplexity first, falls back to gemini)
    from ..config import get_available_providers
    providers = get_available_providers()
    if providers:
        engine.set_provider(providers[0])

    print(f"ppxai HTTP server started")
    print(f"Provider: {engine.provider_name}")
    print(f"Model: {engine.model}")

    yield

    # Shutdown: Cleanup
    # v1.12.3: Save usage to persistent storage before shutdown
    if engine and engine.session:
        try:
            engine.session.save_usage_to_persistent_storage()
            logger.info("Session usage saved to persistent storage")
        except Exception as e:
            logger.warning(f"Failed to save usage to persistent storage: {e}")

    pending_consent_requests.clear()
    pending_shell_consent_requests.clear()
    engine = None
    print("ppxai HTTP server stopped")


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
)


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

async def sse_event_generator(prompt: str) -> AsyncGenerator[str, None]:
    """Generate SSE events from engine chat.

    SSE format: data: {json}\n\n
    Each event is yielded immediately with a sleep(0) to force flush.
    Phase 1C: Also checks consent_event_queue for pending consent requests.
    v1.11.2: Added debug logging for troubleshooting.
    """
    global engine
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

        # v1.12.0: Session cleanup for message alternation errors
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

    # v1.12.3: Auto-save usage to persistent storage after each chat
    # This ensures usage is never lost even if server crashes
    try:
        if engine and engine.session:
            engine.session.save_usage_to_persistent_storage()
    except Exception as save_error:
        logger.warning(f"Failed to auto-save usage: {save_error}")


async def sse_coding_task_generator(
    prompt: str,
    task_type: str
) -> AsyncGenerator[str, None]:
    """Generate SSE events from engine coding task."""
    global engine
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

        # v1.12.0: Session cleanup for message alternation errors
        if "alternation" in error_str.lower() or "alternate" in error_str.lower():
            try:
                messages = engine.session.messages
                while len(messages) > 1 and messages[-1].role == "user" and messages[-2].role == "user":
                    removed = messages.pop()
                    logger.info(f"Session cleanup: removed orphan user message (len={len(removed.content)})")
            except Exception as cleanup_error:
                logger.error(f"Session cleanup failed: {cleanup_error}")

    # v1.12.3: Auto-save usage to persistent storage after each coding task
    try:
        if engine and engine.session:
            engine.session.save_usage_to_persistent_storage()
    except Exception as save_error:
        logger.warning(f"Failed to auto-save usage: {save_error}")


# === API Endpoints ===

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": __version__,
        "engine": engine is not None,
    }


@app.get("/status")
async def get_status():
    """Get current engine status."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    return {
        "provider": engine.provider_name,
        "model": engine.model,
        "tools_enabled": engine.tools_enabled,
        "agent_mode": engine.agent_mode,  # v1.11.8
        "auto_inject_context": engine.auto_inject_context,
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    """Chat endpoint with SSE streaming (v1.11.2: added logging, v1.12.0: added request locking).

    Returns Server-Sent Events stream with chat response chunks.

    v1.12.0: Serializes chat requests to prevent concurrent execution from
    corrupting conversation state. If agent is running, subsequent requests
    will wait for completion.
    """
    global engine, chat_lock
    if not engine:
        logger.error("Chat endpoint called but engine not initialized")
        raise HTTPException(status_code=503, detail="Engine not initialized")

    logger.log_http_request("POST", "/chat", "vscode")

    # Acquire lock to serialize chat requests (v1.12.0)
    async with chat_lock:
        logger.info("Chat lock acquired - processing request")

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
            async for event in sse_event_generator(request.message):
                yield event
            logger.info("Chat request completed - releasing lock")

        return StreamingResponse(
            locked_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            }
        )


@app.post("/coding_task")
async def coding_task(request: CodingTaskRequest):
    """Coding task endpoint with SSE streaming (v1.12.0: added request locking).

    Supports task types: generate, debug, explain, test, docs, implement

    v1.12.0: Serializes coding task requests to prevent concurrent execution.
    """
    global engine, chat_lock
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    # Acquire lock to serialize requests (v1.12.0)
    async with chat_lock:
        logger.info("Coding task lock acquired - processing request")

        # Set provider/model if specified
        if request.provider:
            engine.set_provider(request.provider)
        if request.model:
            engine.set_model(request.model)

        # Wrap generator to ensure lock is held during streaming
        async def locked_generator():
            """Generator that streams events while holding the lock."""
            async for event in sse_coding_task_generator(request.message, request.task_type):
                yield event
            logger.info("Coding task completed - releasing lock")

        return StreamingResponse(
            locked_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )


# === Provider/Model Management ===

@app.get("/providers")
async def get_providers():
    """Get list of available providers."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

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
async def set_provider(request: SetProviderRequest):
    """Set the active provider."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

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
async def get_models():
    """Get list of models for current provider."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

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
async def set_model(request: SetModelRequest):
    """Set the active model."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    success = engine.set_model(request.model)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to set model: {request.model}")

    return {
        "model": engine.model,
        "provider": engine.provider_name,
    }


# === Tools Management ===

@app.get("/tools")
async def get_tools():
    """Get list of available tools."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    tools = engine.list_tools()

    # Get consent mode from session (v1.11.9)
    consent_mode = "default"
    try:
        if hasattr(engine, 'session') and hasattr(engine.session, 'edit_consent_mode'):
            consent_mode = engine.session.edit_consent_mode
    except Exception:
        pass

    return {
        "tools": tools,  # Already list of {"name": ..., "description": ...}
        "enabled": engine.tools_enabled,
        "max_iterations": getattr(engine, 'tool_max_iterations', 15),
        "consent_mode": consent_mode,
        "verbose": getattr(engine, '_tools_verbose', False),  # v1.12.0
    }


@app.post("/tools")
async def set_tools(request: ToolsRequest):
    """Enable or disable tools."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    if request.enabled:
        engine.enable_tools()
    else:
        engine.disable_tools()

    return {
        "enabled": engine.tools_enabled,
    }


@app.post("/tools/config")
async def set_tools_config(request: ToolsConfigRequest):
    """Configure tool settings (e.g., max_iterations)."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    success = engine.set_tool_config(request.setting, request.value)
    if not success:
        raise HTTPException(status_code=400, detail=f"Unknown setting: {request.setting}")

    return {
        "setting": request.setting,
        "value": request.value,
        "success": True,
    }


# === Usage Statistics ===

@app.get("/usage")
async def get_usage():
    """Get token usage statistics for current session.

    Returns full usage including per-model breakdown (v1.12.2).
    """
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    return engine.get_usage()


class UsageDisplayModeRequest(BaseModel):
    """Request body for setting usage display mode."""
    mode: str  # "session", "provider", "model", or "off"


@app.post("/usage/display")
async def set_usage_display_mode(request: UsageDisplayModeRequest):
    """Set usage display mode for status line (v1.12.2).

    Args:
        mode: One of "session", "provider", "model", "off"
            - session: Show session totals
            - provider: Show current provider totals
            - model: Show current model totals
            - off: Hide usage from status line
    """
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    valid_modes = {"session", "provider", "model", "off"}
    if request.mode not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {request.mode}. Valid modes: {', '.join(valid_modes)}"
        )

    success = engine.session.set_usage_display_mode(request.mode)
    return {"mode": request.mode, "success": success}


@app.get("/usage/display")
async def get_usage_display_mode():
    """Get current usage display mode (v1.12.2)."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    return {"mode": engine.session.usage_display_mode}


@app.post("/usage/reset")
async def reset_usage():
    """Reset all usage statistics to zero (v1.12.2)."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

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

@app.post("/context/working_dir")
async def set_working_dir(request: WorkingDirRequest):
    """Set the working directory for file path resolution."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    engine.set_working_dir(request.path)
    return {"path": request.path, "success": True}


@app.post("/context/auto_inject")
async def set_auto_inject(request: AutoInjectRequest):
    """Enable or disable automatic context injection."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    engine.set_auto_inject(request.enabled)
    return {"enabled": request.enabled, "success": True}


@app.get("/context/auto_inject")
async def get_auto_inject():
    """Get auto-inject context status."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    return {"enabled": engine.get_auto_inject()}


# === Session Management ===

@app.get("/sessions")
async def get_sessions():
    """Get list of saved sessions."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    sessions = engine.list_sessions()
    return {
        "sessions": [
            {
                "name": s.name,
                "created_at": s.created_at,
                "provider": s.provider,
                "model": s.model,
                "message_count": s.message_count,
            }
            for s in sessions
        ]
    }


@app.post("/sessions/save")
async def save_session(name: Optional[str] = None):
    """Save current session."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    saved_name = engine.save_session(name)
    return {"name": saved_name}


@app.post("/export")
async def export_answer(request: Request):
    """Export last answer to markdown."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

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
async def load_session(name: str):
    """Load a saved session."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    success = engine.load_session(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Session not found: {name}")

    return {"name": name, "loaded": True}


@app.post("/sessions/clear")
async def clear_session():
    """Clear current session."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    engine.clear_history()
    return {"cleared": True}


@app.post("/interrupt")
async def interrupt_stream():
    """Interrupt the current streaming response.

    This sets a flag that the engine will check during streaming.
    The stream will stop at the next chunk and return partial results.

    Returns:
        JSON: {"interrupted": true}
    """
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    engine.interrupt_stream()
    return {"interrupted": True}


@app.post("/consent")
async def respond_to_consent(request: ConsentRequest):
    """Respond to a file edit consent request (Phase 1C: v1.11.0).

    This endpoint is called by the VSCode extension when the user
    responds to a consent dialog. It resolves the pending Future
    that the consent callback is waiting on.

    Args:
        request: ConsentRequest with file_path and response

    Returns:
        JSON: {"file_path": str, "response": str, "resolved": bool}
    """
    global pending_consent_requests

    file_path = request.file_path
    response = request.response.lower()

    # Validate response
    if response not in ['y', 'n', 'always', 'never']:
        raise HTTPException(status_code=400, detail=f"Invalid response: {response}. Must be y, n, always, or never")

    # Find and resolve the pending request
    if file_path in pending_consent_requests:
        future = pending_consent_requests[file_path]
        if not future.done():
            # Resolve the future with (approved, response)
            approved = response in ['y', 'always']
            future.set_result((approved, response))
            return {
                "file_path": file_path,
                "response": response,
                "resolved": True
            }

    # No pending request found
    raise HTTPException(status_code=404, detail=f"No pending consent request for: {file_path}")


@app.post("/shell-consent")
async def respond_to_shell_consent(request: ShellConsentRequest):
    """Respond to a shell command consent request (v1.11.2).

    This endpoint is called by the VSCode extension when the user
    responds to a shell consent dialog. It resolves the pending Future
    that the shell consent callback is waiting on.

    Args:
        request: ShellConsentRequest with command, working_dir, and response

    Returns:
        JSON: {"command": str, "response": str, "resolved": bool}
    """
    global pending_shell_consent_requests

    command = request.command
    response = request.response.lower()

    # Validate response
    if response not in ['y', 'n', 'always', 'never']:
        raise HTTPException(status_code=400, detail=f"Invalid response: {response}. Must be y, n, always, or never")

    # Find and resolve the pending request
    if command in pending_shell_consent_requests:
        future = pending_shell_consent_requests[command]
        if not future.done():
            # Resolve the future with (approved, response)
            approved = response in ['y', 'always']
            future.set_result((approved, response))
            return {
                "command": command,
                "response": response,
                "resolved": True
            }

    # No pending request found
    raise HTTPException(status_code=404, detail=f"No pending shell consent request for: {command}")


# === Agent Mode (v1.11.8) ===

@app.get("/agent/status")
async def get_agent_status():
    """Get agent mode status (v1.11.8, v1.12.0)."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    # Include checkpoint status in v1.12.0+
    checkpoint_status = engine.get_checkpoint_status()

    return {
        "agent_mode": engine.agent_mode,
        "tools_enabled": engine.tools_enabled,
        "checkpoint": checkpoint_status,  # v1.12.0
    }


@app.get("/agent/config")
async def get_agent_config():
    """Get agent configuration (v1.11.9)."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    return engine.get_agent_config()


@app.post("/agent/enable")
async def enable_agent_mode():
    """Enable agent mode for autonomous task execution (v1.11.8).

    Agent mode automatically enables tools if not already enabled.
    """
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    engine.enable_agent_mode()
    logger.info("Agent mode enabled via API")

    return {
        "ok": True,
        "agent_mode": True,
        "tools_enabled": engine.tools_enabled,
    }


@app.post("/agent/disable")
async def disable_agent_mode():
    """Disable agent mode (v1.11.8)."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    engine.disable_agent_mode()
    logger.info("Agent mode disabled via API")

    return {
        "ok": True,
        "agent_mode": False,
    }


# === Checkpoint Management (v1.12.0) ===

@app.get("/checkpoint/status")
async def get_checkpoint_status():
    """Get checkpoint system status (v1.12.0)."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    return engine.get_checkpoint_status()


@app.post("/checkpoint/undo")
async def undo_last_checkpoint():
    """Undo the last checkpoint (revert agent task changes) (v1.12.0)."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    # v1.12.0: Allow undo regardless of agent mode - checkpoints from previous sessions should be undoable
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

    # v1.12.1: Check if checkpoint is still valid (not stale)
    # CRITICAL: Prevents reverting wrong commit when newer commits exist
    if not status.get("is_valid", True):  # Default to True for backward compat
        validity_reason = status.get("validity_reason", "Checkpoint is stale")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot undo: {validity_reason}. New commits have been made since the agent task. "
                   f"Use 'git revert {status.get('last_checkpoint', '')[:8]}' manually if you still want to revert."
        )

    # v1.12.0: Check for uncommitted changes before undo (git revert requires clean working tree)
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

    logger.info("Checkpoint undo successful via API")

    return {
        "success": True,
        "message": f"Checkpoint {status.get('last_checkpoint', '')[:8]} reverted successfully",
        "backend": status.get("backend"),
        "checkpoint_id": status.get("last_checkpoint"),
    }


@app.get("/checkpoint/list")
async def list_checkpoints(limit: int = 10):
    """List recent checkpoints (v1.12.4)."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    checkpoints = engine.list_checkpoints(limit=limit)
    return {
        "checkpoints": checkpoints,
        "count": len(checkpoints),
    }


@app.post("/checkpoint/backend")
async def set_checkpoint_backend(request: dict):
    """Set the checkpoint backend (v1.12.4).

    Body: {"backend": "git" | "file" | "auto" | "none"}
    """
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

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
async def clear_file_checkpoints(request: dict = None):
    """Clear old file-based checkpoint snapshots (v1.12.4).

    Body (optional): {"keep_last": 0}
    """
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    keep_last = 0
    if request:
        keep_last = request.get("keep_last", 0)

    status = engine.get_checkpoint_status()
    if status.get("backend") != "file":
        raise HTTPException(
            status_code=400,
            detail="Clear only applies to file-based checkpoints. Current backend: " + status.get("backend", "none")
        )

    removed = engine.clear_file_checkpoints(keep_last=keep_last)
    return {
        "success": True,
        "removed": removed,
        "message": f"Cleared {removed} checkpoint(s)",
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


# === CLI Entry Point ===

def run_server():
    """Run the HTTP server (CLI entry point)."""
    import uvicorn

    parser = argparse.ArgumentParser(description="ppxai HTTP Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=54320, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    args = parser.parse_args()

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
    print()

    # Check if running as frozen executable (PyInstaller)
    if getattr(sys, 'frozen', False):
        # Running as bundled executable - use app object directly
        # (string import doesn't work in frozen apps)
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
        )
    else:
        # Running from source - use string import (supports --reload)
        uvicorn.run(
            "ppxai.server.http:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level="info",
        )


if __name__ == "__main__":
    run_server()

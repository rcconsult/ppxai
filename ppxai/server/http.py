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

# Global engine instance (managed by lifespan)
engine: Optional[EngineClient] = None

# Server logger (v1.11.2)
logger = get_logger("server")

# Consent request tracking (Phase 1C: v1.11.0)
# Maps file_path -> asyncio.Future[tuple[bool, str]]
pending_consent_requests: dict[str, asyncio.Future] = {}


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan (startup/shutdown)."""
    global engine

    # Startup: Initialize engine with consent callback (Phase 1C: v1.11.0)
    logger.info("Server starting up - initializing EngineClient")
    engine = EngineClient(consent_callback=http_consent_handler)
    logger.info(f"EngineClient initialized - provider: {engine.provider_name}, model: {engine.model}")

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
    pending_consent_requests.clear()
    engine = None
    print("ppxai HTTP server stopped")


# Create FastAPI app with lifespan
app = FastAPI(
    title="ppxai HTTP Server",
    description="HTTP + SSE server for ppxai AI chat",
    version="1.10.4",
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
        yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"


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
        yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"


# === API Endpoints ===

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "1.11.2",
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
        "auto_inject_context": engine.auto_inject_context,
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    """Chat endpoint with SSE streaming (v1.11.2: added logging).

    Returns Server-Sent Events stream with chat response chunks.
    """
    global engine
    if not engine:
        logger.error("Chat endpoint called but engine not initialized")
        raise HTTPException(status_code=503, detail="Engine not initialized")

    logger.log_http_request("POST", "/chat", "vscode")

    # Set provider/model if specified
    if request.provider:
        logger.info(f"Switching provider to: {request.provider}")
        engine.set_provider(request.provider)
    if request.model:
        logger.info(f"Switching model to: {request.model}")
        engine.set_model(request.model)

    return StreamingResponse(
        sse_event_generator(request.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@app.post("/coding_task")
async def coding_task(request: CodingTaskRequest):
    """Coding task endpoint with SSE streaming.

    Supports task types: generate, debug, explain, test, docs, implement
    """
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    # Set provider/model if specified
    if request.provider:
        engine.set_provider(request.provider)
    if request.model:
        engine.set_model(request.model)

    return StreamingResponse(
        sse_coding_task_generator(request.message, request.task_type),
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
    return {
        "tools": tools,  # Already list of {"name": ..., "description": ...}
        "enabled": engine.tools_enabled,
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
    """Get token usage statistics for current session."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    return engine.get_usage()


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

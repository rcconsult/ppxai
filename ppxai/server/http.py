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
from typing import Optional, AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from ..engine import EngineClient, EventType

# Create FastAPI app
app = FastAPI(
    title="ppxai HTTP Server",
    description="HTTP + SSE server for ppxai AI chat",
    version="1.9.2",
)

# Add CORS middleware for webview/browser access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global engine instance (created on startup)
engine: Optional[EngineClient] = None


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


# === SSE Streaming ===

async def sse_event_generator(prompt: str) -> AsyncGenerator[str, None]:
    """Generate SSE events from engine chat.

    SSE format: data: {json}\n\n
    """
    global engine
    if not engine:
        yield f"data: {json.dumps({'type': 'error', 'data': 'Engine not initialized'})}\n\n"
        return

    try:
        async for event in engine.chat(prompt):
            event_data = {
                "type": event.type.value,
                "data": event.data,
            }
            if event.metadata:
                event_data["metadata"] = event.metadata
            yield f"data: {json.dumps(event_data)}\n\n"
    except Exception as e:
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
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"


# === API Endpoints ===

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "1.9.2",
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
    """Chat endpoint with SSE streaming.

    Returns Server-Sent Events stream with chat response chunks.
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


# === Startup/Shutdown ===

@app.on_event("startup")
async def startup_event():
    """Initialize engine on server startup."""
    global engine
    engine = EngineClient()

    # Set default provider (tries perplexity first, falls back to gemini)
    from ..config import get_available_providers
    providers = get_available_providers()
    if providers:
        engine.set_provider(providers[0])

    print(f"ppxai HTTP server started")
    print(f"Provider: {engine.provider_name}")
    print(f"Model: {engine.model}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on server shutdown."""
    global engine
    engine = None
    print("ppxai HTTP server stopped")


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
    print("  GET  /health        - Health check")
    print("  GET  /status        - Current status")
    print()

    uvicorn.run(
        "ppxai.server.http:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    run_server()

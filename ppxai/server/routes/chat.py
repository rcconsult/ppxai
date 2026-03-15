"""
Chat and coding task endpoints with SSE streaming.
"""

import asyncio

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from typing import Optional

from ...common.logger import get_logger
from ..models import ChatRequest, CodingTaskRequest
from ..state import get_or_create_session
from ..streaming import sse_event_generator, sse_coding_task_generator

logger = get_logger("server")

router = APIRouter()


@router.post("/chat")
async def chat(
    request: ChatRequest,
    raw_request: Request,
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
            engine.set_model(request.model, reset_context=False)

        # Wrap generator to ensure lock is held during streaming
        async def locked_generator():
            """Generator that streams events while holding the lock."""
            async for event in sse_event_generator(request.message, engine, session_id, request=raw_request):
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


@router.post("/coding_task")
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
            engine.set_model(request.model, reset_context=False)

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

"""
Chat and coding task endpoints with SSE streaming.
"""

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from typing import Optional

from ...common.logger import get_logger
from ..models import ChatRequest, CodingTaskRequest
from ..state import Session, get_session
from ..streaming import sse_event_generator, sse_coding_task_generator

logger = get_logger("server")

router = APIRouter()


@router.post("/chat")
async def chat(
    request: ChatRequest,
    raw_request: Request,
    s: Session = Depends(get_session)
):
    """Chat endpoint with SSE streaming (v1.11.2: added logging, v1.12.0: added request locking).

    Returns Server-Sent Events stream with chat response chunks.

    v1.12.0: Serializes chat requests to prevent concurrent execution from
    corrupting conversation state. If agent is running, subsequent requests
    will wait for completion.

    v1.13.10: Supports X-Session-Id header for session isolation.
    Each session has its own conversation history, working directory, and state.
    """

    logger.log_http_request("POST", "/chat", f"session={s.id}")

    # Acquire lock to serialize chat requests (v1.12.0)
    async with s.lock:
        logger.info(f"Chat lock acquired for session {s.id} - processing request")

        # Set provider/model if specified
        if request.provider:
            logger.info(f"Switching provider to: {request.provider}")
            s.engine.set_provider(request.provider)
        if request.model:
            logger.info(f"Switching model to: {request.model}")
            s.engine.set_model(request.model, reset_context=False)

        # Wrap generator to ensure lock is held during streaming
        async def locked_generator():
            """Generator that streams events while holding the lock."""
            async for event in sse_event_generator(request.message, s.engine, s.id, request=raw_request):
                yield event
            logger.info(f"Chat request completed for session {s.id} - releasing lock")

        return StreamingResponse(
            locked_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
                "X-Session-Id": s.id,  # Return session ID
            }
        )


@router.post("/coding_task")
async def coding_task(
    request: CodingTaskRequest,
    s: Session = Depends(get_session)
):
    """Coding task endpoint with SSE streaming (v1.12.0: added request locking).

    Supports task types: generate, debug, explain, test, docs, implement

    v1.12.0: Serializes coding task requests to prevent concurrent execution.
    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    # Acquire lock to serialize requests (v1.12.0)
    async with s.lock:
        logger.info(f"Coding task lock acquired for session {s.id} - processing request")

        # Set provider/model if specified
        if request.provider:
            s.engine.set_provider(request.provider)
        if request.model:
            s.engine.set_model(request.model, reset_context=False)

        # Wrap generator to ensure lock is held during streaming
        async def locked_generator():
            """Generator that streams events while holding the lock."""
            async for event in sse_coding_task_generator(request.message, request.task_type, s.engine):
                yield event
            logger.info(f"Coding task completed for session {s.id} - releasing lock")

        return StreamingResponse(
            locked_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Session-Id": s.id,
            }
        )

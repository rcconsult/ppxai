"""
Chat and coding task endpoints with SSE streaming.

v1.17.4 Phase 3: Added multimodal file attachment support. The chat
endpoint accepts an optional `files[]` array in the request body — each
entry is a `FileAttachment(name, media_type, data)` with base64-encoded
bytes. The route decodes, validates, and preprocesses each file through
`engine.file_preprocessing.preprocess_file` (the same pipeline the Rich
TUI's `/attach` uses) and builds a multimodal content list that the
engine sends to the provider alongside the user's text message.

This means web clients (drag-drop), VSCode (file picker), and any HTTP
consumer can upload files without reimplementing the validation + vision
routing logic that the Rich TUI already has.
"""

import asyncio
import base64
import json
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from typing import Any, Dict, List, Optional

from ...common.logger import get_logger
from ...engine.file_preprocessing import preprocess_file
from ..models import ChatRequest, CodingTaskRequest
from ..state import Session, get_session
from ..streaming import sse_event_generator, sse_coding_task_generator

logger = get_logger("server")

router = APIRouter()


# R15: detect chat requests whose entire body is one or more VSCode-style
# workspace context preambles. When the VSCode extension prepends
# `[Context: Working in VSCode workspace "X" at /path]` to an empty user
# message, the provider sees only that synthetic context block — which
# Perplexity rejects with 400 for breaking user/assistant alternation.
# Stop those requests server-side before they hit any provider.
_CONTEXT_ONLY_RE = re.compile(
    r"""
    \A
    (?:\s*\[Context:[^\]]*\]\s*)+   # one or more [Context: ...] blocks
    \Z
    """,
    re.VERBOSE | re.DOTALL,
)


def _is_empty_or_context_only(message: str) -> bool:
    """True if `message` is blank or contains only [Context: ...] preambles.

    These messages would otherwise be sent to the LLM as a bare user turn
    consisting of nothing but the VSCode workspace context block. The
    provider has no actual prompt to answer and strict-alternation
    providers (Perplexity) reject the request.
    """
    if not message or not message.strip():
        return True
    return bool(_CONTEXT_ONLY_RE.match(message.strip()))


def _build_chat_payload(
    message: str,
    files: list,
    engine: Any,
) -> Any:
    """Build the chat payload from the user's text + attached files.

    When `files` is empty, returns the plain text string so context
    injection (@file/@git/@tree) still works as before. When files are
    present, each is preprocessed through `preprocess_file` and the
    result is merged into a multimodal content list — identical to what
    the Rich TUI's `build_multimodal_content` does. The engine receives
    either a string or a list, and `EngineClient.chat()` handles both.

    Errors from individual file preprocessing (oversized, wrong format,
    etc.) are surfaced as inline text annotations in the content list
    rather than failing the entire request, matching the `/attach` UX.
    """
    if not files:
        return message

    text_chunks: List[str] = [message] if message else []
    non_text_parts: List[Dict[str, Any]] = []

    model = engine.model or ""
    provider = engine.provider_name or ""
    file_store = getattr(engine, "file_store", None)
    vl_captioner = (
        engine.caption_image
        if hasattr(engine, "has_vision_sidecar") and engine.has_vision_sidecar()
        else None
    )

    for attachment in files:
        # Decode base64 → raw bytes. Reject on decode failure with an
        # inline error rather than a 400 so the rest of the message
        # still goes through.
        try:
            data = base64.b64decode(attachment.data)
        except Exception as exc:
            text_chunks.append(
                f"[Attachment error: {attachment.name} — invalid base64: {exc}]"
            )
            continue

        result = preprocess_file(
            attachment.name,
            data,
            model=model,
            provider=provider,
            media_type=attachment.media_type,
            file_store=file_store,
            vl_captioner=vl_captioner,
        )
        if not result.ok:
            text_chunks.append(
                f"[Attachment error: {attachment.name} — {result.error}]"
            )
            continue

        for part in result.parts:
            if part.get("type") == "text":
                text_chunks.append(part["text"])
            else:
                non_text_parts.append(part)

    combined_text = "\n".join(chunk for chunk in text_chunks if chunk)
    parts: List[Dict[str, Any]] = []
    if combined_text:
        parts.append({"type": "text", "text": combined_text})
    parts.extend(non_text_parts)

    if not parts:
        parts.append({"type": "text", "text": ""})

    return parts


@router.post("/chat")
async def chat(
    request: ChatRequest,
    raw_request: Request,
    s: Session = Depends(get_session)
):
    """Chat endpoint with SSE streaming.

    v1.11.2: Added logging.
    v1.12.0: Added request locking to prevent concurrent state corruption.
    v1.13.10: Supports X-Session-Id header for session isolation.
    v1.17.4 Phase 3: Accepts optional `files[]` array for multimodal
    attachments. Each file is preprocessed through the same pipeline as
    the Rich TUI's `/attach` command (validation, vision routing, store
    persistence). The resulting content list is passed to
    `EngineClient.chat()` which handles both string and list payloads.
    """

    logger.log_http_request("POST", "/chat", f"session={s.id}")

    # R15: Reject context-only or empty requests before acquiring the chat
    # lock. These come from clients that auto-prepend a workspace context
    # block (VSCode) when the user sent no actual prompt; dispatching them
    # wastes a provider round-trip and triggers 400 errors on strict
    # alternation providers like Perplexity.
    if not request.files and _is_empty_or_context_only(request.message or ""):
        logger.warning(
            f"Chat rejected for session {s.id}: empty or context-only message "
            f"({len(request.message or '')} chars)"
        )

        async def _empty_message_error():
            payload = json.dumps({
                "type": "error",
                "data": "Empty chat message. Type a prompt before sending.",
            })
            yield f"data: {payload}\n\n"

        return StreamingResponse(
            _empty_message_error(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Session-Id": s.id,
            }
        )

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

        # Build the chat payload — plain string when no files, multimodal
        # content list when files are attached (Phase 3.2).
        chat_payload = _build_chat_payload(
            request.message, request.files, s.engine
        )

        # Wrap generator to ensure lock is held during streaming
        async def locked_generator():
            """Generator that streams events while holding the lock."""
            async for event in sse_event_generator(chat_payload, s.engine, s.id, request=raw_request):
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

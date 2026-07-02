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
from ...engine.types import Event, EventType
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


def is_empty_or_context_only(message: str) -> bool:
    """True if `message` is blank or contains only [Context: ...] preambles.

    These messages would otherwise be sent to the LLM as a bare user turn
    consisting of nothing but the VSCode workspace context block. The
    provider has no actual prompt to answer and strict-alternation
    providers (Perplexity) reject the request.

    Pure predicate — no side effects, no state. Part of the module's
    public surface so unit tests can exercise it directly without
    reaching into privates (v1.18.0 Phase 5g).
    """
    if not message or not message.strip():
        return True
    return bool(_CONTEXT_ONLY_RE.match(message.strip()))


def _build_chat_payload(
    message: str,
    files: list,
    engine: Any,
) -> tuple:
    """Build the chat payload from the user's text + attached files.

    When `files` is empty, returns `(message, [])`. When files are
    present, each is preprocessed through `preprocess_file` and the
    result is merged into a multimodal content list — identical to what
    the Rich TUI's `build_multimodal_content` does. The engine receives
    either a string or a list, and `EngineClient.chat()` handles both.

    Returns a `(payload, warnings)` tuple. `payload` is what gets sent
    to the engine; `warnings` is a list of per-attachment dicts the
    caller surfaces via `Event(EventType.WARNING, ...)` BEFORE the
    chat starts. The vision-capability warning lives here so users see
    "image dropped → text placeholder" in chat transcript instead of
    inferring it from the model's confused response (v1.18.6).

    Errors from individual file preprocessing (oversized, wrong format,
    etc.) are surfaced as inline text annotations in the content list
    rather than failing the entire request, matching the `/attach` UX.
    """
    if not files:
        return message, [], []

    text_chunks: List[str] = [message] if message else []
    non_text_parts: List[Dict[str, Any]] = []
    attachment_warnings: List[Dict[str, Any]] = []
    # ADR 0006 Step 2/3: collect kind-specific ArtifactRefs from each
    # PreprocessResult for re-basing into the final content list. Same
    # routing logic as build_multimodal_content — text-class attachments
    # share the merged text block; non-text attachments get their own.
    text_artifact_refs: List[Any] = []
    non_text_artifact_refs: List[Any] = []

    model = engine.model or ""
    provider = engine.provider_name or ""
    file_store = getattr(engine, "file_store", None)
    vl_captioner = (
        engine.caption_image
        if hasattr(engine, "has_vision_sidecar") and engine.has_vision_sidecar()
        else None
    )
    # v1.19.0 (debt Item 24): the shell-CLI route lets a text-only model
    # still inspect an image via a system utility reading the file from
    # disk. When neither native vision, the sidecar, nor this is available,
    # `preprocess_file` returns ok=False and the send is blocked below.
    shell_image_route = (
        engine.can_shell_process_images()
        if hasattr(engine, "can_shell_process_images")
        else False
    )

    # v1.18.6: precompute vision capability so we can detect the
    # image-on-non-vision-model case and emit a structured warning the
    # client can render distinctly from generic preprocess warnings.
    from ...engine.model_profiles import supports_vision as _supports_vision
    model_has_vision = _supports_vision(model) if model else False

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
            shell_image_route=shell_image_route,
        )
        if not result.ok:
            text_chunks.append(
                f"[Attachment error: {attachment.name} — {result.error}]"
            )
            # v1.19.0 (debt Item 24): a non-vision image with no consumable
            # path now fails loud (ok=False) instead of becoming a silent
            # placeholder. Surface the actionable reason as a structured
            # warning the client renders distinctly, then block the send.
            is_image = (attachment.media_type or "").startswith("image/")
            if is_image:
                attachment_warnings.append({
                    "type": "vision_unsupported",
                    "severity": "error",
                    "message": (
                        f"{attachment.name} could not be attached: "
                        f"{result.error}"
                    ),
                    "suggested_action": (
                        "Switch to a vision-capable model "
                        "(e.g. gpt-5.5, gemini-3-flash), restart with a "
                        "reachable VL sidecar, or enable the shell tool "
                        "with an image utility installed."
                    ),
                    "details": f"attachment: {attachment.name}, model: {model}",
                })
            continue

        # v1.19.0 (debt Item 24): a non-vision image that still succeeded
        # went through one of two indirect routes — the VL sidecar caption
        # or the shell-CLI path. They behave differently, so the user
        # notice must match the route ACTUALLY taken; a single "shell tool"
        # message would mislead when the sidecar captioned it. The shell
        # route tags its PreprocessResult.warnings with a distinctive
        # marker; the sidecar path does not. The hard-fail case (no
        # consumable path) was already handled above (ok=False). Payload
        # shape mirrors the validator-warning renderer
        # (`web/app.js::showValidationWarning`).
        is_image = (attachment.media_type or "").startswith("image/")
        if is_image and not model_has_vision:
            took_shell_route = any(
                "routed to shell-CLI inspection" in w
                for w in (result.warnings or [])
            )
            if took_shell_route:
                attachment_warnings.append({
                    "type": "vision_via_tool",
                    "severity": "info",
                    "message": (
                        f"{attachment.name}: the active model "
                        f"({model or 'unknown'}) can't view images directly — "
                        f"it will inspect the file via the shell tool (e.g. OCR) "
                        f"instead of seeing it."
                    ),
                    "suggested_action": (
                        "For direct visual understanding, switch to a "
                        "vision-capable model (e.g. gpt-5.5, gemini-3-flash)."
                    ),
                    "details": f"attachment: {attachment.name}, model: {model}",
                })
            else:
                # Sidecar caption path: the model gets a text description
                # produced by the VL sidecar, not the image itself.
                attachment_warnings.append({
                    "type": "vision_via_caption",
                    "severity": "info",
                    "message": (
                        f"{attachment.name}: the active model "
                        f"({model or 'unknown'}) can't view images directly — "
                        f"a vision sidecar captioned it and the model sees that "
                        f"text description instead of the image."
                    ),
                    "suggested_action": (
                        "For direct visual understanding, switch to a "
                        "vision-capable model (e.g. gpt-5.5, gemini-3-flash)."
                    ),
                    "details": f"attachment: {attachment.name}, model: {model}",
                })

        produced_non_text = False
        for part in result.parts:
            if part.get("type") == "text":
                text_chunks.append(part["text"])
            else:
                non_text_parts.append(part)
                produced_non_text = True

        # ADR 0006 Step 2/3: route artifact_ref to the right rebase
        # bucket per which output channel its block landed in.
        if result.attachment_ref is not None:
            if produced_non_text:
                non_text_artifact_refs.append(result.attachment_ref)
            else:
                text_artifact_refs.append(result.attachment_ref)

    combined_text = "\n".join(chunk for chunk in text_chunks if chunk)
    parts: List[Dict[str, Any]] = []
    if combined_text:
        parts.append({"type": "text", "text": combined_text})
    parts.extend(non_text_parts)

    if not parts:
        parts.append({"type": "text", "text": ""})

    # Re-base block_index on each ArtifactRef to match positions in
    # the final assembled content list. Mirrors the logic in
    # build_multimodal_content (commands/attach.py) so server route +
    # TUI/Rich path produce identical Message.attachments shape.
    attachment_refs: List[Any] = []
    has_combined_text = bool(combined_text)
    text_block_index = 0 if has_combined_text else -1

    for ref in text_artifact_refs:
        ref.block_index = text_block_index
        attachment_refs.append(ref)

    non_text_start = 1 if has_combined_text else 0
    for offset, ref in enumerate(non_text_artifact_refs):
        ref.block_index = non_text_start + offset
        attachment_refs.append(ref)

    return parts, attachment_warnings, attachment_refs


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
    if not request.files and is_empty_or_context_only(request.message or ""):
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

    # v1.18.1 safety gate: when the chat message is `/agent <task>`,
    # apply the same min-words validation the factory's handle_agent
    # uses. Pre-v1.18.1, web's streamChat shipped /agent <task>
    # straight to /chat which had no awareness — letting users run
    # `/agent fix` and the LLM-with-tools just go. Now we intercept
    # before the lock acquisition / streaming setup. The message
    # the user sees is the same friendly nudge across TUI / web /
    # VSCode (single source: validate_agent_task in commands/agent.py).
    msg_text = (request.message or "").strip()
    if msg_text.startswith("/agent ") or msg_text.startswith("/agent\t"):
        from ...commands.agent import validate_agent_task
        # Strip the /agent prefix to get just the task body
        task = msg_text.split(None, 1)[1] if " " in msg_text or "\t" in msg_text else ""
        agent_config = s.engine.get_agent_config()
        min_words = agent_config.get("min_task_words", 3)
        rejection = validate_agent_task(task.strip(), min_words)
        if rejection is not None:
            logger.info(
                f"/agent rejected for session {s.id}: "
                f"task too brief ({len(task.split())} word(s))"
            )

            async def _vague_task_response():
                # Surface as a system message in the SSE stream so
                # the existing chat-stream UI renders it normally —
                # no special case in the client. The full rejection
                # text from validate_agent_task carries the question
                # framing + concrete examples.
                payload = json.dumps({
                    "type": "system",
                    "data": rejection.message,
                })
                yield f"data: {payload}\n\n"
                # Mark the stream complete so client unwinds normally.
                yield f"data: {json.dumps({'type': 'stream_end', 'data': ''})}\n\n"

            return StreamingResponse(
                _vague_task_response(),
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
        # content list when files are attached (Phase 3.2). Returns a
        # 3-tuple (chat_payload, attachment_warnings, attachment_refs):
        #   - attachment_warnings (v1.18.6): per-attachment vision-warning
        #     events enqueued before the SSE drain so users see them in
        #     chat transcript before the assistant response.
        #   - attachment_refs (ADR 0006 Step 2/3, v1.18.6): kind-specific
        #     ArtifactRefs (Image/Pdf/Office/Text) the producer pipeline
        #     populated with block_index re-based to match the assembled
        #     content list. Threaded into engine.chat(attachment_refs=)
        #     so Message.attachments is populated from the producer side
        #     without re-deriving via extract_attachment_refs. Empty
        #     list when no files attached or all preprocesses failed.
        chat_payload, attachment_warnings, attachment_refs = _build_chat_payload(
            request.message, request.files, s.engine
        )

        # v1.19.0 (debt Item 24): a hard attachment failure — e.g. an image on a
        # text-only model with no VL sidecar and no shell-CLI route — escalates
        # to a severity="error" warning. Such a send must be BLOCKED: the model
        # must not answer over an "[Attachment error: ...]" placeholder as if it
        # had seen the file. Emit the warning(s) + a terminal error and never
        # reach the provider (fail-loud, not silent-degrade).
        fatal_attachments = [
            w for w in attachment_warnings if w.get("severity") == "error"
        ]
        if fatal_attachments:
            logger.warning(
                f"Chat blocked for session {s.id}: "
                f"{len(fatal_attachments)} unreadable attachment(s)"
            )

            async def _blocked_attachment_stream():
                for w in attachment_warnings:
                    yield f"data: {json.dumps({'type': 'warning', 'data': w})}\n\n"
                message = fatal_attachments[0].get(
                    "message", "Attachment could not be processed."
                )
                yield f"data: {json.dumps({'type': 'error', 'data': message})}\n\n"
                yield f"data: {json.dumps({'type': 'stream_end', 'data': ''})}\n\n"

            return StreamingResponse(
                _blocked_attachment_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "X-Session-Id": s.id,
                },
            )

        for w in attachment_warnings:
            s.engine.enqueue_event(Event(
                type=EventType.WARNING,
                data=w,
            ))

        # Wrap generator to ensure lock is held during streaming
        async def locked_generator():
            """Generator that streams events while holding the lock."""
            async for event in sse_event_generator(
                chat_payload, s.engine, s.id, request=raw_request,
                attachment_refs=attachment_refs,
            ):
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

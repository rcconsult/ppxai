"""
SSE (Server-Sent Events) streaming generators for the ppxai HTTP server.
"""

import asyncio
import json
import traceback
from typing import AsyncGenerator

from fastapi import Request

from ..common.logger import get_logger
from ..engine import EngineClient, EventType

logger = get_logger("server")


async def sse_event_generator(prompt, engine: EngineClient, session_id: str = "default", request: Request = None) -> AsyncGenerator[str, None]:
    """Generate SSE events from engine chat.

    SSE format: data: {json}\n\n
    Each event is yielded immediately with a sleep(0) to force flush.
    Drains engine.drain_events() side-channel for consent requests, state sync,
    and status events while the main chat generator is blocked.
    v1.17.2: Thread-safe event queue via drain_events().
    v1.17.4: `prompt` accepts MessageContent (str | list[dict]) so the chat
    route can pass multimodal content lists with file attachments directly
    through to EngineClient.chat().
    v1.16.0: B11 — Detects client disconnect and cancels background engine task.
    """
    if not engine:
        logger.error("SSE event generator called but engine not initialized")
        yield f"data: {json.dumps({'type': 'error', 'data': 'Engine not initialized'})}\n\n"
        return

    # Log text content for the prompt (multimodal content is logged at
    # engine level; here we just want the text portion for the server log).
    if isinstance(prompt, str):
        logger.log_user_message(prompt)
    elif isinstance(prompt, list):
        text_parts = [b.get("text", "") for b in prompt if isinstance(b, dict) and b.get("type") == "text"]
        logger.log_user_message(" ".join(text_parts)[:200] or "[multimodal]")
    else:
        logger.log_user_message(str(prompt)[:200])

    try:
        # v1.16.0: Use racing iterator to poll consent queue while engine is blocked.
        # The engine generator suspends during consent (await Future), so `async for`
        # never advances and the old inline poll never ran — causing a deadlock.
        engine_iter = engine.chat(prompt).__aiter__()
        engine_done = False
        pending_next = None  # asyncio.Task for the next engine event
        last_event_time = asyncio.get_event_loop().time()
        KEEPALIVE_INTERVAL = 5  # seconds — must be shorter than client heartbeat (15s) to prevent false disconnects

        while not engine_done:
            # Start fetching next engine event if not already in flight
            if pending_next is None:
                pending_next = asyncio.ensure_future(engine_iter.__anext__())

            # Poll: race between engine event and consent queue (100ms ticks)
            while not pending_next.done():
                # SSE keepalive: send comment to prevent idle connection timeout
                # Proxies (nginx) and browsers may drop silent SSE connections
                now = asyncio.get_event_loop().time()
                if now - last_event_time >= KEEPALIVE_INTERVAL:
                    yield ": keepalive\n\n"
                    await asyncio.sleep(0)
                    last_event_time = now

                # Drain side-channel event queue (thread-safe via drain_events)
                for queued_event in engine.drain_events():
                    event_data = {
                        "type": queued_event.type.value,
                        "data": queued_event.data,
                    }
                    if queued_event.metadata:
                        event_data["metadata"] = queued_event.metadata
                    logger.log_sse_event(queued_event.type.value, str(queued_event.data)[:100])
                    yield f"data: {json.dumps(event_data)}\n\n"
                    await asyncio.sleep(0)

                # B11: Check if client disconnected
                if request and await request.is_disconnected():
                    logger.info(f"Client disconnected during SSE stream (session={session_id})")
                    pending_next.cancel()
                    # Retrieve the cancelled task's exception to prevent
                    # "Task exception was never retrieved" warning from asyncio
                    try:
                        await pending_next
                    except (asyncio.CancelledError, StopAsyncIteration):
                        pass
                    engine_done = True
                    break

                # Yield control briefly then re-check.
                # v1.18.1 hotfix: was 0.1 — capped streaming throughput at
                # ~10 events/sec because the loop slept 100ms after each
                # check regardless of how fast the engine produced events.
                # Per-token providers (Perplexity sonar-pro at ~9 tok/sec)
                # ran right at the ceiling; batched providers (OpenAI,
                # Gemini emitting 3-5 tokens/chunk) clamped to 10/sec
                # too. Dropping to 10ms uncaps the forwarder — engine
                # rate becomes the real bottleneck, no observable CPU
                # cost at single-digit concurrent connections.
                await asyncio.sleep(0.01)

            if engine_done:
                break

            # Retrieve the engine event
            try:
                event = pending_next.result()
                pending_next = None
            except StopAsyncIteration:
                engine_done = True
                break

            # Drain side-channel queue one more time (event may have been queued just before yield)
            # Drain side-channel one more time (event may have been queued just before yield)
            for queued_event in engine.drain_events():
                event_data = {
                    "type": queued_event.type.value,
                    "data": queued_event.data,
                }
                if queued_event.metadata:
                    event_data["metadata"] = queued_event.metadata
                logger.log_sse_event(queued_event.type.value, str(queued_event.data)[:100])
                yield f"data: {json.dumps(event_data)}\n\n"
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
            last_event_time = asyncio.get_event_loop().time()
    except Exception as e:
        logger.error(
            f"Exception in SSE event generator: {e}\n{traceback.format_exc()}"
        )
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
                    logger.info(f"Session cleanup: removed orphan user message (len={len(removed.text_content())})")
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
        logger.error(
            f"Exception in SSE coding task generator: {e}\n{traceback.format_exc()}"
        )
        error_str = str(e)
        yield f"data: {json.dumps({'type': 'error', 'data': error_str})}\n\n"

        # Session cleanup for message alternation errors
        if "alternation" in error_str.lower() or "alternate" in error_str.lower():
            try:
                messages = engine.session.messages
                while len(messages) > 1 and messages[-1].role == "user" and messages[-2].role == "user":
                    removed = messages.pop()
                    logger.info(f"Session cleanup: removed orphan user message (len={len(removed.text_content())})")
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

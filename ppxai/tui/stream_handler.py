"""
Stream handler — engine event processing for ppxaide TUI.

Extracted from tui/app.py (v1.17.1). Handles streaming responses,
event bus dispatch, reasoning token display, tool call/result rendering,
and usage stats display.

All functions take the app instance as first parameter.
"""

import asyncio
import time
from pathlib import Path
from typing import Any

from ppxai.config import get_auto_save_interval, get_tui_config
from ppxai.tui.widgets.file_tree import FileTree
from ppxai.engine.types import Event, EventType
from ppxai.tui.event_bus import Events
from ppxai.tui.widgets.message_box import MessageBox


def stream_response_thread(app, user_input: str, engine_client) -> None:
    """Worker thread: stream from engine without blocking Textual's event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_stream_response(app, user_input, engine_client))
    finally:
        app.call_from_thread(handle_stream_end, app)
        loop.close()


def handle_stream_end(app) -> None:
    """Handle stream completion (called via call_from_thread)."""
    footer_status = app._footer_status
    footer_status.clear()
    app._engine_client.state.update(is_streaming=False, cancel_requested=False)
    app._log.info("Stream complete, cleaned up")


def handle_stream_cancelled(app) -> None:
    """Handle stream cancellation (called via call_from_thread)."""
    chat_view = app._chat_view
    chat_view.add_system_message("[yellow]⚠ Stream cancelled[/yellow]")
    app._log.info("Stream cancelled by user")
    footer_status = app._footer_status
    footer_status.clear()
    app._engine_client.state.update(is_streaming=False, cancel_requested=False)


def handle_stream_error(app, error_msg: str) -> None:
    """Handle stream error (called via call_from_thread)."""
    chat_view = app._chat_view
    chat_view.add_system_message(f"[red]Stream error:[/red] {error_msg}")
    app._log.error(f"Stream error from thread: {error_msg}")
    footer_status = app._footer_status
    footer_status.clear()
    app._engine_client.state.update(is_streaming=False, cancel_requested=False)


# R16: Every EventType emitted by the engine MUST appear in exactly one of
# EVENT_MAP (routes to a UI bus signal) or NOOP_EVENTS (intentionally ignored
# by the Textual TUI). Adding a new EventType without touching this file will
# fail the drift test in tests/test_stream_handler_dispatch.py and log a
# WARNING at runtime — deliberate friction so ppxaide doesn't silently drop
# new engine signals again.

EVENT_MAP = {
    EventType.STREAM_START: Events.ENGINE_STREAM_START,
    EventType.STREAM_CHUNK: Events.ENGINE_STREAM_CHUNK,
    EventType.REASONING_CHUNK: Events.ENGINE_REASONING_CHUNK,
    EventType.STREAM_END: Events.ENGINE_STREAM_END,
    EventType.TOOL_CALL: Events.ENGINE_TOOL_CALL,
    EventType.TOOL_RESULT: Events.ENGINE_TOOL_RESULT,
    EventType.TOOL_ERROR: Events.ENGINE_TOOL_ERROR,
    EventType.TOOL_GROUP_START: Events.ENGINE_TOOL_GROUP_START,
    EventType.TOOL_GROUP_END: Events.ENGINE_TOOL_GROUP_END,
    EventType.ERROR: Events.ENGINE_ERROR,
    EventType.WARNING: Events.ENGINE_WARNING,
    EventType.INFO: Events.ENGINE_INFO,
    EventType.WORKING_DIR_CHANGED: Events.ENGINE_WORKING_DIR_CHANGED,
    EventType.DISPLAY_FILE: Events.ENGINE_DISPLAY_FILE,
    EventType.CONSENT_REQUEST: Events.ENGINE_CONSENT_FILE,
    EventType.CONTEXT_INJECTED: Events.ENGINE_CONTEXT_INJECTED,
    EventType.AGENT_INTERMEDIATE_PROSE: Events.ENGINE_AGENT_INTERMEDIATE_PROSE,
}

# Events that ppxaide intentionally does not render — either because another
# subsystem already handles them, or because the feature has no Textual UI
# counterpart yet. Listing them here (rather than letting them fall through to
# WARNING) documents the decision and keeps the drift test green.
NOOP_EVENTS = {
    # STATE_SYNC is consumed by AppState observers on every client; the
    # Textual TUI subscribes via state.on() rather than the event bus.
    EventType.STATE_SYNC,
    # Agent-loop events exist for Rich TUI's agent REPL. ppxaide doesn't
    # expose the agent loop as a dedicated UI flow yet — surface via INFO
    # instead. Remove from NOOP_EVENTS when ppxaide adds agent UI.
    EventType.AGENT_ITERATION,
    EventType.AGENT_COMPLETE,
    EventType.AGENT_MAX_ITERATIONS,
    # P0 (v1.18.0) agent lifecycle events. ppxaide renders heartbeat
    # progress via `AppState.agent_beat` (see `app.py::_on_agent_beat_changed`)
    # rather than the event bus — the state field is kept authoritative
    # by EngineClient and auto-clears on RUN_COMPLETE/RUN_ERROR. Events
    # themselves are intentionally silent here to avoid double-rendering.
    EventType.AGENT_BEAT,
    EventType.AGENT_RUN_START,
    EventType.AGENT_RUN_COMPLETE,
    EventType.AGENT_RUN_ERROR,
    EventType.AGENT_ZOMBIE,
    # STATUS is generic notification plumbing; ppxaide surfaces these
    # through ENGINE_INFO (checkpoint commands etc. use INFO).
    EventType.STATUS,
}


def handle_stream_event(app, event_type: str, event_data: Any) -> None:
    """Handle stream event in main thread (called via call_from_thread)."""
    event = Event(type=EventType[event_type], data=event_data)

    if event.type in EVENT_MAP:
        bus_event = EVENT_MAP[event.type]
        app._event_bus.emit(bus_event, data=event.data, event_type=event.type)
    elif event.type in NOOP_EVENTS:
        if app._trace_logging:
            app._log.debug(f"Intentionally ignored event: {event.type}")
    else:
        # Drift: engine added an EventType without updating this file.
        app._log.warning(
            f"Unhandled event type: {event.type} — add an entry to EVENT_MAP "
            f"or NOOP_EVENTS in ppxai/tui/stream_handler.py (R16)"
        )


async def _stream_response(app, user_input: str, engine_client) -> None:
    """Stream AI response from engine (runs in thread's event loop)."""
    try:
        app._log.info(f"Thread: Starting stream for: {user_input[:50]}...")
        event_count = 0

        async for event in engine_client.chat(user_input, stream=True):
            if engine_client.state.get("cancel_requested"):
                app._log.info("Thread: Cancellation requested, stopping stream")
                app.call_from_thread(handle_stream_cancelled, app)
                return

            event_count += 1
            if app._debug_logging:
                app._log.debug(f"Thread: Event #{event_count}: {event.type.name}")

            app.call_from_thread(handle_stream_event, app, event.type.name, event.data)

        app._log.info(f"Thread: Stream finished, {event_count} events")

    except Exception as e:
        app._log.error(f"Thread: Stream error: {e}")
        app.call_from_thread(handle_stream_error, app, str(e))


# === Event bus handlers ===

async def on_stream_start(app, sender, **kwargs) -> None:
    """Handle STREAM_START event."""
    if app._trace_logging:
        app._log.debug("[Event] STREAM_START received (thinking indicator already shown)")


async def on_stream_chunk(app, sender, data, **kwargs) -> None:
    """Handle STREAM_CHUNK event."""
    if not app._current_message_content:
        clear_thinking_indicator(app)
        if app._trace_logging:
            app._log.debug("[Event] First chunk received, cleared thinking indicator")

    app._current_message_content += data

    if app._trace_logging:
        app._log.debug(f"[Event] Chunk: {len(data)} chars, total: {len(app._current_message_content)}")


def clear_thinking_indicator(app) -> None:
    """Clear the thinking indicator from footer."""
    try:
        footer_status = app._footer_status
        footer_status.set_streaming()
        if app._trace_logging:
            app._log.debug("[Event] Changed footer status to streaming")
    except Exception as e:
        if app._trace_logging:
            app._log.debug(f"[Event] Could not update footer status: {e}")


async def on_reasoning_chunk(app, sender, data, **kwargs) -> None:
    """Handle REASONING_CHUNK event (DeepSeek R1, GPT-OSS thinking tokens)."""
    chat_view = app._chat_view

    if not app._reasoning_started:
        app._reasoning_started = True
        clear_thinking_indicator(app)
        app._reasoning_message = MessageBox(
            content="[italic]💭 Thinking...[/italic]",
            role="system",
            streaming=True
        )
        chat_view._messages.append(app._reasoning_message)
        chat_view.mount(app._reasoning_message)
        chat_view.scroll_end(animate=False)
        if app._trace_logging:
            app._log.debug("[Event] Reasoning started")

    app._reasoning_content += data

    if app._trace_logging:
        app._log.debug(f"[Event] Reasoning chunk: {len(data)} chars, total: {len(app._reasoning_content)}")

    if app._debug_logging:
        update_reasoning_display(app)
    else:
        if not app._reasoning_update_pending:
            app._reasoning_update_pending = True
            app.set_timer(0.1, lambda: update_reasoning_display(app))


def update_reasoning_display(app) -> None:
    """Update reasoning bubble display with accumulated content."""
    if app._reasoning_message:
        app._reasoning_message.content = f"[italic]💭 Thinking...\n{app._reasoning_content}[/italic]"
    app._reasoning_update_pending = False


async def on_stream_end(app, sender, data, **kwargs) -> None:
    """Handle STREAM_END event."""
    clear_thinking_indicator(app)
    chat_view = app._chat_view

    app._log.debug(f"STREAM_END: data type={type(data).__name__}")
    app._log.debug(f"STREAM_END: accumulated={len(app._current_message_content)} chars")

    final_response = app._current_message_content

    if not final_response:
        if isinstance(data, str):
            final_response = data
        elif isinstance(data, dict):
            final_response = data.get("content") or data.get("message") or data.get("text") or ""
        else:
            final_response = str(data) if data else ""

    if final_response.strip():
        if app._reasoning_message and app._reasoning_content:
            update_reasoning_display(app)
            app._reasoning_message.content = f"[italic]💭 Thought process:\n{app._reasoning_content}[/italic]"
            app._reasoning_message.streaming = False
            chat_view.add_system_message("[dim]───[/dim]")

        response_time = time.time() - app._response_start_time
        chat_view.add_assistant_message(final_response, response_time=response_time)
    else:
        app._log.warning("STREAM_END with no content to display")

    app._current_message_content = ""
    app._reasoning_content = ""
    app._reasoning_started = False
    app._reasoning_message = None

    update_usage_display(app)

    save_interval = get_auto_save_interval()
    message_count = len(app._engine_client.session.messages)
    if message_count > 0 and (save_interval == 0 or message_count % max(1, save_interval) == 0):
        try:
            app._engine_client.session.save_dirty()
            app._autosave_guard.on_success()
        except Exception as e:
            app._log.warning(f"Auto-save failed: {e}")
            # v1.18.0 Phase 5f: tell the user after the threshold so
            # a run with a full disk or revoked permissions doesn't
            # silently lose every turn's save for the rest of the run.
            if app._autosave_guard.on_failure(e):
                app.notify(
                    f"Auto-save has failed "
                    f"{app._autosave_guard.consecutive_failures} times in a row "
                    f"({e}). Check disk space and permissions.",
                    title="Auto-save failing",
                    severity="warning",
                    timeout=10,
                )


async def on_tool_call(app, sender, data, **kwargs) -> None:
    """Handle TOOL_CALL event."""
    if app._chat_view is None:
        return
    chat_view = app._chat_view

    tool_name = data.get("tool", "unknown")
    tool_args = data.get("arguments", {})

    if app._tool_group_active:
        app._tool_group_tools.append(tool_name)

    if app._tool_group_active and not app._tools_verbose:
        return

    if app._tools_verbose and tool_args:
        args_parts = []
        for key, value in tool_args.items():
            if isinstance(value, str):
                value_str = f'"{value[:100]}..."' if len(value) > 100 else f'"{value}"'
            else:
                value_str = str(value)
            args_parts.append(f"{key}={value_str}")
        args_str = ", ".join(args_parts)
        chat_view.add_tool_message(tool_name, f"[dim]Arguments:[/dim] {args_str}")
    else:
        chat_view.add_system_message(f"[cyan]→ Calling tool: {tool_name}[/cyan]")


async def on_tool_result(app, sender, data, **kwargs) -> None:
    """Handle TOOL_RESULT event."""
    if app._chat_view is None:
        return
    chat_view = app._chat_view

    tool_name = data.get("tool", "unknown")
    result = data.get("result", "")
    result_str = str(result) if result else ""

    if app._tool_group_active and not app._tools_verbose:
        return

    if app._tools_verbose:
        chat_view.add_tool_message(f"{tool_name} result", result_str)
    else:
        size_str = f"{len(result_str)} chars" if result_str else "empty"
        chat_view.add_system_message(f"[dim]  ✓ {tool_name} completed ({size_str})[/dim]")


async def on_tool_error(app, sender, data, **kwargs) -> None:
    """Handle TOOL_ERROR event."""
    if app._chat_view is None:
        return
    chat_view = app._chat_view

    tool_name = data.get("tool", "unknown") if isinstance(data, dict) else "unknown"
    error_msg = data.get("error", str(data)) if isinstance(data, dict) else str(data)
    app._log.error(f"[Event] Tool error from {tool_name}: {error_msg}")
    chat_view.add_tool_message(f"{tool_name} [red]ERROR[/red]", f"[red]{error_msg}[/red]")


async def on_tool_group_start(app, sender, data, **kwargs) -> None:
    """Handle TOOL_GROUP_START event (v1.16.0)."""
    app._tool_group_active = True
    app._tool_group_tools = []
    iteration = data.get("iteration", 0) if isinstance(data, dict) else 0
    count = data.get("count", 0) if isinstance(data, dict) else 0
    app._log.info(f"TOOL_GROUP_START: iteration={iteration}, count={count}")


async def on_tool_group_end(app, sender, data, **kwargs) -> None:
    """Handle TOOL_GROUP_END event (v1.16.0)."""
    app._tool_group_active = False
    if isinstance(data, dict):
        all_succeeded = data.get("all_succeeded", True)
        tools = data.get("tools", app._tool_group_tools)
        iteration = data.get("iteration", 0)
    else:
        all_succeeded = True
        tools = app._tool_group_tools
        iteration = 0

    tool_list = ", ".join(tools) if tools else "none"
    app._log.info(f"TOOL_GROUP_END: iteration={iteration}, tools=[{tool_list}]")

    if not app._tools_verbose and tools:
        if app._chat_view is None:
            return
        chat_view = app._chat_view
        status = "[green]✓[/green]" if all_succeeded else "[red]✗[/red]"
        chat_view.add_system_message(
            f"[dim]  Iteration {iteration}: {tool_list} ({len(tools)} tool{'s' if len(tools) != 1 else ''}) {status}[/dim]"
        )

    app._tool_group_tools = []


async def on_display_file(app, sender, data, **kwargs) -> None:
    """Handle DISPLAY_FILE event — AI-triggered file display."""
    if not data or not isinstance(data, dict):
        return
    filepath = data.get("filepath")
    if filepath:
        app._log.info(f"[Event] DISPLAY_FILE: Opening {filepath}")
        await app._handle_command(f"/show {filepath}")


async def on_consent_request(app, sender, data, **kwargs) -> None:
    """Handle CONSENT_REQUEST event — logging only."""
    if app._trace_logging and data and isinstance(data, dict):
        app._log.debug(f"[Event] Consent requested: {data}")


async def on_engine_error(app, sender, data, **kwargs) -> None:
    """Handle ENGINE_ERROR event."""
    if app._chat_view is None:
        return
    app._log.error(f"[Event] Engine error: {data}")
    app._chat_view.add_system_message(f"[red]Error:[/red] {data}")


async def on_engine_warning(app, sender, data, **kwargs) -> None:
    """Handle ENGINE_WARNING event."""
    if app._chat_view is None:
        return
    if data and isinstance(data, str):
        app._log.warning(f"[Event] Engine warning: {data}")
        app._chat_view.add_system_message(f"[yellow]⚠ Warning:[/yellow] {data}")


async def on_engine_info(app, sender, data, **kwargs) -> None:
    """Handle ENGINE_INFO event."""
    if app._chat_view is None:
        return
    if app._trace_logging:
        app._log.debug(f"[Event] Engine info: {data}")
    app._chat_view.add_system_message(f"[dim]{data}[/dim]")


async def on_agent_intermediate_prose(app, sender, data, **kwargs) -> None:
    """Handle AGENT_INTERMEDIATE_PROSE — model prose between tool iterations.

    R12 Opt 1 (v1.17.5): the engine strips tool-call JSON from each
    iteration's response and, with stream=False, buffers the prose
    internally. Without a surface for that text the UI goes silent for
    5–15 s between tool bubbles. Render it as a dim italic preamble so
    it reads as "model thinking out loud" rather than competing with
    the final answer bubble.
    """
    if app._chat_view is None:
        return
    text = ""
    if isinstance(data, dict):
        text = data.get("text", "") or ""
    elif isinstance(data, str):
        text = data
    text = text.strip()
    if not text:
        return
    if app._trace_logging:
        app._log.debug(f"[Event] Agent intermediate prose: {len(text)} chars")
    app._chat_view.add_system_message(f"[dim italic]{text}[/dim italic]")


async def on_working_dir_changed(app, sender, data, **kwargs) -> None:
    """Handle WORKING_DIR_CHANGED event."""
    path = data.get("path", "") if isinstance(data, dict) else str(data)
    if not path or path == app._working_dir:
        return

    app._working_dir = path

    input_box = app._input_box
    if input_box._completer:
        input_box._completer.update_working_dir(Path(path))

    try:
        file_tree = app.query_one("#file-tree", FileTree)
        file_tree.update_root_path(Path(path))
    except Exception:
        pass

    tui_config = get_tui_config()
    if tui_config.get("show_cwd", True):
        app._status_bar.update_badge("cwd", app._format_cwd_display(path))

    app._chat_view.add_system_message(f"[cyan]📁 Working directory: {path}[/cyan]")


def update_usage_display(app) -> None:
    """Update usage stats in status bar."""
    if not app._engine_client or not app._engine_client.session:
        return

    usage_display = app._engine_client.session.get_usage_for_display(
        app._provider, app._model
    )

    status_bar = app._status_bar

    if not usage_display:
        status_bar.remove_badge("tokens")
        status_bar.remove_badge("cost")
        return

    total_tokens = usage_display.get("total_tokens", 0)
    if total_tokens > 0:
        if total_tokens >= 1_000_000:
            tokens_text = f"{total_tokens / 1_000_000:.1f}M"
        elif total_tokens >= 1_000:
            tokens_text = f"{total_tokens / 1_000:.1f}K"
        else:
            tokens_text = f"{total_tokens}"
        status_bar.update_badge("tokens", tokens_text)

    total_cost = usage_display.get("estimated_cost", 0.0)
    if total_cost > 0:
        status_bar.update_badge("cost", f"${total_cost:.4f}")

"""
Tests for ppxai/rich/event_handler.py

Tests the EventHandler class and TUIEventHandler.
"""

from unittest.mock import Mock

import pytest

from ppxai.engine.types import Event, EventType
from ppxai.rich.event_handler import EventHandler, TUIEventHandler


@pytest.mark.asyncio
async def test_event_handler_stream_start():
    """Test that on_stream_start callback is called."""
    mock_callback = Mock()
    handler = EventHandler(on_stream_start=mock_callback)

    event = Event(EventType.STREAM_START, None)
    should_continue = await handler.handle_event(event)

    assert should_continue is True
    mock_callback.assert_called_once()


@pytest.mark.asyncio
async def test_event_handler_stream_chunk():
    """Test that chunks are accumulated."""
    chunks = []
    handler = EventHandler(on_stream_chunk=lambda x: chunks.append(x))

    await handler.handle_event(Event(EventType.STREAM_CHUNK, "Hello"))
    await handler.handle_event(Event(EventType.STREAM_CHUNK, " World"))

    assert handler.get_response() == "Hello World"
    assert chunks == ["Hello", " World"]


@pytest.mark.asyncio
async def test_event_handler_stream_end():
    """Test that STREAM_END stops the loop and calls callback."""
    mock_callback = Mock()
    handler = EventHandler(on_stream_end=mock_callback)

    event = Event(EventType.STREAM_END, "Final response")
    should_continue = await handler.handle_event(event)

    assert should_continue is False  # Should break loop
    mock_callback.assert_called_once_with("Final response")


@pytest.mark.asyncio
async def test_event_handler_tool_call():
    """Test tool call event handling."""
    mock_callback = Mock()
    handler = EventHandler(on_tool_call=mock_callback)

    tool_data = {"tool": "list_directory", "arguments": {"path": "/"}}
    event = Event(EventType.TOOL_CALL, tool_data)
    should_continue = await handler.handle_event(event)

    assert should_continue is True
    mock_callback.assert_called_once()
    call_args = mock_callback.call_args[0][0]
    assert call_args["tool"] == "list_directory"
    assert call_args["arguments"]["path"] == "/"


@pytest.mark.asyncio
async def test_event_handler_error():
    """Test error event handling."""
    mock_callback = Mock()
    handler = EventHandler(on_error=mock_callback)

    event = Event(EventType.ERROR, "API Error 500")
    should_continue = await handler.handle_event(event)

    assert should_continue is False  # Should break loop
    mock_callback.assert_called_once_with("API Error 500")


@pytest.mark.asyncio
async def test_event_handler_reset():
    """Test that reset clears accumulated response."""
    handler = EventHandler()

    await handler.handle_event(Event(EventType.STREAM_CHUNK, "Test"))
    assert handler.get_response() == "Test"

    handler.reset()
    assert handler.get_response() == ""


@pytest.mark.asyncio
async def test_event_handler_process_events():
    """Test processing full event stream."""
    async def mock_event_stream():
        """Generate mock event stream."""
        yield Event(EventType.STREAM_START, None)
        yield Event(EventType.STREAM_CHUNK, "Hello")
        yield Event(EventType.STREAM_CHUNK, " World")
        yield Event(EventType.STREAM_END, "Hello World")

    handler = EventHandler()
    response = await handler.process_events(mock_event_stream())

    assert response == "Hello World"


@pytest.mark.asyncio
async def test_event_handler_with_tool_events():
    """Test handling multiple event types in sequence."""
    tool_calls = []
    errors = []

    handler = EventHandler(
        on_tool_call=lambda x: tool_calls.append(x),
        on_error=lambda x: errors.append(x)
    )

    # Process sequence of events
    events = [
        Event(EventType.STREAM_START, None),
        Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {"path": "test.py"}}),
        Event(EventType.TOOL_RESULT, {"content": "file content"}),
        Event(EventType.STREAM_CHUNK, "Here is the file"),
        Event(EventType.STREAM_END, "Here is the file"),
    ]

    for event in events:
        await handler.handle_event(event)

    assert len(tool_calls) == 1
    assert tool_calls[0]["tool"] == "read_file"
    assert len(errors) == 0


@pytest.mark.asyncio
async def test_event_handler_no_callbacks():
    """Test that handler works without callbacks (no-op)."""
    handler = EventHandler()  # No callbacks provided

    # Should not raise exceptions
    await handler.handle_event(Event(EventType.STREAM_START, None))
    await handler.handle_event(Event(EventType.STREAM_CHUNK, "test"))
    await handler.handle_event(Event(EventType.TOOL_CALL, {"tool": "test"}))
    result = await handler.handle_event(Event(EventType.STREAM_END, "done"))

    assert result is False  # STREAM_END should signal break
    assert handler.get_response() == "test"


def test_tui_event_handler_creation():
    """Test TUIEventHandler can be created."""
    mock_console = Mock()
    mock_logger = Mock()

    handler = TUIEventHandler(mock_console, mock_logger, verbose=True)

    assert handler.console is mock_console
    assert handler.logger is mock_logger
    assert handler.verbose is True


# =============================================================================
# Agent heartbeat event rendering (P0 v1.18.0)
# =============================================================================

@pytest.mark.asyncio
async def test_tui_agent_beat_renders_dim_status_line():
    """AGENT_BEAT event prints a compact status line with iteration/tool/elapsed."""
    mock_console = Mock()
    mock_logger = Mock()
    handler = TUIEventHandler(mock_console, mock_logger)

    event = Event(EventType.AGENT_BEAT, {
        "iteration": 2,
        "beat": 2,
        "tool": "apply_patch",
        "ok": True,
        "failures": 0,
        "elapsed_s": 4.7,
    })
    should_continue = await handler.handle_event(event)

    assert should_continue is True
    mock_console.print.assert_called_once()
    output = mock_console.print.call_args[0][0]
    assert "iter 2" in output
    assert "apply_patch" in output
    assert "ok" in output
    assert "4.7s" in output
    assert "[dim]" in output


@pytest.mark.asyncio
async def test_tui_agent_beat_shows_failure_streak():
    """AGENT_BEAT surfaces consecutive failure counter when non-zero."""
    mock_console = Mock()
    handler = TUIEventHandler(mock_console, Mock())

    event = Event(EventType.AGENT_BEAT, {
        "iteration": 3, "beat": 3, "tool": "shell",
        "ok": False, "failures": 2, "elapsed_s": 9.1,
    })
    await handler.handle_event(event)

    output = mock_console.print.call_args[0][0]
    assert "fail×2" in output
    assert "fail" in output  # status text


@pytest.mark.asyncio
async def test_tui_agent_zombie_renders_red_warning():
    """AGENT_ZOMBIE prints a visible red warning (loop is stopping)."""
    mock_console = Mock()
    handler = TUIEventHandler(mock_console, Mock())

    event = Event(EventType.AGENT_ZOMBIE, {
        "reason": "3 consecutive tool failures",
        "threshold": 3,
        "last_tool": "apply_patch",
        "iteration": 3,
        "elapsed_s": 12.8,
    })
    should_continue = await handler.handle_event(event)

    assert should_continue is True
    output = mock_console.print.call_args[0][0]
    assert "[red]" in output
    assert "3 consecutive tool failures" in output
    assert "apply_patch" in output


@pytest.mark.asyncio
async def test_tui_agent_run_events_are_silent():
    """AGENT_RUN_START / RUN_COMPLETE / RUN_ERROR render nothing on their own.

    They exist for AppState / observers — the TUI renders progress via the
    ERROR event and BEAT/ZOMBIE heartbeats. A silent handler keeps the
    per-turn output uncluttered.
    """
    mock_console = Mock()
    handler = TUIEventHandler(mock_console, Mock())

    for ev_type in (
        EventType.AGENT_RUN_START,
        EventType.AGENT_RUN_COMPLETE,
        EventType.AGENT_RUN_ERROR,
    ):
        should_continue = await handler.handle_event(Event(ev_type, {"iteration": 1}))
        assert should_continue is True

    mock_console.print.assert_not_called()

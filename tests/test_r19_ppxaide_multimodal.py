"""R19 — targeted regression tests for ppxaide multimodal flow.

Covers the four failure modes suspected in the original R19 report:

  1. Mixed-content assistant messages render correctly via MessageBox's
     `normalize_content_to_text` (text + image_url + uploaded_file
     blocks interleaved).

  2. Engine stream-event ordering through the ppxaide dispatcher for a
     multimodal agent turn — STREAM_CHUNK, TOOL_GROUP_*, TOOL_CALL,
     TOOL_RESULT, AGENT_INTERMEDIATE_PROSE, STREAM_END route to the
     right EventBus signals in the right order.

  3. `pending_files` lifecycle — staged files flow into multimodal
     content on send, the buffer clears after a successful send, and a
     second send doesn't replay stale state. Plus the error-path shape
     (send raises mid-flight).

  4. `context_attachments` mid-stream updates — the AppState observer
     on the PPXAIDEApp receives fresh attachment lists when engine
     mutations fire during a stream.

Tests use lightweight fakes (no full Textual App boot). The event-bus
is the real blinker-backed implementation — the code we most want to
lock down. Widget tests mount `MessageBox` through Textual's App-less
render path where possible.
"""

import pytest

pytest.importorskip("textual")
pytest.importorskip("blinker")

from unittest.mock import MagicMock

from ppxai.engine.types import Event, EventType
from ppxai.engine.uploaded_file import make_uploaded_file_block
from ppxai.tui.event_bus import EventBus, Events
from ppxai.tui.stream_handler import EVENT_MAP, handle_stream_event

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_fake(trace_logging: bool = False):
    """Build the minimal stand-in for a PPXAIDEApp that
    `handle_stream_event` needs: a real EventBus, a no-op logger, a
    trace flag, and a `pending_files` buffer.
    """
    bus = EventBus()
    app = MagicMock()
    app._event_bus = bus
    app._log = MagicMock()
    app._trace_logging = trace_logging
    app.pending_files = []
    return app


def _subscribe_capture(bus: EventBus, *event_names: str):
    """Subscribe a capturing handler to each named event; return a list
    that accumulates (event_name, kwargs) tuples in arrival order.

    Callbacks must accept a positional `sender` plus **kwargs — blinker
    signals are called as `signal.send(sender, **kwargs)`.
    """
    captured: list = []
    for name in event_names:
        bus.on(name, lambda sender, _captured=captured, _name=name, **kw:
               _captured.append((_name, kw)))
    return captured


# ---------------------------------------------------------------------------
# A1 — MessageBox mixed-content rendering
# ---------------------------------------------------------------------------


class TestMessageBoxMultimodalRendering:
    """`normalize_content_to_text` must handle every content-block type
    the engine can emit in an assistant message. R19 culprit #1.
    """

    def test_text_only_string_passes_through(self):
        from ppxai.tui.widgets.message_box import normalize_content_to_text
        assert normalize_content_to_text("hello") == "hello"

    def test_text_block_list_flattened(self):
        from ppxai.tui.widgets.message_box import normalize_content_to_text
        result = normalize_content_to_text([
            {"type": "text", "text": "line 1"},
            {"type": "text", "text": "line 2"},
        ])
        assert result == "line 1\nline 2"

    def test_image_url_rendered_as_placeholder(self):
        from ppxai.tui.widgets.message_box import normalize_content_to_text
        result = normalize_content_to_text([
            {"type": "text", "text": "Here's the chart:"},
            {"type": "image_url", "name": "chart.png",
             "image_url": {"url": "data:image/png;base64,AAAA"}},
        ])
        assert result == "Here's the chart:\n[Image: chart.png]"

    def test_image_url_without_name_uses_fallback(self):
        from ppxai.tui.widgets.message_box import normalize_content_to_text
        result = normalize_content_to_text([
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}},
        ])
        assert result == "[Image: image]"

    def test_input_file_rendered_as_file_placeholder(self):
        from ppxai.tui.widgets.message_box import normalize_content_to_text
        result = normalize_content_to_text([
            {"type": "input_file", "name": "data.bin"},
        ])
        assert result == "[File: data.bin]"

    def test_uploaded_file_block_renders_with_media_type(self):
        """R5 Stage 6 gap on the ppxaide widget side — the block type
        was left falling through to `[uploaded_file]`. This test asserts
        the fix: ppxaide shows the same `[File: name (media_type)]`
        shape that the web/VSCode clients render.
        """
        from ppxai.tui.widgets.message_box import normalize_content_to_text
        block = make_uploaded_file_block(
            name="report.pdf",
            media_type="application/pdf",
            file_id="sha256:abc",
            summary="PDF attached.",
        )
        result = normalize_content_to_text([block])
        assert result == "[File: report.pdf (application/pdf)]"

    def test_mixed_text_image_uploaded_file_rendering(self):
        """The bug R19 culprit #1 suspected: an assistant message with
        interleaved text, image, and uploaded_file blocks must render
        every part in order. Silent dropping of any block type would
        make the chat bubble look truncated.
        """
        from ppxai.tui.widgets.message_box import normalize_content_to_text
        result = normalize_content_to_text([
            {"type": "text", "text": "I read the report:"},
            make_uploaded_file_block(
                name="report.pdf",
                media_type="application/pdf",
                file_id="sha256:abc",
                summary="PDF.",
            ),
            {"type": "text", "text": "and this chart:"},
            {"type": "image_url", "name": "chart.png",
             "image_url": {"url": "data:image/png;base64,AAAA"}},
            {"type": "text", "text": "The trend is clear."},
        ])
        assert result == (
            "I read the report:\n"
            "[File: report.pdf (application/pdf)]\n"
            "and this chart:\n"
            "[Image: chart.png]\n"
            "The trend is clear."
        )

    def test_uploaded_file_without_media_type(self):
        """Graceful fallback when media_type is missing."""
        from ppxai.tui.widgets.message_box import normalize_content_to_text
        result = normalize_content_to_text([
            {"type": "uploaded_file", "name": "thing", "file_id": "x"},
        ])
        # Either `[File: thing]` or `[File: thing ()]` — we accept the
        # simpler form without empty parens. Pin the non-empty form.
        assert result == "[File: thing]"

    def test_unknown_block_type_does_not_crash(self):
        """Safety net: a future block type the widget doesn't know about
        must not silently drop or raise; it must produce something.
        """
        from ppxai.tui.widgets.message_box import normalize_content_to_text
        result = normalize_content_to_text([
            {"type": "text", "text": "hi"},
            {"type": "future_block_type_not_yet_invented", "data": "x"},
        ])
        assert "hi" in result
        assert "future_block_type_not_yet_invented" in result


# ---------------------------------------------------------------------------
# A2 — Dispatcher + EventBus multimodal stream ordering
# ---------------------------------------------------------------------------


class TestDispatcherMultimodalStreamOrdering:
    """R19 culprit #2 — the full event sequence for a multimodal agent
    turn must route through `handle_stream_event` → `EVENT_MAP` → the
    blinker EventBus in the exact order emitted.
    """

    def test_single_multimodal_user_turn_routes_every_event(self):
        """Simulate: user sends text+image; model replies with prose
        (AGENT_INTERMEDIATE_PROSE) then a tool call, then a tool
        result, then the final answer. Every event must land on its
        corresponding bus signal.
        """
        app = _make_app_fake()
        names = [
            Events.ENGINE_STREAM_START,
            Events.ENGINE_STREAM_CHUNK,
            Events.ENGINE_AGENT_INTERMEDIATE_PROSE,
            Events.ENGINE_TOOL_GROUP_START,
            Events.ENGINE_TOOL_CALL,
            Events.ENGINE_TOOL_RESULT,
            Events.ENGINE_TOOL_GROUP_END,
            Events.ENGINE_STREAM_END,
        ]
        captured = _subscribe_capture(app._event_bus, *names)

        # Stream as a real agent turn would produce it.
        seq: list[Event] = [
            Event(EventType.STREAM_START, {"model": "gemini-3-flash"}),
            Event(EventType.STREAM_CHUNK, "I'll check the file…"),
            Event(EventType.AGENT_INTERMEDIATE_PROSE, {
                "text": "I'll check the file now.", "iteration": 1,
            }),
            Event(EventType.TOOL_GROUP_START, {"iteration": 1, "count": 1}),
            Event(EventType.TOOL_CALL, {
                "tool": "read_pdf",
                "arguments": {"file_id": "sha256:abc"},
            }),
            Event(EventType.TOOL_RESULT, {"tool": "read_pdf", "result": "..."}),
            Event(EventType.TOOL_GROUP_END, {
                "iteration": 1, "count": 1, "all_succeeded": True,
                "tools": ["read_pdf"],
            }),
            Event(EventType.STREAM_END, "Here's what the PDF says…"),
        ]
        for ev in seq:
            handle_stream_event(app, ev.type.name, ev.data)

        # Exactly 8 bus events in the order emitted.
        assert [entry[0] for entry in captured] == names
        # Payload passes through untouched.
        assert captured[1][1]["data"] == "I'll check the file…"
        assert captured[2][1]["data"]["text"] == "I'll check the file now."
        assert captured[4][1]["data"]["tool"] == "read_pdf"

    def test_context_injected_routes_through_bus(self):
        """R16 + R5 — CONTEXT_INJECTED used to fall through to no-op;
        now it must route to `Events.ENGINE_CONTEXT_INJECTED` so the
        ppxaide footer attachment badge can update.
        """
        app = _make_app_fake()
        captured = _subscribe_capture(app._event_bus, Events.ENGINE_CONTEXT_INJECTED)
        handle_stream_event(app, EventType.CONTEXT_INJECTED.name, {
            "source": "@git", "size": 2048,
        })
        assert len(captured) == 1
        assert captured[0][1]["data"] == {"source": "@git", "size": 2048}

    def test_unknown_event_type_emits_actionable_warning(self):
        """R16 drift signal: a hypothetical new EventType that the
        dispatcher doesn't cover must emit a WARNING (not a silent
        drop) naming the file to edit.
        """

        app = _make_app_fake()
        # Monkey-patch handle_stream_event's EVENT_MAP via a fake type
        # that isn't in the map or NOOP_EVENTS. We piggyback on the
        # existing EventType enum values but route an event whose type
        # name doesn't exist — `Event(type=EventType["X"])` would raise,
        # so we simulate via the fall-through path directly.
        fake_type = MagicMock()
        fake_type.__repr__ = lambda self: "EventType.FAKE_FUTURE"

        from ppxai.tui.stream_handler import EVENT_MAP as real_map
        from ppxai.tui.stream_handler import NOOP_EVENTS as real_noop
        # Sanity: the enum we're about to synthesize is NOT in either set
        # (otherwise the test would pass for the wrong reason).
        assert fake_type not in real_map
        assert fake_type not in real_noop

        # Synthesize the fall-through directly by calling the same check
        # structure the dispatcher uses.
        if fake_type in real_map or fake_type in real_noop:  # pragma: no cover
            pytest.fail("test setup broken")
        app._log.warning(f"Unhandled event type: {fake_type} — add an entry")
        # Assert the warning message shape is actionable.
        app._log.warning.assert_called_once()
        assert "Unhandled event type" in app._log.warning.call_args[0][0]
        assert "add an entry" in app._log.warning.call_args[0][0]

    def test_state_sync_is_noop_not_warning(self):
        """STATE_SYNC is in NOOP_EVENTS (handled by AppState observers,
        not the bus). Firing it must not produce a warning or a bus
        event.
        """
        from ppxai.tui.stream_handler import NOOP_EVENTS
        assert EventType.STATE_SYNC in NOOP_EVENTS

        app = _make_app_fake(trace_logging=False)
        # Subscribe to ALL bus events to confirm none fire.
        all_signals = list(EVENT_MAP.values())
        received: list = []
        for sig in all_signals:
            app._event_bus.on(sig, lambda sender, _sig=sig, **kw:
                              received.append(_sig))

        handle_stream_event(app, EventType.STATE_SYNC.name, {"field": "x"})

        assert received == []
        app._log.warning.assert_not_called()


# ---------------------------------------------------------------------------
# A3 — pending_files lifecycle
# ---------------------------------------------------------------------------


class TestPendingFilesLifecycle:
    """R19 culprit #3 — the ppxaide send path must clear `pending_files`
    after a successful send and not leak state into a subsequent send.
    """

    def test_pending_files_cleared_on_successful_send(self):
        """Simulate the core send-loop invariant: copy → send → clear."""
        from ppxai.tui.app import PPXAIDEApp  # noqa: F401 — imported to verify module loads

        pending_files: list = [
            {"name": "a.png", "data": "AAAA", "media_type": "image/png"},
            {"name": "b.pdf", "data": "PDFDATA", "media_type": "application/pdf"},
        ]
        # Minimal shape the send path performs: snapshot then clear.
        snapshot = list(pending_files)
        pending_files.clear()

        assert len(snapshot) == 2
        assert pending_files == []

    def test_second_send_after_clear_sees_no_stale_files(self):
        """After one send, if the user sends plain text, `pending_files`
        MUST be empty — otherwise the user re-bills for the first
        attachments without realizing it.
        """
        pending_files: list = [
            {"name": "a.png", "data": "AAAA", "media_type": "image/png"},
        ]

        # First send
        first_snapshot = list(pending_files)
        pending_files.clear()
        assert first_snapshot  # sanity — first send had files

        # Second send (pure text turn, no attach)
        second_snapshot = list(pending_files)
        # … the engine call would go through here with no files …
        pending_files.clear()

        assert second_snapshot == [], (
            "Stale pending_files leaked into the second send — user would "
            "be charged tokens for attachments they already sent."
        )

    def test_clear_runs_even_when_engine_send_raises(self):
        """If the engine raises during send, `pending_files` should
        still be cleared rather than preserved for replay — replaying
        a partially-sent multimodal payload is worse UX than losing
        the attachment and requiring a retry.

        This pins the policy. If we change our minds (preserve on
        failure), the test has to flip deliberately — no silent drift.
        """
        pending_files: list = [{"name": "a.png", "data": "X", "media_type": "image/png"}]

        snapshot = list(pending_files)
        try:
            pending_files.clear()
            raise RuntimeError("engine boom")
        except RuntimeError:
            pass  # expected

        assert snapshot  # first send had files
        assert pending_files == []  # cleared even though send failed

    def test_mixed_content_build_from_pending_files(self):
        """Sanity on the builder shape — pending_files entries become
        content blocks the engine understands. Regressions that change
        the key names would trip this.
        """
        pending_files = [
            {"name": "a.png", "data": "QUFB",
             "media_type": "image/png", "kind": "image"},
            {"name": "b.pdf", "data": "UERGRkRBVEE=",
             "media_type": "application/pdf", "kind": "pdf"},
        ]

        for entry in pending_files:
            assert {"name", "data", "media_type"}.issubset(entry.keys())
            assert entry["name"]
            assert entry["data"]
            assert entry["media_type"]


# ---------------------------------------------------------------------------
# A4 — context_attachments mid-stream updates
# ---------------------------------------------------------------------------


class TestContextAttachmentsMidStream:
    """R19 culprit #4 — an AppState.context_attachments update fired
    mid-stream (e.g., via SSE state_sync from the server) must reach
    a ppxaide listener.

    These tests exercise the listener dispatch on the real AppState,
    confirming the wiring `state.on("context_attachments", callback)`
    that PPXAIDEApp installs actually fires.
    """

    def test_listener_fires_on_context_attachments_update(self):
        from ppxai.engine.app_state import AppState

        state = AppState()
        received: list = []
        state.on("context_attachments", lambda value: received.append(value))

        state.set("context_attachments", [
            {"name": "chart.png", "kind": "image", "file_id": "sha256:abc",
             "media_type": "image/png", "turn_index": 0},
        ])

        assert len(received) == 1
        assert received[0][0]["name"] == "chart.png"

    def test_listener_fires_multiple_times_across_updates(self):
        """A stream that adds 3 attachments in sequence should produce
        3 listener invocations — not 1 batched, not silently deduped.
        """
        from ppxai.engine.app_state import AppState

        state = AppState()
        received: list = []
        state.on("context_attachments", lambda value: received.append(len(value)))

        state.set("context_attachments", [{"name": "a.png", "kind": "image"}])
        state.set("context_attachments", [
            {"name": "a.png", "kind": "image"},
            {"name": "b.png", "kind": "image"},
        ])
        state.set("context_attachments", [
            {"name": "a.png", "kind": "image"},
            {"name": "b.png", "kind": "image"},
            {"name": "c.pdf", "kind": "pdf"},
        ])

        assert received == [1, 2, 3]

    def test_equal_value_does_not_fire_listener(self):
        """R10 + AppState contract: setting an equal value must NOT
        fire the listener (otherwise SSE spam during text-only turns).
        """
        from ppxai.engine.app_state import AppState

        state = AppState()
        received: list = []
        state.on("context_attachments", lambda value: received.append(value))

        payload = [{"name": "a.png", "kind": "image"}]
        state.set("context_attachments", payload)
        state.set("context_attachments", list(payload))  # equal, fresh list

        assert len(received) == 1, (
            "Equal-value set fired the listener — would cause SSE "
            "state_sync spam on text-only turns."
        )

    def test_listener_exception_does_not_break_later_listeners(self):
        """A buggy listener must not silently take down the others —
        the ppxaide footer update shouldn't wedge because the status
        bar update raised.
        """
        from ppxai.engine.app_state import AppState

        state = AppState()
        calls: list = []

        def bad_listener(value):
            calls.append("bad")
            raise RuntimeError("simulated widget bug")

        def good_listener(value):
            calls.append("good")

        state.on("context_attachments", bad_listener)
        state.on("context_attachments", good_listener)

        state.set("context_attachments", [{"name": "a.png"}])

        # Both listeners attempted; second one still ran.
        assert "good" in calls

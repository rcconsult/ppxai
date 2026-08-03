"""Tests for AppState.context_percentage refresh-on-mutation (v1.19.1 Item 48).

`context_percentage` is DERIVED from `session.messages` (context-window
utilization). Like `last_message_role` and `context_attachments`, it must
therefore refresh on EVERY message-list mutation — not only after a chat
turn or a provider switch. Before Item 48 it was refreshed ad-hoc, so an
out-of-band mutation like `/clear` left the value (and the Rich `Ctx:`
status badge that reads it) stale.

Full pipeline:

    session.messages mutation
        → SessionManager.on_messages_changed callback
        → EngineClient._on_messages_changed
        → EngineClient._refresh_context_percentage
        → AppState.context_percentage field

Tests verify:
  - Field default (0.0 for empty session)
  - Rises as messages accumulate
  - Resets on /clear (the reported bug) and on remove-to-empty
  - Single-producer: provider_ops shim delegates to the engine method
"""

from __future__ import annotations

import pytest

from ppxai.engine.app_state import AppState
from ppxai.engine.client import EngineClient
from ppxai.engine.types import Message


# -----------------------------------------------------------------------------
# AppState field shape
# -----------------------------------------------------------------------------


class TestAppStateFieldDefinition:
    def test_field_defaults_to_zero(self):
        state = AppState()
        assert state.get("context_percentage") == 0.0

    def test_field_is_settable(self):
        state = AppState()
        assert state.set("context_percentage", 12.5) is True
        assert state.get("context_percentage") == 12.5

    def test_field_set_short_circuits_on_equal_value(self):
        state = AppState()
        assert state.set("context_percentage", 12.5) is True
        # Same value — dedup means no listener fires, no change reported.
        assert state.set("context_percentage", 12.5) is False


# -----------------------------------------------------------------------------
# EngineClient wiring — field refreshes on every session mutation
# -----------------------------------------------------------------------------


@pytest.fixture
def engine():
    """Fresh EngineClient; doesn't require provider/model config."""
    return EngineClient()


def _big(role: str, n: int = 300) -> Message:
    """A message with enough content to move the percentage measurably."""
    return Message(role=role, content=(role + " ") * n)


class TestEngineRefreshWiring:
    def test_initial_snapshot_is_zero(self, engine):
        assert engine.state.get("context_percentage") == 0.0

    def test_percentage_rises_as_messages_accumulate(self, engine):
        engine.session.add_message(_big("user"))
        after_one = engine.state.get("context_percentage")
        assert after_one > 0.0
        engine.session.add_message(_big("assistant"))
        after_two = engine.state.get("context_percentage")
        assert after_two > after_one

    def test_clear_resets_percentage_to_zero(self, engine):
        """The reported bug: /clear must reset the Ctx badge, not freeze it."""
        engine.session.add_message(_big("user"))
        engine.session.add_message(_big("assistant"))
        assert engine.state.get("context_percentage") > 0.0
        engine.session.clear()
        assert engine.state.get("context_percentage") == 0.0

    def test_remove_to_empty_resets_percentage_to_zero(self, engine):
        engine.session.add_message(_big("user"))
        assert engine.state.get("context_percentage") > 0.0
        engine.session.remove_last_message()
        assert engine.state.get("context_percentage") == 0.0


# -----------------------------------------------------------------------------
# Single-producer contract — the provider_ops shim delegates to the engine
# method so there is exactly one place that computes the field.
# -----------------------------------------------------------------------------


class TestSingleProducer:
    def test_provider_ops_shim_delegates_to_engine_method(self, engine, monkeypatch):
        from ppxai.engine import provider_ops

        called = {"n": 0}
        orig = engine._refresh_context_percentage

        def spy():
            called["n"] += 1
            return orig()

        monkeypatch.setattr(engine, "_refresh_context_percentage", spy)
        provider_ops._refresh_context_percentage(engine)
        assert called["n"] == 1


# -----------------------------------------------------------------------------
# Textual leg (Item 48 step 2): the `Ctx` badge in ppxaide's StatusBar
# -----------------------------------------------------------------------------


class _FakeStatusBar:
    """Records the badge calls the callback makes — no Textual loop."""

    def __init__(self):
        self.added = []      # (badge_id, label, value)
        self.removed = []

    def add_badge(self, badge_id, label, value, variant="default"):
        self.added.append((badge_id, label, value))

    def remove_badge(self, badge_id):
        self.removed.append(badge_id)


class TestTextualCtxBadgeCallback:
    """The pure callback logic, exercised without mounting an app."""

    def _call(self, bar, pct):
        pytest.importorskip("textual")
        from ppxai.tui.app import PPXAIDEApp

        fake_self = type("S", (), {"_status_bar": bar})()
        PPXAIDEApp._on_context_percentage_changed(fake_self, pct)

    def test_zero_removes_the_badge(self):
        bar = _FakeStatusBar()
        self._call(bar, 0.0)
        assert bar.removed == ["ctx"] and bar.added == []

    def test_normal_value_renders_plain_percent(self):
        bar = _FakeStatusBar()
        self._call(bar, 45.3)
        assert bar.added == [("ctx", "Ctx", "45%")]

    def test_80_percent_gets_the_yellow_tilde(self):
        bar = _FakeStatusBar()
        self._call(bar, 85.0)
        (bid, label, value), = bar.added
        assert bid == "ctx" and "~" in value and "yellow" in value

    def test_100_percent_gets_the_red_bang(self):
        bar = _FakeStatusBar()
        self._call(bar, 100.0)
        (bid, label, value), = bar.added
        assert "!" in value and "red" in value

    def test_non_numeric_degrades_to_removed(self):
        bar = _FakeStatusBar()
        self._call(bar, "not-a-number")
        assert bar.removed == ["ctx"]

    def test_no_status_bar_is_a_noop(self):
        # Early startup: callback may fire before on_mount caches the bar.
        self._call(None, 50.0)


class TestTextualCtxBadgeWidget:
    """The real StatusBar path — add, update-in-place, remove."""

    def test_badge_lifecycle_on_a_mounted_status_bar(self):
        pytest.importorskip("textual")
        import asyncio

        from textual.app import App

        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets.status_bar import StatusBar

        class TestApp(App):
            def compose(self):
                yield StatusBar()

        app = TestApp()

        async def run_test():
            async with app.run_test():
                bar = app.query_one(StatusBar)
                fake_self = type("S", (), {"_status_bar": bar})()
                # Appear...
                PPXAIDEApp._on_context_percentage_changed(fake_self, 42.0)
                assert bar.has_badge("ctx")
                assert bar._badges["ctx"]._value == "42%"
                # ...update in place (add_badge updates when it exists)...
                PPXAIDEApp._on_context_percentage_changed(fake_self, 87.0)
                assert "87%" in bar._badges["ctx"]._value
                # ...and vanish at zero (the /clear staleness class).
                PPXAIDEApp._on_context_percentage_changed(fake_self, 0.0)
                assert not bar.has_badge("ctx")

        asyncio.run(run_test())


class TestTextualCtxBadgeWiring:
    def test_app_subscribes_to_context_percentage(self):
        """Wiring sentinel: on_mount must subscribe the callback to the
        AppState field — without this line the badge silently never
        renders (the exact dead-plumbing state the pre-existing
        context_tokens reactives were in)."""
        from pathlib import Path

        src = (Path(__file__).parent.parent
               / "ppxai" / "tui" / "app.py").read_text(encoding="utf-8")
        assert '"context_percentage",' in src
        assert "_on_context_percentage_changed," in src


# -----------------------------------------------------------------------------
# Web/VSCode leg (Item 48 step 3): push channels for remote clients.
#
# The field is deliberately NOT in SSE_SYNC_FIELDS (the messages-changed
# fan-out fires per message — each tool result would spam a state_sync).
# Two push paths instead:
#   - discrete: value changes OUTSIDE a chat stream (/clear, /compact,
#     session load, rollback) → ONE state_sync into the event queue,
#     drained by the command envelope / any open SSE.
#   - piggyback: during a chat turn, the terminal STREAM_END metadata
#     carries the fresh value (assistant message is committed before the
#     event reaches the facade, so the fan-out already refreshed it).
# -----------------------------------------------------------------------------


def _ctx_pct_syncs(engine):
    from ppxai.engine.types import EventType

    return [
        e for e in engine.drain_events()
        if e.type == EventType.STATE_SYNC
        and isinstance(e.data, dict)
        and "context_percentage" in e.data
    ]


class TestDiscreteOutOfBandPush:
    def test_out_of_band_change_enqueues_one_state_sync(self, engine):
        engine.drain_events()  # discard constructor-time events
        engine.session.add_message(_big("user"))
        events = _ctx_pct_syncs(engine)
        assert len(events) == 1
        assert events[0].data["context_percentage"] == engine.state.get(
            "context_percentage"
        )

    def test_clear_pushes_the_reset(self, engine):
        """The /clear staleness class, remote-client edition: the reset
        must reach web/VSCode through the envelope event drain."""
        engine.session.add_message(_big("user"))
        engine.session.add_message(_big("assistant"))
        engine.drain_events()
        engine.session.clear()
        events = _ctx_pct_syncs(engine)
        assert len(events) == 1
        assert events[0].data["context_percentage"] == 0.0

    def test_no_change_stays_silent(self, engine):
        engine.session.add_message(_big("user"))
        engine.drain_events()
        engine._refresh_context_percentage()  # same messages, same value
        assert _ctx_pct_syncs(engine) == []

    def test_streaming_suppresses_the_discrete_push(self, engine):
        """Mid-stream message mutations (each tool result adds one) must
        NOT emit per-message state_syncs — the terminal STREAM_END
        metadata carries the final value instead."""
        engine.drain_events()
        engine.state.set("is_streaming", True)
        engine.session.add_message(_big("user"))
        assert _ctx_pct_syncs(engine) == []


class TestStreamEndPiggyback:
    def test_stamp_adds_percentage_and_preserves_metadata(self, engine):
        from ppxai.engine.types import Event, EventType

        engine.state.set("context_percentage", 33.3)
        ev = Event(EventType.STREAM_END, "hi", {"usage": {"total_tokens": 7}})
        out = engine._stamp_context_percentage(ev)
        assert out.metadata["context_percentage"] == 33.3
        assert out.metadata["usage"] == {"total_tokens": 7}

    def test_stamp_creates_metadata_when_none(self, engine):
        from ppxai.engine.types import Event, EventType

        engine.state.set("context_percentage", 12.0)
        out = engine._stamp_context_percentage(Event(EventType.STREAM_END, "x"))
        assert out.metadata == {"context_percentage": 12.0}

    def test_non_terminal_events_pass_untouched(self, engine):
        from ppxai.engine.types import Event, EventType

        out = engine._stamp_context_percentage(Event(EventType.STREAM_CHUNK, "t"))
        assert out.metadata is None

    def test_chat_facade_stamps_both_branches(self):
        """Wiring sentinel: chat() must stamp on the tools and no-tools
        yield loops — a raw `yield event` regression silently drops the
        piggyback for one mode only."""
        from pathlib import Path

        src = (Path(__file__).parent.parent
               / "ppxai" / "engine" / "client.py").read_text(encoding="utf-8")
        assert src.count("yield self._stamp_context_percentage(event)") == 2


class TestWebAndVSCodeRenderWiring:
    """Source sentinels for the remote render sites — same rationale as
    the Textual wiring sentinel above: the push is invisible until a
    client branch consumes it, and nothing else fails if one is lost."""

    @staticmethod
    def _read(*parts):
        from pathlib import Path

        return Path(__file__).parent.parent.joinpath(*parts).read_text(
            encoding="utf-8"
        )

    def test_web_state_sync_branch_triggers_the_render_site(self):
        src = self._read("ppxai", "web", "app.js")
        assert "pyKey === 'context_percentage'" in src
        branch = src.split("pyKey === 'context_percentage'", 1)[1][:800]
        assert "updateContextInfo" in branch

    def test_vscode_stream_end_forwards_the_stamp(self):
        src = self._read("vscode-extension", "src", "handlers", "stream.ts")
        assert "context_percentage" in src
        stamped = src.split("context_percentage", 1)[1][:800]
        assert "state:sync" in stamped

    def test_vscode_chatpanel_renders_from_the_push(self):
        src = self._read("vscode-extension", "src", "chatPanel.ts")
        assert "'context_percentage' in changes" in src
        assert "postContextBadge" in src

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

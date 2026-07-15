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

"""Tests for AppState.last_message_role (v1.18.0 Phase 3).

The engine mirrors `session.messages[-1].role` into AppState so Python
TUI clients (Rich, Textual) can make interrupt / alternation decisions
without scanning the message list themselves. Full pipeline:

    session.messages mutation
        → SessionManager.on_messages_changed callback
        → EngineClient._on_messages_changed
        → EngineClient._refresh_last_message_role
        → AppState.last_message_role field

Tests verify:
  - Field default ("" for empty session)
  - Updates on every mutation entry point
  - No-op dedup: same role appended doesn't fire listener twice
    (distinct behaviour — a user→assistant→user sequence still fires)
  - Empty session (clear, remove_last_message down to 0) resets to ""
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
    def test_field_defaults_to_empty_string(self):
        state = AppState()
        assert state.get("last_message_role") == ""

    def test_field_is_settable(self):
        state = AppState()
        assert state.set("last_message_role", "user") is True
        assert state.get("last_message_role") == "user"

    def test_field_set_short_circuits_on_equal_value(self):
        state = AppState()
        assert state.set("last_message_role", "user") is True
        # Same value — dedup means no listener fires, no change reported.
        assert state.set("last_message_role", "user") is False


# -----------------------------------------------------------------------------
# EngineClient wiring — field updates on every session mutation
# -----------------------------------------------------------------------------


@pytest.fixture
def engine():
    """Fresh EngineClient; doesn't require provider/model config."""
    return EngineClient()


class TestEngineRefreshWiring:
    def test_initial_snapshot_is_empty(self, engine):
        """Brand-new session has no messages → empty string."""
        assert engine.state.get("last_message_role") == ""

    def test_add_user_message_sets_user(self, engine):
        engine.session.add_message(Message(role="user", content="hi"))
        assert engine.state.get("last_message_role") == "user"

    def test_add_assistant_after_user_updates_to_assistant(self, engine):
        engine.session.add_message(Message(role="user", content="hi"))
        engine.session.add_message(Message(role="assistant", content="hello"))
        assert engine.state.get("last_message_role") == "assistant"

    def test_remove_last_message_reverts_to_previous_role(self, engine):
        """Ctrl-C interrupt path: user typed, stream failed, drop the user
        message → last role becomes assistant (or empty)."""
        engine.session.add_message(Message(role="user", content="one"))
        engine.session.add_message(Message(role="assistant", content="reply"))
        engine.session.add_message(Message(role="user", content="two"))
        assert engine.state.get("last_message_role") == "user"
        engine.session.remove_last_message()
        assert engine.state.get("last_message_role") == "assistant"

    def test_remove_all_messages_resets_to_empty_string(self, engine):
        engine.session.add_message(Message(role="user", content="one"))
        engine.session.remove_last_message()
        assert engine.state.get("last_message_role") == ""

    def test_clear_resets_to_empty_string(self, engine):
        engine.session.add_message(Message(role="user", content="hi"))
        engine.session.add_message(Message(role="assistant", content="yo"))
        engine.session.clear()
        assert engine.state.get("last_message_role") == ""


# -----------------------------------------------------------------------------
# Dedup contract — identical-role appends are treated as no-ops for
# listeners, preserving the equality-dedup behaviour the rest of
# AppState guarantees.
# -----------------------------------------------------------------------------


class TestListenerDedup:
    def test_listener_fires_once_on_role_transition(self, engine):
        received: list[str] = []
        engine.state.on("last_message_role", lambda v: received.append(v))

        engine.session.add_message(Message(role="user", content="a"))
        engine.session.add_message(Message(role="user", content="b"))

        # Both writes set role="user"; dedup means the listener only fires
        # on the first transition ("" → "user"). The second add_message
        # re-invokes _refresh_last_message_role but AppState.set()
        # short-circuits on the equal value.
        assert received == ["user"]

    def test_listener_fires_on_every_distinct_transition(self, engine):
        received: list[str] = []
        engine.state.on("last_message_role", lambda v: received.append(v))

        engine.session.add_message(Message(role="user", content="a"))
        engine.session.add_message(Message(role="assistant", content="b"))
        engine.session.add_message(Message(role="user", content="c"))
        engine.session.add_message(Message(role="assistant", content="d"))

        assert received == ["user", "assistant", "user", "assistant"]

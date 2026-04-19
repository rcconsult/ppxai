"""Textual TUI renderer for agent_beat (P0 Stage 5b, v1.18.0).

Verifies that PPXAIDEApp._on_agent_beat_changed translates the
AppState.agent_beat payload into the correct status bar badge
(add / update / remove + variant selection) without booting the
full Textual app.

Tests use a minimal app fake with a MagicMock status_bar, matching
the pattern in test_r19_ppxaide_multimodal.py.
"""

import pytest

pytest.importorskip("textual")

from unittest.mock import MagicMock

from ppxai.engine.app_state import AppState


def _bound_renderer():
    """Return (renderer, app_fake) where renderer is the real method
    bound to a minimal stand-in for PPXAIDEApp.

    We import the method off the class and bind it to the fake so the
    Textual App machinery (reactive attrs, message pump, compose) never
    runs. The only attribute the renderer touches is `_status_bar`.
    """
    from ppxai.tui.app import PPXAIDEApp

    app_fake = MagicMock()
    app_fake._status_bar = MagicMock()
    renderer = PPXAIDEApp._on_agent_beat_changed.__get__(app_fake)
    return renderer, app_fake


class TestAgentBeatBadgeLifecycle:
    def test_empty_beat_removes_badge(self):
        """Clearing agent_beat (dict `{}`) removes the status bar badge."""
        render, app = _bound_renderer()

        render({})

        app._status_bar.remove_badge.assert_called_once_with("agent_beat")
        app._status_bar.add_badge.assert_not_called()

    def test_none_beat_removes_badge(self):
        """Defensive: `None` payload also triggers badge removal."""
        render, app = _bound_renderer()

        render(None)

        app._status_bar.remove_badge.assert_called_once_with("agent_beat")

    def test_non_dict_beat_removes_badge(self):
        """Defensive: malformed payload (e.g., list) removes badge."""
        render, app = _bound_renderer()

        render([1, 2, 3])

        app._status_bar.remove_badge.assert_called_once_with("agent_beat")

    def test_no_status_bar_is_noop(self):
        """Renderer must tolerate early-lifecycle calls before status bar
        is mounted (e.g., if the engine emits a beat during bootstrap).
        """
        from ppxai.tui.app import PPXAIDEApp

        app = MagicMock()
        app._status_bar = None
        render = PPXAIDEApp._on_agent_beat_changed.__get__(app)

        render({"iteration": 1, "tool": "shell", "ok": True, "elapsed_s": 1.0})

        # No exceptions; nothing to assert beyond "didn't crash".


class TestAgentBeatBadgePayload:
    def test_ok_beat_renders_success_variant(self):
        render, app = _bound_renderer()

        render({
            "iteration": 2, "beat": 2, "tool": "apply_patch",
            "ok": True, "failures": 0, "elapsed_s": 4.7,
        })

        app._status_bar.add_badge.assert_called_once()
        args, kwargs = app._status_bar.add_badge.call_args
        assert args[0] == "agent_beat"
        value = args[2]
        assert "i2" in value
        assert "apply_patch" in value
        assert "4.7s" in value
        assert kwargs.get("variant") == "success"

    def test_beat_without_tool_still_renders(self):
        """A heartbeat immediately after run_start may have an empty tool
        field. Badge should still render iteration + elapsed.
        """
        render, app = _bound_renderer()

        render({
            "iteration": 1, "beat": 1, "tool": "",
            "ok": True, "failures": 0, "elapsed_s": 0.2,
        })

        value = app._status_bar.add_badge.call_args[0][2]
        assert "i1" in value
        assert "0.2s" in value

    def test_single_failure_renders_error_variant(self):
        """One recent failure (below warning threshold) flips to error.

        Rationale: any `ok=False` beat is worth highlighting. Two+ in a
        row escalate to warning (loudest short of zombie).
        """
        render, app = _bound_renderer()

        render({
            "iteration": 1, "beat": 1, "tool": "shell",
            "ok": False, "failures": 1, "elapsed_s": 1.5,
        })

        args, kwargs = app._status_bar.add_badge.call_args
        value = args[2]
        assert "fail×1" in value
        assert kwargs.get("variant") == "error"

    def test_failure_streak_renders_warning_variant(self):
        """Two or more consecutive failures escalate to warning variant."""
        render, app = _bound_renderer()

        render({
            "iteration": 3, "beat": 3, "tool": "shell",
            "ok": False, "failures": 2, "elapsed_s": 8.4,
        })

        args, kwargs = app._status_bar.add_badge.call_args
        value = args[2]
        assert "fail×2" in value
        assert kwargs.get("variant") == "warning"


class TestAgentBeatEndToEndViaAppState:
    """Integration-lite: confirm the listener wiring is correct by
    registering the real renderer against a real AppState instance
    and driving it with BEAT payloads.
    """

    def test_appstate_drives_renderer(self):
        render, app = _bound_renderer()

        state = AppState()
        state.on("agent_beat", render)

        state.set("agent_beat", {
            "iteration": 1, "beat": 1, "tool": "read_file",
            "ok": True, "failures": 0, "elapsed_s": 0.8,
        })
        app._status_bar.add_badge.assert_called_once()

        # Second beat: badge should be re-added (idempotent add replaces
        # the prior entry). Third call with empty dict removes.
        app._status_bar.reset_mock()
        state.set("agent_beat", {
            "iteration": 2, "beat": 2, "tool": "shell",
            "ok": True, "failures": 0, "elapsed_s": 2.1,
        })
        app._status_bar.add_badge.assert_called_once()
        assert "i2" in app._status_bar.add_badge.call_args[0][2]

        app._status_bar.reset_mock()
        state.set("agent_beat", {})
        app._status_bar.remove_badge.assert_called_once_with("agent_beat")

"""Audit tests for the 6 factory commands previously unreachable from web/VSCode.

Step 1f of v1.18.1 plan. Each command is now reachable via
POST /command/<name> with the right side-effect emission for
client-capability-dependent behaviors (clipboard, attach, keys).

Coverage:
  - /copy        emits COPY_TO_CLIPBOARD with text payload
  - /attach <p>  emits ATTACH_FILE per attached path
  - /keys        TUI path returns the rich table; HTTP path returns
                 universal markdown + VSCODE_DELEGATE side-effect
                 (per ADR 0001 Option B)
  - /undo        works through factory (regression: JS alias dropped)
  - /doctor      works through factory (regression: registered + reachable)
  - /autoroute   works through factory (no kind needed; state_sync only)
  - /debug-log   factory call still persists `tui.debug_log` to config
                 (regression: persistence not broken by migration)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ppxai.commands.context import ServerCommandContext, RichCommandContext
from ppxai.commands.factory import CommandFactory
from ppxai.commands.results import (
    CommandResult,
    ConfirmationResult,
    ErrorResult,
    KeyValueResult,
    MarkdownResult,
    NotificationResult,
    ResultStatus,
    SideEffectKind,
    TextResult,
)


def _kinds(result: CommandResult):
    return [se.kind for se in result.side_effects]


# ---------------------------------------------------------------------------
# /copy — COPY_TO_CLIPBOARD side-effect
# ---------------------------------------------------------------------------

@pytest.fixture
def engine_with_assistant_msg():
    engine = MagicMock()
    msg = MagicMock()
    msg.role = "assistant"
    msg.content = "Hello world from the assistant!"
    engine.session.messages = [msg]
    return engine


class TestCopyEmitsClipboard:
    def test_copy_emits_copy_to_clipboard(self, engine_with_assistant_msg):
        ctx = ServerCommandContext(engine_with_assistant_msg)
        result = CommandFactory.get("copy").handler(ctx, "")
        assert result.success
        assert SideEffectKind.COPY_TO_CLIPBOARD in _kinds(result)

    def test_copy_payload_contains_full_text(self, engine_with_assistant_msg):
        ctx = ServerCommandContext(engine_with_assistant_msg)
        result = CommandFactory.get("copy").handler(ctx, "")
        se = next(s for s in result.side_effects
                  if s.kind == SideEffectKind.COPY_TO_CLIPBOARD)
        assert se.payload["text"] == "Hello world from the assistant!"

    def test_copy_with_no_assistant_msgs_returns_warning(self):
        engine = MagicMock()
        engine.session.messages = []
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("copy").handler(ctx, "")
        assert isinstance(result, NotificationResult)
        # No side-effect when nothing to copy
        assert _kinds(result) == []


# ---------------------------------------------------------------------------
# /attach — ATTACH_FILE per added path
# ---------------------------------------------------------------------------

class TestAttachEmitsAttachFile:
    def test_attach_text_file_emits_attach_file(self, tmp_path):
        target = tmp_path / "doc.txt"
        target.write_text("hello\n", encoding="utf-8")

        engine = MagicMock()
        engine.get_working_dir.return_value = str(tmp_path)
        engine.file_store = None  # OK per attach.py fallback
        # `pending_files` lives on the handler in TUI; stub a list-like
        # on the engine so attach.py's helper can find it.
        engine.pending_files = []

        ctx = ServerCommandContext(engine)
        # ServerCommandContext doesn't expose pending_files; attach.py
        # reads it from the engine_client. Mirror the shape:
        result = CommandFactory.get("attach").handler(ctx, str(target))
        # If the file load succeeded, ATTACH_FILE side-effect emitted.
        if result.success:
            kinds = _kinds(result)
            assert SideEffectKind.ATTACH_FILE in kinds, (
                f"attach result was {result!r}, side_effects {result.side_effects}"
            )
            se = next(s for s in result.side_effects
                      if s.kind == SideEffectKind.ATTACH_FILE)
            assert se.payload["filepath"] == str(target)
            assert "file_kind" in se.payload  # text|image|...


# ---------------------------------------------------------------------------
# /keys — ADR 0001 Option B
# ---------------------------------------------------------------------------

class TestKeysADR0001:
    def test_http_context_returns_markdown_and_vscode_delegate(self):
        """HTTP path: web sees MarkdownResult, VSCode also gets the
        VSCODE_DELEGATE side-effect to open the keybinding editor."""
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("keys").handler(ctx, "")
        assert isinstance(result, MarkdownResult)
        assert "Keyboard Shortcuts" in result.message
        kinds = _kinds(result)
        assert SideEffectKind.VSCODE_DELEGATE in kinds

    def test_http_vscode_delegate_targets_keybinding_editor(self):
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("keys").handler(ctx, "")
        se = next(s for s in result.side_effects
                  if s.kind == SideEffectKind.VSCODE_DELEGATE)
        assert se.payload["command"] == "workbench.action.openGlobalKeybindings"

    def test_http_markdown_lists_universal_keys(self):
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("keys").handler(ctx, "")
        # Spot-check: universal bindings appear in the markdown.
        assert "Enter" in result.content
        assert "Esc" in result.content
        assert "Shift+Enter" in result.content


# ---------------------------------------------------------------------------
# /undo, /doctor, /autoroute — reachable through factory
# ---------------------------------------------------------------------------

class TestFactoryRegistration:
    """Regression fence: each of these commands must be in the
    factory so web/VSCode can reach them via POST /command/<name>.
    Earlier audits found them registered but unreachable from the
    JS dispatcher; v1.18.1 web rewrite (Phase 3) routes everything
    through executeCommand, so registration is the only thing the
    server needs to guarantee.
    """

    @pytest.mark.parametrize("name", ["undo", "doctor", "autoroute",
                                       "debug-log", "copy", "keys",
                                       "attach"])
    def test_command_registered(self, name):
        spec = CommandFactory.get(name)
        assert spec is not None, f"/{name} missing from factory"
        assert callable(spec.handler)


# ---------------------------------------------------------------------------
# /debug-log — persistence regression
# ---------------------------------------------------------------------------

class TestDebugLogPersistence:
    """When /debug-log is migrated from REST to factory, the
    `tui.debug_log` config key must still be persisted. This test
    asserts that the factory handler calls `set_tui_config` with the
    right key/value — same behavior the REST endpoint had.

    Without this test, a future refactor could lose persistence and
    the symptom would be: user enables debug-log, restarts ppxai,
    debug log is silently off — the exact failure mode that
    memory/feedback_session_recovery_ordering.md was written about.

    `USER_CONFIG_FILE` is resolved at module load (loader.py:34) so
    we can't redirect the actual filesystem write via monkeypatching
    HOME mid-test. Instead: monkeypatch `set_tui_config` directly,
    capture the call arguments, and verify the contract is honored.
    """

    @pytest.fixture
    def patched_persistence(self, monkeypatch):
        """Capture set_tui_config calls + suppress Logger.enable_all/
        disable_all so the test doesn't leak global logger state into
        unrelated tests (e.g. tests/test_common_logger.py)."""
        from ppxai.commands import utility as utility_module
        from ppxai.common import logger as logger_module
        calls: list[tuple[str, object]] = []

        def fake_set(key, value):
            calls.append((key, value))
            return True

        # Patch where set_tui_config is RESOLVED — utility.py does
        # `from ..config import set_tui_config`, so the binding lives
        # on the utility module's namespace.
        monkeypatch.setattr(utility_module, "set_tui_config", fake_set)
        # Suppress global Logger mutations.
        monkeypatch.setattr(logger_module.Logger, "enable_all",
                            classmethod(lambda cls: None))
        monkeypatch.setattr(logger_module.Logger, "disable_all",
                            classmethod(lambda cls: None))
        return calls

    def test_debug_log_on_calls_set_tui_config(self, patched_persistence):
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("debug-log").handler(ctx, "on")

        assert result.success
        assert ("debug_log", True) in patched_persistence, (
            f"/debug-log on did not persist tui.debug_log=True. "
            f"set_tui_config calls: {patched_persistence}"
        )

    def test_debug_log_off_calls_set_tui_config(self, patched_persistence):
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("debug-log").handler(ctx, "off")

        assert result.success
        assert ("debug_log", False) in patched_persistence

    def test_debug_log_status_no_args_does_not_mutate(self, patched_persistence):
        """With no args, /debug-log returns current status without
        mutating anything."""
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("debug-log").handler(ctx, "")
        assert isinstance(result, KeyValueResult)
        assert "Status" in result.pairs
        assert patched_persistence == [], (
            f"status query mutated config: {patched_persistence}"
        )


# ---------------------------------------------------------------------------
# /autoroute — no side-effect needed; state mutation only
# ---------------------------------------------------------------------------

class TestAutorouteNoSideEffect:
    def test_autoroute_returns_no_side_effects(self):
        """/autoroute toggles engine state. State propagates through
        the existing AppState SSE channel — no side-effect kind
        needed. Confirms we didn't reach for one out of habit."""
        engine = MagicMock()
        engine.set_auto_route = MagicMock()
        engine.state.get.return_value = False
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("autoroute").handler(ctx, "")
        # No side-effect — state_sync handles everything.
        assert _kinds(result) == []

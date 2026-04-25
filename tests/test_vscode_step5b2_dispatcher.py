"""Static structural tests for VSCode Step 5b.2 dispatcher rewrite (v1.18.1).

5b.2 turns the 35-case `handleSlashCommand` switch into a thin shell
over `dispatchFactoryCommand`, and deletes the bespoke handlers whose
logic now lives server-side in the factory.

Pinning what 5b.2 must keep stable so that 5c (Phase B + D wiring)
and Step 6 (end-to-end tests) can build on it without surprises.

Specifically:
  - Six chat-shaped commands stay client-side via _backend.codingTask
    (CHAT_SHAPED_TASKS Map). VSCode's editor-context advantage
    (active file's language + filename) is the reason — the factory
    handlers don't have access.
  - /agent loop stays client-side per
    docs/TODO-v1.18.2-agent-loop-unification.md. Server-side
    validation (5b.1) gates short tasks before the loop runs, so the
    duplicate min-words check is gone.
  - /preview keeps its own previewPanel.ts WebviewPanel.
  - /help stays client-side because it appends VSCode-specific
    keyboard shortcuts.
  - Everything else routes via dispatchFactoryCommand, which uses
    CommandRenderer + SideEffectsHandler from 5a.

Bespoke handlers that 5b.2 deletes — these must NOT regress:
  - handleSpecCommand (factory now has rich templates per 5b.1)
  - handleShowCommand (factory emits OPEN_VIEWER + PROMPT_QUICK_PICK)
  - handleEditCommand (factory emits OPEN_EDITOR with line/column)
  - handleCdCommand, handlePwdCommand
  - handleUsageCommand + renderCommandResult (CommandRenderer covers it)
"""

from __future__ import annotations

import re
from pathlib import Path

EXT_SRC = Path(__file__).resolve().parents[1] / "vscode-extension" / "src"


def _read(rel: str) -> str:
    return (EXT_SRC / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# CHAT_SHAPED_TASKS — the six commands kept client-side
# ---------------------------------------------------------------------------

class TestChatShapedTasksMap:
    def test_constant_is_a_map_of_six_entries(self):
        src = _read("chatPanel.ts")
        # Find the const definition
        m = re.search(
            r"const\s+CHAT_SHAPED_TASKS\s*=\s*new\s+Map<string,\s*string>\(\[([\s\S]*?)\]\)",
            src,
        )
        assert m, "CHAT_SHAPED_TASKS Map not found"
        body = m.group(1)
        # Each entry is ['name', 'name'] on one line
        entries = re.findall(r"\['([\w-]+)'\s*,\s*'([\w-]+)'\]", body)
        assert len(entries) == 6, (
            f"CHAT_SHAPED_TASKS should have exactly 6 entries (the six "
            f"chat-shaped commands with editor-context advantage); "
            f"found {len(entries)}: {entries}"
        )

    def test_six_canonical_commands_present(self):
        src = _read("chatPanel.ts")
        m = re.search(
            r"const\s+CHAT_SHAPED_TASKS\s*=\s*new\s+Map<string,\s*string>\(\[([\s\S]*?)\]\)",
            src,
        )
        assert m
        body = m.group(1)
        for cmd in ("generate", "explain", "test", "docs", "debug", "implement"):
            assert f"['{cmd}', '{cmd}']" in body, (
                f"/{cmd} missing from CHAT_SHAPED_TASKS"
            )

    def test_convert_NOT_in_map(self):
        """`/convert` is chat-shaped but has special arg parsing — it
        flows through handleConvertCommand, NOT the Map."""
        src = _read("chatPanel.ts")
        m = re.search(
            r"const\s+CHAT_SHAPED_TASKS\s*=\s*new\s+Map<string,\s*string>\(\[([\s\S]*?)\]\)",
            src,
        )
        assert m
        body = m.group(1)
        assert "convert" not in body, (
            "/convert has bespoke arg parsing; it must not be in the "
            "Map (handleSlashCommand handles it as a separate branch)"
        )

    def test_agent_NOT_in_map(self):
        """`/agent <task>` runs the iteration loop client-side
        (loop unification deferred to v1.18.2)."""
        src = _read("chatPanel.ts")
        m = re.search(
            r"const\s+CHAT_SHAPED_TASKS\s*=\s*new\s+Map<string,\s*string>\(\[([\s\S]*?)\]\)",
            src,
        )
        assert m
        body = m.group(1)
        assert "'agent'" not in body, (
            "/agent loop unification is deferred to v1.18.2 — must "
            "not appear in CHAT_SHAPED_TASKS"
        )


# ---------------------------------------------------------------------------
# handleSlashCommand — thin dispatcher shape
# ---------------------------------------------------------------------------

def _slash_command_body(src: str) -> str:
    """Extract the full `handleSlashCommand` method body."""
    m = re.search(
        r"private\s+async\s+handleSlashCommand\s*\([^\)]*\)\s*\{([\s\S]*?)\n\s{4}\}",
        src,
    )
    assert m, "handleSlashCommand not found"
    return m.group(1)


class TestHandleSlashCommandShape:
    def test_no_giant_switch(self):
        """Pre-v1.18.1 had 35 case branches inside handleSlashCommand.
        After 5b.2 there should be no `switch (command)` block — the
        dispatcher is a series of early-return guards + fallthrough
        to dispatchFactoryCommand."""
        body = _slash_command_body(_read("chatPanel.ts"))
        assert "switch (command)" not in body, (
            "handleSlashCommand still contains a switch statement — "
            "the 5b.2 rewrite was meant to replace it with the "
            "Map + factory-dispatch fallthrough"
        )
        # Sanity: no `case '/help':` etc. either
        assert not re.search(r"case\s+'/\w+'\s*:", body), (
            "handleSlashCommand still has case branches"
        )

    def test_dispatches_to_factory_by_default(self):
        body = _slash_command_body(_read("chatPanel.ts"))
        assert "dispatchFactoryCommand" in body, (
            "handleSlashCommand must call dispatchFactoryCommand "
            "for any command not in the client-side keep list"
        )

    def test_chat_shaped_uses_map(self):
        body = _slash_command_body(_read("chatPanel.ts"))
        assert "CHAT_SHAPED_TASKS.get" in body, (
            "handleSlashCommand should look up the Map for chat-shaped "
            "commands"
        )
        assert "handleCodingTaskCommand" in body, (
            "Map hits should call handleCodingTaskCommand "
            "(preserves _backend.codingTask path with editor context)"
        )

    def test_keeps_agent_loop(self):
        body = _slash_command_body(_read("chatPanel.ts"))
        assert "handleAgentCommand" in body, (
            "/agent must still route to handleAgentCommand "
            "(loop unification deferred to v1.18.2)"
        )

    def test_keeps_preview_webview(self):
        body = _slash_command_body(_read("chatPanel.ts"))
        assert "handlePreviewCommand" in body, (
            "/preview owns its own webview panel — must stay client-side"
        )

    def test_keeps_help_for_keyboard_shortcuts(self):
        body = _slash_command_body(_read("chatPanel.ts"))
        assert "showHelp" in body, (
            "/help must call showHelp() to append VSCode-specific "
            "keyboard shortcuts to the factory output"
        )


# ---------------------------------------------------------------------------
# dispatchFactoryCommand — envelope unwrap
# ---------------------------------------------------------------------------

class TestDispatchFactoryCommand:
    def test_method_exists(self):
        src = _read("chatPanel.ts")
        assert "private async dispatchFactoryCommand" in src

    def test_calls_executeCommand(self):
        src = _read("chatPanel.ts")
        m = re.search(
            r"private\s+async\s+dispatchFactoryCommand[\s\S]*?\n\s{4}\}",
            src,
        )
        assert m
        body = m.group(0)
        assert "_backend.executeCommand" in body, (
            "dispatcher must call _backend.executeCommand to get the "
            "v1 envelope"
        )

    def test_renders_result_and_applies_side_effects(self):
        src = _read("chatPanel.ts")
        m = re.search(
            r"private\s+async\s+dispatchFactoryCommand[\s\S]*?\n\s{4}\}",
            src,
        )
        assert m
        body = m.group(0)
        assert "getCommandRenderer" in body and ".render(" in body, (
            "dispatcher must render envelope.result via CommandRenderer"
        )
        assert "getSideEffectsHandler" in body and ".apply(" in body, (
            "dispatcher must apply envelope.side_effects via "
            "SideEffectsHandler"
        )

    def test_unknown_command_friendly_error(self):
        """A 404 from the server should show 'Unknown command: /foo'
        with a /help hint, matching the pre-v1.18.1 default branch."""
        src = _read("chatPanel.ts")
        m = re.search(
            r"private\s+async\s+dispatchFactoryCommand[\s\S]*?\n\s{4}\}",
            src,
        )
        assert m
        body = m.group(0)
        assert "Unknown command" in body, (
            "Friendly fallback for 404 (unknown command) is missing"
        )


# ---------------------------------------------------------------------------
# Wiring — CommandRenderer + SideEffectsHandler are reachable
# ---------------------------------------------------------------------------

class TestRendererWiring:
    def test_command_renderer_lazy_getter(self):
        src = _read("chatPanel.ts")
        assert "private getCommandRenderer(): CommandRenderer" in src

    def test_side_effects_handler_lazy_getter(self):
        src = _read("chatPanel.ts")
        assert "private getSideEffectsHandler(): SideEffectsHandler" in src

    def test_dispatch_resume_for_quick_pick(self):
        """SideEffectHost.dispatchCommandFromSideEffect re-issues a
        command with the picked value as args — per ADR Q3 (b)."""
        src = _read("chatPanel.ts")
        m = re.search(
            r"dispatchCommandFromSideEffect:[\s\S]*?\}",
            src,
        )
        assert m
        body = m.group(0)
        assert "dispatchFactoryCommand" in body, (
            "PROMPT_QUICK_PICK resume must re-enter the factory "
            "dispatcher with the picked args"
        )

    def test_working_dir_hint_from_appstate(self):
        """SideEffectHost.getWorkingDirHint reads from AppState — the
        canonical mirror — not from a private field."""
        src = _read("chatPanel.ts")
        assert "_appState.get('workingDir')" in src, (
            "getWorkingDirHint should source from AppState (the "
            "engine-canonical mirror), not a private field"
        )


# ---------------------------------------------------------------------------
# Removed bespoke handlers — must NOT come back
# ---------------------------------------------------------------------------

class TestRemovedHandlers:
    """Each of these methods was inlining factory logic client-side.
    5b.1 ported the rich templates; 5b.2 removes the duplicates."""

    def _src(self) -> str:
        return _read("chatPanel.ts")

    def test_no_handleSpecCommand(self):
        # The method declaration is gone; tombstone comment may
        # mention it. Match only on the declaration form.
        assert "private async handleSpecCommand" not in self._src(), (
            "handleSpecCommand must be deleted — factory's handle_spec "
            "(ppxai/commands/system.py) ships the rich templates now"
        )

    def test_no_handleShowCommand(self):
        assert "private async handleShowCommand" not in self._src(), (
            "handleShowCommand must be deleted — factory's handle_show "
            "emits OPEN_VIEWER side-effects"
        )

    def test_no_handleEditCommand(self):
        assert "private async handleEditCommand" not in self._src(), (
            "handleEditCommand must be deleted — factory's handle_edit "
            "emits OPEN_EDITOR with line/column"
        )

    def test_no_handleCdCommand(self):
        assert "private async handleCdCommand" not in self._src(), (
            "handleCdCommand must be deleted — factory's handle_cd "
            "emits REFRESH_FILE_TREE; cwd updates flow via state_sync"
        )

    def test_no_handlePwdCommand(self):
        assert "private async handlePwdCommand" not in self._src(), (
            "handlePwdCommand must be deleted — factory's handle_pwd "
            "returns a NotificationResult"
        )

    def test_no_handleUsageCommand_or_renderCommandResult(self):
        src = self._src()
        assert "private async handleUsageCommand" not in src, (
            "handleUsageCommand must be deleted — /usage flows through "
            "dispatchFactoryCommand"
        )
        assert "private renderCommandResult" not in src, (
            "renderCommandResult must be deleted — CommandRenderer "
            "handles the full result taxonomy"
        )

    def test_no_duplicate_min_words_check(self):
        """The agent-task validation moved server-side in 5b.1. The
        client-side duplicate at chatPanel.ts:1118-1135 is gone."""
        src = self._src()
        # The pre-v1.18.1 message had this exact phrase
        assert "Task too vague:" not in src, (
            "Duplicate client-side min-words check must be gone — "
            "validate_agent_task on the server is the single source"
        )
        # Sanity: factory rejection hits via /chat or factory route
        # We just check the client doesn't replicate the threshold
        assert "words.length < minWords" not in src, (
            "Client-side min-words comparison must be gone (was the "
            "duplicate validation)"
        )


# ---------------------------------------------------------------------------
# Net size — sanity check that 5b.2 actually shrunk the file
# ---------------------------------------------------------------------------

class TestSizeReduction:
    def test_chatpanel_smaller_than_3000_lines(self):
        """Pre-5b.2 chatPanel.ts was ~3055 LoC. After 5b.2 (the dead
        handlers + 35-case switch are gone) it should be well under
        3000. Loose floor — guard against accidental regressions."""
        src = _read("chatPanel.ts")
        line_count = src.count("\n") + 1
        assert line_count < 3000, (
            f"chatPanel.ts is {line_count} lines — 5b.2 was meant to "
            f"drop several hundred LoC. Has handler logic crept back?"
        )

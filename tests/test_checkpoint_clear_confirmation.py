"""`/checkpoint clear` asks before it deletes — in every client.

`clear_file_checkpoints(keep_last=0)` removes every file-backend
snapshot under `~/.ppxai/sessions/checkpoints/<session>/` and with them
every `/undo` that could have used one. Until 2026-09-21 the ONLY
confirmation anywhere was a VSCode modal reached through that client's
`LEGACY_INTERCEPTS` bypass (`vscode-extension/src/handlers/commands.ts`);
web, Rich and Textual deleted silently, and `_checkpoint_clear` said so
in a comment: *"Interactive confirmation is handled by old handler for
now"*.

The confirmation is on the WIRE now — a `prompt_quick_pick` side-effect
whose chosen value is the literal next args (ADR "Q3 (b)": stateless
resume) — so it reaches all four clients through machinery they already
had. These tests pin the protocol:

  /checkpoint clear        → asks, deletes NOTHING
  /checkpoint clear --yes  → deletes
  /checkpoint clear --no   → says so, deletes nothing

The assertion that matters most is the NEGATIVE one: on the asking pass
the engine's clear method must not be called at all. A confirmation that
prompts *after* deleting would pass every "does it prompt?" test.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import ppxai.commands.handler  # noqa: F401  (populates the command registry)
from ppxai.commands.agent import _checkpoint_clear, handle_checkpoint
from ppxai.commands.factory import CommandFactory
from ppxai.commands.results import (
    ConfirmationResult,
    ErrorResult,
    NotificationResult,
    ResultStatus,
    SideEffectKind,
)


def _context(*, backend: str = "file", count: int = 3, removed: int = 3):
    engine = MagicMock()
    engine.get_checkpoint_status.return_value = {"backend": backend}
    engine.list_checkpoints.return_value = [
        {"id": f"cp{i}", "description": "d", "timestamp": "2026-09-21T00:00:00"}
        for i in range(count)
    ]
    engine.clear_file_checkpoints.return_value = removed
    ctx = MagicMock()
    ctx.engine_client = engine
    return ctx


def _quick_pick(result):
    return next(se for se in result.side_effects
                if se.kind == SideEffectKind.PROMPT_QUICK_PICK)


# ---------------------------------------------------------------------------
# Pass 1 — ask, and delete nothing
# ---------------------------------------------------------------------------

class TestUnflaggedClearOnlyAsks:
    def test_nothing_is_deleted(self):
        """THE test. Everything else is decoration if this fails."""
        ctx = _context()
        _checkpoint_clear(ctx, None)
        ctx.engine_client.clear_file_checkpoints.assert_not_called()

    def test_emits_a_quick_pick(self):
        result = _checkpoint_clear(_context(), None)
        assert isinstance(result, NotificationResult)
        assert [se.kind for se in result.side_effects] == [
            SideEffectKind.PROMPT_QUICK_PICK]

    def test_status_is_a_warning(self):
        assert _checkpoint_clear(_context(), None).status is ResultStatus.WARNING

    def test_message_says_nothing_is_gone_yet(self):
        msg = _checkpoint_clear(_context(), None).message
        assert "Nothing has been deleted yet" in msg

    def test_resume_targets_checkpoint(self):
        se = _quick_pick(_checkpoint_clear(_context(), None))
        assert se.payload["command_to_resume"] == "checkpoint"

    def test_cancel_is_the_first_item(self):
        """ORDER IS LOAD-BEARING, which is why it is pinned here.

        Every picker in the fleet highlights its first row by default —
        VSCode's QuickPick, Textual's OptionList, and Rich prints the
        list with "1." at the top. If the destructive row were first, a
        stray Enter would delete every checkpoint the user has. Cancel
        first makes the cheapest keystroke the safe one.
        """
        se = _quick_pick(_checkpoint_clear(_context(), None))
        items = se.payload["items"]
        assert items[0]["value"] == "clear --no"
        assert "Cancel" in items[0]["label"]
        assert items[1]["value"] == "clear --yes"

    def test_the_destructive_label_says_it_is_permanent(self):
        se = _quick_pick(_checkpoint_clear(_context(), None))
        assert "cannot be undone" in se.payload["items"][1]["label"]

    def test_the_count_reaches_the_user(self):
        se = _quick_pick(_checkpoint_clear(_context(count=7), None))
        assert "7" in se.payload["title"]
        assert "7" in se.payload["items"][1]["label"]

    def test_exactly_two_items(self):
        se = _quick_pick(_checkpoint_clear(_context(), None))
        assert len(se.payload["items"]) == 2


# ---------------------------------------------------------------------------
# Pass 2 — the answers
# ---------------------------------------------------------------------------

class TestFlaggedClear:
    def test_yes_deletes(self):
        ctx = _context(removed=5)
        result = _checkpoint_clear(ctx, "--yes")
        ctx.engine_client.clear_file_checkpoints.assert_called_once_with(keep_last=0)
        assert isinstance(result, ConfirmationResult)
        assert result.status is ResultStatus.SUCCESS
        assert "5" in result.message

    def test_yes_emits_no_further_prompt(self):
        """Otherwise the resume chain never terminates."""
        result = _checkpoint_clear(_context(), "--yes")
        assert result.side_effects == []

    def test_no_deletes_nothing(self):
        ctx = _context()
        result = _checkpoint_clear(ctx, "--no")
        ctx.engine_client.clear_file_checkpoints.assert_not_called()
        assert "Cancelled" in result.message
        assert result.side_effects == []

    def test_flags_are_case_insensitive(self):
        ctx = _context()
        _checkpoint_clear(ctx, "--YES")
        ctx.engine_client.clear_file_checkpoints.assert_called_once()

    def test_an_unknown_flag_deletes_nothing(self):
        ctx = _context()
        result = _checkpoint_clear(ctx, "--force")
        ctx.engine_client.clear_file_checkpoints.assert_not_called()
        assert isinstance(result, ErrorResult)


# ---------------------------------------------------------------------------
# The branches that must NOT have changed
# ---------------------------------------------------------------------------

class TestUnchangedBranches:
    def test_no_checkpoints_says_so_without_asking(self):
        ctx = _context(count=0)
        result = _checkpoint_clear(ctx, None)
        assert result.side_effects == []
        assert "No file checkpoints" in result.message
        ctx.engine_client.clear_file_checkpoints.assert_not_called()

    @pytest.mark.parametrize("backend", ["git", "none", "auto"])
    def test_non_file_backend_is_the_old_error(self, backend):
        ctx = _context(backend=backend)
        result = _checkpoint_clear(ctx, None)
        assert isinstance(result, ErrorResult)
        assert result.message == "Clear only applies to file-based checkpoints"
        assert result.side_effects == []

    def test_non_file_backend_rejects_yes_too(self):
        """The flag must not become a way around the backend check."""
        ctx = _context(backend="git")
        result = _checkpoint_clear(ctx, "--yes")
        assert isinstance(result, ErrorResult)
        ctx.engine_client.clear_file_checkpoints.assert_not_called()


# ---------------------------------------------------------------------------
# Through the real subcommand parser, the way a client reaches it
# ---------------------------------------------------------------------------

class TestThroughHandleCheckpoint:
    def test_clear_asks(self):
        ctx = _context()
        result = handle_checkpoint(ctx, "clear")
        ctx.engine_client.clear_file_checkpoints.assert_not_called()
        assert _quick_pick(result)

    def test_the_resume_line_a_client_sends_deletes(self):
        """End-to-end shape: the picker's value is `clear --yes`, and a
        client re-dispatches `/checkpoint clear --yes`, whose args reach
        `handle_checkpoint` as the string `"clear --yes"`."""
        ctx = _context(removed=2)
        value = _quick_pick(handle_checkpoint(ctx, "clear")).payload["items"][1]["value"]
        assert value == "clear --yes"
        result = handle_checkpoint(ctx, value)
        ctx.engine_client.clear_file_checkpoints.assert_called_once_with(keep_last=0)
        assert "2" in result.message

    def test_the_cancel_value_deletes_nothing(self):
        ctx = _context()
        value = _quick_pick(handle_checkpoint(ctx, "clear")).payload["items"][0]["value"]
        assert value == "clear --no"
        result = handle_checkpoint(ctx, value)
        ctx.engine_client.clear_file_checkpoints.assert_not_called()
        assert "Cancelled" in result.message

    def test_the_usage_string_mentions_the_flag(self):
        """A user who saw the picker once should be able to skip it."""
        spec = CommandFactory.get("checkpoint")
        assert "--yes" in spec.usage

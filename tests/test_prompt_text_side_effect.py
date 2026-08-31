"""Tests for the v1.18.3 `prompt_text` SideEffectKind.

Closes TODO-v1.18.2-prompt-text-kind.md. Validates:
1. SideEffectKind constant exists and is in the v1 taxonomy
2. validate_agent_task emits the side-effect with the right shape
3. The notification message remains as a fallback for clients that
   don't honor the kind (open-enum invariant — TUI rendering)
"""

from __future__ import annotations

import re
from pathlib import Path

from ppxai.commands.agent import validate_agent_task
from ppxai.commands.results import (
    NotificationResult,
    ResultStatus,
    SideEffectKind,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestPromptTextConstant:
    def test_constant_exposed(self):
        assert SideEffectKind.PROMPT_TEXT == "prompt_text"

    def test_in_all_kinds(self):
        assert "prompt_text" in SideEffectKind.all_kinds()


class TestValidateAgentTaskEmitsPromptText:
    """validate_agent_task must emit a prompt_text side-effect on
    rejection so web/VSCode can auto-resume the elaboration. The
    NotificationResult message stays as the user-visible nudge for
    TUI clients that don't honor the kind."""

    def test_short_task_returns_notification_with_side_effect(self):
        result = validate_agent_task("fix", min_words=3)
        assert isinstance(result, NotificationResult)
        assert result.status == ResultStatus.WARNING
        assert "more detail" in result.message.lower()

        # Side-effect carries the resume contract.
        assert len(result.side_effects) == 1
        se = result.side_effects[0]
        assert se.kind == "prompt_text"
        assert se.payload["command_to_resume"] == "auto"
        assert se.payload["original_args"] == "fix"
        assert "question" in se.payload
        assert se.payload["question"]  # non-empty
        # placeholder is optional but we ship one
        assert se.payload.get("placeholder")

    def test_valid_task_returns_none(self):
        # Three-word task passes the threshold → no validation result.
        assert validate_agent_task("fix the parser", min_words=3) is None

    def test_empty_task_still_carries_resume_intent(self):
        """Even with empty original_args, the resume command is set."""
        result = validate_agent_task("", min_words=3)
        assert result is not None
        assert len(result.side_effects) == 1
        se = result.side_effects[0]
        assert se.payload["command_to_resume"] == "auto"
        assert se.payload["original_args"] == ""

    def test_metadata_unchanged_for_backward_compat(self):
        """Pre-v1.18.3 callers reading metadata still get the same shape."""
        result = validate_agent_task("fix", min_words=3)
        assert result.metadata["reason"] == "agent_task_too_vague"
        assert result.metadata["min_words"] == 3
        assert result.metadata["actual_words"] == 1
        assert result.metadata["task"] == "fix"


class TestPromptTextDocumented:
    """Sentinels: the kind must appear in the SideEffect docstring
    AND in both client renderers (web + VSCode). The cross-client
    parity test in tests/test_vscode_step5a_helpers.py also covers
    this from a different angle; this test pins the agent.py path
    so a refactor of the validator can't drop the side-effect."""

    def test_kind_in_sideeffect_docstring(self):
        from ppxai.commands.results import SideEffect
        assert '"prompt_text"' in (SideEffect.__doc__ or "")

    def test_kind_in_web_handler(self):
        src = (
            PROJECT_ROOT / "ppxai" / "web" / "shared" / "side-effects.js"
        ).read_text(encoding="utf-8")
        # Both the case key and a defining handler block.
        assert "prompt_text" in src
        assert "prompt_text(" in src or re.search(r"prompt_text\s*\(", src)

    def test_kind_in_vscode_handler(self):
        src = (
            PROJECT_ROOT / "vscode-extension" / "src" / "sideEffectsHandler.ts"
        ).read_text(encoding="utf-8")
        assert "PROMPT_TEXT: 'prompt_text'" in src
        assert "case KIND.PROMPT_TEXT" in src
        assert "showInputBox" in src

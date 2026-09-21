"""`/tools help` — the declared subcommand that only VSCode implemented.

ADR 0007 step 5 (2026-09-21). `help` has been a DECLARED subcommand on
the `/tools` CommandSpec since step 4, so completion offered it in all
four clients; `handle_tools` answered it with "Unknown subcommand" in
three of them. Only VSCode worked, because VSCode intercepted `/tools`
client-side and rendered a file-editing guide and a per-tool lookup from
its own copy of the text (`vscode-extension/src/handlers/commands.ts`).

Step 5 moved `/tools` to factory routing. Moving it with the handler as
it stood would have DELETED that guide from the product, so the text
moved to `ppxai/commands/tools.py` instead — which is also what makes the
declared subcommand true for Rich, Textual and web for the first time.

These tests are what stops it silently regressing to "Unknown
subcommand" again.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ppxai.commands.factory import CommandFactory
from ppxai.commands.results import (
    ErrorResult,
    KeyValueResult,
    MarkdownResult,
)
from ppxai.commands.tools import handle_tools


@pytest.fixture
def ctx():
    """A context whose engine exposes two tools, `/tools`-style."""
    context = MagicMock()
    context.get_tools_available.return_value = True
    context.engine_client.tools_enabled = True
    context.engine_client.tool_manager.list_tools.return_value = [
        {"name": "read_file", "description": "Read a file from disk",
         "source": "engine"},
        {"name": "apply_patch", "description": "Apply a unified diff",
         "source": "engine"},
    ]
    return context


class TestToolsHelpIsAnswered:
    def test_help_is_a_declared_subcommand(self):
        """The declaration is what completion serves; if it says `help`,
        the handler has to mean it."""
        spec = CommandFactory.get("tools")
        assert spec is not None
        declared = {name for name, _desc in (spec.subcommands or [])}
        assert "help" in declared

    def test_bare_help_lists_the_two_shapes(self, ctx):
        result = handle_tools(ctx, "help")
        assert isinstance(result, KeyValueResult)
        blob = " ".join(result.pairs.keys())
        assert "editing" in blob and "<tool>" in blob

    def test_help_editing_returns_the_guide(self, ctx):
        result = handle_tools(ctx, "help editing")
        assert isinstance(result, MarkdownResult)
        assert "File Editing Tools" in result.content
        # The three things the guide exists to say.
        assert "consent" in result.content.lower()
        assert "apply_patch" in result.content
        assert "/tools enable" in result.content

    def test_help_names_one_tool(self, ctx):
        result = handle_tools(ctx, "help read_file")
        assert isinstance(result, MarkdownResult)
        assert "read_file" in result.content
        assert "Read a file from disk" in result.content

    def test_tool_lookup_is_case_insensitive(self, ctx):
        result = handle_tools(ctx, "help ReAd_FiLe")
        assert isinstance(result, MarkdownResult)
        assert "read_file" in result.content

    def test_unknown_tool_is_an_error_that_points_at_list(self, ctx):
        result = handle_tools(ctx, "help no_such_tool")
        assert isinstance(result, ErrorResult)
        assert "no_such_tool" in result.message
        assert any("/tools list" in s for s in result.suggestions)

    def test_help_is_no_longer_an_unknown_subcommand(self, ctx):
        """The exact regression: `help` falling into the else branch."""
        result = handle_tools(ctx, "help")
        assert not (isinstance(result, ErrorResult)
                    and "Unknown subcommand" in result.message)

    def test_the_unknown_branch_still_fires_for_a_real_typo(self, ctx):
        """Guard on the guard — the else branch must still exist, and
        must now advertise `help`."""
        result = handle_tools(ctx, "halp")
        assert isinstance(result, ErrorResult)
        assert "Unknown subcommand: halp" in result.message
        assert any("help" in s for s in result.suggestions)


class TestRetiredSubcommandNameIsNotAdvertised:
    """ADR 0011 renamed `/tools agent` to `/tools auto` with no alias, so
    `handle_tools` has no `agent` branch — but three user-facing strings
    still told people to type it, and `tests/test_docs_consistency.py`'s
    retired-name scan only reads `docs/`, `scripts/` and `.claude/`."""

    def test_the_spec_usage_line_says_auto(self):
        spec = CommandFactory.get("tools")
        assert "auto" in spec.usage
        assert "agent" not in spec.usage

    def test_the_agent_mode_status_advises_a_command_that_exists(self, ctx):
        ctx.engine_client.agent_mode = False
        result = handle_tools(ctx, "auto")
        rendered = result.message + " ".join(getattr(result, "pairs", {}).values())
        assert "/tools agent" not in rendered

    def test_the_bad_action_error_advises_a_command_that_exists(self, ctx):
        result = handle_tools(ctx, "auto sideways")
        assert isinstance(result, ErrorResult)
        assert all("/tools agent" not in s for s in result.suggestions)

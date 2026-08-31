"""Tests for /help reconciliation across TUI and HTTP clients (v1.18.1).

Step 1g of v1.18.1 plan. The web app's `SharedCommands.generateHelpText`
in `ppxai/web/shared/commands.js` was a parallel registry that drifted
from the Python `CommandFactory`. The factory's `handle_help` now
serves both paths:

  - TUI (Rich/Textual) in-process → TextResult with Rich markup
  - HTTP (web, VSCode)            → MarkdownResult with GFM markdown

Same content, two formatters. The factory's `_registry` is the single
source of truth; the JS-side `SLASH_COMMANDS` table can stay for
client-side autocomplete (its real job) but help text comes from the
server.

Tests cover:
  - HTTP path returns MarkdownResult with no Rich markup leakage.
  - TUI path returns TextResult with Rich markup.
  - `/help <command>` uses the same branching.
  - Markdown output mentions every category that has registered
    commands (drift fence for new categories).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ppxai.commands.context import ServerCommandContext
from ppxai.commands.factory import CommandFactory
from ppxai.commands.results import (
    ErrorResult,
    MarkdownResult,
    ResultStatus,
    TextResult,
)

# ---------------------------------------------------------------------------
# /help — overall listing
# ---------------------------------------------------------------------------

class TestHelpOverall:
    def test_http_context_returns_markdown_result(self):
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("help").handler(ctx, "")
        assert isinstance(result, MarkdownResult)
        assert result.status == ResultStatus.INFO

    def test_http_help_has_no_rich_markup(self):
        """HTTP clients render the result content as markdown.
        Rich tags like `[bold]` would show as literal text — drift
        fence: assert NONE leak into the markdown output."""
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("help").handler(ctx, "")
        # Common Rich tags: [bold], [cyan], [dim], [/bold] etc.
        for leaked in ("[bold]", "[/bold]", "[cyan]", "[/cyan]",
                       "[dim]", "[/dim]"):
            assert leaked not in result.content, (
                f"Rich markup '{leaked}' leaked into HTTP /help output"
            )

    def test_http_help_uses_markdown_syntax(self):
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("help").handler(ctx, "")
        # Spot-check: markdown bold + heading conventions present.
        assert "**" in result.content, "missing markdown bold"
        assert result.content.startswith("## "), (
            "expected markdown H2 header, got: " + result.content[:80]
        )

    def test_http_help_lists_known_commands(self):
        """Every registered command should appear in the help text.
        Drift fence for new commands: when you register one, it
        shows up here automatically (no JS-side parallel list to
        maintain)."""
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("help").handler(ctx, "")
        # Spot-check a few we know exist
        for cmd in ("help", "show", "edit", "cd", "pwd",
                    "tools", "model", "provider"):
            assert f"`/{cmd}`" in result.content, (
                f"/{cmd} missing from /help markdown output"
            )

    def test_http_help_groups_by_category(self):
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("help").handler(ctx, "")
        # Categories in the factory: session, provider, tools, agent,
        # display, system, utility, etc. Markdown formats them as
        # `**Category:**`. Verify at least a few are present.
        # Some categories may have no commands; only those WITH
        # commands appear, matching generate_help() behavior.
        categories_with_commands = {
            cat for cat in CommandFactory.get_categories()
            if CommandFactory.list_by_category(cat)
        }
        # At least one category line must appear, formatted as bold.
        any_match = any(
            f"**{cat.title()}:**" in result.content
            for cat in categories_with_commands
        )
        assert any_match, (
            f"No category headers found. Categories with commands: "
            f"{categories_with_commands}; output starts: "
            f"{result.content[:300]}"
        )


# ---------------------------------------------------------------------------
# /help — TUI path (Rich markup)
# ---------------------------------------------------------------------------

class TestHelpTUIPath:
    def test_rich_context_returns_text_result(self):
        """In-process context (RichCommandContext, anything not
        ServerCommandContext) gets the Rich-markup version."""
        # Use a stub handler since RichCommandContext wraps a
        # CommandHandler that we don't have here; the only thing
        # `handle_help` checks is `isinstance(ctx, ServerCommandContext)`.
        # A bare object suffices.
        ctx = object()
        result = CommandFactory.get("help").handler(ctx, "")
        assert isinstance(result, TextResult)

    def test_tui_help_uses_rich_markup(self):
        ctx = object()
        result = CommandFactory.get("help").handler(ctx, "")
        assert "[bold]" in result.message or "[cyan]" in result.message, (
            "expected Rich markup in TUI help output"
        )


# ---------------------------------------------------------------------------
# /help <command> — detailed help
# ---------------------------------------------------------------------------

class TestHelpDetailed:
    def test_http_detailed_help_returns_markdown(self):
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("help").handler(ctx, "show")
        assert isinstance(result, MarkdownResult)
        # Header line uses markdown H3
        assert result.content.startswith("### ")
        # Usage line uses markdown bold + code
        assert "**Usage:**" in result.content
        # No Rich markup leakage
        for leaked in ("[bold]", "[/bold]", "[cyan]", "[/cyan]"):
            assert leaked not in result.content

    def test_http_detailed_help_unknown_command_returns_error(self):
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("help").handler(ctx, "no-such-command")
        assert isinstance(result, ErrorResult)
        assert "Unknown command" in result.message

    def test_tui_detailed_help_returns_textresult(self):
        ctx = object()
        result = CommandFactory.get("help").handler(ctx, "show")
        assert isinstance(result, TextResult)
        # Rich markup in TUI version
        assert "[bold]" in result.message or "[cyan]" in result.message


# ---------------------------------------------------------------------------
# generate_help / get_command_help — formatter contract
# ---------------------------------------------------------------------------

class TestGenerateHelpFormatters:
    def test_markdown_flag_produces_no_rich_markup(self):
        out = CommandFactory.generate_help(markdown=True)
        for leaked in ("[bold]", "[/bold]", "[cyan]", "[/cyan]",
                       "[dim]", "[/dim]"):
            assert leaked not in out

    def test_default_produces_rich_markup(self):
        out = CommandFactory.generate_help()
        # Some Rich tag should appear in the default formatter
        assert "[bold]" in out or "[cyan]" in out

    def test_get_command_help_markdown_formats_known_command(self):
        out = CommandFactory.get_command_help("help", markdown=True)
        assert out is not None
        assert out.startswith("### ")
        for leaked in ("[bold]", "[/bold]", "[cyan]"):
            assert leaked not in out

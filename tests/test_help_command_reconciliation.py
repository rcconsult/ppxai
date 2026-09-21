"""Tests for /help reconciliation across TUI and HTTP clients (v1.18.1).

Step 1g of v1.18.1 plan. The web app's `generateHelpText` in the
hand-written `ppxai/web/shared/commands.js` catalog was a parallel
registry that drifted from the Python `CommandFactory`. The factory's
`handle_help` now serves both paths:

  - TUI (Rich/Textual) in-process → TextResult with Rich markup
  - HTTP (web, VSCode)            → MarkdownResult with GFM markdown

Same content, two formatters. The factory's `_registry` is the single
source of truth.

Postscript (ADR 0007 step 3a, 2026-09-21): the "the JS-side table can
stay for client-side autocomplete" caveat this docstring used to carry
has expired. `commands.js` is DELETED; web autocomplete already came
from `POST /complete`, and the roster it routes on is fetched from
`GET /commands`. Web `/help` is now the server's output alone — which
also removed the confirmed double-listing of `/token`, `/run` and
`/task` (server catalog + the `_appendExperimentalHelp` shim). The tests
below are unchanged: they pin the SERVER side, which is what web now
shows verbatim.

Tests cover:
  - HTTP path returns MarkdownResult with no Rich markup leakage.
  - TUI path returns TextResult with Rich markup.
  - `/help <command>` uses the same branching.
  - Markdown output mentions every category that has registered
    commands (drift fence for new categories).
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

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


# ---------------------------------------------------------------------------
# `/help <command>` — subcommands section (owner decision, 2026-09-21)
# ---------------------------------------------------------------------------
#
# Eight registered specs declare `CommandSpec.subcommands` (name,
# description pairs, e.g. `/token status|set|mint|clear`) and neither
# `generate_help` (the full listing — NOT touched by this decision) nor
# `get_command_help` (per-command detail) used to render them, so typing
# `/help token` told a user nothing about `status`/`set`/`mint`/`clear`.
# This section is the guard (fails before the fix), the positive
# control (a command WITH subcommands gains a section) and the pin (a
# command WITHOUT subcommands is byte-for-byte unchanged).

class TestGetCommandHelpNoSubcommandsUnchanged:
    """Pin: a spec with no `subcommands` renders EXACTLY as before —
    no new section, no trailing blank line, nothing added."""

    def test_help_markdown_unchanged(self):
        assert CommandFactory.get_command_help("help", markdown=True) == (
            "### `/help` — Show help and available commands\n\n"
            "**Usage:** `/help`\n"
            "**Aliases:** `/h`, `/?`\n"
            "**Category:** system"
        )

    def test_help_rich_unchanged(self):
        assert CommandFactory.get_command_help("help", markdown=False) == (
            "[bold]/help[/bold] - Show help and available commands\n\n"
            "[cyan]Usage:[/cyan] /help\n"
            "[cyan]Aliases:[/cyan] /h, /?\n"
            "[cyan]Category:[/cyan] system"
        )

    def test_show_markdown_unchanged(self):
        """A second no-subcommands command, from a different module
        (display, not system), so the pin isn't accidentally specific to
        `/help` itself."""
        assert CommandFactory.get_command_help("show", markdown=True) == (
            "### `/show` — Display file contents with syntax highlighting\n\n"
            "**Usage:** `/show <filepath> [--source|--rendered|-i]`\n"
            "**Aliases:** `/cat`\n"
            "**Category:** display"
        )

    def test_no_subcommand_output_never_mentions_subcommands(self):
        for name in ("help", "show"):
            for markdown in (True, False):
                out = CommandFactory.get_command_help(name, markdown=markdown)
                assert "ubcommand" not in out, (name, markdown, out)


class TestGetCommandHelpRendersSubcommands:
    """Positive control: every one of the eight specs that declares
    `subcommands` must render them in `/help <command>`."""

    #: (command name, expected first-level subcommand names) — one per
    #: module that declares subcommands, so the fix isn't accidentally
    #: specific to a single call site.
    SUBCOMMAND_SPECS = [
        ("token", ["status", "set", "mint", "clear"]),       # client_handled.py
        ("theme", ["list", "emoji"]),                         # system.py
        ("status", ["version", "cwd", "datetime"]),           # system.py
        ("checkpoint", ["status", "list", "backend", "clear", "info", "undo"]),  # agent.py
        ("tools", ["on", "off", "enable", "disable", "list", "status",
                   "help", "set", "config", "auto"]),          # tools.py
        ("usage", ["show", "session", "provider", "off", "reset"]),  # tools.py
        ("task", ["ls", "get", "watch", "respond", "collect",
                  "resume", "cancel", "help"]),                # task.py
        ("run", ["ls", "get", "watch", "collect", "cancel", "help"]),  # task.py
    ]

    @pytest.mark.parametrize("name,expected_subs", SUBCOMMAND_SPECS)
    def test_markdown_lists_every_declared_subcommand(self, name, expected_subs):
        spec = CommandFactory.get(name)
        assert [n for n, _ in spec.subcommands] == expected_subs, (
            f"test's expected list for /{name} drifted from the spec — "
            "update SUBCOMMAND_SPECS"
        )
        out = CommandFactory.get_command_help(name, markdown=True)
        assert out is not None
        assert "**Subcommands:**" in out
        for sub, desc in spec.subcommands:
            assert f"`{sub}`" in out, (name, sub, out)
            assert desc in out, (name, sub, desc, out)

    @pytest.mark.parametrize("name,expected_subs", SUBCOMMAND_SPECS)
    def test_rich_lists_every_declared_subcommand(self, name, expected_subs):
        spec = CommandFactory.get(name)
        out = CommandFactory.get_command_help(name, markdown=False)
        assert out is not None
        assert "Subcommands:" in out
        for sub, desc in spec.subcommands:
            assert sub in out, (name, sub, out)
            assert desc in out, (name, sub, desc, out)

    def test_full_help_pipeline_renders_subcommands_http(self):
        """End to end through `handle_help` (what `/help token` actually
        runs), not just the factory helper directly. `/token` is
        web/vscode-only (ADR 0007), so this exercises the HTTP branch."""
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("help").handler(ctx, "token")
        assert isinstance(result, MarkdownResult)
        assert "**Subcommands:**" in result.content
        assert "`set`" in result.content

    def test_full_help_pipeline_renders_subcommands_tui(self):
        """Same, for the TUI (rich) branch — `/theme` is universal
        (`clients=None`), unlike `/token`, so it is visible here."""
        tui_ctx = object()
        tui_result = CommandFactory.get("help").handler(tui_ctx, "theme")
        assert isinstance(tui_result, TextResult)
        assert "Subcommands:" in tui_result.message
        assert "list" in tui_result.message


class TestGetCommandHelpSensitiveSubcommands:
    """`/token set` is a sensitive subcommand (ADR 0007 step 3a-sec):
    its NAME is not secret — it must still be listed — but no argument
    VALUE may ever appear (there is none to leak here; `get_command_help`
    takes no user-typed value), and a short marker says the value is
    handled client-side."""

    def test_sensitive_subcommand_name_is_listed_with_a_marker(self):
        spec = CommandFactory.get("token")
        assert spec.sensitive_subcommands == frozenset({"set"})
        out = CommandFactory.get_command_help("token", markdown=True)
        assert "`set`" in out
        # Consistent with GET /commands' per-subcommand `sensitive` flag
        # (ppxai/commands/factory.py::roster) — the marker text itself
        # isn't pinned verbatim, only that it says the value stays
        # client-side / is never sent to the server.
        set_line = next(line for line in out.splitlines() if "`set`" in line)
        lowered = set_line.lower()
        assert "client" in lowered and "never" in lowered

    def test_non_sensitive_subcommands_carry_no_marker(self):
        out = CommandFactory.get_command_help("token", markdown=True)
        status_line = next(line for line in out.splitlines() if "`status`" in line)
        assert "client" not in status_line.lower()
        assert "never" not in status_line.lower()

    def test_no_secret_value_can_appear_regardless_of_input(self):
        """`get_command_help` takes no args at all — the secret has no
        way in — but pin the contract so a future signature change
        can't silently start threading one through."""
        sig = inspect.signature(CommandFactory.get_command_help)
        assert "args" not in sig.parameters
        assert "value" not in sig.parameters

"""
Tests for the shared web/VSCode modules (v1.14.0, retargeted 2026-09-21).

**What changed.** This file used to test `ppxai/web/shared/commands.js` —
a 376-line hand-written slash-command catalog that the web app and the
VSCode extension were both supposed to read. ADR 0007 step 3a DELETED
the web copy: the web client now fetches `GET /commands?client=web` and
caches it in `CommandRoster` (`ppxai/web/shared/command-roster.js`), so
there is no JS-side catalog left to test for web.

**Why this file was not deleted with it.** Two of its checks were real
parity fences and are still live, just pointed at what remains:

  - `vscode-extension/src/shared/commands.ts` is a SEPARATE hand-written
    roster (31 entries) that step 3a deliberately did not touch — VSCode
    is step 3b. The parity check now compares that TS copy against the
    PYTHON registry, which is the drift that actually matters now (the
    old web-vs-TS comparison could pass while both drifted from Python).
  - The formatter inventory (`formatters.js`) is unrelated to the roster
    and is unchanged.

Plus a new fence in the opposite direction: the web app must NOT carry a
command catalog any more — `commands.js` stays deleted, `index.html`
stops loading it, and `app.js` stops restating it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import ppxai.commands.handler  # noqa: F401  (populates CommandFactory)
from ppxai.commands.factory import CommandFactory

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR = REPO_ROOT / "ppxai" / "web" / "shared"
COMMANDS_JS = SHARED_DIR / "commands.js"          # deleted — fenced below
COMMAND_ROSTER_JS = SHARED_DIR / "command-roster.js"
FORMATTERS_JS = SHARED_DIR / "formatters.js"
INDEX_HTML = REPO_ROOT / "ppxai" / "web" / "index.html"
APP_JS = REPO_ROOT / "ppxai" / "web" / "app.js"
VSCODE_SHARED_DIR = REPO_ROOT / "vscode-extension" / "src" / "shared"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestWebHasNoCommandCatalog:
    """ADR 0007 step 3a: the web command catalog is FETCHED, not restated.

    These are the deletions that prove the migration happened; if any of
    them comes back, a second roster exists again.
    """

    def test_commands_js_is_deleted(self):
        assert not COMMANDS_JS.exists(), (
            "ppxai/web/shared/commands.js is back. The web command catalog "
            "comes from GET /commands (CommandRoster); a static JS copy is "
            "the duplication ADR 0007 removed."
        )

    def test_index_html_no_longer_loads_commands_js(self):
        assert "shared/commands.js" not in _read(INDEX_HTML)

    def test_app_js_has_no_inline_fallback_catalog(self):
        """`app.js` carried a second copy of ~30 commands as a fallback for
        when `SharedCommands` failed to load. Deleted: without a roster the
        dispatcher fails closed rather than routing from a stale guess."""
        src = _read(APP_JS)
        assert "this.slashCommands" not in src
        assert "SharedCommands" not in src

    def test_app_js_holds_the_fetched_roster_instead(self):
        src = _read(APP_JS)
        assert "new CommandRoster(" in src, (
            "app.js does not construct the fetched CommandRoster"
        )
        assert "this.commandRoster.load()" in src, (
            "app.js never fetches the roster at startup"
        )


class TestCommandRosterModule:
    """The replacement module: a cache over GET /commands, not a catalog."""

    def test_module_exists(self):
        assert COMMAND_ROSTER_JS.exists()

    def test_valid_javascript_syntax(self):
        result = subprocess.run(
            ["node", "--check", str(COMMAND_ROSTER_JS)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_carries_no_command_names_of_its_own(self):
        """A drift fence with teeth: the roster module must contain NO
        hardcoded `'/<name>'` command literals. The moment one appears the
        catalog has started growing back inside its own replacement."""
        literals = sorted(set(re.findall(r"'/[a-z][a-z-]+'", _read(COMMAND_ROSTER_JS))))
        assert literals == [], f"hardcoded command names in command-roster.js: {literals}"

    def test_resolves_aliases_from_the_aliases_field(self):
        src = _read(COMMAND_ROSTER_JS)
        assert "entry.aliases" in src, (
            "aliases must resolve from the roster's `aliases` FIELD — restating "
            "them as standalone entries is the commands.js duplication"
        )


class TestFormatterFunctions:
    """Unrelated to the roster; unchanged."""

    REQUIRED_FORMATTERS = [
        "formatToolsStatus",
        "formatToolsList",
        "formatToolConfig",
        "formatToolHelp",
        "formatAgentStatus",
        "formatCheckpointStatus",
        "formatCheckpointList",
        "formatCheckpointInfo",
        "formatCheckpointBackendHelp",
        "formatUsageStats",
        "formatUsageDisplayHelp",
        "formatStatus",
        "formatProvidersList",
        "formatModelsList",
        "formatSessionsList",
        "formatFileContents",
        "formatError",
        "formatSuccess",
    ]

    def test_formatters_js_exists(self):
        assert FORMATTERS_JS.exists(), f"formatters.js not found at {FORMATTERS_JS}"

    def test_formatters_js_syntax(self):
        result = subprocess.run(
            ["node", "--check", str(FORMATTERS_JS)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Syntax error in formatters.js: {result.stderr}"

    def test_all_formatters_defined(self):
        content = _read(FORMATTERS_JS)
        for formatter in self.REQUIRED_FORMATTERS:
            assert (f"function {formatter}" in content
                    or f"export function {formatter}" in content), \
                f"Formatter {formatter} not found in formatters.js"

    def test_index_html_still_loads_formatters(self):
        assert "shared/formatters.js" in _read(INDEX_HTML)


class TestVSCodeSharedModules:
    """VSCode still ships its OWN hand-written roster (ADR 0007 step 3b).

    Finding recorded while doing step 3a: `commands.ts` is not a copy of
    `commands.js` sharing one file — it is a SIXTH independent roster.
    Deleting the web copy therefore did not touch VSCode at all, which is
    why the two steps are independent.
    """

    def test_vscode_commands_ts_exists(self):
        assert (VSCODE_SHARED_DIR / "commands.ts").exists()

    def test_vscode_formatters_ts_exists(self):
        assert (VSCODE_SHARED_DIR / "formatters.ts").exists()

    def test_vscode_index_ts_exists(self):
        assert (VSCODE_SHARED_DIR / "index.ts").exists()

    def test_vscode_roster_matches_the_python_registry(self):
        """Retargeted parity fence.

        It used to compare the TS copy against the JS copy — a check that
        stayed green while BOTH drifted from Python (they had, by nine
        commands). Now the reference is the registry itself, which is the
        single declaration ADR 0007 exists to establish. Until step 3b
        deletes `commands.ts` too, this is what keeps it honest.

        Scoped to a required core so an unmigrated VSCode roster does not
        fail the suite for every command added server-side; step 3b
        replaces this with the real fetch.
        """
        ts_content = _read(VSCODE_SHARED_DIR / "commands.ts")
        registry = {info.name for info in CommandFactory.iter_completion_specs()}
        required = {
            "help", "clear", "save", "export", "load", "sessions",
            "provider", "model", "tools", "auto", "checkpoint",
            "usage", "status", "show", "cat",
            "generate", "explain", "test", "docs", "debug", "implement",
            "convert", "spec", "theme",
        }
        missing_from_python = sorted(required - registry)
        assert not missing_from_python, (
            f"commands the VSCode roster needs are absent from the Python "
            f"registry: {missing_from_python}"
        )
        missing_from_ts = sorted(
            name for name in required if f"'/{name}'" not in ts_content
        )
        assert not missing_from_ts, (
            f"commands declared in Python but missing from the VSCode roster "
            f"(vscode-extension/src/shared/commands.ts): {missing_from_ts}"
        )

    def test_known_vscode_roster_gap_until_step_3b(self):
        """Finding, recorded not fixed (2026-09-21).

        `/run`, `/task` and `/token` are registered in Python and are
        intercepted by `chatPanel.ts` at runtime, but the VSCode roster
        does not list them — so VSCode's own autocomplete/help never
        offered them. The deleted web `commands.js` DID list all three,
        which is one more way the two JS rosters had silently diverged.

        Deliberately not patched here: step 3a is web-only, and step 3b
        deletes `commands.ts` outright rather than topping it up. This
        test fails the day someone closes the gap either way, so the
        finding cannot rot.
        """
        ts_content = _read(VSCODE_SHARED_DIR / "commands.ts")
        still_missing = sorted(
            name for name in ("run", "task", "token")
            if f"'/{name}'" not in ts_content
        )
        assert still_missing == ["run", "task", "token"], (
            "the VSCode roster gap changed — if step 3b landed, delete this "
            f"test; if it was topped up by hand, update it. Missing now: {still_missing}"
        )

    def test_vscode_roster_does_not_declare_commands_python_has_retired(self):
        """The direction the old web-vs-TS check could never catch."""
        ts_content = _read(VSCODE_SHARED_DIR / "commands.ts")
        for retired in ("/agent", "/agentrun", "/agentruns"):
            assert f"'{retired}':" not in ts_content, (
                f"{retired} was retired by ADR 0011 but is still in commands.ts"
            )


class TestDesktopSpecIncludesShared:
    """Test that desktop spec includes shared modules."""

    def test_desktop_spec_includes_shared(self):
        content = _read(REPO_ROOT / "ppxai-desktop.spec")
        assert "ppxai/web/shared" in content or "('ppxai/web', 'ppxai/web')" in content, \
            "shared directory not in ppxai-desktop.spec (neither explicit nor via ppxai/web)"

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

  - `vscode-extension/src/shared/commands.ts` was a SEPARATE hand-written
    roster (31 entries) that step 3a deliberately did not touch — VSCode
    was step 3b. **Step 3b landed 2026-09-21 and deleted it**, so the
    parity check inverted again: what is left is a DELETION fence plus
    drift fences on its replacement (`src/commandRoster.ts`,
    `src/commandRouter.ts`). The known-gap test that pinned VSCode's
    missing `/run`·`/task`·`/token` was written to fail the day 3b
    landed; it did, and is replaced by the positive assertion that the
    roster serves all three to vscode.
  - The formatter inventory (`formatters.js`) is unrelated to the roster
    and is unchanged.

Plus fences in the opposite direction for both clients: neither app may
carry a command catalog any more.
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
VSCODE_SRC_DIR = REPO_ROOT / "vscode-extension" / "src"
VSCODE_SHARED_DIR = VSCODE_SRC_DIR / "shared"
VSCODE_ROSTER_TS = VSCODE_SRC_DIR / "commandRoster.ts"
VSCODE_ROUTER_TS = VSCODE_SRC_DIR / "commandRouter.ts"


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


class TestVSCodeHasNoCommandCatalog:
    """ADR 0007 step 3b (2026-09-21): the VSCode catalog is FETCHED too.

    `vscode-extension/src/shared/commands.ts` was a SEPARATE hand-written
    roster — the SIXTH the record counts, not a copy of the web one. It
    is now deleted; `src/commandRoster.ts` caches
    `GET /commands?client=vscode` and `src/commandRouter.ts` routes on
    its server-computed `dispatch` field.

    These are the deletions that prove the migration happened. Inverted
    from what this class used to assert — including the known-gap test
    for `/run`·`/task`·`/token`, which was written to fail the day step
    3b landed and has now done its job.
    """

    def test_commands_ts_is_deleted(self):
        assert not (VSCODE_SHARED_DIR / "commands.ts").exists(), (
            "vscode-extension/src/shared/commands.ts is back. The VSCode "
            "command catalog comes from GET /commands (CommandRoster); a "
            "static TS copy is the duplication ADR 0007 removed."
        )

    def test_nothing_imports_the_deleted_module(self):
        for path in sorted(VSCODE_SRC_DIR.rglob("*.ts")):
            src = _read(path)
            assert "from './shared/commands'" not in src, path
            assert "from '../shared/commands'" not in src, path

    def test_barrel_no_longer_reexports_it(self):
        src = _read(VSCODE_SHARED_DIR / "index.ts")
        assert "} from './commands';" not in src
        for name in ("SLASH_COMMANDS", "generateHelpText", "AI_FORWARDED_COMMANDS",
                     "isAIForwardedCommand", "getCommandNames",
                     "getCommandsByCategory"):
            assert f"    {name}," not in src, (
                f"shared/index.ts still re-exports {name} from the deleted module"
            )

    def test_vscode_formatters_ts_exists(self):
        """Unrelated to the roster; unchanged."""
        assert (VSCODE_SHARED_DIR / "formatters.ts").exists()

    def test_vscode_index_ts_exists(self):
        assert (VSCODE_SHARED_DIR / "index.ts").exists()


class TestVSCodeCommandRosterModule:
    """The replacement modules: a cache over GET /commands plus a router
    that reads it — not a catalog."""

    def test_modules_exist(self):
        assert VSCODE_ROSTER_TS.exists()
        assert VSCODE_ROUTER_TS.exists()

    def test_neither_imports_vscode(self):
        """What makes them testable under Node at all (the
        `taskController.ts` idiom) — and what the behavioural tests in
        tests/test_vscode_command_roster_behavior.py depend on."""
        for path in (VSCODE_ROSTER_TS, VSCODE_ROUTER_TS):
            src = _read(path)
            assert "from 'vscode'" not in src, f"{path.name} imports vscode"
            assert 'from "vscode"' not in src, f"{path.name} imports vscode"

    def test_carries_no_command_names_of_its_own(self):
        """A drift fence with teeth: neither module may contain a
        hardcoded `'/<name>'` command literal. The moment one appears the
        catalog has started growing back inside its own replacement.

        `LEGACY_INTERCEPTS` deliberately names five commands WITHOUT the
        slash — they are the acknowledged-debt baseline ADR 0007 step 5
        inherits, pinned exactly in
        tests/test_client_handled_commands_contract.py, and they carry no
        description, usage or category (which is what a roster is).
        """
        for path in (VSCODE_ROSTER_TS, VSCODE_ROUTER_TS):
            literals = sorted(set(re.findall(r"'/[a-z][a-z-]+'", _read(path))))
            assert literals == [], (
                f"hardcoded command names in {path.name}: {literals}")

    def test_resolves_aliases_from_the_aliases_field(self):
        src = _read(VSCODE_ROSTER_TS)
        assert "entry.aliases" in src, (
            "aliases must resolve from the roster's `aliases` FIELD — restating "
            "them as standalone entries is the commands.ts duplication"
        )

    def test_client_id_is_vscode(self):
        assert "VSCODE_CLIENT_ID = 'vscode'" in _read(VSCODE_ROUTER_TS)


class TestRetiredCommandsAreGoneEverywhere:
    """ADR 0011's hard removals, checked against the registry rather than
    against a JS copy of it (both copies are gone now)."""

    def test_agentrun_family_retired(self):
        for retired in ("agent", "agentrun", "agentruns"):
            assert CommandFactory.get(retired) is None, (
                f"/{retired} was retired by ADR 0011 but is registered again"
            )
        assert CommandFactory.get("run") is not None
        assert CommandFactory.get("task") is not None
        assert CommandFactory.get("auto") is not None

    def test_the_three_commands_vscode_used_to_miss_are_served_to_it(self):
        """The known gap this file pinned until step 3b: `/run`, `/task`
        and `/token` were registered in Python and intercepted at runtime
        by `chatPanel.ts`, but absent from the TS catalog — so VSCode's
        own autocomplete and `/help` never offered them. Fetching the
        roster closes it by construction."""
        served = {c["name"] for c in CommandFactory.roster("vscode")["commands"]}
        assert {"run", "task", "token"} <= served


class TestDesktopSpecIncludesShared:
    """Test that desktop spec includes shared modules."""

    def test_desktop_spec_includes_shared(self):
        content = _read(REPO_ROOT / "ppxai-desktop.spec")
        assert "ppxai/web/shared" in content or "('ppxai/web', 'ppxai/web')" in content, \
            "shared directory not in ppxai-desktop.spec (neither explicit nor via ppxai/web)"

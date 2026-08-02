"""
Tests for shared command definitions module (v1.14.0).

These tests verify the shared commands.js module functionality
that's used by both the Web App and VSCode extension.
"""

import pytest
import subprocess
import json
from pathlib import Path


# Path to the shared commands module
SHARED_DIR = Path(__file__).parent.parent / "ppxai" / "web" / "shared"
COMMANDS_JS = SHARED_DIR / "commands.js"
FORMATTERS_JS = SHARED_DIR / "formatters.js"


class TestSharedCommandsModule:
    """Test the shared commands.js module."""

    def test_commands_js_exists(self):
        """Test that commands.js exists."""
        assert COMMANDS_JS.exists(), f"commands.js not found at {COMMANDS_JS}"

    def test_commands_js_syntax(self):
        """Test that commands.js has valid JavaScript syntax."""
        result = subprocess.run(
            ["node", "--check", str(COMMANDS_JS)],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Syntax error in commands.js: {result.stderr}"

    def test_formatters_js_exists(self):
        """Test that formatters.js exists."""
        assert FORMATTERS_JS.exists(), f"formatters.js not found at {FORMATTERS_JS}"

    def test_formatters_js_syntax(self):
        """Test that formatters.js has valid JavaScript syntax."""
        result = subprocess.run(
            ["node", "--check", str(FORMATTERS_JS)],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Syntax error in formatters.js: {result.stderr}"


class TestCommandDefinitions:
    """Test command definitions are complete and correct."""

    # Expected commands that must exist
    REQUIRED_COMMANDS = [
        "/help", "/clear", "/save", "/export", "/load", "/sessions",
        "/provider", "/model",
        "/tools", "/auto",
        "/checkpoint",
        "/usage", "/status",
        "/show", "/cat",
        "/generate", "/explain", "/test", "/docs", "/debug", "/implement", "/convert", "/spec",
        "/theme"
    ]

    # Commands with subcommands
    COMMANDS_WITH_SUBCOMMANDS = {
        "/tools": ["enable", "disable", "status", "list", "config", "set", "auto", "help"],
        "/checkpoint": ["status", "list", "undo", "backend", "clear", "info"],
        "/usage": ["24h", "week", "month", "year", "all", "show", "reset"],
        "/auto": ["on", "off"],
    }

    def test_required_commands_in_js(self):
        """Test that all required commands are defined in commands.js."""
        content = COMMANDS_JS.read_text(encoding="utf-8")
        for cmd in self.REQUIRED_COMMANDS:
            assert f"'{cmd}'" in content or f'"{cmd}"' in content, \
                f"Command {cmd} not found in commands.js"

    def test_subcommands_in_js(self):
        """Test that commands with subcommands have them listed."""
        content = COMMANDS_JS.read_text(encoding="utf-8")
        for cmd, subcommands in self.COMMANDS_WITH_SUBCOMMANDS.items():
            for subcmd in subcommands:
                # Check if subcommand appears in the file (in subcommands array or usage string)
                assert subcmd in content, \
                    f"Subcommand '{subcmd}' for {cmd} not found in commands.js"

    def test_command_categories_exist(self):
        """Test that command categories are defined."""
        content = COMMANDS_JS.read_text(encoding="utf-8")
        expected_categories = [
            "SESSION", "PROVIDER", "TOOLS", "CHECKPOINT", "USAGE", "FILE", "CODING", "OTHER"
        ]
        for cat in expected_categories:
            assert cat in content, f"Category {cat} not found in commands.js"

    def test_ai_forwarded_commands_defined(self):
        """Test that AI-forwarded commands list is defined."""
        content = COMMANDS_JS.read_text(encoding="utf-8")
        assert "AI_FORWARDED_COMMANDS" in content
        # These commands should be in the AI forwarded list
        for cmd in ["/generate", "/explain", "/test", "/docs", "/debug", "/implement", "/convert", "/spec"]:
            assert cmd in content


class TestFormatterFunctions:
    """Test formatter function definitions."""

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

    def test_all_formatters_defined(self):
        """Test that all required formatter functions are defined."""
        content = FORMATTERS_JS.read_text(encoding="utf-8")
        for formatter in self.REQUIRED_FORMATTERS:
            assert f"function {formatter}" in content or f"export function {formatter}" in content, \
                f"Formatter {formatter} not found in formatters.js"


class TestVSCodeSharedModules:
    """Test that VSCode extension has matching shared modules."""

    VSCODE_SHARED_DIR = Path(__file__).parent.parent / "vscode-extension" / "src" / "shared"

    def test_vscode_commands_ts_exists(self):
        """Test that VSCode commands.ts exists."""
        commands_ts = self.VSCODE_SHARED_DIR / "commands.ts"
        assert commands_ts.exists(), f"commands.ts not found at {commands_ts}"

    def test_vscode_formatters_ts_exists(self):
        """Test that VSCode formatters.ts exists."""
        formatters_ts = self.VSCODE_SHARED_DIR / "formatters.ts"
        assert formatters_ts.exists(), f"formatters.ts not found at {formatters_ts}"

    def test_vscode_index_ts_exists(self):
        """Test that VSCode index.ts exists."""
        index_ts = self.VSCODE_SHARED_DIR / "index.ts"
        assert index_ts.exists(), f"index.ts not found at {index_ts}"

    def test_command_parity(self):
        """Test that Web App and VSCode have the same commands."""
        web_content = COMMANDS_JS.read_text(encoding="utf-8")
        ts_content = (self.VSCODE_SHARED_DIR / "commands.ts").read_text(encoding="utf-8")

        # Extract command names from both files (simplified check)
        for cmd in TestCommandDefinitions.REQUIRED_COMMANDS:
            assert cmd in web_content, f"Command {cmd} missing from commands.js"
            assert cmd in ts_content, f"Command {cmd} missing from commands.ts"


class TestWebAppIntegration:
    """Test that Web App properly integrates shared modules."""

    def test_index_html_loads_shared_modules(self):
        """Test that index.html loads the shared modules."""
        index_html = Path(__file__).parent.parent / "ppxai" / "web" / "index.html"
        content = index_html.read_text(encoding='utf-8')

        assert "shared/commands.js" in content, "commands.js not loaded in index.html"
        assert "shared/formatters.js" in content, "formatters.js not loaded in index.html"

    def test_app_js_uses_shared_commands(self):
        """Test that app.js references SharedCommands."""
        app_js = Path(__file__).parent.parent / "ppxai" / "web" / "app.js"
        content = app_js.read_text(encoding='utf-8')

        assert "SharedCommands" in content, "SharedCommands not referenced in app.js"


class TestDesktopSpecIncludesShared:
    """Test that desktop spec includes shared modules."""

    def test_desktop_spec_includes_shared(self):
        """Test that ppxai-desktop.spec includes shared directory."""
        spec_file = Path(__file__).parent.parent / "ppxai-desktop.spec"
        content = spec_file.read_text(encoding="utf-8")

        # Check that shared is included (either explicitly or via parent directory)
        assert "ppxai/web/shared" in content or "('ppxai/web', 'ppxai/web')" in content, \
            "shared directory not in ppxai-desktop.spec (neither explicit nor via ppxai/web)"

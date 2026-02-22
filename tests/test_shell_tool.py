"""Tests for ShellExecuteTool — compound commands, cd handling, interactive guards."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ppxai.engine.tools.builtin.shell import ShellExecuteTool


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.get_working_dir.return_value = os.getcwd()
    engine.request_shell_consent = AsyncMock(return_value=True)
    return engine


@pytest.fixture
def shell_tool(mock_engine):
    return ShellExecuteTool(mock_engine)


class TestCompoundCommands:
    """Shell operators (&&, ||, ;, |) should bypass cd/interactive handlers."""

    @pytest.mark.asyncio
    async def test_cd_with_and_operator_runs_as_shell(self, shell_tool):
        """cd /path && command should NOT trigger cd handler (was bug: 'Directory not found')."""
        result = await shell_tool.execute("cd /tmp && pwd")
        # Should succeed — subprocess.run(shell=True) handles cd && pwd
        assert "Directory not found" not in result
        assert "/tmp" in result or "private/tmp" in result  # macOS /tmp → /private/tmp

    @pytest.mark.asyncio
    async def test_cd_without_operator_triggers_handler(self, shell_tool, mock_engine):
        """Plain cd /path should still use the cd handler."""
        result = await shell_tool.execute("cd /tmp")
        assert "Changed directory to" in result
        mock_engine.set_working_dir.assert_called_once()

    @pytest.mark.asyncio
    async def test_semicolon_compound_command(self, shell_tool):
        """Commands with ; should run via shell, not cd handler."""
        result = await shell_tool.execute("cd /tmp; pwd")
        assert "Directory not found" not in result

    @pytest.mark.asyncio
    async def test_pipe_compound_command(self, shell_tool):
        """Commands with | should run via shell."""
        result = await shell_tool.execute("echo hello | tr a-z A-Z")
        assert "HELLO" in result

    @pytest.mark.asyncio
    async def test_or_operator_compound_command(self, shell_tool):
        """Commands with || should run via shell."""
        result = await shell_tool.execute("false || echo fallback")
        assert "fallback" in result


class TestInteractiveGuard:
    """Interactive command detection with shell operator bypass."""

    @pytest.mark.asyncio
    async def test_bare_python_blocked(self, shell_tool):
        """Bare 'python3' (no args) should be blocked as interactive."""
        result = await shell_tool.execute("python3")
        assert "interactive command" in result.lower()

    @pytest.mark.asyncio
    async def test_python_with_args_allowed(self, shell_tool):
        """python3 -c 'print(1)' should run (has args)."""
        result = await shell_tool.execute("python3 -c 'print(42)'")
        assert "42" in result

    @pytest.mark.asyncio
    async def test_python_in_compound_not_blocked(self, shell_tool):
        """python3 in a compound command should not be blocked."""
        result = await shell_tool.execute("echo start && python3 -c 'print(99)'")
        assert "interactive" not in result.lower()
        assert "99" in result


class TestConsentDenied:
    """User consent denial should return error."""

    @pytest.mark.asyncio
    async def test_denied_consent(self, mock_engine):
        mock_engine.request_shell_consent = AsyncMock(return_value=False)
        tool = ShellExecuteTool(mock_engine)
        result = await tool.execute("ls")
        assert "denied" in result.lower()


class TestWorkingDir:
    """Working directory handling."""

    @pytest.mark.asyncio
    async def test_default_working_dir_from_engine(self, shell_tool, mock_engine):
        """When no working_dir passed, uses engine's working dir."""
        mock_engine.get_working_dir.return_value = "/tmp"
        result = await shell_tool.execute("pwd")
        assert "/tmp" in result or "private/tmp" in result

    @pytest.mark.asyncio
    async def test_nonexistent_working_dir(self, shell_tool):
        """Non-existent working_dir should return error."""
        result = await shell_tool.execute("ls", working_dir="/nonexistent/path/xyz")
        assert "does not exist" in result.lower()

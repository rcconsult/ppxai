"""Tests for ShellExecuteTool — compound commands, cd handling, interactive guards."""

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ppxai.engine.tools.builtin.shell import ShellExecuteTool, _is_backgrounded

# Windows cmd.exe doesn't support single quotes in arguments
_Q = '"' if sys.platform == 'win32' else "'"


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
        result = await shell_tool.execute(f"python3 -c {_Q}print(42){_Q}")
        assert "42" in result

    @pytest.mark.asyncio
    async def test_python_in_compound_not_blocked(self, shell_tool):
        """python3 in a compound command should not be blocked."""
        result = await shell_tool.execute(f"echo start && python3 -c {_Q}print(99){_Q}")
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


class TestBackgroundDetection:
    """`&`/`nohup` detection used to avoid pipe-EOF deadlock (v1.18.3 P3)."""

    def test_trailing_amp_detected(self):
        assert _is_backgrounded("python main.py &")
        assert _is_backgrounded("sleep 60 &")
        assert _is_backgrounded("cd /x && python main.py > log 2>&1 &")

    def test_amp_with_trailing_whitespace(self):
        assert _is_backgrounded("sleep 60 &   ")

    def test_logical_and_not_backgrounded(self):
        assert not _is_backgrounded("ls && pwd")
        assert not _is_backgrounded("a && b && c")

    def test_nohup_detected(self):
        assert _is_backgrounded("nohup python main.py")

    def test_plain_command_not_backgrounded(self):
        assert not _is_backgrounded("ls -la")
        assert not _is_backgrounded("echo hello")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX backgrounding semantics")
class TestBackgroundedCommandNoDeadlock:
    """Long-running backgrounded children must not block the tool call.

    Regression for the 2026-05-02 demo session where `python main.py > log 2>&1 &`
    held subprocess.run's captured pipes via inherited FDs for the full 300s
    timeout. Fixed by setting stdout/stderr/stdin = DEVNULL +
    start_new_session=True for backgrounded commands.
    """

    @pytest.mark.asyncio
    async def test_long_running_backgrounded_returns_quickly(self, shell_tool, tmp_path):
        # Use a python child that holds stdout/stderr open for 30s — would
        # have hung subprocess.run(capture_output=True) until timeout.
        log = tmp_path / "child.log"
        cmd = (
            f"python3 -c 'import time,sys; sys.stdout.write(\"alive\\n\"); "
            f"sys.stdout.flush(); time.sleep(30)' > {log} 2>&1 &"
        )
        start = time.monotonic()
        result = await shell_tool.execute(cmd)
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"backgrounded command took {elapsed:.2f}s (deadlock?)"
        assert "background" in result.lower()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal semantics")
class TestInterruptCancelsRunningProcess:
    """interrupt_stream() during a running tool must SIGTERM the subprocess
    so /interrupt is effective without waiting for the timeout."""

    @pytest.mark.asyncio
    async def test_interrupt_terminates_running_subprocess(self):
        """Real engine + real subprocess: simulate Esc during a 30s sleep."""
        from ppxai.engine.client import EngineClient

        # Stub providers/config — we only exercise subprocess registry +
        # interrupt_stream; no LLM call.
        with patch("ppxai.engine.client.create_provider"), \
             patch("ppxai.engine.client.get_api_key", return_value="stub"), \
             patch("ppxai.engine.client.get_base_url", return_value="http://stub"):
            engine = EngineClient.__new__(EngineClient)
            engine._interrupted = False
            engine._active_subprocesses = []
            from ppxai.engine.app_state import AppState
            engine.state = AppState()

        tool = ShellExecuteTool(engine)
        # Bypass consent for this test.
        engine.request_shell_consent = AsyncMock(return_value=True)
        engine.get_working_dir = MagicMock(return_value=os.getcwd())

        # Long-running foreground command — would normally run for 30s.
        with patch(
            "ppxai.engine.tools.builtin.shell._get_shell_config",
            return_value={"timeout": 30, "interactive_commands": [], "non_interactive_with_args": []},
        ):
            execute_task = asyncio.create_task(
                tool.execute("python3 -c 'import time; time.sleep(30)'")
            )

            # Wait for the subprocess to actually be registered.
            for _ in range(50):
                if engine._active_subprocesses:
                    break
                await asyncio.sleep(0.05)
            assert engine._active_subprocesses, "subprocess never registered"

            start = time.monotonic()
            engine.interrupt_stream()
            result = await execute_task
            elapsed = time.monotonic() - start

        assert elapsed < 5.0, f"interrupt didn't kill subprocess fast (elapsed={elapsed:.2f}s)"
        # After interrupt: process exited via SIGTERM; tool returns either
        # the (empty) captured output or a non-zero exit-code marker.
        # The key assertion is the elapsed-time bound above.
        assert engine._active_subprocesses == [], "subprocess not unregistered"

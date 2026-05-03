"""
Shell command execution tool with consent management (v1.11.2).

v1.13.6: Interactive command lists now configurable via JSON config.
v1.18.3 P3: async + cancellable. `subprocess.run` (blocking, sync) is
replaced with `asyncio.create_subprocess_shell`/`exec` so the event loop
keeps servicing POST /interrupt while a tool runs. The running process is
registered with the engine so `interrupt_stream()` can SIGTERM it.
Trailing-`&` (and `nohup`) commands now run with `start_new_session=True`
and stdout/stderr/stdin = DEVNULL so a backgrounded long-running child
(e.g. uvicorn) cannot hold the captured pipes open after the wrapper
subshell exits — that was the 5-minute deadlock observed in the demo
session of 2026-05-02.
"""

import asyncio
import os
import re
import platform
import signal
from typing import List

from ....config import get_shell_config
from ...types import ToolEngineProtocol, ToolManagerProtocol
from ..base import BaseTool


def terminate_subprocess_tree(proc) -> None:
    """SIGTERM a subprocess and its children when on POSIX, else fall back.

    Linux-specific bug we caught in CI on v1.18.3: when the shell tool spawns
    via `asyncio.create_subprocess_shell(..., start_new_session=True)`, the
    OS process tree is `/bin/sh -c "<command>"` → `<actual command>`. Calling
    `proc.terminate()` only sends SIGTERM to the shell wrapper. The child
    inherits the wrapper's stdout/stderr file descriptors, so even after the
    wrapper exits, those FDs remain open in the child until the child
    finishes — which means `proc.communicate()` waits for the child's
    natural timeout (the test's 30s sleep), not the SIGTERM-induced exit
    we wanted.

    The fix is to SIGTERM the entire process group via `os.killpg(pgid)`.
    Both the wrapper and the child are in the new session group, so the
    signal reaches the child too, the FDs close, and `communicate()`
    returns immediately. macOS happens to behave differently here
    (SIGTERM-to-leader nudges the orphan in some cases), which is why the
    test passed locally on darwin but failed on CI Linux.
    """
    if proc.returncode is not None:
        return  # already exited

    if hasattr(os, "killpg") and os.name != "nt":
        try:
            pgid = os.getpgid(proc.pid)
        except (ProcessLookupError, OSError):
            return
        try:
            os.killpg(pgid, signal.SIGTERM)
            return
        except (ProcessLookupError, OSError):
            pass

    # Windows or POSIX without killpg: SIGTERM the leader.
    try:
        proc.terminate()
    except (ProcessLookupError, OSError):
        pass


def kill_subprocess_tree(proc) -> None:
    """SIGKILL a subprocess and its children when on POSIX, else fall back."""
    if proc.returncode is not None:
        return

    if hasattr(os, "killpg") and os.name != "nt":
        try:
            pgid = os.getpgid(proc.pid)
        except (ProcessLookupError, OSError):
            return
        try:
            os.killpg(pgid, signal.SIGKILL)
            return
        except (ProcessLookupError, OSError):
            pass

    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass


# `&` at the end of the command, or anywhere followed by whitespace + EOL,
# means "background this". Avoids matching `&&` (logical AND) and `&` inside
# quoted strings is best-effort: a trailing-only check is correct for the
# common `cmd args > log 2>&1 &` pattern. Models that hand-build complex
# pipelines with mid-command `&` are responsible for their own redirection.
_TRAILING_AMP_RE = re.compile(r"(?:^|[^&])&\s*$")


def _is_backgrounded(command: str) -> bool:
    """Detect commands that detach a long-running child from the wrapper shell.

    Matches:
      - trailing `&` (POSIX async list terminator)
      - `nohup ...` prefix (caller intends to outlive the shell)

    Backgrounded commands need stdin/stdout/stderr = DEVNULL and a new
    session so the captured-output pipes from the parent don't keep the
    child's FDs alive. Without this, uvicorn-style servers deadlock the
    `await proc.communicate()` call until the configured timeout fires.
    """
    stripped = command.strip()
    if stripped.startswith("nohup "):
        return True
    return bool(_TRAILING_AMP_RE.search(stripped))


def _get_shell_config() -> dict:
    """Get full shell config from config file.

    Returns:
        Shell config dict with timeout, interactive_commands, etc.
    """
    try:
        return get_shell_config()
    except AttributeError:
        # Fallback defaults if config not available
        return {
            "timeout": 30,
            "shell_bin": None,       # e.g. "/bin/bash" or "/bin/zsh"; None = system default
            "login_shell": False,    # True = invoke with -l (sources profile, full PATH)
            "interactive_commands": [
                'nano', 'vim', 'vi', 'emacs', 'pico', 'joe',
                'less', 'more',
                'top', 'htop', 'btop',
                'python', 'python3', 'ipython', 'node', 'irb', 'ruby',
                'ssh', 'telnet', 'ftp', 'sftp',
                'mysql', 'psql', 'mongo', 'redis-cli',
                'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh',
            ],
            "non_interactive_with_args": [
                'python', 'python3', 'ipython', 'node', 'irb', 'ruby',
                'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh',
                'ssh', 'mysql', 'psql',
            ],
        }


def _get_interactive_commands() -> tuple[List[str], List[str]]:
    """Get interactive command lists from config.

    Returns:
        Tuple of (interactive_commands, non_interactive_with_args)
    """
    config = _get_shell_config()
    return (
        config.get("interactive_commands", []),
        config.get("non_interactive_with_args", [])
    )


class ShellExecuteTool(BaseTool):
    """Execute shell commands with user consent."""

    def __init__(self, engine: ToolEngineProtocol):
        """Initialize with engine reference for consent.

        Args:
            engine: Engine client instance
        """
        self.engine = engine
        self.name = "execute_shell_command"
        self.description = (
            "Execute a shell command in the system. Supports Windows (cmd/PowerShell) and Unix (bash) commands. "
            "Use for system operations like creating directories, running scripts, git commands, npm/pip installs, etc. "
            "Commands run with a configurable timeout (default 30 seconds, set 'tools.shell.timeout' in config). "
            "IMPORTANT: Do NOT use for file editing (sed, awk, perl, etc.) - use file editing tools instead (replace_block, insert_text, delete_lines, apply_patch). "
            "Do NOT use recursive commands like 'ls -R', 'find', 'tree' - they produce too much output. "
            "For file listing use list_directory. For file search use search_files. For reading files use read_file. "
            "WINDOWS NOTE: Bash-specific syntax like heredocs (<<EOF), $(), and bash builtins do NOT work on Windows. "
            "Use PowerShell or simple commands instead. To create files, use insert_text or apply_patch tools."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute (e.g., 'mkdir new_folder', 'git status', 'pwd'). AVOID recursive commands!"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory path where the command should be executed"
                }
            },
            "required": ["command"]
        }

    async def execute(self, command: str, working_dir: str = None, **kwargs) -> str:
        """Execute a shell command with consent checking.

        Args:
            command: The shell command to execute
            working_dir: Optional working directory for the command

        Returns:
            Command output (stdout + stderr) or error message
        """
        # Request consent for shell command execution (v1.11.2)
        # Use engine's working directory if not specified or empty (v1.15.2)
        # Model may pass working_dir='' which is falsy but not None
        if not working_dir:
            working_dir = self.engine.get_working_dir() or "."

        consent_approved = await self.engine.request_shell_consent(command, working_dir)
        if not consent_approved:
            return f"Error: User denied permission to execute command: {command}"

        try:
            # Get shell config including timeout (v1.15.2)
            shell_config = _get_shell_config()
            timeout = shell_config.get("timeout", 30)
            interactive_commands = shell_config.get("interactive_commands", [])
            non_interactive_with_args = shell_config.get("non_interactive_with_args", [])

            # Check for shell operators - if present, skip cd/interactive
            # handling and let subprocess.run(shell=True) handle natively
            shell_operators = ('&&', '||', ';', '|')
            has_shell_operators = any(op in command for op in shell_operators)

            # Extract the base command
            cmd_parts = command.strip().split()
            if cmd_parts:
                base_cmd = os.path.basename(cmd_parts[0].lower())

                # Handle cd command specially - update engine working directory (v1.13.8)
                # Skip if command has shell operators (e.g., "cd /path && python3 main.py")
                if base_cmd == "cd" and len(cmd_parts) >= 2 and not has_shell_operators:
                    target_path = " ".join(cmd_parts[1:])  # Handle paths with spaces
                    # Expand ~ and resolve relative to current working dir
                    expanded = os.path.expanduser(target_path)
                    if not os.path.isabs(expanded):
                        base_dir = working_dir if working_dir and working_dir != "." else os.getcwd()
                        resolved = os.path.normpath(os.path.join(base_dir, expanded))
                    else:
                        resolved = expanded

                    if os.path.isdir(resolved):
                        self.engine.set_working_dir(resolved)
                        return f"Changed directory to: {resolved}"
                    else:
                        return f"Error: Directory not found: {target_path}"

                # Check if it's an interactive command (skip for compound commands)
                if base_cmd in interactive_commands and not has_shell_operators:
                    # Some commands are only interactive without arguments
                    if base_cmd in non_interactive_with_args and len(cmd_parts) > 1:
                        # Has arguments, likely not interactive (e.g., 'python script.py', 'ssh host cmd')
                        pass
                    else:
                        return (
                            f"Error: '{base_cmd}' is an interactive command that requires user input.\n\n"
                            f"Interactive commands like text editors (nano, vim), REPLs (python, node), "
                            f"and pagers (less, more) cannot be run through this tool because they "
                            f"require keyboard input and have a {timeout}-second timeout.\n\n"
                            f"Alternatives:\n"
                            f"- To view file contents: use 'cat <file>' or the read_file tool\n"
                            f"- To edit files: describe the changes you want and I'll help modify the file\n"
                            f"- To run scripts: use 'python script.py' or 'node script.js' with arguments"
                        )

            # Determine shell based on platform
            is_windows = platform.system() == "Windows"

            # Validate working directory without chdir-ing the engine process:
            # the asyncio subprocess accepts cwd= directly, and chdir-ing the
            # whole event-loop thread would race with concurrent tool calls.
            if working_dir and not os.path.isdir(working_dir):
                return f"Error: Working directory does not exist: {working_dir}"

            backgrounded = _is_backgrounded(command)

            # Resolve shell binary and login mode from config.
            shell_bin = shell_config.get("shell_bin") if not is_windows else None
            login_shell = shell_config.get("login_shell", False) and not is_windows

            # Pipe vs DEVNULL:
            # - foreground commands: capture stdout+stderr (the result the
            #   model needs to see).
            # - backgrounded commands: DEVNULL everything so an inherited
            #   pipe FD held open by the long-running child cannot block
            #   our await proc.communicate() / proc.wait().
            if backgrounded:
                stdout_dst = asyncio.subprocess.DEVNULL
                stderr_dst = asyncio.subprocess.DEVNULL
                stdin_dst = asyncio.subprocess.DEVNULL
            else:
                stdout_dst = asyncio.subprocess.PIPE
                stderr_dst = asyncio.subprocess.PIPE
                stdin_dst = asyncio.subprocess.DEVNULL  # never let a tool block on stdin

            # `start_new_session=True` puts the wrapper in its own process
            # group so SIGTERM during interrupt_stream propagates to the
            # whole tree, AND so backgrounded children cannot get TTY
            # signals from the engine process.
            try:
                if shell_bin:
                    cmd_list = [shell_bin]
                    if login_shell:
                        cmd_list.append('-l')
                    cmd_list.extend(['-c', command])
                    proc = await asyncio.create_subprocess_exec(
                        *cmd_list,
                        stdin=stdin_dst,
                        stdout=stdout_dst,
                        stderr=stderr_dst,
                        cwd=working_dir if working_dir else None,
                        start_new_session=not is_windows,
                    )
                else:
                    proc = await asyncio.create_subprocess_shell(
                        command,
                        stdin=stdin_dst,
                        stdout=stdout_dst,
                        stderr=stderr_dst,
                        cwd=working_dir if working_dir else None,
                        start_new_session=not is_windows,
                    )
            except Exception as e:
                return f"Error executing command: {str(e)}"

            self.engine.register_subprocess(proc)
            try:
                if backgrounded:
                    # Wait briefly for the wrapper subshell to fork+detach
                    # (typical: <50 ms). The actual long-running child has
                    # been re-parented via start_new_session and its FDs
                    # are DEVNULL, so we don't wait for it.
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=min(timeout, 5))
                        rc = proc.returncode
                    except asyncio.TimeoutError:
                        # Wrapper itself is still running — unusual for a
                        # backgrounded command but not fatal. Treat as
                        # "launched, detached".
                        rc = 0
                    return (
                        f"Command launched in background (exit code: {rc if rc is not None else 'detached'}). "
                        f"Output discarded — redirect explicitly with `> file 2>&1` if you need it."
                    )

                try:
                    stdout_b, stderr_b = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout
                    )
                except asyncio.TimeoutError:
                    # SIGTERM the whole process group, then SIGKILL after grace.
                    terminate_subprocess_tree(proc)
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        kill_subprocess_tree(proc)
                    return (
                        f"Error: Command timed out after {timeout} seconds. "
                        f"Set 'tools.shell.timeout' in config for longer timeouts."
                    )
                except asyncio.CancelledError:
                    # Engine cancellation (interrupt_stream) — kill and re-raise.
                    terminate_subprocess_tree(proc)
                    raise

                stdout_text = stdout_b.decode('utf-8', errors='replace') if stdout_b else ""
                stderr_text = stderr_b.decode('utf-8', errors='replace') if stderr_b else ""

                output = stdout_text
                if stderr_text:
                    if output:
                        output += "\n--- stderr ---\n"
                    output += stderr_text

                if proc.returncode and proc.returncode != 0:
                    output += f"\n\nCommand exited with code: {proc.returncode}"

                # Truncate output if too large (prevent context overflow)
                max_output = 10000  # 10KB limit
                if len(output) > max_output:
                    output = output[:max_output] + f"\n\n... (output truncated, {len(output) - max_output} chars omitted)"

                return output if output else f"Command completed successfully (exit code: {proc.returncode})"
            finally:
                self.engine.unregister_subprocess(proc)

        except Exception as e:
            return f"Error executing command: {str(e)}"


def register_tools(manager: ToolManagerProtocol, engine: ToolEngineProtocol):
    """Register shell tools with the manager.

    Args:
        manager: ToolManager instance
        engine: Engine client instance (for consent checking)
    """
    # Register shell tool with engine binding for consent
    manager.register_tool(ShellExecuteTool(engine))

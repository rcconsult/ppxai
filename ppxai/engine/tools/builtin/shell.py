"""
Shell command execution tool with consent management (v1.11.2).

v1.13.6: Interactive command lists now configurable via JSON config.
"""

import os
import subprocess
import platform
from typing import TYPE_CHECKING, List

from ....config import get_shell_config
from ..base import BaseTool

if TYPE_CHECKING:
    from ...client import EngineClient
    from ..manager import ToolManager


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

    def __init__(self, engine: 'EngineClient'):
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

            # Change to working directory if specified
            original_dir = None
            if working_dir:
                original_dir = os.getcwd()
                if not os.path.isdir(working_dir):
                    return f"Error: Working directory does not exist: {working_dir}"
                os.chdir(working_dir)

            try:
                # Execute command with shell (timeout configurable via config, v1.15.2)
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    encoding='utf-8' if not is_windows else None,
                    errors='replace'
                )

                # Combine stdout and stderr
                output = ""
                if result.stdout:
                    output += result.stdout
                if result.stderr:
                    if output:
                        output += "\n--- stderr ---\n"
                    output += result.stderr

                # Add return code if non-zero
                if result.returncode != 0:
                    output += f"\n\nCommand exited with code: {result.returncode}"

                # Truncate output if too large (prevent context overflow)
                max_output = 10000  # 10KB limit
                if len(output) > max_output:
                    output = output[:max_output] + f"\n\n... (output truncated, {len(output) - max_output} chars omitted)"

                return output if output else f"Command completed successfully (exit code: {result.returncode})"

            finally:
                # Restore original directory
                if original_dir:
                    os.chdir(original_dir)

        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout} seconds. Set 'tools.shell.timeout' in config for longer timeouts."
        except Exception as e:
            return f"Error executing command: {str(e)}"


def register_tools(manager: 'ToolManager', engine: 'EngineClient'):
    """Register shell tools with the manager.

    Args:
        manager: ToolManager instance
        engine: Engine client instance (for consent checking)
    """
    # Register shell tool with engine binding for consent
    manager.register_tool(ShellExecuteTool(engine))

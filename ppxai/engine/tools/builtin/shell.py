"""
Shell command execution tool with consent management (v1.11.2).

v1.13.6: Interactive command lists now configurable via JSON config.
"""

import os
import subprocess
import platform
from typing import TYPE_CHECKING, List

from ..base import BaseTool

if TYPE_CHECKING:
    from ...client import EngineClient
    from ..manager import ToolManager


def _get_interactive_commands() -> tuple[List[str], List[str]]:
    """Get interactive command lists from config.

    Returns:
        Tuple of (interactive_commands, non_interactive_with_args)
    """
    try:
        from ....config import get_shell_config
        shell_config = get_shell_config()
        return (
            shell_config.get("interactive_commands", []),
            shell_config.get("non_interactive_with_args", [])
        )
    except ImportError:
        # Fallback defaults if config not available
        interactive = [
            'nano', 'vim', 'vi', 'emacs', 'pico', 'joe',
            'less', 'more',
            'top', 'htop', 'btop',
            'python', 'python3', 'ipython', 'node', 'irb', 'ruby',
            'ssh', 'telnet', 'ftp', 'sftp',
            'mysql', 'psql', 'mongo', 'redis-cli',
            'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh',
        ]
        non_interactive_with_args = [
            'python', 'python3', 'ipython', 'node', 'irb', 'ruby',
            'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh',
            'ssh', 'mysql', 'psql',
        ]
        return interactive, non_interactive_with_args


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
            "Commands run with a 30-second timeout. "
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
        # Use engine's working directory if not specified
        if working_dir is None:
            working_dir = self.engine.get_working_dir() or "."

        consent_approved = await self.engine.request_shell_consent(command, working_dir)
        if not consent_approved:
            return f"Error: User denied permission to execute command: {command}"

        try:
            # Get interactive command lists from config (v1.13.6)
            interactive_commands, non_interactive_with_args = _get_interactive_commands()

            # Extract the base command
            cmd_parts = command.strip().split()
            if cmd_parts:
                base_cmd = os.path.basename(cmd_parts[0].lower())

                # Check if it's an interactive command
                if base_cmd in interactive_commands:
                    # Some commands are only interactive without arguments
                    if base_cmd in non_interactive_with_args and len(cmd_parts) > 1:
                        # Has arguments, likely not interactive (e.g., 'python script.py', 'ssh host cmd')
                        pass
                    else:
                        return (
                            f"Error: '{base_cmd}' is an interactive command that requires user input.\n\n"
                            f"Interactive commands like text editors (nano, vim), REPLs (python, node), "
                            f"and pagers (less, more) cannot be run through this tool because they "
                            f"require keyboard input and have a 30-second timeout.\n\n"
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
                # Execute command with shell
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30,  # 30 second timeout
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
            return "Error: Command timed out after 30 seconds"
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

"""
Shell command execution tool.
"""

import os
import subprocess
import platform
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..manager import ToolManager


# Interactive commands that require user input
INTERACTIVE_COMMANDS = [
    'nano', 'vim', 'vi', 'emacs', 'pico', 'joe',  # Text editors
    'less', 'more',  # Pagers
    'top', 'htop', 'btop',  # System monitors
    'python', 'python3', 'ipython', 'node', 'irb', 'ruby',  # REPLs (without args)
    'ssh', 'telnet', 'ftp', 'sftp',  # Remote connections
    'mysql', 'psql', 'mongo', 'redis-cli',  # Database CLIs
    'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh',  # Shells (without args)
]

# Commands that are only interactive without arguments
REPL_COMMANDS = ['python', 'python3', 'ipython', 'node', 'irb', 'ruby', 'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh']


def execute_shell_command(command: str, working_dir: str = None) -> str:
    """Execute a shell command and return the output.

    Args:
        command: The shell command to execute
        working_dir: Optional working directory for the command

    Returns:
        Command output (stdout + stderr) or error message
    """
    try:
        # Extract the base command
        cmd_parts = command.strip().split()
        if cmd_parts:
            base_cmd = os.path.basename(cmd_parts[0].lower())

            # Check if it's an interactive command
            if base_cmd in INTERACTIVE_COMMANDS:
                # Some commands are only interactive without arguments
                if base_cmd in REPL_COMMANDS and len(cmd_parts) > 1:
                    # Has arguments, likely not interactive (e.g., 'python script.py')
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


def register_tools(manager: 'ToolManager'):
    """Register shell tools with the manager."""

    manager.register_function(
        name="execute_shell_command",
        description=(
            "Execute a shell command in the system. Supports Windows (cmd/PowerShell) and Unix (bash) commands. "
            "Use for system operations like creating directories, running scripts, git commands, etc. "
            "Commands run with a 30-second timeout. "
            "IMPORTANT: Do NOT use recursive commands like 'ls -R', 'find', 'tree' - they produce too much output. "
            "For file listing use the list_directory tool. For file search use search_files tool. For reading files use read_file tool."
        ),
        parameters={
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
        },
        handler=execute_shell_command
    )

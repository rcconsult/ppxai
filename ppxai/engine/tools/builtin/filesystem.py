"""
Filesystem tools: read_file, search_files, list_directory.
"""

import glob as glob_module
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..manager import ToolManager


def search_files(pattern: str, directory: str = ".") -> str:
    """Search for files matching a pattern.

    Args:
        pattern: Glob pattern (e.g., '*.py')
        directory: Directory to search (default: '.')

    Returns:
        Newline-separated list of matching files
    """
    try:
        results = glob_module.glob(f"{directory}/**/{pattern}", recursive=True)
        if not results:
            return f"No files found matching '{pattern}'"
        return "\n".join(results[:20])
    except Exception as e:
        return f"Error: {str(e)}"


def read_file(filepath: str, max_lines: int = 500) -> str:
    """Read contents of a file.

    Args:
        filepath: Path to the file
        max_lines: Maximum lines to read (default: 500)

    Returns:
        File contents or error message
    """
    try:
        path = Path(filepath).expanduser().resolve()
        if not path.exists():
            return f"Error: File not found: {filepath}"
        if not path.is_file():
            return f"Error: Not a file: {filepath}"

        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()[:max_lines]
            content = ''.join(lines)

        if len(lines) == max_lines:
            content += f"\n... (truncated to {max_lines} lines)"

        return content
    except Exception as e:
        return f"Error reading file: {str(e)}"


def list_directory(path: str = ".", format: str = "simple") -> str:
    """List files and directories with optional long format.

    Args:
        path: Directory path (default: '.')
        format: 'simple' or 'long' (like 'ls -la')

    Returns:
        Directory listing
    """
    import stat
    from datetime import datetime

    try:
        dir_path = Path(path).expanduser().resolve()
        if not dir_path.exists():
            return f"Error: Directory not found: {path}"
        if not dir_path.is_dir():
            return f"Error: Not a directory: {path}"

        items = []

        if format == "long":
            for item in sorted(dir_path.iterdir()):
                try:
                    stats = item.stat()
                    mode = stats.st_mode
                    perms = stat.filemode(mode)
                    nlink = stats.st_nlink

                    try:
                        import pwd
                        owner = pwd.getpwuid(stats.st_uid).pw_name
                    except Exception:
                        owner = str(stats.st_uid)

                    try:
                        import grp
                        group = grp.getgrgid(stats.st_gid).gr_name
                    except Exception:
                        group = str(stats.st_gid)

                    size = stats.st_size
                    mtime = datetime.fromtimestamp(stats.st_mtime)
                    mtime_str = mtime.strftime("%b %d %H:%M")

                    line = f"{perms} {nlink:3} {owner:8} {group:8} {size:8} {mtime_str} {item.name}"
                    items.append(line)
                except Exception as e:
                    items.append(f"? {item.name} (error: {e})")
        else:
            for item in sorted(dir_path.iterdir()):
                item_type = "DIR " if item.is_dir() else "FILE"
                items.append(f"{item_type} {item.name}")

        result = "\n".join(items[:50])
        if len(items) > 50:
            result += f"\n... ({len(items) - 50} more items)"

        return result
    except Exception as e:
        return f"Error: {str(e)}"


def register_tools(manager: 'ToolManager'):
    """Register filesystem tools with the manager."""

    manager.register_function(
        name="search_files",
        description="Search for files matching a glob pattern in a directory",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g., '*.py')"},
                "directory": {"type": "string", "description": "Directory to search (default: '.')"}
            },
            "required": ["pattern"]
        },
        handler=search_files
    )

    manager.register_function(
        name="read_file",
        description="Read the contents of a text file",
        parameters={
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Path to the file"},
                "max_lines": {"type": "integer", "description": "Max lines (default: 500)"}
            },
            "required": ["filepath"]
        },
        handler=read_file
    )

    manager.register_function(
        name="list_directory",
        description="List files and directories in a path. Supports simple and long format (like 'ls -la')",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path (default: '.')"
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'simple' (default) or 'long' (detailed like 'ls -la')",
                    "enum": ["simple", "long"]
                }
            },
            "required": []
        },
        handler=list_directory
    )

"""
Filesystem tools: read_file, search_files, list_directory, set_working_directory.
"""

import glob as glob_module
import os
import stat
from datetime import datetime
from pathlib import Path

try:
    import pwd
except ImportError:
    pwd = None

try:
    import grp
except ImportError:
    grp = None

from ...types import ToolEngineProtocol, ToolManagerProtocol
from ..base import BaseTool


class SetWorkingDirectoryTool(BaseTool):
    """Tool to set the working directory for file operations."""

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "set_working_directory"
        self.description = (
            "Set the working directory for file operations. Use this when the user asks to change "
            "the working directory, project folder, or current directory. The path can be absolute "
            "or use ~ for home directory."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to set as working directory (absolute path or ~ for home)"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str, **kwargs) -> str:
        """Set the working directory.

        Args:
            path: Directory path

        Returns:
            Success message or error
        """
        try:
            # Expand ~ and resolve path
            expanded = os.path.expanduser(path)
            resolved = Path(expanded).resolve()

            if not resolved.exists():
                return f"Error: Directory not found: {path}"
            if not resolved.is_dir():
                return f"Error: Not a directory: {path}"

            # Update engine context
            self.engine.set_working_dir(str(resolved))

            return f"Working directory set to: {resolved}"
        except Exception as e:
            return f"Error setting working directory: {str(e)}"


class GetWorkingDirectoryTool(BaseTool):
    """Tool to get the current working directory."""

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "get_working_directory"
        self.description = (
            "Get the current working directory. Use this when the user asks what the current "
            "working directory, project folder, or current directory is."
        )
        self.parameters = {
            "type": "object",
            "properties": {},
            "required": []
        }

    async def execute(self, **kwargs) -> str:
        """Get the current working directory.

        Returns:
            Current working directory path or message if not set
        """
        try:
            working_dir = self.engine.get_working_dir()
            if working_dir:
                return f"Current working directory: {working_dir}"
            else:
                return "Working directory not set. Using default system directory."
        except Exception as e:
            return f"Error getting working directory: {str(e)}"


class ListDirectoryTool(BaseTool):
    """Tool to list files and directories."""

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "list_directory"
        self.description = "List files and directories in a path. Supports simple and long format (like 'ls -la')"
        self.parameters = {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path (default: current working directory)"
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'simple' (default) or 'long' (detailed like 'ls -la')",
                    "enum": ["simple", "long"]
                }
            },
            "required": []
        }

    async def execute(self, path: str = ".", format: str = "simple", **kwargs) -> str:
        """List files and directories.

        Args:
            path: Directory path (default: '.')
            format: 'simple' or 'long'

        Returns:
            Directory listing
        """
        try:
            # Resolve path relative to engine's working directory
            if path == "." or not path:
                working_dir = self.engine.get_working_dir()
                dir_path = Path(working_dir) if working_dir else Path.cwd()
            else:
                expanded = os.path.expanduser(path)
                if not os.path.isabs(expanded):
                    working_dir = self.engine.get_working_dir()
                    base = Path(working_dir) if working_dir else Path.cwd()
                    dir_path = (base / expanded).resolve()
                else:
                    dir_path = Path(expanded).resolve()

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
                            owner = pwd.getpwuid(stats.st_uid).pw_name if pwd else str(stats.st_uid)
                        except Exception:
                            owner = str(stats.st_uid)

                        try:
                            group = grp.getgrgid(stats.st_gid).gr_name if grp else str(stats.st_gid)
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

            # v1.18.4: prefix the resolved path in the output. Without
            # it, the model that called this tool with `path="."` has
            # no way to know which directory it just listed — it
            # confabulates a path in its response (e.g. shows the
            # parent dir if the user just `/cd`'d into a subdir).
            # Reported 2026-05-04 from the web UI: after `/cd ppxai_demo`,
            # asking the model "ls" produced "/Users/rado/git/exps
            # contains the files and folders listed above" — the
            # parent of the actual working dir.
            header = (
                f"Long-format listing of {dir_path}:"
                if format == "long"
                else f"Listing of {dir_path}:"
            )
            if not items:
                return f"{header}\n(empty)"

            visible = items[:100]
            body = "\n".join(visible)
            if len(items) > 100:
                body += f"\n... ({len(items) - 100} more items)"

            return f"{header}\n{body}"
        except Exception as e:
            return f"Error: {str(e)}"


class SearchFilesTool(BaseTool):
    """Tool to search for files matching a pattern."""

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "search_files"
        self.description = "Search for files matching a glob pattern in a directory"
        self.parameters = {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g., '*.py')"},
                "directory": {"type": "string", "description": "Directory to search (default: current working directory)"}
            },
            "required": ["pattern"]
        }

    async def execute(self, pattern: str, directory: str = ".", **kwargs) -> str:
        """Search for files matching a pattern.

        Args:
            pattern: Glob pattern (e.g., '*.py')
            directory: Directory to search (default: '.')

        Returns:
            Newline-separated list of matching files
        """
        try:
            # Resolve directory relative to engine's working directory
            if directory == "." or not directory:
                working_dir = self.engine.get_working_dir()
                search_dir = working_dir if working_dir else os.getcwd()
            else:
                expanded = os.path.expanduser(directory)
                if not os.path.isabs(expanded):
                    working_dir = self.engine.get_working_dir()
                    base = working_dir if working_dir else os.getcwd()
                    search_dir = str(Path(base) / expanded)
                else:
                    search_dir = expanded

            results = glob_module.glob(f"{search_dir}/**/{pattern}", recursive=True)
            # v1.18.4: ground every result (including zero-match) in
            # the directory that was searched, so the model knows
            # where the search ran instead of guessing.
            header = f"Searched for '{pattern}' in {search_dir}:"
            if not results:
                return f"{header}\n(no matches)"
            output = "\n".join(results[:50])
            if len(results) > 50:
                output += f"\n... ({len(results) - 50} more files)"
            return f"{header}\n{output}"
        except Exception as e:
            return f"Error: {str(e)}"


class ReadFileTool(BaseTool):
    """Tool to read file contents."""

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "read_file"
        self.description = (
            "Read the contents of a text file. Returns a header with total "
            "line count so you know the full size. Use offset to continue "
            "reading from where you left off instead of re-reading from the start."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Path to the file"},
                "offset": {
                    "type": "integer",
                    "description": (
                        "Line number to start reading from (0-indexed, default: 0). "
                        "Use this to continue reading a large file from where a "
                        "previous read left off, instead of re-reading from the start."
                    ),
                },
                "max_lines": {"type": "integer", "description": "Max lines to return (default: 1000)"},
            },
            "required": ["filepath"]
        }

    async def execute(self, filepath: str, offset: int = 0, max_lines: int = 1000, **kwargs) -> str:
        """Read contents of a file.

        Args:
            filepath: Path to the file
            offset: Line number to start from (0-indexed, default: 0)
            max_lines: Maximum lines to read (default: 1000)

        Returns:
            File contents with a header showing total lines, the range
            returned, and whether more content follows. This metadata
            lets the model decide whether to request more without
            re-reading already-seen content.
        """
        try:
            # Resolve path relative to engine's working directory
            expanded = os.path.expanduser(filepath)
            if not os.path.isabs(expanded):
                working_dir = self.engine.get_working_dir()
                base = Path(working_dir) if working_dir else Path.cwd()
                path = (base / expanded).resolve()
            else:
                path = Path(expanded).resolve()

            if not path.exists():
                # Provide helpful suggestion for creating new files
                return (
                    f"Error: File not found: {filepath}\n"
                    f"Tip: To create a new file, use insert_text tool with line_number=1, "
                    f"or apply_patch with '*** Add File:' syntax."
                )
            if not path.is_file():
                return f"Error: Not a file: {filepath}"

            with open(path, 'r', encoding='utf-8-sig') as f:
                all_lines = f.readlines()

            total_lines = len(all_lines)
            start = min(offset, total_lines)
            end = min(start + max_lines, total_lines)
            selected = all_lines[start:end]
            content = ''.join(selected)

            # Header: tells the model the file size and what slice it got,
            # so it can use offset for the next read instead of re-reading
            # from line 0 with a bigger max_lines.
            header = f"[File: {filepath} | {total_lines} lines total | showing lines {start + 1}-{end}]"
            if end < total_lines:
                remaining = total_lines - end
                header += f" ({remaining} more lines — use offset={end} to continue)"

            return f"{header}\n{content}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


# Legacy standalone functions (for backward compatibility)
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
        output = "\n".join(results[:50])
        if len(results) > 50:
            output += f"\n... ({len(results) - 50} more files)"
        return output
    except Exception as e:
        return f"Error: {str(e)}"


def read_file(filepath: str, max_lines: int = 1000) -> str:
    """Read contents of a file.

    Args:
        filepath: Path to the file
        max_lines: Maximum lines to read (default: 1000)

    Returns:
        File contents or error message
    """
    try:
        path = Path(filepath).expanduser().resolve()
        if not path.exists():
            return f"Error: File not found: {filepath}"
        if not path.is_file():
            return f"Error: Not a file: {filepath}"

        with open(path, 'r', encoding='utf-8-sig') as f:
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
                        owner = pwd.getpwuid(stats.st_uid).pw_name if pwd else str(stats.st_uid)
                    except Exception:
                        owner = str(stats.st_uid)

                    try:
                        group = grp.getgrgid(stats.st_gid).gr_name if grp else str(stats.st_gid)
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

        result = "\n".join(items[:100])
        if len(items) > 100:
            result += f"\n... ({len(items) - 100} more items)"

        return result
    except Exception as e:
        return f"Error: {str(e)}"


def register_tools(manager: ToolManagerProtocol, engine: ToolEngineProtocol = None):
    """Register filesystem tools with the manager.

    Args:
        manager: ToolManager instance
        engine: EngineClient instance (optional, needed for working directory-aware tools)
    """
    if engine is not None:
        # Use engine-aware tool classes that respect working directory
        manager.register_tool(SetWorkingDirectoryTool(engine))
        manager.register_tool(GetWorkingDirectoryTool(engine))
        manager.register_tool(ListDirectoryTool(engine))
        manager.register_tool(SearchFilesTool(engine))
        manager.register_tool(ReadFileTool(engine))
    else:
        # Fall back to legacy standalone functions (no working directory support)
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

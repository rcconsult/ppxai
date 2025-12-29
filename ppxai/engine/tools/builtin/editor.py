"""
File editing tools for autonomous code modification (v1.11.0).

These tools provide safe, atomic file editing operations with user consent.
All tools check for user consent before modifying files.
"""

import difflib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Dict, Any

from ..base import BaseTool

if TYPE_CHECKING:
    from ...client import EngineClient
    from ..manager import ToolManager


class ApplyPatchTool(BaseTool):
    """Apply unified diff patch to a file."""

    def __init__(self, engine: 'EngineClient'):
        """Initialize with engine reference for consent.

        Args:
            engine: Engine client instance
        """
        self.engine = engine
        self.name = "apply_patch"
        self.description = "Apply a unified diff patch to a file"
        self.parameters = {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to file to patch"
                },
                "unified_diff": {
                    "type": "string",
                    "description": "Unified diff format patch"
                }
            },
            "required": ["file_path", "unified_diff"]
        }

    async def execute(self, file_path: str, unified_diff: str, **kwargs) -> str:
        """Apply patch to file.

        Args:
            file_path: Path to file to patch
            unified_diff: Unified diff format patch

        Returns:
            Success/failure message
        """
        try:
            path = Path(file_path).expanduser().resolve()

            # Check consent
            if not await self.engine.request_file_edit_consent(str(path)):
                return f"Error: User denied permission to edit {file_path}"

            # Validate file exists
            if not path.exists():
                return f"Error: File not found: {file_path}"
            if not path.is_file():
                return f"Error: Not a file: {file_path}"

            # Read current content
            with open(path, 'r', encoding='utf-8') as f:
                original_lines = f.readlines()

            # Backup original content for rollback
            backup_content = ''.join(original_lines)

            try:
                # Apply patch
                new_lines = _apply_unified_diff(original_lines, unified_diff)

                # Write atomically (write to temp, then rename)
                temp_path = path.with_suffix(path.suffix + '.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)

                # Replace original file
                temp_path.replace(path)

                lines_changed = sum(1 for a, b in zip(original_lines, new_lines) if a != b)
                # v1.12.0: Track edited file for agent auto-commit
                self.engine._agent_edited_files.add(str(path))
                return f"✓ Successfully applied patch to {file_path} ({lines_changed} lines changed)"

            except Exception as e:
                # Rollback on failure
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(backup_content)
                return f"Error applying patch: {str(e)} (file restored)"

        except Exception as e:
            return f"Error: {str(e)}"


class ReplaceBlockTool(BaseTool):
    """Search for exact text block and replace it."""

    def __init__(self, engine: 'EngineClient'):
        """Initialize with engine reference for consent.

        Args:
            engine: Engine client instance
        """
        self.engine = engine
        self.name = "replace_block"
        self.description = "Search for exact text block and replace it (case-sensitive, must be unique)"
        self.parameters = {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to file to modify"
                },
                "search": {
                    "type": "string",
                    "description": "Text block to search for (exact match)"
                },
                "replace": {
                    "type": "string",
                    "description": "Replacement text"
                }
            },
            "required": ["file_path", "search", "replace"]
        }

    async def execute(self, file_path: str, search: str, replace: str, **kwargs) -> str:
        """Replace text block in file.

        Args:
            file_path: Path to file to modify
            search: Text block to search for
            replace: Replacement text

        Returns:
            Success/failure message
        """
        try:
            path = Path(file_path).expanduser().resolve()

            # Check consent
            if not await self.engine.request_file_edit_consent(str(path)):
                return f"Error: User denied permission to edit {file_path}"

            # Validate file exists
            if not path.exists():
                return f"Error: File not found: {file_path}"
            if not path.is_file():
                return f"Error: Not a file: {file_path}"

            # Read current content
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Backup original
            backup_content = content

            # Count occurrences
            count = content.count(search)

            if count == 0:
                return f"Error: Search text not found in {file_path}"
            elif count > 1:
                return f"Error: Search text found {count} times in {file_path} (must be unique)"

            # Find location for reporting
            start_pos = content.index(search)
            line_num = content[:start_pos].count('\n') + 1

            try:
                # Perform replacement
                new_content = content.replace(search, replace, 1)

                # Write atomically
                temp_path = path.with_suffix(path.suffix + '.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)

                temp_path.replace(path)

                lines_added = replace.count('\n') - search.count('\n')
                # v1.12.0: Track edited file for agent auto-commit
                self.engine._agent_edited_files.add(str(path))
                return f"✓ Successfully replaced block in {file_path} at line {line_num} ({lines_added:+d} lines)"

            except Exception as e:
                # Rollback on failure
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(backup_content)
                return f"Error during replacement: {str(e)} (file restored)"

        except Exception as e:
            return f"Error: {str(e)}"


class InsertTextTool(BaseTool):
    """Insert text at a specific line number."""

    def __init__(self, engine: 'EngineClient'):
        """Initialize with engine reference for consent.

        Args:
            engine: Engine client instance
        """
        self.engine = engine
        self.name = "insert_text"
        self.description = "Insert text at a specific line number (1-indexed)"
        self.parameters = {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to file to modify"
                },
                "line_number": {
                    "type": "integer",
                    "description": "Line number to insert at (1-indexed)"
                },
                "text": {
                    "type": "string",
                    "description": "Text to insert (can be multiple lines)"
                }
            },
            "required": ["file_path", "line_number", "text"]
        }

    async def execute(self, file_path: str, line_number: int, text: str, **kwargs) -> str:
        """Insert text at line number.

        Args:
            file_path: Path to file to modify
            line_number: Line number to insert at
            text: Text to insert

        Returns:
            Success/failure message
        """
        try:
            path = Path(file_path).expanduser().resolve()

            # Check consent
            if not await self.engine.request_file_edit_consent(str(path)):
                return f"Error: User denied permission to edit {file_path}"

            # Validate file exists
            if not path.exists():
                return f"Error: File not found: {file_path}"
            if not path.is_file():
                return f"Error: Not a file: {file_path}"

            # Read current content
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Backup original
            backup_content = ''.join(lines)

            # Validate line number
            if line_number < 1 or line_number > len(lines) + 1:
                return f"Error: Invalid line number {line_number} (file has {len(lines)} lines)"

            try:
                # Convert to 0-indexed
                insert_idx = line_number - 1

                # Ensure text ends with newline if inserting in middle
                if not text.endswith('\n') and insert_idx < len(lines):
                    text += '\n'

                # Insert text
                lines.insert(insert_idx, text)

                # Write atomically
                temp_path = path.with_suffix(path.suffix + '.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)

                temp_path.replace(path)

                num_lines = text.count('\n') + (0 if text.endswith('\n') else 1)
                end_line = line_number + num_lines - 1
                # v1.12.0: Track edited file for agent auto-commit
                self.engine._agent_edited_files.add(str(path))
                return f"✓ Successfully inserted text in {file_path} at lines {line_number}-{end_line}"

            except Exception as e:
                # Rollback on failure
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(backup_content)
                return f"Error during insertion: {str(e)} (file restored)"

        except Exception as e:
            return f"Error: {str(e)}"


class DeleteLinesTool(BaseTool):
    """Delete a range of lines from a file."""

    def __init__(self, engine: 'EngineClient'):
        """Initialize with engine reference for consent.

        Args:
            engine: Engine client instance
        """
        self.engine = engine
        self.name = "delete_lines"
        self.description = "Delete a range of lines from a file (1-indexed, inclusive)"
        self.parameters = {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to file to modify"
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to delete (1-indexed, inclusive)"
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to delete (1-indexed, inclusive)"
                }
            },
            "required": ["file_path", "start_line", "end_line"]
        }

    async def execute(self, file_path: str, start_line: int, end_line: int, **kwargs) -> str:
        """Delete lines from file.

        Args:
            file_path: Path to file to modify
            start_line: First line to delete
            end_line: Last line to delete

        Returns:
            Success/failure message
        """
        try:
            path = Path(file_path).expanduser().resolve()

            # Check consent
            if not await self.engine.request_file_edit_consent(str(path)):
                return f"Error: User denied permission to edit {file_path}"

            # Validate file exists
            if not path.exists():
                return f"Error: File not found: {file_path}"
            if not path.is_file():
                return f"Error: Not a file: {file_path}"

            # Read current content
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Backup original
            backup_content = ''.join(lines)

            # Validate line numbers
            if start_line < 1 or start_line > len(lines):
                return f"Error: Invalid start line {start_line} (file has {len(lines)} lines)"
            if end_line < start_line or end_line > len(lines):
                return f"Error: Invalid end line {end_line} (must be >= {start_line} and <= {len(lines)})"

            try:
                # Convert to 0-indexed (inclusive end)
                start_idx = start_line - 1
                end_idx = end_line  # Python slicing is exclusive at end

                # Get deleted content
                deleted_lines = lines[start_idx:end_idx]
                deleted_content = ''.join(deleted_lines)

                # Delete lines
                new_lines = lines[:start_idx] + lines[end_idx:]

                # Write atomically
                temp_path = path.with_suffix(path.suffix + '.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)

                temp_path.replace(path)

                num_deleted = end_line - start_line + 1
                preview = deleted_content[:100] + "..." if len(deleted_content) > 100 else deleted_content
                # v1.12.0: Track edited file for agent auto-commit
                self.engine._agent_edited_files.add(str(path))
                return f"✓ Successfully deleted lines {start_line}-{end_line} from {file_path} ({num_deleted} lines)\nDeleted content:\n{preview}"

            except Exception as e:
                # Rollback on failure
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(backup_content)
                return f"Error during deletion: {str(e)} (file restored)"

        except Exception as e:
            return f"Error: {str(e)}"


def _apply_unified_diff(original_lines: list, diff_text: str) -> list:
    """Apply a unified diff to original lines.

    Args:
        original_lines: Original file lines (with newlines)
        diff_text: Unified diff text

    Returns:
        New file lines after applying diff
    """
    diff_lines = diff_text.splitlines(keepends=True)
    new_lines = original_lines.copy()
    current_line = 0

    for line in diff_lines:
        if line.startswith('@@'):
            # Parse hunk header: @@ -start,count +start,count @@
            match = re.match(r'@@ -(\d+),?\d* \+(\d+),?\d* @@', line)
            if match:
                current_line = int(match.group(1)) - 1
        elif line.startswith('+') and not line.startswith('+++'):
            # Addition
            new_lines.insert(current_line, line[1:])
            current_line += 1
        elif line.startswith('-') and not line.startswith('---'):
            # Deletion
            if current_line < len(new_lines):
                new_lines.pop(current_line)
        else:
            # Context line
            current_line += 1

    return new_lines


def register_tools(manager: 'ToolManager', engine: 'EngineClient'):
    """Register file editing tools with the manager.

    Args:
        manager: ToolManager instance
        engine: Engine client instance (for consent checking)
    """
    # Register tools with engine binding
    manager.register_tool(ApplyPatchTool(engine))
    manager.register_tool(ReplaceBlockTool(engine))
    manager.register_tool(InsertTextTool(engine))
    manager.register_tool(DeleteLinesTool(engine))

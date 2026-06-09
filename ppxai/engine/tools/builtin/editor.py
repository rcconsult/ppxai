"""
File editing tools for autonomous code modification (v1.11.0).

These tools provide safe, atomic file editing operations with user consent.
All tools check for user consent before modifying files.
"""

import difflib
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Optional, Dict, Any

from ....common.atomic_file import atomic_replace
from ...types import ToolEngineProtocol, ToolManagerProtocol
from ..base import BaseTool
from .syntax_validator import (
    validate_candidate_content,
    format_validation_error,
)


def _register_checkpoint_file(engine: ToolEngineProtocol, path: Path):
    """Register a file with the checkpoint manager before editing.

    This ensures file-based checkpoints capture the original content
    for undo/rollback support during agent mode.
    """
    mgr = getattr(engine, '_checkpoint_manager', None)
    if mgr is not None:
        mgr.register_file(path)


class ApplyPatchTool(BaseTool):
    """Apply unified diff patch to a file."""

    def __init__(self, engine: ToolEngineProtocol):
        """Initialize with engine reference for consent.

        Args:
            engine: Engine client instance
        """
        self.engine = engine
        self.name = "apply_patch"
        self.description = (
            "Apply a unified diff patch to a file. REQUIRED: Both 'file_path' AND 'unified_diff' must be provided. "
            "For new files, use '*** Add File: filename' syntax. For existing files, use standard unified diff with @@ hunks. "
            "To create a new file, use insert_text tool with line_number=1 instead - it's simpler."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "REQUIRED: Absolute or relative path to file to patch (e.g., 'src/main.py' or 'C:/project/file.txt')"
                },
                "unified_diff": {
                    "type": "string",
                    "description": "REQUIRED: Unified diff format patch starting with '*** Begin Patch' or standard @@ hunks"
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
            # Resolve relative paths against engine's working directory
            expanded = os.path.expanduser(file_path)
            if not os.path.isabs(expanded):
                working_dir = self.engine.get_working_dir()
                if working_dir:
                    path = (Path(working_dir) / expanded).resolve()
                else:
                    path = Path(expanded).resolve()
            else:
                path = Path(expanded).resolve()

            # Check consent
            if not await self.engine.request_file_edit_consent(str(path)):
                return f"Error: User denied permission to edit {file_path}"

            # Detect new file creation from diff syntax
            # Models like GPT-OSS 120B use "*** Add File:" or "+++ /dev/null" patterns
            is_new_file = _is_new_file_diff(unified_diff)

            # Detect delete+recreate pattern (replaces entire file)
            is_delete_recreate = _is_delete_and_recreate_diff(unified_diff)

            # Validate file exists (unless creating new file)
            if not path.exists():
                if is_new_file:
                    # Create parent directories if needed
                    path.parent.mkdir(parents=True, exist_ok=True)
                    original_lines = []
                    backup_content = None  # No backup needed for new file
                else:
                    return f"Error: File not found: {file_path}. Use '*** Add File:' syntax in diff to create new files."
            elif not path.is_file():
                return f"Error: Not a file: {file_path}"
            else:
                # Read current content (utf-8-sig strips BOM transparently)
                with open(path, 'r', encoding='utf-8-sig') as f:
                    original_lines = f.readlines()
                # Backup original content for rollback
                backup_content = ''.join(original_lines)

            try:
                # For delete+recreate, treat as new file (ignore original content)
                if is_delete_recreate and path.exists():
                    new_lines = _apply_unified_diff([], unified_diff, is_new_file=True)
                else:
                    # Apply patch
                    new_lines = _apply_unified_diff(original_lines, unified_diff, is_new_file=is_new_file)

                # Check if any changes were actually made
                original_content = ''.join(original_lines)
                new_content = ''.join(new_lines)
                if original_content == new_content:
                    return (
                        f"Error: No changes applied to {file_path}. "
                        f"The patch did not match the file content. "
                        f"Try using write_file tool to overwrite the file directly."
                    )

                # R13: cheap post-apply syntax check. Catches silent
                # corruption when the model's diff context matched the
                # wrong function / lines and produced syntactically
                # broken output. We validate BEFORE writing, so failure
                # leaves the file untouched — no rollback needed.
                ok, language, err = validate_candidate_content(str(path), new_content)
                if not ok:
                    return format_validation_error(
                        file_path, language or "file", err or "parse failed",
                        tool_name="apply_patch",
                    )

                # Register with checkpoint manager before writing
                _register_checkpoint_file(self.engine, path)

                # Write atomically (write to temp, then rename)
                temp_path = path.with_suffix(path.suffix + '.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)

                # Replace original file
                atomic_replace(temp_path, path)

                # Track edited file for agent auto-commit
                self.engine._agent_edited_files.add(str(path))

                # v1.18.4: report the resolved absolute `path` in the
                # success message instead of the input arg `file_path`
                # (which may be relative like "foo.py"). The model can
                # then ground later references in the actual file
                # location, not the relpath that was relative to a
                # since-changed cwd.
                if is_new_file and not original_lines:
                    return f"✓ Successfully created {path} ({len(new_lines)} lines)"
                elif is_delete_recreate:
                    return f"✓ Successfully replaced {path} ({len(new_lines)} lines)"
                else:
                    lines_changed = sum(1 for a, b in zip(original_lines, new_lines) if a != b)
                    lines_added = len(new_lines) - len(original_lines)
                    return f"✓ Successfully applied patch to {path} ({lines_changed} lines modified, {lines_added:+d} lines)"

            except Exception as e:
                # Rollback on failure (only if we had backup)
                if backup_content is not None:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(backup_content)
                    return f"Error applying patch: {str(e)} (file restored)"
                else:
                    # New file creation failed, remove if created
                    if path.exists():
                        path.unlink()
                    return f"Error creating file: {str(e)}"

        except Exception as e:
            return f"Error: {str(e)}"


class ReplaceBlockTool(BaseTool):
    """Search for exact text block and replace it."""

    def __init__(self, engine: ToolEngineProtocol):
        """Initialize with engine reference for consent.

        Args:
            engine: Engine client instance
        """
        self.engine = engine
        self.name = "replace_block"
        self.description = "Search for exact text block and replace it (case-sensitive, must be unique). After modifying files, consider using display_file to show the result to the user."
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
            # Resolve relative paths against engine's working directory
            expanded = os.path.expanduser(file_path)
            if not os.path.isabs(expanded):
                working_dir = self.engine.get_working_dir()
                if working_dir:
                    path = (Path(working_dir) / expanded).resolve()
                else:
                    path = Path(expanded).resolve()
            else:
                path = Path(expanded).resolve()

            # Check consent
            if not await self.engine.request_file_edit_consent(str(path)):
                return f"Error: User denied permission to edit {file_path}"

            # Validate file exists
            if not path.exists():
                return (
                    f"Error: File not found: {file_path}\n"
                    f"Tip: Use read_file or list_directory to verify the path. "
                    f"For new files, use insert_text with line_number=1."
                )
            if not path.is_file():
                return f"Error: Not a file: {file_path}"

            # Read current content (utf-8-sig strips BOM transparently)
            with open(path, 'r', encoding='utf-8-sig') as f:
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

                # R13: syntax-validate before committing. A replace_block
                # that straddled a boundary or dropped a closing brace
                # would otherwise silently corrupt the file.
                ok, language, err = validate_candidate_content(str(path), new_content)
                if not ok:
                    return format_validation_error(
                        file_path, language or "file", err or "parse failed",
                        tool_name="replace_block",
                    )

                # Register with checkpoint manager before writing
                _register_checkpoint_file(self.engine, path)

                # Write atomically
                temp_path = path.with_suffix(path.suffix + '.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)

                atomic_replace(temp_path, path)

                lines_added = replace.count('\n') - search.count('\n')
                # Track edited file for agent auto-commit
                self.engine._agent_edited_files.add(str(path))
                # v1.18.4: resolved absolute path, not the input relpath.
                return f"✓ Successfully replaced block in {path} at line {line_num} ({lines_added:+d} lines)"

            except Exception as e:
                # Rollback on failure
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(backup_content)
                return f"Error during replacement: {str(e)} (file restored)"

        except Exception as e:
            return f"Error: {str(e)}"


class InsertTextTool(BaseTool):
    """Insert text at a specific line number."""

    def __init__(self, engine: ToolEngineProtocol):
        """Initialize with engine reference for consent.

        Args:
            engine: Engine client instance
        """
        self.engine = engine
        self.name = "insert_text"
        self.description = "Insert text at a specific line number (1-indexed). After creating/modifying files, consider using display_file to show the result to the user."
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
            # Resolve relative paths against engine's working directory
            expanded = os.path.expanduser(file_path)
            if not os.path.isabs(expanded):
                working_dir = self.engine.get_working_dir()
                if working_dir:
                    path = (Path(working_dir) / expanded).resolve()
                else:
                    path = Path(expanded).resolve()
            else:
                path = Path(expanded).resolve()

            # Check consent
            if not await self.engine.request_file_edit_consent(str(path)):
                return f"Error: User denied permission to edit {file_path}"

            # Support creating new files when inserting at line 1
            is_new_file = False
            if not path.exists():
                if line_number == 1:
                    # Create parent directories if needed
                    path.parent.mkdir(parents=True, exist_ok=True)
                    lines = []
                    backup_content = None
                    is_new_file = True
                else:
                    return f"Error: File not found: {file_path}. Use line_number=1 to create a new file."
            elif not path.is_file():
                return f"Error: Not a file: {file_path}"
            else:
                # Read current content (utf-8-sig strips BOM transparently)
                with open(path, 'r', encoding='utf-8-sig') as f:
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

                # R13: syntax-validate the combined content before writing.
                # Particularly useful for insert_text — a snippet pasted at
                # the wrong line (wrong indentation, mid-expression) can
                # break a file without the model noticing.
                new_content = ''.join(lines)
                ok, language, err = validate_candidate_content(str(path), new_content)
                if not ok:
                    return format_validation_error(
                        file_path, language or "file", err or "parse failed",
                        tool_name="insert_text",
                    )

                # Register with checkpoint manager before writing
                _register_checkpoint_file(self.engine, path)

                # Write atomically
                temp_path = path.with_suffix(path.suffix + '.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)

                atomic_replace(temp_path, path)

                num_lines = text.count('\n') + (0 if text.endswith('\n') else 1)
                end_line = line_number + num_lines - 1
                # Track edited file for agent auto-commit
                self.engine._agent_edited_files.add(str(path))

                # v1.18.4: resolved absolute path, not the input relpath.
                if is_new_file:
                    return f"✓ Successfully created {path} ({num_lines} lines)"
                else:
                    return f"✓ Successfully inserted text in {path} at lines {line_number}-{end_line}"

            except Exception as e:
                # Rollback on failure (only if we had backup)
                if backup_content is not None:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(backup_content)
                    return f"Error during insertion: {str(e)} (file restored)"
                else:
                    # New file creation failed, remove if created
                    if path.exists():
                        path.unlink()
                    return f"Error creating file: {str(e)}"

        except Exception as e:
            return f"Error: {str(e)}"


class DeleteLinesTool(BaseTool):
    """Delete a range of lines from a file."""

    def __init__(self, engine: ToolEngineProtocol):
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
            # Resolve relative paths against engine's working directory
            expanded = os.path.expanduser(file_path)
            if not os.path.isabs(expanded):
                working_dir = self.engine.get_working_dir()
                if working_dir:
                    path = (Path(working_dir) / expanded).resolve()
                else:
                    path = Path(expanded).resolve()
            else:
                path = Path(expanded).resolve()

            # Check consent
            if not await self.engine.request_file_edit_consent(str(path)):
                return f"Error: User denied permission to edit {file_path}"

            # Validate file exists
            if not path.exists():
                return (
                    f"Error: File not found: {file_path}\n"
                    f"Tip: Use read_file or list_directory to verify the path exists."
                )
            if not path.is_file():
                return f"Error: Not a file: {file_path}"

            # Read current content (utf-8-sig strips BOM transparently)
            with open(path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()

            # Backup original
            backup_content = ''.join(lines)

            # Validate line numbers
            if start_line < 1 or start_line > len(lines):
                return f"Error: Invalid start line {start_line} (file has {len(lines)} lines). Use read_file to check file contents first."
            if end_line < start_line or end_line > len(lines):
                return f"Error: Invalid end line {end_line} (must be >= {start_line} and <= {len(lines)}). Use read_file to check file length first."

            try:
                # Convert to 0-indexed (inclusive end)
                start_idx = start_line - 1
                end_idx = end_line  # Python slicing is exclusive at end

                # Get deleted content
                deleted_lines = lines[start_idx:end_idx]
                deleted_content = ''.join(deleted_lines)

                # Delete lines
                new_lines = lines[:start_idx] + lines[end_idx:]

                # R13: syntax-validate after deletion. Dropping a closing
                # brace, an `except:` block, or a function body can leave
                # the file unparseable — we catch it before the write.
                new_content = ''.join(new_lines)
                ok, language, err = validate_candidate_content(str(path), new_content)
                if not ok:
                    return format_validation_error(
                        file_path, language or "file", err or "parse failed",
                        tool_name="delete_lines",
                    )

                # Register with checkpoint manager before writing
                _register_checkpoint_file(self.engine, path)

                # Write atomically
                temp_path = path.with_suffix(path.suffix + '.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)

                atomic_replace(temp_path, path)

                num_deleted = end_line - start_line + 1
                preview = deleted_content[:100] + "..." if len(deleted_content) > 100 else deleted_content
                # Track edited file for agent auto-commit
                self.engine._agent_edited_files.add(str(path))
                # v1.18.4: resolved absolute path, not the input relpath.
                return f"✓ Successfully deleted lines {start_line}-{end_line} from {path} ({num_deleted} lines)\nDeleted content:\n{preview}"

            except Exception as e:
                # Rollback on failure
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(backup_content)
                return f"Error during deletion: {str(e)} (file restored)"

        except Exception as e:
            return f"Error: {str(e)}"


class WriteFileTool(BaseTool):
    """Write content to a file, creating it if it doesn't exist.

    v1.18.7: the validator's claim_without_action hint has been advertising
    `write_file` since v1.15.x, apply_patch's own error message points models
    at `write_file tool to overwrite the file directly`, and external models
    (Anthropic-family tools, OpenAI assistants) call `write_file` from
    training prior. Until this tool existed those calls all returned
    `Tool not found`, and the model would either retry the same name in a
    loop or fall through to `claim_without_action` after pretending it
    succeeded. This is the simplest write primitive: full-content overwrite,
    consent-gated, atomic.
    """

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "write_file"
        self.description = (
            "Write content to a file (creates if missing, overwrites by default). "
            "Use this when you have the full new contents — simpler than apply_patch "
            "for new files or whole-file rewrites. For partial edits to an existing "
            "file prefer apply_patch / replace_block / insert_text / delete_lines."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to file to write (absolute, or relative to working directory)",
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write. Will be encoded as UTF-8.",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "If false, return an error when the file already exists. Default: true.",
                    "default": True,
                },
            },
            "required": ["file_path", "content"],
        }

    async def execute(
        self,
        file_path: str,
        content: str,
        overwrite: bool = True,
        **kwargs,
    ) -> str:
        try:
            expanded = os.path.expanduser(file_path)
            if not os.path.isabs(expanded):
                working_dir = self.engine.get_working_dir()
                if working_dir:
                    path = (Path(working_dir) / expanded).resolve()
                else:
                    path = Path(expanded).resolve()
            else:
                path = Path(expanded).resolve()

            if not await self.engine.request_file_edit_consent(str(path)):
                return f"Error: User denied permission to edit {file_path}"

            existed = path.exists()
            if existed and not path.is_file():
                return f"Error: Not a file: {file_path}"
            if existed and not overwrite:
                return (
                    f"Error: File already exists: {file_path}. "
                    f"Set overwrite=true to replace it."
                )

            # Backup for rollback if overwriting
            backup_content = None
            if existed:
                with open(path, 'r', encoding='utf-8-sig') as f:
                    backup_content = f.read()

            # Pre-write syntax check — same gate apply_patch uses (R13).
            # Failure leaves the file untouched; no rollback path needed.
            ok, language, err = validate_candidate_content(str(path), content)
            if not ok:
                return format_validation_error(
                    file_path, language or "file", err or "parse failed",
                    tool_name="write_file",
                )

            path.parent.mkdir(parents=True, exist_ok=True)
            _register_checkpoint_file(self.engine, path)

            try:
                temp_path = path.with_suffix(path.suffix + '.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                atomic_replace(temp_path, path)
            except Exception as e:
                if backup_content is not None:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(backup_content)
                    return f"Error writing file: {str(e)} (file restored)"
                if path.exists():
                    path.unlink()
                return f"Error creating file: {str(e)}"

            self.engine._agent_edited_files.add(str(path))

            line_count = content.count('\n') + (0 if content.endswith('\n') or not content else 1)
            byte_count = len(content.encode('utf-8'))
            verb = "overwrote" if existed else "created"
            return f"✓ Successfully {verb} {path} ({line_count} lines, {byte_count} bytes)"

        except Exception as e:
            return f"Error: {str(e)}"


def _is_new_file_diff(diff_text: str) -> bool:
    """Check if diff represents a new file creation.

    v1.13.2: Models like GPT-OSS 120B use various patterns to indicate new files:
    - "*** Add File:" (common in AI-generated patches)
    - "--- /dev/null" (standard unified diff for new files)
    - "@@ -0,0 +1" (hunk starting from line 0)

    Args:
        diff_text: Unified diff text

    Returns:
        True if this diff creates a new file
    """
    # Normalize line endings
    lines = diff_text.replace('\r\n', '\n').split('\n')

    for line in lines:
        line_lower = line.lower().strip()
        # AI model patterns
        if '*** add file' in line_lower:
            return True
        if '*** new file' in line_lower:
            return True
        # Standard unified diff patterns for new files
        if line.startswith('--- /dev/null'):
            return True
        if line.startswith('--- a/dev/null'):
            return True
        # Hunk starting from 0 (new file)
        if line.startswith('@@') and '-0,0' in line:
            return True

    return False


def _is_delete_and_recreate_diff(diff_text: str) -> bool:
    """Check if diff is a delete-then-recreate pattern.

    v1.13.10: Models like GPT-OSS 120B sometimes use:
    *** Delete File: filename
    *** Add File: filename

    This should completely replace file contents.

    Args:
        diff_text: Unified diff text

    Returns:
        True if this is a delete+recreate pattern
    """
    lines = diff_text.replace('\r\n', '\n').split('\n')
    has_delete = False
    has_add = False

    for line in lines:
        line_lower = line.lower().strip()
        if '*** delete file' in line_lower:
            has_delete = True
        if '*** add file' in line_lower:
            has_add = True

    return has_delete and has_add


def _apply_unified_diff(original_lines: list, diff_text: str, is_new_file: bool = False) -> list:
    """Apply a unified diff to original lines.

    Args:
        original_lines: Original file lines (with newlines)
        diff_text: Unified diff text
        is_new_file: If True, extract content from new file diff format

    Returns:
        New file lines after applying diff
    """
    diff_lines = diff_text.splitlines(keepends=True)

    # For new files, just extract the added lines
    if is_new_file and not original_lines:
        new_lines = []
        in_content = False

        for line in diff_lines:
            # Skip headers and markers
            if line.startswith('*** ') or line.startswith('--- ') or line.startswith('+++ '):
                in_content = True
                continue
            if line.startswith('@@'):
                in_content = True
                continue

            # Extract added lines (lines starting with +)
            if in_content and line.startswith('+') and not line.startswith('+++'):
                new_lines.append(line[1:])  # Remove the + prefix
            elif in_content and not line.startswith('-') and not line.startswith('\\'):
                # Also accept lines without +/- prefix (some models don't use proper diff format)
                # But skip "\ No newline at end of file" markers
                if line.strip() and not line.startswith('@@'):
                    new_lines.append(line)

        # Ensure lines end with newlines
        result = []
        for line in new_lines:
            if not line.endswith('\n'):
                line += '\n'
            result.append(line)

        return result

    # Standard diff application for existing files
    new_lines = original_lines.copy()
    current_line = 0

    # Check if this is an AI-generated search-replace diff (no line numbers)
    # Format: @@\n-old\n+new (without @@ -X,Y +X,Y @@)
    has_line_numbers = any(
        re.match(r'@@ -\d+', line.strip())
        for line in diff_lines
        if line.strip().startswith('@@')
    )

    if not has_line_numbers:
        # AI model search-replace format - find old lines and replace with new
        return _apply_search_replace_diff(original_lines, diff_text)

    # Standard unified diff with line numbers
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


def _apply_search_replace_diff(original_lines: list, diff_text: str) -> list:
    """Apply AI-generated search-replace diff format.

    v1.13.2: Models like GPT-OSS 120B use a simpler format:
    *** Begin Patch
    *** Update File: filename.py
    @@
    -old line 1
    -old line 2
    +new line 1
    +new line 2
    *** End Patch

    This finds the old lines in sequence and replaces them with new lines.

    Args:
        original_lines: Original file lines (with newlines)
        diff_text: Diff text in search-replace format

    Returns:
        New file lines after applying diff
    """
    diff_lines = diff_text.splitlines(keepends=True)
    content = ''.join(original_lines)

    # Extract hunks (sections between @@ markers)
    old_lines = []
    new_lines_to_add = []
    in_hunk = False

    for line in diff_lines:
        stripped = line.rstrip('\r\n')

        # Skip headers
        if stripped.startswith('*** ') or stripped.startswith('--- ') or stripped.startswith('+++ '):
            continue

        # Start of hunk
        if stripped == '@@' or stripped.startswith('@@ '):
            # Process previous hunk if any
            if old_lines or new_lines_to_add:
                content = _replace_hunk(content, old_lines, new_lines_to_add)
                old_lines = []
                new_lines_to_add = []
            in_hunk = True
            continue

        if in_hunk:
            if stripped.startswith('-') and not stripped.startswith('---'):
                # Old line to find
                old_lines.append(stripped[1:])  # Remove - prefix
            elif stripped.startswith('+') and not stripped.startswith('+++'):
                # New line to insert
                new_lines_to_add.append(stripped[1:])  # Remove + prefix
            elif stripped.startswith('\\'):
                # "\ No newline at end of file" - ignore
                continue
            elif stripped:
                # Context line (no prefix) - treat as old and new
                old_lines.append(stripped)
                new_lines_to_add.append(stripped)

    # Process final hunk
    if old_lines or new_lines_to_add:
        content = _replace_hunk(content, old_lines, new_lines_to_add)

    # Convert back to lines
    result_lines = content.splitlines(keepends=True)
    # Ensure last line has newline
    if result_lines and not result_lines[-1].endswith('\n'):
        result_lines[-1] += '\n'

    return result_lines


def _normalize_whitespace(text: str) -> str:
    """Normalize all Unicode whitespace variants to regular ASCII space.

    v1.15.2: GPT-OSS and other models often output Unicode whitespace characters
    like NBSP (\\xa0), Narrow No-Break Space (\\u202f), etc. that don't match
    the regular spaces in the actual file content.

    Args:
        text: Text to normalize

    Returns:
        Text with all Unicode whitespace normalized to ASCII space
    """
    result = []
    for char in text:
        # Unicode category 'Zs' = Space Separator (includes NBSP, NNBSP, etc.)
        if unicodedata.category(char) == 'Zs':
            result.append(' ')
        else:
            result.append(char)
    return ''.join(result)


def _collapse_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters into single space.

    v1.15.2: For aggressive fuzzy matching when normal matching fails.

    Args:
        text: Text to normalize

    Returns:
        Text with collapsed whitespace
    """
    # First normalize Unicode whitespace, then collapse runs of spaces
    normalized = _normalize_whitespace(text)
    return re.sub(r'\s+', ' ', normalized).strip()


def _replace_hunk(content: str, old_lines: list, new_lines: list) -> str:
    """Replace old lines with new lines in content.

    v1.15.2: Enhanced with multi-level fuzzy matching to handle:
    - Unicode whitespace variants (NBSP, NNBSP, etc.)
    - Leading/trailing whitespace differences
    - Collapsed whitespace matching as last resort

    Args:
        content: File content as string
        old_lines: Lines to find (without newlines)
        new_lines: Lines to replace with (without newlines)

    Returns:
        Updated content
    """
    if not old_lines:
        # Nothing to find, can't replace
        return content

    # Build search pattern (join with newline)
    old_text = '\n'.join(old_lines)
    new_text = '\n'.join(new_lines)

    # Level 1: Try exact match first
    if old_text in content:
        return content.replace(old_text, new_text, 1)

    # Level 2: Try with different line ending styles
    old_text_crlf = '\r\n'.join(old_lines)
    if old_text_crlf in content:
        return content.replace(old_text_crlf, new_text.replace('\n', '\r\n'), 1)

    # Level 3: Normalize Unicode whitespace (NBSP, NNBSP → regular space)
    old_normalized = '\n'.join(_normalize_whitespace(line) for line in old_lines)
    content_normalized = _normalize_whitespace(content)
    if old_normalized in content_normalized:
        # Find position in normalized content, apply to original
        pos = content_normalized.index(old_normalized)
        # Find corresponding position in original by counting chars
        return content[:pos] + new_text + content[pos + len(old_normalized):]

    # Level 4: Strip leading/trailing whitespace + normalize Unicode
    content_lines = content.splitlines(keepends=True)
    old_stripped = '\n'.join(_normalize_whitespace(line.strip()) for line in old_lines)

    for i in range(len(content_lines) - len(old_lines) + 1):
        window = content_lines[i:i + len(old_lines)]
        window_stripped = '\n'.join(_normalize_whitespace(line.strip()) for line in window).rstrip('\n')
        if window_stripped == old_stripped:
            # Found match - replace
            before = ''.join(content_lines[:i])
            after = ''.join(content_lines[i + len(old_lines):])
            new_with_newlines = '\n'.join(new_lines) + '\n'
            return before + new_with_newlines + after

    # Level 5: Aggressive - collapse all whitespace and compare
    old_collapsed = '\n'.join(_collapse_whitespace(line) for line in old_lines)

    for i in range(len(content_lines) - len(old_lines) + 1):
        window = content_lines[i:i + len(old_lines)]
        window_collapsed = '\n'.join(_collapse_whitespace(line.rstrip('\r\n')) for line in window)
        if window_collapsed == old_collapsed:
            # Found match with collapsed whitespace - replace
            before = ''.join(content_lines[:i])
            after = ''.join(content_lines[i + len(old_lines):])
            new_with_newlines = '\n'.join(new_lines) + '\n'
            return before + new_with_newlines + after

    # No match found - return original
    return content


def register_tools(manager: ToolManagerProtocol, engine: ToolEngineProtocol):
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
    manager.register_tool(WriteFileTool(engine))

"""
CompletionProvider — client-agnostic autocomplete engine.

Extracts the completion logic from Rich TUI's `PPXAICompleter` into a
reusable module that all four clients (Rich, Textual, Web, VSCode) can
consume — either in-process (Rich, Textual) or via the `POST /complete`
server endpoint (Web, VSCode).

Three completion sources:

1. **Slash commands** — reads from `CommandFactory._registry` + aliases.
   Dynamic, never drifts, sorted alphabetically, hidden commands filtered.

2. **Path arguments** — for commands like `/attach`, `/cd`, `/ls`, `/show`
   etc. Shell-style directory traversal with per-command file/dir filters.

3. **@file references** — fuzzy-match files in the working directory for
   context injection.

Each source returns `CompletionItem` dicts with a stable JSON-serializable
schema so the server route can relay them unchanged to HTTP clients.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..commands.factory import CommandFactory


# Commands that accept path arguments, and what kinds of entries make
# sense to complete for each. Matches the table in PPXAICompleter.
_PATH_ARG_COMMANDS: Dict[str, Dict[str, bool]] = {
    "attach":  {"include_files": True,  "include_dirs": True},
    "show":    {"include_files": True,  "include_dirs": True},
    "preview": {"include_files": True,  "include_dirs": True},
    "cd":      {"include_files": False, "include_dirs": True},
    "tree":    {"include_files": False, "include_dirs": True},
    "ls":      {"include_files": True,  "include_dirs": True},
}

# Directories to skip in @file scanning
_IGNORE_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", "dist", "build", ".eggs", ".mypy_cache",
})

# Commands the factory doesn't own (special-cased in CommandHandler).
_BUILTIN_SPECIAL_COMMANDS = [
    {"text": "/quit", "description": "Exit the application", "kind": "command"},
    {"text": "/exit", "description": "Exit the application", "kind": "command"},
]


def complete(
    buffer: str,
    cursor: int = -1,
    *,
    working_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Compute completions for a given input buffer + cursor position.

    This is the single entry point for all completion requests. Clients
    call it directly (Rich, Textual) or via the `POST /complete` server
    route (Web, VSCode).

    Args:
        buffer: The full text the user has typed so far.
        cursor: Cursor position (0-indexed). -1 means end-of-buffer.
        working_dir: Working directory for path completions. Falls back
                     to `os.getcwd()` if not provided.

    Returns:
        List of completion item dicts, each with:
            text: str           — the completion text to insert
            display: str        — what to show in the dropdown
            description: str    — hover/meta text (e.g. "alias for /save")
            kind: str           — "command" | "alias" | "dir" | "file" | "file_ref"
            replace_start: int  — how many chars before cursor to replace
                                  (negative offset, e.g. -2 means replace
                                  the last 2 chars with `text`)
    """
    if cursor < 0:
        cursor = len(buffer)
    text = buffer[:cursor]
    wd = working_dir or os.getcwd()

    # @file reference completion — takes priority when @ is present
    at_pos = text.rfind("@")
    if at_pos >= 0:
        query = text[at_pos + 1:]
        return _complete_file_refs(query, wd, replace_len=len(text) - at_pos)

    # Slash command completion
    if text.startswith("/"):
        # Check if we're completing a path argument for a known command
        space_idx = text.find(" ")
        if space_idx > 0:
            typed_cmd = text[1:space_idx]
            spec = CommandFactory.get(typed_cmd)
            canonical = spec.name if spec else typed_cmd
            path_opts = _PATH_ARG_COMMANDS.get(canonical)
            if path_opts is not None:
                # Complete only the last whitespace-delimited token
                args_region = text[space_idx + 1:]
                _, token = _last_ws_token(args_region)
                return _complete_path(
                    token, wd,
                    include_files=path_opts["include_files"],
                    include_dirs=path_opts["include_dirs"],
                )

        # Regular command name completion
        return _complete_commands(text)

    return []


# =============================================================================
# Command name completion
# =============================================================================


def _complete_commands(prefix: str) -> List[Dict[str, Any]]:
    """Complete slash command names from CommandFactory."""
    CommandFactory._ensure_loaded()
    items: List[Dict[str, Any]] = []
    prefix_lower = prefix.lower()

    # Canonical commands (skip hidden)
    for name, spec in CommandFactory._registry.items():
        if spec.hidden:
            continue
        candidate = f"/{name}"
        if candidate.lower().startswith(prefix_lower):
            items.append({
                "text": candidate,
                "display": candidate,
                "description": spec.description,
                "kind": "command",
                "replace_start": -len(prefix),
            })

    # Aliases
    for alias, canonical in CommandFactory._aliases.items():
        spec = CommandFactory._registry.get(canonical)
        if not spec or spec.hidden:
            continue
        candidate = f"/{alias}"
        if candidate.lower().startswith(prefix_lower):
            items.append({
                "text": candidate,
                "display": candidate,
                "description": f"{spec.description} (alias for /{canonical})",
                "kind": "alias",
                "replace_start": -len(prefix),
            })

    # Builtins
    for bi in _BUILTIN_SPECIAL_COMMANDS:
        if bi["text"].startswith(prefix_lower):
            items.append({
                **bi,
                "replace_start": -len(prefix),
            })

    items.sort(key=lambda e: e["text"])
    return items


# =============================================================================
# Path argument completion
# =============================================================================


def _complete_path(
    partial: str,
    working_dir: str,
    include_files: bool = True,
    include_dirs: bool = True,
    max_entries: int = 200,
) -> List[Dict[str, Any]]:
    """Shell-style path completion for command arguments."""
    parent, leaf = _resolve_path_base(partial, working_dir)
    if not parent.exists() or not parent.is_dir():
        return []

    leaf_lower = leaf.lower()
    show_hidden = leaf.startswith(".")

    try:
        entries = sorted(
            parent.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
    except (OSError, PermissionError):
        return []

    items: List[Dict[str, Any]] = []
    for entry in entries:
        if len(items) >= max_entries:
            break
        name = entry.name
        if not show_hidden and name.startswith("."):
            continue
        if leaf_lower and not name.lower().startswith(leaf_lower):
            continue
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        if is_dir and not include_dirs:
            continue
        if not is_dir and not include_files:
            continue

        completion_text = name + ("/" if is_dir else "")
        items.append({
            "text": completion_text,
            "display": completion_text,
            "description": "dir" if is_dir else "file",
            "kind": "dir" if is_dir else "file",
            "replace_start": -len(leaf),
        })

    return items


def _resolve_path_base(partial: str, working_dir: str) -> tuple[Path, str]:
    """Split a user-typed partial path into (parent_dir, leaf_prefix)."""
    if not partial:
        return Path(working_dir), ""

    if partial.startswith("~"):
        expanded = str(Path(partial).expanduser())
    elif os.path.isabs(partial):
        expanded = partial
    else:
        expanded = os.path.join(working_dir, partial)

    if expanded.endswith(("/", os.sep)):
        return Path(expanded), ""

    parent_str, leaf = os.path.split(expanded)
    return Path(parent_str), leaf


def _last_ws_token(text: str) -> tuple[int, str]:
    """Return (start_index, token) for the last whitespace-delimited token."""
    if not text:
        return 0, ""
    idx = len(text)
    while idx > 0 and not text[idx - 1].isspace():
        idx -= 1
    return idx, text[idx:]


# =============================================================================
# @file reference completion
# =============================================================================


def _complete_file_refs(
    query: str,
    working_dir: str,
    replace_len: int,
    max_files: int = 100,
) -> List[Dict[str, Any]]:
    """Fuzzy-match files in the working directory for @file references."""
    root = Path(working_dir)
    files: List[tuple[str, str]] = []
    query_lower = query.lower()

    try:
        for path in root.rglob("*"):
            if len(files) >= max_files * 2:
                break
            try:
                if not path.is_file():
                    continue
                if any(ignored in path.parts for ignored in _IGNORE_DIRS):
                    continue
                rel_path = str(path.relative_to(root))
                files.append((path.name, rel_path))
            except (ValueError, OSError):
                pass
    except (PermissionError, OSError):
        pass

    items: List[Dict[str, Any]] = []
    for filename, filepath in files[:max_files]:
        if not query_lower or query_lower in filename.lower() or query_lower in filepath.lower():
            items.append({
                "text": f"@{filename}",
                "display": filename,
                "description": filepath,
                "kind": "file_ref",
                "replace_start": -replace_len,
            })

    return items


__all__ = ["complete"]

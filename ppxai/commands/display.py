"""
Display commands - file viewing and content display.

Commands for displaying file contents with syntax highlighting and data rendering.

v1.13.10: Migrated to Command Factory pattern
v1.15.0: Migrated to type-based renderer dispatch
"""

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, List

from .factory import CommandFactory, CommandSpec
from .protocol import CommandContext
from .results import (
    ResultStatus,
    CommandResult,
    ErrorResult,
    FileViewResult,
    TextResult,
)

if TYPE_CHECKING:
    from .handler import CommandHandler


# Helper function for file search (used by both old and new handlers)
def _search_files(handler: "CommandHandler", query: str, max_results: int = 10) -> List[Path]:
    """Search for files matching query in engine's working directory.

    Args:
        handler: CommandHandler instance
        query: Search query (filename or pattern)
        max_results: Maximum number of results to return

    Returns:
        List of matching Path objects
    """
    from ..common.logger import get_logger

    logger = get_logger("tui")

    # Remove @ prefix if present
    query = query.lstrip('@').strip()

    # Get search root from engine client (respects cd command)
    root = Path(handler.engine_client.get_working_dir())

    # Build search patterns
    query_lower = query.lower()

    # If query looks like a path, try exact match first
    if '/' in query or '\\' in query:
        direct_path = root / query
        if direct_path.exists() and direct_path.is_file():
            return [direct_path]

    # Extract filename parts for fuzzy matching
    parts = query_lower.replace('-', ' ').replace('_', ' ').split()

    matches = []
    try:
        # Walk directory tree (skip hidden dirs and common ignore patterns)
        ignore_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox', 'dist', 'build', '.eggs'}

        for path in root.rglob('*'):
            if path.is_file():
                # Skip files in ignored directories
                if any(ignored in path.parts for ignored in ignore_dirs):
                    continue

                # Check if filename matches
                filename_lower = path.name.lower()
                path_str_lower = str(path.relative_to(root)).lower()

                # Exact filename match
                if query_lower == filename_lower:
                    return [path]  # Exact match, return immediately

                # Check if all query parts are in the path
                if all(part in path_str_lower for part in parts):
                    matches.append(path)
                # Also check partial filename match
                elif query_lower in filename_lower:
                    matches.append(path)

                if len(matches) >= max_results * 2:  # Get more for sorting
                    break
    except PermissionError as e:
        logger.debug(f"Permission denied during file search: {e}")

    # Sort by relevance (shorter paths and exact filename matches first)
    def score(p):
        name = p.name.lower()
        # Prefer exact filename matches
        if query_lower == name:
            return (0, len(str(p)))
        if query_lower in name:
            return (1, len(str(p)))
        return (2, len(str(p)))

    matches.sort(key=score)
    return matches[:max_results]


# =============================================================================
# Type-Based Result Handlers (v1.15.0)
# =============================================================================

def handle_show(context: CommandContext, args: str) -> CommandResult:
    """Handle /show command - display file contents.

    Args:
        context: Command context providing access to engine client
        args: Filepath and optional flags

    Returns:
        FileViewResult for file contents, ErrorResult on failure
    """
    if not context.engine_client:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Engine client not available"
        )

    if not args.strip():
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Usage: /show <filepath> [--source|--rendered]",
            suggestions=[
                "/show README.md",
                "/show data.csv              # Rendered as table",
                "/show data.csv --source     # Raw CSV syntax",
                "/show config.json           # Rendered as tree",
                "/show @architecture         # Search for files"
            ]
        )

    # Parse flags
    show_source = '--source' in args or '--raw' in args
    show_rendered = '--rendered' in args
    interactive = '--interactive' in args or '-i' in args

    # Remove flags from args
    query = args
    for flag in ['--source', '--raw', '--rendered', '--interactive', '-i']:
        query = query.replace(flag, '')
    query = query.strip()

    # Extract @reference if present
    at_match = re.search(r'@([\w.\-/]+)', query)
    if at_match:
        query = at_match.group(1)

    # Get working directory
    working_dir = Path(context.engine_client.get_working_dir())

    # Check if it's a direct path first
    direct_path = Path(query).expanduser()
    if not direct_path.is_absolute():
        direct_path = working_dir / query

    if direct_path.exists() and direct_path.is_file():
        path = direct_path.resolve()
    else:
        # Note: For simplicity in v2, we don't implement file search
        # The renderer can delegate to the old handler if needed
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"File not found: {query}",
            suggestions=["Use exact path to file"]
        )

    if not path.is_file():
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Not a file: {query}"
        )

    try:
        content = path.read_text(encoding='utf-8')

        # Detect language from extension
        ext_to_lang = {
            '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
            '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml',
            '.md': 'markdown', '.html': 'html', '.css': 'css',
            '.sh': 'bash', '.bash': 'bash', '.zsh': 'bash',
            '.rs': 'rust', '.go': 'go', '.java': 'java',
            '.c': 'c', '.cpp': 'cpp', '.h': 'c', '.hpp': 'cpp',
            '.rb': 'ruby', '.php': 'php', '.sql': 'sql',
            '.xml': 'xml', '.toml': 'toml', '.ini': 'ini',
            '.csv': 'text', '.tsv': 'text', '.hcl': 'hcl', '.tf': 'hcl',
        }
        lang = ext_to_lang.get(path.suffix.lower(), 'text')

        # Return FileViewResult - renderer will handle syntax highlighting
        return FileViewResult(
            status=ResultStatus.SUCCESS,
            message=f"Displaying {path.name}",
            filepath=str(path),
            content=content,
            language=lang,
            metadata={
                "size_kb": path.stat().st_size / 1024,
                "lines": len(content.split('\n')),
                "show_source": show_source,
                "show_rendered": show_rendered,
                "interactive": interactive
            }
        )

    except UnicodeDecodeError:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Cannot display binary file: {query}"
        )
    except Exception as e:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Error reading file: {e}",
            error_details=str(e)
        )


# =============================================================================
# Command Registration
# =============================================================================

CommandFactory.register(CommandSpec(
    name="show",
    description="Display file contents with syntax highlighting",
    handler=handle_show,
    category="display",
    aliases=["cat"],
    usage="/show <filepath> [--source|--rendered|-i]"
))

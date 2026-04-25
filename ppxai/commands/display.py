"""
Display commands - file viewing and content display.

Commands for displaying file contents with syntax highlighting and data rendering.

v1.13.10: Migrated to Command Factory pattern
v1.15.0: Migrated to type-based renderer dispatch with file type detection
"""

import csv
import io
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .factory import CommandFactory, CommandSpec
from .protocol import CommandContext
from .results import (
    ResultStatus,
    CommandResult,
    ErrorResult,
    FileViewResult,
    ImageResult,
    MarkdownResult,
    NotificationResult,
    PreviewResult,
    SideEffectKind,
    TableResult,
    TextResult,
    TreeResult,
)
from ppxai.common.logger import get_logger
from ppxai.common.preview import resolve_preview_path
from ppxai.common.file_type import (
    FileType,
    detect_file_type,
    get_view_mode,
    get_language_for_extension,
)

# Helper function for file search (used by both old and new handlers)
def _search_files(handler: Any, query: str, max_results: int = 10) -> List[Path]:
    """Search for files matching query in engine's working directory.

    Args:
        handler: CommandHandler instance
        query: Search query (filename or pattern)
        max_results: Maximum number of results to return

    Returns:
        List of matching Path objects
    """
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
    """Handle /show command - display file contents with appropriate viewer.

    Returns the correct typed result based on file type detection:
    - JSON/YAML/TOML/HCL -> TreeResult (tree viewer)
    - CSV/TSV -> TableResult (table viewer)
    - Markdown -> MarkdownResult (markdown viewer)
    - Images -> ImageResult (image viewer)
    - Code/Text -> FileViewResult (code editor)

    Args:
        context: Command context providing access to engine client
        args: Filepath and optional flags (--source to force code view)

    Returns:
        Appropriate typed result for the file type, ErrorResult on failure
    """
    if not context.engine_client:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Engine client not available"
        )

    if not args.strip():
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Usage: /show <filepath> [--source]",
            suggestions=[
                "/show README.md           # Rendered markdown",
                "/show config.json         # Tree viewer",
                "/show data.csv            # Table viewer",
                "/show data.csv --source   # Raw source code view",
                "/show main.py             # Syntax highlighted code"
            ]
        )

    # Parse flags
    show_source = '--source' in args or '--raw' in args

    # Remove flags from args
    query = args
    for flag in ['--source', '--raw']:
        query = query.replace(flag, '')
    query = query.strip()

    # Extract @reference if present
    at_match = re.search(r'@([\w.\-/]+)', query)
    if at_match:
        query = at_match.group(1)

    # Get working directory
    working_dir = Path(context.engine_client.get_working_dir())

    # Resolve path
    direct_path = Path(query).expanduser()
    if not direct_path.is_absolute():
        direct_path = working_dir / query

    if not direct_path.exists():
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"File not found: {query}",
            suggestions=["Use exact path to file"]
        )

    path = direct_path.resolve()

    if not path.is_file():
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Not a file: {query}"
        )

    # Detect file type using magic + extension fallback
    file_type = detect_file_type(path)
    size_kb = path.stat().st_size / 1024

    # Handle images (binary) - return ImageResult
    if file_type == FileType.IMAGE:
        result = ImageResult(
            status=ResultStatus.SUCCESS,
            message=f"Displaying {path.name} ({size_kb:.1f} KB)",
            filepath=str(path),
            format=path.suffix.lower().lstrip('.'),
            metadata={"size_kb": size_kb}
        )
        result.add_side_effect(SideEffectKind.SHOW_IMAGE, filepath=str(path))
        return result

    # Handle PDFs - special-case before binary rejection
    if path.suffix.lower() == ".pdf":
        result = NotificationResult(
            status=ResultStatus.SUCCESS,
            message=f"Opening {path.name} ({size_kb:.1f} KB)",
            metadata={"size_kb": size_kb, "filepath": str(path)}
        )
        result.add_side_effect(SideEffectKind.SHOW_PDF, filepath=str(path))
        return result

    # Handle binary files
    if file_type == FileType.BINARY:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Cannot display binary file: {path.name}"
        )

    # Read text content
    try:
        content = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Cannot read file as text: {path.name}"
        )
    except Exception as e:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Error reading file: {e}",
            error_details=str(e)
        )

    lines = len(content.split('\n'))
    lang = get_language_for_extension(path.suffix) or 'text'

    # If --source flag, force code view regardless of file type
    if show_source:
        return FileViewResult(
            status=ResultStatus.SUCCESS,
            message=f"Displaying {path.name} ({size_kb:.1f} KB, {lines} lines) [source]",
            filepath=str(path),
            content=content,
            language=lang,
            read_only=True,
            metadata={"size_kb": size_kb, "lines": lines}
        )

    # Return typed result based on detected file type
    if file_type == FileType.MARKDOWN:
        return MarkdownResult(
            status=ResultStatus.SUCCESS,
            message=f"Displaying {path.name} ({size_kb:.1f} KB, {lines} lines)",
            filepath=str(path),
            content=content,
            metadata={"size_kb": size_kb, "lines": lines}
        )

    elif file_type in (FileType.JSON, FileType.YAML, FileType.TOML, FileType.HCL):
        # Parse structured data and return TreeResult
        parsed = _parse_structured_data(content, file_type)
        if parsed is not None:
            return TreeResult(
                status=ResultStatus.SUCCESS,
                message=f"Displaying {path.name} ({size_kb:.1f} KB)",
                root=_dict_to_tree(parsed, path.name),
                metadata={
                    "size_kb": size_kb,
                    "filepath": str(path),
                    "content": content,  # Keep original for source toggle
                    "language": lang
                }
            )
        else:
            # Parse failed, fall back to code view
            return FileViewResult(
                status=ResultStatus.WARNING,
                message=f"Displaying {path.name} (parse error, showing source)",
                filepath=str(path),
                content=content,
                language=lang,
                read_only=True,
                metadata={"size_kb": size_kb, "lines": lines}
            )

    elif file_type in (FileType.CSV, FileType.TSV):
        # Parse tabular data and return TableResult
        columns, rows = _parse_tabular_data(content, file_type)
        if columns and rows:
            return TableResult(
                status=ResultStatus.SUCCESS,
                message=f"Displaying {path.name} ({len(rows)} rows, {len(columns)} columns)",
                columns=columns,
                rows=rows,
                metadata={
                    "size_kb": size_kb,
                    "filepath": str(path),
                    "content": content,  # Keep original for source toggle
                }
            )
        else:
            # Parse failed, fall back to code view
            return FileViewResult(
                status=ResultStatus.WARNING,
                message=f"Displaying {path.name} (parse error, showing source)",
                filepath=str(path),
                content=content,
                language='text',
                read_only=True,
                metadata={"size_kb": size_kb, "lines": lines}
            )

    else:
        # Code/Text - return FileViewResult
        return FileViewResult(
            status=ResultStatus.SUCCESS,
            message=f"Displaying {path.name} ({size_kb:.1f} KB, {lines} lines)",
            filepath=str(path),
            content=content,
            language=lang,
            read_only=True,
            metadata={"size_kb": size_kb, "lines": lines}
        )


def _parse_structured_data(content: str, file_type: FileType) -> Optional[Dict[str, Any]]:
    """Parse structured data content into a dictionary.

    Args:
        content: File content
        file_type: Detected file type

    Returns:
        Parsed dictionary or None if parsing fails
    """
    try:
        if file_type == FileType.JSON:
            return json.loads(content)

        elif file_type == FileType.YAML:
            try:
                import yaml
                return yaml.safe_load(content)
            except ImportError:
                return None

        elif file_type == FileType.TOML:
            try:
                import tomllib
            except ImportError:
                try:
                    import tomli as tomllib
                except ImportError:
                    return None
            return tomllib.loads(content)

        elif file_type == FileType.HCL:
            try:
                import hcl2
                return hcl2.loads(content)
            except ImportError:
                return None

    except Exception:
        return None

    return None


def _dict_to_tree(data: Any, label: str = "root") -> Dict[str, Any]:
    """Convert a dictionary/list to tree structure for TreeResult.

    Args:
        data: Data to convert (dict, list, or scalar)
        label: Label for this node

    Returns:
        Tree node dictionary with 'label' and 'children' keys
    """
    if isinstance(data, dict):
        children = []
        for key, value in data.items():
            children.append(_dict_to_tree(value, str(key)))
        return {"label": label, "children": children}

    elif isinstance(data, list):
        children = []
        for i, item in enumerate(data):
            children.append(_dict_to_tree(item, f"[{i}]"))
        return {"label": f"{label} ({len(data)} items)", "children": children}

    else:
        # Scalar value
        value_str = str(data)
        if len(value_str) > 50:
            value_str = value_str[:47] + "..."
        return {"label": f"{label}: {value_str}", "children": []}


def _parse_tabular_data(content: str, file_type: FileType) -> tuple:
    """Parse tabular data content into columns and rows.

    Args:
        content: File content
        file_type: CSV or TSV

    Returns:
        Tuple of (columns, rows) or ([], []) if parsing fails
    """
    try:
        delimiter = '\t' if file_type == FileType.TSV else ','
        reader = csv.reader(io.StringIO(content), delimiter=delimiter)
        rows_list = list(reader)

        if not rows_list:
            return [], []

        # First row is headers
        columns = rows_list[0]
        rows = rows_list[1:]

        # Convert all values to strings
        rows = [[str(cell) for cell in row] for row in rows]

        return columns, rows

    except Exception:
        return [], []


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


# =============================================================================
# /preview Command — Live HTML Preview
# =============================================================================

def handle_preview(context: CommandContext, args: str) -> CommandResult:
    """Handle /preview command - open live-reloading HTML preview.

    Args:
        context: Command context providing access to engine client
        args: Filepath to HTML file, or "close" to stop preview

    Returns:
        PreviewResult on success, ErrorResult on failure
    """
    if not args.strip():
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Usage: /preview <file.html>",
            suggestions=[
                "/preview index.html     — Open live preview",
                "/preview close           — Close preview",
            ]
        )

    args_stripped = args.strip()

    # Handle /preview close
    if args_stripped.lower() == 'close':
        return NotificationResult(
            status=ResultStatus.INFO,
            message="Preview closed",
            metadata={"action": "close"}
        )

    # Resolve and validate HTML file path
    working_dir = context.engine_client.get_working_dir()

    try:
        path = resolve_preview_path(args_stripped, working_dir)
    except FileNotFoundError:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"File not found: {args_stripped}",
            suggestions=["Check the file path and try again"]
        )
    except ValueError as e:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=str(e),
            suggestions=[
                "Only .html and .htm files are supported",
                "Use /show for other file types"
            ]
        )

    result = PreviewResult(
        status=ResultStatus.SUCCESS,
        message=f"Preview: {path.name}",
        filepath=str(path),
        metadata={"working_dir": working_dir}
    )
    result.add_side_effect(SideEffectKind.OPEN_HTML_PREVIEW, filepath=str(path))
    return result


CommandFactory.register(CommandSpec(
    name="preview",
    description="Open live-reloading HTML preview",
    handler=handle_preview,
    category="display",
    usage="/preview <file.html>"
))

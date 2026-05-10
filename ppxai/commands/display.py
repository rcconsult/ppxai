"""
Display commands - file viewing and content display.

Commands for displaying file contents with syntax highlighting and data rendering.

v1.13.10: Migrated to Command Factory pattern
v1.15.0: Migrated to type-based renderer dispatch with file type detection
"""

import csv
import io
import json
import os
import re
import shlex
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def _resolve_at_query(
    search_term: str,
    working_dir: Path,
    *,
    command_to_resume: str,
) -> "CommandResult | str":
    """Resolve `@<search_term>` to a literal path or a quick-pick prompt.

    Returns:
        - absolute path string (single match) — caller continues
          handling as if the user had typed that literal path.
        - CommandResult (zero or many matches) — caller returns it
          directly; ErrorResult for zero, NotificationResult with
          PROMPT_QUICK_PICK side-effect for many.

    Per ADR Q3 (b): the quick-pick item's `value` is the literal
    absolute path. The client re-issues POST /command/<command_to_resume>
    with that path as args, and the second pass takes the non-@ branch.

    Match cap is 25 to keep the quick-pick payload small. If the user's
    intent is broader, they re-search with a more specific term.
    """
    matches: List[Path] = []
    try:
        for candidate in working_dir.rglob('*'):
            try:
                if candidate.is_file() and search_term.lower() in candidate.name.lower():
                    matches.append(candidate)
                    if len(matches) >= 25:
                        break
            except OSError:
                # Network paths can raise WinError 4350; skip
                continue
    except (PermissionError, OSError):
        pass

    if not matches:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"No files found matching: {search_term}",
            suggestions=["Try a different search term, or use a literal path"]
        )

    if len(matches) == 1:
        return str(matches[0].resolve())

    items = []
    for m in matches:
        try:
            label = str(m.resolve().relative_to(working_dir))
        except ValueError:
            label = str(m)
        items.append({
            "label": label,
            "value": str(m.resolve()),
        })
    result = NotificationResult(
        status=ResultStatus.INFO,
        message=f"{len(matches)} files match '{search_term}'",
    )
    result.add_side_effect(
        SideEffectKind.PROMPT_QUICK_PICK,
        title=f"Multiple files match '{search_term}' — pick one",
        items=items,
        command_to_resume=command_to_resume,
    )
    return result


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

    working_dir = Path(context.engine_client.get_working_dir())

    # `@<query>` triggers a fuzzy search across working_dir.
    # 0 matches → error; 1 match → use it; 2+ matches → prompt user
    # to pick. Per ADR Q3 (b): the picker's value is the literal
    # path, so re-issuing /show <picked-path> takes the direct branch.
    at_match = re.match(r'^@(\S+)\s*$', query)
    if at_match:
        search_term = at_match.group(1)
        result_or_path = _resolve_at_query(
            search_term, working_dir, command_to_resume="show"
        )
        if isinstance(result_or_path, CommandResult):
            return result_or_path
        query = result_or_path  # absolute path string

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
        result = FileViewResult(
            status=ResultStatus.SUCCESS,
            message=f"Displaying {path.name} ({size_kb:.1f} KB, {lines} lines) [source]",
            filepath=str(path),
            content=content,
            language=lang,
            read_only=True,
            metadata={"size_kb": size_kb, "lines": lines}
        )
        result.add_side_effect(SideEffectKind.OPEN_VIEWER, filepath=str(path))
        return result

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
            result = FileViewResult(
                status=ResultStatus.WARNING,
                message=f"Displaying {path.name} (parse error, showing source)",
                filepath=str(path),
                content=content,
                language=lang,
                read_only=True,
                metadata={"size_kb": size_kb, "lines": lines}
            )
            result.add_side_effect(SideEffectKind.OPEN_VIEWER, filepath=str(path))
            return result

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
            result = FileViewResult(
                status=ResultStatus.WARNING,
                message=f"Displaying {path.name} (parse error, showing source)",
                filepath=str(path),
                content=content,
                language='text',
                read_only=True,
                metadata={"size_kb": size_kb, "lines": lines}
            )
            result.add_side_effect(SideEffectKind.OPEN_VIEWER, filepath=str(path))
            return result

    else:
        # Code/Text - return FileViewResult
        result = FileViewResult(
            status=ResultStatus.SUCCESS,
            message=f"Displaying {path.name} ({size_kb:.1f} KB, {lines} lines)",
            filepath=str(path),
            content=content,
            language=lang,
            read_only=True,
            metadata={"size_kb": size_kb, "lines": lines}
        )
        result.add_side_effect(SideEffectKind.OPEN_VIEWER, filepath=str(path))
        return result


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

def _parse_preview_args(args: str) -> Tuple[Optional[CommandResult], dict]:
    """Parse `/preview <file> [--serve [cmd]] [--proxy port] [--port N]`.

    Returns (error_result, parsed) — exactly one of the two is non-None.
    `parsed` keys: filepath, mode (static|served|proxied), command, port.

    `--serve` may take an optional positional command (autodetected when
    omitted via the server's `_detect_command`). `--proxy <port>` connects
    to an already-running backend without launching one. `--port N` pins
    the expected port for `--serve` when port-from-stdout detection
    fails. Static mode (no flags) preserves the v1.15.4 behavior.
    """
    try:
        tokens = shlex.split(args.strip())
    except ValueError as e:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Could not parse arguments: {e}",
            suggestions=["Quote arguments containing spaces"]
        ), {}

    serve_flag = False
    serve_command: Optional[str] = None
    proxy_port: Optional[int] = None
    explicit_port: Optional[int] = None
    positional: List[str] = []

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--serve":
            serve_flag = True
            # Optional positional: the command. Skip if next token is a flag.
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                # Heuristic: a single bare token like 'index.html' is more
                # likely the filepath than a serve command. Treat the next
                # token as the command only when it looks shell-y (has a
                # space, or starts with python/node/uv/npm/etc.). Otherwise
                # leave it to autodetect.
                nxt = tokens[i + 1]
                looks_like_command = (
                    " " in nxt or
                    nxt.split()[0] in {"python", "python3", "uv", "npm", "node", "yarn", "pnpm", "deno", "bun", "go", "cargo", "ruby", "rails", "flask", "uvicorn", "gunicorn", "rye", "poetry"}
                )
                if looks_like_command:
                    serve_command = nxt
                    i += 2
                    continue
            i += 1
            continue
        if tok == "--proxy":
            if i + 1 >= len(tokens):
                return ErrorResult(
                    status=ResultStatus.ERROR,
                    message="--proxy requires a port number",
                    suggestions=["/preview index.html --proxy 8000"]
                ), {}
            try:
                proxy_port = int(tokens[i + 1])
            except ValueError:
                return ErrorResult(
                    status=ResultStatus.ERROR,
                    message=f"--proxy port must be an integer, got: {tokens[i + 1]}",
                ), {}
            i += 2
            continue
        if tok == "--port":
            if i + 1 >= len(tokens):
                return ErrorResult(
                    status=ResultStatus.ERROR,
                    message="--port requires a port number",
                ), {}
            try:
                explicit_port = int(tokens[i + 1])
            except ValueError:
                return ErrorResult(
                    status=ResultStatus.ERROR,
                    message=f"--port must be an integer, got: {tokens[i + 1]}",
                ), {}
            i += 2
            continue
        positional.append(tok)
        i += 1

    if not positional:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Missing filepath",
            suggestions=["/preview index.html"]
        ), {}
    if len(positional) > 1:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Expected one filepath, got: {positional}",
            suggestions=["Quote the filepath if it contains spaces"]
        ), {}

    if proxy_port is not None and serve_flag:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="--serve and --proxy are mutually exclusive",
        ), {}

    if proxy_port is not None:
        mode = "proxied"
    elif serve_flag:
        mode = "served"
    else:
        mode = "static"

    return None, {
        "filepath": positional[0],
        "mode": mode,
        "command": serve_command,
        "port": proxy_port if mode == "proxied" else explicit_port,
    }


def handle_preview(context: CommandContext, args: str) -> CommandResult:
    """Handle /preview command - open live-reloading HTML preview.

    Args:
        context: Command context providing access to engine client
        args: Filepath plus optional --serve/--proxy/--port flags, or
            "close" to stop preview.

    Returns:
        PreviewResult on success, ErrorResult on failure.

    v1.18.3: --serve and --proxy flags now reach the engine (they were
    advertised in the web `commands.js` `usage:` field but never parsed).
    The web/VSCode side-effects.js dispatcher reads the `mode` payload
    field and routes to `openServedPreview` / `openProxiedPreview`,
    which orchestrate POST /preview/serve and POST /preview/proxy/start.
    """
    if not args.strip():
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Usage: /preview <file.html> [--serve [\"cmd\"]] [--proxy port] [--port N]",
            suggestions=[
                "/preview index.html                       — static preview only",
                "/preview index.html --serve               — autostart backend (autodetect command, all clients)",
                "/preview index.html --serve \"python main.py\"  — autostart backend with explicit command",
                "/preview index.html --proxy 8000           — proxy to already-running backend",
                "/preview close                             — close static preview AND backend",
                "/preview logs [N]                          — show last N lines from the active backend log (default 100)",
            ]
        )

    if args.strip().lower() == 'close':
        return NotificationResult(
            status=ResultStatus.INFO,
            message="Preview closed",
            metadata={"action": "close"}
        )

    # v1.18.5: `/preview logs [N]` — show the active backend's log tail.
    # Thin wrapper over the read_preview_log tool so user-driven and
    # AI-driven inspection share one source of truth.
    logs_match = re.match(r"^logs(?:\s+(\d+))?\s*$", args.strip(), re.IGNORECASE)
    if logs_match:
        from ppxai.engine.tools.builtin.preview_log import read_preview_log
        n_lines = int(logs_match.group(1)) if logs_match.group(1) else 100
        log_text = read_preview_log(lines=n_lines)
        return TextResult(
            status=ResultStatus.SUCCESS,
            message=log_text,
            metadata={"action": "preview-logs", "lines_requested": n_lines},
        )

    err, parsed = _parse_preview_args(args)
    if err is not None:
        return err

    working_dir = context.engine_client.get_working_dir()

    try:
        path = resolve_preview_path(parsed["filepath"], working_dir)
    except FileNotFoundError:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"File not found: {parsed['filepath']}",
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

    mode = parsed["mode"]
    payload: Dict[str, Any] = {"filepath": str(path), "mode": mode}
    if mode == "served":
        payload["command"] = parsed["command"]  # may be None → autodetect
        payload["port"] = parsed["port"]
        message = f"Starting backend for {path.name}…"
    elif mode == "proxied":
        payload["port"] = parsed["port"]
        message = f"Proxying {path.name} to localhost:{parsed['port']}"
    else:
        message = f"Preview: {path.name}"

    result = PreviewResult(
        status=ResultStatus.SUCCESS,
        message=message,
        filepath=str(path),
        metadata={"working_dir": working_dir, "mode": mode}
    )
    result.add_side_effect(SideEffectKind.OPEN_HTML_PREVIEW, **payload)
    return result


CommandFactory.register(CommandSpec(
    name="preview",
    description="Open live-reloading HTML preview",
    handler=handle_preview,
    category="display",
    usage="/preview <file.html>"
))


# ============================================================================
# /edit — open file in editor (v1.18.1)
# ============================================================================


def handle_edit(context: CommandContext, args: str) -> CommandResult:
    """Handle /edit — open a file for editing.

    Syntax:
        /edit <file>[:line[:col]]
        /edit --create <file>[:line[:col]]    (create + edit, no prompt)

    Behavior:
        - If the file exists → emit `open_editor` side-effect.
        - If the file is missing → return a `prompt_quick_pick`
          asking the user to confirm creation. The "Create" choice's
          `value` is `--create <path>`, so the client re-issues
          POST /command/edit with that string and the second pass
          takes the create branch.
        - If the user passed `--create` directly, mkdir + touch and
          emit `open_editor`.

    Why this shape (per ADR Q3 — quick-pick resume protocol):
        Choices ARE the resolved args. No server-side continuation
        state; every POST is idempotent given the args.
    """
    if not context.engine_client:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Engine client not available"
        )

    raw = args.strip()
    if not raw:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Usage: /edit <filepath>[:line[:col]]",
            suggestions=[
                "/edit README.md",
                "/edit src/main.py:42      # Jump to line 42",
                "/edit config.json:10:5    # Line 10, column 5",
            ]
        )

    # Strip the --create flag and remember its presence.
    create_mode = False
    if raw.startswith("--create "):
        create_mode = True
        raw = raw[len("--create "):].strip()
    elif raw == "--create":
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Usage: /edit --create <filepath>"
        )

    # `@<query>` triggers a fuzzy file search across working_dir.
    # Mirrors /show: 0 → error; 1 → use it; 2+ → quick-pick. The
    # picker's value is the resolved literal path, so the client's
    # re-issue takes the direct branch on the second pass. Search
    # is incompatible with --create (you can't create a non-existent
    # match — the user's input was a search, not a path to create).
    at_match = re.match(r'^@(\S+)\s*$', raw)
    if at_match:
        if create_mode:
            return ErrorResult(
                status=ResultStatus.ERROR,
                message="@search and --create cannot be combined"
            )
        working_dir_for_search = Path(
            context.engine_client.get_working_dir() or os.getcwd()
        )
        result_or_path = _resolve_at_query(
            at_match.group(1),
            working_dir_for_search,
            command_to_resume="edit",
        )
        if isinstance(result_or_path, CommandResult):
            return result_or_path
        raw = result_or_path  # absolute path — fall through to parse

    # Parse `path[:line[:col]]`. `rsplit(':', 2)` handles Windows
    # drive letters cleanly: "C:\foo.py:42:5" splits to
    # ["C:\\foo.py", "42", "5"], drive colon stays with the path.
    line = None
    col = None
    parts = raw.rsplit(':', 2)
    if len(parts) >= 2 and parts[-1].isdigit():
        if len(parts) == 3 and parts[-2].isdigit():
            path_str = parts[0]
            line = int(parts[-2])
            col = int(parts[-1])
        else:
            path_str = ':'.join(parts[:-1])
            line = int(parts[-1])
    else:
        path_str = raw

    # Resolve relative to engine's working dir (canonical).
    working_dir = context.engine_client.get_working_dir() or os.getcwd()
    candidate = Path(path_str).expanduser()
    if not candidate.is_absolute():
        candidate = Path(working_dir) / path_str
    candidate = candidate.resolve()

    if candidate.exists():
        if not candidate.is_file():
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=f"Not a file: {path_str}",
                suggestions=["Pick a regular file, not a directory"]
            )
        # Existing file — emit open_editor.
        result = FileViewResult(
            status=ResultStatus.SUCCESS,
            message=f"Editing {candidate.name}",
            filepath=str(candidate),
            content="",  # client fetches via /files/read
            language=None,
            line_highlight=line,
            col_highlight=col,
            read_only=False,
        )
        payload = {"filepath": str(candidate)}
        if line is not None:
            payload["line"] = line
        if col is not None:
            payload["column"] = col
        result.add_side_effect(SideEffectKind.OPEN_EDITOR, **payload)
        return result

    # Missing file path — two branches.
    if create_mode:
        # User already confirmed (or was passed --create directly).
        # mkdir + touch, then emit open_editor.
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.touch()
        except OSError as exc:
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=f"Could not create file: {exc}",
                error_details=str(exc),
            )
        result = FileViewResult(
            status=ResultStatus.SUCCESS,
            message=f"Created and editing {candidate.name}",
            filepath=str(candidate),
            content="",
            language=None,
            line_highlight=line,
            col_highlight=col,
            read_only=False,
        )
        payload = {"filepath": str(candidate)}
        if line is not None:
            payload["line"] = line
        if col is not None:
            payload["column"] = col
        result.add_side_effect(SideEffectKind.OPEN_EDITOR, **payload)
        return result

    # Missing file, no --create flag → prompt user to confirm creation.
    # Per ADR Q3 (b): the quick-pick choice's value IS the next args
    # to re-issue. "Create" maps to "--create <original_args>",
    # "Cancel" maps to a no-op flag the handler ignores cleanly.
    items = [
        {
            "label": f"Create new file: {path_str}",
            "value": f"--create {raw}",
        },
        {
            "label": "Cancel",
            "value": "--cancelled",  # handler short-circuits below
        },
    ]
    result = NotificationResult(
        status=ResultStatus.INFO,
        message=f"File not found: {path_str}",
    )
    result.add_side_effect(
        SideEffectKind.PROMPT_QUICK_PICK,
        title=f"Create new file '{path_str}'?",
        items=items,
        command_to_resume="edit",
    )
    return result


CommandFactory.register(CommandSpec(
    name="edit",
    description="Open file in editor (creates if missing)",
    handler=handle_edit,
    category="display",
    usage="/edit <file>[:line[:col]]"
))

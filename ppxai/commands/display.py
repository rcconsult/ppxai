"""
Display commands - file viewing and content display.

Commands for displaying file contents with syntax highlighting and data rendering.

v1.13.10: Migrated to Command Factory pattern
"""

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, List

from .factory import CommandFactory, CommandSpec

if TYPE_CHECKING:
    from .handler import CommandHandler


def handle_show(handler: "CommandHandler", args: str) -> None:
    """Handle /show command to display file contents.

    Displays file contents locally without LLM call.
    Supports data format rendering for CSV, TSV, JSON, YAML, TOML, HCL files.

    Flags:
        --source, --raw: Force source/syntax view (skip data rendering)
        --rendered: Force rendered view (default for data files)
        --interactive, -i: Interactive mode with pagination/toggle (data files)

    Args:
        handler: CommandHandler instance providing context
        args: Filepath and optional flags
    """
    from rich.syntax import Syntax
    from ..ui import console
    from ..common.logger import get_logger

    logger = get_logger("tui")
    start_time = time.time()

    if not args.strip():
        console.print("[red]Usage: /show <filepath> [--source|--rendered][/red]")
        console.print("[dim]Examples:[/dim]")
        console.print("[dim]  /show README.md[/dim]")
        console.print("[dim]  /show data.csv              # Rendered as table[/dim]")
        console.print("[dim]  /show data.csv --source     # Raw CSV syntax[/dim]")
        console.print("[dim]  /show config.json           # Rendered as tree[/dim]")
        console.print("[dim]  /show @architecture         # Search for files[/dim]\n")
        return

    # Parse flags
    show_source = '--source' in args or '--raw' in args
    show_rendered = '--rendered' in args
    interactive = '--interactive' in args or '-i' in args

    # Remove flags from args
    query = args
    for flag in ['--source', '--raw', '--rendered', '--interactive', '-i']:
        query = query.replace(flag, '')
    query = query.strip()

    # Extract @reference if present (ignore trailing words like "file", "in docs", etc.)
    at_match = re.search(r'@([\w.\-/]+)', query)
    if at_match:
        query = at_match.group(1)  # Use just the reference without @

    # Get working directory from engine client (respects cd command)
    working_dir = Path(handler.engine_client.get_working_dir())

    # Check if it's a direct path first
    direct_path = Path(query).expanduser()
    if not direct_path.is_absolute():
        direct_path = working_dir / query

    if direct_path.exists() and direct_path.is_file():
        path = direct_path.resolve()
    else:
        # Search for files
        console.print(f"[dim]Searching for '{query}'...[/dim]")
        matches = _search_files(handler, query)

        if not matches:
            console.print(f"[red]No files found matching: {query}[/red]\n")
            return

        if len(matches) == 1:
            path = matches[0]
            console.print(f"[dim]Found: {path.relative_to(working_dir)}[/dim]\n")
        else:
            # Multiple matches - let user choose
            console.print(f"\n[yellow]Multiple files found ({len(matches)}):[/yellow]")
            for i, match in enumerate(matches, 1):
                rel_path = match.relative_to(working_dir)
                console.print(f"  [cyan]{i}[/cyan]. {rel_path}")

            console.print("\n[dim]Use exact path: /show <path>[/dim]\n")
            return

    if not path.is_file():
        console.print(f"[red]Not a file: {query}[/red]\n")
        return

    try:
        content = path.read_text(encoding='utf-8')
        lines = content.split('\n')

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

        # Show file info
        size_kb = path.stat().st_size / 1024
        console.print(f"\n[bold cyan]{path.name}[/bold cyan] [dim]({size_kb:.1f} KB, {len(lines)} lines)[/dim]\n")

        # Check for data formats
        from ..data import (
            detect_format, is_data_format, detect_delimiter,
            parse_csv, parse_structured,
            render_table_tui, render_tree_tui,
            InteractiveTableViewer, InteractiveTreeViewer,
            TABULAR_FORMATS, STRUCTURED_FORMATS,
        )

        data_format = detect_format(str(path), content)
        is_data_file = data_format is not None

        # Determine view mode
        # --source forces source view, --rendered forces data view
        # Default: data view for data files, source view for others
        use_data_view = is_data_file and not show_source

        if use_data_view and data_format in TABULAR_FORMATS:
            # CSV/TSV - render as table
            delimiter = '\t' if data_format == 'tsv' else detect_delimiter(content)
            data = parse_csv(content, delimiter=delimiter)

            if interactive:
                # Interactive mode with pagination
                viewer = InteractiveTableViewer(data, console, str(path), content)
                viewer.run()
            else:
                # Non-interactive - just show the table
                render_table_tui(data, console, title=path.name)

        elif use_data_view and data_format in STRUCTURED_FORMATS:
            # JSON/YAML/TOML/HCL - render as tree
            try:
                tree = parse_structured(content, data_format, root_key=path.name)
                if interactive:
                    viewer = InteractiveTreeViewer(tree, console, str(path), content)
                    viewer.run()
                else:
                    render_tree_tui(tree, console, title=path.name)
            except ImportError as e:
                # Missing parser dependency - fall back to syntax view
                console.print(f"[yellow]Note: {e}[/yellow]")
                console.print("[dim]Falling back to syntax view[/dim]\n")
                syntax = Syntax(content, lang, theme="monokai", line_numbers=True)
                console.print(syntax)
            except Exception as e:
                # Parse error - fall back to syntax view
                console.print(f"[yellow]Parse error: {e}[/yellow]")
                console.print("[dim]Falling back to syntax view[/dim]\n")
                syntax = Syntax(content, lang, theme="monokai", line_numbers=True)
                console.print(syntax)

        elif path.suffix.lower() in ['.md', '.markdown']:
            # For markdown files, render them (including tables) instead of syntax highlighting
            from ..markdown_tables import render_markdown_with_tables
            # Pass the file's parent directory for resolving relative links
            render_markdown_with_tables(content, console, working_dir=str(path.parent))
        else:
            # Display with syntax highlighting (no truncation for local viewing)
            syntax = Syntax(content, lang, theme="monokai", line_numbers=True)
            console.print(syntax)

        # Show timing
        elapsed = time.time() - start_time
        console.print(f"\n[dim]({elapsed:.2f}s)[/dim]\n")

    except UnicodeDecodeError:
        console.print(f"[red]Cannot display binary file: {query}[/red]\n")
    except Exception as e:
        console.print(f"[red]Error reading file: {e}[/red]\n")


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

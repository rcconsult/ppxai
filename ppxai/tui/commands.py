"""
ppxaide local commands - commands that work without AI.

Implements file display, editing, navigation, and session management
commands for the Textual-based TUI.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from .app import PPXAIDEApp


def parse_file_location(args: str) -> Tuple[str, Optional[int], Optional[int]]:
    """Parse file path with optional line:col suffix.

    Args:
        args: File path, optionally with :line or :line:col

    Returns:
        Tuple of (path, line, col) where line/col may be None
    """
    args = args.strip()
    line = None
    col = None

    # Check for :line:col or :line suffix
    if ':' in args:
        parts = args.rsplit(':', 2)
        if len(parts) >= 2 and parts[-1].isdigit():
            if len(parts) == 3 and parts[-2].isdigit():
                # path:line:col
                path = parts[0]
                line = int(parts[-2])
                col = int(parts[-1])
            else:
                # path:line
                path = ':'.join(parts[:-1])
                line = int(parts[-1])
        else:
            path = args
    else:
        path = args

    return path, line, col


def resolve_path(path_str: str, working_dir: str = None) -> Optional[Path]:
    """Resolve a path relative to working directory.

    Args:
        path_str: Path string (absolute or relative)
        working_dir: Working directory for relative paths

    Returns:
        Resolved Path, or None if not found
    """
    path = Path(path_str).expanduser()

    if not path.is_absolute():
        base = Path(working_dir) if working_dir else Path.cwd()
        path = base / path_str

    path = path.resolve()
    return path if path.exists() else None


async def cmd_show(app: "PPXAIDEApp", args: str) -> None:
    """Handle /show command - display file contents.

    For code files: syntax-highlighted view
    For data files (JSON/YAML/TOML): TreeViewer widget
    For CSV/TSV: table display

    Args:
        app: PPXAIDEApp instance
        args: File path
    """
    from .widgets.chat_view import ChatView

    chat_view = app.query_one("#chat-view", ChatView)

    if not args.strip():
        chat_view.add_system_message(
            "[bold]Usage:[/bold] /show <filepath>\n\n"
            "[dim]Examples:[/dim]\n"
            "  /show README.md\n"
            "  /show config.json      [dim]# Tree view[/dim]\n"
            "  /show data.yaml        [dim]# Tree view[/dim]\n"
            "  /show src/main.py:42   [dim]# Jump to line[/dim]"
        )
        return

    path_str, line, col = parse_file_location(args)
    path = resolve_path(path_str, app._working_dir)

    if not path:
        chat_view.add_system_message(f"[red]File not found: {path_str}[/red]")
        return

    if not path.is_file():
        chat_view.add_system_message(f"[red]Not a file: {path_str}[/red]")
        return

    try:
        content = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        chat_view.add_system_message(f"[red]Cannot read binary file: {path.name}[/red]")
        return
    except Exception as e:
        chat_view.add_system_message(f"[red]Error reading file: {e}[/red]")
        return

    # Detect file type
    ext = path.suffix.lower()
    data_formats = {'.json', '.yaml', '.yml', '.toml'}
    tabular_formats = {'.csv', '.tsv'}

    size_kb = path.stat().st_size / 1024
    lines = content.count('\n') + 1

    if ext in data_formats:
        # Use TreeViewer for structured data
        from .screens.viewer import ViewerScreen
        viewer = ViewerScreen(path, content, "tree")
        app.push_screen(viewer)
        chat_view.add_system_message(
            f"[dim]Opened {path.name} ({size_kb:.1f} KB) in tree viewer. Press Escape to close.[/dim]"
        )

    elif ext in tabular_formats:
        # Show table info (full table viewer coming later)
        chat_view.add_system_message(
            f"[bold cyan]{path.name}[/bold cyan] [dim]({size_kb:.1f} KB, {lines} lines)[/dim]\n\n"
            f"[dim]Tabular data preview coming soon. Use /edit to view raw content.[/dim]"
        )

    else:
        # Code/text file - open in viewer
        from .screens.viewer import ViewerScreen
        viewer = ViewerScreen(path, content, "code", line=line)
        app.push_screen(viewer)
        chat_view.add_system_message(
            f"[dim]Opened {path.name} ({size_kb:.1f} KB, {lines} lines). Press Escape to close.[/dim]"
        )


async def cmd_edit(app: "PPXAIDEApp", args: str) -> None:
    """Handle /edit command - edit file with CodeEditor.

    Opens a full-screen editor with syntax highlighting.
    Supports :line:col suffix to jump to location.

    Args:
        app: PPXAIDEApp instance
        args: File path with optional :line:col
    """
    from .widgets.chat_view import ChatView

    chat_view = app.query_one("#chat-view", ChatView)

    if not args.strip():
        chat_view.add_system_message(
            "[bold]Usage:[/bold] /edit <filepath>[:line[:col]]\n\n"
            "[dim]Examples:[/dim]\n"
            "  /edit README.md\n"
            "  /edit src/main.py:42      [dim]# Jump to line 42[/dim]\n"
            "  /edit config.json:10:5    [dim]# Line 10, column 5[/dim]\n\n"
            "[dim]In editor:[/dim]\n"
            "  Ctrl+S  - Save\n"
            "  Escape  - Close (prompts if unsaved)"
        )
        return

    path_str, line, col = parse_file_location(args)
    path = resolve_path(path_str, app._working_dir)

    # For new files, create them
    if not path:
        new_path = Path(path_str).expanduser()
        if not new_path.is_absolute():
            base = Path(app._working_dir) if app._working_dir else Path.cwd()
            new_path = base / path_str
        new_path = new_path.resolve()

        # Create parent directories if needed
        new_path.parent.mkdir(parents=True, exist_ok=True)
        path = new_path
        content = ""
        chat_view.add_system_message(f"[dim]Creating new file: {path.name}[/dim]")
    else:
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            chat_view.add_system_message(f"[red]Cannot edit binary file: {path.name}[/red]")
            return
        except Exception as e:
            chat_view.add_system_message(f"[red]Error reading file: {e}[/red]")
            return

    # Open editor screen
    from .screens.editor import EditorScreen
    editor = EditorScreen(path, content, line=line, col=col)
    app.push_screen(editor)


async def cmd_cd(app: "PPXAIDEApp", args: str) -> None:
    """Handle /cd command - change working directory.

    Args:
        app: PPXAIDEApp instance
        args: Directory path
    """
    from .widgets.chat_view import ChatView

    chat_view = app.query_one("#chat-view", ChatView)

    if not args.strip():
        # Show current directory
        await cmd_pwd(app, "")
        return

    target = Path(args.strip()).expanduser()
    if not target.is_absolute():
        base = Path(app._working_dir) if app._working_dir else Path.cwd()
        target = base / args.strip()

    target = target.resolve()

    if not target.exists():
        chat_view.add_system_message(f"[red]Directory not found: {args}[/red]")
        return

    if not target.is_dir():
        chat_view.add_system_message(f"[red]Not a directory: {args}[/red]")
        return

    app._working_dir = str(target)
    chat_view.add_system_message(f"[green]Working directory:[/green] {target}")


async def cmd_pwd(app: "PPXAIDEApp", args: str) -> None:
    """Handle /pwd command - show working directory.

    Args:
        app: PPXAIDEApp instance
        args: Unused
    """
    from .widgets.chat_view import ChatView

    chat_view = app.query_one("#chat-view", ChatView)
    cwd = app._working_dir or os.getcwd()
    chat_view.add_system_message(f"[cyan]Working directory:[/cyan] {cwd}")


async def cmd_status(app: "PPXAIDEApp", args: str) -> None:
    """Handle /status command - show status information.

    Args:
        app: PPXAIDEApp instance
        args: Unused
    """
    from .widgets.chat_view import ChatView

    chat_view = app.query_one("#chat-view", ChatView)

    # Gather status info
    cwd = app._working_dir or os.getcwd()
    theme = app.theme

    status_text = f"""[bold cyan]━━━ ppxaide Status ━━━[/bold cyan]

  [cyan]Provider:[/cyan] {app._provider}
  [cyan]Model:[/cyan] {app._model}
  [cyan]Tools:[/cyan] {"[green]enabled[/green]" if app._tools_enabled else "[dim]disabled[/dim]"}
  [cyan]Working Dir:[/cyan] {cwd}
  [cyan]Theme:[/cyan] {theme}
  [cyan]Engine:[/cyan] {"[green]connected[/green]" if app._engine_client else "[dim]not connected[/dim]"}
"""
    chat_view.add_system_message(status_text)

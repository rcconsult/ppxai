"""
ppxaide local commands - commands that work without AI.

Implements file display, editing, navigation, and session management
commands for the Textual-based TUI.
"""

from pathlib import Path
from typing import Any

from .widgets.chat_view import ChatView


def parse_file_location(args: str) -> tuple[str, int | None, int | None]:
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


def resolve_path(path_str: str, working_dir: str = None) -> Path | None:
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


async def cmd_edit(app: Any, args: str) -> None:
    """Handle /edit command - edit file with CodeEditor.

    Opens a full-screen editor with syntax highlighting.
    Supports :line:col suffix to jump to location.

    Args:
        app: PPXAIDEApp instance
        args: File path with optional :line:col
    """
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

    # Open in side panel with edit mode
    await app.show_file_in_panel(path, content, mode="code", line=line, col=col, read_only=False)
    chat_view.add_system_message(
        f"[dim]Editing {path.name}. Ctrl+S to save, Ctrl+W to close.[/dim]"
    )



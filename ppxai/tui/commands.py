"""
ppxaide local commands - commands that work without AI.

Implements file display, editing, navigation, and session management
commands for the Textual-based TUI.
"""

import os
from pathlib import Path
from typing import Any

from .terminal import (
    can_display_images,
    detect_image_protocol,
    get_capabilities,
    get_image_protocol_name,
)
from .widgets.chat_view import ChatView
from .widgets.image_handlers import _IMAGEVIEW_AVAILABLE, ImageHandlerFactory, _TextualImage


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


async def cmd_show(app: Any, args: str) -> None:
    """Handle /show command - display file contents.

    For code files: syntax-highlighted view
    For data files (JSON/YAML/TOML): TreeViewer widget
    For CSV/TSV: table display

    Args:
        app: PPXAIDEApp instance
        args: File path
    """
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

    # Detect file type early for binary files
    ext = path.suffix.lower()
    image_formats = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico', '.tiff', '.tif'}
    size_kb = path.stat().st_size / 1024

    # Handle image files first (before trying to read as text)
    if ext in image_formats:
        if can_display_images():
            await app.show_file_in_panel(path, "", mode="image", read_only=True)
            chat_view.add_system_message(
                f"[dim]Opened {path.name} ({size_kb:.1f} KB) via {get_image_protocol_name()}. Ctrl+W to close.[/dim]"
            )
        else:
            chat_view.add_system_message(
                f"[yellow]Image: {path.name} ({size_kb:.1f} KB)[/yellow]\n"
                "[dim]Terminal does not support image display (no iTerm2/Kitty/Sixel)[/dim]"
            )
        return

    # Read text content
    try:
        content = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        chat_view.add_system_message(f"[red]Cannot read binary file: {path.name}[/red]")
        return
    except Exception as e:
        chat_view.add_system_message(f"[red]Error reading file: {e}[/red]")
        return

    # Detect text file type
    data_formats = {'.json', '.yaml', '.yml', '.toml'}
    tabular_formats = {'.csv', '.tsv'}
    lines = content.count('\n') + 1

    if ext in data_formats:
        # Use TreeViewer for structured data in side panel
        await app.show_file_in_panel(path, content, mode="tree", read_only=True)
        chat_view.add_system_message(
            f"[dim]Opened {path.name} ({size_kb:.1f} KB) in tree viewer. Ctrl+W to close.[/dim]"
        )

    elif ext in tabular_formats:
        # Use TableViewer for tabular data (CSV/TSV) in side panel
        await app.show_file_in_panel(path, content, mode="table", read_only=True)
        chat_view.add_system_message(
            f"[dim]Opened {path.name} ({size_kb:.1f} KB, {lines} lines) in table viewer. V toggle view, Ctrl+W to close.[/dim]"
        )

    elif ext in ('.md', '.markdown'):
        # Markdown file - render it in side panel
        await app.show_file_in_panel(path, content, mode="markdown", line=line, read_only=True)
        chat_view.add_system_message(
            f"[dim]Opened {path.name} ({size_kb:.1f} KB, {lines} lines) in markdown view. Ctrl+W to close.[/dim]"
        )

    else:
        # Code/text file - open in side panel with syntax highlighting
        await app.show_file_in_panel(path, content, mode="code", line=line, read_only=True)
        chat_view.add_system_message(
            f"[dim]Opened {path.name} ({size_kb:.1f} KB, {lines} lines). Ctrl+W to close.[/dim]"
        )


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


async def cmd_cd(app: Any, args: str) -> None:
    """Handle /cd command - change working directory.

    Args:
        app: PPXAIDEApp instance
        args: Directory path
    """
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


async def cmd_pwd(app: Any, args: str) -> None:
    """Handle /pwd command - show working directory.

    Args:
        app: PPXAIDEApp instance
        args: Unused
    """
    chat_view = app.query_one("#chat-view", ChatView)
    cwd = app._working_dir or os.getcwd()
    chat_view.add_system_message(f"[cyan]Working directory:[/cyan] {cwd}")


async def cmd_debug(app: Any, args: str) -> None:
    """Handle /debug command - show image viewer debug information.

    Args:
        app: PPXAIDEApp instance
        args: Unused
    """
    chat_view = app.query_one("#chat-view", ChatView)

    # Library information
    lib_status = "[green]installed[/green]" if _IMAGEVIEW_AVAILABLE else "[red]NOT installed[/red]"
    lib_class = f"[dim]{_TextualImage}[/dim]" if _IMAGEVIEW_AVAILABLE else "[dim]N/A[/dim]"

    # Terminal capabilities
    caps = get_capabilities()
    terminal_supports = "[green]YES[/green]" if can_display_images() else "[red]NO[/red]"
    protocol = get_image_protocol_name()
    protocol_display = f"[green]{protocol}[/green]" if protocol != "none" else f"[red]{protocol}[/red]"

    # Full mode availability
    full_mode = ImageHandlerFactory.is_full_mode_available()
    full_mode_status = "[green]AVAILABLE[/green]" if full_mode else "[red]NOT AVAILABLE[/red]"

    # Environment variables
    term_program = os.environ.get("TERM_PROGRAM", "[dim]not set[/dim]")
    term = os.environ.get("TERM", "[dim]not set[/dim]")
    colorterm = os.environ.get("COLORTERM", "[dim]not set[/dim]")
    kitty_window = os.environ.get("KITTY_WINDOW_ID", "[dim]not set[/dim]")
    tmux = os.environ.get("TMUX", "[dim]not set[/dim]")

    debug_info = f"""[bold cyan]━━━ Image Viewer Debug Information ━━━[/bold cyan]

[bold]Library Status:[/bold]
  textual-image: {lib_status}
  Class: {lib_class}

[bold]Terminal Capabilities:[/bold]
  Terminal Name: [cyan]{caps.name}[/cyan]
  Supports Images: {terminal_supports}
  Image Protocol: {protocol_display}
  Protocol Enum: [dim]{detect_image_protocol()}[/dim]
  True Color: {"[green]yes[/green]" if caps.true_color else "[dim]no[/dim]"}
  OSC Hyperlinks: {"[green]yes[/green]" if caps.osc_hyperlinks else "[dim]no[/dim]"}

[bold]Handler Factory:[/bold]
  Full Mode Available: {full_mode_status}
  Decision: {"[green]Will use FullImageHandler[/green]" if full_mode else "[yellow]Will use FallbackHandler[/yellow]"}

[bold]Environment Variables:[/bold]
  TERM_PROGRAM: [cyan]{term_program}[/cyan]
  TERM: [cyan]{term}[/cyan]
  COLORTERM: [cyan]{colorterm}[/cyan]
  KITTY_WINDOW_ID: [cyan]{kitty_window}[/cyan]
  TMUX: [cyan]{tmux}[/cyan]

[bold]Expected Behavior:[/bold]"""

    if full_mode:
        debug_info += """
  ✓ Images will render with zoom/pan controls
  ✓ Using textual-imageview library
  ✓ iTerm2/Kitty/Sixel protocols supported
"""
    elif _IMAGEVIEW_AVAILABLE and not can_display_images():
        debug_info += f"""
  ⚠ Images will show as file info (fallback)
  ⚠ Reason: Terminal doesn't support images
  ⚠ Protocol detected: {protocol}
  💡 Use iTerm2, Kitty, or WezTerm for image rendering
"""
    elif not _IMAGEVIEW_AVAILABLE:
        debug_info += """
  ⚠ Images will show as file info (fallback)
  ⚠ Reason: textual-imageview not installed
  💡 Install with: pip install ppxai[tui]
"""
    else:
        debug_info += """
  ⚠ Images will show as file info (fallback)
  ⚠ Unknown reason - check logs
"""

    chat_view.add_system_message(debug_info)


async def cmd_status(app: Any, args: str) -> None:
    """Handle /status command - show status information.

    Args:
        app: PPXAIDEApp instance
        args: Unused
    """
    chat_view = app.query_one("#chat-view", ChatView)

    # Gather status info
    cwd = app._working_dir or os.getcwd()
    theme = app.theme

    # Terminal capabilities
    caps = get_capabilities()
    image_proto = get_image_protocol_name()

    # Format image protocol with proper markup
    image_status = f"[green]{image_proto}[/green]" if image_proto != "none" else "[dim]none[/dim]"

    status_text = f"""[bold cyan]━━━ ppxaide Status ━━━[/bold cyan]

  [cyan]Provider:[/cyan] {app._provider}
  [cyan]Model:[/cyan] {app._model}
  [cyan]Tools:[/cyan] {"[green]enabled[/green]" if app._tools_enabled else "[dim]disabled[/dim]"}
  [cyan]Working Dir:[/cyan] {cwd}
  [cyan]Theme:[/cyan] {theme}
  [cyan]Engine:[/cyan] {"[green]connected[/green]" if app._engine_client else "[dim]not connected[/dim]"}

[bold cyan]━━━ Terminal ━━━[/bold cyan]

  [cyan]Terminal:[/cyan] {caps.name}
  [cyan]True Color:[/cyan] {"[green]yes[/green]" if caps.true_color else "[dim]no[/dim]"}
  [cyan]Images:[/cyan] {image_status}
  [cyan]Hyperlinks:[/cyan] {"[green]yes[/green]" if caps.osc_hyperlinks else "[dim]no[/dim]"}
"""
    chat_view.add_system_message(status_text)

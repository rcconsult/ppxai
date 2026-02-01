"""
Rich Console Renderer - Type-Based Dispatch for Rich TUI

This module provides Rich console rendering for all 17 result types.
Each result type has a registered renderer function.

Architecture:
- RichRenderer subclasses Renderer
- Each result type gets @RichRenderer.register() decorator
- Dispatch is mechanical: RichRenderer.render(result) → type lookup → call

v1.15.0: Type-based renderer dispatch refactoring
"""

from rich.console import Console
from rich.table import Table
from rich.tree import Tree
from rich.syntax import Syntax
from rich.panel import Panel
from rich.markdown import Markdown

from .base import Renderer
from ..commands.results import (
    ResultStatus,
    NotificationResult,
    ErrorResult,
    ConfirmationResult,
    AIResponseResult,
    TableResult,
    TreeResult,
    ListResult,
    KeyValueResult,
    FileViewResult,
    MarkdownResult,
    ImageResult,
    ProgressResult,
    DiffResult,
    ConsentResult,
    PromptResult,
    CompositeResult,
    ToolExecutionResult,
    TextResult,
)

# Rich console instance for all renderers
console = Console()


class RichRenderer(Renderer):
    """Rich console renderer with type-based dispatch.

    Usage:
        result = handle_sessions(context, "")
        RichRenderer.render(result)  # Automatic dispatch
    """
    pass


# ============================================================================
# Display Result Renderers
# ============================================================================

@RichRenderer.register(NotificationResult)
def render_notification(result: NotificationResult) -> None:
    """Render success/info notification (brief message)."""
    if result.status == ResultStatus.SUCCESS:
        console.print(f"✓ [green]{result.message}[/green]")
    elif result.status == ResultStatus.WARNING:
        console.print(f"⚠ [yellow]{result.message}[/yellow]")
    elif result.status == ResultStatus.INFO:
        console.print(f"ℹ [blue]{result.message}[/blue]")
    else:
        console.print(f"• {result.message}")


@RichRenderer.register(ErrorResult)
def render_error(result: ErrorResult) -> None:
    """Render structured error with details and suggestions."""
    console.print(f"✗ [bold red]{result.message}[/bold red]")

    if result.error_details:
        console.print(f"[dim]{result.error_details}[/dim]")

    if result.suggestions:
        console.print("\n[yellow]Suggestions:[/yellow]")
        for suggestion in result.suggestions:
            console.print(f"  • {suggestion}")


@RichRenderer.register(ConfirmationResult)
def render_confirmation(result: ConfirmationResult) -> None:
    """Render action confirmation."""
    console.print(f"✓ [green]{result.message}[/green]")

    if result.details:
        # Show details in dim text
        details_str = ", ".join(f"{k}={v}" for k, v in result.details.items())
        console.print(f"[dim]  ({details_str})[/dim]")


@RichRenderer.register(AIResponseResult)
def render_ai_response(result: AIResponseResult) -> None:
    """Render AI-generated content with markdown and code blocks."""
    if result.message:
        console.print(f"[bold cyan]{result.message}[/bold cyan]\n")

    if result.content:
        # Render as markdown
        md = Markdown(result.content)
        console.print(md)


# ============================================================================
# Structured Data Result Renderers
# ============================================================================

@RichRenderer.register(TableResult)
def render_table(result: TableResult) -> None:
    """Render table with Rich Table widget."""
    # Show message if not success or if message is important
    if result.status != ResultStatus.SUCCESS or result.message:
        console.print(f"[bold]{result.message}[/bold]\n")

    if not result.columns:
        console.print("[dim]No data to display[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan")

    # Add columns
    for col in result.columns:
        table.add_column(col)

    # Add rows
    for row in result.rows:
        table.add_row(*[str(cell) for cell in row])

    console.print(table)


@RichRenderer.register(TreeResult)
def render_tree(result: TreeResult) -> None:
    """Render hierarchical tree."""
    if result.message:
        console.print(f"[bold]{result.message}[/bold]\n")

    if not result.root:
        console.print("[dim]No tree data[/dim]")
        return

    tree = Tree(result.root.get("label", "Root"))

    def add_children(node, data):
        for child in data.get("children", []):
            child_node = node.add(child.get("label", ""))
            if "children" in child:
                add_children(child_node, child)

    add_children(tree, result.root)
    console.print(tree)


@RichRenderer.register(ListResult)
def render_list(result: ListResult) -> None:
    """Render list with bullets/icons."""
    if result.message:
        console.print(f"[bold]{result.message}[/bold]\n")

    if not result.items:
        console.print("[dim]No items[/dim]")
        return

    for item in result.items:
        icon = item.get("icon", "•")
        text = item.get("text", "")
        badge = item.get("badge", "")

        if badge:
            console.print(f"{icon} {text} [dim]({badge})[/dim]")
        else:
            console.print(f"{icon} {text}")


@RichRenderer.register(KeyValueResult)
def render_key_value(result: KeyValueResult) -> None:
    """Render key-value pairs."""
    if result.message:
        console.print(f"[bold]{result.message}[/bold]\n")

    if not result.pairs:
        console.print("[dim]No data[/dim]")
        return

    max_key_len = max(len(k) for k in result.pairs.keys())

    for key, value in result.pairs.items():
        console.print(f"  [cyan]{key.ljust(max_key_len)}[/cyan] : {value}")


# ============================================================================
# File & Media Result Renderers
# ============================================================================

@RichRenderer.register(FileViewResult)
def render_file_view(result: FileViewResult) -> None:
    """Render file with syntax highlighting."""
    if result.message:
        console.print(f"[bold]{result.message}[/bold]\n")

    if not result.content:
        console.print(f"[dim]File: {result.filepath}[/dim]")
        return

    # Detect language from filepath if not provided
    language = result.language
    if not language and result.filepath:
        ext = result.filepath.split('.')[-1].lower()
        language = ext if ext in ['python', 'js', 'json', 'yaml', 'toml', 'html', 'css'] else 'text'

    syntax = Syntax(
        result.content,
        language or "text",
        theme="monokai",
        line_numbers=True,
        highlight_lines={result.line_highlight} if result.line_highlight else set()
    )
    console.print(syntax)


@RichRenderer.register(MarkdownResult)
def render_markdown(result: MarkdownResult) -> None:
    """Render markdown with rich formatting."""
    if result.message:
        console.print(f"[bold]{result.message}[/bold]\n")

    if result.content:
        md = Markdown(result.content)
        console.print(md)
    else:
        console.print(f"[dim]File: {result.filepath}[/dim]")


def _get_terminal_type() -> str:
    """Detect terminal type for image rendering."""
    import os
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    if term_program == "wezterm":
        return "wezterm"
    if term_program == "iterm.app":
        return "iterm2"
    if os.environ.get("WT_SESSION"):
        return "windows_terminal"
    if os.environ.get("KITTY_WINDOW_ID"):
        return "kitty"
    return "unknown"


def _render_image_iterm2(filepath: str) -> bool:
    """Render image using iTerm2 protocol (for WezTerm, iTerm2)."""
    from pathlib import Path
    try:
        from ..tui.renderable.iterm2 import ITerm2Image
        path = Path(filepath)
        if path.exists():
            img = ITerm2Image(path)
            console.print(img)
            return True
    except Exception as e:
        import logging
        logging.debug(f"iTerm2 image rendering failed: {e}")
    return False


def _render_image_sixel(filepath: str) -> bool:
    """Render image using Sixel protocol (for Windows Terminal)."""
    from pathlib import Path
    try:
        from textual_image.renderable.sixel import Image as SixelImage
        path = Path(filepath)
        if path.exists():
            img = SixelImage(path)
            console.print(img)
            return True
    except Exception as e:
        import logging
        logging.debug(f"Sixel image rendering failed: {e}")
    return False


@RichRenderer.register(ImageResult)
def render_image(result: ImageResult) -> None:
    """Render image with terminal-specific protocols when supported.

    Supports:
    - Windows Terminal: Sixel graphics
    - WezTerm/iTerm2: iTerm2 inline images protocol
    - Others: Fallback to file metadata
    """
    if result.message:
        console.print(f"[bold]{result.message}[/bold]")

    # Try terminal-specific rendering
    terminal = _get_terminal_type()
    rendered = False

    if terminal == "windows_terminal":
        rendered = _render_image_sixel(result.filepath)
    elif terminal in ("wezterm", "iterm2"):
        rendered = _render_image_iterm2(result.filepath)

    # Fallback to metadata display
    if not rendered:
        console.print(f"📊 [cyan]Image:[/cyan] {result.filepath}")
        console.print(f"   [dim]Format: {result.format}[/dim]")

        if result.metadata:
            if 'width' in result.metadata and 'height' in result.metadata:
                console.print(f"   [dim]Size: {result.metadata['width']}x{result.metadata['height']}[/dim]")


# ============================================================================
# Operations Result Renderers
# ============================================================================

@RichRenderer.register(ProgressResult)
def render_progress(result: ProgressResult) -> None:
    """Render progress indicator."""
    if result.total > 0:
        pct = int((result.current / result.total) * 100)
        bar_width = 30
        filled = int(bar_width * result.current / result.total)
        bar = "█" * filled + "░" * (bar_width - filled)

        console.print(f"{result.message} [{bar}] {pct}%")
        if result.description:
            console.print(f"[dim]{result.description}[/dim]")
    else:
        console.print(f"{result.message} [{result.current}/{result.total}]")


@RichRenderer.register(DiffResult)
def render_diff(result: DiffResult) -> None:
    """Render structured diff."""
    if result.message:
        console.print(f"[bold]{result.message}[/bold]\n")

    if result.summary:
        console.print(f"[cyan]{result.summary}[/cyan]\n")

    if not result.files:
        console.print("[dim]No changes[/dim]")
        return

    for file_diff in result.files:
        path = file_diff.get('path', 'unknown')
        console.print(f"[bold yellow]File: {path}[/bold yellow]")

        # Simple diff display (could be enhanced with actual hunks)
        if 'old_content' in file_diff and 'new_content' in file_diff:
            old_lines = file_diff['old_content'].splitlines()
            new_lines = file_diff['new_content'].splitlines()

            console.print(f"  [red]- {len(old_lines)} lines[/red]")
            console.print(f"  [green]+ {len(new_lines)} lines[/green]")

        console.print()


# ============================================================================
# Interactive Result Renderers (Future: User Input)
# ============================================================================

@RichRenderer.register(ConsentResult)
def render_consent(result: ConsentResult) -> None:
    """Render consent request (interactive prompt)."""
    console.print(f"[bold yellow]{result.message}[/bold yellow]")
    console.print(f"{result.question}")

    if result.context:
        console.print(f"[dim]Context: {result.context}[/dim]")

    # TODO: Implement actual interactive prompt
    # For now, just show the options
    console.print(f"Options: {', '.join(result.options)}")
    console.print(f"[dim](Interactive consent not yet implemented in Phase 1)[/dim]")


@RichRenderer.register(PromptResult)
def render_prompt(result: PromptResult) -> None:
    """Render text input prompt (interactive)."""
    console.print(f"[bold]{result.message}[/bold]")
    console.print(result.prompt)

    if result.placeholder:
        console.print(f"[dim]Example: {result.placeholder}[/dim]")

    # TODO: Implement actual input prompt
    console.print(f"[dim](Interactive prompt not yet implemented in Phase 1)[/dim]")


# ============================================================================
# Composite Result Renderers
# ============================================================================

@RichRenderer.register(CompositeResult)
def render_composite(result: CompositeResult) -> None:
    """Render multiple results sequentially."""
    if result.message:
        console.print(f"[bold cyan]{result.message}[/bold cyan]\n")

    # Render each sub-result
    for i, sub_result in enumerate(result.results):
        if i > 0:
            console.print()  # Spacing between results

        # Recursive render
        RichRenderer.render(sub_result)


@RichRenderer.register(ToolExecutionResult)
def render_tool_execution(result: ToolExecutionResult) -> None:
    """Render tool execution summary with artifacts."""
    # Execution summary
    status_icon = "✓" if result.success else "✗"
    status_color = "green" if result.success else "red"

    console.print(
        f"{status_icon} [{status_color}]Tool: {result.tool_name}[/{status_color}] "
        f"[dim]({result.duration:.2f}s)[/dim]"
    )

    if result.message:
        console.print(f"  {result.message}")

    # Show stdout if present
    if result.stdout:
        console.print("\n[bold]Output:[/bold]")
        console.print(Panel(result.stdout, border_style="dim", padding=(0, 1)))

    # Show stderr if present
    if result.stderr:
        console.print("\n[bold red]Errors:[/bold red]")
        console.print(Panel(result.stderr, border_style="red", padding=(0, 1)))

    # Show artifacts
    if result.artifacts:
        console.print(f"\n[bold]Artifacts ({len(result.artifacts)}):[/bold]")
        for i, artifact in enumerate(result.artifacts):
            if i > 0:
                console.print()
            RichRenderer.render(artifact)


# ============================================================================
# Fallback Result Renderer
# ============================================================================

@RichRenderer.register(TextResult)
def render_text(result: TextResult) -> None:
    """Render generic text message (fallback)."""
    if result.status == ResultStatus.SUCCESS:
        console.print(f"[green]{result.message}[/green]")
    elif result.status == ResultStatus.ERROR:
        console.print(f"[red]{result.message}[/red]")
        if result.error_details:
            console.print(f"[dim]{result.error_details}[/dim]")
    elif result.status == ResultStatus.WARNING:
        console.print(f"[yellow]{result.message}[/yellow]")
    else:  # INFO
        console.print(result.message)


# Export Rich renderer
__all__ = ["RichRenderer"]

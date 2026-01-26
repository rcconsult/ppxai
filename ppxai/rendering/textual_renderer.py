"""
Textual TUI Renderer - Type-Based Async Dispatch for Textual Widgets

This module provides Textual widget rendering for all 17 result types.
Each result type has a registered async renderer function.

Architecture:
- TextualRenderer subclasses AsyncRenderer
- Each result type gets @TextualRenderer.register() decorator
- Dispatch is mechanical async: await renderer.render(result)
- Renderers have access to app instance for widget operations

v1.15.0: Type-based renderer dispatch refactoring
"""

from typing import TYPE_CHECKING, Optional
from textual.widgets import DataTable, Tree, Static, Markdown as TextualMarkdown
from textual.containers import VerticalScroll

from .base import AsyncRenderer
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
    ImageResult,
    ProgressResult,
    DiffResult,
    ConsentResult,
    PromptResult,
    CompositeResult,
    ToolExecutionResult,
    TextResult,
)

if TYPE_CHECKING:
    from ..tui.app import PPXAIDEApp
    from ..tui.widgets.chat_view import ChatView


class TextualRenderer(AsyncRenderer):
    """Textual TUI renderer with type-based async dispatch.

    Requires app instance for widget access.

    Usage:
        renderer = TextualRenderer(app)
        result = handle_sessions(context, "")
        await renderer.render(result, renderer)
    """

    def __init__(self, app: "PPXAIDEApp"):
        """Initialize Textual renderer.

        Args:
            app: PPXAIDEApp instance
        """
        self.app = app
        self.chat_view: Optional["ChatView"] = None

        # Lazy load chat_view to avoid errors during initialization
        try:
            self.chat_view = app.query_one("#chat-view")
        except Exception:
            # Chat view might not be mounted yet
            pass

    def _get_chat_view(self) -> "ChatView":
        """Get chat view (lazy load if needed)."""
        if self.chat_view is None:
            self.chat_view = self.app.query_one("#chat-view")
        return self.chat_view

    async def render(self, result) -> None:
        """Override render to pass renderer instance."""
        return await super().render(result, renderer_instance=self)


# ============================================================================
# Display Result Renderers
# ============================================================================

@TextualRenderer.register(NotificationResult)
async def render_notification(renderer: TextualRenderer, result: NotificationResult) -> None:
    """Render success/info notification in chat."""
    chat_view = renderer._get_chat_view()

    if result.status == ResultStatus.SUCCESS:
        chat_view.add_system_message(f"✓ [green]{result.message}[/green]")
    elif result.status == ResultStatus.WARNING:
        chat_view.add_system_message(f"⚠ [yellow]{result.message}[/yellow]")
    elif result.status == ResultStatus.INFO:
        chat_view.add_system_message(f"ℹ [blue]{result.message}[/blue]")
    else:
        chat_view.add_system_message(f"• {result.message}")


@TextualRenderer.register(ErrorResult)
async def render_error(renderer: TextualRenderer, result: ErrorResult) -> None:
    """Render structured error with details."""
    chat_view = renderer._get_chat_view()

    msg = f"✗ [bold red]{result.message}[/bold red]"

    if result.error_details:
        msg += f"\n[dim]{result.error_details}[/dim]"

    if result.suggestions:
        msg += "\n\n[yellow]Suggestions:[/yellow]"
        for suggestion in result.suggestions:
            msg += f"\n  • {suggestion}"

    chat_view.add_system_message(msg)


@TextualRenderer.register(ConfirmationResult)
async def render_confirmation(renderer: TextualRenderer, result: ConfirmationResult) -> None:
    """Render action confirmation."""
    chat_view = renderer._get_chat_view()

    msg = f"✓ [green]{result.message}[/green]"

    if result.details:
        details_str = ", ".join(f"{k}={v}" for k, v in result.details.items())
        msg += f"\n[dim]  ({details_str})[/dim]"

    chat_view.add_system_message(msg)


@TextualRenderer.register(AIResponseResult)
async def render_ai_response(renderer: TextualRenderer, result: AIResponseResult) -> None:
    """Render AI-generated content with markdown."""
    chat_view = renderer._get_chat_view()

    if result.message:
        chat_view.add_system_message(f"[bold cyan]{result.message}[/bold cyan]")

    if result.content:
        # Add as markdown message
        chat_view.add_system_message(result.content)


# ============================================================================
# Structured Data Result Renderers
# ============================================================================

@TextualRenderer.register(TableResult)
async def render_table(renderer: TextualRenderer, result: TableResult) -> None:
    """Render table with DataTable widget in side panel."""
    chat_view = renderer._get_chat_view()

    if not result.columns:
        chat_view.add_system_message("[dim]No data to display[/dim]")
        return

    # Create DataTable widget
    table = DataTable()
    table.add_columns(*result.columns)

    for row in result.rows:
        table.add_row(*[str(cell) for cell in row])

    # Show in side panel
    await renderer.app.show_widget_in_panel(table, title=result.message)
    chat_view.add_system_message(f"[dim]{result.message} (opened in side panel)[/dim]")


@TextualRenderer.register(TreeResult)
async def render_tree(renderer: TextualRenderer, result: TreeResult) -> None:
    """Render tree in side panel."""
    chat_view = renderer._get_chat_view()

    if not result.root:
        chat_view.add_system_message("[dim]No tree data[/dim]")
        return

    # Create Tree widget
    tree = Tree(result.root.get("label", "Root"))

    def add_children(node, data):
        for child in data.get("children", []):
            child_node = node.add(child.get("label", ""))
            if "children" in child:
                add_children(child_node, child)

    add_children(tree, result.root)

    # Show in side panel
    await renderer.app.show_widget_in_panel(tree, title=result.message)
    chat_view.add_system_message(f"[dim]{result.message} (opened in side panel)[/dim]")


@TextualRenderer.register(ListResult)
async def render_list(renderer: TextualRenderer, result: ListResult) -> None:
    """Render list in chat view."""
    chat_view = renderer._get_chat_view()

    if not result.items:
        chat_view.add_system_message("[dim]No items[/dim]")
        return

    lines = []
    if result.message:
        lines.append(f"[bold]{result.message}[/bold]\n")

    for item in result.items:
        icon = item.get("icon", "•")
        text = item.get("text", "")
        badge = item.get("badge", "")

        if badge:
            lines.append(f"{icon} {text} [dim]({badge})[/dim]")
        else:
            lines.append(f"{icon} {text}")

    chat_view.add_system_message("\n".join(lines))


@TextualRenderer.register(KeyValueResult)
async def render_key_value(renderer: TextualRenderer, result: KeyValueResult) -> None:
    """Render key-value pairs in chat."""
    chat_view = renderer._get_chat_view()

    if not result.pairs:
        chat_view.add_system_message("[dim]No data[/dim]")
        return

    lines = []
    if result.message:
        lines.append(f"[bold]{result.message}[/bold]\n")

    max_key_len = max(len(k) for k in result.pairs.keys())

    for key, value in result.pairs.items():
        lines.append(f"  [cyan]{key.ljust(max_key_len)}[/cyan] : {value}")

    chat_view.add_system_message("\n".join(lines))


# ============================================================================
# File & Media Result Renderers
# ============================================================================

@TextualRenderer.register(FileViewResult)
async def render_file_view(renderer: TextualRenderer, result: FileViewResult) -> None:
    """Render file in CodeEditor widget."""
    from pathlib import Path

    chat_view = renderer._get_chat_view()

    if not result.content:
        chat_view.add_system_message(f"[dim]File: {result.filepath}[/dim]")
        return

    # Show in side panel using existing show_file_in_panel method
    await renderer.app.show_file_in_panel(
        Path(result.filepath),
        result.content,
        mode="code",
        line=result.line_highlight,
        read_only=result.read_only
    )

    chat_view.add_system_message(f"[dim]{result.message}[/dim]")


@TextualRenderer.register(ImageResult)
async def render_image(renderer: TextualRenderer, result: ImageResult) -> None:
    """Render image in ImageViewer widget."""
    from pathlib import Path

    chat_view = renderer._get_chat_view()

    if not result.filepath:
        chat_view.add_system_message("[dim]No image path provided[/dim]")
        return

    # Show in side panel using show_file_in_panel with image mode
    await renderer.app.show_file_in_panel(
        Path(result.filepath),
        "",  # Content not needed for images
        mode="image",
        read_only=True
    )

    size_info = ""
    if result.metadata and 'width' in result.metadata and 'height' in result.metadata:
        size_info = f" ({result.metadata['width']}x{result.metadata['height']})"

    chat_view.add_system_message(f"[dim]{result.message}{size_info} (opened in side panel)[/dim]")


# ============================================================================
# Operations Result Renderers
# ============================================================================

@TextualRenderer.register(ProgressResult)
async def render_progress(renderer: TextualRenderer, result: ProgressResult) -> None:
    """Render progress in chat (could also update status bar)."""
    chat_view = renderer._get_chat_view()

    if result.total > 0:
        pct = int((result.current / result.total) * 100)
        bar_width = 20
        filled = int(bar_width * result.current / result.total)
        bar = "█" * filled + "░" * (bar_width - filled)

        msg = f"{result.message} [{bar}] {pct}%"
        if result.description:
            msg += f"\n[dim]{result.description}[/dim]"

        chat_view.add_system_message(msg)
    else:
        chat_view.add_system_message(f"{result.message} [{result.current}/{result.total}]")


@TextualRenderer.register(DiffResult)
async def render_diff(renderer: TextualRenderer, result: DiffResult) -> None:
    """Render structured diff in side panel or chat."""
    chat_view = renderer._get_chat_view()

    if not result.files:
        chat_view.add_system_message("[dim]No changes[/dim]")
        return

    # Build diff text
    lines = []
    if result.summary:
        lines.append(f"[cyan]{result.summary}[/cyan]\n")

    for file_diff in result.files:
        path = file_diff.get('path', 'unknown')
        lines.append(f"[bold yellow]File: {path}[/bold yellow]")

        if 'old_content' in file_diff and 'new_content' in file_diff:
            old_lines = file_diff['old_content'].splitlines()
            new_lines = file_diff['new_content'].splitlines()
            lines.append(f"  [red]- {len(old_lines)} lines[/red]")
            lines.append(f"  [green]+ {len(new_lines)} lines[/green]")

        lines.append("")

    # For now, show in chat (could create dedicated diff viewer widget)
    chat_view.add_system_message("\n".join(lines))


# ============================================================================
# Interactive Result Renderers (Future Phase)
# ============================================================================

@TextualRenderer.register(ConsentResult)
async def render_consent(renderer: TextualRenderer, result: ConsentResult) -> None:
    """Render consent request with modal dialog."""
    from ..tui.widgets.dialog import ConsentDialog

    # Push modal dialog and wait for response
    response = await renderer.app.push_screen_wait(
        ConsentDialog(
            title="Consent Required",
            message=result.message,
            question=result.question,
            options=result.options
        )
    )

    # Store response in result object for caller
    result.user_response = response


@TextualRenderer.register(PromptResult)
async def render_prompt(renderer: TextualRenderer, result: PromptResult) -> None:
    """Render text input prompt with modal dialog."""
    from ..tui.widgets.dialog import PromptDialog

    # Push modal dialog and wait for response
    value = await renderer.app.push_screen_wait(
        PromptDialog(
            title="Input Required",
            message=result.message,
            prompt=result.prompt,
            placeholder=result.placeholder or "",
            default=result.default or ""
        )
    )

    # Store response in result object for caller
    result.user_input = value


# ============================================================================
# Composite Result Renderers
# ============================================================================

@TextualRenderer.register(CompositeResult)
async def render_composite(renderer: TextualRenderer, result: CompositeResult) -> None:
    """Render multiple artifacts (future: tabbed panel)."""
    chat_view = renderer._get_chat_view()

    if result.message:
        chat_view.add_system_message(f"[bold cyan]{result.message}[/bold cyan]")

    # TODO: Use ArtifactPanel with tabs
    # For Phase 1, render sequentially
    for sub_result in result.results:
        await renderer.render(sub_result)


@TextualRenderer.register(ToolExecutionResult)
async def render_tool_execution(renderer: TextualRenderer, result: ToolExecutionResult) -> None:
    """Render tool execution summary with artifacts."""
    chat_view = renderer._get_chat_view()

    # Execution summary
    status_icon = "✓" if result.success else "✗"
    status_color = "green" if result.success else "red"

    msg = f"{status_icon} [{status_color}]Tool: {result.tool_name}[/{status_color}] "
    msg += f"[dim]({result.duration:.2f}s)[/dim]"

    if result.message:
        msg += f"\n  {result.message}"

    # Show stdout
    if result.stdout:
        msg += f"\n\n[bold]Output:[/bold]\n{result.stdout}"

    # Show stderr
    if result.stderr:
        msg += f"\n\n[bold red]Errors:[/bold red]\n{result.stderr}"

    chat_view.add_system_message(msg)

    # Render artifacts
    if result.artifacts:
        chat_view.add_system_message(f"\n[bold]Artifacts ({len(result.artifacts)}):[/bold]")
        for artifact in result.artifacts:
            await renderer.render(artifact)


# ============================================================================
# Fallback Result Renderer
# ============================================================================

@TextualRenderer.register(TextResult)
async def render_text(renderer: TextualRenderer, result: TextResult) -> None:
    """Render generic text message (fallback)."""
    chat_view = renderer._get_chat_view()

    if result.status == ResultStatus.SUCCESS:
        chat_view.add_system_message(f"[green]{result.message}[/green]")
    elif result.status == ResultStatus.ERROR:
        msg = f"[red]{result.message}[/red]"
        if result.error_details:
            msg += f"\n[dim]{result.error_details}[/dim]"
        chat_view.add_system_message(msg)
    elif result.status == ResultStatus.WARNING:
        chat_view.add_system_message(f"[yellow]{result.message}[/yellow]")
    else:  # INFO
        chat_view.add_system_message(result.message)


# Export Textual renderer
__all__ = ["TextualRenderer"]

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

from pathlib import Path
from typing import Any

from textual.widgets import DataTable, Tree

from ..commands.results import (
    AIResponseResult,
    CompositeResult,
    ConfirmationResult,
    ConsentResult,
    DiffResult,
    ErrorResult,
    FileViewResult,
    ImageResult,
    KeyValueResult,
    ListResult,
    MarkdownResult,
    NotificationResult,
    PreviewResult,
    ProgressResult,
    PromptResult,
    ResultStatus,
    TableResult,
    TextResult,
    ToolExecutionResult,
    TreeResult,
)
from ..engine.preview_backend import (
    PreviewBackend,
    PreviewBackendError,
    start_proxied_backend,
    start_served_backend,
    stop_backend,
)
from ..preview_server import PreviewServer
from ..tui.widgets.dialog import ConsentDialog, PromptDialog
from .base import AsyncRenderer


class TextualRenderer(AsyncRenderer):
    """Textual TUI renderer with type-based async dispatch.

    Requires app instance for widget access.

    Usage:
        renderer = TextualRenderer(app)
        result = handle_sessions(context, "")
        await renderer.render(result, renderer)
    """

    def __init__(self, app: Any):
        """Initialize Textual renderer.

        Args:
            app: PPXAIDEApp instance
        """
        self.app = app
        self.chat_view: Any | None = None

        # Lazy load chat_view to avoid errors during initialization
        try:
            self.chat_view = app.query_one("#chat-view")
        except Exception:
            # Chat view might not be mounted yet
            pass

    def _get_chat_view(self) -> Any:
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

    # Special handling for session load - render all messages
    if result.details and result.details.get("action") == "load_session":
        # Clear chat view before loading session messages
        chat_view.clear()

        # Render each loaded message
        messages = result.details.get("messages", [])
        for msg in messages:
            role = msg.role
            # Extract text for display; list content (multimodal) is flattened
            # with [Image:/File:] placeholders for any non-text parts.
            content = msg.text_content() if hasattr(msg, "text_content") else msg.content

            if role == "user":
                chat_view.add_user_message(content)
            elif role == "assistant":
                chat_view.add_assistant_message(content)
            elif role == "system":
                chat_view.add_system_message(content)
            elif role == "tool":
                # Tool messages might have special formatting
                chat_view.add_message(content, role="tool")

        # Show confirmation at the end
        session_name = result.details.get("session_name", "unknown")
        message_count = result.details.get("message_count", 0)
        tools_enabled = result.details.get("tools_enabled", False)
        tools_info = "ON" if tools_enabled else "OFF"
        chat_view.add_system_message(
            f"✓ [green]Session restored:[/green] {session_name} ({message_count} messages, Tools: {tools_info})"
        )
    elif result.details and result.details.get("action") == "clear_session":
        # Clear chat view for /clear command
        chat_view.clear()

        # Show confirmation
        messages_cleared = result.details.get("messages_cleared", 0)
        chat_view.add_system_message(
            f"✓ [green]{result.message}[/green] ({messages_cleared} messages cleared)"
        )
    else:
        # Standard confirmation rendering
        msg = f"✓ [green]{result.message}[/green]"

        if result.details:
            # Filter out internal keys used for special actions
            display_details = {k: v for k, v in result.details.items()
                             if k not in ("messages", "action")}
            if display_details:
                details_str = ", ".join(f"{k}={v}" for k, v in display_details.items())
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
    """Render table with TableViewer widget in side panel (supports V toggle)."""

    chat_view = renderer._get_chat_view()

    if not result.columns:
        chat_view.add_system_message("[dim]No data to display[/dim]")
        return

    # Use metadata for file path and content (enables source toggle)
    filepath = result.metadata.get("filepath", "data.csv") if result.metadata else "data.csv"
    content = result.metadata.get("content", "") if result.metadata else ""

    # If we have filepath and content, use show_file_in_panel which uses TableViewer
    # TableViewer has V toggle between table and source view
    if content:
        await renderer.app.show_file_in_panel(
            Path(filepath),
            content,
            mode="table",
            read_only=True
        )
    else:
        # Fallback: create raw DataTable widget (no source toggle)
        table = DataTable()
        table.add_columns(*result.columns)
        for row in result.rows:
            table.add_row(*[str(cell) for cell in row])

        # `row_command` lets a COMMAND declare what activating a row means,
        # the same way `focus_panel` declares whether to take focus. Without
        # it a table in the panel is inert: you can move the cursor and Enter
        # does nothing, which reads as a broken widget rather than a list.
        # The template is formatted with the row's cells, so `/task get {0}`
        # becomes `/task get run_abc…` for the selected row.
        row_command = (result.metadata or {}).get("row_command")
        if row_command:
            table.cursor_type = "row"
            table.row_command = row_command  # read by the app's RowSelected handler
        # `focus_panel` lets the COMMAND declare whether its output should
        # take focus; the renderer should not guess. Default True keeps every
        # existing caller unchanged. `/task ls` and `/run ls` opt out: a
        # background-run list is glanced at, not driven, and stealing focus
        # would contradict the non-blocking promise those commands make.
        focus_panel = True
        if result.metadata:
            focus_panel = bool(result.metadata.get("focus_panel", True))
        await renderer.app.show_widget_in_panel(
            table, title=result.message, focus=focus_panel
        )

    chat_view.add_system_message(f"[dim]{result.message} (opened in side panel, V for source)[/dim]")


@TextualRenderer.register(TreeResult)
async def render_tree(renderer: TextualRenderer, result: TreeResult) -> None:
    """Render tree with DataViewer widget in side panel (supports V toggle)."""

    chat_view = renderer._get_chat_view()

    if not result.root:
        chat_view.add_system_message("[dim]No tree data[/dim]")
        return

    # Use metadata for file path and content (enables source toggle)
    filepath = result.metadata.get("filepath", "data.json") if result.metadata else "data.json"
    content = result.metadata.get("content", "") if result.metadata else ""

    # If we have filepath and content, use show_file_in_panel which uses DataViewer
    # DataViewer has V toggle between tree and source view
    if content:
        await renderer.app.show_file_in_panel(
            Path(filepath),
            content,
            mode="tree",
            read_only=True
        )
    else:
        # Fallback: create raw Tree widget (no source toggle)
        tree = Tree(result.root.get("label", "Root"))

        def add_children(node, data):
            for child in data.get("children", []):
                child_node = node.add(child.get("label", ""))
                if "children" in child:
                    add_children(child_node, child)

        add_children(tree.root, result.root)
        await renderer.app.show_widget_in_panel(tree, title=result.message)

    chat_view.add_system_message(f"[dim]{result.message} (opened in side panel, V for source)[/dim]")


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
    """Render file in CodeEditor widget.

    Some handlers (e.g. /edit) leave `result.content` empty because
    web/VSCode clients fetch content via their own paths
    (apiClient.readFile, vscode.workspace.openTextDocument). The
    Textual renderer shares the filesystem with the engine, so it
    reads the file directly when `content` is missing.
    """

    chat_view = renderer._get_chat_view()

    content = result.content
    if not content and result.filepath:
        try:
            content = Path(result.filepath).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            chat_view.add_system_message(
                f"[red]Cannot read {result.filepath}: {exc}[/red]"
            )
            return

    if not content and not result.filepath:
        chat_view.add_system_message(f"[dim]File: {result.filepath}[/dim]")
        return

    # Show in side panel using existing show_file_in_panel method
    await renderer.app.show_file_in_panel(
        Path(result.filepath),
        content,
        mode="code",
        line=result.line_highlight,
        read_only=result.read_only
    )

    chat_view.add_system_message(f"[dim]{result.message}[/dim]")


@TextualRenderer.register(MarkdownResult)
async def render_markdown(renderer: TextualRenderer, result: MarkdownResult) -> None:
    """Render markdown in Markdown widget in side panel.

    v1.18.1 hotfix: rewrite relative `![alt](path)` and `[text](path)`
    to absolute file:// URIs using the markdown file's directory as
    base. Without this, Textual's Markdown widget hands the raw
    `docs/foo.png` to the OS when the user clicks the link, which
    can't resolve relative paths and shows a broken-URL popup.
    Shared helper with the Rich renderer for cross-TUI parity.
    """

    chat_view = renderer._get_chat_view()

    if not result.content:
        chat_view.add_system_message(f"[dim]File: {result.filepath}[/dim]")
        return

    # Rewrite relative links to file:// URIs based on the source
    # file's directory so terminal/widget link clicks resolve to
    # actual files instead of "Hmmm... can't reach this page" pop-ups.
    from ..common.markdown_links import rewrite_relative_links
    content = rewrite_relative_links(result.content, result.filepath)

    # Show in side panel using show_file_in_panel with markdown mode
    await renderer.app.show_file_in_panel(
        Path(result.filepath),
        content,
        mode="markdown",
        read_only=True
    )

    chat_view.add_system_message(f"[dim]{result.message} (opened in side panel)[/dim]")


@TextualRenderer.register(ImageResult)
async def render_image(renderer: TextualRenderer, result: ImageResult) -> None:
    """Render image in ImageViewer widget."""

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
    """Render multiple artifacts sequentially.

    Note: ArtifactPanel with tabs is available but no command currently
    produces CompositeResult. When one does, wire up tabbed display here.
    """
    chat_view = renderer._get_chat_view()

    if result.message:
        chat_view.add_system_message(f"[bold cyan]{result.message}[/bold cyan]")

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
# Preview Result Renderer
# ============================================================================

# Module-level active preview state (singletons).
# Static-file PreviewServer (always used). Backend subprocess (only for
# `--serve` / `--proxy` modes since v1.18.5).
_active_preview = None
_active_preview_backend: PreviewBackend | None = None


@TextualRenderer.register(PreviewResult)
async def render_preview(renderer: TextualRenderer, result: PreviewResult) -> None:
    """Render preview result - start PreviewServer and (if `--serve` /
    `--proxy`) the backend, open browser.

    v1.18.5 (gap-fill): pre-fix, this renderer ignored
    `result.metadata["mode"]` and unconditionally started a static-file
    PreviewServer regardless of `--serve` / `--proxy` flags. Now
    `mode=served` actually spawns the backend (same engine helper the
    Web/VSCode flow uses); `mode=proxied` validates port reachability.
    """
    global _active_preview, _active_preview_backend
    chat_view = renderer._get_chat_view()

    # Handle close action — stop both static and backend.
    if result.metadata and result.metadata.get("action") == "close":
        msgs = []
        if _active_preview and _active_preview.is_running:
            _active_preview.stop()
            _active_preview = None
            msgs.append("static preview server")
        if _active_preview_backend is not None:
            await stop_backend(_active_preview_backend)
            _active_preview_backend = None
            msgs.append("backend")
        if msgs:
            chat_view.add_system_message(f"[green]Stopped: {', '.join(msgs)}[/green]")
        else:
            chat_view.add_system_message("[dim]No active preview[/dim]")
        return

    # Stop any existing preview before starting a new one.
    if _active_preview and _active_preview.is_running:
        _active_preview.stop()
    if _active_preview_backend is not None:
        await stop_backend(_active_preview_backend)
        _active_preview_backend = None

    metadata = result.metadata or {}
    working_dir = metadata.get("working_dir", ".")
    mode = metadata.get("mode", "static")

    # Spawn / proxy the backend FIRST so any failure surfaces before the
    # browser opens at a URL that won't load.
    if mode == "served":
        try:
            _active_preview_backend = await start_served_backend(
                command=metadata.get("command"),
                port=metadata.get("port"),
                working_dir=working_dir,
            )
        except PreviewBackendError as e:
            chat_view.add_system_message(f"[red]Failed to start backend: {e}[/red]")
            return
    elif mode == "proxied":
        port = metadata.get("port")
        if not port:
            chat_view.add_system_message("[red]Proxied mode requires --proxy <port>[/red]")
            return
        try:
            _active_preview_backend = await start_proxied_backend(
                port=int(port), working_dir=working_dir
            )
        except PreviewBackendError as e:
            chat_view.add_system_message(f"[red]{e}[/red]")
            return

    # Static-file PreviewServer always runs.
    _active_preview = PreviewServer(result.filepath, working_dir)
    static_url = _active_preview.start(open_browser=True)

    msg_lines = [f"Preview opened: {result.filepath}", f"Static URL: {static_url}"]
    if _active_preview_backend is not None:
        backend_label = (
            f"Backend URL: {_active_preview_backend.url}"
            + (
                f" (pid {_active_preview_backend.process.pid})"
                if _active_preview_backend.process
                else " (proxied)"
            )
        )
        msg_lines.append(backend_label)
        if _active_preview_backend.log_path:
            msg_lines.append(f"Backend log: {_active_preview_backend.log_path}")
    chat_view.add_system_message("[dim]" + "\n".join(msg_lines) + "[/dim]")


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

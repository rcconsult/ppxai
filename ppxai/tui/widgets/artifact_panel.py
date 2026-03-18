"""
Artifact Panel Widget - Tabbed Multi-Artifact Display

This widget provides a tabbed interface for displaying multiple artifacts
from tool execution results. Each artifact (image, table, code, etc.) gets
its own tab for easy navigation.

Architecture:
- Extends TabbedContent for built-in tab management
- Accepts any Textual widget as artifact
- Auto-generates tab titles with icons
- Keyboard shortcuts: Tab (cycle), Ctrl+1-9 (direct)

Use Cases:
- Tool execution with multiple outputs (plots, tables, logs)
- CompositeResult rendering
- Side panel multi-artifact viewer

v1.15.0: Type-based renderer dispatch refactoring
"""

from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from textual.widgets import DataTable, Markdown, TabbedContent, TabPane, Static, Tree
from textual.containers import Container
from textual import on

from ...commands.results import (
    AIResponseResult,
    ConfirmationResult,
    ErrorResult,
    FileViewResult,
    ImageResult,
    NotificationResult,
    TableResult,
    TextResult,
    TreeResult,
)

if TYPE_CHECKING:
    from textual.widget import Widget
    from ...commands.results import CommandResult


class ArtifactPanel(TabbedContent):
    """Tabbed panel for displaying multiple tool execution artifacts.

    Features:
    - Tab per artifact (image, table, code, etc.)
    - Keyboard shortcuts: Ctrl+1/2/3/4/5/6/7/8/9 (direct tab navigation)
    - Auto-labels: "Chart", "Table 1", "Output", etc.
    - Clear and rebuild support

    Example:
        panel = ArtifactPanel()
        panel.add_artifact(image_widget, "Plot", "📊")
        panel.add_artifact(table_widget, "Data", "📋")
        panel.add_artifact(code_widget, "Code", "💻")
    """

    def __init__(self, id: Optional[str] = None, *args, **kwargs):
        """Initialize artifact panel.

        Args:
            id: Widget ID (default: "artifact-panel")
        """
        super().__init__(id=id or "artifact-panel", *args, **kwargs)
        self._artifact_count = 0

    def add_artifact(
        self,
        widget: "Widget",
        title: str,
        icon: str = "📄"
    ) -> None:
        """Add artifact widget as new tab.

        Args:
            widget: Textual widget to display (DataTable, Tree, CodeEditor, etc.)
            title: Tab title
            icon: Optional icon/emoji prefix

        Example:
            panel.add_artifact(DataTable(), "Results", "📊")
        """
        self._artifact_count += 1

        # Create tab pane with title and icon
        tab_title = f"{icon} {title}" if icon else title
        pane_id = f"artifact-{self._artifact_count}"

        # Create TabPane and add widget
        with self.hold_updates():
            pane = TabPane(tab_title, id=pane_id)

            # Mount the pane first
            self.add_pane(pane)

            # Then mount the widget inside the pane
            pane.mount(widget)

    async def show_artifacts(
        self,
        results: List["CommandResult"],
        renderer: Optional["TextualRenderer"] = None
    ) -> None:
        """Display multiple result artifacts in tabs.

        This is the main entry point for CompositeResult and ToolExecutionResult
        rendering. Each result gets rendered to a widget and added as a tab.

        Args:
            results: List of CommandResult objects to display
            renderer: TextualRenderer instance for rendering results to widgets

        Example:
            artifacts = [
                ImageResult(...),
                TableResult(...),
                TextResult(...)
            ]
            await panel.show_artifacts(artifacts, renderer)
        """
        # Clear existing artifacts
        self.clear_artifacts()

        if not renderer:
            # Fallback: show raw text representation
            for i, result in enumerate(results, 1):
                widget = Static(str(result))
                self.add_artifact(widget, f"Artifact {i}", "📄")
            return

        # Render each result to appropriate widget
        for i, result in enumerate(results, 1):
            # Determine icon and title based on result type
            if isinstance(result, ImageResult):
                icon = "📊"
                title = f"Image {i}" if not result.message else result.message[:20]
            elif isinstance(result, TableResult):
                icon = "📋"
                title = f"Table {i}" if not result.message else result.message[:20]
            elif isinstance(result, FileViewResult):
                icon = "💻"
                title = f"Code {i}" if not result.message else result.message[:20]
            elif isinstance(result, TreeResult):
                icon = "🌳"
                title = f"Tree {i}" if not result.message else result.message[:20]
            elif isinstance(result, ErrorResult):
                icon = "❌"
                title = f"Error {i}"
            elif isinstance(result, AIResponseResult):
                icon = "🤖"
                title = f"AI Response {i}"
            else:
                icon = "📄"
                title = f"Output {i}"

            # Render result to widget
            # For now, use a simple container that will be populated by the renderer
            container = Container()

            # Add to panel
            self.add_artifact(container, title, icon)

            # Render result into container
            # Note: This requires renderer to support rendering into containers
            # For Phase 1, we'll use a simplified approach
            await self._render_result_to_container(container, result, renderer)

    async def _render_result_to_container(
        self,
        container: Container,
        result: "CommandResult",
        renderer: "TextualRenderer"
    ) -> None:
        """Render a result into a container widget.

        This is an internal helper that creates appropriate widgets
        for each result type and mounts them into the container.

        Args:
            container: Target container
            result: Result to render
            renderer: Renderer instance
        """
        # Create appropriate widget based on result type
        if isinstance(result, ImageResult):
            # Show image using Static with image path
            # Note: Textual doesn't support inline images natively
            # We'll show metadata instead
            content = f"Image: {result.filepath}\n"
            content += f"Format: {result.format}\n"
            if result.metadata:
                if 'width' in result.metadata and 'height' in result.metadata:
                    content += f"Size: {result.metadata['width']}x{result.metadata['height']}\n"
            widget = Static(content)

        elif isinstance(result, TableResult):
            # Create DataTable widget
            widget = DataTable()
            widget.add_columns(*result.columns)
            for row in result.rows:
                widget.add_row(*[str(cell) for cell in row])

        elif isinstance(result, FileViewResult):
            # Show code with Static (syntax highlighting via CodeEditor in future)
            widget = Static(result.content or f"File: {result.filepath}")

        elif isinstance(result, TreeResult):
            # Create Tree widget
            widget = Tree(result.root.get("label", "Root"))

            def add_children(node, data):
                for child in data.get("children", []):
                    child_node = node.add(child.get("label", ""))
                    if "children" in child:
                        add_children(child_node, child)

            add_children(widget, result.root)

        elif isinstance(result, AIResponseResult):
            # Render as markdown
            content = result.content or result.message
            widget = Markdown(content)

        elif isinstance(result, (ErrorResult, NotificationResult, ConfirmationResult)):
            # Show as static text with formatting
            widget = Static(result.message)

        else:
            # Fallback: plain text
            widget = Static(result.message)

        # Mount widget into container
        await container.mount(widget)

    def clear_artifacts(self) -> None:
        """Clear all artifact tabs.

        Removes all tabs and resets counter.
        """
        # Remove all panes
        self.clear_panes()
        self._artifact_count = 0

    def on_mount(self) -> None:
        """Handle widget mount."""
        # Set initial focus if tabs exist
        if self.tab_count > 0:
            self.active = self.get_tab_at(0).id

    @on(TabbedContent.TabActivated)
    def on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Handle tab activation.

        Args:
            event: Tab activation event
        """
        # Could add logging or analytics here
        pass


# Export artifact panel
__all__ = ["ArtifactPanel"]

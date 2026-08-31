"""
ViewerScreen - Full-screen file viewer.

Displays files with:
- Rendered markdown (for .md files)
- Syntax highlighting (for code files)
- Tree view (for JSON/YAML/TOML)
- Images (via terminal protocols)
"""

import sys
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Center, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Markdown, Static

from ppxai.tui.keys import get_widget_bindings

from ..images import display_image
from ..terminal import get_image_protocol_name
from ..widgets.code_editor import CodeEditor
from ..widgets.tree_viewer import TreeViewer


class ImageViewer(Static):
    """Widget that displays an image using terminal graphics protocols."""

    def __init__(self, path: Path, id: str = None):
        super().__init__(id=id)
        self._path = path
        self._image_displayed = False

    def on_mount(self) -> None:
        """Display the image when mounted."""
        # Get terminal size info
        size = self.app.size
        # Reserve space for header and footer
        max_height = max(10, size.height - 4)
        max_width = max(40, size.width - 4)

        escape_seq = display_image(self._path, max_width=max_width, max_height=max_height)
        if escape_seq:
            # Write escape sequence directly to terminal
            sys.stdout.write(escape_seq)
            sys.stdout.flush()
            self._image_displayed = True
            self.update(f"[dim]{self._path.name} ({get_image_protocol_name()})[/dim]")
        else:
            self.update(f"[red]Failed to display image: {self._path.name}[/red]")


class ViewerScreen(Screen):
    """Full-screen file viewer."""

    BINDINGS = get_widget_bindings("ViewerScreen")

    def __init__(
        self,
        path: Path,
        content: str,
        mode: str = "code",
        line: int | None = None,
    ):
        """Initialize viewer screen.

        Args:
            path: File path
            content: File content (empty for images)
            mode: "code", "tree", "markdown", or "image"
            line: Line to jump to (code mode)
        """
        super().__init__()
        self._path = path
        self._content = content
        self._mode = mode
        self._line = line

    def compose(self) -> ComposeResult:
        """Compose the viewer layout."""
        yield Static(
            f" [bold]{self._path.name}[/bold] [dim](read-only)[/dim]",
            id="viewer-header",
        )

        if self._mode == "tree":
            # Parse and display as tree
            viewer = TreeViewer(id="viewer-content")
            ext = self._path.suffix.lower()

            if ext == ".json":
                viewer.load_json(self._content, self._path.name)
            elif ext in (".yaml", ".yml"):
                viewer.load_yaml(self._content, self._path.name)
            elif ext == ".toml":
                viewer.load_toml(self._content, self._path.name)
            else:
                # Fallback: try JSON
                viewer.load_json(self._content, self._path.name)

            yield viewer

        elif self._mode == "markdown":
            # Rendered markdown view
            with VerticalScroll(id="viewer-content"):
                yield Markdown(self._content, id="markdown-view")

        elif self._mode == "image":
            # Image view using terminal protocols
            with Center(id="viewer-content"):
                yield ImageViewer(self._path, id="image-view")

        else:
            # Code view with syntax highlighting
            editor = CodeEditor(
                text=self._content,
                filename=str(self._path.name),
                read_only=True,
                id="viewer-content",
            )
            yield editor

        yield Footer()

    def on_mount(self) -> None:
        """Handle mount event."""
        self.title = f"Viewing: {self._path.name}"

        # Jump to line if specified (code mode)
        if self._mode == "code" and self._line:
            try:
                editor = self.query_one("#viewer-content", CodeEditor)
                editor.goto_line(self._line)
            except Exception:
                pass

    def action_close(self) -> None:
        """Close the viewer and return to main screen."""
        self.app.pop_screen()

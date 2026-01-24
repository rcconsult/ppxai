"""
ViewerScreen - Full-screen file viewer.

Displays files with syntax highlighting (code) or tree view (data).
"""

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Static

from ..widgets.tree_viewer import TreeViewer
from ..widgets.code_editor import CodeEditor


class ViewerScreen(Screen):
    """Full-screen file viewer."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("q", "close", "Close", show=False),
    ]

    def __init__(
        self,
        path: Path,
        content: str,
        mode: str = "code",
        line: Optional[int] = None,
    ):
        """Initialize viewer screen.

        Args:
            path: File path
            content: File content
            mode: "code" for syntax view, "tree" for structured data
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

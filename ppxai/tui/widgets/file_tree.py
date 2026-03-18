"""
FileTree widget - Norton Commander-style file browser.

Provides a directory tree for browsing and opening files
in the side panel or injecting @file references into chat.
"""

from pathlib import Path
from typing import Iterable, Optional

from textual.events import Click
from textual.message import Message
from textual.widgets import DirectoryTree

from ppxai.tui.keys import get_widget_bindings


def _short_path(path: Path) -> str:
    """Return last 2 path components for display, e.g. 'projects/myapp'."""
    parts = path.parts
    return str(Path(*parts[-2:])) if len(parts) >= 2 else str(path)


class FileTree(DirectoryTree):
    """File system browser widget.

    Opens files in the side panel on Enter (read-only) or Ctrl+Enter (editable).
    Space injects an @file reference into the chat input.
    Escape returns focus to the chat input.
    """

    BINDINGS = get_widget_bindings("FileTree")

    def __init__(self, path: Path, **kwargs) -> None:
        super().__init__(path, **kwargs)
        self.guide_depth = 3

    async def watch_path(self) -> None:
        """Override DirectoryTree.watch_path to show truncated cwd as root label.

        The parent's watch_path calls reset_node(root, str(self.path), ...) which
        sets the root label to the full absolute path. We call super() first, then
        override the label with our short version.
        """
        await super().watch_path()
        self.root.set_label(_short_path(self.path))

    def update_root_path(self, path: Path) -> None:
        """Update the tree root when working directory changes."""
        self.path = path  # Triggers watch_path which sets short label

    class FilePreview(Message):
        """Posted when user selects a file for read-only preview (Enter)."""

        def __init__(self, path: Path) -> None:
            super().__init__()
            self.path = path

    class FileEdit(Message):
        """Posted when user selects a file for editing (Ctrl+Enter)."""

        def __init__(self, path: Path) -> None:
            super().__init__()
            self.path = path

    class FileInject(Message):
        """Posted when user wants to inject an @file reference (Space)."""

        def __init__(self, path: Path) -> None:
            super().__init__()
            self.path = path

    # Directories to hide — keep the tree navigable in large Python projects
    _HIDDEN_DIRS = frozenset({
        ".git", ".svn", ".hg",
        ".venv", "venv", "env", ".env",
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        "node_modules", ".next", "dist", "build",
        ".tox", ".nox",
    })

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        """Exclude noisy directories that would bloat the tree."""
        return [p for p in paths if p.name not in self._HIDDEN_DIRS]

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        """Intercept file selection (Enter on a file node) to preview instead of open."""
        event.stop()
        self.post_message(self.FilePreview(event.path))

    def _get_cursor_file_path(self) -> Optional[Path]:
        """Return the file Path at the current cursor position, or None if not a file."""
        node = self.cursor_node
        if node is None or node.data is None:
            return None
        data = node.data
        # DirectoryTree node data is DirEntry (has .path); handle both DirEntry and raw Path
        path = data.path if hasattr(data, "path") else data
        if isinstance(path, Path) and path.is_file():
            return path
        return None

    def action_edit(self) -> None:
        """Edit the file at the current cursor position (Ctrl+Enter)."""
        path = self._get_cursor_file_path()
        if path:
            self.post_message(self.FileEdit(path))

    def action_inject(self) -> None:
        """Inject an @file reference for the cursor file into the chat input (Space)."""
        path = self._get_cursor_file_path()
        if path:
            self.post_message(self.FileInject(path))

    def action_dismiss_tree(self) -> None:
        """Return focus to the chat input box (Escape)."""
        try:
            self.app.query_one("#input-box").focus()
        except Exception:
            pass

    def on_click(self, event: Click) -> None:
        """Ctrl+Click opens the file for editing (same as Ctrl+Enter)."""
        if not event.ctrl:
            return
        # Tree._on_click is async so cursor_node hasn't updated yet — read the
        # clicked node directly from the style metadata instead.
        meta = event.style.meta
        if "line" in meta:
            node = self.get_node_at_line(meta["line"])
            if node is not None and node.data is not None:
                data = node.data
                path = data.path if hasattr(data, "path") else data
                if isinstance(path, Path) and path.is_file():
                    event.stop()
                    self.post_message(self.FileEdit(path))

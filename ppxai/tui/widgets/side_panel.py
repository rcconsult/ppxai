"""
SidePanel widget - Right-side panel for file viewer/editor.

Displays content in a split view alongside the main chat.
Supports multiple content types: code, markdown, tree, image.
"""

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll, Center
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, Markdown

from .tree_viewer import TreeViewer
from .code_editor import CodeEditor, EXTENSION_TO_LANGUAGE, SUPPORTED_LANGUAGES


class SidePanel(Widget):
    """Side panel for displaying files in split view.

    CSS is defined in themes/layout.tcss under "Side panel" section.
    """

    BINDINGS = [
        Binding("escape", "close_panel", "Close", show=True),
        Binding("ctrl+l", "cycle_language", "Lang", show=True),
    ]

    # Sorted list of languages for cycling
    _LANG_CYCLE = sorted(SUPPORTED_LANGUAGES)

    # Reactive to track if panel is open
    is_open: reactive[bool] = reactive(False)

    class Closed(Message):
        """Message sent when panel is closed."""
        pass

    class Opened(Message):
        """Message sent when panel is opened."""
        pass

    def __init__(self, id: str = "side-panel"):
        super().__init__(id=id)
        self._path: Optional[Path] = None
        self._content: str = ""
        self._mode: str = "code"
        self._line: Optional[int] = None
        self._col: Optional[int] = None
        self._read_only: bool = True
        self._modified: bool = False
        self._current_language: Optional[str] = None

    def compose(self) -> ComposeResult:
        """Compose the panel layout - empty initially."""
        # Header bar with filename and language badge
        with Horizontal(id="panel-header-bar"):
            yield Static("", id="panel-filename")
            # Language badge - shows detected language for code mode
            yield Static("", id="lang-badge")
        yield Vertical(id="panel-content")

    async def show_file(
        self,
        path: Path,
        content: str,
        mode: str = "code",
        line: Optional[int] = None,
        col: Optional[int] = None,
        read_only: bool = True,
    ) -> None:
        """Show a file in the panel.

        Args:
            path: File path
            content: File content (empty for images)
            mode: "code", "tree", "markdown", or "image"
            line: Line to jump to
            col: Column to jump to
            read_only: Whether content is read-only
        """
        self._path = path
        self._content = content
        self._mode = mode
        self._line = line
        self._col = col
        self._read_only = read_only
        self._modified = False

        # Detect language from extension
        lang = EXTENSION_TO_LANGUAGE.get(path.suffix.lower(), "")
        self._current_language = lang if lang else None

        # Update filename in header
        filename_static = self.query_one("#panel-filename", Static)
        mode_label = "edit" if not read_only else "view"
        filename_static.update(f" [bold]{path.name}[/bold] [dim]({mode_label})[/dim]")

        # Update language badge based on mode
        lang_badge = self.query_one("#lang-badge", Static)
        if mode == "code" and lang:
            lang_badge.update(f"({lang})")
        else:
            lang_badge.update("")

        # Clear and rebuild content - must await removal before mounting new widgets
        content_container = self.query_one("#panel-content", Vertical)
        await content_container.remove_children()

        # Add appropriate viewer/editor based on mode
        if mode == "tree":
            viewer = TreeViewer(id="panel-viewer")
            await content_container.mount(viewer)
            ext = path.suffix.lower()
            if ext == ".json":
                viewer.load_json(content, path.name)
            elif ext in (".yaml", ".yml"):
                viewer.load_yaml(content, path.name)
            elif ext == ".toml":
                viewer.load_toml(content, path.name)
            else:
                viewer.load_json(content, path.name)

        elif mode == "markdown":
            scroll = VerticalScroll(id="panel-scroll")
            await content_container.mount(scroll)
            await scroll.mount(Markdown(content, id="panel-markdown"))

        elif mode == "image":
            # Note: Terminal image protocols (iTerm2/Kitty/Sixel) don't work
            # inside Textual widgets because Textual manages terminal rendering.
            # Show image info instead.
            from ..images import get_image_size
            from ..terminal import get_image_protocol_name

            # Get image dimensions if possible
            try:
                data = path.read_bytes()
                size = get_image_size(data)
                size_str = f"{size[0]}x{size[1]}" if size else "unknown"
            except (OSError, ValueError):
                size_str = "unknown"  # File read or parse error

            size_kb = path.stat().st_size / 1024
            proto = get_image_protocol_name()

            info_text = f"""[bold cyan]{path.name}[/bold cyan]

[dim]Size:[/dim] {size_kb:.1f} KB
[dim]Dimensions:[/dim] {size_str}
[dim]Protocol:[/dim] {proto}

[yellow]Note:[/yellow] Images cannot be displayed inline
in the side panel. The image was sent to
your terminal via {proto} protocol.

[dim]Use an external viewer for full display.[/dim]"""

            center = Center(id="panel-image-center")
            await content_container.mount(center)
            await center.mount(Static(info_text, id="panel-image-info"))

        else:
            # Code view (header hidden as SidePanel has its own)
            editor = CodeEditor(
                text=content,
                language=lang if lang else None,  # Pass detected language for syntax highlighting
                filename=str(path.name),
                read_only=read_only,
                show_header=False,
                id="panel-editor",
            )
            await content_container.mount(editor)

            # Jump to line if specified
            if line:
                self.call_after_refresh(lambda: self._goto_line(line, col))

        # Show the panel
        self.add_class("visible")
        self.is_open = True
        self.post_message(self.Opened())

    def _goto_line(self, line: int, col: Optional[int] = None) -> None:
        """Jump to a specific line after content is mounted."""
        try:
            editor = self.query_one("#panel-editor", CodeEditor)
            editor.goto_line(line, col or 0)
        except NoMatches:
            pass  # Editor not mounted yet

    def close(self) -> None:
        """Close the panel."""
        if not self.is_open:
            return

        # Check for unsaved changes in edit mode
        if not self._read_only and self._modified:
            # TODO: Prompt to save
            pass

        self.remove_class("visible")
        self.is_open = False
        self._path = None
        self._content = ""
        self.post_message(self.Closed())

    def action_close_panel(self) -> None:
        """Handle escape key to close panel."""
        self.close()

    def action_cycle_language(self) -> None:
        """Cycle through syntax highlighting languages (Ctrl+L)."""
        if self._mode != "code":
            return

        # Get current language index
        current = self._current_language
        try:
            idx = self._LANG_CYCLE.index(current) if current in self._LANG_CYCLE else -1
        except ValueError:
            idx = -1

        # Cycle to next language
        next_idx = (idx + 1) % len(self._LANG_CYCLE)
        new_lang = self._LANG_CYCLE[next_idx]
        self._current_language = new_lang

        # Update the editor's language
        try:
            editor = self.query_one("#panel-editor", CodeEditor)
            editor.language = new_lang
        except NoMatches:
            pass  # Not in code mode

        # Update the badge
        try:
            lang_badge = self.query_one("#lang-badge", Static)
            lang_badge.update(f"({new_lang})")
        except NoMatches:
            pass  # Badge not found

        self.app.notify(f"Language: {new_lang}", title="Syntax")

    def save(self) -> bool:
        """Save the current file if in edit mode.

        Returns:
            True if saved successfully
        """
        if self._read_only or not self._path:
            return False

        try:
            editor = self.query_one("#panel-editor", CodeEditor)
            self._path.write_text(editor.text, encoding="utf-8")
            self._modified = False
            self.app.notify(f"Saved {self._path.name}", title="Saved")
            return True
        except Exception as e:
            self.app.notify(f"Error saving: {e}", title="Error", severity="error")
            return False

    def on_text_area_changed(self, event) -> None:
        """Track modifications in edit mode."""
        if not self._read_only:
            self._modified = True
            # Update header to show modified indicator
            try:
                filename_static = self.query_one("#panel-filename", Static)
                filename_static.update(f" [bold]{self._path.name}[/bold] [yellow]*[/yellow] [dim](edit)[/dim]")
            except NoMatches:
                pass  # Header not found

    @property
    def current_path(self) -> Optional[Path]:
        """Get the currently displayed file path."""
        return self._path

    @property
    def is_modified(self) -> bool:
        """Check if content has unsaved changes."""
        return self._modified

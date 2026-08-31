"""
DataViewer widget - Structured data viewer with tree/source toggle.

Combines TreeViewer (hierarchical display) and CodeEditor (source view)
with V toggle between modes. Supports JSON, YAML, and TOML formats.
"""

import json
from pathlib import Path
from typing import Any, Literal

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import ContentSwitcher, Static

from ppxai.tui.keys import get_widget_bindings
from ppxai.tui.widgets.code_editor import CodeEditor
from ppxai.tui.widgets.tree_viewer import TreeViewer

# Type for display modes
ViewMode = Literal["tree", "source"]


class DataViewer(Widget):
    """A widget for viewing structured data with tree/source toggle.

    Supports JSON, YAML, and TOML files. Press V to toggle
    between tree view and source (code) view.

    Tree view shows hierarchical data with expand/collapse.
    Source view shows raw content with syntax highlighting.
    """

    can_focus = True
    can_focus_children = True

    # CSS is in layout.tcss

    BINDINGS = get_widget_bindings("DataViewer")

    # Reactive property for current view mode
    view_mode: reactive[ViewMode] = reactive("tree")

    class ViewToggled(Message):
        """Posted when view mode is toggled."""

        def __init__(self, mode: ViewMode):
            super().__init__()
            self.mode = mode

    def __init__(
        self,
        data: Any = None,
        source: str = "",
        format: str = "json",
        filename: str = None,
        id: str = None,
    ):
        """Initialize the data viewer.

        Args:
            data: Parsed data to display (dict, list, etc.)
            source: Raw source text for code view
            format: Data format ("json", "yaml", "toml")
            filename: Filename for display and format detection
            id: Widget ID
        """
        super().__init__(id=id)
        self._data = data
        self._source = source
        self._format = format
        self._filename = filename or "data"
        self._tree_viewer: TreeViewer | None = None
        self._code_editor: CodeEditor | None = None

        # Detect format from filename if not specified
        if filename and format == "json":
            ext = Path(filename).suffix.lower()
            if ext in (".yaml", ".yml"):
                self._format = "yaml"
            elif ext == ".toml":
                self._format = "toml"

    def compose(self) -> ComposeResult:
        """Compose the data viewer layout."""
        # Header with filename and mode indicator
        mode_hint = "[V: source]" if self.view_mode == "tree" else "[V: tree]"
        header_text = f" [bold]{self._filename}[/bold] [dim]({self.view_mode})[/dim]  [dim]{mode_hint}[/dim]"
        yield Static(header_text, classes="data-viewer-header", id="data-viewer-header")

        # Content area with switcher
        with ContentSwitcher(initial="tree-view", id="data-content-switcher"):
            # Tree view (default)
            with Vertical(id="tree-view"):
                self._tree_viewer = TreeViewer(
                    data=self._data,
                    title=self._filename,
                    format=self._format,
                )
                yield self._tree_viewer

            # Source view
            with Vertical(id="source-view"):
                self._code_editor = CodeEditor(
                    text=self._source,
                    language=self._format,
                    filename=self._filename,
                    read_only=True,
                    show_header=False,  # We have our own header
                    show_footer=True,
                )
                yield self._code_editor

    def on_mount(self) -> None:
        """Called when mounted - set initial view."""
        # Focus the appropriate widget
        self._focus_current_view()

    def watch_view_mode(self, mode: ViewMode) -> None:
        """React to view mode changes."""
        try:
            # Update content switcher
            switcher = self.query_one("#data-content-switcher", ContentSwitcher)
            switcher.current = "tree-view" if mode == "tree" else "source-view"

            # Update header
            self._update_header()

            # Focus the appropriate widget
            self._focus_current_view()

            # Post message
            self.post_message(self.ViewToggled(mode))

        except NoMatches:
            pass  # Not yet composed

    def _update_header(self) -> None:
        """Update the header with current mode."""
        try:
            header = self.query_one("#data-viewer-header", Static)
            mode_hint = "[V: source]" if self.view_mode == "tree" else "[V: tree]"
            header_text = f" [bold]{self._filename}[/bold] [dim]({self.view_mode})[/dim]  [dim]{mode_hint}[/dim]"
            header.update(header_text)
        except NoMatches:
            pass

    def _focus_current_view(self) -> None:
        """Focus the widget for the current view mode."""
        if self.view_mode == "tree" and self._tree_viewer:
            def focus_tree():
                try:
                    tree = self._tree_viewer.query_one("Tree")
                    tree.focus()
                except NoMatches:
                    self._tree_viewer.focus()
            self.call_after_refresh(focus_tree)
        elif self.view_mode == "source" and self._code_editor:
            def focus_editor():
                try:
                    # Focus the TextArea inside CodeEditor, not the container
                    text_area = self._code_editor.query_one("#code-text-area")
                    text_area.focus()
                except NoMatches:
                    self._code_editor.focus()
            self.call_after_refresh(focus_editor)

    def action_toggle_view(self) -> None:
        """Toggle between tree and source view (V)."""
        self.view_mode = "source" if self.view_mode == "tree" else "tree"

    def action_expand_all(self) -> None:
        """Expand all tree nodes (e key)."""
        if self.view_mode == "tree" and self._tree_viewer:
            self._tree_viewer.expand_all()

    def action_collapse_all(self) -> None:
        """Collapse all tree nodes (c key)."""
        if self.view_mode == "tree" and self._tree_viewer:
            self._tree_viewer.collapse_all()

    def set_data(self, data: Any, source: str = None, filename: str = None) -> None:
        """Update the viewer with new data.

        Args:
            data: Parsed data structure
            source: Raw source text (if None, generated from data)
            filename: Optional new filename
        """
        self._data = data

        if filename:
            self._filename = filename
            # Detect format from new filename
            ext = Path(filename).suffix.lower()
            if ext in (".yaml", ".yml"):
                self._format = "yaml"
            elif ext == ".toml":
                self._format = "toml"
            elif ext == ".json":
                self._format = "json"

        # Generate source from data if not provided
        if source is not None:
            self._source = source
        elif data is not None:
            self._source = self._format_source(data)

        # Update tree viewer
        if self._tree_viewer:
            self._tree_viewer.set_data(data, self._filename)

        # Update code editor
        if self._code_editor:
            self._code_editor.text = self._source

        # Update header
        self._update_header()

    def _format_source(self, data: Any) -> str:
        """Format data as source text.

        Args:
            data: Data to format

        Returns:
            Formatted source string
        """
        if self._format == "json":
            return json.dumps(data, indent=2, ensure_ascii=False)
        elif self._format == "yaml":
            try:
                import yaml
                return yaml.dump(data, default_flow_style=False, allow_unicode=True)
            except ImportError:
                return str(data)
        elif self._format == "toml":
            try:
                import tomli_w
                return tomli_w.dumps(data)
            except ImportError:
                return str(data)
        return str(data)

    def load_json(self, text: str, filename: str = "data.json") -> bool:
        """Load JSON data from text.

        Args:
            text: JSON string
            filename: Display filename

        Returns:
            True if successful
        """
        try:
            data = json.loads(text)
            self._format = "json"
            self.set_data(data, source=text, filename=filename)
            return True
        except json.JSONDecodeError:
            return False

    def load_yaml(self, text: str, filename: str = "data.yaml") -> bool:
        """Load YAML data from text.

        Args:
            text: YAML string
            filename: Display filename

        Returns:
            True if successful
        """
        try:
            import yaml
            data = yaml.safe_load(text)
            self._format = "yaml"
            self.set_data(data, source=text, filename=filename)
            return True
        except Exception:
            return False

    def load_toml(self, text: str, filename: str = "data.toml") -> bool:
        """Load TOML data from text.

        Args:
            text: TOML string
            filename: Display filename

        Returns:
            True if successful
        """
        try:
            import tomllib
            data = tomllib.loads(text)
            self._format = "toml"
            self.set_data(data, source=text, filename=filename)
            return True
        except Exception:
            return False

    def load_file(self, path: str) -> bool:
        """Load data from a file.

        Args:
            path: Path to the file

        Returns:
            True if successful
        """
        try:
            file_path = Path(path)
            text = file_path.read_text(encoding="utf-8")
            ext = file_path.suffix.lower()

            if ext == ".json":
                return self.load_json(text, file_path.name)
            elif ext in (".yaml", ".yml"):
                return self.load_yaml(text, file_path.name)
            elif ext == ".toml":
                return self.load_toml(text, file_path.name)
            else:
                # Try JSON first, then YAML
                if self.load_json(text, file_path.name):
                    return True
                return self.load_yaml(text, file_path.name)

        except OSError:
            return False

    @property
    def data(self) -> Any:
        """Get the current data."""
        return self._data

    @property
    def source(self) -> str:
        """Get the current source text."""
        return self._source

    @property
    def format(self) -> str:
        """Get the current data format."""
        return self._format

    @property
    def filename(self) -> str:
        """Get the current filename."""
        return self._filename

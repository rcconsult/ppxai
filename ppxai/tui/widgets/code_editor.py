"""
CodeEditor widget - Syntax-highlighted code editor.

Uses Textual's built-in TextArea widget with tree-sitter
syntax highlighting for various programming languages.
"""

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static, TextArea
from textual.widgets.text_area import Selection

# Language detection by file extension
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".lua": "lua",
    ".r": "r",
    ".R": "r",
}


class CodeEditor(Static):
    """A code editor widget with syntax highlighting."""

    # CSS is in layout.tcss

    def __init__(
        self,
        text: str = "",
        language: str = None,
        filename: str = None,
        read_only: bool = False,
        show_line_numbers: bool = True,
        id: str = None,
    ):
        """Initialize the code editor.

        Args:
            text: Initial text content
            language: Language for syntax highlighting (auto-detected from filename)
            filename: Filename for header display and language detection
            read_only: If True, prevent editing
            show_line_numbers: Show line numbers in gutter
            id: Widget ID
        """
        super().__init__(id=id)
        self._text = text
        self._language = language
        self._filename = filename
        self._read_only = read_only
        self._show_line_numbers = show_line_numbers
        self._text_area: Optional[TextArea] = None
        self._modified = False

    def compose(self) -> ComposeResult:
        """Compose the editor layout."""
        # Header with filename
        if self._filename:
            yield Static(
                f" [bold]{self._filename}[/bold]",
                classes="editor-header",
            )

        # Detect language from filename if not specified
        language = self._language
        if not language and self._filename:
            ext = Path(self._filename).suffix.lower()
            language = EXTENSION_TO_LANGUAGE.get(ext)

        # TextArea with syntax highlighting
        self._text_area = TextArea(
            self._text,
            language=language,
            read_only=self._read_only,
            show_line_numbers=self._show_line_numbers,
        )
        yield self._text_area

        # Footer with position info
        yield Static(
            " Ln 1, Col 1",
            classes="editor-footer",
            id="editor-position",
        )

    def on_mount(self) -> None:
        """Called when the editor is mounted."""
        if self._text_area:
            self._text_area.focus()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Handle text changes."""
        self._modified = True

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        """Update position display when cursor moves."""
        if self._text_area:
            cursor = self._text_area.cursor_location
            try:
                footer = self.query_one("#editor-position", Static)
                footer.update(f" Ln {cursor[0] + 1}, Col {cursor[1] + 1}")
            except Exception:
                pass

    @property
    def text(self) -> str:
        """Get the current text content."""
        if self._text_area:
            return self._text_area.text
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        """Set the text content."""
        self._text = value
        if self._text_area:
            self._text_area.text = value
            self._modified = False

    @property
    def modified(self) -> bool:
        """Check if content has been modified."""
        return self._modified

    @property
    def language(self) -> Optional[str]:
        """Get the current language."""
        if self._text_area:
            return self._text_area.language
        return self._language

    @language.setter
    def language(self, value: str) -> None:
        """Set the language for syntax highlighting."""
        self._language = value
        if self._text_area:
            self._text_area.language = value

    def load_file(self, path: str) -> bool:
        """Load content from a file.

        Args:
            path: Path to the file

        Returns:
            True if successful, False on error
        """
        try:
            file_path = Path(path)
            content = file_path.read_text(encoding="utf-8")
            self._filename = file_path.name
            self.text = content

            # Update language based on extension
            ext = file_path.suffix.lower()
            if ext in EXTENSION_TO_LANGUAGE:
                self.language = EXTENSION_TO_LANGUAGE[ext]

            # Update header
            try:
                header = self.query_one(".editor-header", Static)
                header.update(f" [bold]{self._filename}[/bold]")
            except Exception:
                pass

            self._modified = False
            return True
        except Exception:
            return False

    def save_file(self, path: str = None) -> bool:
        """Save content to a file.

        Args:
            path: Path to save to (uses original filename if not specified)

        Returns:
            True if successful, False on error
        """
        save_path = path or self._filename
        if not save_path:
            return False

        try:
            Path(save_path).write_text(self.text, encoding="utf-8")
            self._modified = False
            return True
        except Exception:
            return False

    def goto_line(self, line: int, column: int = 0) -> None:
        """Move cursor to a specific line and column.

        Args:
            line: Line number (1-based)
            column: Column number (0-based)
        """
        if self._text_area:
            # TextArea uses 0-based line numbers
            self._text_area.cursor_location = (line - 1, column)

    def select_all(self) -> None:
        """Select all text."""
        if self._text_area:
            self._text_area.select_all()

    def clear(self) -> None:
        """Clear the editor content."""
        self.text = ""

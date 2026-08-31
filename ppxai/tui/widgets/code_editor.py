"""
CodeEditor widget - Syntax-highlighted code editor.

Uses Textual's built-in TextArea widget with tree-sitter
syntax highlighting for various programming languages.
"""

from pathlib import Path

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static, TextArea

# Languages supported by Textual's built-in TextArea (tree-sitter)
# Check TextArea.available_languages for the full list
SUPPORTED_LANGUAGES = {
    "javascript", "sql", "rust", "xml", "json", "go", "yaml",
    "toml", "python", "regex", "html", "java", "bash", "css", "markdown"
}

# TextArea syntax themes available
# Available: css, dracula, github_light, monokai, vscode_dark
SYNTAX_THEMES = {"css", "dracula", "github_light", "monokai", "vscode_dark"}

# Map Textual app themes to TextArea syntax themes
# Dark app themes → dark syntax themes, Light app themes → light syntax themes
APP_THEME_TO_SYNTAX = {
    # Dark themes → dracula (good contrast, vibrant colors)
    "catppuccin-mocha": "dracula",
    "dracula": "dracula",
    "tokyo-night": "dracula",
    "nord": "monokai",  # Nord has softer colors, monokai complements
    "gruvbox": "monokai",  # Warm colors match
    "monokai": "monokai",
    "tron-legacy": "vscode_dark",  # Cyan/blue theme
    "matrix": "vscode_dark",  # Green on black
    "textual-dark": "vscode_dark",
    "solarized-dark": "monokai",
    "rose-pine": "dracula",
    "rose-pine-moon": "dracula",
    "atom-one-dark": "vscode_dark",
    "flexoki": "monokai",
    "textual-ansi": "vscode_dark",
    # Light themes → github_light
    "textual-light": "github_light",
    "solarized-light": "github_light",
    "rose-pine-dawn": "github_light",
    "atom-one-light": "github_light",
}

# Default syntax theme for unknown app themes
DEFAULT_SYNTAX_THEME = "dracula"


def get_syntax_theme_for_app_theme(app_theme: str) -> str:
    """Get the appropriate syntax theme for a given app theme.

    Args:
        app_theme: Name of the Textual app theme

    Returns:
        Name of the syntax theme to use
    """
    return APP_THEME_TO_SYNTAX.get(app_theme, DEFAULT_SYNTAX_THEME)

# Language detection by file extension
# Maps extensions to language names (with fallbacks for unsupported)
EXTENSION_TO_LANGUAGE = {
    # Python
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    # JavaScript/TypeScript (TS uses JS highlighting as fallback)
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "javascript",  # TypeScript uses JS highlighting
    ".jsx": "javascript",
    ".tsx": "javascript",
    # Data formats
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    # Markup
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    # Database
    ".sql": "sql",
    # Shell
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    # Systems languages
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    # C/C++ (no built-in support, will show as plain text)
    # ".c": None,
    # ".cpp": None,
    # ".h": None,
}


class CodeEditor(Widget):
    """A code editor widget with syntax highlighting."""

    can_focus = True
    can_focus_children = True

    # CSS is in layout.tcss

    def __init__(
        self,
        text: str = "",
        language: str = None,
        filename: str = None,
        read_only: bool = False,
        show_line_numbers: bool = True,
        show_header: bool = True,
        show_footer: bool = True,
        id: str = None,
    ):
        """Initialize the code editor.

        Args:
            text: Initial text content
            language: Language for syntax highlighting (auto-detected from filename)
            filename: Filename for header display and language detection
            read_only: If True, prevent editing
            show_line_numbers: Show line numbers in gutter
            show_header: Show header with filename
            show_footer: Show footer with line/col position
            id: Widget ID
        """
        super().__init__(id=id)
        self._text = text
        self._language = language
        self._filename = filename
        self._read_only = read_only
        self._show_line_numbers = show_line_numbers
        self._show_header = show_header
        self._show_footer = show_footer
        self._text_area: TextArea | None = None
        self._modified = False

    def compose(self) -> ComposeResult:
        """Compose the editor layout."""
        # Detect language from filename if not specified
        language = self._language
        if not language and self._filename:
            ext = Path(self._filename).suffix.lower()
            language = EXTENSION_TO_LANGUAGE.get(ext)
        # Debug: log language detection
        self.log.info(f"CodeEditor: filename={self._filename}, detected_lang={language}")

        # Header with filename and detected language (optional)
        if self._show_header:
            header_text = f" [bold]{self._filename or 'untitled'}[/bold]"
            if language:
                header_text += f" [dim]({language})[/dim]"
            yield Static(header_text, classes="editor-header")

        # Get syntax theme based on current app theme
        syntax_theme = DEFAULT_SYNTAX_THEME
        try:
            app_theme = self.app.theme
            syntax_theme = get_syntax_theme_for_app_theme(app_theme)
        except AttributeError:
            pass  # App not yet available during compose

        # TextArea with syntax highlighting
        # Syntax theme syncs with app theme (dark→dark, light→light)
        # Available themes: css, dracula, github_light, monokai, vscode_dark
        self._text_area = TextArea(
            self._text,
            language=language,
            read_only=self._read_only,
            show_line_numbers=self._show_line_numbers,
            theme=syntax_theme,
            id="code-text-area",
        )
        # Debug log the language being used
        self.log.info(f"TextArea created with language={language}, theme={syntax_theme}")
        yield self._text_area

        # Footer with position info (optional)
        if self._show_footer:
            yield Static(
                " Ln 1, Col 1",
                classes="editor-footer",
                id="editor-position",
            )

    def on_mount(self) -> None:
        """Called when the editor is mounted."""
        if self._text_area:
            # Apply language after mount to ensure syntax highlighting works
            if self._language:
                self._text_area.language = self._language
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
            except NoMatches:
                pass  # Footer not shown

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
    def language(self) -> str | None:
        """Get the current language."""
        if self._text_area:
            return self._text_area.language
        return self._language

    @language.setter
    def language(self, value: str) -> None:
        """Set the language for syntax highlighting."""
        self._language = value
        if self._text_area:
            # Store cursor position
            cursor = self._text_area.cursor_location
            # Apply language
            self._text_area.language = value
            # Force re-render by touching the text
            text = self._text_area.text
            self._text_area.clear()
            self._text_area.insert(text)
            # Restore cursor
            try:
                self._text_area.cursor_location = cursor
            except (ValueError, IndexError):
                pass  # Invalid cursor position after content change

    @property
    def syntax_theme(self) -> str:
        """Get the current syntax theme."""
        if self._text_area:
            return self._text_area.theme
        return DEFAULT_SYNTAX_THEME

    @syntax_theme.setter
    def syntax_theme(self, value: str) -> None:
        """Set the syntax theme for the TextArea.

        Args:
            value: Theme name (dracula, github_light, monokai, vscode_dark, css)
        """
        if value not in SYNTAX_THEMES:
            value = DEFAULT_SYNTAX_THEME
        if self._text_area:
            self._text_area.theme = value
            self.log.info(f"CodeEditor syntax theme changed to: {value}")

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
            except NoMatches:
                pass  # Header not shown

            self._modified = False
            return True
        except OSError:
            return False  # File read error

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
        except OSError:
            return False  # File write error

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

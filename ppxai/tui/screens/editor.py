"""
EditorScreen - Full-screen file editor.

Provides a full-screen editing experience with:
- Syntax highlighting (via Textual's TextArea)
- Save with Ctrl+S
- Line/column display
- Unsaved changes indicator
"""

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Footer, Static

from ..widgets.code_editor import CodeEditor

from ppxai.tui.keys import get_widget_bindings


class EditorScreen(Screen):
    """Full-screen file editor with syntax highlighting."""

    BINDINGS = get_widget_bindings("EditorScreen")

    def __init__(
        self,
        path: Path,
        content: str,
        line: Optional[int] = None,
        col: Optional[int] = None,
    ):
        """Initialize editor screen.

        Args:
            path: File path (may not exist for new files)
            content: Initial content
            line: Line to jump to
            col: Column to jump to
        """
        super().__init__()
        self._path = path
        self._content = content
        self._line = line
        self._col = col
        self._saved = True  # Track if file has been saved since last edit

    def compose(self) -> ComposeResult:
        """Compose the editor layout."""
        yield Static(
            f" [bold]{self._path.name}[/bold]",
            id="editor-title",
        )
        yield CodeEditor(
            text=self._content,
            filename=str(self._path.name),
            read_only=False,
            id="editor-area",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Handle mount event."""
        self.title = f"Editing: {self._path.name}"

        # Jump to location if specified
        if self._line:
            try:
                editor = self.query_one("#editor-area", CodeEditor)
                editor.goto_line(self._line, self._col or 0)
            except NoMatches:
                pass  # Editor not composed yet

        # Focus the editor
        try:
            editor = self.query_one("#editor-area", CodeEditor)
            editor.focus()
        except NoMatches:
            pass  # Editor not composed yet

    def on_text_area_changed(self, event) -> None:
        """Track unsaved changes."""
        self._saved = False
        self._update_title()

    def _update_title(self) -> None:
        """Update title bar with modified indicator."""
        try:
            title = self.query_one("#editor-title", Static)
            modified = "" if self._saved else " [yellow]●[/yellow]"
            title.update(f" [bold]{self._path.name}[/bold]{modified}")
        except NoMatches:
            pass  # Title widget not found

    def action_save(self) -> None:
        """Save the file."""
        try:
            editor = self.query_one("#editor-area", CodeEditor)
            content = editor.text

            # Ensure parent directory exists
            self._path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            self._path.write_text(content, encoding='utf-8')
            self._saved = True
            self._update_title()

            self.notify(f"Saved: {self._path.name}", title="File Saved")

        except Exception as e:
            self.notify(f"Error saving: {e}", title="Save Failed", severity="error")

    def action_close(self) -> None:
        """Close the editor, prompting if unsaved."""
        if not self._saved:
            # Show confirmation dialog
            self.app.push_screen(
                ConfirmCloseScreen(self._path.name),
                self._handle_close_response,
            )
        else:
            self.app.pop_screen()

    def _handle_close_response(self, save: Optional[bool]) -> None:
        """Handle response from close confirmation.

        Args:
            save: True to save and close, False to discard, None to cancel
        """
        if save is True:
            self.action_save()
            self.app.pop_screen()
        elif save is False:
            self.app.pop_screen()
        # None = cancelled, stay in editor


class ConfirmCloseScreen(Screen):
    """Confirmation dialog for closing with unsaved changes."""

    BINDINGS = get_widget_bindings("ConfirmCloseScreen")

    def __init__(self, filename: str):
        super().__init__()
        self._filename = filename

    def compose(self) -> ComposeResult:
        yield Static(
            f"\n\n[bold yellow]Unsaved changes in {self._filename}[/bold yellow]\n\n"
            "[dim]Press:[/dim]\n"
            "  [cyan]Y[/cyan] - Save and close\n"
            "  [cyan]N[/cyan] - Discard changes\n"
            "  [cyan]Esc[/cyan] - Cancel\n",
            id="confirm-dialog",
        )

    def action_save(self) -> None:
        """Save and close."""
        self.dismiss(True)

    def action_discard(self) -> None:
        """Discard changes and close."""
        self.dismiss(False)

    def action_cancel(self) -> None:
        """Cancel and return to editor."""
        self.dismiss(None)

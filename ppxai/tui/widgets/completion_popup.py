"""
CompletionPopup widget - Shows autocomplete suggestions.

Displays a popup list of completion suggestions that can be navigated
with arrow keys and selected with Enter/Tab.
"""

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.message import Message
from textual.widgets import Static
from textual.widget import Widget


class CompletionPopup(Container):
    """Popup widget showing completion suggestions."""

    class Selected(Message):
        """Message sent when user selects a completion."""

        def __init__(self, completion: str):
            super().__init__()
            self.completion = completion

    class Cancelled(Message):
        """Message sent when user cancels completion."""
        pass

    DEFAULT_CSS = """
    CompletionPopup {
        width: 60;
        height: auto;
        max-height: 10;
        background: $surface;
        border: solid $primary;
        padding: 0 1;
        layer: overlay;
        offset: 2 0;
    }

    CompletionPopup VerticalScroll {
        height: auto;
        max-height: 10;
        border: none;
        padding: 0;
    }

    CompletionPopup .completion-item {
        width: 100%;
        height: 1;
        content-align: left middle;
    }

    CompletionPopup .completion-item:hover {
        background: $primary 20%;
    }

    CompletionPopup .completion-item-selected {
        background: $primary;
        color: $text;
    }

    CompletionPopup .completion-text {
        color: $text;
    }

    CompletionPopup .completion-meta {
        color: $text-muted;
        text-style: italic;
    }
    """

    def __init__(self, completions: list[tuple[str, str]], id: str = None):
        """Initialize completion popup.

        Args:
            completions: List of (text, description) tuples
            id: Widget ID
        """
        super().__init__(id=id)
        self.completions = completions
        self.selected_index = 0

    def compose(self) -> ComposeResult:
        """Build the popup layout."""
        with VerticalScroll():
            for i, (text, desc) in enumerate(self.completions):
                classes = "completion-item"
                if i == self.selected_index:
                    classes += " completion-item-selected"

                if desc:
                    content = f"[bold]{text}[/bold]  [dim]{desc}[/dim]"
                else:
                    content = f"[bold]{text}[/bold]"

                yield Static(content, classes=classes, id=f"completion-{i}")

    def on_key(self, event) -> None:
        """Handle key events."""
        if event.key == "escape":
            event.prevent_default()
            self.post_message(self.Cancelled())
            self.remove()
        elif event.key == "up":
            event.prevent_default()
            self._select_previous()
        elif event.key == "down":
            event.prevent_default()
            self._select_next()
        elif event.key in ("enter", "tab"):
            event.prevent_default()
            if self.completions:
                completion_text = self.completions[self.selected_index][0]
                self.post_message(self.Selected(completion_text))
                self.remove()

    def _select_previous(self) -> None:
        """Select previous completion."""
        if not self.completions:
            return

        self.selected_index = (self.selected_index - 1) % len(self.completions)
        self._update_selection()

    def _select_next(self) -> None:
        """Select next completion."""
        if not self.completions:
            return

        self.selected_index = (self.selected_index + 1) % len(self.completions)
        self._update_selection()

    def _update_selection(self) -> None:
        """Update visual selection."""
        for i in range(len(self.completions)):
            try:
                item = self.query_one(f"#completion-{i}", Static)
                if i == self.selected_index:
                    item.add_class("completion-item-selected")
                else:
                    item.remove_class("completion-item-selected")
            except Exception:
                pass

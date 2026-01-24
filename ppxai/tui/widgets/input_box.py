"""
InputBox widget - Multi-line input with history and command detection.
"""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Input, Static


class InputBox(Static):
    """Input widget with command detection and history."""

    # CSS is in layout.tcss

    class Submitted(Message):
        """Message sent when user submits input."""

        def __init__(self, value: str):
            super().__init__()
            self.value = value

    def __init__(self, id: str = None):
        super().__init__(id=id)
        self._history: list[str] = []
        self._history_index = -1

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("[bold cyan]>[/bold cyan]", classes="prompt")
            yield Input(placeholder="Type a message or /help for commands...")

    def on_mount(self) -> None:
        """Focus the input on mount."""
        self.query_one(Input).focus()

    def focus(self) -> None:
        """Focus the input widget."""
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        value = event.value.strip()
        if value:
            # Add to history
            if not self._history or self._history[-1] != value:
                self._history.append(value)
            self._history_index = -1

            # Clear input
            event.input.value = ""

            # Post our own message
            self.post_message(self.Submitted(value))

    def on_key(self, event) -> None:
        """Handle key events for history navigation."""
        if event.key == "up":
            self._navigate_history(-1)
            event.prevent_default()
        elif event.key == "down":
            self._navigate_history(1)
            event.prevent_default()

    def _navigate_history(self, direction: int) -> None:
        """Navigate through command history."""
        if not self._history:
            return

        input_widget = self.query_one(Input)

        if self._history_index == -1:
            # Starting from current input
            if direction == -1:
                self._history_index = len(self._history) - 1
            else:
                return
        else:
            self._history_index += direction
            if self._history_index < 0:
                self._history_index = 0
            elif self._history_index >= len(self._history):
                self._history_index = -1
                input_widget.value = ""
                return

        if 0 <= self._history_index < len(self._history):
            input_widget.value = self._history[self._history_index]
            input_widget.cursor_position = len(input_widget.value)

    def clear_history(self) -> None:
        """Clear command history."""
        self._history.clear()
        self._history_index = -1

    def get_history(self) -> list[str]:
        """Get command history for persistence."""
        return self._history.copy()

    def set_history(self, history: list[str]) -> None:
        """Set command history from persistence."""
        self._history = history.copy()
        self._history_index = -1

    def insert_text(self, text: str) -> None:
        """Insert text at current cursor position.

        Args:
            text: Text to insert
        """
        input_widget = self.query_one(Input)
        # Append to current value (simple implementation)
        input_widget.value = input_widget.value + text
        input_widget.cursor_position = len(input_widget.value)

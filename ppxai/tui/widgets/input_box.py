"""
InputBox widget - Multi-line input with history and command detection.
"""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Input, Static

from .completion_popup import CompletionPopup


class InputBox(Static):
    """Input widget with command detection and history."""

    # CSS is in layout.tcss

    class Submitted(Message):
        """Message sent when user submits input."""

        def __init__(self, value: str):
            super().__init__()
            self.value = value

    def __init__(self, id: str = None, completer=None):
        super().__init__(id=id)
        self._history: list[str] = []
        self._history_index = -1
        self._completer = completer
        self._completion_popup = None

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
        """Handle key events for history navigation and completion."""
        if event.key == "up":
            self._navigate_history(-1)
            event.prevent_default()
        elif event.key == "down":
            self._navigate_history(1)
            event.prevent_default()
        elif event.key == "tab":
            self._show_completions()
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

    def set_completer(self, completer) -> None:
        """Set the completer for autocomplete.

        Args:
            completer: TextualCompleter instance
        """
        self._completer = completer

    def _show_completions(self) -> None:
        """Show completion popup for current input."""
        if not self._completer:
            return

        # Close existing popup if any
        if self._completion_popup:
            self._completion_popup.remove()
            self._completion_popup = None

        # Get current input text
        input_widget = self.query_one(Input)
        text = input_widget.value

        # Get completions
        completions = self._completer.get_completions(text)

        if not completions:
            return

        # Show completion popup
        self._completion_popup = CompletionPopup(completions)

        # Mount the popup - it will be positioned relative to input
        self.app.mount(self._completion_popup)

        # Focus the popup so it can handle keys
        self._completion_popup.focus()

    def on_completion_popup_selected(self, event: CompletionPopup.Selected) -> None:
        """Handle completion selection."""
        input_widget = self.query_one(Input)
        text = input_widget.value

        # Insert the completion
        # For slash commands, replace the entire command
        if text.startswith('/'):
            # Find space after command
            space_pos = text.find(' ')
            if space_pos == -1:
                # No space, replace entire text
                input_widget.value = event.completion + ' '
            else:
                # Has space, replace just the command part
                parts = text.split(None, 1)
                if len(parts) == 2:
                    # Keep the arguments
                    input_widget.value = event.completion + ' ' + parts[1]
                else:
                    input_widget.value = event.completion + ' '
        # For @context providers, replace from @ to cursor
        elif '@' in text:
            at_pos = text.rfind('@')
            input_widget.value = text[:at_pos] + event.completion + ' '
        else:
            input_widget.value = event.completion + ' '

        # Set cursor to end
        input_widget.cursor_position = len(input_widget.value)

        # Focus back to input
        input_widget.focus()

        # Clear popup reference
        self._completion_popup = None

    def on_completion_popup_cancelled(self, event: CompletionPopup.Cancelled) -> None:
        """Handle completion cancellation."""
        # Focus back to input
        input_widget = self.query_one(Input)
        input_widget.focus()

        # Clear popup reference
        self._completion_popup = None

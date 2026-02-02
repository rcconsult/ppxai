"""
InputBox widget - Multi-line input with history.
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

    class StatusUpdate(Message):
        """Message to update status line with completion info."""

        def __init__(self, text: str):
            super().__init__()
            self.text = text

    def __init__(self, id: str = None, completer=None):
        super().__init__(id=id)
        self._history: list[str] = []
        self._history_index = -1
        self._completer = completer  # NOW USED for tab completion

        # Tab completion state
        self._completion_matches: list[tuple[str, str]] = []  # [(text, description), ...]
        self._completion_index = 0
        self._last_completion_text = ""  # Track when to reset cycle

    def compose(self) -> ComposeResult:
        """Compose the input box."""
        with Horizontal():
            yield Static("[bold cyan]>[/bold cyan]", classes="prompt")
            yield Input(
                placeholder="Type a message or /help for commands...",
                id="chat-input"
            )

    def on_mount(self) -> None:
        """Focus the input on mount."""
        self.query_one(Input).focus()

    def focus(self) -> None:
        """Focus the input widget."""
        try:
            input_widget = self.query_one(Input)
            input_widget.focus()
        except:
            pass

    def disable(self) -> None:
        """Disable the input widget (prevent submission during streaming)."""
        try:
            input_widget = self.query_one(Input)
            input_widget.disabled = True
        except:
            pass

    def enable(self) -> None:
        """Enable the input widget."""
        try:
            input_widget = self.query_one(Input)
            input_widget.disabled = False
            input_widget.focus()
        except:
            pass

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

    def on_input_changed(self, event: Input.Changed) -> None:
        """Reset completion state when user types (not from Tab completion)."""
        if event.input.id != "chat-input":
            return

        # If text changed and it's not our completion, reset cycle
        if event.value != self._last_completion_text:
            self._completion_matches = []
            self._completion_index = 0
            self._last_completion_text = ""

    def on_key(self, event) -> None:
        """Handle key events for history navigation and tab completion."""

        # ============================================================
        # TAB COMPLETION
        # ============================================================
        if event.key == "tab":
            input_widget = self.query_one("#chat-input", Input)

            # Only handle if input is focused
            if not input_widget.has_focus:
                return

            if not self._completer:
                return

            text = input_widget.value

            # First Tab press OR text changed: get new completions
            if text != self._last_completion_text or not self._completion_matches:
                self._completion_matches = self._completer.get_completions(text)
                self._completion_index = 0

            if self._completion_matches:
                # Apply current completion
                completion_text, description = self._completion_matches[self._completion_index]

                # Handle different completion types
                if text.rfind('@') >= 0:
                    # @file/@clipboard/@url completion: replace from @ to end
                    at_pos = text.rfind('@')
                    input_widget.value = text[:at_pos] + completion_text
                elif self._is_file_command(text):
                    # File commands (/show, /edit, /cat): replace from command to end
                    # Example: "/show READ" + Tab → "/show README.md"
                    parts = text.split(None, 1)  # Split on first whitespace
                    if len(parts) == 2:
                        # Has command + partial filename
                        input_widget.value = f"{parts[0]} {completion_text}"
                    else:
                        # Just command, no space yet
                        input_widget.value = f"{parts[0]} {completion_text}"
                elif text.startswith('/'):
                    # Slash command handling - preserve command prefix for subcommands
                    parts = text.split()
                    has_space = text and text[-1].isspace()

                    if len(parts) >= 1 and (len(parts) > 1 or has_space):
                        # Subcommand completion: preserve command prefix
                        # Examples:
                        #   "/provider " + Tab → "/provider perplexity"
                        #   "/model son" + Tab → "/model sonar"
                        #   "/tools ena" + Tab → "/tools enable"
                        cmd = parts[0]
                        if completion_text.startswith('/'):
                            # Completion is a full command - replace entirely
                            input_widget.value = completion_text
                        else:
                            # Completion is a subcommand/argument - preserve prefix
                            input_widget.value = f"{cmd} {completion_text}"
                    else:
                        # Simple command completion: replace entire input
                        input_widget.value = completion_text
                else:
                    # Fallback: replace entire input
                    input_widget.value = completion_text

                # Move cursor to end
                input_widget.cursor_position = len(input_widget.value)

                # Track for state management
                self._last_completion_text = input_widget.value

                # Cycle to next completion for next Tab press
                self._completion_index = (self._completion_index + 1) % len(self._completion_matches)

                # Show status
                status_msg = f"Completed: {completion_text}"
                if len(self._completion_matches) > 1:
                    # Show cycle position (using previous index since we already incremented)
                    current = (self._completion_index - 1) % len(self._completion_matches) + 1
                    total = len(self._completion_matches)
                    status_msg += f" ({current}/{total}) - Press Tab to cycle"

                self.post_message(self.StatusUpdate(status_msg))

                # CRITICAL: Prevent Tab from moving focus
                event.prevent_default()
                event.stop()
            else:
                # No matches
                self.post_message(self.StatusUpdate("No completions available"))
                event.prevent_default()
                event.stop()

            return  # Don't fall through to history navigation

        # ============================================================
        # HISTORY NAVIGATION (existing code)
        # ============================================================
        if event.key == "up":
            self._navigate_history(-1)
            event.prevent_default()
        elif event.key == "down":
            self._navigate_history(1)
            event.prevent_default()

    def _is_file_command(self, text: str) -> bool:
        """Check if text is a file-referencing command (/show, /edit, /cat)."""
        text_lower = text.lower().strip()
        return text_lower.startswith(('/show ', '/edit ', '/cat '))

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
        """Set the completer for tab-based autocomplete.

        Args:
            completer: TextualCompleter instance
        """
        self._completer = completer

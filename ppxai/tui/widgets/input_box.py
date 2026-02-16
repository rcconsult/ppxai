"""
InputBox widget - Multi-line input with history.
"""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Input, Static, TextArea


class ChatTextArea(TextArea):
    """Custom TextArea that handles Ctrl+Enter for submission.

    Ctrl+Enter works in terminals with enhanced keyboard protocol support:
    - Ghostty (with explicit keybind: ctrl+enter=text:\\x1b[13;5u in ~/.config/ghostty/config)
    - Kitty (native support)
    - WezTerm (with enable_kitty_keyboard)

    Ctrl+J is the universal fallback that works in ALL terminals (GNOME Terminal, Konsole, etc.)
    """

    class Submit(Message):
        """Message sent when user presses Ctrl+Enter or Ctrl+J."""
        pass

    # Keys that trigger submission across different terminals:
    # - "ctrl+enter": Primary binding (works in Ghostty/Kitty/WezTerm with proper config)
    # - "ctrl+j": Universal fallback - works in ALL terminals (sends \\n newline character)
    SUBMIT_KEYS = {"ctrl+enter", "ctrl+j"}

    def on_key(self, event) -> None:
        """Handle Ctrl+Enter for submission.

        Using on_key() instead of _on_key() allows Escape to bubble up naturally
        to app-level handlers (for closing panels, help, etc.).
        """
        # Log key events when debug logging is enabled (/debug-log on)
        try:
            if getattr(self.app, "_debug_logging", False):
                from pathlib import Path
                log_path = Path.home() / ".ppxai" / "logs" / "keys.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                k = repr(event.key)
                c = repr(event.character)
                a = repr(event.aliases) if hasattr(event, "aliases") else "N/A"
                with open(log_path, "a") as f:
                    f.write(f"key={k} character={c} aliases={a}\n")
        except Exception:
            pass

        if event.key in self.SUBMIT_KEYS:
            self.post_message(self.Submit())
            event.prevent_default()
            event.stop()
        # All other keys (including Escape, Enter) → let them bubble naturally


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
            yield ChatTextArea(
                "",  # Empty initial content
                id="chat-input",
                show_line_numbers=False,
            )

    def on_mount(self) -> None:
        """Focus the input on mount."""
        text_area = self.query_one(ChatTextArea)
        text_area.focus()

    def focus(self) -> None:
        """Focus the input widget."""
        try:
            text_area = self.query_one(ChatTextArea)
            text_area.focus()
        except NoMatches:
            pass  # Widget not mounted yet

    def disable(self) -> None:
        """Disable the input widget (prevent submission during streaming)."""
        try:
            text_area = self.query_one(ChatTextArea)
            text_area.disabled = True
        except NoMatches:
            pass  # Widget not mounted yet

    def enable(self) -> None:
        """Enable the input widget."""
        try:
            text_area = self.query_one(ChatTextArea)
            text_area.disabled = False
            text_area.focus()
        except NoMatches:
            pass  # Widget not mounted yet

    def on_chat_text_area_submit(self, event: ChatTextArea.Submit) -> None:
        """Handle submission from ChatTextArea (Enter key pressed)."""
        try:
            text_area = self.query_one(ChatTextArea)
            value = text_area.text.strip()

            if value:
                # Add to history
                if not self._history or self._history[-1] != value:
                    self._history.append(value)
                self._history_index = -1

                # Clear input
                text_area.clear()

                # Post our own message
                self.post_message(self.Submitted(value))
        except NoMatches:
            pass

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Reset completion state when user types (not from Tab completion)."""
        if event.text_area.id != "chat-input":
            return

        # If text changed and it's not our completion, reset cycle
        if event.text_area.text != self._last_completion_text:
            self._completion_matches = []
            self._completion_index = 0
            self._last_completion_text = ""

    def on_key(self, event) -> None:
        """Handle key events for history navigation and tab completion."""

        # ============================================================
        # TAB COMPLETION
        # ============================================================
        if event.key == "tab":
            text_area = self.query_one("#chat-input", ChatTextArea)

            # Only handle if input is focused
            if not text_area.has_focus:
                return

            if not self._completer:
                return

            text = text_area.text

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
                    text_area.text = text[:at_pos] + completion_text
                elif self._is_file_command(text):
                    # File commands (/show, /edit, /cat): replace from command to end
                    # Example: "/show READ" + Tab → "/show README.md"
                    parts = text.split(None, 1)  # Split on first whitespace
                    if len(parts) == 2:
                        # Has command + partial filename
                        text_area.text = f"{parts[0]} {completion_text}"
                    else:
                        # Just command, no space yet
                        text_area.text = f"{parts[0]} {completion_text}"
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
                            text_area.text = completion_text
                        else:
                            # Completion is a subcommand/argument - preserve prefix
                            text_area.text = f"{cmd} {completion_text}"
                    else:
                        # Simple command completion: replace entire input
                        text_area.text = completion_text
                else:
                    # Fallback: replace entire input
                    text_area.text = completion_text

                # Move cursor to end
                text_area.move_cursor_relative(rows=999, columns=999)

                # Track for state management
                self._last_completion_text = text_area.text

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

        text_area = self.query_one(ChatTextArea)

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
                text_area.clear()
                return

        if 0 <= self._history_index < len(self._history):
            text_area.text = self._history[self._history_index]
            text_area.move_cursor_relative(rows=999, columns=999)

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
        text_area = self.query_one(ChatTextArea)
        # Insert at cursor position
        text_area.insert(text)
        text_area.move_cursor_relative(columns=len(text))

    def set_completer(self, completer) -> None:
        """Set the completer for tab-based autocomplete.

        Args:
            completer: TextualCompleter instance
        """
        self._completer = completer

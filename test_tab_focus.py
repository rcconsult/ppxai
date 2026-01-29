#!/usr/bin/env python3
"""
Test if Tab key can be intercepted in Textual while keeping focus.

Run: python test_tab_focus.py
"""

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Button, Static


class TestApp(App):
    """Test app to verify Tab interception."""

    CSS = """
    Screen {
        align: center middle;
    }

    Vertical {
        width: 60;
        height: auto;
        border: solid green;
        padding: 1;
    }

    Input {
        margin: 1 0;
    }

    Button {
        margin: 1 0;
    }

    .status {
        color: yellow;
        margin: 1 0;
    }
    """

    def __init__(self):
        super().__init__()
        self.completions = ['/help', '/model', '/provider', '/tools', '/status']
        self.completion_index = 0
        self.last_completions = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Tab Interception Test", classes="status")
            yield Static("Type '/' and press Tab to see autocomplete", classes="status")
            yield Static("Without Tab handler, Tab would move to button below", classes="status")
            yield Input(placeholder="Type / and press Tab...", id="test-input")
            yield Button("Dummy Button (Tab should NOT focus this)", id="dummy-btn")
            yield Static("", id="status-line", classes="status")

    def on_mount(self) -> None:
        """Focus the input on mount."""
        self.query_one("#test-input", Input).focus()

    def on_key(self, event) -> None:
        """Global key handler - intercept Tab before focus navigation."""

        if event.key == "tab":
            input_widget = self.query_one("#test-input", Input)

            # Only handle if input is focused
            if not input_widget.has_focus:
                return

            text = input_widget.value

            # Get matching completions
            if text.startswith('/'):
                matches = [cmd for cmd in self.completions if cmd.startswith(text)]

                if matches:
                    # First Tab or new text: reset index
                    if matches != self.last_completions:
                        self.completion_index = 0
                        self.last_completions = matches

                    # Apply completion
                    input_widget.value = matches[self.completion_index]

                    # Move cursor to end
                    input_widget.cursor_position = len(input_widget.value)

                    # Cycle index for next Tab press
                    self.completion_index = (self.completion_index + 1) % len(matches)

                    # Update status
                    status = f"Completed: {matches[self.completion_index - 1]} "
                    status += f"({self.completion_index}/{len(matches)}) - Press Tab again to cycle"
                    self.query_one("#status-line", Static).update(status)

                    # CRITICAL: Prevent Tab from moving focus
                    event.prevent_default()
                    event.stop()
                else:
                    self.query_one("#status-line", Static).update("No matches found")
                    event.prevent_default()
                    event.stop()
            else:
                self.query_one("#status-line", Static).update("Type '/' first")
                event.prevent_default()
                event.stop()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Reset completion state when text changes."""
        if event.input.id == "test-input":
            # Reset if user types something (not from Tab completion)
            if not event.value.startswith('/'):
                self.last_completions = []
                self.completion_index = 0


if __name__ == "__main__":
    app = TestApp()
    app.run()

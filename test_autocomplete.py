"""
Quick manual test for textual-autocomplete integration.

Run this script to verify autocomplete is working:
    uv run python test_autocomplete.py

Test cases:
1. Type "/" - should show slash commands
2. Type "/sh" - should filter to /show, /show-config, etc.
3. Type "@" - should show @file, @clipboard, @url
4. Type "@file" - should show file completions (if files exist)
5. Press Tab or click to select a completion
6. Press Escape to dismiss dropdown
"""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer

from ppxai.tui.widgets.input_box import InputBox
from ppxai.tui.completer import TextualCompleter


class AutocompleteTestApp(App):
    """Test app for autocomplete functionality."""

    CSS = """
    Screen {
        align: center middle;
    }

    InputBox {
        width: 80;
        height: 3;
        border: solid green;
    }

    #instructions {
        width: 80;
        height: auto;
        margin: 1;
        padding: 1;
        background: $panel;
        border: solid $accent;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the test UI."""
        yield Header()

        # Instructions
        from textual.widgets import Static
        yield Static(
            "[bold]Autocomplete Test[/bold]\n\n"
            "Test cases:\n"
            "1. Type [cyan]/[/cyan] → shows slash commands\n"
            "2. Type [cyan]/sh[/cyan] → filters to /show, /show-config\n"
            "3. Type [cyan]@[/cyan] → shows @file, @clipboard, @url\n"
            "4. Type [cyan]@file[/cyan] → shows file completions\n"
            "5. Press [green]Tab[/green] or [green]Enter[/green] to select\n"
            "6. Press [red]Escape[/red] to dismiss\n"
            "7. Press [red]q[/red] to quit\n",
            id="instructions"
        )

        # Input box with autocomplete
        yield InputBox(id="input-box")

        yield Footer()

    def on_mount(self) -> None:
        """Set up autocomplete on mount."""
        # Initialize completer
        completer = TextualCompleter(
            working_dir=Path.cwd(),
            engine_client=None  # Mock engine client not needed for basic testing
        )

        # Set completer on input box
        input_box = self.query_one("#input-box", InputBox)
        input_box.set_completer(completer)

        # Focus input
        input_box.focus()

    def on_input_box_submitted(self, event: InputBox.Submitted) -> None:
        """Handle input submission."""
        # Show submitted value
        self.notify(f"Submitted: {event.value}")


if __name__ == "__main__":
    app = AutocompleteTestApp()
    app.run()

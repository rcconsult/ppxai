"""
Minimal test to verify input works with AutoComplete.
"""

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input
from textual_autocomplete import AutoComplete, DropdownItem


class SimpleTestApp(App):
    """Minimal test app."""

    def compose(self) -> ComposeResult:
        yield Header()

        # Test 1: Plain Input (should work)
        yield Input(placeholder="Plain input - type here", id="plain")

        # Test 2: Input with AutoComplete
        input_widget = Input(placeholder="Autocomplete input - type here", id="autocomplete")
        yield AutoComplete(
            input_widget,
            candidates=self.get_completions
        )

        yield Footer()

    def get_completions(self, target_state):
        """Simple completion callback."""
        text = target_state.text
        if text.startswith('/'):
            return [
                DropdownItem(main="/show"),
                DropdownItem(main="/edit"),
                DropdownItem(main="/help"),
            ]
        return []


if __name__ == "__main__":
    app = SimpleTestApp()
    app.run()

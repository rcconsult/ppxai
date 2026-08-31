"""
Modal dialog widgets for user interaction.

Provides:
- ConsentDialog - Yes/No/Cancel buttons
- PromptDialog - Text input with OK/Cancel
- MessageDialog - Simple OK acknowledgment
"""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class ConsentDialog(ModalScreen):
    """Modal dialog for yes/no/cancel consent prompts.

    Used for tool consent, session restoration, etc.
    """

    DEFAULT_CSS = """
    ConsentDialog {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    ConsentDialog #dialog-container {
        width: 60;
        height: auto;
        min-height: 12;
        max-height: 25;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    ConsentDialog #dialog-title {
        color: $primary;
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }

    ConsentDialog #dialog-message {
        margin-bottom: 1;
    }

    ConsentDialog #dialog-question {
        text-style: bold;
        margin-bottom: 1;
    }

    ConsentDialog #dialog-buttons {
        height: 3;
        align: center middle;
    }

    ConsentDialog Button {
        min-width: 10;
        margin: 0 1;
    }
    """

    class Responded(Message):
        """Posted when user responds to dialog."""
        def __init__(self, response: str) -> None:
            self.response = response
            super().__init__()

    def __init__(
        self,
        title: str,
        message: str,
        question: str,
        options: list[str] = None,
    ):
        """Initialize consent dialog.

        Args:
            title: Dialog title
            message: Context/explanation message
            question: Question to ask user
            options: List of option labels (default: ["Yes", "No", "Cancel"])
        """
        super().__init__()
        self.dialog_title = title
        self.dialog_message = message
        self.dialog_question = question
        self.options = options or ["Yes", "No", "Cancel"]

    def compose(self) -> ComposeResult:
        """Build dialog layout."""
        with Vertical(id="dialog-container"):
            yield Static(self.dialog_title, id="dialog-title")
            yield Static(self.dialog_message, id="dialog-message")
            yield Static(self.dialog_question, id="dialog-question")

            with Horizontal(id="dialog-buttons"):
                for option in self.options:
                    # First option gets primary variant
                    variant = "primary" if option == self.options[0] else "default"
                    yield Button(option, id=f"btn-{option.lower()}", variant=variant)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        # Extract response from button ID (btn-yes -> yes)
        response = event.button.id.replace("btn-", "")
        self.post_message(self.Responded(response))
        self.dismiss(response)


class PromptDialog(ModalScreen):
    """Modal dialog for text input prompts."""

    class Submitted(Message):
        """Posted when user submits input."""
        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    class Cancelled(Message):
        """Posted when user cancels."""
        pass

    def __init__(
        self,
        title: str,
        message: str,
        prompt: str,
        placeholder: str = "",
        default: str = "",
    ):
        """Initialize prompt dialog.

        Args:
            title: Dialog title
            message: Context message
            prompt: Input field label
            placeholder: Placeholder text
            default: Default input value
        """
        super().__init__()
        self.dialog_title = title
        self.dialog_message = message
        self.dialog_prompt = prompt
        self.placeholder = placeholder
        self.default = default

    def compose(self) -> ComposeResult:
        """Build dialog layout."""
        with Vertical(id="dialog-container"):
            yield Static(self.dialog_title, id="dialog-title")
            yield Static(self.dialog_message, id="dialog-message")
            yield Label(self.dialog_prompt)
            yield Input(
                placeholder=self.placeholder,
                value=self.default,
                id="prompt-input"
            )

            with Horizontal(id="dialog-buttons"):
                yield Button("OK", id="btn-ok", variant="primary")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        """Focus input on mount."""
        self.query_one("#prompt-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "btn-ok":
            value = self.query_one("#prompt-input", Input).value
            self.post_message(self.Submitted(value))
            self.dismiss(value)
        else:
            self.post_message(self.Cancelled())
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
        self.post_message(self.Submitted(event.value))
        self.dismiss(event.value)


class MessageDialog(ModalScreen):
    """Simple message dialog with OK button."""

    def __init__(self, title: str, message: str):
        """Initialize message dialog.

        Args:
            title: Dialog title
            message: Message to display
        """
        super().__init__()
        self.dialog_title = title
        self.dialog_message = message

    def compose(self) -> ComposeResult:
        """Build dialog layout."""
        with Vertical(id="dialog-container"):
            yield Static(self.dialog_title, id="dialog-title")
            yield Static(self.dialog_message, id="dialog-message")

            with Horizontal(id="dialog-buttons"):
                yield Button("OK", id="btn-ok", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        self.dismiss(True)

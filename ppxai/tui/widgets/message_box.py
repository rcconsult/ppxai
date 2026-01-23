"""
MessageBox widget - Individual chat message display.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static, Markdown


class MessageBox(Static):
    """A single chat message with role indicator and content."""

    DEFAULT_CSS = """
    MessageBox {
        width: 100%;
        padding: 1;
        margin-bottom: 1;
    }

    MessageBox.user {
        background: $primary-darken-3;
        border-left: thick $primary;
    }

    MessageBox.assistant {
        background: $surface;
        border-left: thick $success;
    }

    MessageBox.system {
        background: $surface-darken-1;
        border-left: thick $warning;
    }

    MessageBox.tool {
        background: $surface-darken-2;
        border-left: thick $accent;
    }

    MessageBox .role-label {
        color: $text-muted;
        text-style: bold;
        margin-bottom: 1;
    }

    MessageBox .content {
        color: $text;
    }

    MessageBox.streaming .content {
        color: $text-muted;
    }
    """

    content = reactive("")
    streaming = reactive(False)

    ROLE_LABELS = {
        "user": "You",
        "assistant": "Assistant",
        "system": "System",
        "tool": "Tool",
    }

    ROLE_ICONS = {
        "user": "[bold blue]>[/bold blue]",
        "assistant": "[bold green]<[/bold green]",
        "system": "[bold yellow]![/bold yellow]",
        "tool": "[bold cyan]#[/bold cyan]",
    }

    def __init__(
        self,
        content: str = "",
        role: str = "assistant",
        streaming: bool = False,
    ):
        super().__init__()
        self.content = content
        self.role = role
        self.streaming = streaming
        self.add_class(role)
        if streaming:
            self.add_class("streaming")

    def compose(self) -> ComposeResult:
        icon = self.ROLE_ICONS.get(self.role, "")
        label = self.ROLE_LABELS.get(self.role, self.role.title())

        with Vertical():
            yield Static(f"{icon} [bold]{label}[/bold]", classes="role-label")
            yield Static(self.content, classes="content", markup=True)

    def watch_content(self, content: str) -> None:
        """Update content when it changes (for streaming)."""
        try:
            content_widget = self.query_one(".content", Static)
            content_widget.update(content)
        except Exception:
            pass

    def watch_streaming(self, streaming: bool) -> None:
        """Update streaming state."""
        if streaming:
            self.add_class("streaming")
        else:
            self.remove_class("streaming")

    def append_content(self, chunk: str) -> None:
        """Append content chunk (for streaming responses)."""
        self.content += chunk

    def finish_streaming(self) -> None:
        """Mark streaming as complete."""
        self.streaming = False

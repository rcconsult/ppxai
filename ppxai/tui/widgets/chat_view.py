"""
ChatView widget - Scrollable container for chat messages.
"""

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ppxai.tui.widgets.message_box import MessageBox


class ChatView(VerticalScroll):
    """Scrollable container for chat messages."""

    # CSS is in layout.tcss

    def __init__(self, id: str = None):
        super().__init__(id=id)
        self._messages = []

    def add_message(self, content: str, role: str = "assistant") -> None:
        """Add a message to the chat view."""
        message = MessageBox(content=content, role=role)
        self._messages.append(message)
        self.mount(message)
        self.scroll_end(animate=True)

    def add_user_message(self, content: str) -> None:
        """Add a user message."""
        self.add_message(content, role="user")

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message."""
        self.add_message(content, role="assistant")

    def add_system_message(self, content: str) -> None:
        """Add a system/info message."""
        self.add_message(content, role="system")

    def add_tool_message(self, tool_name: str, content: str) -> None:
        """Add a tool call result message."""
        self.add_message(f"[bold cyan]{tool_name}[/bold cyan]\n{content}", role="tool")

    def clear(self) -> None:
        """Clear all messages."""
        for message in self._messages:
            message.remove()
        self._messages.clear()

    def start_streaming(self) -> MessageBox:
        """Start a streaming message and return it for updates."""
        message = MessageBox(content="", role="assistant", streaming=True)
        self._messages.append(message)
        self.mount(message)
        self.scroll_end(animate=True)
        return message

    def get_messages(self) -> list:
        """Get all messages for session save."""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self._messages
        ]

"""
ChatView widget - Scrollable container for chat messages.
"""

import re

from textual.containers import VerticalScroll

from ppxai.tui.widgets.message_box import MessageBox


def _strip_rich_markup(text: str) -> str:
    """Remove Rich markup tags (e.g. [bold cyan], [/red]) leaving plain text.

    Matches only valid Rich tag syntax (identifier-based names), so citation
    markers like [1], [2] and tokens like [DONE] are preserved.
    """
    return re.sub(r'\[/?[a-zA-Z][a-zA-Z0-9_\- ]*(?:=[^\]]+)?\]', '', text)


class ChatView(VerticalScroll):
    """Scrollable container for chat messages."""

    # CSS is in layout.tcss

    def __init__(self, id: str = None):
        super().__init__(id=id)
        self._messages = []

    def add_message(self, content: str, role: str = "assistant", response_time: float = 0.0) -> None:
        """Add a message to the chat view."""
        message = MessageBox(content=content, role=role, response_time=response_time)
        self._messages.append(message)
        self.mount(message)
        # No animation during streaming - reduces visual lag
        self.scroll_end(animate=False)

    def add_user_message(self, content: str) -> None:
        """Add a user message."""
        self.add_message(content, role="user")

    def add_assistant_message(self, content: str, response_time: float = 0.0) -> None:
        """Add an assistant message with optional response time."""
        self.add_message(content, role="assistant", response_time=response_time)

    def add_system_message(self, content: str) -> None:
        """Add a system/info message."""
        self.add_message(content, role="system")

    def add_tool_message(self, tool_name: str, content: str) -> None:
        """Add a tool call result message."""
        clean_name = _strip_rich_markup(tool_name)
        clean_content = _strip_rich_markup(content)
        self.add_message(f"**{clean_name}**\n\n{clean_content}", role="tool")

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
        # No animation during streaming - reduces visual lag
        self.scroll_end(animate=False)
        return message

    def get_messages(self) -> list:
        """Get all messages for session save."""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self._messages
        ]

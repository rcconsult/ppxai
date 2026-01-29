"""
MessageBox widget - Individual chat message display.
"""

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Static, Markdown, Button

from ..clipboard import copy_to_clipboard


class MessageBox(Static):
    """A single chat message with role indicator and content."""

    # CSS is in layout.tcss

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
        response_time: float = 0.0,
    ):
        super().__init__()
        self.content = content
        self.role = role
        self.streaming = streaming
        self.response_time = response_time
        self.timestamp = datetime.now().strftime("%H:%M:%S")
        self.add_class(role)
        if streaming:
            self.add_class("streaming")

    def compose(self) -> ComposeResult:
        icon = self.ROLE_ICONS.get(self.role, "")
        label = self.ROLE_LABELS.get(self.role, self.role.title())
        # Add timestamp like Rich TUI: "Assistant [16:45:27]"
        timestamp_display = f"[dim]\\[{self.timestamp}][/dim]"

        # Add response time badge if provided (assistant messages only)
        if self.response_time > 0 and self.role == "assistant":
            timestamp_display += f" [dim]({self.response_time:.1f}s)[/dim]"

        with Vertical():
            # Header row with role label (no button - moved to footer)
            yield Static(f"{icon} [bold]{label}[/bold] {timestamp_display}", classes="role-label")

            # Tool messages get scrollable content for long outputs
            if self.role == "tool":
                with VerticalScroll(classes="content-scroll"):
                    yield Static(self.content, classes="content", markup=True)
            elif self.role in ("assistant", "user"):
                # Use Markdown widget for proper rendering with clickable URLs
                yield Markdown(self.content, classes="content")
            else:
                # System messages use Rich markup
                yield Static(self.content, classes="content", markup=True)

            # Footer with copy button (v1.15.1 - moved from header to match VSCode)
            if self.role in ("assistant", "tool"):
                with Horizontal(classes="message-footer"):
                    yield Static("", classes="footer-spacer")
                    yield Button("📋 Copy", id="copy-btn", classes="copy-btn", variant="default")

    def watch_content(self, content: str) -> None:
        """Update content when it changes (for streaming)."""
        try:
            # Try Markdown widget first (assistant/user messages)
            content_widget = self.query_one(".content", Markdown)
            content_widget.update(content)
        except NoMatches:
            try:
                # Fall back to Static widget (system/tool messages)
                content_widget = self.query_one(".content", Static)
                content_widget.update(content)
            except NoMatches:
                pass  # Widget not yet composed

    def watch_streaming(self, streaming: bool) -> None:
        """Update streaming state."""
        if streaming:
            self.add_class("streaming")
        else:
            self.remove_class("streaming")

    def append_content(self, chunk: str) -> None:
        """Append content chunk (for streaming responses)."""
        self.content += chunk

    def finish_streaming(self, response_time: float = 0.0) -> None:
        """Mark streaming as complete and optionally set response time."""
        self.streaming = False
        if response_time > 0:
            self.response_time = response_time
            self._update_header()

    def _update_header(self) -> None:
        """Update the header to show response time badge."""
        try:
            role_label = self.query_one(".role-label", Static)
            icon = self.ROLE_ICONS.get(self.role, "")
            label = self.ROLE_LABELS.get(self.role, self.role.title())
            timestamp_display = f"[dim]\\[{self.timestamp}][/dim]"

            # Add response time badge if set
            if self.response_time > 0 and self.role == "assistant":
                timestamp_display += f" [dim]({self.response_time:.1f}s)[/dim]"

            role_label.update(f"{icon} [bold]{label}[/bold] {timestamp_display}")
        except Exception:
            pass  # Widget not yet composed

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle copy button click (v1.15.0)."""
        if event.button.id == "copy-btn":
            event.stop()
            # Copy the raw content (without markdown rendering)
            success = copy_to_clipboard(self.content)
            if success:
                # Show feedback by changing button text temporarily
                event.button.label = "✓"
                event.button.add_class("copied")
                # Reset after 1.5 seconds
                self.set_timer(1.5, lambda: self._reset_copy_button(event.button))
            else:
                # Clipboard not available - show red X and notify user
                event.button.label = "✗"
                event.button.add_class("failed")
                self.notify(
                    "Clipboard unavailable. Install xclip, xsel, or wl-clipboard.",
                    title="Copy Failed",
                    severity="error",
                    timeout=4,
                )
                self.set_timer(1.5, lambda: self._reset_copy_button(event.button))

    def _reset_copy_button(self, button: Button) -> None:
        """Reset copy button to original state."""
        button.label = "📋"
        button.remove_class("copied")
        button.remove_class("failed")

"""
MessageBox widget - Individual chat message display.
"""

from datetime import datetime
from typing import Any, List

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Static, Markdown, Button

from ..clipboard import copy_to_clipboard


def _normalize_content_to_text(content: Any) -> str:
    """Flatten multimodal Message.content (str | list[dict]) to display text.

    Image / file parts are rendered as `[Image: name]` / `[File: name]`
    placeholders so the user sees *something* for attached media rather than
    a silently truncated bubble. This mirrors Message.text_content() but is
    duplicated here to keep widgets free of engine imports.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts: List[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "image_url":
            name = block.get("name") or "image"
            parts.append(f"[Image: {name}]")
        elif btype in ("input_file", "file"):
            name = block.get("name") or block.get("filename") or "file"
            parts.append(f"[File: {name}]")
        elif btype == "uploaded_file":
            # R5 (v1.17.6): first-class uploaded_file content block.
            # Mirror Message.text_content()'s rendering so the ppxaide
            # MessageBox stays consistent with Rich TUI, web, and
            # VSCode clients — all four show `[File: name (media_type)]`.
            name = block.get("name") or "file"
            media = block.get("media_type") or ""
            parts.append(f"[File: {name} ({media})]" if media else f"[File: {name}]")
        else:
            parts.append(f"[{btype or 'part'}]")
    return "\n".join(parts)


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
        content: Any = "",
        role: str = "assistant",
        streaming: bool = False,
        response_time: float = 0.0,
    ):
        super().__init__()
        # Widget always displays plain text; multimodal list content is
        # flattened to text + placeholders. Streaming chunks (appended later)
        # are always strings so the reactive field stays str-typed.
        self.content = _normalize_content_to_text(content)
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

            if self.role == "tool":
                # Tool output uses Markdown (safe — Rich markup stripped by chat_view)
                with VerticalScroll(classes="content-scroll"):
                    yield Markdown(self.content, classes="content")
            elif self.role in ("assistant", "user"):
                yield Markdown(self.content, classes="content")
            else:
                # System messages use Rich markup for colored status indicators
                yield Static(self.content, classes="content", markup=True)

            # Footer with copy button (v1.15.1 - moved from header to match VSCode)
            if self.role in ("assistant", "tool"):
                with Horizontal(classes="message-footer"):
                    yield Static("", classes="footer-spacer")
                    yield Button("📋 Copy", id="copy-btn", classes="copy-btn", variant="default")

    def watch_content(self, content: str) -> None:
        """Update content when it changes (for streaming)."""
        try:
            self.query_one(".content", Markdown).update(content)
        except NoMatches:
            try:
                self.query_one(".content", Static).update(content)
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

"""
PPXAIDEApp - Main Textual application for ppxaide.

This is the core application class that manages:
- Screen layout and navigation
- Engine client connection
- Theme management
- Keyboard bindings
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Input, RichLog

from ppxai.tui.widgets.status_bar import StatusBar
from ppxai.tui.widgets.chat_view import ChatView
from ppxai.tui.widgets.input_box import InputBox
from ppxai.tui.themes.themes import CUSTOM_THEMES, DEFAULT_THEME, CYCLE_THEMES
from ppxai.tui.clipboard import copy_to_clipboard, paste_from_clipboard, is_clipboard_available


class PPXAIDEApp(App):
    """Main ppxaide application."""

    TITLE = "ppxaide"
    SUB_TITLE = "AI Assistant"

    CSS_PATH = "themes/layout.tcss"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear", "Clear", show=True),
        Binding("ctrl+t", "cycle_theme", "Theme", show=True),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self):
        super().__init__()
        self._current_theme_index = 0
        self._engine_client = None
        self._provider = "perplexity"
        self._model = "sonar"
        self._tools_enabled = False

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header()
        yield StatusBar(
            provider=self._provider,
            model=self._model,
            tools_enabled=self._tools_enabled,
        )
        yield ChatView(id="chat-view")
        yield InputBox(id="input-box")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.title = "ppxaide"
        self.sub_title = f"{self._provider}/{self._model}"

        # Register custom themes (built-in themes like catppuccin-mocha are already available)
        for theme in CUSTOM_THEMES.values():
            self.register_theme(theme)

        # Set initial theme (catppuccin-mocha by default)
        self.theme = DEFAULT_THEME

        # Focus the input box
        input_box = self.query_one("#input-box", InputBox)
        input_box.focus()

        # Add welcome message
        chat_view = self.query_one("#chat-view", ChatView)
        chat_view.add_system_message(
            "Welcome to ppxaide! Type a message or use /help for commands.\n"
            "[dim]Use Ctrl+T to cycle themes, or Ctrl+P for all themes.[/dim]"
        )

    async def on_input_box_submitted(self, event: InputBox.Submitted) -> None:
        """Handle user input submission."""
        message = event.value.strip()
        if not message:
            return

        chat_view = self.query_one("#chat-view", ChatView)

        # Handle commands
        if message.startswith("/"):
            await self._handle_command(message)
            return

        # Add user message to chat
        chat_view.add_user_message(message)

        # TODO: Send to engine client and stream response
        # For now, show a placeholder
        chat_view.add_assistant_message(
            f"[dim]Engine connection not implemented yet. You said: {message}[/dim]"
        )

    async def _handle_command(self, command: str) -> None:
        """Handle slash commands."""
        chat_view = self.query_one("#chat-view", ChatView)
        parts = command[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "help":
            chat_view.add_system_message(self._get_help_text())
        elif cmd == "quit" or cmd == "q":
            self.exit()
        elif cmd == "clear":
            chat_view.clear()
        elif cmd == "theme":
            self.action_cycle_theme()
            chat_view.add_system_message(
                f"Theme: {CYCLE_THEMES[self._current_theme_index]}"
            )
        elif cmd == "provider":
            chat_view.add_system_message(
                f"Current provider: {self._provider}\n"
                "[dim]Provider switching not implemented yet[/dim]"
            )
        elif cmd == "model":
            chat_view.add_system_message(
                f"Current model: {self._model}\n"
                "[dim]Model switching not implemented yet[/dim]"
            )
        elif cmd == "copy":
            # Copy last assistant message to clipboard
            messages = chat_view.get_messages()
            assistant_msgs = [m for m in messages if m["role"] == "assistant"]
            if assistant_msgs:
                if copy_to_clipboard(assistant_msgs[-1]["content"]):
                    self.notify("Copied to clipboard", title="Copy")
                else:
                    chat_view.add_system_message(
                        "[yellow]Clipboard not available[/yellow]"
                    )
            else:
                chat_view.add_system_message(
                    "[dim]No assistant messages to copy[/dim]"
                )
        elif cmd == "paste":
            # Paste from clipboard into input
            text = paste_from_clipboard()
            if text:
                input_box = self.query_one("#input-box", InputBox)
                input_box.insert_text(text)
            else:
                chat_view.add_system_message(
                    "[dim]Clipboard is empty or unavailable[/dim]"
                )
        else:
            chat_view.add_system_message(
                f"[yellow]Unknown command: /{cmd}[/yellow]\n"
                "Type /help for available commands."
            )

    def _get_help_text(self) -> str:
        """Get help text for available commands."""
        return """[bold]Available Commands:[/bold]

[cyan]/help[/cyan]      - Show this help message
[cyan]/quit[/cyan]      - Exit ppxaide
[cyan]/clear[/cyan]     - Clear chat history
[cyan]/theme[/cyan]     - Cycle through themes
[cyan]/provider[/cyan]  - Show/switch provider
[cyan]/model[/cyan]     - Show/switch model
[cyan]/copy[/cyan]      - Copy last response to clipboard
[cyan]/paste[/cyan]     - Paste from clipboard to input

[bold]Keyboard Shortcuts:[/bold]
[cyan]Ctrl+C[/cyan]     - Quit
[cyan]Ctrl+L[/cyan]     - Clear chat
[cyan]Ctrl+T[/cyan]     - Cycle theme (8 curated themes)
[cyan]Ctrl+P[/cyan]     - Command palette (all 17+ themes)
[cyan]Enter[/cyan]      - Send message
"""

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()

    def action_clear(self) -> None:
        """Clear the chat view."""
        chat_view = self.query_one("#chat-view", ChatView)
        chat_view.clear()

    def action_cycle_theme(self) -> None:
        """Cycle through curated themes (Ctrl+T)."""
        self._current_theme_index = (self._current_theme_index + 1) % len(CYCLE_THEMES)
        theme_name = CYCLE_THEMES[self._current_theme_index]
        self.theme = theme_name
        self.notify(f"Theme: {theme_name}", title="Theme Changed")

    def action_cancel(self) -> None:
        """Cancel current operation."""
        # TODO: Cancel streaming response if in progress
        pass

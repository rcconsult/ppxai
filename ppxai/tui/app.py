"""
PPXAIDEApp - Main Textual application for ppxaide.

This is the core application class that manages:
- Screen layout and navigation
- Engine client connection
- Theme management
- Keyboard bindings
- Split view for file viewing/editing
"""

import os
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Input, RichLog

from ppxai.tui.widgets.status_bar import StatusBar
from ppxai.tui.widgets.chat_view import ChatView
from ppxai.tui.widgets.input_box import InputBox
from ppxai.tui.widgets.side_panel import SidePanel
from ppxai.tui.widgets.code_editor import CodeEditor, get_syntax_theme_for_app_theme
from ppxai.tui.themes.themes import CUSTOM_THEMES, DEFAULT_THEME, CYCLE_THEMES
from ppxai.tui.clipboard import copy_to_clipboard, paste_from_clipboard, is_clipboard_available
from ppxai.tui import commands as local_commands


class PPXAIDEApp(App):
    """Main ppxaide application."""

    TITLE = "ppxaide"
    SUB_TITLE = "AI Assistant"

    CSS_PATH = "themes/layout.tcss"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear", "Clear", show=True),
        Binding("ctrl+t", "cycle_theme", "Theme", show=True),
        Binding("ctrl+w", "close_panel", "Close", show=False),
        Binding("ctrl+s", "save_panel", "Save", show=False),
        Binding("f6", "toggle_focus", "Switch Pane", show=False),
        Binding("ctrl+tab", "toggle_focus", "Switch Pane", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        # Split resize bindings (use ctrl+[ and ctrl+] to avoid conflict with text navigation)
        Binding("ctrl+left_square_bracket", "resize_panel('left')", "Shrink Panel", show=False),
        Binding("ctrl+right_square_bracket", "resize_panel('right')", "Grow Panel", show=False),
    ]

    # Split ratio presets (chat% : panel%)
    SPLIT_RATIOS = [30, 40, 50, 60, 70]
    DEFAULT_SPLIT_INDEX = 2  # 50%

    def __init__(self):
        super().__init__()
        self._current_theme_index = 0
        self._engine_client = None
        self._provider = "perplexity"
        self._model = "sonar"
        self._tools_enabled = False
        self._working_dir = os.getcwd()
        self._split_index = self.DEFAULT_SPLIT_INDEX  # Current split ratio index

    def compose(self) -> ComposeResult:
        """Compose the application layout with split view support."""
        yield Header()
        yield StatusBar(
            provider=self._provider,
            model=self._model,
            tools_enabled=self._tools_enabled,
        )
        # Main content area: horizontal split (chat left, panel right)
        with Horizontal(id="main-content"):
            # Left pane: chat + input
            with Vertical(id="chat-pane"):
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")
            # Right pane: side panel (hidden by default)
            yield SidePanel(id="side-panel")
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

    def watch_theme(self, old_theme: str, new_theme: str) -> None:
        """Called when the app theme changes - sync syntax highlighting themes.

        Args:
            old_theme: Previous theme name
            new_theme: New theme name
        """
        # Get the appropriate syntax theme for the new app theme
        syntax_theme = get_syntax_theme_for_app_theme(new_theme)

        # Update all CodeEditor widgets in the app
        for editor in self.query(CodeEditor):
            editor.syntax_theme = syntax_theme

        self.log.info(f"Theme changed: {old_theme} → {new_theme}, syntax: {syntax_theme}")

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
        elif cmd in ("quit", "q", "exit"):
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
        # File commands
        elif cmd == "show":
            await local_commands.cmd_show(self, args)
        elif cmd == "edit":
            await local_commands.cmd_edit(self, args)
        # Navigation commands
        elif cmd == "cd":
            await local_commands.cmd_cd(self, args)
        elif cmd == "pwd":
            await local_commands.cmd_pwd(self, args)
        # Status and debug commands
        elif cmd == "status":
            await local_commands.cmd_status(self, args)
        elif cmd == "debug":
            await local_commands.cmd_debug(self, args)
        elif cmd == "badge":
            # Test badge API: /badge add test "Test" "value"
            # /badge update test "new_value"
            # /badge remove test
            # /badge hide test
            # /badge show test
            await self._handle_badge_command(args)
        else:
            chat_view.add_system_message(
                f"[yellow]Unknown command: /{cmd}[/yellow]\n"
                "Type /help for available commands."
            )

    async def _handle_badge_command(self, args: str) -> None:
        """Handle badge testing commands.

        Usage:
            /badge add <id> <label> <value> [variant]
            /badge update <id> <value>
            /badge remove <id>
            /badge hide <id>
            /badge show <id>
            /badge list
        """
        chat_view = self.query_one("#chat-view", ChatView)
        status_bar = self.query_one(StatusBar)

        parts = args.split(maxsplit=1)
        if not parts:
            chat_view.add_system_message(
                "[yellow]Usage:[/yellow]\n"
                "/badge add <id> <label> <value> [variant]\n"
                "/badge update <id> <value>\n"
                "/badge remove <id>\n"
                "/badge hide <id>\n"
                "/badge show <id>\n"
                "/badge list"
            )
            return

        action = parts[0].lower()
        remaining = parts[1] if len(parts) > 1 else ""

        if action == "add":
            # Parse: id label value [variant]
            tokens = remaining.split(maxsplit=3)
            if len(tokens) < 3:
                chat_view.add_system_message(
                    "[yellow]Usage:[/yellow] /badge add <id> <label> <value> [variant]"
                )
                return
            badge_id = tokens[0]
            label = tokens[1]
            value = tokens[2]
            variant = tokens[3] if len(tokens) > 3 else "default"
            status_bar.add_badge(badge_id, label, value, variant)
            chat_view.add_system_message(f"Added badge: {badge_id}")

        elif action == "update":
            # Parse: id value
            tokens = remaining.split(maxsplit=1)
            if len(tokens) < 2:
                chat_view.add_system_message(
                    "[yellow]Usage:[/yellow] /badge update <id> <value>"
                )
                return
            badge_id = tokens[0]
            value = tokens[1]
            status_bar.update_badge(badge_id, value)
            chat_view.add_system_message(f"Updated badge: {badge_id}")

        elif action == "remove":
            badge_id = remaining.strip()
            if not badge_id:
                chat_view.add_system_message(
                    "[yellow]Usage:[/yellow] /badge remove <id>"
                )
                return
            status_bar.remove_badge(badge_id)
            chat_view.add_system_message(f"Removed badge: {badge_id}")

        elif action == "hide":
            badge_id = remaining.strip()
            if not badge_id:
                chat_view.add_system_message(
                    "[yellow]Usage:[/yellow] /badge hide <id>"
                )
                return
            status_bar.hide_badge(badge_id)
            chat_view.add_system_message(f"Hidden badge: {badge_id}")

        elif action == "show":
            badge_id = remaining.strip()
            if not badge_id:
                chat_view.add_system_message(
                    "[yellow]Usage:[/yellow] /badge show <id>"
                )
                return
            status_bar.show_badge(badge_id)
            chat_view.add_system_message(f"Shown badge: {badge_id}")

        elif action == "list":
            badges = list(status_bar._badges.keys())
            if badges:
                chat_view.add_system_message(f"Badges: {', '.join(badges)}")
            else:
                chat_view.add_system_message("No badges")
        else:
            chat_view.add_system_message(f"[yellow]Unknown badge action:[/yellow] {action}")

    def _get_help_text(self) -> str:
        """Get help text for available commands."""
        # Use raw string to avoid escape sequence warnings
        help_text = (
            "[bold]Available Commands:[/bold]\n\n"
            "[bold dim]System:[/bold dim]\n"
            "[cyan]/help[/cyan]      - Show this help message\n"
            "[cyan]/quit[/cyan]      - Exit ppxaide (aliases: /q, /exit)\n"
            "[cyan]/clear[/cyan]     - Clear chat history\n"
            "[cyan]/theme[/cyan]     - Cycle through themes\n"
            "[cyan]/status[/cyan]    - Show status information\n"
            "[cyan]/debug[/cyan]     - Show image viewer debug info\n\n"
            "[bold dim]Files:[/bold dim]\n"
            "[cyan]/show[/cyan]      - Display file (syntax/tree view)\n"
            "[cyan]/edit[/cyan]      - Edit file with syntax highlighting\n\n"
            "[bold dim]Navigation:[/bold dim]\n"
            "[cyan]/cd[/cyan]        - Change working directory\n"
            "[cyan]/pwd[/cyan]       - Show working directory\n\n"
            "[bold dim]Clipboard:[/bold dim]\n"
            "[cyan]/copy[/cyan]      - Copy last response to clipboard\n"
            "[cyan]/paste[/cyan]     - Paste from clipboard to input\n\n"
            "[bold dim]AI (coming soon):[/bold dim]\n"
            "[cyan]/provider[/cyan]  - Show/switch provider\n"
            "[cyan]/model[/cyan]     - Show/switch model\n\n"
            "[bold]Keyboard Shortcuts:[/bold]\n"
            "[cyan]Ctrl+C[/cyan]     - Quit\n"
            "[cyan]Ctrl+L[/cyan]     - Clear chat\n"
            "[cyan]Ctrl+T[/cyan]     - Cycle theme (8 curated themes)\n"
            "[cyan]Ctrl+P[/cyan]     - Command palette (all 17+ themes)\n"
            "[cyan]Ctrl+W[/cyan]     - Close side panel\n"
            "[cyan]Ctrl+S[/cyan]     - Save (in edit mode)\n"
            "[cyan]F6[/cyan]         - Switch focus between panes\n"
            "[cyan]Ctrl+Tab[/cyan]   - Switch focus between panes\n"
            "[cyan]Ctrl+Bracket[/cyan] - Resize split panes\n"
            "[cyan]Escape[/cyan]     - Close panel / Cancel\n"
            "[cyan]Enter[/cyan]      - Send message\n"
        )
        return help_text

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
        """Cancel current operation or close side panel."""
        side_panel = self.query_one("#side-panel", SidePanel)
        if side_panel.is_open:
            side_panel.close()
        # TODO: Cancel streaming response if in progress

    def action_close_panel(self) -> None:
        """Close the side panel (Ctrl+W)."""
        side_panel = self.query_one("#side-panel", SidePanel)
        if side_panel.is_open:
            side_panel.close()

    def action_save_panel(self) -> None:
        """Save the side panel content (Ctrl+S)."""
        side_panel = self.query_one("#side-panel", SidePanel)
        if side_panel.is_open:
            side_panel.save()

    def action_toggle_focus(self) -> None:
        """Toggle focus between chat input and side panel (F6 / Ctrl+Tab)."""
        side_panel = self.query_one("#side-panel", SidePanel)
        input_box = self.query_one("#input-box", InputBox)

        if not side_panel.is_open:
            # No panel open, keep focus on input
            input_box.focus()
            return

        # Check if side panel has focus (or any of its children)
        focused = self.focused
        if focused and side_panel in focused.ancestors_with_self:
            # Focus is in side panel, move to input
            input_box.focus()
        else:
            # Focus is elsewhere, move to side panel
            side_panel.focus()

    def action_resize_panel(self, direction: str) -> None:
        """Resize the split panel (Ctrl+[/]).

        Args:
            direction: 'left' to move divider left (grow chat, shrink panel)
                      'right' to move divider right (shrink chat, grow panel)
        """
        side_panel = self.query_one("#side-panel", SidePanel)
        if not side_panel.is_open:
            return

        # Adjust split index
        # Ctrl+[ (left) → move divider left → decrease chat% (shrink panel)
        # Ctrl+] (right) → move divider right → increase chat% (grow panel)
        if direction == "left" and self._split_index > 0:
            self._split_index -= 1  # Less chat, more panel (divider moves left)
        elif direction == "right" and self._split_index < len(self.SPLIT_RATIOS) - 1:
            self._split_index += 1  # More chat, less panel (divider moves right)
        else:
            return  # At limit

        self._apply_split_ratio()
        chat_pct = self.SPLIT_RATIOS[self._split_index]
        self.notify(f"Split: {chat_pct}% / {100 - chat_pct}%", title="Resize")

    def _apply_split_ratio(self) -> None:
        """Apply the current split ratio to chat and panel panes."""
        chat_pct = self.SPLIT_RATIOS[self._split_index]
        panel_pct = 100 - chat_pct

        chat_pane = self.query_one("#chat-pane")
        side_panel = self.query_one("#side-panel", SidePanel)

        # Update widths dynamically
        chat_pane.styles.width = f"{chat_pct}%"
        side_panel.styles.width = f"{panel_pct}%"

    def on_side_panel_opened(self, event: SidePanel.Opened) -> None:
        """Handle side panel opened - adjust layout."""
        try:
            # Shrink chat pane to make room for side panel
            chat_pane = self.query_one("#chat-pane")
            chat_pane.add_class("split-active")
            # Apply current split ratio
            self._apply_split_ratio()
            # Make input box taller when split view is active
            input_box = self.query_one("#input-box", InputBox)
            input_box.add_class("split-mode")
        except Exception:
            # In test mode or special screens, widgets might not exist
            pass

    def on_side_panel_closed(self, event: SidePanel.Closed) -> None:
        """Handle side panel closed - restore layout."""
        try:
            # Restore chat pane to full width
            chat_pane = self.query_one("#chat-pane")
            chat_pane.remove_class("split-active")
            chat_pane.styles.width = "100%"
            # Restore input box height
            input_box = self.query_one("#input-box", InputBox)
            input_box.remove_class("split-mode")
            # Refocus input after closing panel
            input_box.focus()
            # Reset split ratio to default for next time
            self._split_index = self.DEFAULT_SPLIT_INDEX
        except Exception:
            # In test mode or special screens, widgets might not exist
            pass

    async def show_file_in_panel(
        self,
        path: Path,
        content: str,
        mode: str = "code",
        line: Optional[int] = None,
        col: Optional[int] = None,
        read_only: bool = True,
    ) -> None:
        """Show a file in the side panel.

        Args:
            path: File path
            content: File content
            mode: "code", "tree", "markdown", or "image"
            line: Line to jump to
            col: Column to jump to
            read_only: Whether content is read-only (False for /edit)
        """
        side_panel = self.query_one("#side-panel", SidePanel)
        await side_panel.show_file(path, content, mode, line, col, read_only)

    def close_side_panel(self) -> None:
        """Close the side panel."""
        side_panel = self.query_one("#side-panel", SidePanel)
        side_panel.close()

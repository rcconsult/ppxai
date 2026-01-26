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

# Engine integration (Phase 6.1)
from ppxai.engine import EngineClient
from ppxai.engine.types import Event, EventType
from ppxai.config import get_default_provider, get_default_model, get_api_key

# Command Factory integration (Phase 6.1.1 - Technical debt cleanup)
from ppxai.commands import CommandFactory
from ppxai.commands.protocol import CommandContext
from ppxai.commands.results import CommandResult
from ppxai.rendering.textual_renderer import TextualRenderer


class PPXAIDEApp(App):
    """Main ppxaide application.

    Implements CommandContext protocol for command factory integration.
    """

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
        self._engine_client: Optional[EngineClient] = None
        self._provider = "perplexity"
        self._model = "sonar"
        self._tools_enabled = False
        self._working_dir = os.getcwd()
        self._split_index = self.DEFAULT_SPLIT_INDEX  # Current split ratio index

        # Streaming state (Phase 6.1)
        self._current_message_content = ""
        self._is_streaming = False

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
        # Initialize engine client (Phase 6.1)
        self._initialize_engine()

        self.title = "ppxaide"
        self.sub_title = f"{self._provider}/{self._model}"

        # Register custom themes (built-in themes like catppuccin-mocha are already available)
        for theme in CUSTOM_THEMES.values():
            self.register_theme(theme)

        # Set initial theme (catppuccin-mocha by default)
        self.theme = DEFAULT_THEME

        # Update status bar with engine state (Phase 6.1)
        status_bar = self.query_one(StatusBar)
        status_bar.update_badge("provider", self._provider)
        status_bar.update_badge("model", self._model)

        # Show bootstrap context status (Phase 6.3)
        if self._engine_client:
            bootstrap_status = self._engine_client.get_bootstrap_status()
            if bootstrap_status["loaded"]:
                sources = bootstrap_status.get("sources", [])
                if sources:
                    # Add context badge to status bar
                    scopes = [src["scope"] for src in sources]
                    scope_text = "/".join(scopes)  # e.g., "global/project" or "project"
                    status_bar.add_badge("context", "Context", scope_text)
                    self.log.info(f"Bootstrap context loaded: {scope_text}")

        # Focus the input box
        input_box = self.query_one("#input-box", InputBox)
        input_box.focus()

        # Add welcome message with bootstrap status (Phase 6.3)
        chat_view = self.query_one("#chat-view", ChatView)
        welcome_msg = f"Welcome to ppxaide! Connected to {self._provider}/{self._model}\n"

        # Add bootstrap context info if loaded
        if self._engine_client:
            bootstrap_status = self._engine_client.get_bootstrap_status()
            if bootstrap_status["loaded"]:
                sources = bootstrap_status.get("sources", [])
                char_count = bootstrap_status.get("char_count", 0)
                welcome_msg += f"[dim]Bootstrap context: {len(sources)} file(s), ~{char_count} chars[/dim]\n"

        welcome_msg += (
            "Type a message or use /help for commands.\n"
            "[dim]Use Ctrl+T to cycle themes, or Ctrl+P for all themes.[/dim]"
        )
        chat_view.add_system_message(welcome_msg)

    def _initialize_engine(self) -> None:
        """Initialize the engine client (Phase 6.1).

        Sets up:
        - Provider and model from config
        - Engine client instance
        - Working directory
        - Bootstrap context (Phase 6.3)
        """
        # Load config
        self._provider = get_default_provider()
        self._model = get_default_model(self._provider)

        # Create engine client (automatically loads bootstrap context)
        self._engine_client = EngineClient()

        # Set provider and model
        try:
            self._engine_client.set_provider(self._provider)
            self._engine_client.set_model(self._model)
        except Exception as e:
            self.log.error(f"Failed to initialize engine: {e}")
            # Fall back to defaults
            self._provider = "perplexity"
            self._model = "sonar"

        # Set working directory
        self._engine_client.set_working_dir(self._working_dir)

        self.log.info(f"Engine initialized: {self._provider}/{self._model}")

    # ========================================================================
    # CommandContext Protocol Implementation (Phase 6.1.1)
    # ========================================================================

    @property
    def engine_client(self) -> EngineClient:
        """Access to engine client (CommandContext protocol)."""
        return self._engine_client

    @property
    def session(self):
        """Access to current session (CommandContext protocol)."""
        return self._engine_client.session if self._engine_client else None

    @property
    def working_dir(self) -> str:
        """Current working directory (CommandContext protocol)."""
        return self._working_dir

    @property
    def current_model(self) -> str:
        """Currently selected model (CommandContext protocol)."""
        return self._model

    @property
    def provider(self) -> str:
        """Currently selected provider (CommandContext protocol)."""
        return self._provider

    def set_model(self, model: str) -> None:
        """Switch to specified model (CommandContext protocol)."""
        if self._engine_client:
            self._engine_client.set_model(model)
            self._model = model
            # Update status bar
            status_bar = self.query_one(StatusBar)
            status_bar.update_badge("model", model)

    def set_provider(self, provider: str) -> None:
        """Switch to specified provider (CommandContext protocol)."""
        if self._engine_client:
            self._engine_client.set_provider(provider)
            self._provider = provider
            # Update status bar
            status_bar = self.query_one(StatusBar)
            status_bar.update_badge("provider", provider)

    def get_provider(self) -> str:
        """Get current provider (CommandContext protocol)."""
        return self._provider

    def get_model(self) -> str:
        """Get current model (CommandContext protocol)."""
        return self._model

    def get_auto_route(self) -> bool:
        """Get auto-routing status (CommandContext protocol)."""
        # TUI doesn't support auto-routing yet
        return False

    def set_auto_route(self, enabled: bool) -> None:
        """Set auto-routing status (CommandContext protocol)."""
        # TUI doesn't support auto-routing yet
        pass

    def get_tools_available(self) -> bool:
        """Check if tool support is available (CommandContext protocol)."""
        return self._tools_enabled

    def get_tools_verbose(self) -> bool:
        """Get tool verbose logging status (CommandContext protocol)."""
        # TUI doesn't have verbose tool logging yet
        return False

    def set_tools_verbose(self, verbose: bool) -> None:
        """Set tool verbose logging status (CommandContext protocol)."""
        # TUI doesn't have verbose tool logging yet
        pass

    @property
    def tools_enabled(self) -> bool:
        """Check if tools are enabled (CommandContext protocol)."""
        return self._tools_enabled

    @property
    def autoroute_enabled(self) -> bool:
        """Check if auto-routing is enabled (CommandContext protocol)."""
        return False

    # ========================================================================
    # Theme Management
    # ========================================================================

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
        """Handle user input submission (Phase 6.1 - Engine integration)."""
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

        # Stream response from engine
        if self._engine_client:
            await self._stream_response(message)
        else:
            chat_view.add_system_message(
                "[yellow]Engine not initialized[/yellow]"
            )

    async def _stream_response(self, user_input: str) -> None:
        """Stream AI response from engine (Phase 6.1).

        Args:
            user_input: User's message
        """
        chat_view = self.query_one("#chat-view", ChatView)

        # Reset streaming state
        self._current_message_content = ""
        self._is_streaming = True

        try:
            # Stream events from engine
            async for event in self._engine_client.chat(user_input, stream=True):
                await self._handle_event(event)

        except Exception as e:
            self.log.error(f"Stream error: {e}")
            chat_view.add_system_message(f"[red]Error:[/red] {e}")
        finally:
            self._is_streaming = False

    async def _handle_event(self, event: Event) -> None:
        """Handle engine events during streaming (Phase 6.1).

        Args:
            event: Engine event
        """
        chat_view = self.query_one("#chat-view", ChatView)

        if event.type == EventType.STREAM_START:
            # Start accumulating response
            self._current_message_content = ""

        elif event.type == EventType.STREAM_CHUNK:
            # Accumulate chunk
            self._current_message_content += event.data

        elif event.type == EventType.STREAM_END:
            # Finalize and display
            chat_view.add_assistant_message(self._current_message_content)
            self._current_message_content = ""

            # Update usage stats in status bar (Phase 6.4)
            self._update_usage_display()

        elif event.type == EventType.TOOL_CALL:
            # Show tool being called (Phase 6.5)
            tool_data = event.data
            tool_name = tool_data.get("tool", "unknown")
            tool_args = tool_data.get("arguments", {})

            # Format arguments for display
            if tool_args:
                # Format as compact JSON-like string
                args_parts = []
                for key, value in tool_args.items():
                    if isinstance(value, str):
                        # Truncate long strings
                        if len(value) > 100:
                            value_str = f'"{value[:100]}..."'
                        else:
                            value_str = f'"{value}"'
                    else:
                        value_str = str(value)
                    args_parts.append(f"{key}={value_str}")
                args_str = ", ".join(args_parts)
                content = f"[dim]Calling with:[/dim] {args_str}"
            else:
                content = "[dim]Called with no arguments[/dim]"

            chat_view.add_tool_message(tool_name, content)

        elif event.type == EventType.TOOL_RESULT:
            # Show tool result (Phase 6.5)
            tool_data = event.data
            tool_name = tool_data.get("tool", "unknown")
            result = tool_data.get("result", "")

            # Format result for display
            if len(result) > 500:
                # Truncate long results
                formatted_result = f"{result[:500]}...\n[dim](Result truncated, {len(result)} chars total)[/dim]"
            else:
                formatted_result = result

            chat_view.add_tool_message(f"{tool_name} result", formatted_result)

        elif event.type == EventType.TOOL_ERROR:
            # Tool error (Phase 6.5)
            tool_data = event.data
            tool_name = tool_data.get("tool", "unknown") if isinstance(event.data, dict) else "unknown"
            error_msg = tool_data.get("error", str(event.data)) if isinstance(event.data, dict) else str(event.data)

            chat_view.add_tool_message(f"{tool_name} [red]ERROR[/red]", f"[red]{error_msg}[/red]")

        elif event.type == EventType.ERROR:
            # General error
            chat_view.add_system_message(
                f"[red]Error:[/red] {event.data}"
            )

        elif event.type == EventType.INFO:
            # Info message
            chat_view.add_system_message(f"[dim]{event.data}[/dim]")

    def _update_usage_display(self) -> None:
        """Update usage stats in status bar (Phase 6.4).

        Gets current usage stats from session and updates status bar badges.
        Respects the display_mode setting (session/provider/model/off).
        """
        if not self._engine_client or not self._engine_client.session:
            return

        # Get usage stats for display (respects display_mode)
        usage_display = self._engine_client.session.get_usage_for_display(
            self._provider,
            self._model
        )

        if not usage_display:
            # Display mode is "off" - remove badges if they exist
            status_bar = self.query_one(StatusBar)
            status_bar.remove_badge("tokens")
            status_bar.remove_badge("cost")
            return

        # Update status bar with usage stats
        status_bar = self.query_one(StatusBar)

        # Format tokens badge
        total_tokens = usage_display.get("total_tokens", 0)
        if total_tokens > 0:
            if total_tokens >= 1_000_000:
                tokens_text = f"{total_tokens / 1_000_000:.1f}M"
            elif total_tokens >= 1_000:
                tokens_text = f"{total_tokens / 1_000:.1f}K"
            else:
                tokens_text = f"{total_tokens}"

            status_bar.update_badge("tokens", "Tokens", tokens_text)

        # Format cost badge
        total_cost = usage_display.get("estimated_cost", 0.0)
        if total_cost > 0:
            cost_text = f"${total_cost:.4f}"
            status_bar.update_badge("cost", "Cost", cost_text)

    async def _handle_command(self, command: str) -> None:
        """Handle slash commands using Command Factory pattern."""
        chat_view = self.query_one("#chat-view", ChatView)
        parts = command[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Special case: quit/exit (direct action)
        if cmd in ("quit", "q", "exit"):
            self.exit()
            return

        # Try Command Factory first
        spec = CommandFactory.get(cmd)
        if spec:
            try:
                # Call command handler with context
                result = spec.handler(self, args)

                # Render result if it's a CommandResult type
                if result is not None:
                    renderer = TextualRenderer(self)
                    await renderer.render(result)

            except Exception as e:
                self.log.error(f"Command error: {cmd} - {e}", exc_info=True)
                chat_view.add_system_message(
                    f"[red]Command failed: {cmd}[/red]\n"
                    f"[dim]{str(e)}[/dim]"
                )
            return

        # TUI-specific commands (fallback)
        # File operations (side panel with multiple rendering modes)
        if cmd == "show":
            # Display file with advanced rendering (tree, table, image, markdown, code)
            await local_commands.cmd_show(self, args)
        elif cmd == "edit":
            # Edit file in side panel with syntax highlighting
            await local_commands.cmd_edit(self, args)
        # Clipboard operations
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
        # Dev/test commands
        elif cmd == "badge":
            # TUI test command for badge API
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
                "/badge list\n"
                "/badge txn - Test transactional API (demo)"
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

        elif action == "txn":
            # Demo: Transactional API with rollback on error
            chat_view.add_system_message("[cyan]Testing transactional API...[/cyan]")

            # Test 1: Successful transaction
            with status_bar.transaction() as txn:
                txn.add("test1", "Test1", "value1")
                txn.add("test2", "Test2", "value2")
                success, error = txn.commit()
                if success:
                    chat_view.add_system_message("[green]✓ Transaction 1 succeeded[/green]")
                else:
                    chat_view.add_system_message(f"[red]✗ Transaction 1 failed:[/red] {error}")

            # Test 2: Failed transaction (duplicate badge) - should rollback
            with status_bar.transaction() as txn:
                txn.update("test1", "updated")
                txn.add("test1", "Duplicate", "should_fail")  # This will fail
                success, error = txn.commit()
                if success:
                    chat_view.add_system_message("[green]✓ Transaction 2 succeeded[/green]")
                else:
                    chat_view.add_system_message(f"[yellow]✓ Transaction 2 failed as expected:[/yellow] {error}")
                    chat_view.add_system_message("[dim]test1 badge should still have 'value1' (rollback worked)[/dim]")

            # Test 3: Cleanup
            with status_bar.transaction() as txn:
                txn.remove("test1")
                txn.remove("test2")
                success, error = txn.commit()
                if success:
                    chat_view.add_system_message("[green]✓ Cleanup succeeded[/green]")
                else:
                    chat_view.add_system_message(f"[red]✗ Cleanup failed:[/red] {error}")

        else:
            chat_view.add_system_message(f"[yellow]Unknown badge action:[/yellow] {action}")

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

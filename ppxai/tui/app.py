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
from ppxai.tui.completer import TextualCompleter

# Engine integration (Phase 6.1)
from ppxai.engine import EngineClient
from ppxai.engine.types import Event, EventType
from ppxai.config import get_default_provider, get_default_model, get_api_key, initialize

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

    CSS_PATH = ["themes/layout.tcss", "themes/dialog.tcss"]

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
        # Use ppxai's logger instead of Textual's self.log (which doesn't write to our log file)
        from ppxai.common.logger import get_logger
        self._log = get_logger("tui")

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

    async def on_mount(self) -> None:
        """Called when the app is mounted."""
        self._log.info("=== on_mount() START ===")
        # Initialize engine client (Phase 6.1)
        self._initialize_engine()
        self._log.info("=== After _initialize_engine() ===")

        self.title = "ppxaide"

        # Set subtitle based on engine state
        if self._provider and self._model:
            self.sub_title = f"{self._provider}/{self._model}"
        else:
            self.sub_title = "Not configured - use /provider"

        # Register custom themes (built-in themes like catppuccin-mocha are already available)
        for theme in CUSTOM_THEMES.values():
            self.register_theme(theme)

        # Set initial theme (catppuccin-mocha by default)
        self.theme = DEFAULT_THEME

        # Update status bar with engine state (Phase 6.1)
        status_bar = self.query_one(StatusBar)
        if self._provider:
            status_bar.update_badge("provider", self._provider)
        else:
            status_bar.update_badge("provider", "[bold red]none[/bold red]")

        if self._model:
            status_bar.update_badge("model", self._model)
        else:
            status_bar.update_badge("model", "[bold red]none[/bold red]")

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
                    self._log.info(f"Bootstrap context loaded: {scope_text}")

        # Add optional status bar badges based on config (Phase 1.2)
        from ppxai.config import get_tui_config
        from ppxai.version import __version__
        from datetime import datetime

        tui_config = get_tui_config()

        # Version badge
        if tui_config.get("show_version", True):
            status_bar.add_badge("version", "Version", f"v{__version__}", variant="info")

        # Working directory badge
        if tui_config.get("show_cwd", True) and self._engine_client:
            cwd = self._engine_client.get_working_dir()
            if cwd:
                # Show abbreviated path (last 2 components)
                cwd_parts = Path(cwd).parts
                cwd_display = "/".join(cwd_parts[-2:]) if len(cwd_parts) >= 2 else cwd
                status_bar.add_badge("cwd", "Dir", cwd_display, variant="info")

        # DateTime badge
        if tui_config.get("show_datetime", False):
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            status_bar.add_badge("datetime", "Time", now, variant="info")

            # Start timer to update datetime every minute
            self.set_interval(60, self._update_datetime)

        # Agent mode badge (Phase 1.3)
        if self._engine_client and self._engine_client.agent_mode:
            status_bar.add_badge("agent", "Agent", "ACTIVE", variant="success")

            # Checkpoint status badge (Phase 1.3)
            checkpoint_status = self._engine_client.get_checkpoint_status()
            if checkpoint_status.get("enabled"):
                last_checkpoint = checkpoint_status.get("last_checkpoint")
                is_valid = checkpoint_status.get("is_valid", True)
                if last_checkpoint:
                    if not is_valid:
                        # Stale checkpoint - undo may not work correctly
                        status_bar.add_badge("checkpoint", "Undo", "↶!", variant="warning")
                    else:
                        # Valid checkpoint - undo available
                        status_bar.add_badge("checkpoint", "Undo", "↶", variant="success")

        # Focus the input box and set up autocomplete
        input_box = self.query_one("#input-box", InputBox)

        # Initialize autocomplete completer (Phase 1.1)
        completer = TextualCompleter(
            working_dir=Path(self._working_dir),
            engine_client=self._engine_client
        )
        input_box.set_completer(completer)

        input_box.focus()

        # Add welcome message with bootstrap status (Phase 6.3)
        chat_view = self.query_one("#chat-view", ChatView)

        if self._provider and self._model:
            welcome_msg = f"Welcome to ppxaide! Connected to {self._provider}/{self._model}\n"
        else:
            welcome_msg = "[bold yellow]Welcome to ppxaide![/bold yellow]\n"
            welcome_msg += "[red]⚠️  Engine not configured - check your .env file for API keys[/red]\n"
            welcome_msg += "[dim]Use /provider list to see available providers[/dim]\n\n"

        # Add bootstrap context info if loaded
        if self._engine_client and self._provider:
            bootstrap_status = self._engine_client.get_bootstrap_status()
            if bootstrap_status["loaded"]:
                sources = bootstrap_status.get("sources", [])
                char_count = bootstrap_status.get("char_count", 0)
                welcome_msg += f"[dim]Bootstrap context: {len(sources)} file(s), ~{char_count} chars[/dim]\n"

        welcome_msg += (
            "Type a message or use /help for commands.\n"
            "[dim]Use Ctrl+T to cycle themes, or Ctrl+P for all themes.[/dim]"
        )
        self._log.info("=== Before add_system_message ===")
        chat_view.add_system_message(welcome_msg)
        self._log.info("=== After add_system_message ===")

        # Check for session restoration (Phase 7) - after welcome message
        # Must run in worker to allow push_screen_wait() for modal dialog
        self._log.info("=== About to call _check_session_restoration() ===")
        self.run_worker(self._check_session_restoration(), exclusive=True)

    def _initialize_engine(self) -> None:
        """Initialize the engine client (Phase 6.1).

        Sets up:
        - Provider and model from config
        - Engine client instance
        - Working directory
        - Bootstrap context (Phase 6.3)

        Note: initialize() is called in main() before event loop starts (matches Rich TUI)
        """
        # Load config (initialize() already called in main())
        self._provider = get_default_provider()
        self._model = get_default_model(self._provider)

        # Create engine client (automatically loads bootstrap context)
        self._engine_client = EngineClient()

        # Set provider and model
        try:
            provider_ok = self._engine_client.set_provider(self._provider)
            model_ok = self._engine_client.set_model(self._model)

            if not provider_ok:
                self._log.error(f"Failed to set provider: {self._provider} (check API key in .env)")
                self._provider = None
            if not model_ok:
                self._log.error(f"Failed to set model: {self._model}")
                self._model = None

            if not provider_ok or not model_ok:
                self._log.warning("Engine initialization incomplete - check configuration")

        except Exception as e:
            self._log.error(f"Failed to initialize engine: {e}")
            self._provider = None
            self._model = None

        # Set working directory
        self._engine_client.set_working_dir(self._working_dir)

        if self._provider and self._model:
            self._log.info(f"Engine initialized: {self._provider}/{self._model}")
        else:
            self._log.warning("Engine not fully initialized - use /provider and /model commands")

    def _update_datetime(self) -> None:
        """Update datetime badge every minute (Phase 1.2)."""
        from datetime import datetime
        from ppxai.config import get_tui_config

        tui_config = get_tui_config()
        if tui_config.get("show_datetime", False):
            status_bar = self.query_one(StatusBar)
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            status_bar.update_badge("datetime", now)

    async def _check_session_restoration(self) -> None:
        """Check for last session and offer to restore (Phase 7).

        Shows interactive modal dialog if auto_restore is "prompt".
        Auto-restores if config says 'always'.
        """
        self._log.info("_check_session_restoration() called")
        try:
            if not self._engine_client:
                self._log.debug("No engine client, skipping session restoration")
                return

            from ppxai.config import get_auto_restore_mode
            from ppxai.engine.session import SessionManager
            from ppxai.tui.widgets.dialog import ConsentDialog

            # Get last session state
            last_state = SessionManager.get_last_session_state()
            if not last_state:
                self._log.debug("No last session state found")
                return

            session_name = last_state.get("name")
            message_count = last_state.get("message_count", 0)

            self._log.info(f"Found last session: {session_name} with {message_count} messages")

            # Skip if no messages
            if message_count == 0:
                self._log.debug("Skipping session with 0 messages")
                return

            chat_view = self.query_one("#chat-view", ChatView)
            provider_info = last_state.get("provider", "unknown")
            tools_info = "ON" if last_state.get("tools_enabled") else "OFF"

            # Check if session was dirty (crash recovery) - Phase 2.2
            is_dirty = last_state.get("dirty", False)
            if is_dirty:
                self._log.info(f"Detected dirty session (crash): {session_name}")

                # Always show crash recovery prompt (higher priority than auto_restore)
                response = await self.push_screen_wait(
                    ConsentDialog(
                        title="⚠ Session Recovery",
                        message=f"ppxaide was interrupted during last session",
                        question=f"Recover session '{session_name}'?\n{message_count} messages, Provider: {provider_info}, Tools: {tools_info}",
                        options=["Yes", "No"]
                    )
                )

                if response == "yes":
                    if await self._restore_session(session_name, last_state):
                        chat_view.add_system_message(
                            f"⚠ [yellow]Session recovered:[/yellow] {session_name} ({message_count} messages)\n"
                            f"[dim]Provider: {provider_info}, Tools: {tools_info}[/dim]"
                        )
                        self._log.info(f"User chose to recover crash session: {session_name}")
                    return
                else:
                    # Clear dirty flag if user declines recovery
                    from ppxai.engine.session import SessionManager
                    SessionManager.clear_state_file()
                    self._log.info("User declined crash recovery, cleared state file")
                    return

            # Normal auto-restore logic (not a crash)
            auto_restore = get_auto_restore_mode()
            self._log.info(f"Auto-restore mode: {auto_restore}")

            # Auto-restore if configured
            if auto_restore == "always":
                if await self._restore_session(session_name, last_state):
                    chat_view.add_system_message(
                        f"✓ [green]Session restored:[/green] {session_name} ({message_count} messages)\n"
                        f"[dim]Provider: {provider_info}, Tools: {tools_info}[/dim]"
                    )
                    self._log.info(f"Auto-restored session: {session_name}")
                return

            # Show interactive prompt for "prompt" mode
            if auto_restore != "never":
                self._log.info(f"Showing session restoration prompt for {session_name}")

                # Show modal dialog
                response = await self.push_screen_wait(
                    ConsentDialog(
                        title="Session Restoration",
                        message=f"Last session: {session_name}",
                        question=f"{message_count} messages, Provider: {provider_info}, Tools: {tools_info}\n\nRestore this session?",
                        options=["Yes", "No"]
                    )
                )

                if response.lower() == "yes":
                    if await self._restore_session(session_name, last_state):
                        chat_view.add_system_message(
                            f"✓ [green]Session restored:[/green] {session_name} ({message_count} messages)\n"
                            f"[dim]Provider: {provider_info}, Tools: {tools_info}[/dim]"
                        )
                        self._log.info(f"User chose to restore session: {session_name}")
                else:
                    self._log.info("User declined session restoration")

        except Exception as e:
            self._log.error(f"Error checking session restoration: {e}", exc_info=True)

    async def _restore_session(self, session_name: str, session_state: dict) -> bool:
        """Restore a session with provider, model, and tools state (async for Textual).

        Args:
            session_name: Name of session to load
            session_state: Session state from state file

        Returns:
            True if restored successfully
        """
        if not self._engine_client:
            self._log.error("Restoration failed: No engine client")
            return False

        # Load the session
        self._log.info(f"Loading session: {session_name}")
        if not self._engine_client.session.load(session_name):
            self._log.error(f"Restoration failed: session.load() returned False for {session_name}")
            return False

        self._log.info(f"Session loaded successfully: {len(self._engine_client.session.messages)} messages")

        # Restore provider/model - matches Rich TUI behavior (lines 573-594 of rich/main.py)
        # session.load() already set session.metadata from the session file
        status_bar = self.query_one(StatusBar)
        stored_provider = self._engine_client.session.metadata.get("provider")
        stored_model = self._engine_client.session.metadata.get("model")

        if stored_provider:
            from ppxai.config import PROVIDERS
            if stored_provider in PROVIDERS:
                try:
                    # Don't check return value - just try to set it (Rich TUI line 579)
                    self._engine_client.set_provider(stored_provider)
                    self._provider = stored_provider
                    status_bar.update_badge("provider", stored_provider)
                    self._log.info(f"Restored provider: {stored_provider}")
                except Exception as e:
                    self._log.debug(f"Failed to restore provider '{stored_provider}': {e}")

        if stored_model:
            # Use strict mode to validate model exists (Rich TUI line 586)
            if self._engine_client.set_model(stored_model, strict=True):
                self._model = stored_model
                status_bar.update_badge("model", stored_model)
                self._log.info(f"Restored model: {stored_model}")
            else:
                # Model not available - use provider's default (Rich TUI lines 589-594)
                from ppxai.config import get_default_model
                default_model = get_default_model(self._engine_client.provider_name) if self._engine_client.provider else None
                if default_model:
                    self._engine_client.set_model(default_model)
                    self._model = default_model
                    self._log.warning(f"Model '{stored_model}' not available, using default: {default_model}")

        # Restore tools state from loaded session (not session_state parameter)
        # session.load() already set session.tools_enabled from the session file
        tools_enabled = self._engine_client.session.tools_enabled
        if tools_enabled:
            self._engine_client.enable_tools()
            self._tools_enabled = True
            status_bar = self.query_one(StatusBar)
            status_bar.update_badge("tools", "ON")
        else:
            # Ensure tools are disabled if they were disabled in session
            self._engine_client.tools_enabled = False
            self._tools_enabled = False
            status_bar = self.query_one(StatusBar)
            status_bar.update_badge("tools", "OFF")

        # Restore working directory from loaded session
        # session.load() already set session.working_dir from the session file
        working_dir = self._engine_client.session.working_dir
        if working_dir and os.path.isdir(working_dir):
            try:
                os.chdir(working_dir)
                self._engine_client.set_working_dir(working_dir)
                self._working_dir = working_dir
            except Exception:
                pass

        # Render loaded messages into ChatView (like /load command does)
        chat_view = self.query_one("#chat-view", ChatView)
        chat_view.clear()

        messages = self._engine_client.session.messages
        self._log.info(f"Rendering {len(messages)} messages to chat view")
        for msg in messages:
            role = msg.role
            content = msg.content

            if role == "user":
                chat_view.add_user_message(content)
            elif role == "assistant":
                chat_view.add_assistant_message(content)
            elif role == "system":
                chat_view.add_system_message(content)
            elif role == "tool":
                chat_view.add_message(content, role="tool")

        # Update subtitle to match restored provider/model
        if self._provider and self._model:
            self.sub_title = f"{self._provider}/{self._model}"
            self._log.info(f"Updated subtitle: {self.sub_title}")

        # Refocus input box after session restoration (critical for autocomplete integration)
        input_box = self.query_one("#input-box", InputBox)
        input_box.focus()

        self._log.info(f"Session restoration complete: provider={self._provider}, model={self._model}, tools={self._tools_enabled}")
        return True

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
        # Tools are always available in ppxai (dependencies are built-in)
        return True

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

        self._log.info(f"Theme changed: {old_theme} → {new_theme}, syntax: {syntax_theme}")

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
            self._log.error(f"Stream error: {e}")
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
            # Finalize and display (only if there's content)
            if self._current_message_content.strip():
                chat_view.add_assistant_message(self._current_message_content)
            self._current_message_content = ""

            # Update usage stats in status bar (Phase 6.4)
            self._update_usage_display()

            # Auto-save session after each message pair (Phase 2.1)
            from ppxai.config import get_auto_save_interval
            save_interval = get_auto_save_interval()
            message_count = len(self._engine_client.session.messages)
            if message_count > 0 and (save_interval == 0 or message_count % max(1, save_interval) == 0):
                try:
                    self._engine_client.session.save_dirty()
                    self._log.debug(f"Auto-saved session at {message_count} messages (interval={save_interval})")
                except Exception as e:
                    self._log.warning(f"Auto-save failed: {e}")

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

            # Show full result (scrollable bubble will handle long content)
            chat_view.add_tool_message(f"{tool_name} result", result)

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

            status_bar.update_badge("tokens", tokens_text)

        # Format cost badge
        total_cost = usage_display.get("estimated_cost", 0.0)
        if total_cost > 0:
            cost_text = f"${total_cost:.4f}"
            status_bar.update_badge("cost", cost_text)

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
                self._log.debug(f"Calling handler for command: {cmd} with args: {args}")
                result = spec.handler(self, args)
                self._log.debug(f"Handler returned: {type(result).__name__}")

                # Check if result is a coroutine (async handler)
                import inspect
                if inspect.iscoroutine(result):
                    self._log.debug(f"Handler returned coroutine, awaiting it")
                    result = await result

                # Render result if it's a CommandResult type
                if result is not None:
                    renderer = TextualRenderer(self)
                    await renderer.render(result)

                # Sync TUI state with engine client after command execution
                if cmd in ("tools", "agent"):
                    # Update tools enabled state
                    if self._engine_client:
                        self._tools_enabled = self._engine_client.tools_enabled
                        status_bar = self.query_one(StatusBar)
                        status_bar.update_badge("tools", "ON" if self._tools_enabled else "OFF")

                    # Update agent mode badge (Phase 1.3)
                    if cmd == "agent" and self._engine_client:
                        agent_mode = self._engine_client.agent_mode
                        if agent_mode:
                            status_bar.add_badge("agent", "Agent", "ACTIVE", variant="success")

                            # Check checkpoint status
                            checkpoint_status = self._engine_client.get_checkpoint_status()
                            if checkpoint_status.get("enabled"):
                                last_checkpoint = checkpoint_status.get("last_checkpoint")
                                is_valid = checkpoint_status.get("is_valid", True)
                                if last_checkpoint:
                                    if not is_valid:
                                        status_bar.add_badge("checkpoint", "Undo", "↶!", variant="warning")
                                    else:
                                        status_bar.add_badge("checkpoint", "Undo", "↶", variant="success")
                        else:
                            # Agent mode disabled - remove badges
                            status_bar.remove_badge("agent")
                            status_bar.remove_badge("checkpoint")

                # Sync working directory after /cd command
                if cmd == "cd" and self._engine_client:
                    engine_working_dir = self._engine_client.get_working_dir()
                    if engine_working_dir != self._working_dir:
                        self._working_dir = engine_working_dir
                        self._log.info(f"Working directory synced: {engine_working_dir}")

                # Handle status bar toggle commands (Phase 1.2)
                if cmd == "status" and args and args.split()[0] in ("version", "cwd", "datetime"):
                    from ppxai.config import get_tui_config
                    from ppxai.version import __version__
                    from datetime import datetime

                    subcommand = args.split()[0]
                    tui_config = get_tui_config()
                    status_bar = self.query_one(StatusBar)

                    # Update badge based on new config value
                    if subcommand == "version":
                        if tui_config.get("show_version", True):
                            status_bar.add_badge("version", "Version", f"v{__version__}", variant="info")
                        else:
                            status_bar.remove_badge("version")

                    elif subcommand == "cwd":
                        if tui_config.get("show_cwd", True) and self._engine_client:
                            cwd = self._engine_client.get_working_dir()
                            if cwd:
                                cwd_parts = Path(cwd).parts
                                cwd_display = "/".join(cwd_parts[-2:]) if len(cwd_parts) >= 2 else cwd
                                status_bar.add_badge("cwd", "Dir", cwd_display, variant="info")
                        else:
                            status_bar.remove_badge("cwd")

                    elif subcommand == "datetime":
                        if tui_config.get("show_datetime", False):
                            now = datetime.now().strftime("%Y-%m-%d %H:%M")
                            status_bar.add_badge("datetime", "Time", now, variant="info")
                            # Start timer if not already running
                            self.set_interval(60, self._update_datetime)
                        else:
                            status_bar.remove_badge("datetime")

            except RuntimeError as e:
                import os
                import traceback

                # Always log full traceback
                self._log.error(f"RuntimeError in command '{cmd}': {e}", exc_info=True)

                if "asyncio.run() cannot be called" in str(e) and "running event loop" in str(e):
                    # Special handling for asyncio.run() errors
                    error_msg = (
                        f"[red]Command failed: {cmd}[/red]\n"
                        f"[yellow]asyncio.run() called from running event loop[/yellow]\n"
                    )

                    # Add full traceback if --trace enabled
                    if os.getenv('PPXAIDE_TRACE'):
                        tb = traceback.format_exc()
                        error_msg += f"\n[dim]Full traceback:\n{tb}[/dim]"
                    else:
                        error_msg += f"[dim]Use --trace flag for full traceback[/dim]"

                    chat_view.add_system_message(error_msg)
                else:
                    # Other RuntimeErrors
                    error_msg = f"[red]Command failed: {cmd}[/red]\n[dim]{str(e)}[/dim]"

                    if os.getenv('PPXAIDE_TRACE'):
                        tb = traceback.format_exc()
                        error_msg += f"\n\n[dim]Traceback:\n{tb}[/dim]"

                    chat_view.add_system_message(error_msg)
            except Exception as e:
                import os
                import traceback

                # Always log full traceback
                self._log.error(f"Exception in command '{cmd}': {e}", exc_info=True)

                error_msg = f"[red]Command failed: {cmd}[/red]\n[dim]{str(e)}[/dim]"

                # Add full traceback if --trace enabled
                if os.getenv('PPXAIDE_TRACE'):
                    tb = traceback.format_exc()
                    error_msg += f"\n\n[dim]Traceback:\n{tb}[/dim]"

                chat_view.add_system_message(error_msg)
            return

        # TUI-specific commands (fallback for commands not in factory)
        if cmd == "edit":
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
        # Mark session clean on graceful exit (Phase 2.2)
        if self._engine_client:
            try:
                self._engine_client.session.mark_clean()
                self._log.debug("Marked session as clean on exit")
            except Exception as e:
                self._log.warning(f"Failed to mark session clean: {e}")
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

    async def show_widget_in_panel(self, widget, title: str = "") -> None:
        """Show an arbitrary widget in the side panel.

        Args:
            widget: The widget to display (DataTable, Tree, etc.)
            title: Title to show in panel header
        """
        side_panel = self.query_one("#side-panel", SidePanel)
        await side_panel.show_widget(widget, title)

    def close_side_panel(self) -> None:
        """Close the side panel."""
        side_panel = self.query_one("#side-panel", SidePanel)
        side_panel.close()

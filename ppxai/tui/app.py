"""
PPXAIDEApp - Main Textual application for ppxaide.

This is the core application class that manages:
- Screen layout and navigation
- Engine client connection
- Theme management
- Keyboard bindings
- Split view for file viewing/editing
"""

import asyncio
import inspect
import os
import time
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Header, Footer, Static, Input, RichLog

from ppxai.common.autosave_guard import AutosaveFailureGuard
from ppxai.common.consent import normalize_consent_response
from ppxai.common.logger import Logger, get_logger
from ppxai.constants import ConsentResponse
from ppxai.tui.widgets.status_bar import StatusBar
from ppxai.tui.widgets.footer_status import FooterStatus
from ppxai.tui.widgets.chat_view import ChatView
from ppxai.tui.widgets.input_box import InputBox
from ppxai.tui.widgets.side_panel import SidePanel
from ppxai.tui.widgets.file_tree import FileTree
from ppxai.tui.keys import get_app_bindings
from ppxai.tui.widgets.code_editor import CodeEditor, get_syntax_theme_for_app_theme
from ppxai.tui.widgets.dialog import ConsentDialog
from ppxai.tui.widgets.message_box import MessageBox
from ppxai.tui.themes.themes import CUSTOM_THEMES, DEFAULT_THEME, CYCLE_THEMES
from ppxai.tui.clipboard import copy_to_clipboard, paste_from_clipboard, is_clipboard_available
from ppxai.tui import commands as local_commands
from ppxai.tui.completer import TextualCompleter
from ppxai.tui.event_bus import EventBus, Events
from ppxai.tui import stream_handler
from ppxai.tui.terminal import can_display_images

# Engine integration (Phase 6.1)
from ppxai.engine import EngineClient
from ppxai.engine.types import Event, EventType
from ppxai.engine.session import SessionManager
from ppxai.config import (
    PROVIDERS, get_default_provider, get_default_model, get_api_key, initialize,
    get_tui_config, get_auto_restore_mode, get_auto_save_interval,
)
from ppxai.version import __version__, format_version_banner

# Command Factory integration (Phase 6.1.1 - Technical debt cleanup)
from ppxai.commands import CommandFactory
from ppxai.commands.attach import build_multimodal_content, _load_file as _attach_load_file
from ppxai.commands.protocol import CommandContext
from ppxai.commands.results import CommandResult, DirectoryListingResult, DirectoryTreeResult
from ppxai.rendering.textual_renderer import TextualRenderer


class PPXAIDEApp(App):
    """Main ppxaide application.

    Implements CommandContext protocol for command factory integration.
    """

    TITLE = "ppxaide"
    SUB_TITLE = "AI Assistant"

    CSS_PATH = ["themes/layout.tcss", "themes/dialog.tcss"]

    BINDINGS = get_app_bindings()

    # Split ratio presets (chat% : panel%)
    SPLIT_RATIOS = [30, 40, 50, 60, 70]
    DEFAULT_SPLIT_INDEX = 2  # 50%

    # File tree width presets (percentage of total width)
    TREE_WIDTHS = [15, 20, 25, 30, 35]
    DEFAULT_TREE_WIDTH_INDEX = 2  # 25%

    def __init__(self, debug_logging: bool = False, trace_logging: bool = False):
        super().__init__()
        # Use ppxai's logger instead of Textual's self.log (which doesn't write to our log file)
        self._log = get_logger("tui")

        # Debug mode controls event bus logging and handler verbosity
        self._debug_logging = debug_logging
        # Trace mode: verbose per-event logging (--trace flag)
        self._trace_logging = trace_logging

        # Event bus for decoupled component communication (v1.15.0 blinker integration)
        # Only log events when trace mode is enabled (--trace or /debug-log on)
        self._event_bus = EventBus(log_events=self._trace_logging)

        self._current_theme_index = 0
        self._engine_client: Optional[EngineClient] = None
        # Shadow state fields — kept for compose() which runs before engine init.
        # After _initialize_engine(), properties delegate to engine_client.state (AppState).
        self._provider = "perplexity"
        self._model = "sonar"
        self._tools_enabled = False     # Shadow for compose(); reads from AppState after init
        self._tools_verbose = False     # Shadow for compose(); reads from AppState after init
        self._tool_group_active = False  # v1.16.0: Track active tool group for noise reduction
        self._tool_group_tools = []  # v1.16.0: Tool names in current group
        self._working_dir = os.getcwd()
        self._split_index = self.DEFAULT_SPLIT_INDEX  # Current split ratio index
        self._tree_width_index = self.DEFAULT_TREE_WIDTH_INDEX  # File tree width index
        self._file_tree_visible: bool = True

        # Streaming state (Phase 6.1)
        self._current_message_content = ""

        # Ctrl+C double-press tracking (v1.15.2)
        self._last_ctrl_c_time: float = 0.0
        self._CTRL_C_TIMEOUT = 2.0  # seconds to press Ctrl+C again

        # v1.18.0 Phase 5f: tell the user if auto-save has been failing
        # silently. stream_handler.py reads this and surfaces a footer
        # warning the Nth consecutive failure; first success resets it.
        self._autosave_guard = AutosaveFailureGuard()
        self._response_start_time: float = 0.0
        # Reasoning token state (DeepSeek R1, GPT-OSS thinking)
        self._reasoning_started = False
        self._reasoning_content = ""
        self._reasoning_message: Optional["MessageBox"] = None  # For streaming updates
        self._reasoning_update_pending = False  # Throttling flag
        self._reasoning_update_timer = None  # Timer for throttled updates

        # Cached widget references — set in on_mount, avoids repeated DOM traversal
        self._chat_view: Optional["ChatView"] = None
        self._status_bar: Optional["StatusBar"] = None
        self._footer_status: Optional["FooterStatus"] = None
        self._input_box: Optional["InputBox"] = None

        # Files staged for the next chat turn (v1.17.4 Phase 7.1-7.3).
        # Populated by FileTree.FileAttach handler and /attach command,
        # consumed and cleared by on_input_box_submitted before calling
        # engine.chat(). Public property so CommandContext proxy can
        # forward it to /attach's handle_attach.
        self.pending_files: list = []

    def compose(self) -> ComposeResult:
        """Compose the application layout with split view support."""
        yield Header()
        yield StatusBar(
            provider=self._provider,
            model=self._model,
            tools_enabled=self._tools_enabled,
        )
        # Main content area: file tree + chat + side panel
        with Horizontal(id="main-content"):
            # Leftmost pane: file tree browser (Norton Commander style)
            yield FileTree(Path(self._working_dir), id="file-tree")
            # Center pane: chat + input
            with Vertical(id="chat-pane"):
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")
            # Right pane: side panel (hidden by default)
            yield SidePanel(id="side-panel")
        yield FooterStatus()
        yield Footer()

    async def on_mount(self) -> None:
        """Called when the app is mounted."""
        self._log.info("=== on_mount() START ===")

        # Cache frequently accessed widgets to avoid repeated DOM traversal
        self._chat_view = self.query_one("#chat-view", ChatView)
        self._status_bar = self.query_one(StatusBar)
        self._footer_status = self.query_one(FooterStatus)
        self._input_box = self.query_one("#input-box", InputBox)

        # Initialize config system (v1.15.3: DAG-based init)
        initialize()
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
        status_bar = self._status_bar
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

        # Subscribe to context_attachments changes (v1.17.4 Phase 7.4).
        # When the user attaches images (via /attach in Rich TUI, or
        # via the file tree, or loaded from a session), the status bar
        # shows a persistent badge. Same data source as Rich's status
        # bar — AppState.context_attachments is the canonical field.
        if self._engine_client:
            self._engine_client.state.on(
                "context_attachments",
                self._on_context_attachments_changed,
            )
            # Render initial snapshot in case a restored session already
            # has attachments.
            initial_attachments = self._engine_client.state.get("context_attachments") or []
            if initial_attachments:
                self._on_context_attachments_changed(initial_attachments)

        # P0 (v1.18.0): Subscribe to agent_beat for heartbeat badge.
        # EngineClient emits BEAT events during tool iterations and writes
        # the payload to AppState.agent_beat; RUN_COMPLETE/RUN_ERROR clear
        # the field. The badge surfaces iteration, last tool, ok/fail, and
        # elapsed wall-clock — same view as the Rich TUI's dim line but
        # persistent in the status bar while the agent is active.
        if self._engine_client:
            self._engine_client.state.on(
                "agent_beat",
                self._on_agent_beat_changed,
            )
            # v1.19.0 (Inc 9): background-agents badge. The server mirrors
            # the active /v1/agent/* run set into AppState.background_agents;
            # show a count badge while any background run is active.
            self._engine_client.state.on(
                "background_agents",
                self._on_background_agents_changed,
            )

        # Add optional status bar badges based on config (Phase 1.2)
        tui_config = get_tui_config()

        # Version badge
        if tui_config.get("show_version", True):
            status_bar.add_badge("version", "Version", f"v{__version__}", variant="info")

        # Working directory badge
        if tui_config.get("show_cwd", True) and self._engine_client:
            cwd = self._engine_client.get_working_dir()
            if cwd:
                status_bar.add_badge("cwd", "Dir", self._format_cwd_display(cwd), variant="info")

        # DateTime badge
        if tui_config.get("show_datetime", False):
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            status_bar.add_badge("datetime", "Time", now, variant="info")

            # Start timer to update datetime every minute
            self.set_interval(60, self._update_datetime)

        # Agent mode badge (Phase 1.3)
        if self._engine_client and self._engine_client.state.get("agent_mode"):
            status_bar.add_badge("agent", "Agent", "ACTIVE", variant="success")
            self._update_checkpoint_badge(status_bar)

        # Focus the input box and set up autocomplete
        input_box = self._input_box

        # Initialize autocomplete completer (Phase 1.1)
        completer = TextualCompleter(
            working_dir=Path(self._working_dir),
            engine_client=self._engine_client
        )
        input_box.set_completer(completer)

        input_box.focus()

        # Add welcome message with bootstrap status (Phase 6.3)
        chat_view = self._chat_view

        # v1.18.2: prefix with the runtime-version banner so screenshots
        # of the welcome frame always carry version + commit + source mtime.
        # See ppxai/version.py::format_version_banner.
        version_line = f"[dim]{format_version_banner()}[/dim]\n"
        if self._provider and self._model:
            welcome_msg = version_line + f"Welcome to ppxaide! Connected to {self._provider}/{self._model}\n"
        else:
            welcome_msg = version_line + "[bold yellow]Welcome to ppxaide![/bold yellow]\n"
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
        - Consent callbacks for tool execution

        Note: initialize() is called in main() before event loop starts (matches Rich TUI)
        """
        # Load config (initialize() already called in main())
        self._provider = get_default_provider()
        self._model = get_default_model(self._provider)

        # Create engine client with consent callbacks for tool execution
        self._engine_client = EngineClient(
            consent_callback=self._file_edit_consent_handler,
            shell_consent_callback=self._shell_consent_handler
        )

        # Subscribe to engine events via event bus (v1.15.0 blinker integration)
        # Handlers are in stream_handler.py — lambdas bind self for the event bus signature
        _sh = stream_handler  # Short alias
        self._event_bus.on(Events.ENGINE_STREAM_START, lambda s, **kw: _sh.on_stream_start(self, s, **kw))
        self._event_bus.on(Events.ENGINE_STREAM_CHUNK, lambda s, **kw: _sh.on_stream_chunk(self, s, **kw))
        self._event_bus.on(Events.ENGINE_REASONING_CHUNK, lambda s, **kw: _sh.on_reasoning_chunk(self, s, **kw))
        self._event_bus.on(Events.ENGINE_STREAM_END, lambda s, **kw: _sh.on_stream_end(self, s, **kw))
        self._event_bus.on(Events.ENGINE_TOOL_CALL, lambda s, **kw: _sh.on_tool_call(self, s, **kw))
        self._event_bus.on(Events.ENGINE_TOOL_RESULT, lambda s, **kw: _sh.on_tool_result(self, s, **kw))
        self._event_bus.on(Events.ENGINE_TOOL_ERROR, lambda s, **kw: _sh.on_tool_error(self, s, **kw))
        self._event_bus.on(Events.ENGINE_TOOL_GROUP_START, lambda s, **kw: _sh.on_tool_group_start(self, s, **kw))
        self._event_bus.on(Events.ENGINE_TOOL_GROUP_END, lambda s, **kw: _sh.on_tool_group_end(self, s, **kw))
        self._event_bus.on(Events.ENGINE_DISPLAY_FILE, lambda s, **kw: _sh.on_display_file(self, s, **kw))
        self._event_bus.on(Events.ENGINE_CONSENT_FILE, lambda s, **kw: _sh.on_consent_request(self, s, **kw))
        self._event_bus.on(Events.ENGINE_ERROR, lambda s, **kw: _sh.on_engine_error(self, s, **kw))
        self._event_bus.on(Events.ENGINE_WARNING, lambda s, **kw: _sh.on_engine_warning(self, s, **kw))
        self._event_bus.on(Events.ENGINE_INFO, lambda s, **kw: _sh.on_engine_info(self, s, **kw))
        self._event_bus.on(Events.ENGINE_WORKING_DIR_CHANGED, lambda s, **kw: _sh.on_working_dir_changed(self, s, **kw))
        self._event_bus.on(Events.ENGINE_AGENT_INTERMEDIATE_PROSE, lambda s, **kw: _sh.on_agent_intermediate_prose(self, s, **kw))
        self._log.info("[EventBus] Subscribed to all engine events")

        # Register AppState observers — auto-update status bar on state changes.
        # This replaces ~30 manual update_badge() calls scattered across methods.
        state = self._engine_client.state
        state.on("provider", self._on_state_provider_changed)
        state.on("model", self._on_state_model_changed)
        state.on("tools_enabled", self._on_state_tools_changed)
        state.on("tools_verbose", self._on_state_tools_verbose_changed)
        state.on("working_dir", self._on_state_working_dir_changed)
        self._log.info("[AppState] Observers registered for status bar sync")

        # Set provider and model
        try:
            provider_ok = self._engine_client.set_provider(self._provider)
            model_ok = self._engine_client.set_model(self._model, reset_context=False)

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

    # ========================================================================
    # AppState observers — auto-update status bar on state changes
    # ========================================================================

    def _on_state_provider_changed(self, value: str) -> None:
        """AppState observer: provider changed → update status bar."""
        self._provider = value  # Keep shadow field for compose()
        if self._status_bar:
            self._status_bar.update_badge("provider", value or "[bold red]none[/bold red]")

    def _on_state_model_changed(self, value: str) -> None:
        """AppState observer: model changed → update status bar."""
        self._model = value  # Keep shadow field for compose()
        if self._status_bar:
            self._status_bar.update_badge("model", value or "[bold red]none[/bold red]")

    def _on_state_tools_changed(self, value: bool) -> None:
        """AppState observer: tools_enabled changed → update status bar + shadow."""
        self._tools_enabled = value  # Keep shadow for compose() and direct reads
        if self._status_bar:
            self._status_bar.update_badge("tools", "ON" if value else "OFF")

    def _on_state_tools_verbose_changed(self, value: bool) -> None:
        """AppState observer: tools_verbose changed → sync shadow field."""
        self._tools_verbose = value

    def _on_state_working_dir_changed(self, value: str) -> None:
        """AppState observer: working_dir changed → update status bar + file tree."""
        self._working_dir = value
        if self._status_bar and value:
            self._status_bar.update_badge("cwd", self._format_cwd_display(value))
        # Sync file tree root directory
        if value:
            try:
                file_tree = self.query_one("#file-tree", FileTree)
                file_tree.update_root_path(Path(value))
            except Exception:
                pass

    async def _file_edit_consent_handler(self, file_path: str) -> tuple[bool, str]:
        """Handle file edit consent request using Textual dialog.

        Args:
            file_path: Path to file that needs editing

        Returns:
            tuple: (approved: bool, response: str)
        """
        self._log.info(f"File edit consent requested for: {file_path}")

        try:
            result = await self._show_consent_dialog(
                title="⚠️  File Edit Request",
                message=f"AI wants to edit: {file_path}",
                question="Allow this file edit?"
            )
            return result

        except Exception as e:
            self._log.error(f"Consent dialog error: {e}")
            return (False, "no")

    async def _shell_consent_handler(self, command: str, working_dir: str, risk_level: str) -> tuple[bool, str]:
        """Handle shell command consent request using Textual dialog.

        Args:
            command: Shell command that needs execution
            working_dir: Working directory for the command
            risk_level: Risk level classification (safe, dangerous, never)

        Returns:
            tuple: (approved: bool, response: str)
        """
        self._log.info(f"Shell consent requested for: {command[:50]}... (risk: {risk_level})")

        # Determine risk color/emoji
        risk_display = {
            "never": "🔴 BLOCKED",
            "dangerous": "🟡 DANGEROUS",
            "safe": "🟢 SAFE"
        }.get(risk_level, "🟡 UNKNOWN")

        try:
            result = await self._show_consent_dialog(
                title=f"⚠️  Shell Command Request ({risk_display})",
                message=f"Command: {command}\nDirectory: {working_dir}",
                question="Allow this shell command?"
            )
            return result

        except Exception as e:
            self._log.error(f"Shell consent dialog error: {e}")
            return (False, "no")

    async def _show_consent_dialog(
        self, title: str, message: str, question: str
    ) -> tuple[bool, str]:
        """Show consent dialog during streaming using threading.Event pattern.

        When called from worker thread, uses call_from_thread to show dialog in main thread.
        Uses threading.Event for synchronization between threads.

        Args:
            title: Dialog title
            message: Dialog message
            question: Question to ask

        Returns:
            tuple: (approved: bool, response: str) - response is normalized to ConsentResponse enum
        """
        self._log.info(f"Showing consent dialog: {title}")

        # Create threading event and result container for cross-thread communication
        consent_event = threading.Event()
        consent_result = {"response": "no"}

        def show_dialog_in_main_thread():
            """Show dialog in main Textual thread."""
            def on_dialog_dismiss(response: str) -> None:
                """Callback when dialog is dismissed."""
                self._log.info(f"Dialog dismissed with response: {response}")
                consent_result["response"] = response or "no"
                consent_event.set()

            # Show dialog with callback (CORRECT: callback passed to push_screen, not dialog)
            dialog = ConsentDialog(
                title=title,
                message=message,
                question=question
            )
            self.push_screen(dialog, on_dialog_dismiss)

        # Use call_from_thread to show dialog in main thread (thread-safe)
        self.call_from_thread(show_dialog_in_main_thread)

        # Wait for user response (blocks worker thread, not main thread)
        consent_event.wait()

        # Normalize response to ConsentResponse enum value
        raw_response = consent_result["response"]
        normalized_response = normalize_consent_response(raw_response)

        # Determine approval status and log
        approved = normalized_response in (ConsentResponse.YES, ConsentResponse.ALWAYS)

        if normalized_response == ConsentResponse.YES:
            self._log.info("Consent approved (this file only)")
        elif normalized_response == ConsentResponse.ALWAYS:
            self._log.info("All actions approved for this session")
        elif normalized_response == ConsentResponse.NEVER:
            self._log.info("All actions blocked for this session")
        else:  # NO
            self._log.info("Consent denied")

        return (approved, normalized_response)

    # Removed: on_ppxaide_app_show_consent_dialog - no longer using message-based consent
    # Now using call_from_thread + threading.Event for direct cross-thread communication

    def _update_datetime(self) -> None:
        """Update datetime badge every minute (Phase 1.2)."""
        tui_config = get_tui_config()
        if tui_config.get("show_datetime", False):
            status_bar = self._status_bar
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            status_bar.update_badge("datetime", now)

    def _on_context_attachments_changed(self, attachments) -> None:
        """Callback from AppState — update the attachment badge (Phase 7.4).

        Called by the engine's `_refresh_context_attachments` → AppState →
        listener chain whenever session.messages mutates and the multimodal
        attachment set changes. The badge shows a compact count + filenames
        in the status bar, matching the Rich TUI's `📎 N: file1, file2`
        format. Empty attachments list hides the badge.
        """
        if not self._status_bar:
            return
        if not attachments:
            self._status_bar.remove_badge("attachments")
            return

        count = len(attachments)
        names = [
            (a.get("name") if isinstance(a, dict) else getattr(a, "name", "?"))
            for a in attachments
        ]
        short = []
        for n in names[:3]:
            short.append(n if len(n) <= 18 else n[:15] + "...")
        label = ", ".join(short)
        if count > 3:
            label += f", +{count - 3}"

        self._status_bar.add_badge(
            "attachments", "\U0001F4CE", f"{count}: {label}", variant="warning"
        )

    def _on_agent_beat_changed(self, beat) -> None:
        """Callback from AppState — update the agent heartbeat badge (P0 v1.18.0).

        `beat` is the dict payload from `AgentBeatState.as_event_data()` or
        an empty dict when the engine clears the field at run completion.
        Empty beat hides the badge; active beat shows iteration, tool,
        status, and elapsed wall-clock.
        """
        if not self._status_bar:
            return
        if not beat or not isinstance(beat, dict):
            self._status_bar.remove_badge("agent_beat")
            return

        iteration = beat.get("iteration", 0)
        tool = beat.get("tool", "")
        ok = beat.get("ok", True)
        failures = beat.get("failures", 0)
        elapsed = beat.get("elapsed_s", 0.0)

        parts = [f"i{iteration}"]
        if tool:
            parts.append(tool)
        if failures:
            parts.append(f"fail×{failures}")
        parts.append(f"{elapsed}s")
        value = " · ".join(parts)

        # warning variant when a failure streak is mounting (but not yet
        # tripping the zombie breaker); error variant when ok=False on the
        # latest beat; success otherwise.
        if failures >= 2:
            variant = "warning"
        elif not ok:
            variant = "error"
        else:
            variant = "success"

        self._status_bar.add_badge("agent_beat", "\u2699", value, variant=variant)

    def _on_background_agents_changed(self, runs) -> None:
        """Callback from AppState \u2014 background-agents badge (Inc 9 v1.19.0).

        `runs` is the active-run summary list pushed by the server
        (`[{run_id, status, task, owner}, ...]`) or an empty list when no
        background run is active. Empty list hides the badge; otherwise show
        the active count (and the single task when there's exactly one).
        """
        if not self._status_bar:
            return
        if not runs or not isinstance(runs, list):
            self._status_bar.remove_badge("background_agents")
            return

        count = len(runs)
        if count == 1:
            task = (runs[0].get("task") or "").strip()
            label = task[:24] + ("\u2026" if len(task) > 24 else "") if task else "1 run"
        else:
            label = f"{count} runs"
        self._status_bar.add_badge(
            "background_agents", "\U0001F916", label, variant="information"
        )

    def _format_cwd_display(self, path: str) -> str:
        """Format working directory path for status bar display.

        Shows abbreviated path with last 2 components for readability.
        Example: "/home/user/projects/myapp" -> "projects/myapp"

        Args:
            path: Full working directory path

        Returns:
            Abbreviated path string for display
        """
        cwd_parts = Path(path).parts
        return "/".join(cwd_parts[-2:]) if len(cwd_parts) >= 2 else path

    def _update_checkpoint_badge(self, status_bar: "StatusBar") -> None:
        """Update checkpoint/undo badge based on current checkpoint status.

        Shows ↶ for valid checkpoint (undo available), ↶! for stale checkpoint
        (undo may not work correctly), or nothing if no checkpoint exists.

        Args:
            status_bar: StatusBar widget to update
        """
        if not self._engine_client:
            return

        checkpoint_status = self._engine_client.get_checkpoint_status()
        if not checkpoint_status.get("enabled"):
            return

        last_checkpoint = checkpoint_status.get("last_checkpoint")
        is_valid = checkpoint_status.get("is_valid", True)

        if last_checkpoint:
            if not is_valid:
                # Stale checkpoint - undo may not work correctly
                status_bar.add_badge("checkpoint", "Undo", "↶!", variant="warning")
            else:
                # Valid checkpoint - undo available
                status_bar.add_badge("checkpoint", "Undo", "↶", variant="success")

    async def _check_session_restoration(self) -> None:
        """Check for last session and offer to restore (Phase 7).

        Thin wrapper around `session_restore_ops.check_session_restoration`
        — the body was extracted to that ops module in v1.18.2 (Item 1
        narrowing) to mirror the engine/session_ops.py decomposition.
        Kept as a method on PPXAIDEApp because `on_mount` calls it via
        `self.run_worker(self._check_session_restoration(), ...)`,
        which needs a bound coroutine.
        """
        from .session_restore_ops import check_session_restoration
        await check_session_restoration(self)

    async def _restore_session(self, session_name: str, session_state: dict) -> bool:
        """Restore a session — thin wrapper around session_restore_ops.

        See `tui/session_restore_ops.py::restore_session` for the body.
        Returns True on full successful restoration.
        """
        from .session_restore_ops import restore_session
        return await restore_session(self, session_name, session_state)

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
        if self._engine_client:
            return self._engine_client.state.get("model") or ""
        return self._model or ""

    @property
    def provider(self) -> str:
        """Currently selected provider (CommandContext protocol)."""
        if self._engine_client:
            return self._engine_client.state.get("provider") or ""
        return self._provider or ""

    def set_model(self, model: str) -> None:
        """Switch to specified model (CommandContext protocol)."""
        if self._engine_client:
            self._engine_client.set_model(model)
            # AppState observer updates status bar automatically
            # Notify user if context was reset (A3)
            reset_count = self._engine_client.last_model_switch_reset
            if reset_count > 0:
                self.notify(f"Cleared {reset_count} previous messages for clean context", severity="warning")

    def set_provider(self, provider: str) -> None:
        """Switch to specified provider (CommandContext protocol)."""
        if self._engine_client:
            self._engine_client.set_provider(provider)
            # AppState observer updates status bar automatically

    def get_provider(self) -> str:
        """Get current provider (CommandContext protocol)."""
        if self._engine_client:
            return self._engine_client.state.get("provider") or ""
        return self._provider or ""

    def get_model(self) -> str:
        """Get current model (CommandContext protocol)."""
        if self._engine_client:
            return self._engine_client.state.get("model") or ""
        return self._model or ""

    def get_auto_route(self) -> bool:
        """Get auto-routing status (CommandContext protocol)."""
        if self._engine_client:
            return self._engine_client.state.get("auto_route")
        return False

    def set_auto_route(self, enabled: bool) -> None:
        """Set auto-routing status (CommandContext protocol)."""
        if self._engine_client:
            self._engine_client.state.set("auto_route", enabled)

    def get_tools_available(self) -> bool:
        """Check if tool support is available (CommandContext protocol)."""
        return True

    def get_tools_verbose(self) -> bool:
        """Get tool verbose logging status (CommandContext protocol)."""
        if self._engine_client:
            return self._engine_client.state.get("tools_verbose")
        return False

    def set_tools_verbose(self, verbose: bool) -> None:
        """Set tool verbose logging status (CommandContext protocol)."""
        if self._engine_client:
            self._engine_client.state.set("tools_verbose", verbose)
        self._log.debug(f"Tools verbose mode: {'enabled' if verbose else 'disabled'}")

    @property
    def tools_enabled(self) -> bool:
        """Check if tools are enabled (CommandContext protocol)."""
        if self._engine_client:
            return self._engine_client.state.get("tools_enabled")
        return False

    @property
    def autoroute_enabled(self) -> bool:
        """Check if auto-routing is enabled (CommandContext protocol)."""
        if self._engine_client:
            return self._engine_client.state.get("auto_route")
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

    async def on_input_box_status_update(self, event: InputBox.StatusUpdate) -> None:
        """Handle completion status messages from InputBox."""
        # Show as toast notification with brief timeout
        self.notify(event.text, timeout=2)

    async def on_input_box_submitted(self, event: InputBox.Submitted) -> None:
        """Handle user input submission (Phase 6.1 - Engine integration)."""
        message = event.value.strip()
        if not message:
            return

        # Prevent concurrent submissions while streaming
        if self._engine_client and self._engine_client.state.get("is_streaming"):
            self.notify(
                "Please wait for the current response to complete",
                title="Streaming in Progress",
                severity="warning",
                timeout=3,
            )
            return

        # Add to session command history for persistence (matches Rich TUI behavior)
        if self._engine_client:
            self._engine_client.session.add_to_history(message)

        chat_view = self._chat_view

        # Handle commands
        if message.startswith("/"):
            await self._handle_command(message)
            return

        # Add user message to chat
        chat_view.add_user_message(message)

        # Stream response from engine using Textual's call_from_thread()
        if self._engine_client:
            # v1.17.4 Phase 7.3: if files are staged, build multimodal
            # content. Same pipeline as Rich TUI (build_multimodal_content
            # → preprocess_file). Pending files are cleared after the
            # stream thread receives the payload, so a failed stream
            # doesn't leave orphaned attachments on the next turn.
            pending = list(self.pending_files)
            if pending:
                # ADR 0006 Step 2/3: build_multimodal_content now returns
                # (parts, attachment_refs); refs threaded into engine.chat
                # below so Message.attachments is populated from producer
                # side without re-deriving from in-block keys.
                chat_payload, attachment_refs = build_multimodal_content(
                    message,
                    pending,
                    model=self._engine_client.model or "",
                    provider=self._engine_client.provider_name or "",
                    file_store=self._engine_client.file_store,
                    vl_captioner=(
                        self._engine_client.caption_image
                        if self._engine_client.has_vision_sidecar()
                        else None
                    ),
                )
                self.pending_files.clear()
                self._log.info(
                    f"Sending multimodal: {len(pending)} file(s), "
                    f"{len(chat_payload)} part(s), "
                    f"{len(attachment_refs)} artifact ref(s)"
                )
            else:
                chat_payload = message
                attachment_refs = []

            # Setup in main thread (UI-safe)
            status_bar = self._status_bar
            self._current_message_content = ""
            self._engine_client.state.update(is_streaming=True, cancel_requested=False)
            self._reasoning_started = False
            self._reasoning_content = ""
            self._reasoning_message = None

            # Track timing
            self._response_start_time = time.time()

            # Show streaming indicator in footer
            footer_status = self._footer_status
            footer_status.set_thinking()

            self._log.info("Stream setup complete, starting worker thread")

            # Start worker thread (doesn't block UI)
            # Worker will use call_from_thread() to emit events in main thread
            thread = threading.Thread(
                target=self._stream_response_thread,
                args=(chat_payload, self._engine_client, attachment_refs or None),
                daemon=True
            )
            thread.start()
        else:
            chat_view.add_system_message(
                "[yellow]Engine not initialized[/yellow]"
            )

    # === Streaming (delegated to stream_handler.py) ===

    def _stream_response_thread(self, user_input, engine_client, attachment_refs=None) -> None:
        """Worker thread: stream from engine. Delegated to stream_handler.

        ADR 0006 Step 3: `attachment_refs` is the producer-pipeline output
        (kind-specific ArtifactRefs from build_multimodal_content); None
        for plain-text turns.
        """
        stream_handler.stream_response_thread(self, user_input, engine_client, attachment_refs)

    def _handle_stream_event(self, event_type: str, event_data: any) -> None:
        """Handle stream event in main thread. Delegated to stream_handler."""
        stream_handler.handle_stream_event(self, event_type, event_data)

    async def _handle_command(self, command: str) -> None:
        """Handle slash commands using Command Factory pattern."""
        chat_view = self._chat_view
        parts = command[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Special case: quit/exit (direct action)
        if cmd in ("quit", "q", "exit"):
            self.exit()
            return

        # Special case: debug-log (TUI-specific, not in command factory)
        if cmd == "debug-log":
            await self._handle_debug_log_command(args)
            return

        # Handle /<command> help pattern - redirect to /help <command>
        # e.g., "/usage help" becomes "/help usage"
        if args.strip().lower() == "help" and cmd != "help":
            args = cmd
            cmd = "help"

        # Try Command Factory first
        spec = CommandFactory.get(cmd)
        if spec:
            try:
                # Call command handler with context
                if self._debug_logging:
                    self._log.debug(f"Calling handler for command: {cmd} with args: {args}")
                result = spec.handler(self, args)
                if self._debug_logging:
                    self._log.debug(f"Handler returned: {type(result).__name__}")

                # Check if result is a coroutine (async handler)
                if inspect.iscoroutine(result):
                    if self._debug_logging:
                        self._log.debug(f"Handler returned coroutine, awaiting it")
                    result = await result

                # Render result if it's a CommandResult type
                if result is not None:
                    renderer = TextualRenderer(self)
                    await renderer.render(result)

                    # Emit event bus events for subscribable result types
                    RESULT_EVENT_MAP = {
                        DirectoryListingResult: Events.UI_DIRECTORY_LISTED,
                        DirectoryTreeResult: Events.UI_TREE_LOADED,
                    }
                    bus_event = RESULT_EVENT_MAP.get(type(result))
                    if bus_event:
                        self._event_bus.emit(bus_event, data=result)

                # AppState observers handle provider/model/tools badge sync
                # automatically after session load and tools commands.

                if cmd in ("tools", "agent"):
                    # Update agent mode badge (Phase 1.3)
                    if cmd == "agent" and self._engine_client:
                        agent_mode = self._engine_client.state.get("agent_mode")
                        if agent_mode:
                            status_bar.add_badge("agent", "Agent", "ACTIVE", variant="success")
                            self._update_checkpoint_badge(status_bar)
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

                        # Update completer working directory for file completions
                        input_box = self._input_box
                        if input_box._completer:
                            input_box._completer.update_working_dir(Path(engine_working_dir))

                # Handle status bar toggle commands (Phase 1.2)
                if cmd == "status" and args and args.split()[0] in ("version", "cwd", "datetime"):
                    subcommand = args.split()[0]
                    tui_config = get_tui_config()
                    status_bar = self._status_bar

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
                                status_bar.add_badge("cwd", "Dir", self._format_cwd_display(cwd), variant="info")
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
                input_box = self._input_box
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

    async def _handle_debug_log_command(self, args: str) -> None:
        """Handle /debug-log command to toggle verbose event logging.

        Usage:
            /debug-log on   - Enable event bus and handler logging
            /debug-log off  - Disable event bus and handler logging
            /debug-log      - Show current status
        """
        chat_view = self._chat_view
        args = args.strip().lower()

        if not args:
            # Show current status
            status = "enabled" if self._debug_logging else "disabled"
            chat_view.add_system_message(
                f"[bold]Debug Logging:[/bold] {status}\n"
                f"Use [cyan]/debug-log on[/cyan] or [cyan]/debug-log off[/cyan] to toggle."
            )
        elif args == "on":
            self.toggle_debug_logging(True)
            chat_view.add_system_message(
                "[green]✓[/green] Debug logging enabled\n"
                "[dim]Event bus and handler logs will be verbose[/dim]"
            )
        elif args == "off":
            self.toggle_debug_logging(False)
            chat_view.add_system_message(
                "[green]✓[/green] Debug logging disabled\n"
                "[dim]Event bus and handler logs will be minimal[/dim]"
            )
        else:
            chat_view.add_system_message(
                f"[yellow]Unknown argument: {args}[/yellow]\n"
                f"Use [cyan]/debug-log on[/cyan] or [cyan]/debug-log off[/cyan]"
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
        chat_view = self._chat_view
        status_bar = self._status_bar

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

    def action_noop(self) -> None:
        """No-op action for display-only bindings.

        Used by ctrl+enter app binding — shown in footer but actual handling
        is in ChatTextArea.on_key() (submit) and FileTree.action_edit() (edit file).
        """
        pass

    def action_quit(self) -> None:
        """Quit the application with double Ctrl+C confirmation.

        First Ctrl+C shows a warning, second Ctrl+C within timeout actually exits.
        This prevents accidental exits when user intends to copy text.

        If streaming is active, first Ctrl+C cancels the stream instead of showing quit warning.
        """
        now = time.time()
        time_since_last = now - self._last_ctrl_c_time

        # If streaming is active, first Ctrl+C cancels the stream
        is_streaming = self._engine_client and self._engine_client.state.get("is_streaming")
        cancel_requested = self._engine_client and self._engine_client.state.get("cancel_requested")
        if is_streaming and not cancel_requested:
            self._engine_client.interrupt_stream()
            self._log.info("Cancellation requested for active stream")
            self.notify(
                "Cancelling stream... Press Ctrl+C again to force quit",
                title="Cancelling",
                timeout=2.0
            )
            # Reset timer so next Ctrl+C within timeout will quit
            self._last_ctrl_c_time = now
            return

        if time_since_last < self._CTRL_C_TIMEOUT:
            # Second Ctrl+C within timeout - actually quit
            # Mark session clean on graceful exit (Phase 2.2)
            if self._engine_client:
                try:
                    self._engine_client.session.mark_clean()
                    self._log.debug("Marked session as clean on exit")
                except Exception as e:
                    self._log.warning(f"Failed to mark session clean: {e}")
            self.exit()
        else:
            # First Ctrl+C - show warning
            self._last_ctrl_c_time = now
            self.notify(
                "Press Ctrl+C again to exit",
                title="Quit?",
                timeout=self._CTRL_C_TIMEOUT
            )

    def action_clear(self) -> None:
        """Clear the chat view."""
        chat_view = self._chat_view
        chat_view.clear()


    def action_cycle_theme(self) -> None:
        """Cycle through curated themes (Ctrl+T)."""
        self._current_theme_index = (self._current_theme_index + 1) % len(CYCLE_THEMES)
        theme_name = CYCLE_THEMES[self._current_theme_index]
        self.theme = theme_name
        self.notify(f"Theme: {theme_name}", title="Theme Changed")

    def action_cancel(self) -> None:
        """Cancel current operation or close help panel/side panel.

        Handles Escape key for various dismissible UI elements.
        Priority order: help panel > modal screens > side panel > nothing
        """
        # Try to close help panel first (Textual's built-in keys help)
        # action_hide_help_panel() is safe to call even if help panel isn't showing
        try:
            self.action_hide_help_panel()
            return
        except Exception:
            pass

        # Check if there's a modal screen (fallback)
        if len(self.screen_stack) > 1:
            self.pop_screen()
            return

        # If focus is in the file tree, return to input (don't close tree).
        # v1.18.0 Phase 5f: narrowed from bare Exception to NoMatches —
        # the only expected failure is "file-tree not mounted in this
        # layout state." Any other exception should propagate.
        focused = self.focused
        try:
            file_tree = self.query_one("#file-tree", FileTree)
            if focused and file_tree in focused.ancestors_with_self:
                self.query_one("#input-box", InputBox).focus()
                return
        except NoMatches:
            pass

        # Check if side panel is open
        side_panel = self.query_one("#side-panel", SidePanel)
        if side_panel.is_open:
            side_panel.close()

    def action_toggle_file_tree(self) -> None:
        """Show or hide the file tree browser (Ctrl+B)."""
        # v1.18.0 Phase 5f: narrowed from bare Exception to NoMatches.
        try:
            file_tree = self.query_one("#file-tree", FileTree)
        except NoMatches:
            return
        self._file_tree_visible = not self._file_tree_visible
        if self._file_tree_visible:
            file_tree.remove_class("hidden")
        else:
            file_tree.add_class("hidden")
        # If side panel is open, recompute its width for the new layout
        side_panel = self.query_one("#side-panel", SidePanel)
        if side_panel.is_open:
            self._apply_split_ratio()

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
        """Cycle focus: input → file tree (if visible) → side panel (if open) → input.

        F6 / Ctrl+Tab.
        """
        side_panel = self.query_one("#side-panel", SidePanel)
        input_box = self._input_box
        focused = self.focused

        # Determine where focus currently is
        in_input = focused and input_box in focused.ancestors_with_self
        in_side_panel = side_panel.is_open and focused and side_panel in focused.ancestors_with_self

        try:
            file_tree = self.query_one("#file-tree", FileTree)
            in_file_tree = self._file_tree_visible and focused and file_tree in focused.ancestors_with_self
        except Exception:
            file_tree = None
            in_file_tree = False

        if in_input:
            # From input: go to file tree (if visible), else side panel (if open), else stay
            if file_tree and self._file_tree_visible:
                file_tree.focus()
            elif side_panel.is_open:
                side_panel.focus()
        elif in_file_tree:
            # From file tree: go to side panel (if open), else input
            if side_panel.is_open:
                side_panel.focus()
            else:
                input_box.focus()
        elif in_side_panel:
            # From side panel: go back to input
            input_box.focus()
        else:
            # Focus is elsewhere: return to input
            input_box.focus()

    def action_resize_panel(self, direction: str) -> None:
        """Resize panes (Ctrl+[/]).

        When focus is in file tree: resize the tree width.
        Otherwise: resize the chat/side-panel split.

        Args:
            direction: 'left' to shrink, 'right' to grow the focused pane
        """
        # Check if focus is in the file tree
        focused = self.focused
        try:
            file_tree = self.query_one("#file-tree", FileTree)
            in_file_tree = (
                self._file_tree_visible
                and focused
                and file_tree in focused.ancestors_with_self
            )
        except Exception:
            in_file_tree = False

        if in_file_tree:
            # Resize file tree width
            # Ctrl+[ → shrink tree, Ctrl+] → grow tree
            if direction == "left" and self._tree_width_index > 0:
                self._tree_width_index -= 1
            elif direction == "right" and self._tree_width_index < len(self.TREE_WIDTHS) - 1:
                self._tree_width_index += 1
            else:
                return
            self._apply_tree_width()
            tree_pct = self.TREE_WIDTHS[self._tree_width_index]
            self.notify(f"Tree: {tree_pct}%", title="Resize")
            # Recompute side panel if open
            side_panel = self.query_one("#side-panel", SidePanel)
            if side_panel.is_open:
                self._apply_split_ratio()
            return

        # Default: resize chat/side-panel split
        side_panel = self.query_one("#side-panel", SidePanel)
        if not side_panel.is_open:
            return

        # Ctrl+[ (left) → shrink panel, Ctrl+] (right) → grow panel
        if direction == "left" and self._split_index > 0:
            self._split_index -= 1
        elif direction == "right" and self._split_index < len(self.SPLIT_RATIOS) - 1:
            self._split_index += 1
        else:
            return

        self._apply_split_ratio()
        chat_pct = self.SPLIT_RATIOS[self._split_index]
        self.notify(f"Split: {chat_pct}% / {100 - chat_pct}%", title="Resize")

    def _apply_tree_width(self) -> None:
        """Apply the current tree width to the file tree pane."""
        try:
            file_tree = self.query_one("#file-tree", FileTree)
            tree_pct = self.TREE_WIDTHS[self._tree_width_index]
            file_tree.styles.width = f"{tree_pct}%"
        except Exception:
            pass

    def _apply_split_ratio(self) -> None:
        """Apply the current split ratio to chat and panel panes.

        Chat pane uses width: 1fr in CSS and fills whatever space remains after
        the file tree and the side panel (explicit %).
        We only need to set the side panel's explicit width here.
        """
        file_tree_pct = self.TREE_WIDTHS[self._tree_width_index] if self._file_tree_visible else 0
        available_pct = 100 - file_tree_pct

        chat_ratio = self.SPLIT_RATIOS[self._split_index] / 100.0
        panel_ratio = 1.0 - chat_ratio
        panel_pct = panel_ratio * available_pct

        side_panel = self.query_one("#side-panel", SidePanel)
        side_panel.styles.width = f"{panel_pct:.1f}%"

    def toggle_debug_logging(self, enabled: bool) -> None:
        """Toggle debug logging for event bus and handlers.

        Args:
            enabled: True to enable debug logging, False to disable
        """
        self._debug_logging = enabled
        self._trace_logging = enabled  # Enable trace for verbose per-event logging
        self._event_bus._log_events = enabled
        # Enable/disable all file loggers (tui, chat, session, validator, etc.)
        if enabled:
            Logger.enable_all()
        else:
            Logger.disable_all()
        # Persist so next startup enables logger BEFORE session-recovery prompt
        # — see memory/feedback_session_recovery_ordering.md
        from ..config import set_tui_config
        set_tui_config("debug_log", enabled)
        # Sync to AppState
        if self._engine_client:
            self._engine_client.state.set("debug_log", enabled)
        self._log.info(f"Debug logging {'enabled' if enabled else 'disabled'}")

    def on_side_panel_opened(self, event: SidePanel.Opened) -> None:
        """Handle side panel opened - adjust layout."""
        try:
            # Shrink chat pane to make room for side panel
            chat_pane = self.query_one("#chat-pane")
            chat_pane.add_class("split-active")
            # Apply current split ratio
            self._apply_split_ratio()
            # Make input box taller when split view is active
            input_box = self._input_box
            input_box.add_class("split-mode")
        except Exception:
            # In test mode or special screens, widgets might not exist
            pass

    def on_side_panel_closed(self, event: SidePanel.Closed) -> None:
        """Handle side panel closed - restore layout."""
        try:
            # Restore chat pane to fill remaining space (file tree may still be visible)
            chat_pane = self.query_one("#chat-pane")
            chat_pane.remove_class("split-active")
            chat_pane.styles.width = "1fr"
            # Restore input box height
            input_box = self._input_box
            input_box.remove_class("split-mode")
            # Refocus input after closing panel
            input_box.focus()
            # Reset split ratio to default for next time
            self._split_index = self.DEFAULT_SPLIT_INDEX
        except Exception:
            # In test mode or special screens, widgets might not exist
            pass

    async def _open_file_from_tree(self, path: Path, read_only: bool) -> None:
        """Read a file and display it in the side panel (called by FileTree handlers)."""
        ext = path.suffix.lower()
        image_formats = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico', '.tiff', '.tif'}

        if ext in image_formats:
            if can_display_images():
                await self.show_file_in_panel(path, "", mode="image", read_only=True)
            else:
                self.notify(f"Terminal does not support image display", title=path.name, severity="warning")
            return

        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            self.notify(f"Cannot read binary file: {path.name}", severity="error")
            return
        except Exception as e:
            self.notify(f"Error reading file: {e}", severity="error")
            return

        data_formats = {'.json', '.yaml', '.yml', '.toml'}
        tabular_formats = {'.csv', '.tsv'}
        if ext in data_formats:
            mode = "tree"
        elif ext in tabular_formats:
            mode = "table"
        elif ext in ('.md', '.markdown'):
            mode = "markdown"
        else:
            mode = "code"

        await self.show_file_in_panel(path, content, mode=mode, read_only=read_only)

    async def on_file_tree_file_preview(self, event: FileTree.FilePreview) -> None:
        """Handle file tree Enter — open file read-only in the side panel."""
        await self._open_file_from_tree(event.path, read_only=True)

    async def on_file_tree_file_edit(self, event: FileTree.FileEdit) -> None:
        """Handle file tree Ctrl+Enter — open file editable in the side panel."""
        await self._open_file_from_tree(event.path, read_only=False)

    def on_file_tree_file_inject(self, event: FileTree.FileInject) -> None:
        """Handle file tree Space — inject @file reference into the chat input."""
        try:
            rel_path = event.path.relative_to(Path(self._working_dir))
        except ValueError:
            rel_path = event.path
        input_box = self._input_box
        input_box.inject_text(f"@file:{rel_path} ")
        self.notify(f"Injected @file:{rel_path}", title="File injected")

    def on_file_tree_file_attach(self, event: FileTree.FileAttach) -> None:
        """Handle file tree 'a' key — stage file for next chat turn (Phase 7.1).

        Reads file bytes, runs early validation for images, creates a
        PendingFile, and stages it in `_pending_files`. On the next chat
        submit, `_stream_response_thread` will consume the pending files
        through `build_multimodal_content` → `preprocess_file`.
        """
        file_store = getattr(self._engine_client, "file_store", None)
        pf, err = _attach_load_file(str(event.path), self._working_dir, file_store=file_store)
        if err:
            self.notify(err, title="Attach failed", severity="error", timeout=5)
            return

        self.pending_files.append(pf)
        kind_icon = "\U0001F5BC" if pf.kind == "image" else "\U0001F4C4"
        self.notify(
            f"{kind_icon} {pf.name} ({pf.media_type}, {pf.size / 1024:.1f} KB) staged",
            title="Attached",
            timeout=3,
        )

    def action_attach_shortcut(self) -> None:
        """Ctrl+U — open or focus the file tree for attaching (Phase 7.2).

        If the file tree is hidden, show it. Then focus it so the user
        can immediately navigate with arrow keys and press 'a' to attach
        the highlighted file. Pressing Ctrl+U a second time while the
        tree is already focused does nothing (not toggle-close) — that
        matches the docstring intent: this shortcut is a "get me to
        attach mode in one keystroke", not a show/hide toggle.
        Ctrl+B remains the show/hide toggle.
        """
        # Step 1: make sure the tree is visible. `action_toggle_file_tree`
        # is a pure toggle, so only call it when the tree is currently
        # hidden — otherwise it would close a tree the user wants to use.
        if not self._file_tree_visible:
            self.action_toggle_file_tree()

        # Step 2: move focus to the tree so the 'a' key hits it directly.
        # Ignored silently if the tree widget isn't mounted yet (shouldn't
        # happen during a normal session, but belt-and-suspenders so a
        # shortcut press during app startup doesn't raise).
        try:
            file_tree = self.query_one("#file-tree", FileTree)
        except NoMatches:
            return
        file_tree.focus()

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

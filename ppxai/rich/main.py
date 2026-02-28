"""
Main entry point for the ppxai application.
"""

import argparse
import os
import sys
import asyncio
import time
from pathlib import Path

from ..version import __version__

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

from ..commands.handler import CommandHandler
from ..config import (
    PROVIDERS,
    get_default_provider,
    get_default_model,
    get_api_key,
    get_auto_restore_mode,
    get_auto_save_interval,
    get_base_url,
    get_provider_config,
    get_tui_config,
    get_tui_theme,
)
from .ui import console, display_welcome, select_model, select_provider
from .ui_components import format_usage_string, render_status_line, render_status_panel
from ..engine.session import SessionManager
from ..engine.types import EventType
from .markdown_tables import render_markdown_with_tables
from .themes import get_theme
from ..common.logger import get_logger
from .event_handler import TUIEventHandler

logger = get_logger("tui")


def format_tokens(count: int) -> str:
    """Format token count for display (e.g., 1.2K, 15.3K)."""
    if count >= 1000:
        return f"{count/1000:.1f}K"
    return str(count)


def get_status_line(handler, use_themed: bool = True):
    """Generate status line showing current settings.

    v1.12.0: Now uses handler.provider instead of legacy client.
    v1.12.0: Added agent mode and checkpoint status.
    v1.12.0: Added session token usage and cost display.
    v1.12.0: Added themed status line with badges (experiment/rich-tui).
    """
    provider_config = get_provider_config(handler.provider)
    provider_name = provider_config["name"]

    # Get tools status (v1.12.0: engine only)
    tools_enabled = handler.engine_client.tools_enabled if handler.engine_client else False

    # Get model display name (use ID if not found)
    model_display = handler.current_model
    for model_info in provider_config.get("models", {}).values():
        if model_info.get("id") == handler.current_model:
            model_display = model_info.get("name", handler.current_model)
            break

    # Get agent mode status (v1.12.0)
    agent_mode = handler.engine_client and handler.engine_client.agent_mode

    # Get checkpoint status for display (v1.12.1)
    # Shows user-friendly label instead of git hash
    checkpoint_str = None
    if agent_mode and handler.engine_client:
        checkpoint_status = handler.engine_client.get_checkpoint_status()
        if checkpoint_status.get("enabled"):
            last_checkpoint = checkpoint_status.get("last_checkpoint")
            is_valid = checkpoint_status.get("is_valid", True)
            if last_checkpoint:
                if not is_valid:
                    checkpoint_str = "↶!"  # Stale - undo may not work correctly
                else:
                    checkpoint_str = "↶"  # Valid checkpoint - undo available

    # Get session usage stats (v1.12.0, v1.12.2: display mode support)
    usage_str = None
    if handler.engine_client:
        # Use display mode-aware method
        usage_display = handler.engine_client.session.get_usage_for_display(
            current_provider=handler.provider,
            current_model=handler.current_model
        )

        if usage_display:  # None if display_mode is "off"
            prompt_tokens = usage_display.get("prompt_tokens", 0)
            completion_tokens = usage_display.get("completion_tokens", 0)
            cost = usage_display.get("estimated_cost", 0.0)
            label = usage_display.get("label")  # Provider/model label or None

            if prompt_tokens > 0 or completion_tokens > 0:
                usage_str = format_usage_string(prompt_tokens, completion_tokens, cost)
                # Add label prefix for provider/model modes
                if label:
                    usage_str = f"[{label}] {usage_str}"

    # Use themed status line if available (experiment/rich-tui)
    if use_themed:
        # Use handler's current theme if set, otherwise fall back to config
        theme_name = getattr(handler, 'current_theme_name', None) or get_tui_theme()
        theme = get_theme(theme_name)

        # Get TUI display options
        tui_config = get_tui_config()
        show_version = tui_config.get("show_version", True)
        show_cwd = tui_config.get("show_cwd", True)
        show_datetime = tui_config.get("show_datetime", False)

        # Get working directory from engine
        working_dir = None
        if show_cwd and handler.engine_client:
            working_dir = handler.engine_client.get_working_dir()

        # Get context usage percentage
        context_percent = None
        if handler.engine_client:
            try:
                context_info = handler.engine_client.get_context_info()
                context_percent = context_info.get('usage_percent', 0)
            except Exception:
                pass  # Silently ignore errors getting context info

        # Use framed panel for status (experiment/rich-tui)
        return render_status_panel(
            provider=provider_name,
            model=model_display,
            tools_enabled=tools_enabled,
            agent_mode=agent_mode,
            usage_str=usage_str,
            checkpoint_str=checkpoint_str,
            theme=theme,
            version=f"v{__version__}" if show_version else None,
            working_dir=working_dir,
            show_datetime=show_datetime,
            context_percent=context_percent,
        )

    # Fallback: plain text status line
    tools_status = "[green]ON[/green]" if tools_enabled else "[dim]OFF[/dim]"

    # Build legacy status line
    parts = [provider_name, model_display, f"Tools: {tools_status}"]
    if agent_mode:
        parts.append("Agent: [green]ON[/green]")
        if checkpoint_str:
            parts.append(f"[cyan]{checkpoint_str}[/cyan]")  # ↶ for undo available, ↶! for stale
    if usage_str:
        parts.append(f"[cyan]{usage_str}[/cyan]")

    status = "[dim][[/dim]" + "[dim] | [/dim]".join(parts) + "[dim]][/dim]"
    return status


class PPXAICompleter(Completer):
    """Custom completer for slash commands and @file references."""

    COMMANDS = [
        ('/help', 'Show available commands'),
        ('/model', 'Switch model'),
        ('/provider', 'Switch provider'),
        ('/clear', 'Clear conversation history'),
        ('/save', 'Save session to JSON'),
        ('/export', 'Export last answer to markdown'),
        ('/copy', 'Copy last response to clipboard'),
        ('/load', 'Load a saved session'),
        ('/sessions', 'List saved sessions'),
        ('/new', 'Start new session'),
        ('/history', 'Show conversation history'),
        ('/tools', 'Manage AI tools'),
        ('/show', 'Display file contents'),
        ('/cat', 'Display file contents (alias)'),
        ('/usage', 'Show token usage stats'),
        ('/status', 'Show current status'),
        ('/explain', 'Explain code'),
        ('/test', 'Generate tests'),
        ('/review', 'Review code'),
        ('/debug', 'Debug code'),
        ('/optimize', 'Optimize code'),
        ('/agent', 'Run autonomous agent loop'),
        ('/undo', 'Revert last agent task'),
        ('/checkpoint', 'Manage checkpoint settings'),
        ('/theme', 'Switch or list themes'),
        ('/quit', 'Exit the application'),
        ('/exit', 'Exit the application'),
    ]

    # Subcommands for /tools
    TOOLS_SUBCOMMANDS = [
        ('enable', 'Enable AI tools'),
        ('disable', 'Disable AI tools'),
        ('list', 'List available tools'),
        ('status', 'Show tools status'),
        ('help', 'Show help for a tool'),
        ('set', 'Configure tool settings'),
        ('config', 'Configure tool settings'),
        ('agent', 'Enable/disable agent mode'),
    ]

    # Theme names for /theme autocomplete
    THEME_NAMES = [
        ('list', 'Show available themes'),
        ('standard', 'Default ppxai theme'),
        ('tron-legacy', 'Cyan/orange Tron: Legacy style'),
        ('matrix', 'Green-on-black Matrix style'),
        ('nord', 'Arctic bluish Nord palette'),
    ]

    # Subcommands for /usage (v1.12.2)
    USAGE_SUBCOMMANDS = [
        ('show', 'Set status line display mode'),
        ('reset', 'Reset all usage counters'),
    ]

    # Subcommands for /checkpoint (v1.12.4)
    CHECKPOINT_SUBCOMMANDS = [
        ('status', 'Show checkpoint status'),
        ('list', 'List recent checkpoints'),
        ('backend', 'Set checkpoint backend'),
        ('clear', 'Clear old file-based snapshots'),
        ('info', 'Show details about a checkpoint'),
        ('undo', 'Revert last checkpoint (alias)'),
    ]

    # Backend options for /checkpoint backend
    CHECKPOINT_BACKENDS = [
        ('git', 'Use git commits (requires git repo)'),
        ('file', 'Use file snapshots'),
        ('auto', 'Auto-detect best backend'),
        ('none', 'Disable checkpoints'),
    ]

    # Display modes for /usage show
    USAGE_DISPLAY_MODES = [
        ('session', 'Show session totals'),
        ('provider', 'Show current provider totals'),
        ('model', 'Show current model totals'),
        ('off', 'Hide usage from status line'),
    ]

    # Subcommands for /status
    STATUS_SUBCOMMANDS = [
        ('version', 'Show/toggle version display'),
        ('cwd', 'Show/toggle working directory display'),
        ('datetime', 'Show/toggle date/time display'),
    ]

    # Directories to ignore when searching for files
    IGNORE_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox', 'dist', 'build', '.eggs', '.mypy_cache'}

    def __init__(self, command_handler=None):
        self._file_cache = {}
        self._cache_time = 0
        self._cache_dir = None  # Track which directory the cache is for
        self._command_handler = command_handler

    def _get_working_dir(self) -> Path:
        """Get the current working directory from engine client or fallback to os.cwd()."""
        if self._command_handler and hasattr(self._command_handler, 'engine_client'):
            return Path(self._command_handler.engine_client.get_working_dir())
        return Path.cwd()

    def _get_files(self, max_files: int = 100) -> list[tuple[str, str]]:
        """Get files in the current directory for completion."""
        import time
        now = time.time()

        root = self._get_working_dir()

        # Cache for 5 seconds, but invalidate if directory changed
        if (now - self._cache_time < 5 and
            self._file_cache and
            self._cache_dir == root):
            return list(self._file_cache.items())[:max_files]

        files = {}

        try:
            for path in root.rglob('*'):
                if len(files) >= max_files * 2:
                    break
                try:
                    # Check if file - can fail on network paths (WinError 4350)
                    if path.is_file():
                        # Skip files in ignored directories
                        if any(ignored in path.parts for ignored in self.IGNORE_DIRS):
                            continue
                        try:
                            rel_path = str(path.relative_to(root))
                            files[path.name] = rel_path
                        except ValueError:
                            pass
                except OSError:
                    # Network file unavailable, skip it
                    pass
        except (PermissionError, OSError):
            pass

        self._file_cache = files
        self._cache_time = now
        self._cache_dir = root  # Remember which directory this cache is for
        return list(files.items())[:max_files]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Check for @file reference anywhere in the text (priority over commands)
        at_pos = text.rfind('@')
        if at_pos >= 0:
            # Get the query after @
            query = text[at_pos + 1:].lower()

            # Show file completions
            for filename, filepath in self._get_files():
                if not query or query in filename.lower() or query in filepath.lower():
                    # Calculate how much to replace (from @ to cursor)
                    replace_len = len(text) - at_pos
                    yield Completion(
                        '@' + filename,
                        start_position=-replace_len,
                        display=filename,
                        display_meta=filepath
                    )
            return  # Don't show command completions when typing @file

        # Check for slash command at start of line (only if no @ in text)
        if text.startswith('/'):
            cmd_text = text.lower()

            # Handle /tools subcommands
            if cmd_text.startswith('/tools '):
                parts = text.split()
                if len(parts) == 2:
                    # Completing subcommand: /tools en<tab>
                    subquery = parts[1].lower()
                    for subcmd, desc in self.TOOLS_SUBCOMMANDS:
                        if subcmd.startswith(subquery):
                            yield Completion(
                                subcmd,
                                start_position=-len(parts[1]),
                                display_meta=desc
                            )
                elif len(parts) >= 3 and parts[1].lower() == 'help':
                    # Completing tool name: /tools help calc<tab>
                    tool_query = parts[2].lower() if len(parts) > 2 else ''
                    for tool_name, tool_desc in self._get_tool_names():
                        if tool_name.lower().startswith(tool_query):
                            yield Completion(
                                tool_name,
                                start_position=-len(tool_query) if tool_query else 0,
                                display_meta=tool_desc[:40] + '...' if len(tool_desc) > 40 else tool_desc
                            )
                return

            # Handle /theme subcommands (experiment/rich-tui)
            if cmd_text.startswith('/theme '):
                parts = text.split()
                if len(parts) == 2:
                    # Completing theme name or emoji subcommand: /theme ma<tab> or /theme em<tab>
                    query = parts[1].lower()

                    # Check if typing "emoji" subcommand
                    if 'emoji'.startswith(query):
                        yield Completion(
                            'emoji',
                            start_position=-len(parts[1]),
                            display_meta='Toggle emoji mode (on|off)'
                        )

                    # Theme names
                    for theme_name, desc in self.THEME_NAMES:
                        if theme_name.startswith(query):
                            yield Completion(
                                theme_name,
                                start_position=-len(parts[1]),
                                display_meta=desc
                            )
                elif len(parts) == 3 and parts[1].lower() == 'emoji':
                    # Completing /theme emoji on|off
                    emoji_query = parts[2].lower()
                    for opt, desc in [('on', 'Show original emojis'), ('off', 'Convert to text symbols')]:
                        if opt.startswith(emoji_query):
                            yield Completion(
                                opt,
                                start_position=-len(parts[2]),
                                display_meta=desc
                            )
                return

            # Handle /usage subcommands (v1.12.2)
            if cmd_text.startswith('/usage '):
                parts = text.split()
                if len(parts) == 2:
                    # Completing subcommand: /usage sh<tab>
                    subquery = parts[1].lower()
                    for subcmd, desc in self.USAGE_SUBCOMMANDS:
                        if subcmd.startswith(subquery):
                            yield Completion(
                                subcmd,
                                start_position=-len(parts[1]),
                                display_meta=desc
                            )
                elif len(parts) == 3 and parts[1].lower() == 'show':
                    # Completing display mode: /usage show se<tab>
                    mode_query = parts[2].lower()
                    for mode, desc in self.USAGE_DISPLAY_MODES:
                        if mode.startswith(mode_query):
                            yield Completion(
                                mode,
                                start_position=-len(parts[2]),
                                display_meta=desc
                            )
                return

            # Handle /checkpoint subcommands (v1.12.4)
            if cmd_text.startswith('/checkpoint '):
                parts = text.split()
                if len(parts) == 2:
                    # Completing subcommand: /checkpoint st<tab>
                    subquery = parts[1].lower()
                    for subcmd, desc in self.CHECKPOINT_SUBCOMMANDS:
                        if subcmd.startswith(subquery):
                            yield Completion(
                                subcmd,
                                start_position=-len(parts[1]),
                                display_meta=desc
                            )
                elif len(parts) == 3 and parts[1].lower() == 'backend':
                    # Completing backend: /checkpoint backend gi<tab>
                    backend_query = parts[2].lower()
                    for backend, desc in self.CHECKPOINT_BACKENDS:
                        if backend.startswith(backend_query):
                            yield Completion(
                                backend,
                                start_position=-len(parts[2]),
                                display_meta=desc
                            )
                return

            # Handle /status subcommands (v1.13.10)
            if cmd_text.startswith('/status '):
                parts = text.split()
                if len(parts) == 2:
                    # Completing subcommand: /status ver<tab>
                    subquery = parts[1].lower()
                    for subcmd, desc in self.STATUS_SUBCOMMANDS:
                        if subcmd.startswith(subquery):
                            yield Completion(
                                subcmd,
                                start_position=-len(parts[1]),
                                display_meta=desc
                            )
                return

            # Regular command completion
            for cmd, desc in self.COMMANDS:
                if cmd.lower().startswith(cmd_text):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display_meta=desc
                    )

    def _get_tool_names(self) -> list[tuple[str, str]]:
        """Get available tool names and descriptions for completion."""
        if not self._command_handler:
            return []

        engine = self._command_handler.engine_client
        if not engine or not engine.tools_enabled or not engine.tool_manager:
            # Return common tool names even if tools not enabled
            return [
                ('calculator', 'Evaluate mathematical expressions'),
                ('get_datetime', 'Get current date and time'),
                ('list_directory', 'List files in a directory'),
                ('read_file', 'Read file contents'),
                ('execute_shell_command', 'Execute shell commands'),
                ('apply_patch', 'Apply unified diff patches'),
                ('replace_block', 'Find and replace text blocks'),
                ('insert_text', 'Insert text at line numbers'),
                ('delete_lines', 'Delete line ranges'),
                ('web_search', 'Search the web'),
                ('fetch_url', 'Fetch URL contents'),
            ]

        # Get actual tools from manager
        tools = engine.tool_manager.list_tools()
        return [(t['name'], t['description']) for t in tools]

# Note: Environment variables are loaded in config.py


def check_session_recovery() -> tuple[bool, dict | None]:
    """Check if there's a session to recover.

    v1.13.9: Implements session recovery logic based on config.

    Returns:
        Tuple of (should_restore, session_state) where:
        - should_restore: True if we should restore a session
        - session_state: Dict with session info if available
    """
    auto_restore = get_auto_restore_mode()

    # Get last session state
    last_state = SessionManager.get_last_session_state()
    if not last_state:
        return False, None

    session_name = last_state.get("name")
    is_dirty = last_state.get("dirty", False)
    message_count = last_state.get("message_count", 0)

    # Skip if no messages in last session
    if message_count == 0:
        return False, None

    # If session was dirty (crash), always try to recover
    if is_dirty:
        console.print(f"\n[yellow]⚠ Recovering from interrupted session:[/yellow] {session_name}")
        console.print(f"[dim]  {message_count} messages, last provider: {last_state.get('provider', 'unknown')}[/dim]")
        return True, last_state

    # Handle based on auto_restore config
    if auto_restore == "never":
        return False, None

    if auto_restore == "always":
        console.print(f"\n[cyan]↻ Restoring last session:[/cyan] {session_name}")
        console.print(f"[dim]  {message_count} messages[/dim]")
        return True, last_state

    # auto_restore == "prompt"
    console.print(f"\n[cyan]Last session available:[/cyan] {session_name}")
    console.print(f"[dim]  {message_count} messages, provider: {last_state.get('provider', 'unknown')}[/dim]")

    try:
        response = console.input("[cyan]Restore? (y/n): [/cyan]").strip().lower()
        if response in ('y', 'yes'):
            return True, last_state
    except (KeyboardInterrupt, EOFError):
        console.print()
        pass

    return False, None


def restore_session_to_handler(handler: CommandHandler, session_state: dict) -> bool:
    """Restore a session to the command handler.

    Args:
        handler: CommandHandler to restore to
        session_state: Session state dict from state file

    Returns:
        True if restored successfully
    """
    session_name = session_state.get("name")
    if not session_name:
        return False

    result = handler.engine_client.restore_session(session_name)
    if not result["success"]:
        console.print(f"[red]Failed to load session: {session_name}[/red]")
        return False

    handler.provider = result["provider"] or handler.provider
    handler.current_model = result["model"] or handler.current_model

    # Restore working directory
    working_dir = result["working_dir"]
    if working_dir and os.path.isdir(working_dir):
        try:
            os.chdir(working_dir)
        except Exception:
            pass

    console.print(f"[green]✓ Session restored:[/green] {session_name} ({result['message_count']} messages)")
    return True


def main():
    """Main application loop."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="ppxai - Terminal UI for AI providers")
    parser.add_argument("--version", "-v", action="version", version=f"ppxai {__version__}")
    parser.parse_args()

    # Initialize configuration system (v1.13.10: explicit initialization)
    from ..config import initialize
    initialize()

    # Check if provider selection is needed or use environment default
    provider = get_default_provider()

    # Allow provider selection at startup if multiple providers configured
    if len(PROVIDERS) > 1:
        console.print("\n[bold cyan]Available Providers:[/bold cyan]")
        for key, config in PROVIDERS.items():
            api_key_env = config["api_key_env"]
            has_key = bool(os.getenv(api_key_env))
            status = "[green]configured[/green]" if has_key else "[yellow]not configured[/yellow]"
            console.print(f"  - {key}: {config['name']} ({status})")

        # Check if user wants to change provider
        if os.getenv("MODEL_PROVIDER"):
            console.print(f"\n[dim]Using provider from MODEL_PROVIDER env: {provider}[/dim]")
        else:
            provider = select_provider()

    # Get provider configuration
    provider_config = get_provider_config(provider)
    api_key = get_api_key(provider)
    base_url = get_base_url(provider)

    if not api_key:
        api_key_env = provider_config["api_key_env"]
        console.print(f"[red]Error: {api_key_env} not found in environment variables.[/red]")
        console.print("[yellow]Please create a .env file with your API key (see .env.example)[/yellow]")
        sys.exit(1)

    console.print(f"\n[green]Connected to:[/green] {provider_config['name']} ({base_url})")

    # Display welcome
    display_welcome()

    # Select initial model (from provider's available models)
    current_model = select_model(provider)

    # Create command handler with provider info (no legacy client)
    handler = CommandHandler(api_key, current_model, base_url, provider)

    # Check for session recovery
    should_restore, session_state = check_session_recovery()
    if should_restore and session_state:
        if restore_session_to_handler(handler, session_state):
            # Update local variables from restored session
            provider = handler.provider
            current_model = handler.current_model

    # Create prompt session with history and completer
    # Pre-populate history from restored session
    history = InMemoryHistory()
    for cmd in handler.engine_client.session.command_history:
        history.append_string(cmd)

    completer = PPXAICompleter(command_handler=handler)
    session = PromptSession(
        history=history,
        completer=completer,
        complete_while_typing=True,
        auto_suggest=AutoSuggestFromHistory(),
    )

    # Main loop
    console.print("\n[bold green]Ready to chat! Type your message or /help for commands.[/bold green]")
    console.print("[dim]Tab: autocomplete • @file: reference files • ↑/↓: history • Ctrl-C twice to exit[/dim]\n")
    console.print(f"[dim]Session: {handler.engine_client.session.session_name}[/dim]\n")

    # Track Ctrl-C presses for double-press to exit
    ctrl_c_count = 0
    ctrl_c_timestamp = 0
    ctrl_c_timeout = 2.0  # seconds

    while True:
        try:
            # Reset Ctrl-C counter if timeout elapsed
            if ctrl_c_count > 0 and time.time() - ctrl_c_timestamp > ctrl_c_timeout:
                ctrl_c_count = 0

            # Display status line (v1.12.0: uses handler only)
            status_line = get_status_line(handler)
            console.print(status_line)

            # Get user input with history and completion support
            user_input = session.prompt("You: ").strip()

            # Reset Ctrl-C counter on successful input
            ctrl_c_count = 0

            if not user_input:
                continue

            # Add to command history
            handler.engine_client.session.add_to_history(user_input)

            # Handle commands
            if user_input.startswith("/"):
                should_exit = handler.handle_command(user_input)
                if should_exit:
                    break
                # Update current_model from handler (no legacy client)
                current_model = handler.current_model
                continue

            # Log user input
            if user_input.startswith('/'):
                logger.log_command(user_input)
            else:
                logger.log_user_message(user_input)

            # Send message to API
            # ALWAYS use EngineClient (created at startup)
            # This ensures @git/@tree/@file context injection always works
            if handler.engine_client:
                # Use engine with event-based streaming
                # EngineClient handles all context injection (@file, @git, @tree) internally
                async def stream_engine_response():
                    """Stream response from EngineClient using shared TUIEventHandler."""
                    # Create TUI-specific event handler with verbose setting, theme, and emoji mode
                    verbose = hasattr(handler, 'tools_verbose') and handler.tools_verbose
                    theme_name = getattr(handler, 'current_theme_name', None)
                    emoji_mode = getattr(handler, 'emoji_mode', False)
                    event_handler = TUIEventHandler(
                        console, logger,
                        verbose=verbose,
                        theme_name=theme_name,
                        emoji_mode=emoji_mode,
                        engine_client=handler.engine_client
                    )

                    # Process events using shared handler
                    # Pass user_input directly - EngineClient.chat() handles context injection
                    async for event in handler.engine_client.chat(user_input, stream=True):
                        should_continue = await event_handler.handle_event(event)
                        if not should_continue:
                            break

                    return event_handler.get_response()

                response = asyncio.run(stream_engine_response())

            # Update session metadata (v1.12.0: use engine session as source of truth)
            if response and handler.engine_client:
                message_count = len(handler.engine_client.session.messages)

                # Auto-save session based on config interval (dirty save for recovery)
                save_interval = get_auto_save_interval()
                if message_count > 0 and (save_interval == 0 or message_count % max(1, save_interval) == 0):
                    try:
                        handler.engine_client.session.save_dirty()
                    except Exception as e:
                        logger.warning(f"Auto-save failed: {e}")

        except KeyboardInterrupt:
            # Implement double Ctrl-C to exit
            ctrl_c_count += 1
            ctrl_c_timestamp = time.time()

            if ctrl_c_count == 1:
                # First Ctrl-C: Show warning with options
                console.print("\n[yellow]⚠ Activity interrupted![/yellow]")
                console.print("[yellow]  • Press Ctrl-C again to exit[/yellow]")
                console.print("[yellow]  • Or continue typing to resume[/yellow]\n")

                # Cleanup conversation history if interrupted during streaming (v1.12.0: engine only)
                cleaned = False
                if handler.engine_client and handler.engine_client.session.messages:
                    if handler.engine_client.session.messages[-1].role == "user":
                        handler.engine_client.session.remove_last_message()
                        cleaned = True
                if cleaned:
                    console.print("[dim]Conversation history cleaned up. Message chain is in a sane state.[/dim]\n")
            else:
                # Second Ctrl-C: Exit gracefully
                console.print("\n[yellow]Exiting gracefully...[/yellow]")
                # Mark session clean on graceful exit
                try:
                    handler.engine_client.session.mark_clean()
                except Exception:
                    pass
                break

            continue

        except EOFError:
            console.print("\n[yellow]Goodbye![/yellow]")
            # Mark session clean on graceful exit
            try:
                handler.engine_client.session.mark_clean()
            except Exception:
                pass
            break

        except Exception as e:
            console.print(f"\n[red]Unexpected error: {str(e)}[/red]\n")
            continue


if __name__ == "__main__":
    main()

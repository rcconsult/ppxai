"""
Command handlers for the ppxai application.

This module provides the CommandHandler class which handles all slash commands
in the TUI application (/help, /model, /save, /load, etc.).
"""


import asyncio
import os
import re
import warnings
from pathlib import Path

from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.validation import ValidationError, Validator

from ..common.consent import normalize_consent_response
from ..common.logger import get_logger
from ..config import (  # noqa: F401 — re-exported via commands/__init__.py
    get_api_key,
    get_base_url,
    get_coding_model,
    get_default_provider,
    get_provider_config,
    get_tui_theme,
)
from ..constants import ConsentDecision, ConsentResponse, ShellRiskLevel
from ..engine import EngineClient
from ..engine.types import EventType
from ..prompts import CODING_PROMPTS
from ..rich.themes import (
    DEFAULT_THEME,
    get_theme,
)
from ..rich.ui import (  # noqa: F401 — re-exported via commands/__init__.py
    console,
    display_file_editing_help,
    display_sessions,
    display_welcome,
    select_model,
    select_provider,
)

# Import command modules to trigger self-registration
from .context import RichCommandContext
from .factory import CommandFactory
from .results import CommandResult

logger = get_logger("tui")


class ConsentValidator(Validator):
    """Validator for file edit consent responses."""

    # Valid responses: short forms (y, n) and long forms (yes, no, always, never)
    VALID_RESPONSES = [
        ConsentResponse.YES, ConsentResponse.NO,  # "y", "n"
        ConsentResponse.ALWAYS, ConsentResponse.NEVER,  # "always", "never"
        ConsentDecision.YES, ConsentDecision.NO,  # "yes", "no"
    ]

    def validate(self, document):
        text = document.text.strip().lower()
        if text not in self.VALID_RESPONSES:
            raise ValidationError(
                message="Please enter: y (yes), n (no), always, or never",
                cursor_position=len(document.text)
            )


async def tui_consent_handler(file_path: str) -> tuple[bool, str]:
    """
    Handle file edit consent request in TUI.

    Prompts user with options:
    - y/yes: Allow editing this file (this session)
    - n/no: Deny editing this file
    - always: Allow editing all files (this session)
    - never: Deny all file edits (this session)

    Args:
        file_path: Path to file that needs editing

    Returns:
        tuple: (approved: bool, response: str) - response is normalized to ConsentResponse enum
    """
    console.print("\n[bold yellow]⚠️  File Edit Request[/bold yellow]")
    console.print(f"[cyan]AI wants to edit:[/cyan] {file_path}")
    console.print("[dim]Options: y (yes), n (no), always (all files), never (block all)[/dim]")

    try:
        # Use prompt_toolkit for input with validation
        response = await asyncio.to_thread(
            pt_prompt,
            "Allow edit? ",
            validator=ConsentValidator(),
            validate_while_typing=False
        )

        # Normalize response to ConsentResponse enum value
        normalized_response = normalize_consent_response(response)

        # Determine approval and show feedback
        approved = normalized_response in (ConsentResponse.YES, ConsentResponse.ALWAYS)

        if normalized_response == ConsentResponse.YES:
            console.print("[green]✓ Edit approved for this file[/green]\n")
        elif normalized_response == ConsentResponse.ALWAYS:
            console.print("[green]✓ All file edits approved for this session[/green]\n")
        elif normalized_response == ConsentResponse.NEVER:
            console.print("[yellow]✗ All file edits blocked for this session[/yellow]\n")
        else:  # NO
            console.print("[yellow]✗ Edit denied for this file[/yellow]\n")

        return (approved, normalized_response)

    except (KeyboardInterrupt, EOFError):
        # User cancelled - deny for safety
        console.print("\n[yellow]✗ Edit cancelled[/yellow]\n")
        return (False, ConsentResponse.NO)


async def tui_shell_consent_handler(command: str, working_dir: str, risk_level: str) -> tuple[bool, str]:
    """
    Handle shell command consent request in TUI.

    Prompts user with options:
    - y/yes: Allow executing this command (this session)
    - n/no: Deny executing this command
    - always: Allow all shell commands (this session)
    - never: Deny all shell commands (this session)

    Args:
        command: Shell command that needs execution
        working_dir: Working directory for the command
        risk_level: Risk level classification (safe, dangerous, never)

    Returns:
        tuple: (approved: bool, response: str) - response is normalized to ConsentResponse enum
    """
    # Determine risk color
    risk_color = {
        ShellRiskLevel.NEVER: "red",
        ShellRiskLevel.DANGEROUS: "yellow",
        ShellRiskLevel.SAFE: "green"
    }.get(risk_level, "yellow")

    console.print(f"\n[bold {risk_color}]⚠️  Shell Command Request[/bold {risk_color}]")
    console.print(f"[cyan]Command:[/cyan] {command}")
    console.print(f"[dim]Directory:[/dim] {working_dir}")
    console.print(f"[dim]Risk Level:[/dim] [{risk_color}]{risk_level.upper()}[/{risk_color}]")
    console.print("[dim]Options: y (yes), n (no), always (all commands), never (block all)[/dim]")

    try:
        # Use prompt_toolkit for input with validation
        response = await asyncio.to_thread(
            pt_prompt,
            "Allow command? ",
            validator=ConsentValidator(),
            validate_while_typing=False
        )

        # Normalize response to ConsentResponse enum value
        normalized_response = normalize_consent_response(response)

        # Determine approval and show feedback
        approved = normalized_response in (ConsentResponse.YES, ConsentResponse.ALWAYS)

        if normalized_response == ConsentResponse.YES:
            console.print("[green]✓ Command approved[/green]\n")
        elif normalized_response == ConsentResponse.ALWAYS:
            console.print("[green]✓ All shell commands approved for this session[/green]\n")
        elif normalized_response == ConsentResponse.NEVER:
            console.print("[yellow]✗ All shell commands blocked for this session[/yellow]\n")
        else:  # NO
            console.print("[yellow]✗ Command denied[/yellow]\n")

        return (approved, normalized_response)

    except (KeyboardInterrupt, EOFError):
        # User cancelled - deny for safety
        console.print("\n[yellow]✗ Command cancelled[/yellow]\n")
        return (False, ConsentResponse.NO)


def send_coding_task(handler: 'CommandHandler', task_type: str, user_message: str, model: str, provider: str = None) -> str | None:
    """Send a coding task with appropriate system prompt and optional auto-routing."""
    if task_type not in CODING_PROMPTS:
        console.print(f"[red]Unknown task type: {task_type}[/red]")
        return None

    # Auto-route to coding model if enabled (use provider-specific coding model)
    coding_model = get_coding_model(provider)
    if handler.auto_route and model != coding_model:
        model = coding_model
        console.print(f"[dim]Auto-routed to {coding_model} for coding task (disable with /autoroute off)[/dim]")

    # Create a temporary message with system instruction
    system_prompt = CODING_PROMPTS[task_type]
    full_message = f"{system_prompt}\n\n{user_message}"

    async def run_coding_task():
        content = ""
        # Temporarily switch model for coding task if auto-routed
        original_model = handler.engine_client.model
        if model != original_model:
            handler.engine_client.set_model(model, reset_context=False)

        try:
            async for event in handler.engine_client.chat(full_message, stream=True):
                if event.type == EventType.STREAM_CHUNK:
                    chunk = event.data
                    console.print(chunk, end="")
                    content += chunk
                elif event.type == EventType.ERROR:
                    console.print(f"\n[red]Error: {event.data}[/red]")
        finally:
            # Restore original model
            if model != original_model:
                handler.engine_client.set_model(original_model, reset_context=False)

        # Render final content with markdown
        if content:
            console.print()  # New line after streaming
        return content

    return asyncio.run(run_coding_task())


class CommandHandler:
    """Handles all slash commands for the application."""

    def __init__(self, client_or_api_key, api_key_or_model: str = None, current_model_or_base_url: str = None, base_url_or_provider: str = None, provider_or_none: str = None):
        """Initialize CommandHandler.

        Supports both old and new signatures for backward compatibility.

        New signature:
            CommandHandler(api_key, current_model, base_url=None, provider=None)

        Legacy signature (deprecated):
            CommandHandler(client, api_key, current_model, base_url, provider)
            The client parameter is ignored - all operations use EngineClient.
        """
        # Detect signature based on first argument type
        # If first arg is a string, it's the new signature (api_key first)
        # If first arg is not a string, it's the old signature (client first)
        if isinstance(client_or_api_key, str):
            # New signature: (api_key, current_model, base_url, provider)
            self.api_key = client_or_api_key
            initial_model = api_key_or_model
            base_url = current_model_or_base_url
            provider = base_url_or_provider
        else:
            # Legacy signature: (client, api_key, current_model, base_url, provider)
            # client is ignored
            warnings.warn(
                "Passing client object to CommandHandler is deprecated. "
                "Use CommandHandler(api_key, model, base_url, provider) instead. "
                "The client parameter is ignored. Will be removed in v2.0.0.",
                DeprecationWarning,
                stacklevel=2
            )
            self.api_key = api_key_or_model
            initial_model = current_model_or_base_url
            base_url = base_url_or_provider
            provider = provider_or_none

        actual_provider = provider or get_default_provider()
        self.base_url = base_url or get_base_url(actual_provider)

        # EngineClient is REQUIRED for all operations
        # Create engine client with consent callbacks
        self.engine_client = EngineClient(
            consent_callback=tui_consent_handler,
            shell_consent_callback=tui_shell_consent_handler
        )
        self.engine_client.set_provider(actual_provider)
        self.engine_client.set_model(initial_model, reset_context=False)
        # Set working directory for context injection
        self.engine_client.set_working_dir(os.getcwd())

        # Sync initial state to AppState
        self.engine_client.state.set("auto_route", True)

        # tools_available is always True (engine has builtin tools)
        self.tools_available = True

        # TUI theme support - load from config
        try:
            config_theme = get_tui_theme()
            self.current_theme_name = config_theme
            self.theme = get_theme(config_theme)
        except ValueError:
            # Fallback to default if config theme is invalid
            self.current_theme_name = DEFAULT_THEME
            self.theme = get_theme(DEFAULT_THEME)

        # Emoji mode - convert emojis to text symbols for panel alignment
        # True = show original emojis (may cause misalignment in some terminals)
        # False = convert emojis to text symbols (guaranteed alignment)
        self.emoji_mode = False  # Default: text symbols for reliable alignment

        # Files staged by /attach for the next chat turn (v1.17.4, Phase 1).
        # Populated by commands/attach.py, consumed and cleared by the Rich
        # TUI send loop in rich/main.py.
        self.pending_files = []

        # Initialize logger for agent mode event handling
        self.logger = get_logger("tui")

    # ========================================================================
    # Public Interface (used by RichCommandContext adapter)
    # Properties delegate to engine_client.state (AppState) where possible.
    # ========================================================================

    @property
    def provider(self) -> str:
        """Current provider name — reads from AppState."""
        return self.engine_client.state.get("provider")

    @provider.setter
    def provider(self, value: str) -> None:
        """Write-through to AppState (for backward compat with direct assignment)."""
        self.engine_client.state.set("provider", value)

    @property
    def current_model(self) -> str:
        """Current model ID — reads from AppState."""
        return self.engine_client.state.get("model")

    @current_model.setter
    def current_model(self, value: str) -> None:
        """Write-through to AppState (for backward compat with direct assignment)."""
        self.engine_client.state.set("model", value)

    @property
    def tools_verbose(self) -> bool:
        """Tool output verbosity — reads from AppState."""
        return self.engine_client.state.get("tools_verbose")

    @tools_verbose.setter
    def tools_verbose(self, value: bool) -> None:
        """Write-through to AppState."""
        self.engine_client.state.set("tools_verbose", value)

    @property
    def auto_route(self) -> bool:
        """Auto-routing for coding tasks — reads from AppState."""
        return self.engine_client.state.get("auto_route")

    @auto_route.setter
    def auto_route(self, value: bool) -> None:
        """Write-through to AppState."""
        self.engine_client.state.set("auto_route", value)

    @property
    def session(self):
        """Access to current session."""
        return self.engine_client.session

    @property
    def working_dir(self) -> str:
        """Current working directory."""
        return self.engine_client.state.get("working_dir") or ""

    @property
    def tools_enabled(self) -> bool:
        """Check if tools are enabled."""
        return self.engine_client.state.get("tools_enabled")

    @property
    def autoroute_enabled(self) -> bool:
        """Check if auto-routing is enabled."""
        return self.engine_client.state.get("auto_route")

    def set_provider(self, provider: str) -> None:
        """Set provider — delegates to engine (which syncs AppState)."""
        self.engine_client.set_provider(provider)

    def set_model(self, model: str) -> None:
        """Set model — delegates to engine (which syncs AppState)."""
        self.engine_client.set_model(model)

    # CommandContext protocol methods (used by __getattr__ proxy in context.py)
    def get_provider(self) -> str:
        return self.provider

    def get_model(self) -> str:
        return self.current_model

    def get_auto_route(self) -> bool:
        return self.auto_route

    def set_auto_route(self, enabled: bool) -> None:
        self.auto_route = enabled

    def get_tools_available(self) -> bool:
        return self.tools_available

    def get_tools_verbose(self) -> bool:
        return self.tools_verbose

    def set_tools_verbose(self, verbose: bool) -> None:
        self.tools_verbose = verbose

    def get_config_value(self, key: str, default=None):
        return default

    def set_config_value(self, key: str, value: str) -> None:
        pass

    def handle_quit(self) -> bool:
        """Handle /quit or /exit command. Returns True if should exit."""
        if self.engine_client.session.messages:
            try:
                self.engine_client.session.save()
                console.print(f"[dim]Session saved: {self.engine_client.session.session_name}[/dim]")
            except Exception as e:
                console.print(f"[yellow]Warning: Could not save session: {e}[/yellow]")

        # Save usage to persistent storage for time-based analytics
        try:
            self.engine_client.session.save_usage_to_persistent_storage()
        except Exception:
            # Non-critical - don't fail on usage persistence errors
            pass

        # Mark session clean on graceful exit
        try:
            self.engine_client.session.mark_clean()
        except Exception:
            # Non-critical - don't fail on state file errors
            pass

        console.print("\n[yellow]Goodbye![/yellow]")
        return True

    def _search_files(self, query: str, max_results: int = 10) -> list:
        """Search for files matching query in engine's working directory."""
        # Remove @ prefix if present
        query = query.lstrip('@').strip()

        # Get search root from engine client (respects cd command)
        root = Path(self.engine_client.get_working_dir())

        # Build search patterns
        query_lower = query.lower()

        # If query looks like a path, try exact match first
        if '/' in query or '\\' in query:
            direct_path = root / query
            if direct_path.exists() and direct_path.is_file():
                return [direct_path]

        # Extract filename parts for fuzzy matching
        parts = query_lower.replace('-', ' ').replace('_', ' ').split()

        matches = []
        try:
            # Walk directory tree (skip hidden dirs and common ignore patterns)
            ignore_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox', 'dist', 'build', '.eggs'}

            for path in root.rglob('*'):
                if path.is_file():
                    # Skip files in ignored directories
                    if any(ignored in path.parts for ignored in ignore_dirs):
                        continue

                    # Check if filename matches
                    filename_lower = path.name.lower()
                    path_str_lower = str(path.relative_to(root)).lower()

                    # Exact filename match
                    if query_lower == filename_lower:
                        return [path]  # Exact match, return immediately

                    # Check if all query parts are in the path
                    if all(part in path_str_lower for part in parts):
                        matches.append(path)
                    # Also check partial filename match
                    elif query_lower in filename_lower:
                        matches.append(path)

                    if len(matches) >= max_results * 2:  # Get more for sorting
                        break
        except PermissionError as e:
            logger.debug(f"Permission denied during file search: {e}")

        # Sort by relevance (shorter paths and exact filename matches first)
        def score(p):
            name = p.name.lower()
            # Prefer exact filename matches
            if query_lower == name:
                return (0, len(str(p)))
            if query_lower in name:
                return (1, len(str(p)))
            return (2, len(str(p)))

        matches.sort(key=score)
        return matches[:max_results]

    def process_file_references(self, content: str) -> tuple[str, list[dict]]:
        """
        Process @filename references in a message and return augmented message with file contents.

        Returns:
            tuple: (augmented_message, list of {name, path} dicts for resolved files)
        """
        # Match @filename patterns (word characters, dots, hyphens, slashes)
        ref_pattern = r'@([\w.\-/]+)'
        matches = list(re.finditer(ref_pattern, content))

        if not matches:
            return content, []

        resolved_files = []
        processed_message = content

        for match in matches:
            ref = match.group(1)
            full_match = match.group(0)

            # Try to resolve the file
            files = self._search_files(ref, max_results=1)
            if files:
                file_path = files[0]
                try:
                    file_content = file_path.read_text(encoding="utf-8")
                    filename = file_path.name

                    resolved_files.append({
                        'name': filename,
                        'path': str(file_path),
                        'content': file_content
                    })

                    # Replace @ref with just the filename in the message
                    processed_message = processed_message.replace(full_match, filename, 1)
                except Exception:
                    # File couldn't be read, leave reference as-is
                    pass

        if not resolved_files:
            return content, []

        # Build augmented message with file contents as context
        augmented_message = processed_message
        augmented_message += '\n\n---\n**Referenced Files:**\n'

        for f in resolved_files:
            ext = Path(f['name']).suffix.lstrip('.')
            augmented_message += f"\n**{f['name']}** (`{f['path']}`):\n```{ext}\n{f['content']}\n```\n"

        return augmented_message, [{'name': f['name'], 'path': f['path']} for f in resolved_files]

    def handle_command(self, user_input: str) -> bool | None:
        """
        Handle a slash command.

        Returns:
            - True if should exit the application
            - False/None to continue
        """
        # Lazy by necessity: `rendering/__init__` -> `base` -> this
        # package's __init__ -> here. One call site.
        from ..rendering.rich_renderer import RichRenderer

        command_parts = user_input.split(maxsplit=1)
        command = command_parts[0].lower()
        args = command_parts[1] if len(command_parts) > 1 else ""

        # Strip leading / for factory lookup
        cmd_name = command[1:] if command.startswith("/") else command

        # Special case: quit/exit must return True
        if command in ["/quit", "/exit"]:
            return self.handle_quit()

        # Handle /<command> help pattern - redirect to /help <command>
        # e.g., "/usage help" becomes "/help usage"
        if args.strip().lower() == "help" and cmd_name != "help":
            args = cmd_name
            cmd_name = "help"

        # All commands use CommandFactory + CommandContext protocol
        spec = CommandFactory.get(cmd_name)
        if spec:
            try:
                context = RichCommandContext(self)
                result = spec.handler(context, args)

                if result is not None and isinstance(result, CommandResult):
                    RichRenderer.render(result)
                    # v1.17.4 Phase 1: /attach returns a TextResult with
                    # metadata["attached_paths"] holding any newly-attached
                    # *image* files. Render an inline preview of each so the
                    # user sees confirmation that the image loaded correctly
                    # before sending their prompt. Non-image attachments
                    # don't preview (text files just go into the prompt).
                    attached_paths = (result.metadata or {}).get("attached_paths") if result.metadata else None
                    if attached_paths:
                        self._render_inline_image_previews(attached_paths)

                return False
            except Exception as e:
                console.print(f"[red]Error executing /{cmd_name}: {e}[/red]\n")
                return False

        # Unknown command
        console.print(f"[red]Unknown command: {user_input}[/red]")
        console.print("[yellow]Type /help for available commands[/yellow]\n")
        return False

    def _render_inline_image_previews(self, paths: list) -> None:
        """Show inline image previews for newly-attached files.

        Uses the existing ImageResult renderer helpers which dispatch to the
        iTerm2 or Sixel protocol based on the detected terminal. Terminals
        without image support silently fall through — the /attach result
        text already lists filenames, so the user isn't left guessing.
        """
        try:
            from ..rendering.rich_renderer import (
                _get_terminal_type,
                _render_image_iterm2,
                _render_image_sixel,
            )
        except Exception as exc:
            logger.debug(f"Inline preview unavailable: {exc}")
            return

        terminal = _get_terminal_type()
        for path in paths:
            rendered = False
            if terminal == "windows_terminal":
                rendered = _render_image_sixel(path)
            elif terminal in ("wezterm", "iterm2"):
                rendered = _render_image_iterm2(path)
            if not rendered:
                # Stay silent on unsupported terminals — the text result
                # already named the files.
                return

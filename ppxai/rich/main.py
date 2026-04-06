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

from ..commands.attach import build_multimodal_content, collect_context_attachments
from ..commands.factory import CommandFactory
from ..commands.handler import CommandHandler
from ..config import (
    PROVIDERS,
    get_default_provider,
    get_api_key,
    get_auto_restore_mode,
    get_auto_save_interval,
    get_base_url,
    get_provider_config,
    get_tui_config,
    get_tui_theme,
    initialize,
)
from .ui import console, display_welcome, select_model, select_provider
from .ui_components import format_usage_string, render_status_panel
from ..engine.session import SessionManager
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

    All state reads go through handler properties / AppState.
    Only checkpoint_status and usage_display require engine_client
    method calls (not part of AppState — derived data).
    """
    state = handler.engine_client.state
    provider_config = get_provider_config(handler.provider)
    provider_name = provider_config["name"]

    # All core fields from AppState via handler properties
    tools_enabled = handler.tools_enabled
    agent_mode = state.get("agent_mode")

    # Get model display name (use ID if not found)
    model_display = handler.current_model
    for model_info in provider_config.get("models", {}).values():
        if model_info.get("id") == handler.current_model:
            model_display = model_info.get("name", handler.current_model)
            break

    # Checkpoint status — derived data, not in AppState
    checkpoint_str = None
    if agent_mode:
        checkpoint_status = handler.engine_client.get_checkpoint_status()
        if checkpoint_status.get("enabled"):
            last_checkpoint = checkpoint_status.get("last_checkpoint")
            is_valid = checkpoint_status.get("is_valid", True)
            if last_checkpoint:
                checkpoint_str = "↶!" if not is_valid else "↶"

    # Usage stats — derived data, not in AppState
    usage_str = None
    usage_display = handler.engine_client.session.get_usage_for_display(
        current_provider=handler.provider,
        current_model=handler.current_model
    )
    if usage_display:
        prompt_tokens = usage_display.get("prompt_tokens", 0)
        completion_tokens = usage_display.get("completion_tokens", 0)
        cost = usage_display.get("estimated_cost", 0.0)
        label = usage_display.get("label")
        if prompt_tokens > 0 or completion_tokens > 0:
            usage_str = format_usage_string(prompt_tokens, completion_tokens, cost)
            if label:
                usage_str = f"[{label}] {usage_str}"

    if use_themed:
        theme_name = getattr(handler, 'current_theme_name', None) or get_tui_theme()
        theme = get_theme(theme_name)

        tui_config = get_tui_config()
        show_version = tui_config.get("show_version", True)
        show_cwd = tui_config.get("show_cwd", True)
        show_datetime = tui_config.get("show_datetime", False)

        # Working dir and context from AppState
        working_dir = handler.working_dir if show_cwd else None
        context_percent = state.get("context_percentage")

        # Attachments badge (v1.17.4 Phase 1) — union of two sources:
        #   • `pending_files` on the handler — Rich-client-specific staging
        #     for `/attach`, not yet sent. Kept on the handler because the
        #     staging UX differs per client (slash command here, drag-drop
        #     in web, file picker in VSCode) and doesn't need cross-client
        #     sync.
        #   • `state.context_attachments` on AppState — canonical list of
        #     attachments already committed to session.messages, maintained
        #     by EngineClient._refresh_context_attachments. This is the
        #     shared source of truth every client reads; Textual / Web /
        #     VSCode will render from the same field in later phases.
        staged = list(getattr(handler, "pending_files", None) or [])
        in_context = state.get("context_attachments") or []
        # Dedupe by name; staged entries take precedence because they still
        # carry size / path / kind metadata useful for display.
        attachments_by_name: dict = {}
        for entry in in_context:
            attachments_by_name[entry.get("name", "")] = entry
        for entry in staged:
            attachments_by_name[getattr(entry, "name", "")] = entry
        attachments = [v for k, v in attachments_by_name.items() if k] or None

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
            pending_files=attachments,
        )

    # Fallback: plain text status line
    tools_status = "[green]ON[/green]" if tools_enabled else "[dim]OFF[/dim]"
    parts = [provider_name, model_display, f"Tools: {tools_status}"]
    if agent_mode:
        parts.append("Agent: [green]ON[/green]")
        if checkpoint_str:
            parts.append(f"[cyan]{checkpoint_str}[/cyan]")
    if usage_str:
        parts.append(f"[cyan]{usage_str}[/cyan]")

    status = "[dim][[/dim]" + "[dim] | [/dim]".join(parts) + "[dim]][/dim]"
    return status


class PPXAICompleter(Completer):
    """Custom completer for slash commands and @file references.

    Slash-command completions are computed dynamically from the
    CommandFactory registry (the single source of truth that every command
    module registers into via side-effect imports). This means newly-added
    commands such as `/attach` (Phase 1) and upcoming `/doctor` (Phase 2)
    appear in tab completion automatically — no hand-maintained list to
    drift against reality.

    Subcommand-level completion (e.g. `/tools <enable|disable|list>`) still
    uses hardcoded tables below, because subcommands are encoded in each
    command's `usage` string as free-form text and can't be reliably parsed.
    When we add structured subcommand metadata to `CommandSpec` later, the
    tables below can be retired the same way.
    """

    # Commands the factory doesn't own (special-cased in CommandHandler).
    # Kept as a tiny fallback list so /quit and /exit remain completable.
    _BUILTIN_SPECIAL_COMMANDS = (
        ('/quit', 'Exit the application'),
        ('/exit', 'Exit the application'),
    )

    # Commands that accept path arguments, and what kinds of entries make
    # sense to complete for each. `include_files` and `include_dirs` control
    # which filesystem entries appear in the suggestion list — directories
    # are always traversable on tab, but e.g. `/cd` only makes sense to
    # select a directory at the end. Keys are canonical command names
    # *without* the leading slash; aliases resolve via CommandFactory at
    # lookup time so adding a new alias doesn't require editing this table.
    _PATH_ARG_COMMANDS: dict = {
        # files only (dirs still shown so users can traverse into them)
        "attach":  {"include_files": True,  "include_dirs": True},
        "show":    {"include_files": True,  "include_dirs": True},
        "preview": {"include_files": True,  "include_dirs": True},
        # dirs-only targets
        "cd":      {"include_files": False, "include_dirs": True},
        "tree":    {"include_files": False, "include_dirs": True},
        # dirs + files both legitimate
        "ls":      {"include_files": True,  "include_dirs": True},
    }

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
        # Cached (commands, registry_size) — invalidates when CommandFactory
        # grows (e.g. /reload of user commands) without polling every keystroke.
        self._commands_cache: list[tuple[str, str]] = []
        self._commands_cache_size = -1

    def _get_commands(self) -> list[tuple[str, str]]:
        """Return the full list of completable slash commands.

        Pulls from `CommandFactory._registry` (canonical set of registered
        commands) plus `CommandFactory._aliases` (so `/att` completes the
        same as `/attach`, `/s` as `/save`, etc.), and finally adds the two
        builtin specials `/quit` and `/exit` which bypass the factory.

        Cached until the registry size changes. Reading the size is O(1)
        and avoids rebuilding the list on every keystroke during typing,
        but still picks up dynamically loaded user commands the first time
        the user hits tab after a `/config reload`.
        """
        # Local import avoids a top-of-module cycle: commands.handler imports
        # from this module via the rendering stack, so we defer the factory
        # import into the function body.
        from ..commands.factory import CommandFactory

        current_size = len(CommandFactory._registry) + len(CommandFactory._aliases)
        if current_size == self._commands_cache_size and self._commands_cache:
            return self._commands_cache

        commands: list[tuple[str, str]] = []

        # Canonical commands from the registry (skip hidden ones).
        for name, spec in CommandFactory._registry.items():
            if spec.hidden:
                continue
            commands.append((f"/{name}", spec.description))

        # Aliases — resolve to the canonical spec for the description, with a
        # marker in the meta so the user can see what it points at.
        for alias, canonical in CommandFactory._aliases.items():
            spec = CommandFactory._registry.get(canonical)
            if not spec or spec.hidden:
                continue
            commands.append((f"/{alias}", f"{spec.description} (alias for /{canonical})"))

        # Hardcoded fallbacks for commands that never reach the factory.
        commands.extend(self._BUILTIN_SPECIAL_COMMANDS)

        # Stable alphabetical order — makes the completion menu predictable
        # as new commands land instead of reflecting registration order.
        commands.sort(key=lambda entry: entry[0])

        self._commands_cache = commands
        self._commands_cache_size = current_size
        return commands

    def _get_working_dir(self) -> Path:
        """Get the current working directory from engine client or fallback to os.cwd()."""
        if self._command_handler and hasattr(self._command_handler, 'engine_client'):
            return Path(self._command_handler.engine_client.get_working_dir())
        return Path.cwd()

    def _get_files(self, max_files: int = 100) -> list[tuple[str, str]]:
        """Get files in the current directory for completion."""
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

    def _resolve_path_base(self, partial: str) -> tuple[Path, str]:
        """Split a user-typed partial path into (directory_to_list, leaf_prefix).

        Handles `~/` expansion, absolute paths, and relative paths resolved
        against the engine's current working directory. A trailing separator
        (`src/`) means "list everything in `src/`"; an unterminated partial
        (`src/com`) means "list `src/` filtered by names starting with `com`";
        a bare `.` or `.foo` leaf correctly means "match hidden files"
        rather than being normalized away.

        Uses `os.path` string operations rather than `Path.parent` /
        `Path.name` because pathlib normalizes trailing `"."` / `".."`
        components — e.g. `Path("/tmp") / "." .name == ""` on some
        interpreter versions, which loses the hidden-file filter the user
        explicitly typed.

        Returns the parent directory to iterate over, plus the leaf prefix
        to filter against. If the partial points somewhere that doesn't
        exist or isn't a directory, the caller will see an empty parent
        and yield no completions.
        """
        # Empty input — list working directory contents.
        if not partial:
            return self._get_working_dir(), ""

        # ~ expansion (display stays literal — expanduser only influences
        # where we look on disk, not what we render).
        if partial.startswith("~"):
            expanded = str(Path(partial).expanduser())
        elif os.path.isabs(partial):
            expanded = partial
        else:
            expanded = os.path.join(str(self._get_working_dir()), partial)

        # Trailing separator signals "enter this directory".
        if expanded.endswith(("/", os.sep)):
            return Path(expanded), ""

        # `os.path.split` preserves literal leafs like "." and ".foo"
        # instead of collapsing them via pathlib normalization.
        parent_str, leaf = os.path.split(expanded)
        return Path(parent_str), leaf

    def _complete_path(
        self,
        partial: str,
        include_files: bool,
        include_dirs: bool,
        max_entries: int = 200,
    ):
        """Yield path completions for a typed partial.

        Standard shell-style path completion: list a single directory, filter
        by leaf prefix, append a trailing `/` to directories so pressing tab
        on a directory navigates *into* it rather than selecting it as the
        final answer. Hidden files (dotfiles) are skipped unless the user
        explicitly typed a leading dot — matching common shell behavior.

        Args:
            partial: The path fragment typed by the user (e.g. "src/com").
            include_files: Whether to yield regular files.
            include_dirs: Whether to yield directories. Directories are
                          *always* traversable via tab even when
                          include_files is the primary intent.
            max_entries: Hard cap on yielded completions — huge directories
                         don't hang the completion UI.
        """
        parent, leaf = self._resolve_path_base(partial)
        if not parent.exists() or not parent.is_dir():
            return

        leaf_lower = leaf.lower()
        show_hidden = leaf.startswith(".")

        try:
            # Directories first, then files; alphabetical within each group.
            entries = sorted(
                parent.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except (OSError, PermissionError):
            return

        yielded = 0
        for entry in entries:
            if yielded >= max_entries:
                break
            name = entry.name
            if not show_hidden and name.startswith("."):
                continue
            if leaf_lower and not name.lower().startswith(leaf_lower):
                continue
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir and not include_dirs:
                continue
            if not is_dir and not include_files:
                continue

            # Directories get a trailing slash so tab-completing a directory
            # leaves the cursor in position to keep typing into it (the user
            # can hit tab again to list its contents).
            completion_text = name + ("/" if is_dir else "")
            display_meta = "dir" if is_dir else "file"
            yield Completion(
                completion_text,
                start_position=-len(leaf),
                display=completion_text,
                display_meta=display_meta,
            )
            yielded += 1

    def _last_whitespace_token(self, text: str) -> tuple[int, str]:
        """Return (start_index, token) for the last whitespace-delimited token.

        Used by path-argument completion in multi-arg commands like
        `/attach a.png b.p<tab>` — we want to complete only `b.p`, not the
        whole args string. Returns (0, "") for empty input.
        """
        if not text:
            return 0, ""
        idx = len(text)
        while idx > 0 and not text[idx - 1].isspace():
            idx -= 1
        return idx, text[idx:]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Delegate command names, path arguments, and @file references
        # to the engine's CompletionProvider (v1.17.4 Task #11). This
        # is the same logic that the POST /complete server endpoint
        # uses, so all four clients get identical results. Subcommand
        # tables (tools, theme, usage, etc.) remain here because they're
        # Rich-specific UI chrome not shared with other clients.
        from ..engine.completion import complete as engine_complete

        # @file reference — delegate and return early
        at_pos = text.rfind('@')
        if at_pos >= 0:
            wd = str(self._get_working_dir())
            for item in engine_complete(text, len(text), working_dir=wd):
                yield Completion(
                    item["text"],
                    start_position=item.get("replace_start", 0),
                    display=item.get("display", item["text"]),
                    display_meta=item.get("description", ""),
                )
            return

        # Slash commands
        if text.startswith('/'):
            cmd_text = text.lower()

            # Path-argument completion — delegated to engine
            space_idx = text.find(" ")
            if space_idx > 0:
                typed_cmd = text[1:space_idx]
                spec = CommandFactory.get(typed_cmd)
                canonical = spec.name if spec else typed_cmd
                path_opts = self._PATH_ARG_COMMANDS.get(canonical)
                if path_opts is not None:
                    wd = str(self._get_working_dir())
                    for item in engine_complete(text, len(text), working_dir=wd):
                        yield Completion(
                            item["text"],
                            start_position=item.get("replace_start", 0),
                            display=item.get("display", item["text"]),
                            display_meta=item.get("description", ""),
                        )
                    return

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

            # Handle /model — dynamic model names for current provider
            if cmd_text.startswith('/model '):
                parts = text.split()
                if len(parts) == 2:
                    query = parts[1].lower()
                    for model_id, model_name in self._get_model_names(query):
                        yield Completion(
                            model_id,
                            start_position=-len(parts[1]),
                            display_meta=model_name,
                        )
                return

            # Handle /provider — known provider IDs
            if cmd_text.startswith('/provider '):
                parts = text.split()
                if len(parts) == 2:
                    query = parts[1].lower()
                    for provider_id, provider_name in self._get_provider_names(query):
                        yield Completion(
                            provider_id,
                            start_position=-len(parts[1]),
                            display_meta=provider_name,
                        )
                return

            # Regular command name completion — delegated to engine.
            wd = str(self._get_working_dir())
            for item in engine_complete(text, len(text), working_dir=wd):
                yield Completion(
                    item["text"],
                    start_position=item.get("replace_start", 0),
                    display=item.get("display", item["text"]),
                    display_meta=item.get("description", ""),
                )

    def _get_model_names(self, query: str = '') -> list[tuple[str, str]]:
        """Dynamic model names for the current provider."""
        if not self._command_handler:
            return []
        current_provider = self._command_handler.provider
        provider_config = get_provider_config(current_provider)
        results = []
        for model_key, model_info in provider_config.get('models', {}).items():
            model_id = model_info.get('id', model_key)
            model_name = model_info.get('name', model_id)
            if not query or query in model_id.lower() or query in model_name.lower():
                results.append((model_id, model_name))
        return results

    def _get_provider_names(self, query: str = '') -> list[tuple[str, str]]:
        """All configured provider IDs and display names."""
        results = []
        for provider_id, provider_cfg in PROVIDERS.items():
            provider_name = provider_cfg.get('name', provider_id)
            if not query or query in provider_id.lower() or query in provider_name.lower():
                results.append((provider_id, provider_name))
        return results

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

    restore_session() updates EngineClient and AppState atomically.
    Handler properties (provider, current_model, working_dir) read
    from AppState, so no manual sync is needed.

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

    # AppState is already updated by restore_session() — handler.provider
    # and handler.current_model read from state automatically.

    # Sync OS working directory to match restored session
    working_dir = handler.working_dir
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
                # v1.17.4 Phase 1: if /attach staged any files, build a
                # multimodal content list (text + image_url parts) and pass
                # that instead of the plain string. EngineClient.chat()
                # accepts either format. Pending files are cleared after
                # the chat send completes, whether or not it succeeds —
                # otherwise a failed send leaves orphaned attachments that
                # would be auto-included in the *next* turn.
                pending_files = list(getattr(handler, "pending_files", []) or [])
                if pending_files:
                    # v1.17.4 Phase 2.2: pass live model + provider +
                    # file_store so `build_multimodal_content` can route
                    # each file through `preprocess_file` with the
                    # correct vision routing and persistence context.
                    # Model / provider may have changed since /attach was
                    # run, which is why the routing decision happens here
                    # rather than at attach time.
                    #
                    # Phase 2.7: when a VL sidecar is configured and the
                    # current model is text-only, `preprocess_file` calls
                    # `engine.caption_image` to generate a text caption
                    # instead of dropping the image to a placeholder.
                    # `has_vision_model()` returns False when the sidecar
                    # is disabled or unconfigured, so we pass None in
                    # that case and the placeholder fallback kicks in.
                    vl_captioner = (
                        handler.engine_client.caption_image
                        if handler.engine_client.has_vision_model()
                        else None
                    )
                    chat_payload = build_multimodal_content(
                        user_input,
                        pending_files,
                        model=handler.current_model,
                        provider=handler.provider,
                        file_store=handler.engine_client.file_store,
                        vl_captioner=vl_captioner,
                    )
                    logger.info(
                        f"Sending multimodal message: {len(pending_files)} attachment(s), "
                        f"{len(chat_payload)} content part(s)"
                    )
                else:
                    chat_payload = user_input

                # Use engine with event-based streaming
                # EngineClient handles all context injection (@file, @git, @tree) internally
                async def stream_engine_response():
                    """Stream response from EngineClient using shared TUIEventHandler."""
                    # Create TUI-specific event handler with verbose setting, theme, and emoji mode
                    verbose = handler.tools_verbose  # reads from AppState
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
                    # chat_payload is either the raw user_input (context
                    # injection still runs) or a multimodal content list
                    # when attachments are present.
                    async for event in handler.engine_client.chat(chat_payload, stream=True):
                        should_continue = await event_handler.handle_event(event)
                        if not should_continue:
                            break

                    return event_handler.get_response()

                try:
                    response = asyncio.run(stream_engine_response())
                finally:
                    # Always drop pending attachments after the send attempt,
                    # so the next turn starts clean even on error/interrupt.
                    if pending_files and hasattr(handler, "pending_files"):
                        handler.pending_files.clear()

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

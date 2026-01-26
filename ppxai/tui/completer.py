"""
Autocomplete logic for Textual TUI.

Provides completions for slash commands, @file references, model names,
provider names, and subcommands.
"""

import time
from pathlib import Path
from typing import Optional

from ..commands.factory import CommandFactory
from ..config import PROVIDERS, get_provider_config


class TextualCompleter:
    """Autocomplete handler for Textual TUI."""

    # Directories to ignore when searching for files
    IGNORE_DIRS = {
        '.git', 'node_modules', '__pycache__', '.venv', 'venv',
        '.tox', 'dist', 'build', '.eggs', '.mypy_cache', '.pytest_cache'
    }

    # Context providers (in addition to @file)
    CONTEXT_PROVIDERS = [
        ('@file', 'Include file contents'),
        ('@clipboard', 'Include clipboard contents'),
        ('@url', 'Fetch and include URL contents'),
    ]

    # Subcommands for various commands
    TOOLS_SUBCOMMANDS = [
        ('on', 'Enable AI tools'),
        ('off', 'Disable AI tools'),
        ('enable', 'Enable AI tools'),
        ('disable', 'Disable AI tools'),
        ('list', 'List available tools'),
        ('status', 'Show tools status'),
        ('help', 'Show help for a tool'),
        ('set', 'Configure tool settings'),
        ('config', 'Show tool configuration'),
        ('agent', 'Enable/disable agent mode'),
    ]

    USAGE_SUBCOMMANDS = [
        ('show', 'Show usage statistics'),
        ('session', 'Show session usage'),
        ('provider', 'Show provider usage'),
        ('off', 'Hide usage display'),
        ('reset', 'Reset usage counters'),
    ]

    CHECKPOINT_SUBCOMMANDS = [
        ('status', 'Show checkpoint status'),
        ('list', 'List recent checkpoints'),
        ('backend', 'Set checkpoint backend'),
        ('clear', 'Clear old snapshots'),
        ('info', 'Show checkpoint details'),
        ('undo', 'Revert last checkpoint'),
    ]

    CHECKPOINT_BACKENDS = [
        ('git', 'Use git commits'),
        ('file', 'Use file snapshots'),
        ('auto', 'Auto-detect best backend'),
        ('none', 'Disable checkpoints'),
    ]

    STATUS_SUBCOMMANDS = [
        ('version', 'Toggle version display'),
        ('cwd', 'Toggle working directory display'),
        ('datetime', 'Toggle date/time display'),
    ]

    THEME_SUBCOMMANDS = [
        ('list', 'Show available themes'),
    ]

    def __init__(self, working_dir: Path, engine_client=None):
        """Initialize completer.

        Args:
            working_dir: Current working directory for file completions
            engine_client: Engine client for accessing tools, models, etc.
        """
        self.working_dir = working_dir
        self.engine_client = engine_client
        self._file_cache = {}
        self._cache_time = 0
        self._cache_dir = None

    def get_completions(self, text: str) -> list[tuple[str, str]]:
        """Get completion suggestions for the given text.

        Args:
            text: Text to complete

        Returns:
            List of (completion_text, description) tuples
        """
        # Priority 1: @context providers (anywhere in text)
        at_pos = text.rfind('@')
        if at_pos >= 0:
            return self._complete_context_provider(text, at_pos)

        # Priority 2: Slash commands (at start of line)
        if text.startswith('/'):
            return self._complete_command(text)

        # No completions for regular text
        return []

    def _complete_context_provider(self, text: str, at_pos: int) -> list[tuple[str, str]]:
        """Complete @file, @clipboard, @url references.

        Args:
            text: Full input text
            at_pos: Position of @ symbol

        Returns:
            List of (completion, description) tuples
        """
        query = text[at_pos + 1:].lower()
        completions = []

        # First, show context provider types if query matches
        for provider, desc in self.CONTEXT_PROVIDERS:
            provider_name = provider[1:]  # Remove @ prefix
            if provider_name.startswith(query):
                completions.append((provider, desc))

        # For @file specifically, also show file completions
        if query.startswith('file'):
            # User typed "@file" - show file completions
            file_query = query[4:].lstrip()  # Remove "file" and whitespace
            for filename, filepath in self._get_files():
                if not file_query or file_query in filename.lower() or file_query in filepath.lower():
                    completions.append((f'@file:{filename}', filepath))
        elif not any(query.startswith(p[1:]) for p, _ in self.CONTEXT_PROVIDERS):
            # User typed "@so" - show files directly
            for filename, filepath in self._get_files():
                if not query or query in filename.lower() or query in filepath.lower():
                    completions.append((f'@file:{filename}', filepath))

        return completions[:20]  # Limit to 20 completions

    def _complete_command(self, text: str) -> list[tuple[str, str]]:
        """Complete slash commands and subcommands.

        Args:
            text: Full input text starting with /

        Returns:
            List of (completion, description) tuples
        """
        parts = text.split()
        cmd_text = text.lower()

        # Handle subcommands
        if len(parts) >= 2:
            cmd = parts[0].lower()

            # /tools subcommands
            if cmd == '/tools':
                return self._complete_subcommand(parts[1].lower() if len(parts) == 2 else '', self.TOOLS_SUBCOMMANDS)

            # /usage subcommands
            elif cmd == '/usage':
                return self._complete_subcommand(parts[1].lower() if len(parts) == 2 else '', self.USAGE_SUBCOMMANDS)

            # /checkpoint subcommands
            elif cmd == '/checkpoint':
                if len(parts) == 2:
                    return self._complete_subcommand(parts[1].lower(), self.CHECKPOINT_SUBCOMMANDS)
                elif len(parts) == 3 and parts[1].lower() == 'backend':
                    return self._complete_subcommand(parts[2].lower(), self.CHECKPOINT_BACKENDS)

            # /status subcommands
            elif cmd == '/status':
                return self._complete_subcommand(parts[1].lower() if len(parts) == 2 else '', self.STATUS_SUBCOMMANDS)

            # /theme subcommands
            elif cmd == '/theme':
                return self._complete_theme(parts[1].lower() if len(parts) == 2 else '')

            # /model - show model completions
            elif cmd == '/model':
                return self._complete_model(parts[1].lower() if len(parts) == 2 else '')

            # /provider - show provider completions
            elif cmd == '/provider':
                return self._complete_provider(parts[1].lower() if len(parts) == 2 else '')

            return []

        # Complete slash commands
        query = text[1:].lower()  # Remove / prefix
        completions = []

        # Get all commands from factory
        all_commands = CommandFactory.list_commands()
        for cmd in all_commands:
            cmd_name = f'/{cmd}'
            if cmd.startswith(query):
                # Get command metadata if available
                desc = self._get_command_description(cmd)
                completions.append((cmd_name, desc))

        return sorted(completions)

    def _complete_subcommand(self, query: str, subcommands: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Complete subcommands.

        Args:
            query: Partial subcommand text
            subcommands: List of (subcmd, description) tuples

        Returns:
            Matching completions
        """
        return [(subcmd, desc) for subcmd, desc in subcommands if subcmd.startswith(query)]

    def _complete_model(self, query: str) -> list[tuple[str, str]]:
        """Complete model names for /model command.

        Args:
            query: Partial model name

        Returns:
            List of (model_id, description) tuples
        """
        if not self.engine_client:
            return []

        completions = []
        current_provider = self.engine_client.provider

        # Get models for current provider
        provider_config = get_provider_config(current_provider)
        models = provider_config.get('models', {})

        for model_key, model_info in models.items():
            model_id = model_info.get('id', model_key)
            model_name = model_info.get('name', model_id)

            if query.lower() in model_id.lower() or query.lower() in model_name.lower():
                completions.append((model_id, model_name))

        return completions

    def _complete_provider(self, query: str) -> list[tuple[str, str]]:
        """Complete provider names for /provider command.

        Args:
            query: Partial provider name

        Returns:
            List of (provider_id, name) tuples
        """
        completions = []

        for provider_id, provider_config in PROVIDERS.items():
            provider_name = provider_config.get('name', provider_id)

            if query.lower() in provider_id.lower() or query.lower() in provider_name.lower():
                completions.append((provider_id, provider_name))

        return completions

    def _complete_theme(self, query: str) -> list[tuple[str, str]]:
        """Complete theme names for /theme command.

        Args:
            query: Partial theme name

        Returns:
            List of (theme_name, description) tuples
        """
        # Get available themes from the theme directory
        themes = [
            ('catppuccin-mocha', 'Catppuccin Mocha theme'),
            ('dracula', 'Dracula theme'),
            ('tokyo-night', 'Tokyo Night theme'),
            ('nord', 'Nord theme'),
            ('gruvbox', 'Gruvbox theme'),
            ('solarized-dark', 'Solarized Dark theme'),
            ('solarized-light', 'Solarized Light theme'),
            ('monokai', 'Monokai theme'),
            ('material', 'Material theme'),
            ('textual-dark', 'Textual Dark (default)'),
            ('textual-light', 'Textual Light'),
            ('tron-legacy', 'Tron Legacy (cyan/orange)'),
            ('matrix', 'Matrix (green-on-black)'),
        ]

        # Add theme subcommands
        theme_completions = self._complete_subcommand(query, self.THEME_SUBCOMMANDS)
        if theme_completions:
            return theme_completions

        # Filter themes by query
        return [(name, desc) for name, desc in themes if name.startswith(query)]

    def _get_command_description(self, cmd: str) -> str:
        """Get description for a command.

        Args:
            cmd: Command name (without /)

        Returns:
            Command description
        """
        descriptions = {
            'help': 'Show available commands',
            'model': 'Switch model',
            'provider': 'Switch provider',
            'clear': 'Clear conversation history',
            'save': 'Save session to JSON',
            'export': 'Export last answer to markdown',
            'load': 'Load a saved session',
            'sessions': 'List saved sessions',
            'new': 'Start new session',
            'history': 'Show conversation history',
            'tools': 'Manage AI tools',
            'show': 'Display file contents',
            'cat': 'Display file contents (alias)',
            'usage': 'Show token usage stats',
            'status': 'Show current status',
            'explain': 'Explain code',
            'test': 'Generate tests',
            'review': 'Review code',
            'debug': 'Debug code',
            'optimize': 'Optimize code',
            'agent': 'Run autonomous agent loop',
            'undo': 'Revert last agent task',
            'checkpoint': 'Manage checkpoint settings',
            'theme': 'Switch or list themes',
            'context': 'Manage bootstrap context',
            'edit': 'Edit file in VSCode or Monaco',
            'cd': 'Change working directory',
            'pwd': 'Print working directory',
            'quit': 'Exit the application',
            'exit': 'Exit the application',
        }
        return descriptions.get(cmd, '')

    def _get_files(self, max_files: int = 100) -> list[tuple[str, str]]:
        """Get files in the working directory for completion.

        Args:
            max_files: Maximum number of files to return

        Returns:
            List of (filename, relative_path) tuples, with priority files first
        """
        now = time.time()

        # Cache for 5 seconds
        if (now - self._cache_time < 5 and
            self._file_cache and
            self._cache_dir == self.working_dir):
            return list(self._file_cache.items())[:max_files]

        # Priority files - always include these first
        priority_files = ['AGENTS.md', 'CLAUDE.md', 'README.md', '.env', 'pyproject.toml', 'package.json']
        priority_dict = {}
        regular_files = {}

        try:
            for path in self.working_dir.rglob('*'):
                if len(regular_files) >= max_files * 2:
                    break
                if path.is_file():
                    # Skip files in ignored directories
                    if any(ignored in path.parts for ignored in self.IGNORE_DIRS):
                        continue
                    try:
                        rel_path = str(path.relative_to(self.working_dir))
                        # Prioritize important files
                        if path.name in priority_files:
                            priority_dict[path.name] = rel_path
                        else:
                            regular_files[path.name] = rel_path
                    except ValueError:
                        pass
        except PermissionError:
            pass

        # Combine: priority files first, then regular files
        files = {**priority_dict, **regular_files}

        self._file_cache = files
        self._cache_time = now
        self._cache_dir = self.working_dir
        return list(files.items())[:max_files]

    def update_working_dir(self, working_dir: Path) -> None:
        """Update the working directory for file completions.

        Args:
            working_dir: New working directory
        """
        self.working_dir = working_dir
        # Invalidate cache
        self._file_cache = {}
        self._cache_time = 0
        self._cache_dir = None

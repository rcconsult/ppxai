"""
Autocomplete logic for Textual TUI.

Provides completions for:
- Slash commands (/help, /model, /tools, etc.)
- Subcommands (/tools enable, /checkpoint backend git, etc.)
- File arguments for commands (/show README.md, /edit src/main.py)
- Context providers (@file, @git, @tree, @clipboard, @url)
- Model names (dynamic from current provider)
- Provider names (dynamic from config)
- Theme names
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
        ('@git', 'Include git diff (staged + unstaged)'),
        ('@tree', 'Include project directory structure'),
        ('@clipboard', 'Include clipboard text content'),
        ('@url', 'Fetch and include URL content'),
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
        self._file_cache = []  # List of (filename, rel_path) tuples
        self._cache_time = 0
        self._cache_dir = None

    def get_completions(self, text: str) -> list[tuple[str, str]]:
        """Get completion suggestions for the given text.

        Args:
            text: Text to complete

        Returns:
            List of (completion_text, description) tuples
        """
        # Priority 0: File commands (/show, /edit, /cat) - return plain filenames
        text_lower = text.lower()
        if text_lower.startswith(('/show ', '/edit ', '/cat ')):
            return self._complete_file_argument(text)

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

    def _complete_file_argument(self, text: str) -> list[tuple[str, str]]:
        """Complete file arguments for /show, /edit, /cat commands.

        Returns plain filenames (no @ prefix) for terminal-like UX.

        Args:
            text: Full input text (e.g., "/show REA")

        Returns:
            List of (filename, filepath) tuples
        """
        # Extract the file query after the command
        parts = text.split(None, 1)  # Split on first whitespace
        if len(parts) < 2:
            # Just "/show" with no query - return all files
            query = ""
        else:
            # "/show READ" - extract "READ"
            query = parts[1].strip()

        # Remove @ prefix if user typed it (for backward compatibility)
        query = query.lstrip('@')

        # Check if query is a directory path (contains path separator)
        is_dir_path = '/' in query or '\\' in query

        # Get files matching query
        completions = []
        for filename, filepath in self._get_files():
            if not query or query.lower() in filename.lower() or query.lower() in filepath.lower():
                # For directory paths, return full relative path
                # Example: "/show src/" should complete to "/show src/main.py", not "/show main.py"
                if is_dir_path:
                    completions.append((filepath, filepath))
                else:
                    # For simple queries, just return filename
                    completions.append((filename, filepath))

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

        # If text ends with whitespace, user is asking for next part
        # Example: "/tools " should complete subcommands, not slash commands
        has_trailing_space = text and text[-1].isspace()
        if has_trailing_space and len(parts) >= 1:
            # Add empty string to represent the part being typed
            parts.append('')

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
        all_commands = CommandFactory.list_all()
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
        current_provider = self.engine_client.provider_name  # Use provider_name (string), not provider (object)

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

    def _get_files(self, max_files: int = 100, max_depth: int = 3, max_time_ms: int = 100) -> list[tuple[str, str]]:
        """Get files in the working directory for completion.

        Uses depth-limited search to avoid blocking on large directories.
        v1.15.2: Performance optimization - limit recursion depth and time.

        Args:
            max_files: Maximum number of files to return
            max_depth: Maximum directory depth to search (default 3)
            max_time_ms: Maximum time to spend scanning in milliseconds (default 100)

        Returns:
            List of (filename, relative_path) tuples, with priority files first
        """
        now = time.time()

        # Cache for 5 seconds (cache stores list of (filename, rel_path) tuples)
        if (now - self._cache_time < 5 and
            self._file_cache and
            self._cache_dir == self.working_dir):
            return self._file_cache[:max_files]

        # Priority files - always include these first
        priority_names = {'AGENTS.md', 'CLAUDE.md', 'README.md', '.env', 'pyproject.toml', 'package.json'}
        priority_files = []  # List of (filename, rel_path) tuples
        regular_files = []   # List of (filename, rel_path) tuples
        start_time = time.time()
        timeout = max_time_ms / 1000.0  # Convert to seconds

        def scan_dir(dir_path: Path, depth: int) -> bool:
            """Recursively scan directory with depth limit.

            Returns False if scan should stop (timeout or max files reached).
            """
            if depth > max_depth:
                return True
            if len(regular_files) >= max_files * 2:
                return False
            # Check timeout periodically
            if time.time() - start_time > timeout:
                return False

            try:
                # Use iterdir() instead of rglob() for controlled recursion
                for path in dir_path.iterdir():
                    if len(regular_files) >= max_files * 2:
                        return False

                    # Skip ignored directories
                    if path.name in self.IGNORE_DIRS:
                        continue

                    try:
                        # Check file type - can fail on network paths (WinError 4350)
                        if path.is_file():
                            try:
                                rel_path = str(path.relative_to(self.working_dir))
                                # Prioritize important files
                                if path.name in priority_names:
                                    priority_files.append((path.name, rel_path))
                                else:
                                    regular_files.append((path.name, rel_path))
                            except ValueError:
                                pass
                        elif path.is_dir():
                            # Recurse into subdirectory
                            if not scan_dir(path, depth + 1):
                                return False
                    except OSError:
                        # Network file unavailable (WinError 4350), skip it
                        pass
            except (PermissionError, OSError):
                pass
            return True

        # Start scanning from working directory
        scan_dir(self.working_dir, 0)

        # Combine: priority files first, then regular files (as list, not dict)
        all_files = priority_files + regular_files

        # Cache as list of (filename, rel_path) tuples
        self._file_cache = all_files
        self._cache_time = now
        self._cache_dir = self.working_dir
        return all_files[:max_files]

    def update_working_dir(self, working_dir: Path) -> None:
        """Update the working directory for file completions.

        Args:
            working_dir: New working directory
        """
        # Skip if same directory (avoid unnecessary cache invalidation)
        if self.working_dir == working_dir:
            return
        self.working_dir = working_dir
        # Invalidate cache
        self._file_cache = []
        self._cache_time = 0
        self._cache_dir = None

"""
Autocomplete logic for Textual TUI.

Delegates command-name, path-argument, and @file-reference completion to
engine/completion.py — the same CompletionProvider used by the Rich TUI
(`PPXAICompleter`) and the `POST /complete` server endpoint. All four
clients get identical results for these cases.

Subcommand-level completion (/tools enable, /model <name>, etc.) and the
@git/@tree/@clipboard/@url context-provider shortcuts remain here as
TUI-specific UI chrome that isn't shared with other clients.

`get_completions()` returns (replacement_text, description) tuples where
replacement_text is the *full desired content* of the input box after
applying the completion. InputBox sets text_area.text = replacement_text
directly — no further transformation needed.
"""

from pathlib import Path
from typing import Optional

from ..config import PROVIDERS, get_provider_config
from ..engine.completion import complete as engine_complete


class TextualCompleter:
    """Autocomplete handler for Textual TUI."""

    # Context provider shortcuts — handled by ContextInjector, not in engine
    CONTEXT_PROVIDERS = [
        ('@git',       'Include git diff (staged + unstaged)'),
        ('@tree',      'Include project directory structure'),
        ('@clipboard', 'Include clipboard text content'),
        ('@url',       'Fetch and include URL content'),
    ]

    # Subcommands for /tools
    TOOLS_SUBCOMMANDS = [
        ('on',      'Enable AI tools'),
        ('off',     'Disable AI tools'),
        ('enable',  'Enable AI tools'),
        ('disable', 'Disable AI tools'),
        ('list',    'List available tools'),
        ('status',  'Show tools status'),
        ('help',    'Show help for a tool'),
        ('set',     'Configure tool settings'),
        ('config',  'Show tool configuration'),
        ('agent',   'Enable/disable agent mode'),
    ]

    USAGE_SUBCOMMANDS = [
        ('show',     'Show usage statistics'),
        ('session',  'Show session usage'),
        ('provider', 'Show provider usage'),
        ('off',      'Hide usage display'),
        ('reset',    'Reset usage counters'),
    ]

    CHECKPOINT_SUBCOMMANDS = [
        ('status',  'Show checkpoint status'),
        ('list',    'List recent checkpoints'),
        ('backend', 'Set checkpoint backend'),
        ('clear',   'Clear old snapshots'),
        ('info',    'Show checkpoint details'),
        ('undo',    'Revert last checkpoint'),
    ]

    CHECKPOINT_BACKENDS = [
        ('git',  'Use git commits'),
        ('file', 'Use file snapshots'),
        ('auto', 'Auto-detect best backend'),
        ('none', 'Disable checkpoints'),
    ]

    STATUS_SUBCOMMANDS = [
        ('version',  'Toggle version display'),
        ('cwd',      'Toggle working directory display'),
        ('datetime', 'Toggle date/time display'),
    ]

    THEME_NAMES = [
        ('catppuccin-mocha', 'Catppuccin Mocha'),
        ('dracula',          'Dracula'),
        ('tokyo-night',      'Tokyo Night'),
        ('nord',             'Nord'),
        ('gruvbox',          'Gruvbox'),
        ('solarized-dark',   'Solarized Dark'),
        ('solarized-light',  'Solarized Light'),
        ('monokai',          'Monokai'),
        ('material',         'Material'),
        ('textual-dark',     'Textual Dark (default)'),
        ('textual-light',    'Textual Light'),
        ('tron-legacy',      'Tron Legacy (cyan/orange)'),
        ('matrix',           'Matrix (green-on-black)'),
    ]

    def __init__(self, working_dir: Path, engine_client=None):
        self.working_dir = working_dir
        self.engine_client = engine_client

    def get_completions(self, text: str) -> list[tuple[str, str]]:
        """Return completion candidates for *text*.

        Each item is (replacement_text, description) where replacement_text
        is the full desired input-box content after applying the completion.
        The caller can set text_area.text = replacement_text directly.
        """
        # @file references and context provider shortcuts
        at_pos = text.rfind('@')
        if at_pos >= 0:
            query = text[at_pos + 1:].lower()
            completions: list[tuple[str, str]] = []
            # @git, @tree, @clipboard, @url — not in engine
            for provider, desc in self.CONTEXT_PROVIDERS:
                if provider[1:].startswith(query):
                    completions.append((text[:at_pos] + provider, desc))
            # @file references from engine (uses working_dir for fs scan)
            for item in engine_complete(text, len(text), working_dir=str(self.working_dir)):
                full = text[:len(text) + item["replace_start"]] + item["text"]
                completions.append((full, item.get("description", "")))
            return completions[:20]

        if text.startswith('/'):
            return self._complete_command(text)

        return []

    def _complete_command(self, text: str) -> list[tuple[str, str]]:
        """Return slash command completions (names, subcommands, path args)."""
        parts = text.split()
        has_trailing_space = bool(text) and text[-1].isspace()
        if has_trailing_space:
            parts.append('')

        if len(parts) >= 2:
            cmd = parts[0].lower()
            query = parts[1].lower()

            if cmd == '/tools':
                return [(f"{parts[0]} {s}", d) for s, d in self.TOOLS_SUBCOMMANDS if s.startswith(query)]
            if cmd == '/usage':
                return [(f"{parts[0]} {s}", d) for s, d in self.USAGE_SUBCOMMANDS if s.startswith(query)]
            if cmd == '/checkpoint':
                if len(parts) == 2:
                    return [(f"{parts[0]} {s}", d) for s, d in self.CHECKPOINT_SUBCOMMANDS if s.startswith(query)]
                if len(parts) == 3 and parts[1].lower() == 'backend':
                    return [(f"{parts[0]} backend {s}", d) for s, d in self.CHECKPOINT_BACKENDS if s.startswith(parts[2].lower())]
                return []
            if cmd == '/status':
                return [(f"{parts[0]} {s}", d) for s, d in self.STATUS_SUBCOMMANDS if s.startswith(query)]
            if cmd == '/theme':
                subs = [(f"{parts[0]} {s}", d) for s, d in [('list', 'Show available themes')] if s.startswith(query)]
                themes = [(f"{parts[0]} {n}", d) for n, d in self.THEME_NAMES if n.startswith(query)]
                return subs + themes
            if cmd == '/model':
                return [(f"{parts[0]} {m}", d) for m, d in self._get_model_completions(query)]
            if cmd == '/provider':
                return [(f"{parts[0]} {p}", d) for p, d in self._get_provider_completions(query)]

            # Path argument completion from engine (/attach, /cd, /ls, /show, /tree, /preview)
            items = engine_complete(text, len(text), working_dir=str(self.working_dir))
            return [
                (text[:len(text) + item["replace_start"]] + item["text"], item.get("description", ""))
                for item in items
            ]

        # Command name completion from engine — reads CommandFactory._registry + aliases,
        # matches PPXAICompleter behaviour exactly.
        # Append a trailing space so the completed command is ready for arguments.
        cursor = len(text)
        items = engine_complete(text, cursor, working_dir=str(self.working_dir))
        return [
            (text[:cursor + item["replace_start"]] + item["text"] + " ", item.get("description", ""))
            for item in items
        ]

    def _get_model_completions(self, query: str) -> list[tuple[str, str]]:
        if not self.engine_client:
            return []
        current_provider = self.engine_client.provider_name
        provider_config = get_provider_config(current_provider)
        completions = []
        for model_key, model_info in provider_config.get('models', {}).items():
            model_id = model_info.get('id', model_key)
            model_name = model_info.get('name', model_id)
            if not query or query in model_id.lower() or query in model_name.lower():
                completions.append((model_id, model_name))
        return completions

    def _get_provider_completions(self, query: str) -> list[tuple[str, str]]:
        completions = []
        for provider_id, provider_cfg in PROVIDERS.items():
            provider_name = provider_cfg.get('name', provider_id)
            if not query or query in provider_id.lower() or query in provider_name.lower():
                completions.append((provider_id, provider_name))
        return completions

    def update_working_dir(self, working_dir: Path) -> None:
        """Update the working directory for path completions."""
        self.working_dir = working_dir

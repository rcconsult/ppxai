"""
Command Factory - Central registry for slash commands.

The factory guarantees that all built-in command modules are imported
(and therefore registered) before any read operation on the registry.
This makes command availability deterministic regardless of import path:
``from .factory import CommandFactory`` and ``from . import CommandFactory``
both yield a fully-populated registry.

v1.13.10: Initial implementation (Command Factory pattern)
v1.17.4:  Eager loading — factory owns its preconditions
"""

import importlib
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Built-in command modules that self-register when imported.
# The factory imports these eagerly on first read access so the registry
# is fully populated regardless of which module imported CommandFactory.
_BUILTIN_COMMAND_MODULES = (
    "session",
    "provider",
    "system",
    "coding",
    "utility",
    "agent",
    "tools",
    "display",
    "attach",
    "doctor",
)


@dataclass
class CommandSpec:
    """Specification for a slash command.

    Attributes:
        name: Command name without the slash (e.g., "help", "save")
        description: Short description shown in /help
        handler: Function that handles the command: fn(handler, args: str) -> Any
        category: Category for grouping in help (e.g., "session", "model", "tools")
        aliases: Alternative names for the command
        usage: Usage string shown in help (e.g., "/save [name]")
        hidden: If True, command is not shown in /help
    """
    name: str
    description: str
    handler: Callable
    category: str = "general"
    aliases: List[str] = field(default_factory=list)
    usage: str = ""
    hidden: bool = False


@dataclass
class CompletionCommandInfo:
    """Minimal, completion-oriented view of a registered command.

    A deliberately narrow, stable shape decoupled from `CommandSpec` (it
    carries no handler / no internal storage). This is the public seam the
    completion logic consumes instead of reaching into the factory's
    private `_registry` / `_aliases`, and the seed of the
    `CommandRegistryProtocol` planned in ADR 0007 (first-class
    `CompletionService`).
    """
    name: str            # command or alias name, without the leading slash
    description: str     # canonical command's description
    hidden: bool         # canonical command's hidden flag
    is_alias: bool       # True if `name` is an alias
    canonical: str       # canonical command name (== name when not an alias)


class CommandFactory:
    """Central registry for all commands. Leaf module - no ppxai imports.

    Commands self-register at module import time. The factory provides:
    - Registration of command specs
    - Lookup by name or alias
    - Dispatch to command handlers
    - Listing by category
    - Dynamic reloading of user commands

    Example:
        # In a command module (e.g., session.py)
        from .factory import CommandFactory, CommandSpec

        def handle_save(handler, args: str):
            # Save logic here
            pass

        CommandFactory.register(CommandSpec(
            name="save",
            description="Save current session",
            handler=handle_save,
            category="session",
            aliases=["s"],
            usage="/save [name]"
        ))
    """
    _registry: Dict[str, CommandSpec] = {}
    _aliases: Dict[str, str] = {}  # alias -> canonical name
    _loaded: bool = False

    @classmethod
    def _ensure_loaded(cls) -> None:
        """Import all built-in command modules so the registry is populated.

        Called automatically before any read operation. Idempotent — the
        import cost is paid exactly once per process.
        """
        if cls._loaded:
            return
        cls._loaded = True
        for module_name in _BUILTIN_COMMAND_MODULES:
            try:
                importlib.import_module(f".{module_name}", package="ppxai.commands")
            except Exception as e:
                logger.warning(f"Failed to load command module {module_name}: {e}")

    @classmethod
    def register(cls, spec: CommandSpec) -> None:
        """Register a command specification.

        Args:
            spec: CommandSpec to register

        Raises:
            ValueError: If command name or alias already registered
        """
        if spec.name in cls._registry:
            logger.warning(f"Command '{spec.name}' already registered, overwriting")

        cls._registry[spec.name] = spec

        # Register aliases
        for alias in spec.aliases:
            if alias in cls._aliases or alias in cls._registry:
                logger.warning(f"Alias '{alias}' conflicts with existing command/alias")
            cls._aliases[alias] = spec.name

    @classmethod
    def unregister(cls, name: str) -> bool:
        """Unregister a command by name.

        Args:
            name: Command name to unregister

        Returns:
            True if command was found and removed, False otherwise
        """
        if name not in cls._registry:
            return False

        spec = cls._registry[name]
        # Remove aliases
        for alias in spec.aliases:
            cls._aliases.pop(alias, None)
        # Remove command
        del cls._registry[name]
        return True

    @classmethod
    def get(cls, name: str) -> Optional[CommandSpec]:
        """Get command spec by name or alias.

        Args:
            name: Command name or alias (without leading /)

        Returns:
            CommandSpec if found, None otherwise
        """
        cls._ensure_loaded()
        # Check if it's an alias
        canonical = cls._aliases.get(name, name)
        return cls._registry.get(canonical)

    @classmethod
    def dispatch(cls, name: str, handler, args: str = "") -> Any:
        """Dispatch a command by name.

        Args:
            name: Command name or alias (without leading /)
            handler: CommandHandler instance providing context
            args: Command arguments string

        Returns:
            Result from command handler

        Raises:
            ValueError: If command not found
        """
        spec = cls.get(name)
        if not spec:
            raise ValueError(f"Unknown command: /{name}")
        return spec.handler(handler, args)

    @classmethod
    def call(cls, name: str, handler, args: str = "") -> Any:
        """Call another command (for composition).

        This is an alias for dispatch() but semantically indicates
        command-to-command calls rather than external dispatch.

        Args:
            name: Command name (without /)
            handler: CommandHandler instance
            args: Arguments to pass

        Returns:
            Result from the called command

        Raises:
            ValueError: If command not found
        """
        return cls.dispatch(name, handler, args)

    @classmethod
    def list_all(cls) -> List[str]:
        """List all registered command names.

        Returns:
            List of command names (not aliases)
        """
        cls._ensure_loaded()
        return list(cls._registry.keys())

    @classmethod
    def list_by_category(cls, category: str) -> List[CommandSpec]:
        """List commands in a category.

        Args:
            category: Category name

        Returns:
            List of CommandSpec in the category
        """
        cls._ensure_loaded()
        return [spec for spec in cls._registry.values()
                if spec.category == category and not spec.hidden]

    @classmethod
    def iter_completion_specs(cls) -> List[CompletionCommandInfo]:
        """Public, completion-oriented snapshot of the registry.

        Returns one entry per canonical command followed by one per alias
        (alias entries carry the canonical command's description + hidden
        flag). This replaces direct reads of the private `_registry` /
        `_aliases` from `engine.completion` — see ADR 0007. Order is
        canonicals-then-aliases; callers that need a stable display order
        should sort by their own key (the completion provider sorts by
        candidate text).
        """
        cls._ensure_loaded()
        infos: List[CompletionCommandInfo] = []
        for name, spec in cls._registry.items():
            infos.append(CompletionCommandInfo(
                name=name,
                description=spec.description,
                hidden=spec.hidden,
                is_alias=False,
                canonical=name,
            ))
        for alias, canonical in cls._aliases.items():
            spec = cls._registry.get(canonical)
            if spec is None:
                continue
            infos.append(CompletionCommandInfo(
                name=alias,
                description=spec.description,
                hidden=spec.hidden,
                is_alias=True,
                canonical=canonical,
            ))
        return infos

    @classmethod
    def get_categories(cls) -> List[str]:
        """Get all unique category names.

        Returns:
            Sorted list of category names
        """
        cls._ensure_loaded()
        categories = set(spec.category for spec in cls._registry.values()
                        if not spec.hidden)
        return sorted(categories)

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations (for testing)."""
        cls._registry.clear()
        cls._aliases.clear()
        cls._loaded = False

    @classmethod
    def generate_help(cls, client: Optional[str] = None, markdown: bool = False) -> str:
        """Generate help text from registered commands.

        Dynamically builds help output grouped by category.

        Args:
            client: Optional client filter ("rich", "textual", or None for all)
            markdown: If True, output GitHub-flavored markdown (web,
                VSCode). If False, Rich console markup (TUI).
                Same content, two formatters.

        Returns:
            Formatted help text
        """
        cls._ensure_loaded()
        if markdown:
            lines = ["**Available Commands:**\n"]
        else:
            lines = ["[bold]Available Commands:[/bold]\n"]

        # Group by category
        for category in cls.get_categories():
            commands = cls.list_by_category(category)
            if not commands:
                continue

            # Category header
            if markdown:
                lines.append(f"**{category.title()}:**")
            else:
                lines.append(f"[cyan]{category.title()}:[/cyan]")

            # Commands in category, sorted by name
            for cmd in sorted(commands, key=lambda c: c.name):
                alias_str = ""
                if cmd.aliases:
                    if markdown:
                        alias_str = f" *(/{', /'.join(cmd.aliases)})*"
                    else:
                        alias_str = f" [dim](/{', /'.join(cmd.aliases)})[/dim]"
                if markdown:
                    lines.append(f"- `/{cmd.name}`{alias_str} — {cmd.description}")
                else:
                    lines.append(f"  /{cmd.name}{alias_str} - {cmd.description}")

            lines.append("")  # Blank line between categories

        if markdown:
            lines.append("*Use `/help <command>` for detailed help on a specific command.*")
        else:
            lines.append("[dim]Use /help <command> for detailed help on a specific command.[/dim]")
        return "\n".join(lines)

    @classmethod
    def get_command_help(cls, name: str, markdown: bool = False) -> Optional[str]:
        """Get detailed help for a specific command.

        Args:
            name: Command name or alias (without leading /)
            markdown: If True, output GitHub-flavored markdown.
                If False, Rich console markup.

        Returns:
            Formatted help text, or None if command not found
        """
        cls._ensure_loaded()
        spec = cls.get(name)
        if not spec:
            return None

        lines = []
        if markdown:
            lines.append(f"### `/{spec.name}` — {spec.description}")
            lines.append("")
            usage = spec.usage if spec.usage else f"/{spec.name}"
            lines.append(f"**Usage:** `{usage}`")
            if spec.aliases:
                aliases = ", ".join(f"`/{a}`" for a in spec.aliases)
                lines.append(f"**Aliases:** {aliases}")
            lines.append(f"**Category:** {spec.category}")
        else:
            lines.append(f"[bold]/{spec.name}[/bold] - {spec.description}")
            lines.append("")
            if spec.usage:
                lines.append(f"[cyan]Usage:[/cyan] {spec.usage}")
            else:
                lines.append(f"[cyan]Usage:[/cyan] /{spec.name}")
            if spec.aliases:
                aliases = ", ".join(f"/{a}" for a in spec.aliases)
                lines.append(f"[cyan]Aliases:[/cyan] {aliases}")
            lines.append(f"[cyan]Category:[/cyan] {spec.category}")

        return "\n".join(lines)

    @classmethod
    def reload_user_commands(cls) -> int:
        """Reload user commands from ~/.ppxai/commands/.

        Unregisters existing user commands (category="custom") and
        re-imports all .py files from the user commands directory.

        Returns:
            Number of modules loaded
        """
        # Unregister existing user commands
        user_cmds = [name for name, spec in cls._registry.items()
                     if spec.category == "custom"]
        for name in user_cmds:
            cls.unregister(name)

        # Re-scan and import user commands
        user_commands_dir = Path.home() / ".ppxai" / "commands"
        if not user_commands_dir.exists():
            return 0

        count = 0
        sys.path.insert(0, str(user_commands_dir))
        try:
            for py_file in user_commands_dir.glob("*.py"):
                if not py_file.name.startswith("_"):
                    module_name = py_file.stem
                    try:
                        # Force reimport if already loaded
                        if module_name in sys.modules:
                            importlib.reload(sys.modules[module_name])
                        else:
                            importlib.import_module(module_name)
                        count += 1
                    except Exception as e:
                        logger.warning(f"Failed to load user command {py_file.name}: {e}")
        finally:
            sys.path.pop(0)

        return count

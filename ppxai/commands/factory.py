"""
Command Factory - Central registry for slash commands.

This is a LEAF MODULE - no ppxai imports allowed.
Commands self-register at import time via ToolFactory.register().

v1.13.10: Initial implementation (Command Factory pattern)
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


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
        return list(cls._registry.keys())

    @classmethod
    def list_by_category(cls, category: str) -> List[CommandSpec]:
        """List commands in a category.

        Args:
            category: Category name

        Returns:
            List of CommandSpec in the category
        """
        return [spec for spec in cls._registry.values()
                if spec.category == category and not spec.hidden]

    @classmethod
    def get_categories(cls) -> List[str]:
        """Get all unique category names.

        Returns:
            Sorted list of category names
        """
        categories = set(spec.category for spec in cls._registry.values()
                        if not spec.hidden)
        return sorted(categories)

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations (for testing)."""
        cls._registry.clear()
        cls._aliases.clear()

    @classmethod
    def reload_user_commands(cls) -> int:
        """Reload user commands from ~/.ppxai/commands/.

        Unregisters existing user commands (category="custom") and
        re-imports all .py files from the user commands directory.

        Returns:
            Number of modules loaded
        """
        import sys
        import importlib
        from pathlib import Path

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

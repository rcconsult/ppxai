# Design: Command Factory Pattern

**Status:** Proposed
**Created:** 2026-01-16
**Related:**
- [TECHNICAL_DEBT.md](TECHNICAL_DEBT.md) Item #2 (Monolithic Files)
- [DESIGN-TOOL-FACTORY.md](DESIGN-TOOL-FACTORY.md) (Aligned pattern)

---

## Problem Statement

`ppxai/commands.py` is 2,404 lines with 32 `handle_*` methods. The current dispatch uses a massive if/elif chain:

```python
def handle_command(self, user_input: str) -> Optional[bool]:
    if user_input.startswith('/quit'):
        return self.handle_quit()
    elif user_input.startswith('/save'):
        return self.handle_save(args)
    elif user_input.startswith('/model'):
        return self.handle_model(args)
    # ... 30+ more elif branches
```

Issues:
- **Monolithic file** - 2,400+ lines, hard to navigate
- **Static dispatch** - Adding commands requires editing the main file
- **No user commands** - No way to add custom commands at runtime
- **Inconsistent with Tool Factory** - Different patterns for similar concepts

---

## Proposed Solution: Command Factory with Self-Registration

### Architecture

```
                    ┌──────────────────┐
                    │  CommandFactory  │  (leaf module - no ppxai imports)
                    │  - registry      │
                    │  - get(name)     │
                    │  - dispatch(...) │
                    └────────┬─────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   session.py           model.py             agent.py
   (self-registers)    (self-registers)    (self-registers)
```

### Key Components

#### 1. CommandFactory (new leaf module)

```python
# ppxai/commands/factory.py
from typing import Callable, Dict, Any, Optional, List
from dataclasses import dataclass, field

@dataclass
class CommandSpec:
    """Command specification - metadata + handler."""
    name: str                              # Primary name (e.g., "save")
    description: str                       # Help text
    handler: Callable                      # Function to call
    category: str = "general"              # For grouping in /help
    aliases: List[str] = field(default_factory=list)  # e.g., ["s"] for /s
    usage: str = ""                        # Usage hint (e.g., "/save [name]")
    hidden: bool = False                   # Hide from /help


class CommandFactory:
    """Central registry for all commands. Leaf module - no ppxai imports."""
    _registry: Dict[str, CommandSpec] = {}
    _aliases: Dict[str, str] = {}  # alias -> primary name

    @classmethod
    def register(cls, spec: CommandSpec):
        """Register a command specification."""
        cls._registry[spec.name] = spec
        for alias in spec.aliases:
            cls._aliases[alias] = spec.name

    @classmethod
    def get(cls, name: str) -> Optional[CommandSpec]:
        """Get command spec by name or alias."""
        # Check aliases first
        if name in cls._aliases:
            name = cls._aliases[name]
        return cls._registry.get(name)

    @classmethod
    def list_commands(cls) -> List[str]:
        """List all registered command names."""
        return list(cls._registry.keys())

    @classmethod
    def list_by_category(cls, category: str) -> List[CommandSpec]:
        """List commands in a category."""
        return [c for c in cls._registry.values()
                if c.category == category and not c.hidden]

    @classmethod
    def categories(cls) -> List[str]:
        """List all categories."""
        return list(set(c.category for c in cls._registry.values()))

    @classmethod
    def dispatch(cls, name: str, handler: Any, args: str) -> Optional[bool]:
        """Dispatch command to registered handler.

        Args:
            name: Command name (without leading /)
            handler: CommandHandler instance (provides context)
            args: Arguments string

        Returns:
            Handler return value, or None if command not found
        """
        spec = cls.get(name)
        if not spec:
            return None
        return spec.handler(handler, args)

    @classmethod
    def generate_help(cls) -> str:
        """Generate help text from registered commands."""
        lines = ["Available commands:\n"]
        for category in sorted(cls.categories()):
            commands = cls.list_by_category(category)
            if commands:
                lines.append(f"\n[bold]{category.title()}[/bold]")
                for cmd in sorted(commands, key=lambda c: c.name):
                    alias_str = f" (/{', /'.join(cmd.aliases)})" if cmd.aliases else ""
                    lines.append(f"  /{cmd.name}{alias_str} - {cmd.description}")
        return "\n".join(lines)

    @classmethod
    def clear(cls):
        """Clear registry (for testing)."""
        cls._registry.clear()
        cls._aliases.clear()
```

#### 2. Command Self-Registration

```python
# ppxai/commands/session.py
"""Session management commands."""

from rich.console import Console
from .factory import CommandFactory, CommandSpec
from ..ui import display_sessions, display_usage, display_global_usage

console = Console()


def handle_save(handler, args: str):
    """Handle /save command."""
    try:
        session_name = handler.engine_client.session.save()
        filepath = handler.engine_client.session.sessions_dir / f"{session_name}.json"
        console.print(f"\n[green]Session saved to:[/green] {filepath}\n")
    except Exception as e:
        console.print(f"[red]Error saving session: {e}[/red]\n")


def handle_load(handler, args: str):
    """Handle /load command."""
    if not args.strip():
        console.print("[red]Please specify a session name: /load <session_name>[/red]\n")
        return
    # ... rest of implementation


def handle_export(handler, args: str):
    """Handle /export command."""
    # ... implementation


def handle_sessions(handler, args: str):
    """Handle /sessions command."""
    sessions = handler.engine_client.session.list_sessions()
    display_sessions(sessions)


def handle_usage(handler, args: str):
    """Handle /usage command."""
    # ... implementation


# Self-registration at module import time
CommandFactory.register(CommandSpec(
    name="save",
    aliases=["s"],
    description="Save current session",
    handler=handle_save,
    category="session",
    usage="/save [name]"
))

CommandFactory.register(CommandSpec(
    name="load",
    aliases=["l"],
    description="Load a saved session",
    handler=handle_load,
    category="session",
    usage="/load <session_name>"
))

CommandFactory.register(CommandSpec(
    name="export",
    aliases=["e"],
    description="Export last response to markdown",
    handler=handle_export,
    category="session",
    usage="/export [filename]"
))

CommandFactory.register(CommandSpec(
    name="sessions",
    aliases=[],
    description="List saved sessions",
    handler=handle_sessions,
    category="session"
))

CommandFactory.register(CommandSpec(
    name="usage",
    aliases=["u"],
    description="Show token usage statistics",
    handler=handle_usage,
    category="session",
    usage="/usage [session|global|reset]"
))
```

#### 3. Dynamic Command Discovery

```python
# ppxai/commands/handler.py
"""Main CommandHandler class with factory-based dispatch."""

import os
import importlib
import pkgutil
from typing import Optional

from ..config import get_default_provider, get_base_url, get_tui_theme
from ..engine import EngineClient
from ..themes import get_theme, DEFAULT_THEME
from ..common.logger import get_logger

from .factory import CommandFactory
from .consent import tui_consent_handler, tui_shell_consent_handler


class CommandHandler:
    """Handles all slash commands for the application."""

    def __init__(self, client_or_api_key, ...):
        # Initialize handler state
        self.api_key = ...
        self.current_model = ...
        self.provider = ...

        # Create engine client
        self.engine_client = EngineClient(
            consent_callback=tui_consent_handler,
            shell_consent_callback=tui_shell_consent_handler
        )
        self.engine_client.set_provider(self.provider)
        self.engine_client.set_model(self.current_model)

        # Discover and register all commands
        self._discover_commands()

    def _discover_commands(self):
        """Discover and import all command modules."""
        from . import session, model, coding, file, agent, ui
        # Importing triggers self-registration via CommandFactory.register()

        # Also scan user commands directory
        self._load_user_commands()

    def _load_user_commands(self):
        """Load user-defined commands from ~/.ppxai/commands/"""
        import sys
        from pathlib import Path

        user_commands_dir = Path.home() / ".ppxai" / "commands"
        if not user_commands_dir.exists():
            return

        # Add to path and import
        sys.path.insert(0, str(user_commands_dir))
        for py_file in user_commands_dir.glob("*.py"):
            if not py_file.name.startswith("_"):
                try:
                    importlib.import_module(py_file.stem)
                except Exception as e:
                    self.logger.warning(f"Failed to load user command {py_file}: {e}")
        sys.path.pop(0)

    def handle_command(self, user_input: str) -> Optional[bool]:
        """Dispatch command via factory."""
        if not user_input.startswith('/'):
            return None

        # Parse command and args
        parts = user_input[1:].split(maxsplit=1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Dispatch via factory
        result = CommandFactory.dispatch(cmd_name, self, args)

        if result is None:
            # Unknown command
            from rich.console import Console
            Console().print(f"[red]Unknown command: /{cmd_name}[/red]")
            Console().print("Type /help for available commands.")

        return result

    def handle_help(self, args: str = ""):
        """Handle /help command - auto-generated from registry."""
        from rich.console import Console
        Console().print(CommandFactory.generate_help())
```

#### 4. Package __init__.py

```python
# ppxai/commands/__init__.py
"""Command handlers for the ppxai application."""

from .handler import CommandHandler
from .factory import CommandFactory, CommandSpec

# For backward compatibility with send_coding_task
from .coding import send_coding_task

__all__ = [
    "CommandHandler",
    "CommandFactory",
    "CommandSpec",
    "send_coding_task"
]
```

---

## Package Structure

```
ppxai/commands/
├── __init__.py          # Re-exports CommandHandler, CommandFactory
├── factory.py           # CommandFactory + CommandSpec (leaf module)
├── handler.py           # CommandHandler class
├── consent.py           # Consent handlers (~150 lines)
├── session.py           # Session commands: save, load, export, sessions, usage
├── model.py             # Model commands: model, provider, tools, autoroute
├── coding.py            # Coding commands: generate, test, docs, implement, debug, explain, convert
├── file.py              # File commands: show, cd, pwd, context, config
├── agent.py             # Agent commands: agent, undo, checkpoint
└── ui.py                # UI commands: quit, clear, help, theme, spec, debug_log, status
```

---

## DAG Import Structure

```
config.py, themes.py, prompts.py, utils.py  (leaf modules)
           ↓
engine/types.py, engine/client.py
           ↓
commands/factory.py                          (leaf - no ppxai.commands imports)
           ↓
commands/consent.py                          (imports factory only)
           ↓
commands/session.py, model.py, coding.py...  (import factory, consent)
           ↓
commands/handler.py                          (imports all command modules)
           ↓
commands/__init__.py                         (re-exports)
```

**Key Rule:** Command modules do NOT import each other. They only import:
- Standard library
- Third-party (rich, prompt_toolkit)
- Leaf modules (config, themes, prompts, utils)
- Engine modules (EngineClient, types)
- `factory.py` (for CommandFactory, CommandSpec)
- `consent.py` (for consent handlers)

---

## Benefits

| Aspect | Current | Factory Pattern |
|--------|---------|-----------------|
| File size | 2,404 lines | ~300 lines max per file |
| Dispatch | 30+ elif chain | Single registry lookup |
| Adding commands | Edit main file | Drop file in directory |
| User commands | Not possible | `~/.ppxai/commands/` |
| /help generation | Manual maintenance | Auto-generated from registry |
| Aliases | Hardcoded | Declarative in CommandSpec |
| Consistency | Different from tools | Same pattern as ToolFactory |

---

## Alignment with Tool Factory

| Aspect | CommandFactory | ToolFactory |
|--------|----------------|-------------|
| Spec class | `CommandSpec` | `ToolSpec` |
| Registry | `_registry: Dict[str, CommandSpec]` | `_registry: Dict[str, ToolSpec]` |
| Registration | `CommandFactory.register(spec)` | `ToolFactory.register(spec)` |
| Lookup | `CommandFactory.get(name)` | `ToolFactory.get(name)` |
| Dispatch | `CommandFactory.dispatch(name, handler, args)` | `ToolFactory.call(name, args, engine)` |
| Categories | `category: str` | `category: str` |
| User extensions | `~/.ppxai/commands/` | `~/.ppxai/tools/` |

**Same pattern, same learning curve, consistent architecture.**

---

## Performance Analysis

| Operation | Latency | Notes |
|-----------|---------|-------|
| Command discovery (one-time) | ~5-20ms | Import all command modules at startup |
| Factory lookup | ~1μs | Dictionary lookup |
| Handler call | ~100ns | Standard Python function call |
| Actual command execution | 1ms - 10s | Depends on command (save, agent, etc.) |

**Conclusion:** Factory overhead is negligible. Command execution time dominates.

---

## Migration Path

### Phase 1: Create Factory (Non-Breaking)
1. Create `ppxai/commands/` directory
2. Create `factory.py` with CommandFactory and CommandSpec
3. Original `commands.py` unchanged

### Phase 2: Extract Consent Handlers
1. Move `ConsentValidator`, `tui_consent_handler`, `tui_shell_consent_handler` to `consent.py`
2. Import in original `commands.py`
3. Test

### Phase 3: Migrate Commands by Category
1. Start with smallest category (coding - 7 commands, ~100 lines)
2. Create `coding.py` with self-registering commands
3. Update `handle_command()` to check factory first, fallback to old dispatch
4. Test, repeat for each category

### Phase 4: Create handler.py
1. Move `CommandHandler.__init__` to `handler.py`
2. Replace old dispatch with `CommandFactory.dispatch()`
3. Add `_discover_commands()` and `_load_user_commands()`
4. Create `__init__.py` with re-exports

### Phase 5: Cleanup
1. Delete old `commands.py`
2. Update `ppxai/__init__.py` lazy loading path

### Phase 6: Documentation
1. Finalize [CUSTOM_COMMAND_DEVELOPMENT_GUIDE.md](CUSTOM_COMMAND_DEVELOPMENT_GUIDE.md)
2. Add examples to `~/.ppxai/commands/examples/`
3. Update README with custom command section

---

## User-Defined Commands

### Creating a Custom Command

```python
# ~/.ppxai/commands/my_commands.py
from ppxai.commands import CommandFactory, CommandSpec

def handle_hello(handler, args: str):
    """Handle /hello command."""
    from rich.console import Console
    Console().print(f"[green]Hello, {args or 'World'}![/green]")

CommandFactory.register(CommandSpec(
    name="hello",
    description="Say hello",
    handler=handle_hello,
    category="custom",
    usage="/hello [name]"
))
```

After creating this file and running `/reload`, the command is available:
```
> /reload
User commands reloaded.

> /hello Claude
Hello, Claude!

> /help
...
Custom
  /hello - Say hello
```

### Dynamic Reloading

User commands can be reloaded at runtime without restarting:

```python
# In CommandFactory
@classmethod
def reload_user_commands(cls):
    """Reload user commands from ~/.ppxai/commands/"""
    import sys
    import importlib
    from pathlib import Path

    # Unregister existing user commands
    user_cmds = [name for name, spec in cls._registry.items()
                 if spec.category == "custom"]
    for name in user_cmds:
        del cls._registry[name]
        # Also remove aliases
        cls._aliases = {k: v for k, v in cls._aliases.items() if v != name}

    # Re-scan and import user commands
    user_commands_dir = Path.home() / ".ppxai" / "commands"
    if not user_commands_dir.exists():
        return 0

    count = 0
    sys.path.insert(0, str(user_commands_dir))
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
            except Exception:
                pass
    sys.path.pop(0)
    return count
```

### /reload Command

```python
# Built-in reload command
def handle_reload(handler, args: str):
    """Handle /reload command."""
    from rich.console import Console
    from ..config import reload_config

    console = Console()

    # Reload config
    reload_config()
    console.print("[dim]Configuration reloaded.[/dim]")

    # Reload user commands
    count = CommandFactory.reload_user_commands()
    console.print(f"[green]User commands reloaded ({count} modules).[/green]")

CommandFactory.register(CommandSpec(
    name="reload",
    description="Reload config and user commands",
    handler=handle_reload,
    category="system",
    hidden=False
))
```

### Dynamic Loading Options

| Approach | Implementation | UX |
|----------|---------------|-----|
| **`/reload` command** | ✅ Included | User explicitly reloads after changes |
| **File watcher** | Future | Auto-detect changes (requires watchdog) |
| **Hot module reload** | Future | Reload individual modules on change |

The `/reload` approach is simple, explicit, and covers most use cases.

---

## Command Composition

Commands can call other commands via the factory, enabling reuse of well-tested built-in commands.

### The `call()` Method

```python
class CommandFactory:
    @classmethod
    def call(cls, name: str, handler, args: str = "") -> Any:
        """Call another command (for composition).

        Args:
            name: Command name (without /)
            handler: CommandHandler instance
            args: Arguments to pass

        Returns:
            Result from the called command

        Raises:
            ValueError: If command not found
        """
        spec = cls.get(name)
        if not spec:
            raise ValueError(f"Unknown command: {name}")
        return spec.handler(handler, args)
```

### Example: Workflow Command

```python
# ~/.ppxai/commands/workflows.py
from ppxai.commands import CommandFactory, CommandSpec
from rich.console import Console

console = Console()

def handle_backup(handler, args: str):
    """Full backup: save session, export response, show status."""
    console.print("[bold]Running backup workflow...[/bold]\n")

    # Reuse built-in commands
    CommandFactory.call("save", handler, "")
    CommandFactory.call("export", handler, "backup.md")
    CommandFactory.call("status", handler, "")

    console.print("\n[green]Backup complete![/green]")

def handle_fresh_start(handler, args: str):
    """Save current session and start fresh."""
    # Save first
    CommandFactory.call("save", handler, "")
    # Then clear
    CommandFactory.call("clear", handler, "")
    console.print("[green]Ready for new conversation.[/green]")

def handle_switch_coding(handler, args: str):
    """Switch to coding mode with tools enabled."""
    CommandFactory.call("provider", handler, "openrouter")
    CommandFactory.call("model", handler, "anthropic/claude-sonnet-4")
    CommandFactory.call("tools", handler, "on")
    console.print("[green]Coding mode active.[/green]")

# Register workflow commands
CommandFactory.register(CommandSpec(
    name="backup",
    description="Full backup workflow",
    handler=handle_backup,
    category="workflow"
))

CommandFactory.register(CommandSpec(
    name="fresh",
    aliases=["new"],
    description="Save and start fresh",
    handler=handle_fresh_start,
    category="workflow"
))

CommandFactory.register(CommandSpec(
    name="coding",
    description="Switch to coding mode",
    handler=handle_switch_coding,
    category="workflow"
))
```

### Error Handling in Composition

```python
def handle_safe_workflow(handler, args: str):
    """Workflow with error handling."""
    try:
        CommandFactory.call("save", handler, "")
    except Exception as e:
        console.print(f"[yellow]Warning: Save failed: {e}[/yellow]")
        # Continue anyway or abort
        return

    # Only proceed if save succeeded
    CommandFactory.call("export", handler, "report.md")
```

### Checking Command Existence

```python
def handle_conditional(handler, args: str):
    """Call command only if it exists."""
    if CommandFactory.get("custom_cmd"):
        CommandFactory.call("custom_cmd", handler, args)
    else:
        console.print("[dim]custom_cmd not available[/dim]")
```

### Benefits of Composition

| Benefit | Description |
|---------|-------------|
| **Reuse** | Leverage well-tested built-in commands |
| **DRY** | Don't repeat save/export/clear logic |
| **Consistency** | Same behavior as direct command invocation |
| **Testability** | Mock `CommandFactory.call()` in tests |
| **Extensibility** | Users can create powerful workflows |

### Guidelines

1. **Always handle errors** - Called commands might fail
2. **Check existence first** - For optional dependencies
3. **Avoid circular calls** - `/a` calls `/b` calls `/a` → infinite loop
4. **Document dependencies** - List which commands your workflow uses

---

## Future Extensions

### Command Validation

```python
@dataclass
class CommandSpec:
    name: str
    validator: Optional[Callable[[str], bool]] = None  # Validate args
    completer: Optional[Callable[[], List[str]]] = None  # Tab completion
```

### Async Commands

```python
@dataclass
class CommandSpec:
    is_async: bool = False  # Handler is async def

# In dispatch:
if spec.is_async:
    return await spec.handler(handler, args)
return spec.handler(handler, args)
```

### Command Permissions

```python
@dataclass
class CommandSpec:
    requires_tools: bool = False  # Only available when tools enabled
    requires_session: bool = False  # Only available with active session
```

---

## Decision Record

**Decision:** Implement Command Factory pattern for commands.py refactoring.

**Rationale:**
- Aligns with planned Tool Factory pattern
- Enables user-defined commands
- Cleaner dispatch mechanism
- Auto-generated /help
- Consistent architecture across codebase

**When to Implement:** v1.13.10 stabilization branch (current)

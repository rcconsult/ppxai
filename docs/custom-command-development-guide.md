# Custom Command Development Guide

This guide explains how to create, register, and debug custom commands using the Command Factory framework. Custom commands work with both **ppxai** (Rich TUI) and **ppxaide** (Textual TUI).

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Command Structure](#command-structure)
3. [Registration](#registration)
4. [Arguments and Parsing](#arguments-and-parsing)
5. [Accessing Handler Context](#accessing-handler-context)
6. [Output and Formatting](#output-and-formatting)
7. [Error Handling](#error-handling)
8. [Logging and Debugging](#logging-and-debugging)
9. [Testing Your Command](#testing-your-command)
10. [Best Practices](#best-practices)
11. [Examples](#examples)

---

## Quick Start

### Step 1: Create the Commands Directory

```bash
mkdir -p ~/.ppxai/commands
```

### Step 2: Create Your Command File

```python
# ~/.ppxai/commands/hello.py
from ppxai.commands import CommandFactory, CommandSpec
from rich.console import Console

console = Console()

def handle_hello(handler, args: str):
    """Handle /hello command."""
    name = args.strip() if args.strip() else "World"
    console.print(f"[green]Hello, {name}![/green]")

# Register the command
CommandFactory.register(CommandSpec(
    name="hello",
    description="Say hello to someone",
    handler=handle_hello,
    category="custom",
    usage="/hello [name]"
))
```

### Step 3: Load and Use

```
> /reload
User commands reloaded (1 modules).

> /hello Claude
Hello, Claude!

> /help
...
Custom
  /hello - Say hello to someone
```

---

## Command Structure

### The Handler Function

Every command is a Python function with this signature:

```python
def handle_<name>(handler, args: str) -> Optional[bool]:
    """
    Handle /<name> command.

    Args:
        handler: CommandHandler instance (provides access to engine, session, etc.)
        args: Raw argument string (everything after the command name)

    Returns:
        None - Normal completion
        True - Signal to exit the application (only for /quit-like commands)
        False - Continue but indicate failure (rarely used)
    """
    pass
```

### The CommandSpec

```python
@dataclass
class CommandSpec:
    name: str                    # Command name (without /)
    description: str             # Short description for /help
    handler: Callable            # The handler function
    category: str = "general"    # Category for grouping in /help
    aliases: List[str] = []      # Alternative names (e.g., ["h"] for /h -> /hello)
    usage: str = ""              # Usage hint (e.g., "/hello [name]")
    hidden: bool = False         # Hide from /help listing
```

---

## Registration

### Basic Registration

```python
from ppxai.commands import CommandFactory, CommandSpec

CommandFactory.register(CommandSpec(
    name="mycommand",
    description="Does something useful",
    handler=handle_mycommand,
    category="custom"
))
```

### With Aliases

```python
CommandFactory.register(CommandSpec(
    name="search",
    aliases=["s", "find"],      # /s and /find also work
    description="Search for something",
    handler=handle_search,
    category="custom",
    usage="/search <query>"
))
```

### Hidden Commands

```python
CommandFactory.register(CommandSpec(
    name="debug_internal",
    description="Internal debugging command",
    handler=handle_debug_internal,
    category="custom",
    hidden=True                  # Won't appear in /help
))
```

### Multiple Commands in One File

```python
# ~/.ppxai/commands/git_commands.py

def handle_gstatus(handler, args: str):
    """Show git status."""
    ...

def handle_glog(handler, args: str):
    """Show git log."""
    ...

def handle_gdiff(handler, args: str):
    """Show git diff."""
    ...

# Register all commands
for name, func, desc in [
    ("gstatus", handle_gstatus, "Show git status"),
    ("glog", handle_glog, "Show git log"),
    ("gdiff", handle_gdiff, "Show git diff"),
]:
    CommandFactory.register(CommandSpec(
        name=name,
        description=desc,
        handler=func,
        category="git"
    ))
```

---

## Arguments and Parsing

### Raw Arguments

The `args` parameter contains everything after the command name:

```
/mycommand foo bar baz
           ^^^^^^^^^^^
           args = "foo bar baz"
```

### Simple Argument Parsing

```python
def handle_greet(handler, args: str):
    """Handle /greet <name> [greeting]"""
    parts = args.split(maxsplit=1)

    if not parts:
        console.print("[red]Usage: /greet <name> [greeting][/red]")
        return

    name = parts[0]
    greeting = parts[1] if len(parts) > 1 else "Hello"

    console.print(f"{greeting}, {name}!")
```

### Flag-Style Arguments

```python
def handle_list(handler, args: str):
    """Handle /list [-a|--all] [-n NUM] [path]"""
    import shlex

    try:
        tokens = shlex.split(args)
    except ValueError:
        tokens = args.split()

    show_all = False
    limit = 10
    path = "."

    i = 0
    while i < len(tokens):
        if tokens[i] in ("-a", "--all"):
            show_all = True
        elif tokens[i] == "-n" and i + 1 < len(tokens):
            limit = int(tokens[i + 1])
            i += 1
        elif not tokens[i].startswith("-"):
            path = tokens[i]
        i += 1

    # Use parsed arguments...
```

### Using argparse (Advanced)

```python
import argparse
import shlex

def handle_fetch(handler, args: str):
    """Handle /fetch [options] <url>"""
    parser = argparse.ArgumentParser(prog="/fetch", add_help=False)
    parser.add_argument("url", help="URL to fetch")
    parser.add_argument("-o", "--output", help="Output file")
    parser.add_argument("-q", "--quiet", action="store_true")

    try:
        parsed = parser.parse_args(shlex.split(args))
    except SystemExit:
        console.print(f"[dim]Usage: /fetch [-o FILE] [-q] <url>[/dim]")
        return

    # Use parsed.url, parsed.output, parsed.quiet
    ...
```

---

## Accessing Handler Context

The `handler` parameter provides access to the full application context:

### Engine Client

```python
def handle_ask(handler, args: str):
    """Send a message to the AI."""
    import asyncio

    async def run():
        async for event in handler.engine_client.chat(args, stream=True):
            if event.type.name == "STREAM_CHUNK":
                console.print(event.data, end="")
        console.print()

    asyncio.run(run())
```

### Session Data

```python
def handle_history(handler, args: str):
    """Show conversation history."""
    messages = handler.engine_client.session.messages

    for i, msg in enumerate(messages[-10:], 1):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")[:50]
        console.print(f"{i}. [{role}] {content}...")
```

### Current Model and Provider

```python
def handle_info(handler, args: str):
    """Show current configuration."""
    console.print(f"Provider: {handler.provider}")
    console.print(f"Model: {handler.current_model}")
    console.print(f"Tools enabled: {handler.engine_client.tools_enabled}")
    console.print(f"Working dir: {handler.engine_client.working_dir}")
```

### Theme

```python
def handle_themed(handler, args: str):
    """Output using current theme."""
    theme = handler.theme

    console.print(f"[{theme.info}]Info message[/]")
    console.print(f"[{theme.success}]Success message[/]")
    console.print(f"[{theme.error}]Error message[/]")
```

---

## Output and Formatting

### Using Rich Console

```python
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()

def handle_table(handler, args: str):
    """Show data in a table."""
    table = Table(title="My Data")
    table.add_column("Name", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Item 1", "100")
    table.add_row("Item 2", "200")

    console.print(table)

def handle_panel(handler, args: str):
    """Show content in a panel."""
    console.print(Panel(
        "This is important content",
        title="Notice",
        border_style="yellow"
    ))

def handle_markdown(handler, args: str):
    """Render markdown."""
    md = Markdown("""
# Heading
- Item 1
- Item 2

**Bold** and *italic* text.
    """)
    console.print(md)
```

### Status Messages

```python
def handle_process(handler, args: str):
    """Process with status indicator."""
    from rich.status import Status

    with console.status("[bold green]Processing...") as status:
        # Do work...
        import time
        time.sleep(2)

    console.print("[green]Done![/green]")
```

---

## Error Handling

### User Errors

```python
def handle_open(handler, args: str):
    """Open a file."""
    if not args.strip():
        console.print("[red]Error: Please specify a file path[/red]")
        console.print("[dim]Usage: /open <filepath>[/dim]")
        return

    path = Path(args.strip()).expanduser()

    if not path.exists():
        console.print(f"[red]Error: File not found: {path}[/red]")
        return

    if not path.is_file():
        console.print(f"[red]Error: Not a file: {path}[/red]")
        return

    # Process file...
```

### Exception Handling

```python
def handle_risky(handler, args: str):
    """Command that might fail."""
    try:
        result = do_something_risky(args)
        console.print(f"[green]Success: {result}[/green]")
    except ValueError as e:
        console.print(f"[red]Invalid input: {e}[/red]")
    except FileNotFoundError as e:
        console.print(f"[red]File not found: {e}[/red]")
    except Exception as e:
        # Log unexpected errors
        logger.exception(f"Unexpected error in /risky: {e}")
        console.print(f"[red]Unexpected error: {e}[/red]")
        console.print("[dim]Check logs for details.[/dim]")
```

---

## Logging and Debugging

### Setting Up Logging

```python
# ~/.ppxai/commands/my_commands.py
from ppxai.common.logger import get_logger

logger = get_logger("custom.mycommands")

def handle_debug_example(handler, args: str):
    """Example with logging."""
    logger.debug(f"Command called with args: {args!r}")

    try:
        result = process(args)
        logger.info(f"Processed successfully: {result}")
        console.print(f"[green]Result: {result}[/green]")
    except Exception as e:
        logger.exception(f"Failed to process: {e}")
        console.print(f"[red]Error: {e}[/red]")
```

### Log Levels

```python
logger.debug("Detailed debugging info (only in debug mode)")
logger.info("General information")
logger.warning("Warning - something unexpected but not fatal")
logger.error("Error - operation failed")
logger.exception("Error with stack trace (use in except blocks)")
```

### Viewing Logs

```bash
# Logs are stored in ~/.ppxai/logs/
tail -f ~/.ppxai/logs/tui-debug.log

# Or use /debug-log in ppxai to enable logging, then show it
> /debug-log on
> /debug-log show
```

### Debug Mode

```python
def handle_verbose(handler, args: str):
    """Command with verbose output."""
    verbose = "-v" in args or "--verbose" in args

    if verbose:
        console.print("[dim]Step 1: Initializing...[/dim]")

    # Do step 1...

    if verbose:
        console.print("[dim]Step 2: Processing...[/dim]")

    # Do step 2...
```

---

## Testing Your Command

### Interactive Testing

```bash
# 1. Create your command file
vim ~/.ppxai/commands/test_command.py

# 2. Start ppxai
ppxai

# 3. Reload to pick up changes
> /reload
User commands reloaded (1 modules).

# 4. Test your command
> /test_command arg1 arg2

# 5. Make changes, reload, repeat
> /reload
```

### Unit Testing

```python
# tests/test_my_commands.py
import pytest
from unittest.mock import MagicMock, patch

# Import your command module
import sys
sys.path.insert(0, str(Path.home() / ".ppxai" / "commands"))
import my_commands

def test_handle_hello():
    """Test hello command."""
    handler = MagicMock()

    with patch.object(my_commands, 'console') as mock_console:
        my_commands.handle_hello(handler, "Claude")
        mock_console.print.assert_called_once()
        call_args = mock_console.print.call_args[0][0]
        assert "Claude" in call_args

def test_handle_hello_no_args():
    """Test hello with no arguments."""
    handler = MagicMock()

    with patch.object(my_commands, 'console') as mock_console:
        my_commands.handle_hello(handler, "")
        call_args = mock_console.print.call_args[0][0]
        assert "World" in call_args
```

---

## Best Practices

### 1. Validate Arguments Early

```python
def handle_cmd(handler, args: str):
    # Validate first
    if not args.strip():
        console.print("[red]Error: Argument required[/red]")
        return

    # Then process
    ...
```

### 2. Use Descriptive Names

```python
# Good
CommandSpec(name="search_files", ...)
CommandSpec(name="git_status", ...)

# Avoid
CommandSpec(name="sf", ...)  # Too cryptic
CommandSpec(name="do_thing", ...)  # Too vague
```

### 3. Provide Usage Hints

```python
CommandSpec(
    name="convert",
    description="Convert file format",
    usage="/convert <input> <output> [-f FORMAT]",
    ...
)
```

### 4. Use Categories

```python
# Group related commands
category="git"       # Git operations
category="file"      # File operations
category="session"   # Session management
category="custom"    # User-defined (default)
```

### 5. Handle Async Operations

```python
import asyncio

def handle_async_cmd(handler, args: str):
    """Command that needs async."""

    async def run():
        # Async operations here
        result = await some_async_function()
        console.print(result)

    asyncio.run(run())
```

### 6. Don't Block the Event Loop

```python
# Bad - blocks for a long time
def handle_slow(handler, args: str):
    import time
    time.sleep(60)  # Blocks everything!

# Better - show progress
def handle_slow(handler, args: str):
    from rich.progress import Progress

    with Progress() as progress:
        task = progress.add_task("Processing...", total=100)
        for i in range(100):
            do_work_chunk()
            progress.update(task, advance=1)
```

### 7. Clean Up Resources

```python
def handle_file_op(handler, args: str):
    """Handle file with proper cleanup."""
    path = Path(args.strip())

    try:
        with open(path) as f:
            content = f.read()
        # Process content
    except IOError as e:
        console.print(f"[red]Error: {e}[/red]")
```

---

## Examples

### Example 1: Git Status Command

```python
# ~/.ppxai/commands/git.py
"""Git helper commands."""

import subprocess
from ppxai.commands import CommandFactory, CommandSpec
from rich.console import Console
from rich.syntax import Syntax

console = Console()

def run_git(args: list) -> tuple[str, int]:
    """Run git command and return output."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True
    )
    return result.stdout + result.stderr, result.returncode

def handle_gs(handler, args: str):
    """Show git status."""
    output, code = run_git(["status", "--short"])
    if code == 0:
        if output.strip():
            console.print(output)
        else:
            console.print("[green]Working tree clean[/green]")
    else:
        console.print(f"[red]{output}[/red]")

def handle_gl(handler, args: str):
    """Show git log."""
    count = args.strip() if args.strip() else "10"
    output, code = run_git(["log", f"-{count}", "--oneline"])
    if code == 0:
        console.print(output)
    else:
        console.print(f"[red]{output}[/red]")

def handle_gd(handler, args: str):
    """Show git diff."""
    output, code = run_git(["diff"] + args.split())
    if code == 0:
        syntax = Syntax(output, "diff", theme="monokai")
        console.print(syntax)
    else:
        console.print(f"[red]{output}[/red]")

# Register commands
CommandFactory.register(CommandSpec(
    name="gs", description="Git status (short)", handler=handle_gs, category="git"
))
CommandFactory.register(CommandSpec(
    name="gl", description="Git log", handler=handle_gl, category="git", usage="/gl [count]"
))
CommandFactory.register(CommandSpec(
    name="gd", description="Git diff", handler=handle_gd, category="git", usage="/gd [file]"
))
```

### Example 2: Quick Note Command

```python
# ~/.ppxai/commands/notes.py
"""Quick notes commands."""

from pathlib import Path
from datetime import datetime
from ppxai.commands import CommandFactory, CommandSpec
from rich.console import Console

console = Console()
NOTES_FILE = Path.home() / ".ppxai" / "notes.md"

def handle_note(handler, args: str):
    """Add a quick note."""
    if not args.strip():
        console.print("[red]Usage: /note <your note>[/red]")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {timestamp}\n\n{args.strip()}\n"

    NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(NOTES_FILE, "a") as f:
        f.write(entry)

    console.print(f"[green]Note saved.[/green]")

def handle_notes(handler, args: str):
    """Show recent notes."""
    if not NOTES_FILE.exists():
        console.print("[dim]No notes yet. Use /note to add one.[/dim]")
        return

    content = NOTES_FILE.read_text()
    entries = content.split("\n## ")[-5:]  # Last 5 entries

    for entry in entries:
        if entry.strip():
            console.print(f"[cyan]## {entry}[/cyan]")

CommandFactory.register(CommandSpec(
    name="note", description="Add a quick note", handler=handle_note,
    category="notes", usage="/note <text>"
))
CommandFactory.register(CommandSpec(
    name="notes", description="Show recent notes", handler=handle_notes,
    category="notes"
))
```

### Example 3: API Helper Command

```python
# ~/.ppxai/commands/api.py
"""API helper commands."""

import json
import asyncio
from ppxai.commands import CommandFactory, CommandSpec
from rich.console import Console
from rich.syntax import Syntax

console = Console()

def handle_api(handler, args: str):
    """Make API request via AI."""
    if not args.strip():
        console.print("[red]Usage: /api <describe what you want>[/red]")
        return

    prompt = f"""Generate a curl command for: {args}
    Return ONLY the curl command, no explanation."""

    async def run():
        response = ""
        async for event in handler.engine_client.chat(prompt, stream=True):
            if event.type.name == "STREAM_CHUNK":
                response += event.data

        # Extract curl command
        if "curl" in response:
            console.print("\n[bold]Generated command:[/bold]")
            syntax = Syntax(response.strip(), "bash", theme="monokai")
            console.print(syntax)

    asyncio.run(run())

CommandFactory.register(CommandSpec(
    name="api",
    description="Generate API curl command",
    handler=handle_api,
    category="tools",
    usage="/api <describe the API call>"
))
```

---

## Troubleshooting

### Command Not Found After /reload

1. Check file is in `~/.ppxai/commands/`
2. Check file has `.py` extension
3. Check for syntax errors: `python ~/.ppxai/commands/myfile.py`
4. Check logs: `/debug-log show`

### Import Errors

```python
# Wrong - ppxai might not be in path
from commands import CommandFactory

# Correct
from ppxai.commands import CommandFactory, CommandSpec
```

### Command Registered But Not Working

```python
# Check registration
from ppxai.commands import CommandFactory
print(CommandFactory.list_all())
print(CommandFactory.get("mycommand"))
```

### Handler Not Called

- Ensure function signature is `def handle_xxx(handler, args: str)`
- Check the `handler` parameter in `CommandSpec` points to correct function

---

## Reference

### Available Imports

```python
# Command framework
from ppxai.commands import CommandFactory, CommandSpec

# Logging
from ppxai.common.logger import get_logger

# Configuration
from ppxai.config import get_tui_config, get_provider_config

# UI utilities
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.syntax import Syntax
```

### Handler Context (handler object)

| Attribute | Type | Description |
|-----------|------|-------------|
| `handler.engine_client` | EngineClient | Main AI client |
| `handler.provider` | str | Current provider name |
| `handler.current_model` | str | Current model name |
| `handler.theme` | Theme | Current UI theme |
| `handler.api_key` | str | API key |
| `handler.base_url` | str | API base URL |
| `handler.tools_verbose` | bool | Verbose tool logging |
| `handler.auto_route` | bool | Auto-route to coding model |

### Engine Client Methods

| Method | Description |
|--------|-------------|
| `engine_client.chat(message, stream=True)` | Send message, get response |
| `engine_client.set_model(name)` | Change model |
| `engine_client.set_provider(name)` | Change provider |
| `engine_client.enable_tools()` | Enable tools |
| `engine_client.disable_tools()` | Disable tools |
| `engine_client.session.save()` | Save session |
| `engine_client.session.load(name)` | Load session |
| `engine_client.session.messages` | Conversation history |

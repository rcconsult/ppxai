"""
UI/display functions for the ppxai terminal interface.
"""

import json
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.table import Table

from ..config import MODELS, USAGE_FILE, PROVIDERS, get_provider_config
from ..prompts import SPEC_GUIDELINES, SPEC_TEMPLATES

# Initialize Rich console
console = Console()


def display_welcome():
    """Display welcome message."""
    welcome_text = """
# ppxai - AI Text UI

Welcome to the AI terminal interface!

## General Commands
- Type your question or prompt to chat
- `/save` - Save session to JSON file
- `/export [filename]` - Export last answer to markdown file
- `/sessions` - List all saved sessions
- `/load <session>` - Load a previous session
- `/usage` - Show current session usage statistics
- `/clear` - Clear conversation history
- `/model` - Change model
- `/status` - Show status info
- `/status datetime` - Toggle date/time in status bar
- `/status version` - Toggle version in status bar
- `/status cwd` - Toggle working dir in status bar
- `/context` - Show context usage (tokens, injected files)
- `/context clear` - Remove injected @file/@git/@tree from history
- `/context hints` - Show active bootstrap hints for current provider/model
- `/help` - Show this help message
- `/quit` or `/exit` - Exit the application

## File Commands
- `/show <file>` - Display file contents with syntax highlighting (no LLM call)
- `/cat <file>` - Alias for /show

## Code Generation Tools
- `/generate <description>` - Generate code from natural language description
- `/test <file>` - Generate unit tests for a code file
- `/docs <file>` - Generate documentation for a code file
- `/implement <specification>` - Implement a feature from detailed specification
- `/debug <error>` - Analyze and fix errors, exceptions, and bugs
- `/explain <file>` - Explain code logic and design decisions step-by-step
- `/convert <from> <to> <file>` - Convert code between programming languages
- `/spec [type]` - Show specification guidelines and templates (api, cli, lib, algo, ui)
- `/autoroute [on|off]` - Toggle auto-routing to best coding model (enabled by default)
- `/provider` - Switch between providers (Perplexity, Custom)

## AI Tools (Experimental)
- `/tools enable` - Enable AI tools (file search, calculator, **file editing**)
- `/tools disable` - Disable AI tools
- `/tools list` - Show available tools
- `/tools status` - Show tools status and consent mode
- `/tools help editing` - 🆕 Interactive guide for file editing tools

## Agent Mode (v1.12.0) 🆕
- `/agent <task>` - Execute autonomous agent task with checkpoints
- `/undo` - Revert last agent task (requires checkpoints enabled)
**Safety:** Changes auto-committed (git) or snapshotted (file backup) before tasks

## File Editing Tools (v1.11.0) 🆕
When tools are enabled, AI can edit files **with your consent**:
- **apply_patch** - Apply unified diff patches
- **replace_block** - Find and replace code blocks
- **insert_text** - Insert code at specific lines
- **delete_lines** - Delete line ranges

**Safety:** User consent required (y/n/always/never) before any edit!
**Learn more:** Type `/tools help editing` for examples
"""
    console.print(Panel(Markdown(welcome_text), title="Welcome", border_style="cyan"))


def display_file_editing_help():
    """Display interactive help for file editing tools (v1.11.0)."""
    help_text = """
# File Editing Tools Guide 🎯

## Overview

ppxai can now **autonomously edit files** during conversations! All edits require your **explicit consent** before any changes are made.

## Quick Start

1. **Enable tools**: `/tools enable`
2. **Ask AI to edit**: Just request file changes naturally!
3. **Grant consent**: Choose y/n/always/never when prompted

---

## Consent System

When AI wants to edit a file, you'll see:

```
⚠️  File Edit Request
AI wants to edit: /path/to/file.py
Options: y (yes), n (no), always (all files), never (block all)

Allow edit?
```

### Consent Options

| Option | Effect | Example |
|--------|--------|---------|
| **y** | Allow this file only | Same file can be edited again |
| **n** | Deny this edit | File unchanged, AI continues |
| **always** | Auto-approve all files | Great for multi-file refactoring |
| **never** | Block all edits | No files modified this session |

---

## Practical Examples

### Example 1: Fix a Typo

**You:** `Fix the typo in config.py - 'databse' should be 'database'`

**AI:** `I'll fix that typo` → **[Consent Prompt]** → You type `y`

**Result:** ✓ File edited using `replace_block` tool

---

### Example 2: Add New Function

**You:** `Add a password validation function to utils.py`

**AI:** `I'll add password_is_strong() after line 45` → **[Consent]** → `y`

**Result:** ✓ Function inserted using `insert_text` tool

---

### Example 3: Multi-File Refactoring

**You:** `Extract database connection logic into db.py`

**AI:** `Creating db.py and updating main.py` → **[Consent]** → `always`

**Result:** ✓ AI edits both files without additional prompts

---

### Example 4: Apply Code Review

**You:** `Remove all debug print statements from auth.py`

**AI:** `Found 3 debug statements to remove` → **[Consent]** → `y`

**Result:** ✓ Lines deleted using `delete_lines` tool (3 edits, 1 consent)

---

### Example 5: Apply a Patch

**You:** `Apply this security patch:` + diff

**AI:** `Applying SQL injection fix` → **[Consent]** → `y`

**Result:** ✓ Patch applied using `apply_patch` tool

---

## Available Tools

### 1. replace_block
**Purpose:** Find and replace exact text (must be unique)

**Example prompts:**
- `Replace the old error handling with try/catch`
- `Change DATABASE_URL to use env variable`
- `Fix typo 'recieve' to 'receive'`

### 2. insert_text
**Purpose:** Add lines at specific position

**Example prompts:**
- `Add this import at the top`
- `Insert error handling after line 42`
- `Add docstring to the function`

### 3. delete_lines
**Purpose:** Remove line ranges

**Example prompts:**
- `Remove the deprecated login function`
- `Delete all commented code`
- `Clean up debug statements`

### 4. apply_patch
**Purpose:** Apply unified diff patches

**Example prompts:**
- `Apply this code review patch`
- `Use this diff to fix the bug`

---

## Pro Tips 💡

**For refactoring:**
```
You: Refactor auth module - extract hashing to utils
[Use "always" on first consent prompt]
```

**With file references:**
```
You: @bug_report.md @user_service.py
     Fix the race condition described in the report
```

**For multiple edits:**
```
You: Implement user profile editing:
     1. Add PUT endpoint
     2. Add database method
     3. Update model
[AI edits all 3 files systematically]
```

---

## Safety Features ✅

- **Session-scoped consent** - Permissions only last this session
- **Atomic operations** - All-or-nothing edits
- **Automatic rollback** - Failed edits restore original
- **No silent changes** - You always see what's modified
- **Safe defaults** - Errors/timeouts deny edits

---

## Troubleshooting

**"Search text not found"**
→ Ask AI to show current content first: `Show me the login function`

**"Search text found multiple times"**
→ Be more specific: `Replace the version check in __init__, not main`

**Accidentally denied consent**
→ Just ask again: `Try that edit again`

**Too many prompts**
→ Use `always` for the session: Type `always` on first consent

---

## Commands

- `/tools status` - Check consent mode (ask/always/never)
- `/tools list` - See all available tools
- `/tools disable` - Turn off file editing
- `/help` - General help

---

## Full Guide

For complete documentation with advanced patterns:
📖 See `docs/FILE_EDITING_GUIDE.md`

---

**Ready to try?** Enable tools and ask AI to make a file change!
"""
    console.print(Panel(Markdown(help_text), title="📝 File Editing Tools - Interactive Guide", border_style="green", padding=(1, 2)))


def display_spec_help(spec_type: Optional[str] = None):
    """Display specification guidelines or specific template."""
    if not spec_type:
        # Show general guidelines
        console.print(Panel(Markdown(SPEC_GUIDELINES), title="Specification Guidelines", border_style="green"))
    elif spec_type in SPEC_TEMPLATES:
        # Show specific template
        console.print(Panel(Markdown(SPEC_TEMPLATES[spec_type]), title=f"{spec_type.upper()} Specification Template", border_style="green"))
    else:
        console.print(f"[red]Unknown specification type: {spec_type}[/red]")
        console.print("[yellow]Available types: api, cli, lib, algo, ui[/yellow]")
        console.print("[yellow]Use /spec without arguments for general guidelines[/yellow]\n")


def display_models(provider: str = None):
    """Display available models in a table."""
    config = get_provider_config(provider)
    models = config["models"]
    provider_name = config["name"]

    table = Table(title=f"Available Models ({provider_name})", show_header=True, header_style="bold magenta")
    table.add_column("Choice", style="cyan", width=8)
    table.add_column("Name", style="green")
    table.add_column("Description", style="white")

    for choice, model in models.items():
        table.add_row(choice, model["name"], model["description"])

    console.print(table)


def select_model(provider: str = None) -> Optional[str]:
    """Prompt user to select a model."""
    config = get_provider_config(provider)
    models = config["models"]

    display_models(provider)

    # Default to first model if only one available
    default_choice = "1" if len(models) == 1 else "2" if "2" in models else "1"

    choice = Prompt.ask(
        "\n[bold yellow]Select a model[/bold yellow]",
        choices=list(models.keys()),
        default=default_choice
    )

    selected_model = models[choice]
    console.print(f"\n[green]Selected:[/green] {selected_model['name']}")
    return selected_model["id"]


def select_provider() -> str:
    """Prompt user to select a provider."""
    table = Table(title="Available Providers", show_header=True, header_style="bold magenta")
    table.add_column("Choice", style="cyan", width=8)
    table.add_column("Provider", style="green")
    table.add_column("Endpoint", style="white")

    provider_keys = list(PROVIDERS.keys())
    for idx, key in enumerate(provider_keys, 1):
        config = PROVIDERS[key]
        table.add_row(str(idx), config["name"], config["base_url"])

    console.print(table)

    choice = Prompt.ask(
        "\n[bold yellow]Select a provider[/bold yellow]",
        choices=[str(i) for i in range(1, len(provider_keys) + 1)],
        default="1"
    )

    selected_provider = provider_keys[int(choice) - 1]
    console.print(f"\n[green]Selected:[/green] {PROVIDERS[selected_provider]['name']}")
    return selected_provider


def display_sessions(sessions):
    """Display all saved sessions in a table."""
    if not sessions:
        console.print("\n[yellow]No saved sessions found.[/yellow]\n")
        return

    table = Table(title="Saved Sessions", show_header=True, header_style="bold magenta")
    table.add_column("Session Name", style="cyan")
    table.add_column("Created", style="green")
    table.add_column("Last Saved", style="green")
    table.add_column("Messages", style="yellow", justify="right")

    for session in sessions:
        created = session.get('created_at', '')
        created = created[:19] if created and created != "Unknown" else "Unknown"
        saved = session.get('saved_at', '')
        saved = saved[:19] if saved and saved != "Unknown" else "Unknown"
        table.add_row(
            session.get('name', session.get('session_name', 'Unknown')),
            created,
            saved,
            str(session.get('message_count', 0))
        )

    console.print(table)
    console.print()


def display_usage(usage):
    """Display current session usage statistics."""
    table = Table(title="Current Session Usage", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")

    table.add_row("Total Tokens", f"{usage['total_tokens']:,}")
    table.add_row("Prompt Tokens", f"{usage['prompt_tokens']:,}")
    table.add_row("Completion Tokens", f"{usage['completion_tokens']:,}")
    table.add_row("Estimated Cost", f"${usage['estimated_cost']:.4f}")

    console.print()
    console.print(table)
    console.print()


def display_global_usage():
    """Display global usage statistics from all time."""
    if not USAGE_FILE.exists():
        console.print("\n[yellow]No usage data available yet.[/yellow]\n")
        return

    with open(USAGE_FILE, 'r') as f:
        usage_data = json.load(f)

    if not usage_data:
        console.print("\n[yellow]No usage data available yet.[/yellow]\n")
        return

    table = Table(title="Global Usage Statistics", show_header=True, header_style="bold magenta")
    table.add_column("Date", style="cyan")
    table.add_column("Model", style="green")
    table.add_column("Requests", style="yellow", justify="right")
    table.add_column("Total Tokens", style="yellow", justify="right")

    for date in sorted(usage_data.keys(), reverse=True)[:7]:  # Last 7 days
        for model, stats in usage_data[date].items():
            table.add_row(
                date,
                model,
                str(stats['requests']),
                f"{stats['total_tokens']:,}"
            )

    console.print()
    console.print(table)
    console.print("\n[dim]Showing last 7 days of usage[/dim]\n")


def display_tools_table(tools_list):
    """Display available tools in a table."""
    table = Table(title="Available Tools", show_header=True, header_style="bold cyan")
    table.add_column("Tool", style="green")
    table.add_column("Source", style="yellow")
    table.add_column("Description", style="white")

    for tool_info in tools_list:
        desc = tool_info['description']
        table.add_row(
            tool_info['name'],
            tool_info['source'],
            desc[:60] + "..." if len(desc) > 60 else desc
        )

    console.print()
    console.print(table)
    console.print()


def display_tool_help(tool_name: str, tool_info: dict):
    """Display detailed help for a specific tool.

    Args:
        tool_name: Name of the tool
        tool_info: Dictionary with 'description' and 'parameters' keys
    """
    description = tool_info.get('description', 'No description available')
    parameters = tool_info.get('parameters', {})
    properties = parameters.get('properties', {})
    required = parameters.get('required', [])

    # Build help text
    lines = []
    lines.append(f"**{tool_name}**")
    lines.append("")
    lines.append(description)
    lines.append("")

    if properties:
        lines.append("## Parameters")
        lines.append("")

        for param_name, param_info in properties.items():
            param_type = param_info.get('type', 'any')
            param_desc = param_info.get('description', 'No description')
            is_required = param_name in required

            # Handle enum types
            if 'enum' in param_info:
                enum_values = ', '.join(f'`{v}`' for v in param_info['enum'])
                param_type = f"enum [{enum_values}]"

            req_marker = "**required**" if is_required else "optional"
            lines.append(f"- `{param_name}` ({param_type}, {req_marker})")
            lines.append(f"  {param_desc}")
            lines.append("")
    else:
        lines.append("*No parameters required*")
        lines.append("")

    # Add usage example
    lines.append("## Example Usage")
    lines.append("")
    lines.append(f"Ask the AI: *\"Use {tool_name} to ...\"*")
    lines.append("")

    # Build example call
    if properties:
        example_args = []
        for param_name in required[:2]:  # Show first 2 required params
            param_info = properties.get(param_name, {})
            if param_info.get('type') == 'string':
                example_args.append(f'{param_name}="value"')
            elif param_info.get('type') == 'integer':
                example_args.append(f'{param_name}=10')
            elif param_info.get('type') == 'boolean':
                example_args.append(f'{param_name}=true')
            else:
                example_args.append(f'{param_name}=...')

        if example_args:
            args_str = ', '.join(example_args)
            lines.append(f"AI calls: `{tool_name}({args_str})`")

    help_text = '\n'.join(lines)
    console.print(Panel(
        Markdown(help_text),
        title=f"🔧 Tool Help: {tool_name}",
        border_style="cyan",
        padding=(1, 2)
    ))

"""
UI/display functions for the ppxai terminal interface.
"""

import json
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from ..config import PROVIDERS, USAGE_FILE, get_provider_config
from ..prompts import SPEC_GUIDELINES, SPEC_TEMPLATES

# Initialize Rich console
console = Console()


#: Prose the welcome screen keeps that is NOT command metadata: the
#: consent/safety model for the file-editing tools. It names exactly one
#: command (`/tools help editing`, the guide that explains it), so it is
#: not a roster and cannot drift into one.
_SAFETY_NOTES = """
## File Editing Tools

When tools are enabled, AI can edit files **with your consent** —
`apply_patch`, `replace_block`, `insert_text`, `delete_lines`.

**Safety:** user consent (y/n/always/never) is required before any edit,
and auto-mode changes are auto-committed (git) or snapshotted (file
backup) before a task runs.
**Learn more:** type `/tools help editing` for examples.
"""


def display_welcome(commands):
    """Display the welcome message, DERIVED from the command registry.

    ADR 0007 step 5. This screen used to carry a hand-written ~30-command
    list with its own usage strings and descriptions — the SEVENTH roster
    the record found, on the Python side, and already drifted: 18
    registered commands were missing from it (`/attach`, `/cd`,
    `/checkpoint`, `/config`, `/debug-log`, `/doctor`, `/edit`, `/keys`,
    `/ls`, `/preview`, `/preview-log`, `/pwd`, `/reload`, `/run`,
    `/task`, `/terminal`, `/theme`, `/tree`) and several descriptions no
    longer matched the spec.

    `commands` is PLAIN DATA — the `commands` list of
    `CommandFactory.roster("rich")` — handed in by the caller, exactly as
    step 4 did for `engine.completion.complete(roster=...)`. It is
    REQUIRED and has no default: this module cannot import
    `ppxai.commands` (that package's `__init__` imports this one back,
    so a module-scope import is a genuine circular-import failure, and
    the project bans lazy imports), and a default would turn a forgotten
    roster into a silently empty welcome screen instead of a `TypeError`
    naming the call site.

    Args:
        commands: Roster entries — dicts with `name`, `aliases`,
            `description`, `usage`, `category`, `hidden`.
    """
    by_category: dict[str, list[dict]] = {}
    for cmd in commands:
        if cmd.get("hidden"):
            continue
        by_category.setdefault(cmd.get("category") or "other", []).append(cmd)

    lines = [
        "",
        "# ppxai - AI Text UI",
        "",
        "Welcome to the AI terminal interface!",
        "",
        "Type your question or prompt to chat, or use a command:",
        "",
    ]
    for category in sorted(by_category):
        lines.append(f"## {category.title()}")
        for cmd in sorted(by_category[category], key=lambda c: c["name"]):
            usage = cmd.get("usage") or f"/{cmd['name']}"
            aliases = cmd.get("aliases") or []
            alias_str = f" *(/{', /'.join(aliases)})*" if aliases else ""
            lines.append(f"- `{usage}`{alias_str} - {cmd['description']}")
        lines.append("")
    lines.append(_SAFETY_NOTES)

    console.print(Panel(Markdown("\n".join(lines)),
                        title="Welcome", border_style="cyan"))


def display_spec_help(spec_type: str | None = None):
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


def select_model(provider: str = None) -> str | None:
    """Prompt user to select a model.

    Returns None and prints a clean exit message on Ctrl+C / EOF
    instead of dumping a stack trace.
    """
    config = get_provider_config(provider)
    models = config["models"]

    display_models(provider)

    # Default to first model if only one available
    default_choice = "1" if len(models) == 1 else "2" if "2" in models else "1"

    try:
        choice = Prompt.ask(
            "\n[bold yellow]Select a model[/bold yellow]",
            choices=list(models.keys()),
            default=default_choice
        )
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Interrupted.[/dim]")
        sys.exit(0)

    selected_model = models[choice]
    console.print(f"\n[green]Selected:[/green] {selected_model['name']}")
    return selected_model["id"]


def select_provider() -> str:
    """Prompt user to select a provider.

    Returns cleanly on Ctrl+C / EOF instead of dumping a stack trace.
    """
    table = Table(title="Available Providers", show_header=True, header_style="bold magenta")
    table.add_column("Choice", style="cyan", width=8)
    table.add_column("Provider", style="green")
    table.add_column("Endpoint", style="white")

    provider_keys = list(PROVIDERS.keys())
    for idx, key in enumerate(provider_keys, 1):
        config = PROVIDERS[key]
        table.add_row(str(idx), config["name"], config["base_url"])

    console.print(table)

    try:
        choice = Prompt.ask(
            "\n[bold yellow]Select a provider[/bold yellow]",
            choices=[str(i) for i in range(1, len(provider_keys) + 1)],
            default="1"
        )
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Interrupted.[/dim]")
        sys.exit(0)

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

    with open(USAGE_FILE, 'r', encoding="utf-8") as f:
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

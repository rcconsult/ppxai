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

from .config import MODELS, USAGE_FILE, PROVIDERS, get_provider_config
from .prompts import SPEC_GUIDELINES, SPEC_TEMPLATES

# Initialize Rich console
console = Console()


def display_welcome():
    """Display welcome message."""
    welcome_text = """
# ppxai - AI Text UI

Welcome to the AI terminal interface!

## General Commands
- Type your question or prompt to chat
- `/save [filename]` - Export conversation to markdown file
- `/sessions` - List all saved sessions
- `/load <session>` - Load a previous session
- `/usage` - Show current session usage statistics
- `/clear` - Clear conversation history
- `/model` - Change model
- `/help` - Show this help message
- `/quit` or `/exit` - Exit the application

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
- `/tools enable` - Enable AI tools (file search, calculator, etc.)
- `/tools disable` - Disable AI tools
- `/tools list` - Show available tools
- `/tools status` - Show tools status
"""
    console.print(Panel(Markdown(welcome_text), title="Welcome", border_style="cyan"))


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
        created = session['created_at'][:19] if session['created_at'] != "Unknown" else "Unknown"
        saved = session['saved_at'][:19] if session['saved_at'] != "Unknown" else "Unknown"
        table.add_row(
            session['name'],
            created,
            saved,
            str(session['message_count'])
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

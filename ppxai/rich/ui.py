"""
UI/display functions for the ppxai terminal interface.
"""

import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from ..config import PROVIDERS, get_provider_config

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



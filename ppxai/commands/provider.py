"""
Provider and model management commands.

Commands for switching providers, models, and configuring auto-routing.

v1.13.10: Migrated to Command Factory pattern
"""

from typing import TYPE_CHECKING

from .factory import CommandFactory, CommandSpec

if TYPE_CHECKING:
    from .handler import CommandHandler


def handle_model(handler: "CommandHandler", args: str) -> None:
    """Handle /model command - switch or list models.

    Args:
        handler: CommandHandler instance providing context
        args: "list" to list models, model ID to switch, or empty for interactive
    """
    from ..config import get_provider_config
    from ..ui import console, select_model

    args = args.strip().lower()

    if args == "list":
        # List available models
        config = get_provider_config(handler.provider)
        models = config.get("models", {})

        console.print(f"\n[bold cyan]Available Models ({handler.provider}):[/bold cyan]")
        for num, info in models.items():
            model_id = info.get("id", num)
            is_current = " [green]✓[/green]" if model_id == handler.current_model else ""
            console.print(f"  • [bold]{model_id}[/bold]{is_current} - {info.get('description', '')}")
        console.print()
    elif args:
        # Direct model selection by ID
        config = get_provider_config(handler.provider)
        models = config.get("models", {})

        # Find model by ID
        found = False
        for num, info in models.items():
            model_id = info.get("id", num)
            if model_id == args:
                handler.current_model = model_id
                handler.engine_client.set_model(handler.current_model)
                handler.engine_client.session.set_model(handler.current_model)
                console.print(f"[green]✓ Switched to model: {model_id}[/green]\n")
                found = True
                break

        if not found:
            console.print(f"[red]Model not found: {args}[/red]")
            console.print("[dim]Use /model list to see available models[/dim]\n")
    else:
        # Interactive selection
        handler.current_model = select_model(handler.provider)
        handler.engine_client.set_model(handler.current_model)
        handler.engine_client.session.set_model(handler.current_model)
        console.print()


def handle_provider(handler: "CommandHandler", args: str) -> None:
    """Handle /provider command - switch between providers.

    Args:
        handler: CommandHandler instance providing context
        args: "list" to list providers, provider ID to switch, or empty for interactive
    """
    from ..config import PROVIDERS, get_api_key, get_base_url, get_provider_config
    from ..ui import console, select_model, select_provider

    args = args.strip().lower()

    if args == "list":
        # List available providers
        console.print(f"\n[bold cyan]Available Providers:[/bold cyan]")
        for provider_id, config in PROVIDERS.items():
            has_key = bool(get_api_key(provider_id))
            is_current = " [green]✓[/green]" if provider_id == handler.provider else ""
            key_status = "" if has_key else " [dim](no API key)[/dim]"
            console.print(f"  • [bold]{provider_id}[/bold]{is_current} - {config.get('name', provider_id)}{key_status}")
        console.print()
        return

    if args and args != "list":
        # Direct provider selection by ID
        if args not in PROVIDERS:
            console.print(f"[red]Provider not found: {args}[/red]")
            console.print("[dim]Use /provider list to see available providers[/dim]\n")
            return

        new_provider = args
    else:
        # Interactive selection
        console.print(f"\n[cyan]Current provider:[/cyan] {handler.provider}")
        new_provider = select_provider()

    if new_provider == handler.provider:
        console.print("[dim]Same provider selected, no change needed.[/dim]\n")
        return

    # Check if new provider has API key configured
    new_api_key = get_api_key(new_provider)
    if not new_api_key:
        config = get_provider_config(new_provider)
        console.print(f"[red]Error: {config['api_key_env']} not configured.[/red]")
        console.print("[yellow]Please add the API key to your .env file.[/yellow]\n")
        return

    # Check if tools are currently enabled
    tools_were_enabled = handler.engine_client.tools_enabled

    # Switch to new provider
    new_base_url = get_base_url(new_provider)
    new_config = get_provider_config(new_provider)

    # Update handler and engine client
    handler.api_key = new_api_key
    handler.base_url = new_base_url
    handler.provider = new_provider
    handler.engine_client.set_provider(new_provider)
    handler.engine_client.session.set_provider(new_provider)

    # Select model for new provider (auto-select default if direct switch)
    if args:
        handler.current_model = new_config.get("default_model", "")
    else:
        handler.current_model = select_model(new_provider)
    handler.engine_client.set_model(handler.current_model)
    handler.engine_client.session.set_model(handler.current_model)

    console.print(f"\n[green]Switched to:[/green] {new_config['name']} (model: {handler.current_model})")

    # Re-enable tools if they were enabled before switching
    if tools_were_enabled:
        console.print("[dim]Re-enabling tools for new provider...[/dim]")
        handler._enable_tools()
    else:
        console.print()


def handle_autoroute(handler: "CommandHandler", args: str) -> None:
    """Handle /autoroute command - toggle auto-routing to coding model.

    Args:
        handler: CommandHandler instance providing context
        args: "on" to enable, "off" to disable, or empty for status
    """
    from ..config import get_coding_model
    from ..ui import console

    coding_model = get_coding_model(handler.provider)

    if not args:
        status = "enabled" if handler.auto_route else "disabled"
        console.print(f"\n[cyan]Auto-routing is currently:[/cyan] [bold]{status}[/bold]")
        console.print(f"[dim]Auto-routing uses {coding_model} for coding commands[/dim]")
        console.print("[yellow]Use /autoroute on or /autoroute off to change[/yellow]\n")
        return

    arg = args.strip().lower()
    if arg == "on":
        handler.auto_route = True
        console.print(f"[green]Auto-routing enabled.[/green] Coding commands will use {coding_model}\n")
    elif arg == "off":
        handler.auto_route = False
        console.print(f"[yellow]Auto-routing disabled.[/yellow] Manual model selection will be used\n")
    else:
        console.print("[red]Invalid option. Use /autoroute on or /autoroute off[/red]\n")


# =============================================================================
# Command Registration
# =============================================================================

CommandFactory.register(CommandSpec(
    name="model",
    description="Switch or list models",
    handler=handle_model,
    category="provider",
    aliases=["m"],
    usage="/model [list|<model_id>]"
))

CommandFactory.register(CommandSpec(
    name="provider",
    description="Switch between AI providers",
    handler=handle_provider,
    category="provider",
    aliases=["p"],
    usage="/provider [list|<provider_id>]"
))

CommandFactory.register(CommandSpec(
    name="autoroute",
    description="Toggle auto-routing to coding model",
    handler=handle_autoroute,
    category="provider",
    usage="/autoroute [on|off]"
))

"""
System commands - help, status, theme, and configuration.

Commands for displaying help, status, themes, and system configuration.

v1.13.10: Migrated to Command Factory pattern
"""

from typing import TYPE_CHECKING

from .factory import CommandFactory, CommandSpec

if TYPE_CHECKING:
    from .handler import CommandHandler


def handle_help(handler: "CommandHandler", args: str) -> None:
    """Handle /help command - display help information.

    Args:
        handler: CommandHandler instance providing context
        args: Command arguments (unused)
    """
    from ..ui import display_welcome

    display_welcome()


def handle_theme(handler: "CommandHandler", args: str) -> None:
    """Handle /theme command - switch TUI themes and emoji mode.

    Args:
        handler: CommandHandler instance providing context
        args: "list" to list, theme name to switch, "emoji on/off" for emoji mode
    """
    from ..themes import get_theme
    from ..ui import console
    from ..ui_components import render_theme_list

    args = args.strip().lower() if args else ""

    # Handle emoji subcommand
    if args.startswith("emoji"):
        emoji_args = args[5:].strip()  # Get text after "emoji"

        if not emoji_args:
            # Show current emoji mode
            mode = "on (original emojis)" if handler.emoji_mode else "off (text symbols)"
            console.print(f"[cyan]Emoji mode:[/cyan] {mode}")
            console.print("[dim]Use /theme emoji on|off to change[/dim]\n")
            return

        if emoji_args == "on":
            handler.emoji_mode = True
            console.print("[green]* Emoji mode: ON[/green]")
            console.print("[dim]Original emojis will be shown (may cause panel misalignment in some terminals)[/dim]\n")
        elif emoji_args == "off":
            handler.emoji_mode = False
            console.print("[green]* Emoji mode: OFF[/green]")
            console.print("[dim]Emojis converted to text symbols for reliable panel alignment[/dim]\n")
        else:
            console.print("[red]Invalid option. Use: /theme emoji on|off[/red]\n")
        return

    if not args or args == "list":
        # Show available themes and current settings
        console.print(render_theme_list(handler.current_theme_name))
        emoji_status = "on" if handler.emoji_mode else "off"
        console.print(f"[dim]Emoji mode: {emoji_status}[/dim]")
        console.print("[dim]Usage: /theme <name> | /theme emoji on|off[/dim]\n")
        return

    # Try to switch to the specified theme
    try:
        new_theme = get_theme(args)
        handler.theme = new_theme
        handler.current_theme_name = args
        console.print(f"[green]* Theme switched to: {new_theme.name}[/green]\n")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        console.print("[dim]Use /theme list to see available themes[/dim]\n")


def handle_status(handler: "CommandHandler", args: str) -> None:
    """Handle /status command - show comprehensive status information.

    Args:
        handler: CommandHandler instance providing context
        args: "version", "cwd", or "datetime" to toggle display settings
    """
    from ..config import get_provider_config, get_tui_config, set_tui_config
    from ..ui import console
    from ..version import __version__

    parts = args.strip().split() if args else []

    # Handle toggle subcommands
    if parts:
        subcommand = parts[0].lower()
        if subcommand in ("version", "cwd", "datetime"):
            # Toggle the setting
            tui_config = get_tui_config()
            key = f"show_{subcommand}"
            current_value = tui_config.get(key, subcommand != "datetime")
            new_value = not current_value

            if set_tui_config(key, new_value):
                status = "[green]enabled[/green]" if new_value else "[dim]disabled[/dim]"
                console.print(f"\n[cyan]{key}:[/cyan] {status}")
                console.print("[dim]Setting saved to config file.[/dim]\n")
            else:
                console.print(f"\n[red]Failed to save setting.[/red]")
                console.print(f"[dim]Try manually editing ppxai-config.json: \"tui\": {{ \"{key}\": {str(new_value).lower()} }}[/dim]\n")
            return

    # Show comprehensive status
    console.print("\n[bold cyan]━━━ ppxai Status ━━━[/bold cyan]")

    # Version
    console.print(f"  [cyan]Version:[/cyan] v{__version__}")

    # Provider and model
    provider_config = get_provider_config(handler.provider)
    console.print(f"  [cyan]Provider:[/cyan] {provider_config.get('name', handler.provider)}")
    console.print(f"  [cyan]Model:[/cyan] {handler.current_model}")

    # Working directory
    if handler.engine_client:
        cwd = handler.engine_client.get_working_dir() or "[dim]not set[/dim]"
        console.print(f"  [cyan]Working Dir:[/cyan] {cwd}")

    # Tools status
    tools_status = "[green]enabled[/green]" if (handler.engine_client and handler.engine_client.tools_enabled) else "[dim]disabled[/dim]"
    console.print(f"  [cyan]Tools:[/cyan] {tools_status}")

    # Agent mode
    agent_status = "[green]active[/green]" if (handler.engine_client and handler.engine_client.agent_mode) else "[dim]inactive[/dim]"
    console.print(f"  [cyan]Agent Mode:[/cyan] {agent_status}")

    # Theme
    console.print(f"  [cyan]Theme:[/cyan] {handler.current_theme_name}")

    # Session info
    if handler.engine_client and handler.engine_client.session:
        session = handler.engine_client.session
        msg_count = len(session.get_messages())
        console.print(f"  [cyan]Messages:[/cyan] {msg_count}")

        # Usage stats
        total_usage = session.get_usage()
        if total_usage:
            console.print(f"  [cyan]Tokens:[/cyan] {total_usage.get('prompt_tokens', 0)}↓ / {total_usage.get('completion_tokens', 0)}↑")
            cost = total_usage.get('estimated_cost', 0.0)
            if cost > 0:
                console.print(f"  [cyan]Cost:[/cyan] ${cost:.4f}")

    # Status bar display settings
    tui_config = get_tui_config()
    console.print("\n[bold dim]Status Bar Settings:[/bold dim]")
    console.print(f"  show_version: {'[green]true[/green]' if tui_config.get('show_version', True) else '[dim]false[/dim]'}")
    console.print(f"  show_cwd: {'[green]true[/green]' if tui_config.get('show_cwd', True) else '[dim]false[/dim]'}")
    console.print(f"  show_datetime: {'[green]true[/green]' if tui_config.get('show_datetime', False) else '[dim]false[/dim]'}")

    console.print()


def handle_spec(handler: "CommandHandler", args: str) -> None:
    """Handle /spec command - display specification templates.

    Args:
        handler: CommandHandler instance providing context
        args: Spec type (api, cli, lib, algo, ui) or empty for list
    """
    from ..ui import display_spec_help

    spec_type = args.strip().lower() if args else None
    display_spec_help(spec_type)


# =============================================================================
# Command Registration
# =============================================================================

CommandFactory.register(CommandSpec(
    name="help",
    description="Show help and available commands",
    handler=handle_help,
    category="system",
    aliases=["h", "?"],
    usage="/help"
))

CommandFactory.register(CommandSpec(
    name="theme",
    description="Switch TUI theme or emoji mode",
    handler=handle_theme,
    category="system",
    usage="/theme [list|<name>|emoji on|off]"
))

CommandFactory.register(CommandSpec(
    name="status",
    description="Show status information",
    handler=handle_status,
    category="system",
    usage="/status [version|cwd|datetime]"
))

CommandFactory.register(CommandSpec(
    name="spec",
    description="Show specification templates",
    handler=handle_spec,
    category="system",
    usage="/spec [api|cli|lib|algo|ui]"
))

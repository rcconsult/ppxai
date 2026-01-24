"""
Utility commands - navigation, config, debugging, and context management.

Commands for directory navigation, configuration management, debug logging,
and context window management.

v1.13.10: Migrated to Command Factory pattern
"""

import os
from typing import TYPE_CHECKING

from .factory import CommandFactory, CommandSpec

if TYPE_CHECKING:
    from .handler import CommandHandler


def handle_cd(handler: "CommandHandler", args: str) -> None:
    """Handle /cd command - change working directory.

    Args:
        handler: CommandHandler instance providing context
        args: Directory path to change to (empty shows current)
    """
    from ..rich.ui import console

    if not handler.engine_client:
        console.print("[red]Error: Engine client not available[/red]\n")
        return

    if not args.strip():
        # No args - show current directory
        handle_pwd(handler, "")
        return

    target_path = args.strip()

    try:
        # Expand ~ and resolve path
        expanded = os.path.expanduser(target_path)
        resolved = os.path.abspath(expanded)

        if not os.path.isdir(resolved):
            console.print(f"[red]Not a valid directory: {target_path}[/red]\n")
            return

        handler.engine_client.set_working_dir(resolved)
        console.print(f"\n[green]Working directory changed to:[/green] {resolved}\n")

    except Exception as e:
        console.print(f"[red]Error changing directory: {e}[/red]\n")


def handle_pwd(handler: "CommandHandler", args: str) -> None:
    """Handle /pwd command - show current working directory.

    Args:
        handler: CommandHandler instance providing context
        args: Command arguments (unused)
    """
    from ..rich.ui import console

    if not handler.engine_client:
        console.print("[red]Error: Engine client not available[/red]\n")
        return

    cwd = handler.engine_client.get_working_dir()
    if cwd:
        console.print(f"\n[cyan]Current working directory:[/cyan] {cwd}\n")
    else:
        console.print("\n[yellow]Working directory not set.[/yellow]\n")


def handle_config(handler: "CommandHandler", args: str) -> None:
    """Handle /config command - configuration management.

    Args:
        handler: CommandHandler instance providing context
        args: "reload" to reload, "path" to show path
    """
    from ..config import find_config_file, reload_config
    from ..rich.ui import console

    parts = args.strip().split() if args else []

    if not parts:
        console.print("\n[cyan]Config Commands:[/cyan]")
        console.print("  /config reload  - Reload config from file")
        console.print("  /config path    - Show config file path\n")
        return

    subcommand = parts[0].lower()

    if subcommand == "reload":
        try:
            reload_config()
            console.print("\n[green]Configuration reloaded successfully.[/green]")
            console.print("[dim]Provider prompts and settings updated from config file.[/dim]\n")
        except Exception as e:
            console.print(f"\n[red]Failed to reload config: {e}[/red]\n")

    elif subcommand == "path":
        config_path = find_config_file()
        if config_path:
            console.print(f"\n[cyan]Config file:[/cyan] {config_path}\n")
        else:
            console.print("\n[dim]No config file found. Using defaults.[/dim]\n")

    else:
        console.print(f"[red]Unknown subcommand: {subcommand}[/red]")
        console.print("[dim]Available: reload, path[/dim]\n")


def handle_debug_log(handler: "CommandHandler", args: str) -> None:
    """Handle /debug-log command - enable/disable debug logging.

    Args:
        handler: CommandHandler instance providing context
        args: "on" to enable, "off" to disable, "show" to view, "clear" to reset
    """
    from pathlib import Path

    from ..common.logger import get_logger
    from ..rich.ui import console

    logger = get_logger("tui")

    if not args:
        # Show status
        status = "enabled" if logger.enabled else "disabled"
        log_file = Path.home() / '.ppxai' / 'logs' / 'tui-debug.log'
        console.print(f"\n[bold]Debug Logging Status:[/bold] {status}")
        if logger.enabled:
            console.print(f"[dim]Log file: {log_file}[/dim]")
            console.print("[dim]Use '/debug-log off' to disable[/dim]\n")
        else:
            console.print(f"[dim]Log file: {log_file}[/dim]")
            console.print("[dim]Use '/debug-log on' to enable[/dim]")
            console.print("[dim]Or set PPXAI_DEBUG=1 environment variable[/dim]\n")
        return

    cmd = args.strip().lower()

    if cmd in ["on", "enable", "1", "true", "yes"]:
        logger.enable()
        log_file = Path.home() / '.ppxai' / 'logs' / 'tui-debug.log'
        console.print("[green]Debug logging enabled[/green]")
        console.print(f"[dim]Logs will be written to: {log_file}[/dim]")
        console.print("[dim]All message flow, API requests, and tool executions will be logged[/dim]\n")
    elif cmd in ["off", "disable", "0", "false", "no"]:
        logger.disable()
        console.print("[yellow]Debug logging disabled[/yellow]\n")
    elif cmd in ["show", "view", "cat"]:
        # Show recent log entries
        log_file = Path.home() / '.ppxai' / 'logs' / 'tui-debug.log'
        if not log_file.exists():
            console.print("[yellow]No log file found[/yellow]\n")
            return

        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
                # Show last 50 lines
                recent_lines = lines[-50:]
                console.print(f"\n[bold]Recent debug log entries:[/bold] (last 50 lines)\n")
                for line in recent_lines:
                    console.print(line.rstrip())
                console.print()
        except Exception as e:
            console.print(f"[red]Error reading log file: {e}[/red]\n")
    elif cmd in ["clear", "clean", "reset"]:
        # Clear log file
        log_file = Path.home() / '.ppxai' / 'logs' / 'tui-debug.log'
        if log_file.exists():
            log_file.unlink()
            console.print("[green]Debug log cleared[/green]\n")
        else:
            console.print("[yellow]No log file to clear[/yellow]\n")
    else:
        console.print(f"[red]Unknown command: {cmd}[/red]")
        console.print("[yellow]Usage: /debug-log [on|off|show|clear][/yellow]\n")


def _show_active_hints(handler: "CommandHandler", console) -> None:
    """Display active bootstrap hints for current provider/model (v1.14.0)."""
    from pathlib import Path

    hints_info = handler.engine_client.get_active_hints()

    if not hints_info["loaded"]:
        console.print("\n[yellow]No bootstrap context loaded.[/yellow]")
        cwd = handler.engine_client.get_working_dir() or "unknown"
        console.print(f"[dim]Working directory: {cwd}[/dim]")
        console.print("[dim]Create AGENTS.md or CLAUDE.md in your project directory,[/dim]")
        console.print("[dim]or use /cd <path> to navigate to a directory with one.[/dim]\n")
        return

    console.print("\n[bold cyan]━━━ Active Bootstrap Hints ━━━[/bold cyan]")

    # Source file
    source_name = Path(hints_info["source"]).name
    console.print(f"  [cyan]Source:[/cyan] {hints_info['source']}")

    # Current provider/model
    console.print(f"  [cyan]Provider:[/cyan] {hints_info['provider']}")
    console.print(f"  [cyan]Model:[/cyan] {hints_info['model']}")

    # Provider hints
    provider_hints = hints_info["provider_hints"]
    if provider_hints:
        console.print(f"\n[cyan]Provider Hints:[/cyan] ({len(provider_hints)} active)")
        if hints_info["inherited_local"]:
            console.print("  [dim](includes inherited 'local' hints)[/dim]")
        for source, hint in provider_hints:
            # Truncate long hints for display
            display_hint = hint[:80] + "..." if len(hint) > 80 else hint
            console.print(f"  [green]•[/green] [{source}] {display_hint}")
    else:
        console.print(f"\n[cyan]Provider Hints:[/cyan] [dim]none active[/dim]")
        available = hints_info["all_provider_keys"]
        if available:
            console.print(f"  [dim]Available: {', '.join(available)}[/dim]")

    # Model hints
    model_hints = hints_info["model_hints"]
    if model_hints:
        patterns = hints_info["matched_patterns"]
        console.print(f"\n[cyan]Model Hints:[/cyan] ({len(model_hints)} active)")
        console.print(f"  [dim]Matched patterns: {', '.join(patterns)}[/dim]")
        for pattern, hint in model_hints:
            display_hint = hint[:80] + "..." if len(hint) > 80 else hint
            console.print(f"  [green]•[/green] [{pattern}] {display_hint}")
    else:
        console.print(f"\n[cyan]Model Hints:[/cyan] [dim]none active[/dim]")
        available = hints_info["all_model_patterns"]
        if available:
            console.print(f"  [dim]Available patterns: {', '.join(available)}[/dim]")

    # Summary
    total_hints = len(provider_hints) + len(model_hints)
    console.print(f"\n[dim]Total active hints: {total_hints}[/dim]")
    console.print("[dim]Use /context to see full context usage[/dim]\n")


def _show_bootstrap_hierarchy(handler: "CommandHandler", console) -> None:
    """Display bootstrap context hierarchy with scope information (v1.14.2)."""
    from pathlib import Path

    status = handler.engine_client.get_bootstrap_status()

    if not status["loaded"]:
        console.print("\n[yellow]No bootstrap context loaded.[/yellow]")
        cwd = handler.engine_client.get_working_dir() or "unknown"
        console.print(f"[dim]Working directory: {cwd}[/dim]")
        console.print("\n[dim]Scope search order:[/dim]")
        console.print("  [dim]1. ~/.ppxai/AGENTS.md (global)[/dim]")
        console.print("  [dim]2. {git_root}/AGENTS.md (project)[/dim]")
        console.print("  [dim]3. {cwd}/AGENTS.md (subdir)[/dim]")
        console.print("\n[dim]Create AGENTS.md or CLAUDE.md in any of these locations.[/dim]\n")
        return

    console.print("\n[bold cyan]━━━ Bootstrap Context ━━━[/bold cyan]")

    # Show sources with scope labels
    sources = status.get("sources", [])
    total_size = status.get("total_size", 0)

    console.print(f"\n[cyan]Sources:[/cyan] ({len(sources)} file{'s' if len(sources) != 1 else ''})")

    for i, src in enumerate(sources, 1):
        path = src["path"]
        scope = src["scope"]
        size_kb = src["size"] / 1024

        # Color-code by scope
        scope_color = {
            "global": "blue",
            "project": "green",
            "subdir": "yellow",
        }.get(scope, "white")

        console.print(f"  {i}. {path}")
        console.print(f"     [{scope_color}][{scope}][/{scope_color}] {size_kb:.1f} KB")

    # Total size
    total_kb = total_size / 1024
    estimated_tokens = status.get("char_count", 0) // 4  # Rough estimate
    console.print(f"\n[cyan]Total:[/cyan] {total_kb:.1f} KB (~{estimated_tokens:,} tokens)")

    # Show hints summary
    if status.get("has_hints"):
        provider_hints = status.get("provider_hints", [])
        model_hints = status.get("model_hints", [])
        console.print(f"\n[cyan]Hints Defined:[/cyan]")
        if provider_hints:
            console.print(f"  Provider: {', '.join(provider_hints)}")
        if model_hints:
            console.print(f"  Model: {', '.join(model_hints)}")
    else:
        console.print(f"\n[cyan]Hints:[/cyan] [dim]none defined[/dim]")

    # Tips
    console.print("\n[dim]Tips:[/dim]")
    console.print("  [dim]- /context hints - See active hints for current provider/model[/dim]")
    console.print("  [dim]- /context reload - Refresh from disk[/dim]\n")


def handle_context(handler: "CommandHandler", args: str) -> None:
    """Handle /context command - context usage information.

    Args:
        handler: CommandHandler instance providing context
        args: "clear" to remove injected content, "hints" to show active hints,
              "show" to display bootstrap context hierarchy (v1.14.2)
    """
    from ..rich.ui import console

    if not handler.engine_client:
        console.print("[red]Error: Engine client not available[/red]\n")
        return

    parts = args.strip().split() if args else []

    if parts and parts[0].lower() == "clear":
        # Clear injected contexts
        removed = handler.engine_client.clear_injected_contexts()
        if removed > 0:
            console.print(f"\n[green]Cleared {removed} injected context(s) from history.[/green]")
            # Show updated usage
            info = handler.engine_client.get_context_info()
            console.print(f"[dim]New estimated usage: ~{info['estimated_tokens']:,} tokens ({info['usage_percent']:.0f}%)[/dim]\n")
        else:
            console.print("\n[yellow]No injected contexts to clear.[/yellow]\n")
        return

    if parts and parts[0].lower() == "hints":
        # Show active bootstrap hints (v1.14.0)
        _show_active_hints(handler, console)
        return

    if parts and parts[0].lower() == "show":
        # Show bootstrap context hierarchy (v1.14.2)
        _show_bootstrap_hierarchy(handler, console)
        return

    if parts and parts[0].lower() == "reload":
        # Reload bootstrap context from disk (v1.14.1)
        if handler.engine_client.reload_bootstrap_context():
            status = handler.engine_client.get_bootstrap_status()
            sources = status.get('sources', [])
            char_count = status.get('char_count', 0)
            console.print(f"\n[green]✓ Bootstrap context reloaded[/green]")
            if len(sources) > 1:
                console.print(f"  [dim]Merged {len(sources)} files[/dim]")
            for src in sources:
                console.print(f"  [dim]{src['path']} [{src['scope']}][/dim]")
            console.print(f"  [dim]Total: {char_count:,} chars[/dim]\n")
        else:
            console.print("\n[yellow]No bootstrap context file found[/yellow]")
            console.print("  [dim]Looking for: AGENTS.md, CLAUDE.md[/dim]")
            console.print("  [dim]Searched: ~/.ppxai/, git root, working dir[/dim]\n")
        return

    # Show context usage info
    info = handler.engine_client.get_context_info()

    console.print("\n[cyan]Context Usage:[/cyan]")
    console.print(f"  Estimated: ~{info['estimated_tokens']:,} / {info['context_limit']:,} tokens ({info['usage_percent']:.1f}%)")
    console.print(f"  Model: {info['model']} ({info['provider']})")
    console.print(f"  Messages: {info['message_count']}")

    # Show progress bar
    pct = min(info['usage_percent'], 100)
    bar_width = 30
    filled = int(bar_width * pct / 100)
    bar = "[green]" + "#" * filled + "[/green]" + "[dim]-[/dim]" * (bar_width - filled)
    if pct >= 80:
        bar = "[yellow]" + "#" * filled + "[/yellow]" + "[dim]-[/dim]" * (bar_width - filled)
    if pct >= 95:
        bar = "[red]" + "#" * filled + "[/red]" + "[dim]-[/dim]" * (bar_width - filled)
    console.print(f"  [{bar}] {pct:.0f}%")

    # Show injected contexts
    injected = info.get('injected_contexts', [])
    if injected:
        console.print(f"\n[cyan]Injected Contexts:[/cyan] ({info['injected_tokens']:,} tokens)")
        for ctx in injected:
            size_kb = ctx['size'] / 1024
            truncated = " [yellow](truncated)[/yellow]" if ctx.get('truncated') else ""
            console.print(f"  {ctx['source']}: {size_kb:.1f} KB{truncated}")

    # Show tips
    console.print("\n[dim]Tips:[/dim]")
    if injected:
        console.print("  [dim]- /context clear - Remove injected files, keep chat[/dim]")
    console.print("  [dim]- /new - Start fresh session[/dim]")
    console.print("  [dim]- /save - Save session before clearing[/dim]")
    if info['usage_percent'] >= 80:
        console.print("  [dim]- Consider switching to a model with larger context[/dim]")
    console.print()


# =============================================================================
# Command Registration
# =============================================================================

CommandFactory.register(CommandSpec(
    name="cd",
    description="Change working directory",
    handler=handle_cd,
    category="navigation",
    usage="/cd <path>"
))

CommandFactory.register(CommandSpec(
    name="pwd",
    description="Show current working directory",
    handler=handle_pwd,
    category="navigation",
    usage="/pwd"
))

CommandFactory.register(CommandSpec(
    name="config",
    description="Configuration management",
    handler=handle_config,
    category="utility",
    usage="/config [reload|path]"
))

CommandFactory.register(CommandSpec(
    name="debug-log",
    description="Enable/disable debug logging",
    handler=handle_debug_log,
    category="utility",
    usage="/debug-log [on|off|show|clear]"
))

CommandFactory.register(CommandSpec(
    name="context",
    description="Show context usage, hints, and manage injected files",
    handler=handle_context,
    category="utility",
    usage="/context [clear|hints|show|reload]"
))

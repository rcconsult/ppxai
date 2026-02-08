"""
Utility commands - navigation, config, debugging, and context management.

Commands for directory navigation, configuration management, debug logging,
and context window management.

v1.13.10: Migrated to Command Factory pattern
v1.15.0: Migrated to type-based renderer dispatch
"""

import os
from typing import TYPE_CHECKING

from .factory import CommandFactory, CommandSpec
from .protocol import CommandContext
from .results import (
    ResultStatus,
    CommandResult,
    ConfirmationResult,
    KeyValueResult,
    ErrorResult,
    TreeResult,
    TextResult,
    FileViewResult,
)

if TYPE_CHECKING:
    from .handler import CommandHandler


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


def handle_cd(context: CommandContext, args: str) -> CommandResult:
    """Handle /cd command - change working directory.

    Args:
        context: Command context providing access to engine client
        args: Directory path to change to (empty shows current)

    Returns:
        ConfirmationResult on success, KeyValueResult if no args, ErrorResult on failure
    """
    if not context.engine_client:
        return ErrorResult(status=ResultStatus.ERROR, message="Engine client not available")

    if not args.strip():
        # No args - show current directory (delegate to pwd)
        return handle_pwd(context, "")

    target_path = args.strip()

    try:
        # Expand ~ and resolve path
        expanded = os.path.expanduser(target_path)

        # Resolve relative paths against engine client's working directory, not OS cwd
        if os.path.isabs(expanded):
            resolved = expanded
        else:
            current_wd = context.engine_client.get_working_dir() or os.getcwd()
            resolved = os.path.normpath(os.path.join(current_wd, expanded))

        if not os.path.isdir(resolved):
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=f"Not a valid directory: {target_path}",
                suggestions=["Check the path and try again"]
            )

        context.engine_client.set_working_dir(resolved)
        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message=f"Working directory changed to: {resolved}",
            details={"working_dir": resolved}
        )

    except Exception as e:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Error changing directory: {e}",
            error_details=str(e)
        )


def handle_pwd(context: CommandContext, args: str) -> CommandResult:
    """Handle /pwd command - show current working directory.

    Args:
        context: Command context providing access to engine client
        args: Command arguments (unused)

    Returns:
        KeyValueResult with current working directory, or ErrorResult
    """
    if not context.engine_client:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Engine client not available"
        )

    cwd = context.engine_client.get_working_dir()
    if cwd:
        return KeyValueResult(
            status=ResultStatus.SUCCESS,
            message="Current working directory",
            pairs={"Working Directory": cwd}
        )
    else:
        return KeyValueResult(
            status=ResultStatus.WARNING,
            message="Working directory not set",
            pairs={"Status": "Not set"}
        )


def handle_config(context: CommandContext, args: str) -> CommandResult:
    """Handle /config command - configuration management.

    Args:
        context: Command context providing access to engine client
        args: "reload" to reload, "path" to show path

    Returns:
        KeyValueResult for path/help, ConfirmationResult for reload, ErrorResult on failure
    """
    from ..config import find_config_file, reload_config

    parts = args.strip().split() if args else []

    if not parts:
        return KeyValueResult(
            status=ResultStatus.INFO,
            message="Config Commands",
            pairs={
                "/config reload": "Reload config from file",
                "/config path": "Show config file path"
            }
        )

    subcommand = parts[0].lower()

    if subcommand == "reload":
        try:
            # Reload config store and refresh engine client's cached providers
            if context.engine_client:
                context.engine_client.reload_config()
            else:
                reload_config()
            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message="Configuration reloaded successfully. Provider prompts and settings updated from config file.",
                details={"config_reloaded": True}
            )
        except Exception as e:
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=f"Failed to reload config: {e}",
                error_details=str(e)
            )

    elif subcommand == "path":
        config_path = find_config_file()
        if config_path:
            return KeyValueResult(
                status=ResultStatus.SUCCESS,
                message="Config file location",
                pairs={"Config file": str(config_path)}
            )
        else:
            return KeyValueResult(
                status=ResultStatus.INFO,
                message="No config file found",
                pairs={"Status": "Using defaults"}
            )

    else:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Unknown subcommand: {subcommand}",
            suggestions=["Available: reload, path"]
        )


def handle_debug_log(context: CommandContext, args: str) -> CommandResult:
    """Handle /debug-log command - enable/disable debug logging.

    Args:
        context: Command context providing access to engine client
        args: "on" to enable, "off" to disable, "show" to view, "clear" to reset

    Returns:
        Appropriate CommandResult based on subcommand
    """
    from pathlib import Path
    from ..common.logger import get_logger

    logger = get_logger("tui")
    log_file = Path.home() / '.ppxai' / 'logs' / 'tui-debug.log'

    if not args:
        # Show status
        status = "enabled" if logger.enabled else "disabled"
        pairs = {
            "Status": status,
            "Log file": str(log_file)
        }
        if logger.enabled:
            pairs["To disable"] = "/debug-log off"
        else:
            pairs["To enable"] = "/debug-log on"
            pairs["Alternative"] = "Set PPXAI_DEBUG=1 environment variable"

        return KeyValueResult(
            status=ResultStatus.INFO if logger.enabled else ResultStatus.WARNING,
            message="Debug Logging Status",
            pairs=pairs
        )

    cmd = args.strip().lower()

    if cmd in ["on", "enable", "1", "true", "yes"]:
        logger.enable()
        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message=f"Debug logging enabled. Logs will be written to: {log_file}. All message flow, API requests, and tool executions will be logged.",
            details={"log_file": str(log_file), "enabled": True}
        )
    elif cmd in ["off", "disable", "0", "false", "no"]:
        logger.disable()
        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message="Debug logging disabled",
            details={"enabled": False}
        )
    elif cmd in ["show", "view", "cat"]:
        # Show recent log entries
        if not log_file.exists():
            return ErrorResult(status=ResultStatus.ERROR, message="No log file found")

        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
                # Show last 50 lines
                recent_lines = lines[-50:]
                content = ''.join(recent_lines)

                # Use FileViewResult for proper log display (Phase 2.3)
                return FileViewResult(
                    status=ResultStatus.INFO,
                    message=f"Debug log (last 50 lines)",
                    filepath=str(log_file),
                    content=content,
                    language="log",
                    read_only=True
                )
        except Exception as e:
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=f"Error reading log file: {e}",
                error_details=str(e)
            )
    elif cmd in ["clear", "clean", "reset"]:
        # Clear log file
        if log_file.exists():
            log_file.unlink()
            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message="Debug log cleared",
                details={"log_file": str(log_file)}
            )
        else:
            return ErrorResult(status=ResultStatus.ERROR, message="No log file to clear")
    else:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Unknown command: {cmd}",
            suggestions=["Usage: /debug-log [on|off|show|clear]"]
        )


def handle_context(context: CommandContext, args: str) -> CommandResult:
    """Handle /context command - context usage information.

    Args:
        context: Command context providing access to engine client
        args: "clear", "hints", "show", or "reload"

    Returns:
        Appropriate CommandResult based on subcommand
    """
    from pathlib import Path

    if not context.engine_client:
        return ErrorResult(status=ResultStatus.ERROR, message="Engine client not available")

    parts = args.strip().split() if args else []

    if parts and parts[0].lower() == "clear":
        # Clear injected contexts
        removed = context.engine_client.clear_injected_contexts()
        if removed > 0:
            info = context.engine_client.get_context_info()
            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message=f"Cleared {removed} injected context(s) from history. New estimated usage: ~{info['estimated_tokens']:,} tokens ({info['usage_percent']:.0f}%)",
                details={
                    "removed": removed,
                    "estimated_tokens": info['estimated_tokens'],
                    "usage_percent": info['usage_percent']
                }
            )
        else:
            return ErrorResult(status=ResultStatus.ERROR, message="No injected contexts to clear")

    if parts and parts[0].lower() == "hints":
        # Show active bootstrap hints (v1.14.0)
        hints_info = context.engine_client.get_active_hints()

        if not hints_info["loaded"]:
            cwd = context.engine_client.get_working_dir() or "unknown"
            return KeyValueResult(
                status=ResultStatus.WARNING,
                message="No bootstrap context loaded",
                pairs={
                    "Working directory": cwd,
                    "Hint": "Create AGENTS.md or CLAUDE.md in your project directory"
                }
            )

        # Build pairs for display
        pairs = {
            "Source": hints_info["source"],
            "Provider": hints_info["provider"],
            "Model": hints_info["model"]
        }

        provider_hints = hints_info["provider_hints"]
        model_hints = hints_info["model_hints"]

        if provider_hints:
            pairs["Provider Hints"] = f"{len(provider_hints)} active"
            if hints_info["inherited_local"]:
                pairs["Inherited"] = "includes 'local' hints"
        else:
            pairs["Provider Hints"] = "none active"

        if model_hints:
            pairs["Model Hints"] = f"{len(model_hints)} active"
        else:
            pairs["Model Hints"] = "none active"

        total_hints = len(provider_hints) + len(model_hints)
        pairs["Total Active"] = str(total_hints)

        return KeyValueResult(
            status=ResultStatus.SUCCESS,
            message="Active Bootstrap Hints",
            pairs=pairs
        )

    if parts and parts[0].lower() == "show":
        # Show bootstrap context hierarchy (v1.14.2)
        status = context.engine_client.get_bootstrap_status()

        if not status["loaded"]:
            cwd = context.engine_client.get_working_dir() or "unknown"
            return KeyValueResult(
                status=ResultStatus.WARNING,
                message="No bootstrap context loaded",
                pairs={
                    "Working directory": cwd,
                    "Search order": "~/.ppxai/AGENTS.md (global), {git_root}/AGENTS.md (project), {cwd}/AGENTS.md (subdir)",
                    "Hint": "Create AGENTS.md or CLAUDE.md in any of these locations"
                }
            )

        # Build tree structure for sources
        sources = status.get("sources", [])
        total_size = status.get("total_size", 0)

        # Create tree result
        children = []
        for src in sources:
            path = src["path"]
            scope = src["scope"]
            size_kb = src["size"] / 1024
            children.append({
                "label": f"{path} [{scope}] {size_kb:.1f} KB",
                "children": []
            })

        root = {
            "label": f"Bootstrap Context ({len(sources)} files, {total_size/1024:.1f} KB)",
            "children": children
        }

        return TreeResult(
            status=ResultStatus.SUCCESS,
            message="Bootstrap Context Hierarchy",
            root=root
        )

    if parts and parts[0].lower() == "reload":
        # Reload bootstrap context from disk (v1.14.1)
        if context.engine_client.reload_bootstrap_context():
            status = context.engine_client.get_bootstrap_status()
            sources = status.get('sources', [])
            char_count = status.get('char_count', 0)

            details = {
                "sources": [src['path'] for src in sources],
                "char_count": char_count
            }

            message = "Bootstrap context reloaded"
            if len(sources) > 1:
                message += f" (merged {len(sources)} files)"

            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message=message,
                details=details
            )
        else:
            return ErrorResult(
                status=ResultStatus.ERROR,
                message="No bootstrap context file found",
                error_details="Looking for: AGENTS.md, CLAUDE.md in ~/.ppxai/, git root, working dir"
            )

    # Show context usage info (default)
    info = context.engine_client.get_context_info()

    pairs = {
        "Estimated": f"~{info['estimated_tokens']:,} / {info['context_limit']:,} tokens ({info['usage_percent']:.1f}%)",
        "Model": f"{info['model']} ({info['provider']})",
        "Messages": str(info['message_count'])
    }

    # Show injected contexts
    injected = info.get('injected_contexts', [])
    if injected:
        pairs["Injected Contexts"] = f"{info['injected_tokens']:,} tokens"

    # Add tips based on usage
    if injected:
        pairs["Tip"] = "/context clear to remove injected files"
    if info['usage_percent'] >= 80:
        pairs["Warning"] = "Consider switching to a model with larger context"

    return KeyValueResult(
        status=ResultStatus.SUCCESS if info['usage_percent'] < 80 else ResultStatus.WARNING,
        message="Context Usage",
        pairs=pairs
    )


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

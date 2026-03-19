"""
Tools and usage commands - tool management and usage statistics.

Commands for enabling/disabling tools, tool configuration, and usage tracking.

v1.13.10: Migrated to Command Factory pattern
v1.15.0: Migrated to type-based renderer dispatch
"""

from typing import List

from ..config import get_model_context_limit, get_max_injection_size
from ..engine.tools.builtin import web_premium
from ..usage import get_usage_report
from .factory import CommandFactory, CommandSpec
from .protocol import CommandContext
from .results import (
    ResultStatus,
    CommandResult,
    ConfirmationResult,
    TableResult,
    KeyValueResult,
    ErrorResult,
    NotificationResult,
    TextResult,
)


# =============================================================================
# Type-Based Result Handlers (v1.15.0)
# =============================================================================

def handle_tools(context: CommandContext, args: str) -> CommandResult:
    """Handle /tools command for tool management.

    Subcommands:
        /tools status    - Show tools status (default)
        /tools on/enable - Enable tools
        /tools off/disable - Disable tools
        /tools list      - List available tools
        /tools config    - Configure tool settings
        /tools set       - Set tool display options
        /tools agent     - Control agent mode

    Args:
        context: Command context providing access to engine client
        args: Subcommand and arguments

    Returns:
        Appropriate CommandResult based on subcommand
    """
    if not context.get_tools_available():
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Tool support not available",
            error_details="Missing dependencies",
            suggestions=["Check docs/TOOL_CREATION_GUIDE.md"]
        )

    parts = args.strip().split() if args else []
    subcommand = parts[0].lower() if parts else "status"
    subargs = parts[1:] if len(parts) > 1 else []

    if subcommand in ("enable", "on"):
        return _enable_tools(context)
    elif subcommand in ("disable", "off"):
        return _disable_tools(context)
    elif subcommand == "list":
        return _list_tools(context)
    elif subcommand == "status":
        return _tools_status(context)
    elif subcommand == "config":
        return _tools_config(context, subargs)
    elif subcommand == "set":
        return _tools_set(context, subargs)
    elif subcommand == "agent":
        return _tools_agent(context, subargs)
    else:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Unknown subcommand: {subcommand}",
            suggestions=[
                "Available subcommands: on, off, list, status, config, set, agent"
            ]
        )


def _enable_tools(context: CommandContext) -> CommandResult:
    """Enable AI tools."""
    if not context.engine_client:
        return ErrorResult(status=ResultStatus.ERROR, message="Engine client not available")

    if context.engine_client.tools_enabled:
        return NotificationResult(
            status=ResultStatus.WARNING,
            message="Tools already enabled"
        )

    context.engine_client.enable_tools()

    # Get context limit info
    try:
        provider = context.get_provider()
        model = context.get_model()
        context_limit = get_model_context_limit(provider, model)
        max_injection = get_max_injection_size()

        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message="Tools enabled! Includes file editing tools (apply_patch, replace_block, insert_text, delete_lines)",
            details={
                "tools_enabled": True,
                "context_limit": context_limit,
                "max_injection_kb": max_injection // 1000,
                "hint": "Use '/tools list' to see available tools"
            }
        )
    except ImportError:
        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message="Tools enabled",
            details={"tools_enabled": True}
        )


def _disable_tools(context: CommandContext) -> CommandResult:
    """Disable AI tools."""
    if not context.engine_client:
        return ErrorResult(status=ResultStatus.ERROR, message="Engine client not available")

    if not context.engine_client.tools_enabled:
        return NotificationResult(
            status=ResultStatus.WARNING,
            message="Tools not enabled"
        )

    context.engine_client.disable_tools()
    return ConfirmationResult(
        status=ResultStatus.SUCCESS,
        message="Tools disabled",
        details={"tools_enabled": False}
    )


def _list_tools(context: CommandContext) -> CommandResult:
    """List available tools."""
    if not context.engine_client or not context.engine_client.tools_enabled:
        return NotificationResult(
            status=ResultStatus.WARNING,
            message="Tools not enabled. Use '/tools enable' first"
        )

    if not context.engine_client.tool_manager:
        return NotificationResult(
            status=ResultStatus.WARNING,
            message="Tool manager not available"
        )

    engine_tools = context.engine_client.tool_manager.list_tools()

    if not engine_tools:
        return NotificationResult(
            status=ResultStatus.INFO,
            message="No tools available"
        )

    return TableResult(
        status=ResultStatus.SUCCESS,
        message=f"{len(engine_tools)} tool(s) available",
        columns=["Tool", "Description"],
        rows=[
            [tool.get("name", ""), tool.get("description", "")]
            for tool in engine_tools
        ]
    )


def _tools_status(context: CommandContext) -> CommandResult:
    """Show tools status."""
    if context.engine_client and context.engine_client.tools_enabled:
        # Get tool count from engine
        tool_count = 0
        if context.engine_client.tool_manager:
            try:
                tool_count = len(context.engine_client.tool_manager.list_tools())
            except Exception:
                pass

        data = {
            "Status": f"Enabled ({tool_count} tools available)"
        }

        # Show consent mode
        try:
            consent_mode = context.engine_client.session.edit_consent_mode
            data["Consent Mode"] = consent_mode
        except Exception:
            pass

        # Show web search provider
        try:
            provider = context.get_provider()
            if web_premium.is_available():
                search_provider = web_premium.get_premium_search_provider(provider)
                if search_provider:
                    data["Web Search"] = f"{search_provider.title()} (premium)"
                else:
                    data["Web Search"] = "DuckDuckGo (free)"
            else:
                data["Web Search"] = "DuckDuckGo (free)"
        except Exception:
            data["Web Search"] = "DuckDuckGo (free)"

        data["Hint"] = "Use '/tools list' to see available tools"
        return KeyValueResult(
            status=ResultStatus.SUCCESS,
            message="Tools Status",
            pairs=data
        )
    else:
        return KeyValueResult(
            status=ResultStatus.INFO,
            message="Tools Status",
            pairs={
                "Status": "Not enabled",
                "Hint": "Use '/tools enable' to activate AI tools"
            }
        )


def _tools_config(context: CommandContext, args: List[str]) -> CommandResult:
    """Configure tool settings."""
    if not context.engine_client or not context.engine_client.tools_enabled:
        return NotificationResult(
            status=ResultStatus.WARNING,
            message="Tools not enabled. Use '/tools enable' first"
        )

    if not args:
        # Show current config
        status = context.engine_client.get_tools_status()
        max_iter = status.get('max_iterations', 15)
        auto_retry = status.get('auto_retry_empty', 2)

        return KeyValueResult(
            status=ResultStatus.INFO,
            message="Tool Configuration - Use /tools config <setting> <value>",
            pairs={
                "max_iterations": str(max_iter),
                "auto_retry_empty": str(auto_retry),
                "Available": "max_iterations (1-50), auto_retry_empty (0-5)"
            }
        )

    if len(args) < 2:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Usage: /tools config <setting> <value>",
            suggestions=["Available settings: max_iterations, auto_retry_empty"]
        )

    setting = args[0].lower()
    value = args[1]

    if setting == "max_iterations":
        try:
            num = int(value)
            if num < 1 or num > 50:
                return ErrorResult(
                    status=ResultStatus.ERROR,
                    message="max_iterations must be between 1 and 50"
                )
            context.engine_client.set_tool_config("max_iterations", num)
            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message=f"max_iterations set to {num}",
                details={"max_iterations": num}
            )
        except ValueError:
            return ErrorResult(status=ResultStatus.ERROR, message=f"Invalid number: {value}")
    elif setting == "auto_retry_empty":
        try:
            num = int(value)
            if num < 0 or num > 5:
                return ErrorResult(
                    status=ResultStatus.ERROR,
                    message="auto_retry_empty must be between 0 and 5"
                )
            context.engine_client.set_tool_config("auto_retry_empty", num)
            status_msg = "disabled" if num == 0 else f"{num} retries"
            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message=f"auto_retry_empty set to {status_msg}",
                details={"auto_retry_empty": num}
            )
        except ValueError:
            return ErrorResult(status=ResultStatus.ERROR, message=f"Invalid number: {value}")
    else:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Unknown setting: {setting}",
            suggestions=["Available settings: max_iterations, auto_retry_empty"]
        )


def _tools_set(context: CommandContext, args: List[str]) -> CommandResult:
    """Set tool settings (verbose mode)."""
    if not args:
        # Show current settings
        verbose_status = "enabled" if context.get_tools_verbose() else "disabled"
        return KeyValueResult(
            status=ResultStatus.INFO,
            message="Tool Settings - Use /tools set <setting> <value>",
            pairs={
                "verbose": verbose_status,
                "Available": "verbose on/off - Show tool inputs and outputs"
            }
        )

    if len(args) < 2:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Usage: /tools set <setting> <value>",
            suggestions=["Available setting: verbose"]
        )

    setting = args[0].lower()
    value = args[1].lower()

    if setting == "verbose":
        if value in ["on", "true", "1", "yes"]:
            context.set_tools_verbose(True)
            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message="Verbose tool logging enabled. Tool inputs and outputs will be displayed during execution",
                details={"verbose": True}
            )
        elif value in ["off", "false", "0", "no"]:
            context.set_tools_verbose(False)
            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message="Verbose tool logging disabled",
                details={"verbose": False}
            )
        else:
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=f"Invalid value: {value}",
                suggestions=["Use: on, off, true, false, 1, 0, yes, or no"]
            )
    else:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Unknown setting: {setting}",
            suggestions=["Available setting: verbose"]
        )


def _tools_agent(context: CommandContext, args: List[str]) -> CommandResult:
    """Control agent mode for autonomous task execution."""
    if not context.engine_client:
        return ErrorResult(status=ResultStatus.ERROR, message="Engine client not available")

    if not args:
        # Show current agent mode status
        status = "ON" if context.engine_client.agent_mode else "OFF"
        return KeyValueResult(
            status=ResultStatus.INFO,
            message="Agent Mode - Use /tools agent on|off",
            pairs={
                "Status": status,
                "Usage": "'/agent <task>' to run autonomous task"
            }
        )

    action = args[0].lower()
    if action in ["on", "enable"]:
        context.engine_client.enable_agent_mode()
        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message="Agent mode enabled. Tools auto-enabled. Use '/agent <task>' to start autonomous execution.",
            details={"agent_mode": True}
        )
    elif action in ["off", "disable"]:
        context.engine_client.disable_agent_mode()
        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message="Agent mode disabled",
            details={"agent_mode": False}
        )
    else:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Unknown action: {action}",
            suggestions=["Usage: /tools agent on|off"]
        )


def handle_usage(context: CommandContext, args: str) -> CommandResult:
    """Handle /usage command for usage statistics.

    Subcommands:
        /usage              - Show session usage totals
        /usage 24h          - Show usage for last 24 hours
        /usage week         - Show usage for last 7 days
        /usage month        - Show usage for last 30 days
        /usage year         - Show usage for last 365 days
        /usage all          - Show all-time usage
        /usage show session - Status line shows session totals (default)
        /usage show provider - Status line shows current provider totals
        /usage show model   - Status line shows current model totals
        /usage show off     - Hide usage from status line
        /usage reset        - Reset all usage counters

    Args:
        context: Command context providing access to engine client
        args: Subcommand and arguments

    Returns:
        Appropriate CommandResult based on subcommand
    """
    args = args.strip().lower()

    if not args:
        # Default: show session totals with per-model breakdown
        return _display_usage_report(context)

    parts = args.split()
    sub_command = parts[0]

    # Time-based usage reports
    time_periods = {"24h", "week", "month", "year", "all"}
    if sub_command in time_periods:
        return _display_global_usage_report(context, sub_command)

    if sub_command == "show":
        if len(parts) < 2:
            current_mode = context.engine_client.session.usage_display_mode
            return KeyValueResult(
                status=ResultStatus.INFO,
                message="Usage Display Mode",
                pairs={
                    "Current mode": current_mode,
                    "Usage": "/usage show <session|provider|model|off>"
                }
            )

        mode = parts[1]
        valid_modes = {"session", "provider", "model", "off"}
        if mode not in valid_modes:
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=f"Invalid mode: {mode}",
                suggestions=[f"Valid modes: {', '.join(valid_modes)}"]
            )

        if context.engine_client.session.set_usage_display_mode(mode):
            mode_descriptions = {
                "session": "session totals",
                "provider": f"current provider ({context.get_provider()}) totals",
                "model": f"current model ({context.get_model()}) totals",
                "off": "hidden"
            }
            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message=f"Usage display set to: {mode_descriptions[mode]}",
                details={"display_mode": mode}
            )
        else:
            return ErrorResult(status=ResultStatus.ERROR, message="Failed to set display mode")

    elif sub_command == "reset":
        context.engine_client.session.reset_usage()
        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message="Usage counters reset to zero",
            details={"counters_reset": True}
        )

    else:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Unknown sub-command: {sub_command}",
            suggestions=["Available: 24h, week, month, year, all, show, reset"]
        )


def _display_usage_report(context: CommandContext) -> CommandResult:
    """Display detailed usage report with per-model breakdown."""
    usage = context.engine_client.session.get_usage()

    # Build per-model breakdown table
    by_model = usage.get("by_model", {})
    rows = []

    if by_model:
        for key, stats in sorted(by_model.items()):
            parts = key.split("/", 1)
            provider = parts[0]
            model = parts[1] if len(parts) > 1 else key
            rows.append([
                provider,
                model,
                f"{stats['prompt_tokens']:,}",
                f"{stats['completion_tokens']:,}",
                f"${stats['estimated_cost']:.4f}"
            ])

        # Add totals row
        rows.append([
            "TOTAL",
            "",
            f"{usage['prompt_tokens']:,}",
            f"{usage['completion_tokens']:,}",
            f"${usage['estimated_cost']:.4f}"
        ])

    # Get tool usage if available
    tool_calls = usage.get("tool_calls", {})
    total_tool_cost = sum(tc.get("estimated_cost", 0.0) for tc in tool_calls.values())
    total_cost = usage['estimated_cost'] + total_tool_cost

    display_mode = usage.get("display_mode", "session")

    # Build message with key stats
    message_parts = [
        f"Session Usage Statistics - Total: ${total_cost:.4f}",
        f"({usage['total_tokens']:,} tokens: {usage['prompt_tokens']:,} in / {usage['completion_tokens']:,} out)",
        f"Display mode: {display_mode} - Change with /usage show <mode>"
    ]

    return TableResult(
        status=ResultStatus.SUCCESS,
        message=" | ".join(message_parts),
        columns=["Provider", "Model", "In", "Out", "Cost"],
        rows=rows,
        metadata={
            "report_type": "session",
            "title": "Session Usage Statistics",
            "total_tokens": usage['total_tokens'],
            "prompt_tokens": usage['prompt_tokens'],
            "completion_tokens": usage['completion_tokens'],
            "estimated_cost": total_cost,
            "display_mode": display_mode,
        }
    )


def _display_global_usage_report(context: CommandContext, period: str) -> CommandResult:
    """Display usage report for a time period.

    Args:
        period: One of "24h", "week", "month", "year", "all"

    Returns:
        TableResult with usage breakdown
    """
    report = get_usage_report(period)

    # Header with period info
    period_labels = {
        "24h": "Last 24 Hours",
        "week": "Last 7 Days",
        "month": "Last 30 Days",
        "year": "Last 365 Days",
        "all": "All Time"
    }

    # By model breakdown
    by_model = report.get("by_model", {})
    rows = []

    if by_model:
        for key, stats in sorted(by_model.items()):
            parts = key.split("/", 1)
            provider = parts[0]
            model = parts[1] if len(parts) > 1 else key
            rows.append([
                provider,
                model,
                f"{stats['prompt_tokens']:,}",
                f"{stats['completion_tokens']:,}",
                f"${stats['estimated_cost']:.4f}"
            ])

        # Add totals row
        rows.append([
            "TOTAL",
            "",
            f"{report.get('prompt_tokens', 0):,}",
            f"{report.get('completion_tokens', 0):,}",
            f"${report.get('total_cost', 0.0):.4f}"
        ])

    # Build message with stats
    message = f"Usage Report: {period_labels.get(period, period)}"
    if report.get("start_date"):
        message += f" ({report['start_date']} to {report['end_date']})"
    message += f" | {report.get('session_count', 0)} sessions | {report.get('total_tokens', 0):,} tokens ({report.get('prompt_tokens', 0):,}↓ / {report.get('completion_tokens', 0):,}↑) | ${report.get('total_cost', 0.0):.4f}"

    return TableResult(
        status=ResultStatus.SUCCESS,
        message=message,
        columns=["Provider", "Model", "In", "Out", "Cost"],
        rows=rows,
        metadata={
            "report_type": "period",
            "title": f"Usage Report: {period_labels.get(period, period)}",
            "period": period_labels.get(period, period),
            "session_count": report.get("session_count", 0),
            "total_tokens": report.get("total_tokens", 0),
            "prompt_tokens": report.get("prompt_tokens", 0),
            "completion_tokens": report.get("completion_tokens", 0),
            "estimated_cost": report.get("total_cost", 0.0),
            "start_date": report.get("start_date"),
            "end_date": report.get("end_date"),
        }
    )


# =============================================================================
# Command Registration
# =============================================================================

CommandFactory.register(CommandSpec(
    name="tools",
    description="Manage AI tools and tool settings",
    handler=handle_tools,
    category="tools",
    aliases=["t"],
    usage="/tools [on|off|list|status|config|set|help|agent]"
))

CommandFactory.register(CommandSpec(
    name="usage",
    description="Show usage statistics",
    handler=handle_usage,
    category="tools",
    usage="/usage [24h|week|month|year|all|show|reset]"
))

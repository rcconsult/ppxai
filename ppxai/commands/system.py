"""
System commands - help, status, theme, and configuration.

Commands for displaying help, status, themes, and system configuration.

v1.13.10: Migrated to Command Factory pattern
v1.14.0: Added bootstrap context status to /status command
v1.15.0: Migrated to type-based renderer dispatch
"""

from pathlib import Path
from typing import TYPE_CHECKING

from .factory import CommandFactory, CommandSpec
from .protocol import CommandContext
from .results import (
    ResultStatus,
    CommandResult,
    ConfirmationResult,
    ErrorResult,
    KeyValueResult,
    ListResult,
    TextResult,
)

if TYPE_CHECKING:
    from .handler import CommandHandler


# =============================================================================
# Type-Based Result Handlers (v1.15.0)
# =============================================================================

def handle_help(context: CommandContext, args: str) -> CommandResult:
    """Handle /help command - display help information.

    Args:
        context: Command context providing access to engine client
        args: Command arguments (unused)

    Returns:
        TextResult with help content
    """
    from ..version import __version__

    help_text = f"""ppxai v{__version__} - AI Chat Assistant

Available Commands:
  /help, /h, /?           Show this help message
  /model, /m              Switch or list AI models
  /provider, /p           Switch AI provider
  /tools, /t              Enable/disable AI tools
  /show <file>            Display file contents
  /status                 Show system status
  /theme                  Switch UI theme
  /save, /s               Save conversation
  /load, /l               Load conversation
  /clear, /c              Clear conversation
  /exit, /quit            Exit application

For detailed command usage, see the full documentation.
"""
    return TextResult(
        status=ResultStatus.INFO,
        message="ppxai Help - Available Commands",
        content=help_text
    )


def handle_theme(context: CommandContext, args: str) -> CommandResult:
    """Handle /theme command - switch TUI themes and emoji mode.

    Args:
        context: Command context providing access to engine client
        args: "list" to list, theme name to switch, "emoji on/off" for emoji mode

    Returns:
        ListResult when listing, ConfirmationResult when switching, KeyValueResult for emoji status
    """
    from ..rich.themes import get_theme, THEMES

    args = args.strip().lower() if args else ""

    # Note: For now, theme switching affects the old handler's state
    # In a full migration, this would be managed by the TUI framework adapter
    # This is marked as a limitation since we can't access handler from context

    # Handle emoji subcommand
    if args.startswith("emoji"):
        emoji_args = args[5:].strip()  # Get text after "emoji"

        if not emoji_args:
            # Show current emoji mode - Note: can't access from context in current architecture
            return KeyValueResult(
                status=ResultStatus.INFO,
                message="Emoji mode status",
                pairs={
                    "Note": "Use /theme emoji on|off to change",
                    "Current": "Check with old handler (not accessible from context)"
                }
            )

        if emoji_args == "on":
            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message="Emoji mode: ON. Original emojis will be shown (may cause panel misalignment in some terminals)",
                details={"emoji_mode": True}
            )
        elif emoji_args == "off":
            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message="Emoji mode: OFF. Emojis converted to text symbols for reliable panel alignment",
                details={"emoji_mode": False}
            )
        else:
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=f"Invalid option: {emoji_args}",
                suggestions=["Use: /theme emoji on|off"]
            )

    if not args or args == "list":
        # Show available themes
        items = []
        for theme_name in THEMES.keys():
            items.append({
                "text": theme_name,
                "current": False  # Can't determine current theme from context
            })

        return ListResult(
            status=ResultStatus.SUCCESS,
            message="Available themes",
            items=items
        )

    # Try to switch to the specified theme
    try:
        new_theme = get_theme(args)
        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message=f"Theme switched to: {new_theme.name}",
            details={"theme": args}
        )
    except ValueError as e:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=str(e),
            suggestions=["Use /theme list to see available themes"]
        )


def handle_status(context: CommandContext, args: str) -> CommandResult:
    """Handle /status command - show comprehensive status information.

    Args:
        context: Command context providing access to engine client
        args: "version", "cwd", or "datetime" to toggle display settings

    Returns:
        ConfirmationResult for settings changes, KeyValueResult for status display
    """
    from ..config import get_provider_config, get_tui_config, set_tui_config
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
                status_text = "enabled" if new_value else "disabled"
                return ConfirmationResult(
                    status=ResultStatus.SUCCESS,
                    message=f"{key}: {status_text}. Setting saved to config file.",
                    details={key: new_value}
                )
            else:
                return ErrorResult(
                    status=ResultStatus.ERROR,
                    message="Failed to save setting",
                    error_details=f'Try manually editing ppxai-config.json: "tui": {{ "{key}": {str(new_value).lower()} }}'
                )

    # Show comprehensive status
    pairs = {}

    # Version
    pairs["Version"] = f"v{__version__}"

    # Provider and model
    provider_config = get_provider_config(context.get_provider())
    pairs["Provider"] = provider_config.get('name', context.get_provider())
    pairs["Model"] = context.get_model()

    # Working directory
    if context.engine_client:
        cwd = context.engine_client.get_working_dir() or "not set"
        pairs["Working Dir"] = cwd

    # Tools status
    tools_status = "enabled" if (context.engine_client and context.engine_client.tools_enabled) else "disabled"
    pairs["Tools"] = tools_status

    # Agent mode
    agent_status = "active" if (context.engine_client and context.engine_client.agent_mode) else "inactive"
    pairs["Agent Mode"] = agent_status

    # Bootstrap context
    if context.engine_client:
        bootstrap_status = context.engine_client.get_bootstrap_status()
        if bootstrap_status.get("loaded"):
            sources = bootstrap_status.get("sources", [])
            if sources and isinstance(sources[0], dict):
                source_name = Path(sources[0]["path"]).name if sources else "unknown"
            else:
                source_name = Path(sources[0]).name if sources else "unknown"
            char_count = bootstrap_status.get("char_count", 0)

            # Show active hints
            active_hints = context.engine_client.get_active_hints()
            active_provider = len(active_hints.get("provider_hints", []))
            active_model = len(active_hints.get("model_hints", []))
            total_active = active_provider + active_model

            if total_active > 0:
                hint_parts = []
                if active_provider:
                    inherited = "+" if active_hints.get("inherited_local") else ""
                    hint_parts.append(f"{active_provider}{inherited} provider")
                if active_model:
                    hint_parts.append(f"{active_model} model")
                hint_info = f" ({', '.join(hint_parts)} hints active)"
            else:
                defined_providers = len(bootstrap_status.get("provider_hints", []))
                defined_models = len(bootstrap_status.get("model_hints", []))
                if defined_providers or defined_models:
                    hint_info = f" ({defined_providers} provider, {defined_models} model patterns defined)"
                else:
                    hint_info = ""

            pairs["Bootstrap"] = f"{source_name} ({char_count:,} chars){hint_info}"
        else:
            pairs["Bootstrap"] = "none"

    # Session info
    if context.engine_client and context.engine_client.session:
        session = context.engine_client.session
        msg_count = len(session.get_messages())
        pairs["Messages"] = str(msg_count)

        # Usage stats
        total_usage = session.get_usage()
        if total_usage:
            pairs["Tokens"] = f"{total_usage.get('prompt_tokens', 0)}↓ / {total_usage.get('completion_tokens', 0)}↑"
            cost = total_usage.get('estimated_cost', 0.0)
            if cost > 0:
                pairs["Cost"] = f"${cost:.4f}"

    # Status bar display settings
    tui_config = get_tui_config()
    pairs["show_version"] = "true" if tui_config.get('show_version', True) else "false"
    pairs["show_cwd"] = "true" if tui_config.get('show_cwd', True) else "false"
    pairs["show_datetime"] = "true" if tui_config.get('show_datetime', False) else "false"

    return KeyValueResult(
        status=ResultStatus.SUCCESS,
        message="ppxai Status",
        pairs=pairs
    )


def handle_spec(context: CommandContext, args: str) -> CommandResult:
    """Handle /spec command - display specification templates.

    Args:
        context: Command context providing access to engine client
        args: Spec type (api, cli, lib, algo, ui) or empty for list

    Returns:
        TextResult with spec template content
    """
    spec_type = args.strip().lower() if args else None

    if not spec_type:
        spec_text = """Available Specification Templates:

  /spec api    - API specification template
  /spec cli    - CLI application specification
  /spec lib    - Library specification
  /spec algo   - Algorithm specification
  /spec ui     - UI component specification

Use: /spec <type> to view a specific template
"""
    else:
        # Simple spec template - full templates can be added later
        spec_text = f"""Specification Template: {spec_type.upper()}

[Basic template - use old handler for full rich templates]

For detailed {spec_type} specification templates, the full rich UI version
provides comprehensive templates with examples and best practices.
"""

    return TextResult(
        status=ResultStatus.INFO,
        message=f"Specification Template{f': {spec_type}' if spec_type else 's'}",
        content=spec_text
    )


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

"""
Provider and model management commands.

Commands for switching providers, models, and configuring auto-routing.

v1.13.10: Migrated to Command Factory pattern
v1.15.0: Migrated to type-based renderer dispatch
"""

from typing import TYPE_CHECKING

from ..config import PROVIDERS, get_api_key, get_base_url, get_provider_config
from .factory import CommandFactory, CommandSpec
from .protocol import CommandContext
from .results import (
    ResultStatus,
    CommandResult,
    ConfirmationResult,
    ListResult,
    ErrorResult,
    KeyValueResult,
)

if TYPE_CHECKING:
    from .handler import CommandHandler


def handle_model(context: CommandContext, args: str) -> CommandResult:
    """Handle /model command - switch or list models.

    Args:
        context: Command context providing access to engine client
        args: "list" to list models, model ID to switch, or empty for list

    Returns:
        ListResult when listing, ConfirmationResult when switching, ErrorResult on failure
    """
    from ..config import get_provider_config

    # Reload config from disk to pick up external changes (e.g., new models added)
    if context.engine_client:
        context.engine_client.reload_config()

    args = args.strip().lower()
    provider = context.get_provider()
    current_model = context.get_model()

    if args == "list" or not args:
        # List available models
        config = get_provider_config(provider)
        models = config.get("models", {})

        items = []
        for num, info in models.items():
            model_id = info.get("id", num)
            description = info.get("description", "")
            is_current = model_id == current_model
            items.append({
                "id": model_id,
                "description": description,
                "current": is_current
            })

        return ListResult(
            status=ResultStatus.SUCCESS,
            message=f"Available models for {provider}",
            items=[
                {
                    "text": f"{'✓ ' if item['current'] else ''}{item['id']} - {item['description']}",
                    "current": item['current']
                }
                for item in items
            ]
        )
    else:
        # Direct model selection by ID
        config = get_provider_config(provider)
        models = config.get("models", {})

        # Find model by ID
        for num, info in models.items():
            model_id = info.get("id", num)
            if model_id == args:
                context.set_model(model_id)
                context.engine_client.set_model(model_id)
                context.engine_client.session.set_model(model_id)
                reset_count = context.engine_client.last_model_switch_reset
                message = f"Switched to model: {model_id}"
                if reset_count > 0:
                    message += f" (cleared {reset_count} previous messages)"
                return ConfirmationResult(
                    status=ResultStatus.SUCCESS,
                    message=message,
                    details={
                        "provider": provider,
                        "model": model_id,
                        "context_reset": reset_count,
                    }
                )

        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Model not found: {args}",
            suggestions=["Use /model list to see available models"]
        )


def handle_provider(context: CommandContext, args: str) -> CommandResult:
    """Handle /provider command - switch between providers.

    Args:
        context: Command context providing access to engine client
        args: "list" to list providers, provider ID to switch, or empty for list

    Returns:
        ListResult when listing, ConfirmationResult when switching, ErrorResult on failure
    """
    # Reload config from disk to pick up external changes (e.g., new providers)
    # reload_config() updates PROVIDERS dict in-place via initialize()
    if context.engine_client:
        context.engine_client.reload_config()

    args = args.strip().lower()
    current_provider = context.get_provider()

    if args == "list" or not args:
        # List available providers
        items = []
        for provider_id, config in PROVIDERS.items():
            has_key = bool(get_api_key(provider_id))
            is_current = provider_id == current_provider
            key_status = "" if has_key else " (no API key)"
            items.append({
                "id": provider_id,
                "name": config.get("name", provider_id),
                "has_key": has_key,
                "current": is_current,
                "key_status": key_status
            })

        return ListResult(
            status=ResultStatus.SUCCESS,
            message="Available providers",
            items=[
                {
                    "text": f"{'✓ ' if item['current'] else ''}{item['id']} - {item['name']}{item['key_status']}",
                    "current": item['current']
                }
                for item in items
            ]
        )

    # Direct provider selection by ID
    if args not in PROVIDERS:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Provider not found: {args}",
            suggestions=["Use /provider list to see available providers"]
        )

    new_provider = args

    if new_provider == current_provider:
        return ConfirmationResult(
            status=ResultStatus.INFO,
            message="Already using this provider, no change needed",
            details={"provider": current_provider}
        )

    # Check if new provider has API key configured
    new_api_key = get_api_key(new_provider)
    if not new_api_key:
        config = get_provider_config(new_provider)
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"API key not configured for {new_provider}",
            error_details=f"{config['api_key_env']} not found in .env file",
            suggestions=["Add the API key to your .env file"]
        )

    # Check if tools are currently enabled
    tools_were_enabled = context.engine_client.tools_enabled

    # Switch to new provider
    new_base_url = get_base_url(new_provider)
    new_config = get_provider_config(new_provider)

    # Update context and engine client
    context.set_provider(new_provider)
    context.engine_client.set_provider(new_provider)
    context.engine_client.session.set_provider(new_provider)

    # Auto-select default model for new provider
    new_model = new_config.get("default_model", "")
    context.set_model(new_model)
    context.engine_client.set_model(new_model)
    context.engine_client.session.set_model(new_model)

    reset_count = context.engine_client.last_model_switch_reset
    message = f"Switched to: {new_config['name']} (model: {new_model})"
    if reset_count > 0:
        message += f" (cleared {reset_count} previous messages)"

    details = {
        "provider": new_provider,
        "provider_name": new_config['name'],
        "model": new_model,
        "context_reset": reset_count,
    }

    return ConfirmationResult(
        status=ResultStatus.SUCCESS,
        message=message,
        details=details
    )


def handle_autoroute(context: CommandContext, args: str) -> CommandResult:
    """Handle /autoroute command - toggle auto-routing to coding model.

    Args:
        context: Command context providing access to engine client
        args: "on" to enable, "off" to disable, or empty for status

    Returns:
        KeyValueResult for status, ConfirmationResult for state changes, ErrorResult on invalid input
    """
    from ..config import get_coding_model

    provider = context.get_provider()
    coding_model = get_coding_model(provider)
    current_status = context.get_auto_route()

    if not args:
        # Show status
        return KeyValueResult(
            status=ResultStatus.INFO,
            message="Auto-routing status",
            pairs={
                "Status": "enabled" if current_status else "disabled",
                "Coding Model": coding_model,
                "Provider": provider
            }
        )

    arg = args.strip().lower()
    if arg == "on":
        context.set_auto_route(True)
        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message=f"Auto-routing enabled. Coding commands will use {coding_model}",
            details={
                "auto_route": True,
                "coding_model": coding_model
            }
        )
    elif arg == "off":
        context.set_auto_route(False)
        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message="Auto-routing disabled. Manual model selection will be used",
            details={"auto_route": False}
        )
    else:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Invalid option: {arg}",
            suggestions=["Use /autoroute on or /autoroute off"]
        )


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

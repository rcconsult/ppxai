"""
Provider and model management commands.

Commands for switching providers, models, and configuring auto-routing.

v1.13.10: Migrated to Command Factory pattern
v1.15.0: Migrated to type-based renderer dispatch
"""


from ..config import (  # noqa: F401 — patched/read by tests
    PROVIDERS,
    get_api_key,
    get_base_url,
    get_coding_model,
    get_provider_config,
)
from ..engine.facts_config import model_fact_overrides
from ..engine.model_facts import (
    UNMEASURED,
    apply_overrides,
    is_unmeasured,
    shipped_facts_for_model,
)
from ..engine.provider_ops import ModelSwitchInFlightError
from ..engine.providers import get_provider_class
from .factory import CommandFactory, CommandSpec
from .protocol import CommandContext
from .results import (
    CommandResult,
    ConfirmationResult,
    ErrorResult,
    KeyValueResult,
    ListResult,
    ResultStatus,
)


def _run_in_flight_error(exc: ModelSwitchInFlightError) -> ErrorResult:
    """The engine refused a switch because a response is streaming (v1.19.2)."""
    return ErrorResult(
        status=ResultStatus.ERROR,
        message=str(exc),
        suggestions=[
            "Wait for the current response to finish, then switch",
            "Or stop the run first (Ctrl+C in the TUI, Stop in the web/VSCode UI)",
        ],
    )


def handle_model(context: CommandContext, args: str) -> CommandResult:
    """Handle /model command - switch or list models.

    Args:
        context: Command context providing access to engine client
        args: "list" to list models, model ID to switch, or empty for list

    Returns:
        ListResult when listing, ConfirmationResult when switching, ErrorResult on failure
    """
    # Reload config from disk to pick up external changes (e.g., new models added)
    if context.engine_client:
        context.engine_client.reload_config()

    args = args.strip()
    provider = context.get_provider()
    current_model = context.get_model()

    # Dispatch /model info [model-id]
    if args.lower().startswith("info"):
        info_args = args[4:].strip()
        model_id = info_args if info_args else current_model
        return handle_model_info(context, provider, model_id)

    args = args.lower()

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
                try:
                    context.set_model(model_id)
                except ModelSwitchInFlightError as exc:
                    return _run_in_flight_error(exc)
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

    # Switch to new provider
    new_config = get_provider_config(new_provider)

    # Update context and engine client
    # context.set_provider() updates both UI state and engine_client.set_provider()
    # which internally sets session and default model.
    # context.set_model() updates both UI state and engine_client.set_model()
    # which internally sets session — no need for separate session/engine calls.
    # Auto-select default model for new provider. set_provider() refuses
    # BEFORE mutating anything while a response streams (v1.19.2), so a
    # refusal here never leaves the provider switched with the model not.
    new_model = new_config.get("default_model", "")
    try:
        context.set_provider(new_provider)
        context.set_model(new_model)
    except ModelSwitchInFlightError as exc:
        return _run_in_flight_error(exc)

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


def handle_model_info(context: CommandContext, provider: str, model_id: str) -> CommandResult:
    """Handle /model info [model-id] - show effective tool calling profile.

    Shows the resolved `ModelFacts` (shipped row + config) with source
    attribution — the same answer the send path resolves.

    Args:
        context: Command context
        provider: Current provider name
        model_id: Model ID to inspect

    Returns:
        KeyValueResult with effective profile details
    """
    # ONE resolver (ADR 0012 §2 Q0e). This display used to re-implement the
    # merge a third time — its own layer order, its own field list — which is
    # how `api_path` came to be shown here while nothing routed on it (debt
    # Item 61). It now reports what the send path will actually do.

    try:
        provider_table = getattr(
            get_provider_class(provider), "shipped_model_facts", {}
        )
    except Exception:  # noqa: BLE001 — an unknown provider still shows rows
        provider_table = {}

    shipped = shipped_facts_for_model(model_id, provider_table)
    config_overrides = model_fact_overrides(provider, model_id)
    effective = apply_overrides(shipped, config_overrides)
    unmeasured = is_unmeasured(model_id, provider_table)

    # v1.19.3 — a provider row can itself BE the floor, field by field.
    #
    # `is_unmeasured()` answers "did a row match", and a matched row used to
    # make every field print `(built-in)`. But `PerplexityProvider` seeds its
    # gateway rows from `shipped_facts_for_model("openai/")` (and
    # `"anthropic/"`, `"google/"`, `"xai/"`, `"perplexity/"`), none of which
    # match anything — so the seed IS `UNMEASURED`, and only three fields
    # (`wire_protocol`, `tool_mode`, `max_tokens`) are then deliberately set.
    # The remaining nine arrived as floor values wearing a `(built-in)` label,
    # across every model those five globs serve. Q0e requires the opposite:
    # "an operator should be told which of their models those are rather than
    # discovering it when a tool call silently degrades" — which is exactly
    # how it was found.
    #
    # REPORTING ONLY. The vendor-agnostic floor is correct as *resolution*
    # (one wire, four vendors, a roster that changes without notice); it was
    # only ever wrong as a *label*. `is_unmeasured` and the send path are
    # untouched.
    #
    # The guard is `has_global_row`: a model with a real row in
    # `SHIPPED_MODEL_FACTS` keeps `(built-in)` for every field, so a MEASURED
    # value that happens to equal the floor — `o3*`'s measured-serial
    # `parallel_tool_calls=False`, `gemini-3.1-pro*`'s — is never relabelled
    # as a guess. Only a model resolved SOLELY through a provider row is
    # compared field-by-field.
    has_global_row = not is_unmeasured(model_id)

    def _source(field: str) -> str:
        if field in config_overrides:
            return "config"
        if unmeasured:
            return "unmeasured"
        if has_global_row:
            return "built-in"
        if getattr(shipped, field) == getattr(UNMEASURED, field):
            return "unmeasured"
        return "built-in"

    def _row(field: str) -> str:
        return f"{str(getattr(effective, field)):<20s} ({_source(field)})"

    # Count active hints.
    #
    # `bootstrap_ctx` was referenced here but NEVER ASSIGNED (ruff F821), so
    # this block raised NameError on every call rather than doing nothing —
    # the Hints row could not have appeared for anyone. Resolved from the
    # engine, the same path `bootstrap_ops.py` uses; `getattr` because the
    # attribute is Optional on the client and the protocol does not oblige a
    # test double to carry it.
    bootstrap_ctx = getattr(context.engine_client, "_bootstrap_context", None)

    hint_count = ""
    if bootstrap_ctx is not None:
        try:
            active = bootstrap_ctx.get_active_hints_for(provider, model_id)
            p_count = len(active.get("provider_hints", []))
            m_count = len(active.get("model_hints", []))
            hint_count = f"{m_count} model, {p_count} provider"
        except (AttributeError, TypeError):
            pass

    # Format pairs
    pairs = {
        "Model": f"{model_id} ({provider})",
        "Tier": effective.tier
        or ("(unmeasured)" if _source("tier") == "unmeasured" else "(no tier)"),
        "": "",  # separator
        "wire_protocol": _row("wire_protocol"),
        "tool_mode": _row("tool_mode"),
        "fallback_on_empty": _row("fallback_on_empty"),
        "fallback_on_failure": _row("fallback_on_failure"),
        "strip_json_from_text": _row("strip_json_from_text"),
        "parallel_tool_calls": _row("parallel_tool_calls"),
        " ": "",  # separator
        "max_tokens": _row("max_tokens"),
        "max_tool_iterations": _row("max_tool_iterations"),
    }

    if hint_count:
        pairs["  "] = ""  # separator
        pairs["Hints"] = hint_count

    return KeyValueResult(
        status=ResultStatus.INFO,
        message=f"Model profile: {model_id}",
        pairs=pairs,
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

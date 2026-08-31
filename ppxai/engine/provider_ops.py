"""
Provider and model operations — switching, listing, and hint transitions.

Extracted from engine/client.py (v1.17.4) to reduce EngineClient size
and co-locate all provider/model management in one focused module.
All functions take an engine reference as first parameter.

Covers:
- `set_provider(engine, provider_name)` — full provider switch including
  API key lookup, capability resolution, provider instance creation,
  default model application, tool re-registration, and hints logging
- `list_providers(engine)` — list all configured providers with status
- `get_current_provider(engine)` — current provider name or None
- `set_model(engine, model_id, strict, reset_context)` — model switch
  with strict/permissive variants and optional context reset
- `list_models(engine)` — list models for the current provider
- `get_current_model(engine)` — current model ID or None

The two internal helpers `_apply_model_switch` and
`_log_model_hints_transition` are also moved here as module-private
functions because they're only called from `set_model` / `set_provider`.
"""

from typing import List, Optional

from .types import ProviderInfo, ModelInfo, ProviderCapabilities
from .providers import create_provider
from .providers.openai_compat import OpenAICompatibleProvider
from .tools.builtin import register_all_builtin_tools
from ..common.logger import get_logger
from ..constants import Default
from .model_facts import supports_vision as _supports_vision

logger = get_logger("engine")


# =============================================================================
# Provider switching
# =============================================================================


def set_provider(engine, provider_name: str) -> bool:
    """Switch the active provider.

    Full provider switch: validates the provider exists in config,
    looks up the API key, resolves base_url and capabilities, creates
    a new provider instance (with OpenAI-compatible fallback), updates
    AppState, re-registers tools for the new provider context, and
    logs the hints transition.

    Args:
        engine: EngineClient reference (read/write).
        provider_name: Provider ID (e.g., 'perplexity', 'openai')

    Returns:
        True if provider was set successfully, False if the provider
        isn't configured or has no API key.
    """
    if provider_name not in engine.providers_config:
        return False

    api_key = engine._get_api_key(provider_name)
    if not api_key:
        return False

    base_url = engine._get_base_url(provider_name)
    provider_config = engine.providers_config[provider_name]

    # Parse capabilities from config
    caps_dict = provider_config.get("capabilities", {})
    capabilities = ProviderCapabilities.from_dict(caps_dict)

    # Create provider instance with optional provider-specific options
    provider_options = provider_config.get("options", {})
    engine.provider = create_provider(
        provider_name,
        api_key=api_key,
        base_url=base_url,
        models=provider_config.get("models", {}),
        capabilities=capabilities,
        **provider_options  # Pass provider-specific options (e.g., enable_grounding for Gemini)
    )

    if engine.provider is None:
        # Fallback to generic OpenAI-compatible provider
        engine.provider = OpenAICompatibleProvider(
            api_key=api_key,
            base_url=base_url,
            models=provider_config.get("models", {}),
            capabilities=capabilities,
            provider_id=provider_name  # For config lookup (generation_params, max_tokens)
        )

    engine.provider_name = provider_name
    engine.state.set("provider", provider_name)
    engine.tool_manager.set_provider(provider_name)
    engine.session.set_provider(provider_name)

    # Set default model for this provider (no context reset — provider switch
    # resets via the user's explicit set_model call, not this internal default).
    # Suppress hint logging here — the caller's set_model() will log the final model.
    default_model = provider_config.get("default_model")
    if default_model:
        engine._suppress_hint_log = True
        set_model(engine, default_model, reset_context=False)
        engine._suppress_hint_log = False

    # Re-register tools when switching providers if tools are enabled.
    # This ensures provider-aware tools (like web_search) are correctly
    # filtered for the new provider. Without this, switching from
    # perplexity to custom would keep web_search excluded even though
    # custom providers need it.
    if engine.tools_enabled:
        engine.tool_manager.clear()
        register_all_builtin_tools(engine.tool_manager, provider_name, engine=engine)
        engine.tool_manager.max_iterations = engine._agent_config.get(
            "max_tool_iterations", Default.MAX_TOOL_ITERATIONS
        )
        engine.tool_manager.max_same_tool_calls = engine._agent_config.get(
            "max_same_tool_calls", Default.MAX_SAME_TOOL_CALLS
        )

    # Log hints transition for debugging (v1.14.0)
    if engine._bootstrap_context:
        hints_info = engine.get_active_hints()
        provider_count = len(hints_info["provider_hints"])
        model_count = len(hints_info["model_hints"])
        inherited = " (inherited local)" if hints_info["inherited_local"] else ""
        patterns = hints_info["matched_patterns"]
        logger.debug(
            f"Provider switch to '{provider_name}': "
            f"{provider_count} provider hints{inherited}, "
            f"{model_count} model hints (patterns: {patterns})"
        )

    return True


def list_providers(engine) -> List[ProviderInfo]:
    """List available providers with their status.

    Returns:
        List of ProviderInfo objects
    """
    providers = []
    for provider_id, config in engine.providers_config.items():
        has_key = bool(engine._get_api_key(provider_id))
        caps_dict = config.get("capabilities", {})

        providers.append(ProviderInfo(
            id=provider_id,
            name=config.get("name", provider_id),
            base_url=config.get("base_url", ""),
            api_key_env=config.get("api_key_env", ""),
            has_api_key=has_key,
            capabilities=ProviderCapabilities.from_dict(caps_dict),
            default_model=config.get("default_model", ""),
            coding_model=config.get("coding_model")
        ))

    return providers


def get_current_provider(engine) -> Optional[str]:
    """Get the current provider name.

    Returns:
        Provider name or None
    """
    return engine.provider_name if engine.provider else None


# =============================================================================
# Model switching
# =============================================================================


def set_model(
    engine,
    model_id: str,
    strict: bool = False,
    reset_context: bool = True,
) -> bool:
    """Set the current model.

    Args:
        engine: EngineClient reference.
        model_id: Model ID to use
        strict: If True, reject models not in provider's configured list (v1.13.10)
        reset_context: If True, strip assistant/tool messages on model switch (v1.16.0)

    Returns:
        True if model was set successfully
    """
    if not engine.provider:
        return False

    engine.last_model_switch_reset = 0

    models = engine.provider.list_models()
    model_exists = any(m.id == model_id for m in models)

    if model_exists:
        return _apply_model_switch(engine, model_id, reset_context)

    if strict:
        # Strict mode - reject unavailable models (used for session restore)
        return False

    # Allow setting model even if not in list (for flexibility with custom endpoints)
    return _apply_model_switch(engine, model_id, reset_context)


def _apply_model_switch(engine, model_id: str, reset_context: bool) -> bool:
    """Apply a confirmed model switch: update state, optionally reset context."""
    engine.model = model_id
    engine.state.set("model", model_id)
    # v1.18.6: drives the cross-client attach-button badge and per-file
    # warning when user attaches an image to a model that can't accept
    # it. Single source of truth lives in model_facts.supports_vision();
    # this just projects it onto AppState so the SSE_SYNC_FIELDS push
    # reaches every connected web/VSCode client transparently.
    engine.state.set("model_supports_vision", _supports_vision(model_id))
    engine.session.set_model(model_id)
    if reset_context and engine.session.messages:
        removed = engine.session.reset_for_model_switch()
        engine.last_model_switch_reset = removed
        if removed:
            logger.info(
                f"Reset context for model switch to {model_id}: removed {removed} messages"
            )
    _log_model_hints_transition(engine, model_id)
    _refresh_context_percentage(engine)
    return True


def _refresh_context_percentage(engine) -> None:
    """Refresh the context-percentage badge after a provider/model switch.

    v1.19.1 Item 48: delegates to the single producer on EngineClient so
    there is one source of truth for the `context_percentage` AppState
    field. Kept as a thin shim because the provider-switch path calls it
    explicitly (a model switch changes `context_limit`, so the percentage
    must refresh even when the message list did not change).
    """
    engine._refresh_context_percentage()


def _log_model_hints_transition(engine, model_id: str) -> None:
    """Log hints transition when model changes (v1.14.0)."""
    if not engine._bootstrap_context or getattr(engine, "_suppress_hint_log", False):
        return

    hints_info = engine.get_active_hints()
    model_count = len(hints_info["model_hints"])
    patterns = hints_info["matched_patterns"]

    if patterns:
        logger.debug(
            f"Model switch to '{model_id}': "
            f"{model_count} model hints (matched: {patterns})"
        )
    # No logging when no hints matched — reduces noise in logs.
    # Available patterns can be seen via /context show command.


def list_models(engine) -> List[ModelInfo]:
    """List available models for current provider.

    Returns:
        List of ModelInfo objects
    """
    if not engine.provider:
        return []
    return engine.provider.list_models()


def get_current_model(engine) -> Optional[str]:
    """Get the current model.

    Returns:
        Model ID or None
    """
    return engine.model if engine.model else None


__all__ = [
    "set_provider",
    "list_providers",
    "get_current_provider",
    "set_model",
    "list_models",
    "get_current_model",
]

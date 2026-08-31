"""
Provider, model, pricing, and capabilities configuration.

Depends on context.py (for get_default_context_limit).
"""

import os
from typing import Any

from .context import get_default_context_limit
from .loader import DEFAULT_CAPABILITIES, _load_json_config, find_config_file
from .store import ConfigStore


def _get_config() -> dict[str, Any]:
    """Get config dict from config store."""
    return ConfigStore.get_instance().config


def _get_providers() -> dict[str, Any]:
    """Get providers dict from config store."""
    return _get_config().get("providers", {})


def _get_models() -> dict[str, Any]:
    """Get models from default perplexity provider."""
    return _get_providers().get("perplexity", {}).get("models", {})


def get_default_provider() -> str:
    """Get the default provider from environment or configuration.

    Checks in order:
    1. MODEL_PROVIDER environment variable
    2. default_provider from config file
    3. Falls back to "perplexity"

    Returns:
        Provider ID string.
    """
    env_provider = os.getenv("MODEL_PROVIDER")
    if env_provider and env_provider in _get_providers():
        return env_provider

    config = ConfigStore.get_instance().config
    default = config.get("default_provider", "perplexity")
    if default in _get_providers():
        return default

    return "perplexity"


def get_config_source() -> str:
    """Get the source of the current configuration."""
    return ConfigStore.get_instance().config.get("config_source", "builtin")


def get_available_providers() -> list[str]:
    """Get list of all available provider IDs."""
    return list(_get_providers().keys())


def get_provider_config(provider: str = None) -> dict:
    """Get configuration for the specified provider."""
    if provider is None:
        provider = get_default_provider()
    providers = _get_providers()
    return providers.get(provider, providers.get("perplexity", {}))


def get_active_models() -> dict:
    """Get models for the active provider."""
    return get_provider_config().get("models", {})


def get_active_pricing() -> dict:
    """Get pricing for the active provider."""
    return get_provider_config().get("pricing", {})


def get_model_pricing(provider: str = None) -> dict:
    """Get pricing for the specified provider."""
    return get_provider_config(provider).get("pricing", {})


def calculate_cost(prompt_tokens: int, completion_tokens: int, model: str, provider: str = None) -> float:
    """Calculate estimated cost in USD for token usage."""
    pricing = get_model_pricing(provider)
    model_pricing = pricing.get(model, {})

    if not model_pricing:
        return 0.0

    input_price = model_pricing.get("input", 0.0)
    output_price = model_pricing.get("output", 0.0)

    input_cost = (prompt_tokens / 1_000_000) * input_price
    output_cost = (completion_tokens / 1_000_000) * output_price

    return input_cost + output_cost


def get_api_key(provider: str = None) -> str:
    """Get API key for the specified provider from environment."""
    config = get_provider_config(provider)
    return os.getenv(config.get("api_key_env", ""), "")


def get_base_url(provider: str = None) -> str:
    """Get base URL for the specified provider."""
    return get_provider_config(provider).get("base_url", "")


def get_provider_capabilities(provider: str = None) -> dict:
    """Get capabilities for the specified provider."""
    config = get_provider_config(provider)
    return config.get("capabilities", DEFAULT_CAPABILITIES)


def provider_needs_tool(provider: str, tool_category: str) -> bool:
    """Check if a provider needs a specific tool category."""
    capabilities = get_provider_capabilities(provider)
    return not capabilities.get(tool_category, False)


def get_coding_model(provider: str = None) -> str:
    """Get the best model for coding tasks for the provider."""
    return get_provider_config(provider).get("coding_model", "")


def get_default_model(provider: str = None) -> str:
    """Get the default model for the provider."""
    return get_provider_config(provider).get("default_model", "")


def validate_config() -> dict[str, Any]:
    """Validate the current configuration and check API key availability."""
    config = ConfigStore.get_instance().config
    providers = _get_providers()

    result = {
        "valid": True,
        "config_source": config.get("config_source", "builtin"),
        "providers": {},
    }

    for provider_id, provider_config in providers.items():
        api_key = get_api_key(provider_id)
        has_key = bool(api_key)

        result["providers"][provider_id] = {
            "name": provider_config.get("name", provider_id),
            "has_api_key": has_key,
            "api_key_env": provider_config.get("api_key_env", ""),
            "base_url": provider_config.get("base_url", ""),
            "model_count": len(provider_config.get("models", {})),
            "default_model": provider_config.get("default_model", ""),
        }

    return result


def get_model_context_limit(provider: str = None, model: str = None) -> int:
    """Get the context limit for a specific model."""
    if provider is None:
        provider = get_default_provider()

    if model is None:
        model = get_default_model(provider)

    config_path = find_config_file()
    if config_path:
        json_config = _load_json_config(config_path)
        provider_config = json_config.get("providers", {}).get(provider, {})
        models = provider_config.get("models", {})
        model_config = models.get(model, {})

        if "context_limit" in model_config:
            return model_config["context_limit"]

    return get_default_context_limit()


def get_model_max_tokens(provider: str = None, model: str = None) -> int | None:
    """Get the max_tokens setting for output generation."""
    if provider is None:
        provider = get_default_provider()

    if model is None:
        model = get_default_model(provider)

    config_path = find_config_file()
    if config_path:
        json_config = _load_json_config(config_path)
        provider_config = json_config.get("providers", {}).get(provider, {})

        models = provider_config.get("models", {})
        model_config = models.get(model, {})
        if "max_tokens" in model_config:
            return model_config["max_tokens"]

        if "default_max_tokens" in provider_config:
            return provider_config["default_max_tokens"]

    return None


def get_generation_params(provider: str = None, model: str = None) -> dict[str, Any]:
    """Get generation parameters (temperature, top_p, etc.) for a model.

    These params are passed directly to the chat completions API.
    Supports both provider-level defaults and model-level overrides.

    Config structure:
        providers:
          custom:
            generation_params:      # Provider-level defaults
              temperature: 0.7
            models:
              my-model:
                generation_params:  # Model-level overrides
                  temperature: 0.3
                  top_p: 0.9

    Supported parameters (OpenAI-compatible):
        - temperature: 0.0-2.0 (lower = more deterministic, reduces hallucinations)
        - top_p: 0.0-1.0 (nucleus sampling)
        - frequency_penalty: -2.0-2.0 (reduce repetition)
        - presence_penalty: -2.0-2.0 (encourage new topics)
        - seed: int (for reproducibility, if supported by provider)

    Args:
        provider: Provider name (uses default if not specified)
        model: Model name (uses default if not specified)

    Returns:
        Dict of generation parameters to pass to API (empty if none configured)
    """
    if provider is None:
        provider = get_default_provider()

    if model is None:
        model = get_default_model(provider)

    params = {}

    config_path = find_config_file()
    if config_path:
        json_config = _load_json_config(config_path)
        provider_config = json_config.get("providers", {}).get(provider, {})

        # Start with provider-level defaults
        if "generation_params" in provider_config:
            params.update(provider_config["generation_params"])

        # Override with model-level params
        models = provider_config.get("models", {})
        model_config = models.get(model, {})
        if "generation_params" in model_config:
            params.update(model_config["generation_params"])

    # Filter out comment keys (e.g., "__comment_temperature")
    return {k: v for k, v in params.items() if not k.startswith("__comment")}


def get_extra_body(provider: str = None, model: str = None) -> dict[str, Any]:
    """Get vendor-specific ``extra_body`` payload for a model.

    OpenAI's chat-completions ``extra_body`` parameter is a pass-through
    dict that adds vendor-specific fields the SDK does not officially
    expose. v1.18.3 plumbs this through ppxai so users can drive Qwen3.5
    / GLM thinking-mode toggles via ``chat_template_kwargs`` and similar
    NIM- / vLLM-specific runtime knobs without forking the engine.

    Config structure (mirrors generation_params: provider defaults +
    model-level overrides, model wins on conflict)::

        providers:
          nvidia:
            extra_body:                # Provider-level defaults
              chat_template_kwargs:
                enable_thinking: false
            models:
              qwen/qwen3.5-122b-a10b:
                extra_body:            # Model-level overrides
                  chat_template_kwargs:
                    enable_thinking: true

    Args:
        provider: Provider name (uses default if not specified).
        model: Model name (uses default if not specified).

    Returns:
        Dict suitable for passing as ``extra_body=...`` to OpenAI SDK
        chat-completions calls. Empty dict when nothing is configured.
    """
    if provider is None:
        provider = get_default_provider()
    if model is None:
        model = get_default_model(provider)

    body: dict[str, Any] = {}
    config_path = find_config_file()
    if not config_path:
        return body

    json_config = _load_json_config(config_path)
    provider_config = json_config.get("providers", {}).get(provider, {})

    if "extra_body" in provider_config:
        body.update(provider_config["extra_body"])

    models = provider_config.get("models", {})
    model_config = models.get(model, {})
    if "extra_body" in model_config:
        body.update(model_config["extra_body"])

    # Strip top-level __comment_* sentinels — vendor APIs don't expect them.
    return {k: v for k, v in body.items() if not k.startswith("__comment")}


def get_reasoning_trigger(provider: str = None, model: str = None) -> str | None:
    """Get the per-model reasoning trigger string.

    Some models (notably ``nvidia/llama-3.3-nemotron-super-49b-v1.5``)
    use an in-prompt convention to toggle reasoning mode: appending
    ``/think`` enables reasoning, ``/no_think`` disables it. This is
    distinct from ``chat_template_kwargs.enable_thinking`` (which
    Qwen3.5 / GLM use via ``extra_body``) — nemotron has no extra-body
    knob, only the prompt-level marker.

    v1.18.3: read from per-provider or per-model ``reasoning_trigger``.
    Model-level wins on conflict.

    Config example::

        providers:
          nvidia:
            models:
              "nvidia/llama-3.3-nemotron-super-49b-v1.5":
                reasoning_trigger: "/think"

    Args:
        provider: Provider name (uses default if not specified).
        model: Model name (uses default if not specified).

    Returns:
        The trigger string (e.g. ``"/think"``) or ``None`` when not
        configured. ``None`` means "do not modify the system prompt".
    """
    if provider is None:
        provider = get_default_provider()
    if model is None:
        model = get_default_model(provider)

    config_path = find_config_file()
    if not config_path:
        return None

    json_config = _load_json_config(config_path)
    provider_config = json_config.get("providers", {}).get(provider, {})

    # Provider-level default.
    trigger = provider_config.get("reasoning_trigger")

    # Model-level override.
    models = provider_config.get("models", {})
    model_config = models.get(model, {})
    if "reasoning_trigger" in model_config:
        trigger = model_config["reasoning_trigger"]

    if trigger is None or not isinstance(trigger, str) or not trigger.strip():
        return None
    return trigger.strip()



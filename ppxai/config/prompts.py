"""
System prompt configuration.

Depends on providers.py (for get_default_provider).
"""

from .loader import _load_json_config, find_config_file
from .providers import get_default_provider

# =============================================================================
# Default System Prompts
# =============================================================================

DEFAULT_SYSTEM_PROMPTS = {
    "global": (
        "You are a helpful AI assistant. Be concise and direct in your responses. "
        "When using tools, report results briefly without unnecessary elaboration."
    ),
    "perplexity": (
        "You are a helpful AI assistant with web search capabilities. "
        "Be concise. Cite sources as markdown links. "
        "For tool results, report essential information only."
    ),
    "gemini": (
        "You are a helpful AI assistant. Be concise and direct. "
        "When using tools, report results briefly. "
        "For web searches, cite sources as markdown links."
    ),
    "openai": (
        "You are a helpful AI assistant. Be concise and direct. "
        "When using tools, report results briefly without elaboration."
    ),
    "custom": (
        "You are a helpful AI coding assistant. Be concise and direct. "
        "When executing tools, report only the essential results. "
        "Avoid lengthy explanations unless explicitly requested."
    ),
}


def get_system_prompt(provider: str = None) -> str:
    """Get the system prompt for the specified provider."""
    if provider is None:
        provider = get_default_provider()

    config_path = find_config_file()
    if config_path:
        json_config = _load_json_config(config_path)

        provider_config = json_config.get("providers", {}).get(provider, {})
        if provider_config.get("system_prompt"):
            return provider_config["system_prompt"]

        if json_config.get("system_prompt"):
            return json_config["system_prompt"]

    return DEFAULT_SYSTEM_PROMPTS.get(provider, DEFAULT_SYSTEM_PROMPTS["global"])


def get_system_prompt_mode(provider: str = None) -> str:
    """Get the system prompt mode for the specified provider."""
    if provider is None:
        provider = get_default_provider()

    config_path = find_config_file()
    if config_path:
        json_config = _load_json_config(config_path)

        provider_config = json_config.get("providers", {}).get(provider, {})
        if provider_config.get("system_prompt_mode"):
            return provider_config["system_prompt_mode"]

        if json_config.get("system_prompt_mode"):
            return json_config["system_prompt_mode"]

    return "prepend"

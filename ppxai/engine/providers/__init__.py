"""
Provider registry and factory.

Providers are dynamically registered and can be retrieved by name.
"""

from typing import Dict, List, Optional, Type

from .base import BaseProvider

# Provider registry - all providers inherit from BaseProvider (v1.16.0)
_providers: dict[str, type[BaseProvider]] = {}


def register_provider(name: str, provider_class: type):
    """Register a provider implementation."""
    _providers[name] = provider_class


def get_provider_class(name: str) -> type | None:
    """Get a provider class by name."""
    return _providers.get(name)


def create_provider(name: str, **kwargs) -> BaseProvider | None:
    """Create an instance of a provider by name.

    Args:
        name: Provider name (e.g., "openai", "custom", "perplexity")
        **kwargs: Provider-specific arguments (api_key, base_url, models, etc.)

    Returns:
        Provider instance or None if not found
    """
    provider_class = _providers.get(name)
    if provider_class is None:
        return None
    # Pass provider_id so provider can look up config (generation_params, max_tokens, etc.)
    return provider_class(provider_id=name, **kwargs)


def list_registered_providers() -> list[str]:
    """List all registered provider names."""
    return list(_providers.keys())


# Import and register built-in providers
# These imports trigger the registration via decorators or explicit calls
from .gemini import GeminiProvider

# Try to import native Gemini provider (optional dependency)
# Falls back to OpenAI-compatible provider if google-genai not installed
from .gemini import is_available as gemini_available  # noqa: E402
from .openai_compat import OpenAICompatibleProvider  # noqa: E402 — must follow register_provider

# Import native OpenAI provider
from .openai_native import OpenAINativeProvider  # noqa: E402
from .perplexity import PerplexityProvider  # noqa: E402

# Register providers
register_provider("openai", OpenAINativeProvider)
register_provider("perplexity", PerplexityProvider)
register_provider("local", OpenAICompatibleProvider)
register_provider("custom", OpenAICompatibleProvider)

# Use native Gemini provider if google-genai package is installed
if gemini_available():
    register_provider("gemini", GeminiProvider)
else:
    # Fall back to OpenAI-compatible provider
    register_provider("gemini", OpenAICompatibleProvider)

__all__ = [
    "BaseProvider",
    "OpenAICompatibleProvider",
    "OpenAINativeProvider",
    "PerplexityProvider",
    "GeminiProvider",
    "register_provider",
    "get_provider_class",
    "create_provider",
    "list_registered_providers",
]

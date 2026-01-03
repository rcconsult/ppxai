"""
Provider registry and factory.

Providers are dynamically registered and can be retrieved by name.
"""

from typing import Dict, Type, Optional, List, Union
from .base import BaseProvider

# Provider registry - supports both BaseProvider subclasses and native providers
_providers: Dict[str, Type] = {}


def register_provider(name: str, provider_class: Type):
    """Register a provider implementation."""
    _providers[name] = provider_class


def get_provider_class(name: str) -> Optional[Type]:
    """Get a provider class by name."""
    return _providers.get(name)


def create_provider(name: str, **kwargs) -> Optional[Union[BaseProvider, "GeminiProvider"]]:
    """Create an instance of a provider by name."""
    provider_class = _providers.get(name)
    if provider_class is None:
        return None
    return provider_class(**kwargs)


def list_registered_providers() -> List[str]:
    """List all registered provider names."""
    return list(_providers.keys())


# Import and register built-in providers
# These imports trigger the registration via decorators or explicit calls
from .openai_compat import OpenAICompatibleProvider
from .perplexity import PerplexityProvider

# Try to import native Gemini provider (optional dependency)
# Falls back to OpenAI-compatible provider if google-genai not installed
from .gemini import is_available as gemini_available, GeminiProvider

# Register providers
register_provider("openai", OpenAICompatibleProvider)
register_provider("perplexity", PerplexityProvider)
register_provider("openrouter", OpenAICompatibleProvider)
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
    "PerplexityProvider",
    "GeminiProvider",
    "register_provider",
    "get_provider_class",
    "create_provider",
    "list_registered_providers",
]

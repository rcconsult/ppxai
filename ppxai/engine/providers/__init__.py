"""
Provider registry and factory (ADR 0016 §1–§2).

The registry is a declared table, not a set of imports: a provider's module,
and with it its SDK, is imported only when that provider is first created or
its class is asked for. `load_provider_class` is the one place that imports
a provider module; the table is the dependency list, so every module named
here must also be in the PyInstaller specs' `hiddenimports` (fenced by
`tests/test_provider_registry.py`).
"""

import importlib
import sys

from .base import BaseProvider

#: Registered provider name -> (module, class).
_PROVIDER_MODULES: dict[str, tuple[str, str]] = {
    "openai": ("ppxai.engine.providers.openai_native", "OpenAINativeProvider"),
    "gemini": ("ppxai.engine.providers.gemini", "GeminiProvider"),
    "anthropic": ("ppxai.engine.providers.anthropic", "AnthropicProvider"),
    "local": ("ppxai.engine.providers.openai_compat", "OpenAICompatibleProvider"),
    "custom": ("ppxai.engine.providers.openai_compat", "OpenAICompatibleProvider"),
}

#: Any configured name not in the table (openrouter, nvidia, ollama, ...).
_FALLBACK: tuple[str, str] = ("ppxai.engine.providers.openai_compat", "OpenAICompatibleProvider")

#: Classes loaded so far, by provider name. `None` = registered in the table
#: but unavailable here (its optional SDK is missing).
_loaded: dict[str, type[BaseProvider] | None] = {}


def _import(entry: tuple[str, str]):
    """Import a table entry's module: the ONE provider-module import site."""
    return importlib.import_module(entry[0])


def fallback_provider_class() -> type[BaseProvider]:
    """The class that serves any name the table does not know."""
    return getattr(_import(_FALLBACK), _FALLBACK[1])


def _registered_class(name: str) -> type[BaseProvider] | None:
    """The class registered under `name`, or None if there is none here."""
    if name in _loaded:
        return _loaded[name]
    entry = _PROVIDER_MODULES.get(name)
    if entry is None:
        return None
    module = _import(entry)
    cls = getattr(module, entry[1])
    is_available = getattr(module, "is_available", None)
    if is_available is not None and not is_available():
        if name == "gemini":
            # Without google-genai, Gemini is served over its OpenAI-compatible
            # endpoint.
            cls = fallback_provider_class()
        else:
            # Anthropic has NO OpenAI-compatible fallback registered: it speaks
            # the `messages` wire and nothing else, so it stays unregistered
            # without its SDK.
            cls = None
    _loaded[name] = cls
    return cls


def load_provider_class(name: str) -> type[BaseProvider]:
    """The class that serves provider `name`, importing its module on first use.

    The registered class, or `OpenAICompatibleProvider` for a name the table
    does not know (or a registered provider whose SDK is missing and that has
    no class of its own without it).
    """
    cls = _registered_class(name)
    return cls if cls is not None else fallback_provider_class()


def is_loaded(name: str) -> bool:
    """Whether serving `name` needs no module import any more."""
    if name in _loaded:
        return True
    return _PROVIDER_MODULES.get(name, _FALLBACK)[0] in sys.modules


def get_provider_class(name: str) -> type[BaseProvider] | None:
    """The REGISTERED class for `name`, or None for a type-based name."""
    return _registered_class(name)


def create_provider(name: str, **kwargs) -> BaseProvider:
    """Create an instance of a provider by name.

    Args:
        name: Provider name (e.g., "openai", "gemini", "openrouter")
        **kwargs: Provider-specific arguments (api_key, base_url, models, etc.)

    Returns:
        An instance of `load_provider_class(name)`.
    """
    # Pass provider_id so provider can look up config (generation_params, max_tokens, etc.)
    return load_provider_class(name)(provider_id=name, **kwargs)


def list_registered_providers() -> list[str]:
    """List all registered provider names available here."""
    return [name for name in _PROVIDER_MODULES if _registered_class(name) is not None]


__all__ = [
    "BaseProvider",
    "load_provider_class",
    "fallback_provider_class",
    "is_loaded",
    "get_provider_class",
    "create_provider",
    "list_registered_providers",
]

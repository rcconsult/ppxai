"""Provider facts that can be read without loading a provider SDK (ADR 0016 §3).

ADR 0012 put per-model facts on the provider class, and three callers read
them without creating a provider: the facts resolver, the `/task`
authorizer's tool-capable-model hint and the `/provider` listing. Reading a
class attribute means importing the class's module, and with it the SDK.
The facts now live here, in modules that import no SDK, and each provider
class assigns its attributes from them, so ADR 0012's resolution order is
unchanged.

**No module in this package may import a provider SDK, a provider
implementation module, or `providers.base`.** Fenced by
`tests/test_provider_sdk_free_modules.py`.
"""

from importlib.util import find_spec

from . import anthropic, gemini, openai_compat, openai_native
from ._record import ProviderFacts

#: Registered provider name -> its facts. Mirrors the registry in
#: `providers/__init__.py`; `tests/test_provider_sdk_free_modules.py`
#: holds the two to the same answer.
_FACTS: dict[str, ProviderFacts] = {
    "openai": openai_native.FACTS,
    "gemini": gemini.FACTS,
    "anthropic": anthropic.FACTS,
    "local": openai_compat.FACTS,
    "custom": openai_compat.FACTS,
}

#: Any configured name not in the table (openrouter, nvidia, ollama, ...) is
#: served by `OpenAICompatibleProvider`.
_FALLBACK = openai_compat.FACTS

#: Providers served by their own class only when their SDK is installed.
#: Without it the registry gives `gemini` the OpenAI-compatible class and
#: leaves `anthropic` unregistered, and both then resolve to the fallback.
_NEEDS_SDK: dict[str, str] = {
    "gemini": "google.genai",
    "anthropic": "anthropic",
}


def _sdk_installed(module: str) -> bool:
    """Whether `module` can be imported, found without importing it."""
    try:
        return find_spec(module) is not None
    except (ImportError, ValueError):
        # A missing parent package (`google`) raises instead of returning None.
        return False


def get_provider_facts(name: str) -> ProviderFacts:
    """The facts of the class that serves provider `name`.

    The same class `FactsResolver.provider_class` resolves, without
    importing it: the registered provider's own facts, or the
    OpenAI-compatible fallback for an unregistered name or a provider whose
    SDK is missing.
    """
    sdk = _NEEDS_SDK.get(name)
    if sdk is not None and not _sdk_installed(sdk):
        return _FALLBACK
    return _FACTS.get(name, _FALLBACK)


__all__ = ["ProviderFacts", "get_provider_facts"]

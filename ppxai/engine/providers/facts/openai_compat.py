"""Facts for `OpenAICompatibleProvider` (ADR 0016 §3). No SDK import.

Also the facts for every configured name that is not a registered provider
(openrouter, nvidia, a vLLM or Ollama host), and for `gemini` or `anthropic`
when their SDK is missing.
"""

from ...types import ProviderCapabilities
from ._record import ProviderFacts

FACTS = ProviderFacts(
    default_capabilities=ProviderCapabilities(
        web_search=False,
        web_fetch=False,
        weather=False,
        citations=False,
        streaming=True,
    ),
)

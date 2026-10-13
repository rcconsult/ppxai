"""Facts for `AnthropicProvider` (ADR 0016 §3). No SDK import."""

from ...model_facts import ModelFacts
from ...types import ProviderCapabilities
from ._record import ProviderFacts

#: Streaming default. The guidance for agentic work is 64k, and a low cap is
#: not a cost control: hitting it truncates mid-thought and buys a retry,
#: so cost per COMPLETED task gets worse, not better.
DEFAULT_MAX_TOKENS = 64000

FACTS = ProviderFacts(
    #: Stands in when a caller builds a config with no target model.
    default_model_for_facts="claude-opus-5",
    #: An UNLISTED Claude model still speaks `messages` — this provider has
    #: no other wire. The global floor says `chat_completions`, which is safe
    #: everywhere else and simply wrong here, so this supplies its own
    #: complete floor (ADR 0012 §2 Q0e), exactly as Gemini does.
    #:
    #: `tool_mode` stays at the conservative default: the wire is a fact
    #: about the endpoint, tool support is a fact about the model, and only
    #: the first is knowable without measuring.
    unmeasured_facts=ModelFacts(wire_protocol="messages"),
    #: Per-model rows, consulted BEFORE the global shipped table. Every
    #: current Claude model is native-tool-capable over `messages` and
    #: supports vision and reasoning.
    shipped_model_facts={
        "claude-*": ModelFacts(
            wire_protocol="messages",
            tool_mode="native",
            parallel_tool_calls=True,
            supports_reasoning=True,
            supports_vision=True,
            max_tokens=DEFAULT_MAX_TOKENS,
        ),
    },
    default_capabilities=ProviderCapabilities(
        web_search=False,   # server-side web_search is a per-request tool, not an account fact
        web_fetch=False,
        weather=False,
        citations=False,
        streaming=True,
    ),
)

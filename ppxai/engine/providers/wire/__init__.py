"""Wire-protocol handlers (ADR 0012).

A provider owns an *account* — a key, a base URL, a price table. A handler
owns a *wire* — how messages become a request and how a response becomes
events. `ModelFacts.wire_protocol` picks the handler per model, so one
account can speak several protocols (OpenAI already does: Chat Completions
for most models, Responses for Codex/Pro).

Handlers are registered here rather than imported directly by providers, so
a provider declares the set it can speak and routing does the lookup.

All three live wires are registered here as of W4. Each owns its own
`convert_messages` with its own return type — `List[Dict]` for
chat-completions, `(instructions, input_items)` for responses,
`(contents, system_instruction)` for generate_content — which is why the
contract types that return `Any`: pretending they share one shape is what
produced the Liskov violation debt Item 62 (b) records. `messages` (the
Anthropic wire) joins them with `feat/anthropic-provider`.
"""

from typing import Dict

from .chat_completions import ChatCompletionsHandler
from .generate_content import GenerateContentHandler
from .protocol import ProtocolHandler
from .responses import ResponsesHandler


#: name -> handler instance. Handlers are stateless, so one shared instance
#: per protocol is correct; per-request state lives in the arguments.
HANDLERS: Dict[str, ProtocolHandler] = {
    ChatCompletionsHandler.name: ChatCompletionsHandler(),
    GenerateContentHandler.name: GenerateContentHandler(),
    ResponsesHandler.name: ResponsesHandler(),
}


def get_handler(name: str) -> ProtocolHandler:
    """Look up a handler by `ModelFacts.wire_protocol` value.

    Raises `KeyError` for an unregistered protocol rather than falling back
    to a default. A silent fallback is what let `api_path` sit inert for
    three releases (debt Item 61): the value was declared, nothing consumed
    it, and nothing complained. An unknown protocol here is a config or
    table error and should say so.
    """
    try:
        return HANDLERS[name]
    except KeyError:
        raise KeyError(
            f"no wire-protocol handler registered for {name!r}; "
            f"known protocols: {sorted(HANDLERS)}"
        ) from None


__all__ = [
    "ProtocolHandler",
    "ChatCompletionsHandler",
    "GenerateContentHandler",
    "ResponsesHandler",
    "HANDLERS",
    "get_handler",
]

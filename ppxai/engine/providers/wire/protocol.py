"""The wire-protocol handler contract (ADR 0012 §1).

A `ProtocolHandler` owns one wire format end to end: how a `Message` list
becomes that wire's request shape, and how a request is issued and its
response turned back into `Event`s. A provider owns an *account* — a key, a
base URL, a price table — and delegates the wire to a handler chosen per
model by `ModelFacts.wire_protocol`.

Following `docs/patterns/protocol-dependency-inversion.md`: a structural
`Protocol` declared in the leaf module that the handlers and their hosts both
depend on, so neither imports the other and no `TYPE_CHECKING` is needed.

`convert_messages` belongs here rather than on `BaseProvider` because message
conversion *is* protocol-specific — every protocol already routed around the
base method, and Gemini overrode it with an incompatible return type to do so
(debt Item 62). Its return type is deliberately `Any`: each wire's shape is
its own (`List[Dict]` for chat-completions, `(instructions, input_items)` for
responses, `(contents, system_instruction)` for generate_content), and
pretending they share one type is what produced that Liskov violation.
"""

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from ...types import Event, Message


@runtime_checkable
class ProtocolHandler(Protocol):
    """One wire format. Stateless with respect to the conversation.

    `ctx` is deliberately NOT "an OpenAI SDK client" — it is whatever the
    handler needs from its host, and the client type is the handler's own
    business. The `responses` handler needs a client plus `enable_web_search`
    and the host's token/extra-body lookups; `generate_content` will need a
    google-genai client instead. Specifying it as a host object rather than a
    client is the one part that would be expensive to relax later.
    """

    #: Matches `ModelFacts.wire_protocol`; the key routing selects on.
    name: str

    def convert_messages(self, messages: list[Message]) -> Any:
        """Engine messages -> this wire's request shape."""
        ...

    def chat(
        self,
        ctx: Any,
        messages: list[Message],
        model: str,
        stream: bool = True,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Event]:
        """Streaming or non-streaming turn, emitted as engine events."""
        ...

    def oneshot(
        self,
        ctx: Any,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Stateless single turn -> {content, finish_reason, model, usage}."""
        ...

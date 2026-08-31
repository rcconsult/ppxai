"""OpenAI Chat Completions (`/chat/completions`) as a wire-protocol handler.

The most widely spoken of the four wires: OpenAI, Perplexity's Sonar, and
every OpenAI-compatible endpoint (OpenRouter, NVIDIA, vLLM, Ollama, …).

**Why this exists as a handler at all (ADR 0012 W4, debt Item 62 (b)).**
Message conversion for this wire used to live on `BaseProvider` as
`_convert_messages`, which made one protocol's emitter the shared base's
default. Two consequences followed, and both were live:

- Every other protocol had to route *around* the base method rather than
  through it, and `GeminiProvider` overrode it with an **incompatible return
  type** (`tuple`, not `List[Dict]`) to do so — a Liskov violation the type
  checker could not see because the base's own annotation was the narrow one.
- ADR 0006's `assert_wire_blocks_clean` sat inside that method, so the
  validator covered exactly one wire while the other two reached the network
  unchecked.

Conversion is protocol-specific, so it belongs to the protocol. With each
wire owning its own converter there is no shared method to disagree about,
and the validator travels with the conversion instead of with the base class.
"""

from typing import Any

from ...types import Message
from ...uploaded_file import assert_wire_blocks_clean, flatten_uploaded_file_blocks


class ChatCompletionsHandler:
    """The `chat_completions` wire.

    Conversion only, for now. The send paths still live on their providers:
    `openai_native._chat_completions_api`, `openai_compat.chat` and
    Perplexity's own `chat` each do provider-specific work around the
    request (citations, reasoning extraction, throttle classification,
    prompt-based tool parsing) that is genuinely the account's business, not
    the wire's. Moving conversion first is what closes Item 62; moving the
    send paths is a separate change with its own risk, and pretending
    otherwise would make this "extraction" a rewrite.
    """

    name = "chat_completions"

    @staticmethod
    def convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
        """Convert Message objects to Chat Completions format.

        R5 (v1.17.6): any `uploaded_file` content blocks are flattened
        back to their legacy `<uploaded_file>` text-marker form before
        shaping the API request. Providers (OpenAI, Perplexity, and any
        OpenAI-compatible endpoint) would reject an unknown block type
        outright, so the structured type is an engine-internal schema
        only. The flatten uses `format_uploaded_file_reference` under
        the hood, so the LLM sees byte-identical strings whether the
        producer emitted a legacy text marker (pre-R5) or a structured
        block flattened here.

        Args:
            messages: List of Message objects

        Returns:
            List of dicts with 'role', 'content', and optional tool fields
        """
        result = []
        for m in messages:
            content = flatten_uploaded_file_blocks(m.content)
            # ADR 0006 Step 6 wire validator — `__debug__`-gated assertion
            # that catches producer-side regressions (non-spec keys inside
            # content blocks). Production builds with `python -O` strip
            # this. Tests and dev builds get a loud failure naming the
            # role + block + offending keys.
            assert_wire_blocks_clean(content, role=m.role)
            msg: dict[str, Any] = {"role": m.role, "content": content}
            if m.tool_calls:
                msg["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            result.append(msg)
        return result

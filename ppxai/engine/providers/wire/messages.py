"""Anthropic Messages (`/v1/messages`) as a wire-protocol handler.

The fourth wire, and the slot `WireProtocol` has reserved since ADR 0012 W4
(`Literal[..., "messages"]` with nothing registered against it). A provider
owns an *account*; this owns the *format*.

**Why this wire is not chat-completions with different names.** Three shape
differences make a translation layer the wrong tool:

- **`system` is a request parameter, not a message role.** Anthropic rejects
  `{"role": "system"}` inside `messages`. So `convert_messages` returns a
  `(system, messages)` tuple — the same move `generate_content` makes for
  `system_instruction`, and the reason `ProtocolHandler.convert_messages` is
  typed `Any` rather than pretending the four wires share a return type.
- **Tool results are user-turn content blocks**, not a `tool` role. An
  OpenAI `{"role": "tool", "tool_call_id": X}` message becomes a
  `{"type": "tool_result", "tool_use_id": X}` block inside a `user` message,
  and consecutive results must be merged into ONE user turn — splitting them
  across messages trains the model out of parallel tool calls.
- **Tool calls are assistant content blocks.** OpenAI's sidecar
  `tool_calls` array becomes `{"type": "tool_use", ...}` blocks alongside the
  text, and the arguments are a decoded object rather than a JSON string.

**Images.** Engine content carries OpenAI-style `image_url` parts. Anthropic
takes `{"type": "image", "source": {...}}` with base64 split into
`media_type` + `data`, or a `url` source. Both are handled here; a data URL
that does not parse is dropped with a warning rather than sent, because an
malformed source is a 400 for the whole request, not a degraded image.
"""

import base64
import binascii
import json
import re
from typing import Any

from ....common.logger import get_logger
from ...types import Message
from ...uploaded_file import assert_wire_blocks_clean, flatten_uploaded_file_blocks

logger = get_logger("provider")

#: `data:image/png;base64,iVBORw0…` -> ("image/png", "iVBORw0…")
_DATA_URL = re.compile(r"^data:(?P<media_type>[^;,]+);base64,(?P<data>.+)$", re.DOTALL)


class MessagesHandler:
    """The `messages` wire (Anthropic).

    Conversion only, matching `ChatCompletionsHandler`. The send path lives
    on `AnthropicProvider` because streaming, throttle classification and
    usage parsing are the account's business — and because doing the send
    here first would make this an extraction in name only.
    """

    name = "messages"

    @staticmethod
    def convert_messages(
        messages: list[Message],
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Engine messages -> `(system, messages)` for the Anthropic wire.

        `system` is returned separately because it is a request parameter.
        Multiple system messages are joined with blank lines rather than
        last-one-wins: an engine that injected bootstrap context AND a
        per-session instruction means both, and silently dropping one would
        be a behaviour change no caller asked for.
        """
        system_parts: list[str] = []
        result: list[dict[str, Any]] = []

        for m in messages:
            content = flatten_uploaded_file_blocks(m.content)
            # ADR 0006 Step 6 wire validator, same as every other wire —
            # `__debug__`-gated, stripped by `python -O`, loud in tests.
            assert_wire_blocks_clean(content, role=m.role)

            if m.role == "system":
                text = _as_text(content)
                if text:
                    system_parts.append(text)
                continue

            if m.role == "tool":
                # A tool result is a content block on a USER turn. Merge into
                # the previous user turn when there is one, so parallel calls
                # come back in a single message — returning them as separate
                # messages is what teaches the model to stop calling in
                # parallel.
                block = {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id or "",
                    "content": _as_text(content),
                }
                if result and result[-1]["role"] == "user" and isinstance(
                    result[-1].get("content"), list
                ):
                    result[-1]["content"].append(block)
                else:
                    result.append({"role": "user", "content": [block]})
                continue

            blocks = _content_blocks(content)

            if m.role == "assistant" and m.tool_calls:
                for call in m.tool_calls:
                    fn = call.get("function", {})
                    blocks.append({
                        "type": "tool_use",
                        "id": call.get("id", ""),
                        "name": fn.get("name", ""),
                        # Anthropic takes a decoded object; OpenAI carries a
                        # JSON *string*. A malformed string is the model's
                        # output, not ours — send `{}` rather than raising.
                        "input": _decode_arguments(fn.get("arguments")),
                    })

            if not blocks:
                # An empty content list is a 400 on this wire. The
                # transcript-integrity work upstream (v1.19.1) already
                # filters empty assistant turns, but a provider that
                # depends on that invariant being enforced elsewhere is a
                # provider that breaks when it is not.
                continue

            result.append({"role": m.role, "content": blocks})

        system = "\n\n".join(system_parts) if system_parts else None
        return system, result


def _decode_arguments(raw: Any) -> dict[str, Any]:
    """OpenAI tool-call `arguments` (a JSON string) -> Anthropic `input`."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning(f"tool-call arguments were not valid JSON; sending {{}}: {raw!r:.120}")
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _as_text(content: Any) -> str:
    """Best-effort plain text from either content shape."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content) if content is not None else ""


def _content_blocks(content: Any) -> list[dict[str, Any]]:
    """OpenAI-style content -> Anthropic content blocks."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []

    if not isinstance(content, list):
        text = str(content) if content is not None else ""
        return [{"type": "text", "text": text}] if text else []

    blocks: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")

        if kind == "text":
            if part.get("text"):
                blocks.append({"type": "text", "text": part["text"]})

        elif kind == "image_url":
            image = _image_block(part.get("image_url") or {})
            if image is not None:
                blocks.append(image)

    return blocks


def _image_block(image_url: dict[str, Any]) -> dict[str, Any] | None:
    """One OpenAI `image_url` part -> one Anthropic `image` block.

    Returns None (and warns) for anything that would make the whole request
    a 400. Dropping one image degrades the turn; sending a malformed source
    loses it entirely.
    """
    url = image_url.get("url")
    if not isinstance(url, str) or not url:
        return None

    match = _DATA_URL.match(url)
    if match is None:
        return {"type": "image", "source": {"type": "url", "url": url}}

    data = match.group("data")
    try:
        # Validate rather than trust: a truncated base64 payload is a 400
        # for the entire request, and the message it returns names the
        # request, not the image.
        base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        logger.warning("dropping an image whose data URL is not valid base64")
        return None

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": match.group("media_type"),
            "data": data,
        },
    }

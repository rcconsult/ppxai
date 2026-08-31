"""Google Gemini `generateContent` as a wire-protocol handler.

The third wire, and the one that proves the contract had to be shaped the way
ADR 0012 §1 shapes it. Gemini's request is not a message list at all — it is
`(contents, system_instruction)`, with `user`/`model` roles rather than
`user`/`assistant`, `parts` arrays rather than string content, and native
tool round-trips carried as `function_call` / `function_response` parts.

**This is why `convert_messages` returns `Any` (debt Item 62 (b)).** While
conversion lived on `BaseProvider` typed as `-> List[Dict[str, Any]]`,
`GeminiProvider` had to override it returning a `tuple` — a Liskov violation
the type checker could not see, because the base's annotation was one
protocol's shape imposed on all of them. Each wire now owns its converter and
declares its own return type; there is no shared method left to disagree
about.

**The pairing hazard, preserved verbatim.** Gemini's wire has NO tool-call id
on a function response — pairing is by function NAME — so the id→name mapping
is resolved from the preceding assistant turn. A tool result whose id cannot
be resolved falls back to a plain user text turn rather than an invalid
`function_response`. That logic moved unchanged; it is the reason this
conversion cannot be shared with the OpenAI-shaped wires even in principle.
"""

import base64
import json
import logging
from typing import Any, Dict, List

from ...types import Message
from ...uploaded_file import assert_wire_blocks_clean, flatten_uploaded_file_blocks


logger = logging.getLogger(__name__)


class GenerateContentHandler:
    """The `generate_content` wire.

    Conversion only, as with `chat_completions`: `GeminiProvider`'s send
    paths do genuinely provider-specific work (thought signatures, grounding
    metadata, its own streaming envelope) that belongs to the account rather
    than the wire. Moving conversion is what closes Item 62; moving the send
    paths is a separate change with its own risk.
    """

    name = "generate_content"

    @staticmethod
    def convert_messages(messages: List[Message]) -> tuple:
        """Convert Message objects to Gemini format.

        Gemini uses a different format than OpenAI:
        - 'user' and 'model' roles (not 'assistant')
        - 'parts' array instead of 'content' string
        - System messages become system_instruction in config
        - Native tool round-trips use function_call / function_response
          parts instead of OpenAI's tool_calls / tool-role messages

        The engine's native pairing branch (engine/chat.py) records tool
        round-trips as an assistant message carrying `tool_calls` followed
        by tool-role messages carrying `tool_call_id`. Gemini's wire format
        has no id field on function responses — pairing is by function
        NAME — so the id→name mapping is resolved here from the preceding
        assistant turn. A tool result whose id can't be resolved falls back
        to a plain user text turn rather than an invalid function_response.

        Args:
            messages: List of Message objects

        Returns:
            Tuple of (contents list, system_instruction string or None)
        """
        contents = []
        system_parts = []
        call_id_to_name: Dict[str, str] = {}

        if not messages:
            return contents, None

        for m in messages:
            # ADR 0006 Step 6 sentinel — the THIRD and final call site
            # (ADR 0012 W4; debt Item 62 (a) fully closed). Before W2 the
            # validator ran on ONE wire, so two of three reached the network
            # unchecked. It now travels with each converter, which is where
            # it always belonged. Placed at the top of the loop rather than
            # inside `_content_to_gemini_parts` because the role is the
            # diagnostic half of the message and only exists here — and
            # because system messages take the `text_content()` path that
            # never reaches the parts helper at all.
            # `__debug__`-gated: no cost under -O.
            assert_wire_blocks_clean(m.content, role=m.role)

            if m.role == "system":
                # Collect system messages for system_instruction. Gemini's
                # system_instruction is text-only, so flatten any multimodal
                # content to its text representation.
                system_parts.append(m.text_content())
            elif m.role == "assistant" and m.tool_calls:
                parts: List[Dict[str, Any]] = []
                text = m.text_content()
                if text and text.strip():
                    parts.append({"text": text})
                for tc in m.tool_calls:
                    func = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                    name = func.get("name", "")
                    if not name:
                        continue
                    args = GenerateContentHandler._parse_tool_call_arguments(func.get("arguments"))
                    call_id = tc.get("id")
                    if call_id:
                        call_id_to_name[call_id] = name
                    fc_part: Dict[str, Any] = {
                        "function_call": {"name": name, "args": args}
                    }
                    # Item 45: Gemini 3.x REQUIRES the signature it issued with
                    # this call to come back on the functionCall part, or the
                    # whole request 400s ("missing a thought_signature in
                    # functionCall parts"). 2.5 never sets it → key absent →
                    # unchanged behaviour there.
                    sig = GenerateContentHandler._decode_thought_signature(
                        tc.get("thought_signature") if isinstance(tc, dict) else None
                    )
                    if sig:
                        fc_part["thought_signature"] = sig
                    parts.append(fc_part)
                if parts:
                    contents.append({"role": "model", "parts": parts})
            elif m.role == "tool":
                name = call_id_to_name.get(m.tool_call_id or "")
                if name:
                    contents.append({
                        "role": "user",
                        "parts": [{
                            "function_response": {
                                "name": name,
                                "response": {"result": m.text_content()},
                            }
                        }],
                    })
                else:
                    # Unpaired tool result (e.g. restored session that lost
                    # the assistant turn) — degrade to a plain user turn.
                    contents.append({
                        "role": "user",
                        "parts": GenerateContentHandler._content_to_gemini_parts(m.content),
                    })
            else:
                role = "model" if m.role == "assistant" else "user"
                contents.append({
                    "role": role,
                    "parts": GenerateContentHandler._content_to_gemini_parts(m.content),
                })

        # Combine all system messages into one instruction
        system_instruction = "\n\n".join(system_parts) if system_parts else None
        return contents, system_instruction

    @staticmethod
    def _parse_tool_call_arguments(raw: Any) -> Dict[str, Any]:
        """Normalize a recorded tool-call `arguments` value to a dict.

        The engine stores arguments as a JSON string (OpenAI wire shape);
        Gemini's function_call part wants the structured dict. Malformed
        JSON degrades to {} — the call was already executed, the replayed
        part only needs to exist for transcript coherence.
        """
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw:
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _content_to_gemini_parts(content: Any) -> List[Dict[str, Any]]:
        """Convert Message.content to Gemini `parts` list.

        String content → single text part. List content (OpenAI multimodal
        format) → mix of `{"text": ...}` and `{"inline_data": {mime_type, data}}`
        parts. Data URIs (`data:image/png;base64,...`) are split into mime_type
        and base64 payload. Remote `http(s)://` URLs are unsupported — Gemini
        requires the caller to fetch and embed the bytes.

        R5 (v1.17.6): `uploaded_file` blocks are flattened to legacy
        text markers before the shape conversion, so the block-type
        walk below only has to know about `text` and `image_url`.
        """
        if isinstance(content, str):
            return [{"text": content}]
        if not isinstance(content, list):
            return [{"text": str(content)}]

        # R5: collapse any uploaded_file blocks to their legacy text form
        # before we walk the list. Keeps the block-type dispatch simple
        # and guarantees Gemini sees the exact same marker string it did
        # pre-R5.
        content = flatten_uploaded_file_blocks(content)

        parts: List[Dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append({"text": block.get("text", "")})
            elif btype == "image_url":
                url = (block.get("image_url") or {}).get("url", "")
                if url.startswith("data:"):
                    # data:image/png;base64,AAAA...
                    try:
                        header, data = url.split(",", 1)
                        mime_type = header[5:].split(";", 1)[0] or "image/png"
                    except ValueError:
                        # Malformed data URI — skip rather than crash.
                        continue
                    parts.append({
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": data,
                        }
                    })
                # Non-data URIs are silently skipped; the preprocessing layer
                # is responsible for inlining remote images before they reach
                # the provider.
        # Gemini rejects empty parts — fall back to a blank text part so the
        # turn stays valid even if every block was filtered out.
        if not parts:
            parts.append({"text": ""})
        return parts

    @staticmethod
    def _decode_thought_signature(sig):
        """Reverse `_thought_signature_of` for the outbound wire.

        The SDK types `Part.thought_signature` as `Optional[bytes]` and
        pydantic rejects a non-base64 str outright, so the value we stored
        (base64 text, for JSON-safety in the session transcript) must be
        decoded back to the ORIGINAL bytes before it goes out. Returns None
        when the value cannot be decoded, so a malformed signature degrades to
        "omit the field" rather than poisoning the whole request.
        """
        if not sig:
            return None
        if isinstance(sig, bytes):
            return sig
        try:
            return base64.b64decode(sig, validate=True)
        except Exception:
            return None

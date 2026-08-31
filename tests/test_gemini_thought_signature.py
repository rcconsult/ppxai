"""Gemini 3.x thought_signature round-trip + oneshot thought/answer split.

Covers two live-observed defects (2026-07-22, `gemini-3.1-pro-preview`):

**Item 45 — every native tool round-trip 400'd.** Gemini 3.x returns an opaque
`thought_signature` on each functionCall PART and rejects the follow-up turn
unless the client echoes it back:

    400 INVALID_ARGUMENT — Function call is missing a thought_signature in
    functionCall parts … `default_api:<tool>`, position N

Reproduced 3x across two trial sessions on two different tools (`read_file`,
`web_search`), i.e. tool-agnostic. The signature must survive the whole hop:
response part -> parsed call -> TOOL_CALL event -> session `tool_calls` entry
-> outbound functionCall part.

**Item 51 — reasoning leaked into the answer.** `chat()` has always split
`part.thought` into REASONING_CHUNK, but `oneshot()` concatenated every text
part, so `/agentrun` (which drives oneshot) returned the model's internal
monologue as the answer.

Gemini 2.5 sends neither field, so both fixes must be no-ops there.
"""

from __future__ import annotations

import ppxai.engine.providers.gemini as gm
from ppxai.engine.providers.gemini import GeminiProvider
from ppxai.engine.types import Message
from ppxai.engine.providers.wire.generate_content import GenerateContentHandler


def _provider() -> GeminiProvider:
    """Bare provider instance — we never touch the network in these tests."""
    return object.__new__(GeminiProvider)


class _FC:
    def __init__(self, name="read_file", args=None, id=None):
        self.name = name
        self.args = args if args is not None else {"path": "x"}
        self.id = id


class _Part:
    def __init__(self, function_call=None, thought_signature=None, text=None,
                 thought=False):
        if function_call is not None:
            self.function_call = function_call
        if thought_signature is not None:
            self.thought_signature = thought_signature
        if text is not None:
            self.text = text
        self.thought = thought


# ---------------------------------------------------------------------------
# Item 45 — inbound capture
# ---------------------------------------------------------------------------


class TestSignatureCapture:
    def test_signature_on_part_is_captured(self):
        p = _provider()
        fc = _FC(id="fc1")
        parsed = p._parse_function_call(fc, _Part(fc, thought_signature="SIG-1"))
        assert parsed["thought_signature"] == "SIG-1"

    def test_absent_signature_leaves_key_out(self):
        """Gemini 2.5 shape — the key must not appear at all."""
        p = _provider()
        fc = _FC(id="fc1")
        parsed = p._parse_function_call(fc, _Part(fc))
        assert "thought_signature" not in parsed

    def test_bytes_signature_is_base64_encoded_for_storage(self):
        """The session transcript is JSON, so raw bytes must be encoded."""
        p = _provider()
        fc = _FC(id="fc1")
        parsed = p._parse_function_call(fc, _Part(fc, thought_signature=b"\x00\x01\xff"))
        assert isinstance(parsed["thought_signature"], str)
        import json
        json.dumps(parsed)  # must not raise

    def test_missing_part_is_tolerated(self):
        """Older call sites may not pass the part; must not raise."""
        p = _provider()
        parsed = p._parse_function_call(_FC(id="fc1"))
        assert parsed["name"] == "read_file"
        assert "thought_signature" not in parsed


# ---------------------------------------------------------------------------
# Item 45 — outbound replay (the actual 400 fix)
# ---------------------------------------------------------------------------


class TestSignatureReplay:
    def _msgs(self, sig=None):
        call = {
            "id": "fc1",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path": "x"}'},
        }
        if sig:
            call["thought_signature"] = sig
        return [
            Message("assistant", "", tool_calls=[call]),
            Message("tool", "file contents", tool_call_id="fc1"),
        ]

    def test_signature_is_replayed_on_function_call_part(self):
        import base64
        original = b"sig-bytes-1"
        stored = base64.b64encode(original).decode("ascii")
        contents, _ = GenerateContentHandler.convert_messages(self._msgs(sig=stored))
        model_turn = contents[0]
        assert model_turn["role"] == "model"
        # Decoded back to the original bytes — the SDK types this as bytes.
        assert model_turn["parts"][0]["thought_signature"] == original
        # The call itself must still be intact.
        assert model_turn["parts"][0]["function_call"]["name"] == "read_file"

    def test_no_signature_means_no_key_on_the_wire(self):
        """Gemini 2.5 path must be byte-identical to pre-fix behaviour."""
        contents, _ = GenerateContentHandler.convert_messages(self._msgs())
        assert "thought_signature" not in contents[0]["parts"][0]

    def test_tool_result_still_pairs_by_name(self):
        """The Item 41 pairing contract must survive the change."""
        contents, _ = GenerateContentHandler.convert_messages(self._msgs(sig="SIG-1"))
        assert contents[1]["parts"][0]["function_response"]["name"] == "read_file"

    def test_stored_signature_is_decoded_back_to_the_original_bytes(self):
        """Storage is base64 text; the WIRE must carry the original bytes.

        Regression guard for the first fix attempt, which encoded on capture
        but never decoded on replay — the 400 survived because the SDK got a
        str where it types the field as bytes.
        """
        import base64
        original = b"\x01\x02\xff\xfe"
        stored = base64.b64encode(original).decode("ascii")
        contents, _ = GenerateContentHandler.convert_messages(self._msgs(sig=stored))
        assert contents[0]["parts"][0]["thought_signature"] == original

    def test_part_is_accepted_by_the_real_sdk_type(self):
        """Validate through google-genai itself, not our assumed shape.

        `Part.thought_signature` is Optional[bytes] and pydantic rejects a
        non-base64 str outright, so a shape that only satisfies our own dict
        assertions can still 400 in production. This is the check that would
        have caught the first attempt.
        """
        from google.genai import types

        import base64
        original = b"\x01\x02\xff\xfe"
        stored = base64.b64encode(original).decode("ascii")
        contents, _ = GenerateContentHandler.convert_messages(self._msgs(sig=stored))
        part = types.Part.model_validate(contents[0]["parts"][0])
        assert part.thought_signature == original
        assert part.function_call.name == "read_file"

    def test_malformed_signature_is_dropped_not_fatal(self):
        """A corrupt stored value must degrade to omitting the field."""
        contents, _ = GenerateContentHandler.convert_messages(self._msgs(sig="not-base64!!"))
        assert "thought_signature" not in contents[0]["parts"][0]


class TestEngineTransportHop:
    """The middle hop that broke the first two fix attempts.

    `chat_with_tools` rebuilds each native TOOL_CALL event into a parsed-call
    dict and then into the session's `tool_calls` entry. Both rebuilds list
    their keys explicitly, so a provider-opaque field is silently dropped
    unless carried deliberately. Capture and replay were BOTH correct while
    the live call still 400'd, because the value never survived the middle.
    """

    def test_parsed_call_rebuild_preserves_signature(self):
        """Mirrors chat.py's event -> parsed_calls rebuild."""
        event_data = {
            "tool": "read_file",
            "arguments": {"path": "x"},
            "tool_call_id": "fc1",
            "native": True,
            "thought_signature": "Et8ECtwE",
        }
        entry = {
            "tool": event_data["tool"],
            "arguments": event_data.get("arguments", {}),
            "tool_call_id": event_data.get("tool_call_id"),
        }
        if event_data.get("thought_signature"):
            entry["thought_signature"] = event_data["thought_signature"]
        assert entry["thought_signature"] == "Et8ECtwE"

    def test_session_tool_calls_entry_preserves_signature(self):
        """The engine's assistant-message rebuild must keep the field so the
        NEXT outbound turn can replay it."""
        import json

        from ppxai.engine.types import Message

        tc = {
            "tool": "read_file",
            "arguments": {"path": "x"},
            "tool_call_id": "fc1",
            "thought_signature": "Et8ECtwE",
        }
        entry = {
            "id": tc["tool_call_id"],
            "type": "function",
            "function": {
                "name": tc["tool"],
                "arguments": json.dumps(tc.get("arguments", {})),
            },
        }
        if tc.get("thought_signature"):
            entry["thought_signature"] = tc["thought_signature"]

        msg = Message("assistant", "", tool_calls=[entry])
        assert msg.tool_calls[0]["thought_signature"] == "Et8ECtwE"
        # And it must be JSON-serialisable for the session store.
        json.dumps(msg.tool_calls)


# ---------------------------------------------------------------------------
# Item 51 — oneshot must not return the monologue as the answer
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, parts):
        cand = type("C", (), {})()
        cand.content = type("X", (), {"parts": parts})()
        cand.finish_reason = "STOP"
        self.candidates = [cand]
        self.usage_metadata = None


def _oneshot_with(parts) -> dict:
    p = _provider()
    p.client = type("c", (), {
        "models": type("m", (), {
            "generate_content": staticmethod(lambda **kw: _Resp(parts))
        })()
    })()
    p.enable_grounding = False
    p._get_generation_params = lambda m: {}
    p._build_config = lambda **kw: None
    p._convert_messages = lambda msgs: ([], None)
    p._parse_usage = lambda u: None
    return p.oneshot("q", "gemini-3.1-pro-preview")


class TestOneshotThoughtSplit:
    def test_thought_part_excluded_from_content(self):
        out = _oneshot_with([
            _Part(text="My Thought Process: the user wants weather...", thought=True),
            _Part(text="Saturday: 31C, sunny."),
        ])
        assert out["content"] == "Saturday: 31C, sunny."
        assert "Thought Process" not in out["content"]

    def test_reasoning_is_exposed_separately(self):
        out = _oneshot_with([
            _Part(text="thinking...", thought=True),
            _Part(text="answer"),
        ])
        assert out["reasoning"] == "thinking..."

    def test_plain_response_unchanged_and_no_reasoning_key(self):
        """Gemini 2.5 / non-thinking models — untouched."""
        out = _oneshot_with([_Part(text="just the answer")])
        assert out["content"] == "just the answer"
        assert "reasoning" not in out

    def test_thought_only_response_falls_back_to_reasoning(self):
        """Never return an empty completion when the model only thought."""
        out = _oneshot_with([_Part(text="only thinking", thought=True)])
        assert out["content"] == "only thinking"

"""Item 41 — Gemini native tool-loop fidelity.

Before v1.19.0 the Gemini provider never emitted a `tool_call_id`, so the
engine's native tool-result pairing branch (engine/chat.py — one assistant
message carrying `tool_calls`, then N tool-role messages) was dead for
Gemini: every tool round-trip flattened through the synthetic
assistant/user text path ("I'll use the X tool…"), an off-label transcript
shape. These tests pin the fix:

1. `_parse_function_call` threads the SDK's `FunctionCall.id` when present
   and synthesizes one when absent — the engine requires every call to
   carry an id, but the id never goes back on the Gemini wire.
2. `chat()` TOOL_CALL events carry `tool_call_id` (both response modes).
3. `_convert_messages` maps the engine's native transcript shape onto
   Gemini's wire format: assistant `tool_calls` → model `function_call`
   parts; tool-role messages → user `function_response` parts paired by
   function NAME via the id→name mapping from the preceding model turn.
4. `_filter_empty_parts` (dead since a post-v1.15.3 refactor, see
   docs/known-issues.md KI-001) stays deleted.
"""

import json
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.types import Event, EventType, Message
from ppxai.engine.providers.wire.generate_content import GenerateContentHandler


def _fc(name: str, args: dict, call_id=None) -> SimpleNamespace:
    """Build a FunctionCall-shaped object (SDK pydantic model stand-in)."""
    return SimpleNamespace(name=name, args=args, id=call_id)


def _response_with_function_call(fc) -> Any:
    """Non-streaming Gemini response with a single function_call part."""
    part = MagicMock()
    part.text = None
    part.thought = False
    part.function_call = fc

    candidate = MagicMock()
    candidate.content.parts = [part]
    candidate.grounding_metadata = None

    response = MagicMock()
    response.candidates = [candidate]
    response.usage_metadata = None
    return response


async def _drain(agen: AsyncIterator[Event]) -> list[Event]:
    return [ev async for ev in agen]


@pytest.fixture
def provider():
    from ppxai.engine.providers.gemini import GeminiProvider

    with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
        mock_genai.Client.return_value = MagicMock()
        return GeminiProvider(api_key="test")


class TestParseFunctionCallId:
    def test_sdk_id_is_threaded(self, provider):
        tc = provider._parse_function_call(_fc("read_file", {"path": "a.py"}, call_id="fc-123"))
        assert tc == {"name": "read_file", "arguments": {"path": "a.py"}, "tool_call_id": "fc-123"}

    def test_missing_id_is_synthesized_and_unique(self, provider):
        a = provider._parse_function_call(_fc("read_file", {}))
        b = provider._parse_function_call(_fc("read_file", {}))
        assert a["tool_call_id"].startswith("gemini-fc-")
        assert b["tool_call_id"].startswith("gemini-fc-")
        assert a["tool_call_id"] != b["tool_call_id"]

    def test_none_and_nameless_still_rejected(self, provider):
        assert provider._parse_function_call(None) is None
        assert provider._parse_function_call(_fc("", {})) is None


class TestChatEmitsToolCallId:
    @pytest.mark.asyncio
    async def test_non_streaming_tool_call_event_carries_id(self, provider):
        response = _response_with_function_call(_fc("shell", {"command": "ls"}, call_id="fc-7"))
        provider.client.models.generate_content = MagicMock(return_value=response)

        events = await _drain(
            provider.chat([Message("user", "list files")], model="gemini-2.5-flash", stream=False)
        )

        tool_events = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(tool_events) == 1
        assert tool_events[0].data["tool"] == "shell"
        assert tool_events[0].data["tool_call_id"] == "fc-7"
        assert tool_events[0].data["native"] is True

        # STREAM_END metadata mirrors the same id for session bookkeeping
        end = next(e for e in events if e.type == EventType.STREAM_END)
        assert end.metadata["tool_calls"][0]["tool_call_id"] == "fc-7"

    @pytest.mark.asyncio
    async def test_streaming_tool_call_event_carries_id(self, provider):
        chunk = MagicMock()
        part = MagicMock()
        part.text = None
        part.thought = False
        part.function_call = _fc("get_weather", {"city": "Geneva"}, call_id=None)
        chunk.candidates = [MagicMock()]
        chunk.candidates[0].content.parts = [part]
        chunk.candidates[0].grounding_metadata = None
        chunk.usage_metadata = None
        provider.client.models.generate_content_stream = MagicMock(return_value=iter([chunk]))

        events = await _drain(
            provider.chat([Message("user", "weather?")], model="gemini-2.5-flash", stream=True)
        )

        tool_events = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(tool_events) == 1
        assert tool_events[0].data["tool_call_id"].startswith("gemini-fc-")


class TestConvertMessagesNativeShape:
    """The engine records native round-trips as assistant(tool_calls) +
    tool(tool_call_id) messages; Gemini's wire pairs by function NAME."""

    def _native_transcript(self):
        return [
            Message("user", "read a.py"),
            Message("assistant", "", tool_calls=[{
                "id": "fc-1",
                "type": "function",
                "function": {"name": "read_file", "arguments": json.dumps({"path": "a.py"})},
            }]),
            Message("tool", "print('hi')", tool_call_id="fc-1"),
        ]

    def test_assistant_tool_calls_become_function_call_parts(self, provider):
        contents, _ = GenerateContentHandler.convert_messages(self._native_transcript())

        model_turn = contents[1]
        assert model_turn["role"] == "model"
        assert model_turn["parts"] == [
            {"function_call": {"name": "read_file", "args": {"path": "a.py"}}}
        ]

    def test_tool_result_becomes_function_response_paired_by_name(self, provider):
        contents, _ = GenerateContentHandler.convert_messages(self._native_transcript())

        tool_turn = contents[2]
        assert tool_turn["role"] == "user"
        assert tool_turn["parts"] == [{
            "function_response": {
                "name": "read_file",
                "response": {"result": "print('hi')"},
            }
        }]

    def test_no_synthetic_prose_in_native_transcript(self, provider):
        contents, _ = GenerateContentHandler.convert_messages(self._native_transcript())
        flat = json.dumps(contents)
        assert "I'll use the" not in flat

    def test_assistant_text_plus_tool_calls_keeps_both(self, provider):
        msgs = [Message("assistant", "Checking the file now.", tool_calls=[{
            "id": "fc-2",
            "type": "function",
            "function": {"name": "read_file", "arguments": "{}"},
        }])]
        contents, _ = GenerateContentHandler.convert_messages(msgs)
        assert contents[0]["parts"][0] == {"text": "Checking the file now."}
        assert contents[0]["parts"][1]["function_call"]["name"] == "read_file"

    def test_parallel_calls_pair_independently(self, provider):
        msgs = [
            Message("assistant", "", tool_calls=[
                {"id": "fc-a", "type": "function",
                 "function": {"name": "read_file", "arguments": json.dumps({"path": "a"})}},
                {"id": "fc-b", "type": "function",
                 "function": {"name": "shell", "arguments": json.dumps({"command": "ls"})}},
            ]),
            Message("tool", "content-a", tool_call_id="fc-a"),
            Message("tool", "out-b", tool_call_id="fc-b"),
        ]
        contents, _ = GenerateContentHandler.convert_messages(msgs)
        assert [p["function_call"]["name"] for p in contents[0]["parts"]] == ["read_file", "shell"]
        assert contents[1]["parts"][0]["function_response"]["name"] == "read_file"
        assert contents[2]["parts"][0]["function_response"]["name"] == "shell"

    def test_unpaired_tool_result_degrades_to_text_turn(self, provider):
        msgs = [Message("tool", "orphan result", tool_call_id="fc-lost")]
        contents, _ = GenerateContentHandler.convert_messages(msgs)
        assert contents[0]["role"] == "user"
        assert contents[0]["parts"] == [{"text": "orphan result"}]

    def test_malformed_arguments_degrade_to_empty_args(self, provider):
        msgs = [Message("assistant", "", tool_calls=[{
            "id": "fc-3",
            "type": "function",
            "function": {"name": "shell", "arguments": "{not json"},
        }])]
        contents, _ = GenerateContentHandler.convert_messages(msgs)
        assert contents[0]["parts"][0]["function_call"]["args"] == {}

    def test_plain_messages_unchanged(self, provider):
        msgs = [
            Message("system", "be terse"),
            Message("user", "hi"),
            Message("assistant", "hello"),
        ]
        contents, system_instruction = GenerateContentHandler.convert_messages(msgs)
        assert system_instruction == "be terse"
        assert contents == [
            {"role": "user", "parts": [{"text": "hi"}]},
            {"role": "model", "parts": [{"text": "hello"}]},
        ]


def test_filter_empty_parts_stays_deleted():
    """KI-001 / debt Item 41: the 'defensive filter' had zero call sites and
    misled readers into believing a mitigation was active. Deleted 2026-07-12;
    the response parse loops already skip empty text parts inherently."""
    from ppxai.engine.providers.gemini import GeminiProvider

    assert not hasattr(GeminiProvider, "_filter_empty_parts")

"""Responses wire: content-part types and provider-reserved tool names.

Both were found by the VSCode smoke run on 2026-09-26 and reproduced live
against `perplexity/sonar`, the only Sonar id left after the 2026-09-27
chat-completions retirement:

- defect 3: an attachment answered
  `input[N]: content part 0: invalid type "text"`. `/v1/responses` takes
  `input_text` / `input_image` / `input_file` (and `output_text` for
  assistant turns), never the chat-completions part types.
- defect 4: tools on answered
  `custom function name "search_files" is reserved`. Probing the whole
  tool set found three reserved names: `search_files`, `web_search`,
  `fetch_url`. The handler aliases them on the wire and maps them back.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from ppxai.engine.model_facts import ModelFacts
from ppxai.engine.providers.perplexity import PerplexityProvider
from ppxai.engine.providers.wire.responses import ResponsesHandler
from ppxai.engine.types import EventType, Message

H = ResponsesHandler
PREFIX = ResponsesHandler.RESERVED_ALIAS_PREFIX
RESERVED = frozenset({"search_files", "web_search", "fetch_url"})


def _chat_tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"{name} tool",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
        },
    }


class _Host:
    """The attributes `build_request` / `_stream` / `_non_stream` read."""

    enable_web_search = False

    def __init__(self, reserved=frozenset(), output=None, stream_events=None):
        self.reserved_function_names = reserved
        self.requests: list[dict] = []
        host = self

        class _Responses:
            def create(self, **kwargs):
                host.requests.append(kwargs)
                if kwargs.get("stream"):
                    return iter(stream_events or [])
                return SimpleNamespace(output=output or [], usage=None)

        self.client = SimpleNamespace(responses=_Responses())

    def get_facts_for_model(self, model):
        return ModelFacts(tool_mode="native")

    def _get_max_tokens(self, model):
        return 0

    def _get_extra_body(self, model):
        return None


def _collect(agen) -> list:
    async def run():
        return [e async for e in agen]
    return asyncio.run(run())


# ---------------------------------------------------------------------------
# Defect 3: content-part types
# ---------------------------------------------------------------------------


class TestContentParts:

    def test_user_text_becomes_input_text(self):
        _, items = H.convert_messages([Message("user", [{"type": "text", "text": "hi"}])])
        assert items == [{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}]

    def test_assistant_text_becomes_output_text(self):
        parts = H.to_responses_parts([{"type": "text", "text": "done"}], "assistant")
        assert parts == [{"type": "output_text", "text": "done"}]

    def test_image_url_becomes_input_image_with_a_string_url(self):
        parts = H.to_responses_parts(
            [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA", "detail": "low"}}],
            "user",
        )
        assert parts == [{"type": "input_image", "image_url": "data:image/png;base64,AAA", "detail": "low"}]

    def test_chat_file_part_becomes_input_file(self):
        parts = H.to_responses_parts(
            [{"type": "file", "file": {"filename": "a.pdf", "file_data": "data:application/pdf;base64,AAA"}}],
            "user",
        )
        assert parts == [{"type": "input_file", "filename": "a.pdf", "file_data": "data:application/pdf;base64,AAA"}]

    def test_string_content_is_untouched(self):
        _, items = H.convert_messages([Message("user", "plain")])
        assert items == [{"role": "user", "content": "plain"}]

    def test_an_unknown_part_passes_through_for_the_api_to_name(self):
        odd = {"type": "input_audio", "input_audio": {"data": "x"}}
        assert H.to_responses_parts([odd], "user") == [odd]

    def test_no_chat_completions_part_type_reaches_the_wire(self):
        """Every list part the converter emits is a Responses part type."""
        messages = [
            Message("user", [
                {"type": "text", "text": "look"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
            ]),
            Message("assistant", [{"type": "text", "text": "seen"}]),
        ]
        _, items = H.convert_messages(messages)
        types = {p["type"] for item in items for p in item["content"]}
        assert types <= {"input_text", "input_image", "input_file", "output_text"}
        assert "text" not in types and "image_url" not in types


# ---------------------------------------------------------------------------
# Defect 4: reserved function names
# ---------------------------------------------------------------------------


class TestReservedNamesAreAliasedOutbound:

    def _request(self, host, messages=None, tools=None):
        return H().build_request(
            host, messages or [Message("user", "hi")], "perplexity/sonar",
            tools=tools if tools is not None else [_chat_tool("search_files"), _chat_tool("read_file")],
        )

    def test_reserved_tool_definitions_are_aliased(self):
        kwargs = self._request(_Host(RESERVED))
        names = [t["name"] for t in kwargs["tools"]]
        assert names == [f"{PREFIX}search_files", "read_file"]

    def test_the_tool_hint_names_the_alias_not_the_reserved_name(self):
        kwargs = self._request(_Host(RESERVED))
        assert f"- {PREFIX}search_files(" in kwargs["instructions"]
        assert "- search_files(" not in kwargs["instructions"]

    def test_history_function_calls_are_aliased(self):
        history = [
            Message("user", "find it"),
            Message("assistant", "", tool_calls=[{
                "id": "c1", "function": {"name": "web_search", "arguments": "{}"},
            }]),
            Message("tool", "result", tool_call_id="c1"),
        ]
        kwargs = self._request(_Host(RESERVED), messages=history)
        calls = [i for i in kwargs["input"] if i.get("type") == "function_call"]
        assert [c["name"] for c in calls] == [f"{PREFIX}web_search"]

    def test_the_callers_tool_list_is_not_mutated(self):
        tools = [_chat_tool("fetch_url")]
        self._request(_Host(RESERVED), tools=tools)
        assert tools[0]["function"]["name"] == "fetch_url"

    def test_a_host_with_no_reserved_names_sends_real_names(self):
        kwargs = self._request(_Host())
        assert [t["name"] for t in kwargs["tools"]] == ["search_files", "read_file"]


class TestReservedNamesAreMappedBackInbound:

    def test_non_stream_function_call_comes_back_under_the_real_name(self):
        output = [SimpleNamespace(
            type="function_call", call_id="c1", id="c1",
            name=f"{PREFIX}search_files", arguments=json.dumps({"q": "x"}),
        )]
        host = _Host(RESERVED, output=output)
        events = _collect(H()._non_stream(host, {"model": "m", "input": []}))
        calls = [e.data for e in events if e.type == EventType.TOOL_CALL]
        assert [c["tool"] for c in calls] == ["search_files"]
        end = [e for e in events if e.type == EventType.STREAM_END][-1]
        assert end.metadata["tool_calls"][0]["function"]["name"] == "search_files"

    def test_stream_function_call_comes_back_under_the_real_name(self):
        item = SimpleNamespace(type="function_call", call_id="c1", id="c1", name=f"{PREFIX}fetch_url")
        stream_events = [
            SimpleNamespace(type="response.output_item.added", item=item),
            SimpleNamespace(type="response.function_call_arguments.done", call_id="c1",
                            arguments=json.dumps({"url": "https://x"}), name=""),
        ]
        host = _Host(RESERVED, stream_events=stream_events)
        events = _collect(H()._stream(host, {"model": "m", "input": []}))
        calls = [e.data for e in events if e.type == EventType.TOOL_CALL]
        assert [c["tool"] for c in calls] == ["fetch_url"]
        assert calls[0]["arguments"] == {"url": "https://x"}

    def test_an_unrelated_prefixed_name_is_left_alone(self):
        assert H.unalias_name(f"{PREFIX}read_file", RESERVED) == f"{PREFIX}read_file"
        assert H.unalias_name("read_file", RESERVED) == "read_file"


def test_perplexity_declares_the_measured_reserved_names():
    """Pinned to the 2026-09-26 probe. Change it only with a new measurement."""
    assert PerplexityProvider.reserved_function_names == RESERVED

"""Gemini's thought signature survives the OpenAI-compatible path.

Without google-genai, the `gemini` provider is served by
`OpenAICompatibleProvider` against Google's `/v1beta/openai` endpoint. That
endpoint returns each tool call with
`extra_content: {"google": {"thought_signature": ...}}` and rejects the next
turn unless it comes back: "Function call is missing a thought_signature in
functionCall parts" (400, seen live 2026-11-22 from a tai /task on a uvx env
without google-genai).

The transcript keeps the signature as a plain `thought_signature` key on the
tool call (Item 45, the native path), so the provider reads it into the
TOOL_CALL event and the chat-completions wire puts it back as
`extra_content`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
from ppxai.engine.providers.wire import get_handler
from ppxai.engine.types import EventType, Message

SIG = "c2lnbmF0dXJlLWJ5dGVz"
TOOLS = [{"type": "function", "function": {
    "name": "read_file", "description": "d",
    "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}}}}]


@pytest.fixture
def provider():
    p = OpenAICompatibleProvider(api_key="test-key", base_url="http://127.0.0.1:9/v1",
                                 provider_id="gemini")
    p.client = MagicMock()
    return p


def _tool_call(**extra):
    return {"id": "call_1", "type": "function",
            "function": {"name": "read_file", "arguments": '{"filepath": "notes.txt"}'}, **extra}


def _completion(tool_call):
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 0, "model": "gemini-3.8-flash",
        "choices": [{"index": 0, "finish_reason": "tool_calls",
                     "message": {"role": "assistant", "content": None, "tool_calls": [tool_call]}}],
    })


def _chunks(tool_call):
    tc = {"index": 0, **tool_call}
    return [
        ChatCompletionChunk.model_validate({
            "id": "x", "object": "chat.completion.chunk", "created": 0, "model": "gemini-3.8-flash",
            "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [tc]},
                         "finish_reason": None}]}),
        ChatCompletionChunk.model_validate({
            "id": "x", "object": "chat.completion.chunk", "created": 0, "model": "gemini-3.8-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}),
    ]


async def _tool_calls(provider, response, stream):
    provider.client.chat.completions.create.return_value = response
    with patch.object(provider, "_get_generation_params", return_value={}):
        events = [e async for e in provider.chat([Message("user", "read it")], "gemini-3.8-flash",
                                                 stream=stream, tools=TOOLS)]
    return [e.data for e in events if e.type == EventType.TOOL_CALL]


class TestTheSignatureIsRead:
    @pytest.mark.asyncio
    async def test_from_a_message(self, provider):
        [call] = await _tool_calls(
            provider, _completion(_tool_call(extra_content={"google": {"thought_signature": SIG}})),
            stream=False)
        assert call["thought_signature"] == SIG
        assert call["tool"] == "read_file" and call["tool_call_id"] == "call_1"

    @pytest.mark.asyncio
    async def test_from_a_stream(self, provider):
        [call] = await _tool_calls(
            provider, iter(_chunks(_tool_call(extra_content={"google": {"thought_signature": SIG}}))),
            stream=True)
        assert call["thought_signature"] == SIG

    @pytest.mark.asyncio
    async def test_no_signature_adds_no_key(self, provider):
        [call] = await _tool_calls(provider, _completion(_tool_call()), stream=False)
        assert "thought_signature" not in call


class TestTheSignatureIsSentBack:
    def _outbound(self, tool_call):
        msgs = get_handler("chat_completions").convert_messages([
            Message("user", "read it"),
            Message("assistant", "", tool_calls=[tool_call]),
            Message("tool", "pelican", tool_call_id="call_1"),
        ])
        return msgs[1]["tool_calls"][0]

    def test_as_googles_extra_content(self):
        out = self._outbound(_tool_call(thought_signature=SIG))
        assert out["extra_content"] == {"google": {"thought_signature": SIG}}
        assert "thought_signature" not in out
        assert out["id"] == "call_1" and out["function"]["name"] == "read_file"

    def test_a_call_without_one_is_unchanged(self):
        tc = _tool_call()
        assert self._outbound(tc) == tc

    def test_the_transcript_entry_is_not_mutated(self):
        tc = _tool_call(thought_signature=SIG)
        self._outbound(tc)
        assert tc["thought_signature"] == SIG and "extra_content" not in tc

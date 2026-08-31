"""R17 regression test — Gemini provider must survive None `.parts` responses.

Gemini returns a candidate whose `content.parts` is None under several
conditions (safety-blocked responses, certain tool-result continuations,
empty outputs with a set `finish_reason`). A prior fix (commit 6feb406b)
added a triple guard `candidates and candidates[0].content and
candidates[0].content.parts` in both non-streaming code paths.

This test pins that guard. If a future refactor removes any leg of the
check, the iterate-over-None TypeError that users saw before the fix will
come back.
"""

import pytest
from typing import Any, AsyncIterator
from unittest.mock import MagicMock, patch

from ppxai.engine.types import Event, EventType, Message
from ppxai.engine.providers.wire.generate_content import GenerateContentHandler


def _make_response_with_null_parts() -> Any:
    """Build a mock Gemini response where `candidates[0].content.parts` is None.

    Mirrors the shape of a safety-blocked response from the google-genai
    SDK: candidate exists, content exists, but parts is explicitly None.
    """
    part_holder = MagicMock()
    part_holder.parts = None  # ← the nasty case

    candidate = MagicMock()
    candidate.content = part_holder
    candidate.grounding_metadata = None

    response = MagicMock()
    response.candidates = [candidate]
    response.usage_metadata = None
    return response


def _make_response_with_no_candidates() -> Any:
    response = MagicMock()
    response.candidates = []
    response.usage_metadata = None
    return response


def _make_response_with_null_content() -> Any:
    candidate = MagicMock()
    candidate.content = None
    candidate.grounding_metadata = None
    response = MagicMock()
    response.candidates = [candidate]
    response.usage_metadata = None
    return response


async def _drain(agen: AsyncIterator[Event]) -> list[Event]:
    """Collect all events from an async generator without raising."""
    events = []
    async for ev in agen:
        events.append(ev)
    return events


class TestGeminiNullPartsRegression:
    """R17 — non-streaming Gemini responses with missing content must not crash."""

    @pytest.fixture
    def provider(self):
        from ppxai.engine.providers.gemini import GeminiProvider

        with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            provider = GeminiProvider(api_key="test")
        return provider

    @pytest.mark.asyncio
    async def test_null_parts_does_not_raise(self, provider):
        """The canonical R17 repro — parts is None, must not iterate."""
        response = _make_response_with_null_parts()
        provider.client.models.generate_content = MagicMock(return_value=response)

        messages = [Message("user", "hello")]
        events = await _drain(provider.chat(messages, model="gemini-3-flash-preview", stream=False))

        # Must reach STREAM_END without an ERROR event from TypeError
        errors = [e for e in events if e.type == EventType.ERROR]
        assert not errors, f"R17 regressed — iterate over None: {[e.data for e in errors]}"
        assert any(e.type == EventType.STREAM_END for e in events)

    @pytest.mark.asyncio
    async def test_no_candidates_does_not_raise(self, provider):
        """Empty candidates list — guard must short-circuit."""
        response = _make_response_with_no_candidates()
        provider.client.models.generate_content = MagicMock(return_value=response)

        messages = [Message("user", "hello")]
        events = await _drain(provider.chat(messages, model="gemini-3-flash-preview", stream=False))

        errors = [e for e in events if e.type == EventType.ERROR]
        assert not errors, f"empty candidates raised: {[e.data for e in errors]}"

    @pytest.mark.asyncio
    async def test_null_content_does_not_raise(self, provider):
        """candidate.content is None — guard must short-circuit."""
        response = _make_response_with_null_content()
        provider.client.models.generate_content = MagicMock(return_value=response)

        messages = [Message("user", "hello")]
        events = await _drain(provider.chat(messages, model="gemini-3-flash-preview", stream=False))

        errors = [e for e in events if e.type == EventType.ERROR]
        assert not errors, f"null content raised: {[e.data for e in errors]}"

    def test_chat_sync_simple_null_parts_does_not_raise(self, provider):
        """Same guard in the synchronous helper — captions / VL sidecar path."""
        response = _make_response_with_null_parts()
        provider.client.models.generate_content = MagicMock(return_value=response)

        # chat_sync_simple returns a string; null parts → empty string, no raise
        result = provider.chat_sync_simple(
            [Message("user", "hello")], model="gemini-3-flash-preview"
        )
        assert result == ""


class TestGeminiNoneIterableGuards:
    """Defensive guards against the broader 'NoneType is not iterable'
    class of bugs flagged in the gemini-3.1-pro benchmark debug logs.
    The exact trigger wasn't reproducible from committed logs but the
    most likely candidate is _convert_tools_to_gemini iterating None.
    Pin the guards so future code paths can pass None safely."""

    @pytest.fixture
    def provider(self):
        from ppxai.engine.providers.gemini import GeminiProvider

        with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            provider = GeminiProvider(api_key="test")
        return provider

    def test_convert_tools_to_gemini_handles_none(self, provider):
        """Direct None input must return [] without iterating."""
        result = provider._convert_tools_to_gemini(None)
        assert result == []

    def test_convert_tools_to_gemini_handles_empty_list(self, provider):
        result = provider._convert_tools_to_gemini([])
        assert result == []

    def test_convert_tools_to_gemini_skips_non_dict_entries(self, provider):
        """A malformed tools list with mixed non-dict entries must
        skip the bad ones rather than raise AttributeError on .get()."""
        malformed = [
            None,  # bad
            "string",  # bad
            42,  # bad
            {"type": "function", "function": {"name": "good_tool",
                                              "description": "ok"}},
        ]
        result = provider._convert_tools_to_gemini(malformed)
        assert len(result) == 1
        assert result[0]["name"] == "good_tool"

    def test_parse_function_call_handles_none(self, provider):
        assert provider._parse_function_call(None) is None

    def test_parse_grounding_handles_none(self, provider):
        assert provider._parse_grounding(None) == []

    def test_parse_usage_handles_none(self, provider):
        assert provider._parse_usage(None) is None

    def test_content_to_gemini_parts_handles_none_content(self, provider):
        """Message content=None should produce an empty/blank text
        part, not crash on `for block in None`."""
        result = GenerateContentHandler._content_to_gemini_parts(None)
        assert isinstance(result, list)
        # Either empty parts OR a blank text fallback — both safe.
        assert len(result) >= 0

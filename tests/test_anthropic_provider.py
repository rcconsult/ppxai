"""The Anthropic provider and the `messages` wire (ROADMAP Phase 1).

`WireProtocol` has reserved `"messages"` since ADR 0012 W4 with nothing
registered against it. This is the handler that fills the slot plus the
account that owns the key, and the tests split the same way: conversion is
the wire's, everything else is the provider's.

No network. Every test here shapes a request or reads a response object;
the SDK is never called.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ppxai.engine.providers import list_registered_providers
from ppxai.engine.providers.anthropic import AnthropicProvider
from ppxai.engine.providers.wire import HANDLERS, get_handler
from ppxai.engine.types import Message

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24).decode()


@pytest.fixture
def provider():
    return AnthropicProvider(api_key="test-key", provider_id="anthropic")


# ---------------------------------------------------------------------------
# The wire
# ---------------------------------------------------------------------------

class TestTheMessagesWireIsRegistered:
    def test_the_reserved_slot_is_filled(self):
        assert "messages" in HANDLERS
        assert get_handler("messages").name == "messages"

    def test_the_provider_is_registered(self):
        assert "anthropic" in list_registered_providers()


class TestSystemIsAParameterNotARole:
    """Anthropic rejects `{"role": "system"}` inside `messages`."""

    def test_system_is_lifted_out(self):
        system, msgs = get_handler("messages").convert_messages([
            Message(role="system", content="You are terse."),
            Message(role="user", content="hi"),
        ])

        assert system == "You are terse."
        assert [m["role"] for m in msgs] == ["user"]

    def test_multiple_system_messages_join_rather_than_overwrite(self):
        """Bootstrap context AND a session instruction means both."""
        system, _ = get_handler("messages").convert_messages([
            Message(role="system", content="A"),
            Message(role="system", content="B"),
            Message(role="user", content="hi"),
        ])

        assert "A" in system and "B" in system


class TestToolResultsBecomeUserContentBlocks:
    def test_a_tool_message_becomes_a_tool_result_block(self):
        _, msgs = get_handler("messages").convert_messages([
            Message(role="user", content="run it"),
            Message(role="assistant", content="", tool_calls=[
                {"id": "t1", "function": {"name": "shell", "arguments": '{"cmd":"ls"}'}}
            ]),
            Message(role="tool", content="a.txt", tool_call_id="t1"),
        ])

        assistant = [m for m in msgs if m["role"] == "assistant"][0]
        use = [b for b in assistant["content"] if b["type"] == "tool_use"][0]
        assert use["name"] == "shell"
        assert use["input"] == {"cmd": "ls"}, "arguments must arrive decoded"

        result_block = msgs[-1]["content"][-1]
        assert result_block["type"] == "tool_result"
        assert result_block["tool_use_id"] == "t1"

    def test_parallel_results_merge_into_one_user_turn(self):
        """Splitting results across messages trains the model out of
        parallel tool calls."""
        _, msgs = get_handler("messages").convert_messages([
            Message(role="user", content="go"),
            Message(role="assistant", content="", tool_calls=[
                {"id": "a", "function": {"name": "f", "arguments": "{}"}},
                {"id": "b", "function": {"name": "g", "arguments": "{}"}},
            ]),
            Message(role="tool", content="1", tool_call_id="a"),
            Message(role="tool", content="2", tool_call_id="b"),
        ])

        tool_turns = [m for m in msgs if m["role"] == "user"
                      and any(b.get("type") == "tool_result" for b in m["content"])]
        assert len(tool_turns) == 1, "results must land in a single user turn"
        assert len(tool_turns[0]["content"]) == 2

    def test_malformed_tool_arguments_do_not_raise(self):
        _, msgs = get_handler("messages").convert_messages([
            Message(role="user", content="go"),
            Message(role="assistant", content="", tool_calls=[
                {"id": "x", "function": {"name": "f", "arguments": "{not json"}}
            ]),
        ])

        assert msgs[-1]["content"][0]["input"] == {}


class TestImages:
    def test_a_data_url_splits_into_media_type_and_data(self):
        _, msgs = get_handler("messages").convert_messages([
            Message(role="user", content=[
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG}"}},
                {"type": "text", "text": "what is this"},
            ]),
        ])

        image = msgs[0]["content"][0]
        assert image["source"]["type"] == "base64"
        assert image["source"]["media_type"] == "image/png"

    def test_a_plain_url_passes_through_as_a_url_source(self):
        _, msgs = get_handler("messages").convert_messages([
            Message(role="user", content=[
                {"type": "image_url", "image_url": {"url": "https://x.test/a.png"}},
            ]),
        ])

        assert msgs[0]["content"][0]["source"] == {
            "type": "url", "url": "https://x.test/a.png"
        }

    def test_a_corrupt_data_url_is_dropped_not_sent(self):
        """A malformed source 400s the WHOLE request; dropping one image
        only degrades the turn."""
        _, msgs = get_handler("messages").convert_messages([
            Message(role="user", content=[
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,!!!!"}},
                {"type": "text", "text": "still here"},
            ]),
        ])

        assert [b["type"] for b in msgs[0]["content"]] == ["text"]


# ---------------------------------------------------------------------------
# The account
# ---------------------------------------------------------------------------

class TestRequestShape:
    def test_thinking_is_adaptive_and_never_budget_tokens(self, provider):
        """`budget_tokens` is a 400 on every model this provider targets."""
        kw = provider._request_kwargs("claude-opus-5", 64000)

        assert kw["thinking"]["type"] == "adaptive"
        assert "budget_tokens" not in kw["thinking"]
        assert kw["thinking"]["display"] == "summarized", (
            "the API default is 'omitted', which streams empty thinking "
            "blocks and leaves ppxai's reasoning pane blank"
        )

    def test_sampling_params_are_dropped_not_forwarded(self, provider):
        """An operator config written for another provider must not make
        every Claude request fail."""
        with patch.object(
            provider, "_get_generation_params",
            lambda model: {"temperature": 0.7, "top_p": 0.9},
        ):
            kw = provider._request_kwargs("claude-opus-5", 1000)

        assert "temperature" not in kw
        assert "top_p" not in kw

    def test_prompt_caching_is_requested_by_default(self, provider):
        assert provider._request_kwargs("claude-opus-5", 1000)["cache_control"] == {
            "type": "ephemeral"
        }

    def test_effort_is_only_sent_when_configured(self, provider):
        assert "output_config" not in provider._request_kwargs("claude-opus-5", 1000)

        p = AnthropicProvider(api_key="k", effort="low")
        assert p._request_kwargs("claude-opus-5", 1000)["output_config"] == {
            "effort": "low"
        }

    def test_tools_are_flattened_to_the_anthropic_shape(self, provider):
        out = provider._convert_tools([
            {"type": "function", "function": {
                "name": "read_file", "description": "d",
                "parameters": {"type": "object", "properties": {}},
            }}
        ])

        assert out == [{
            "name": "read_file", "description": "d",
            "input_schema": {"type": "object", "properties": {}},
        }]


class TestUsageKeepsTheCacheClassesApart:
    def test_cache_tokens_are_not_folded_into_prompt_tokens(self, provider):
        """Folding them in over-reports cost by up to 10x on the cached
        portion — the reason UsageStats grew the fields."""
        u = provider._usage(SimpleNamespace(
            input_tokens=100, output_tokens=50,
            cache_creation_input_tokens=900, cache_read_input_tokens=8000,
        ))

        assert u.prompt_tokens == 100
        assert u.cache_creation_input_tokens == 900
        assert u.cache_read_input_tokens == 8000
        assert u.total_tokens == 100 + 50 + 900 + 8000

    def test_a_response_without_cache_fields_still_works(self, provider):
        u = provider._usage(SimpleNamespace(input_tokens=10, output_tokens=5))
        assert (u.cache_creation_input_tokens, u.cache_read_input_tokens) == (0, 0)


class TestRefusalIsSurfacedNotMistakenForEmpty:
    def test_stop_details_is_only_read_on_a_refusal(self, provider):
        """It is None for every other stop reason — reading it unguarded
        is an AttributeError on the happy path."""
        assert provider._refusal_message(
            SimpleNamespace(stop_reason="end_turn", stop_details=None)
        ) is None

    def test_a_refusal_names_its_category(self, provider):
        msg = provider._refusal_message(SimpleNamespace(
            stop_reason="refusal",
            stop_details=SimpleNamespace(category="cyber", explanation="nope"),
        ))

        assert "cyber" in msg and "declined" in msg


class TestFacts:
    def test_an_unlisted_claude_model_still_speaks_messages(self, provider):
        """The global floor says chat_completions, which is a wire this
        account does not serve — the same reason Gemini overrides it."""
        assert AnthropicProvider.unmeasured_facts.wire_protocol == "messages"

    def test_shipped_facts_mark_claude_native_and_multimodal(self, provider):
        facts = provider.get_facts_for_model("claude-opus-5")

        assert facts.wire_protocol == "messages"
        assert facts.tool_mode == "native"
        assert facts.supports_vision is True


class TestErrorsAreClassifiedNotSwallowed:
    def test_each_status_gets_its_own_message(self, provider):
        import anthropic

        cases = [
            (anthropic.AuthenticationError, "ANTHROPIC_API_KEY"),
            (anthropic.NotFoundError, "model"),
            (anthropic.RateLimitError, "Rate limited"),
        ]
        for exc_cls, expected in cases:
            e = exc_cls.__new__(exc_cls)
            assert expected in provider._format_error(e)

    def test_a_429_is_a_throttle_not_a_generic_error(self, provider):
        payload = provider._classify_throttle(
            SimpleNamespace(status_code=429, response=None)
        )

        assert payload is not None
        assert payload["status_code"] == 429
        assert payload["provider"] == "anthropic"

    def test_a_400_is_not_a_throttle(self, provider):
        assert provider._classify_throttle(
            SimpleNamespace(status_code=400, response=None)
        ) is None

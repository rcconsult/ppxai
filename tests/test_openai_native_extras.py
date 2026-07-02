"""Tests for v1.18.3 follow-up: OpenAI-native provider wiring of
``extra_body`` pass-through and throttle telemetry on BOTH the Chat
Completions API path (`gpt-4.1`, `gpt-5.x`, `o-series`) and the
Responses API path (`gpt-5.1-codex*`, `gpt-*-pro`).

These tests verify the wiring sites — the helpers themselves are unit-
tested in `test_extra_body.py` / `test_provider_throttle.py`.
"""

from unittest.mock import MagicMock, patch

import openai as openai_module
import pytest

from ppxai.engine.providers.openai_native import OpenAINativeProvider
from ppxai.engine.types import EventType, Message


def _make_provider() -> OpenAINativeProvider:
    with patch("ppxai.engine.providers.openai_native.OpenAI"):
        return OpenAINativeProvider(api_key="test-key", provider_id="openai")


# ---------------------------------------------------------------------------
# Chat Completions API path (gpt-4.1, gpt-5.x, o-series)
# ---------------------------------------------------------------------------


class TestChatCompletionsExtraBody:
    @pytest.mark.asyncio
    async def test_extra_body_forwarded(self):
        provider = _make_provider()
        provider.client = MagicMock()
        # Empty stream — we only care about the create() call kwargs
        provider.client.chat.completions.create.return_value = iter([])

        with patch(
            "ppxai.engine.providers.base.get_extra_body",
            return_value={"service_tier": "default"},
        ):
            async for _ in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="gpt-5.4-mini",
                stream=True,
            ):
                pass

        kwargs = provider.client.chat.completions.create.call_args.kwargs
        assert kwargs.get("extra_body") == {"service_tier": "default"}

    @pytest.mark.asyncio
    async def test_empty_extra_body_omitted(self):
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.chat.completions.create.return_value = iter([])

        with patch(
            "ppxai.engine.providers.base.get_extra_body",
            return_value={},
        ):
            async for _ in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="gpt-5.4-mini",
                stream=True,
            ):
                pass

        kwargs = provider.client.chat.completions.create.call_args.kwargs
        assert "extra_body" not in kwargs


class TestChatCompletionsThrottle:
    @pytest.mark.asyncio
    async def test_429_emits_provider_throttled(self):
        provider = _make_provider()
        provider.client = MagicMock()
        rate_limit = openai_module.RateLimitError(
            message="Rate limit",
            response=MagicMock(status_code=429, headers={"retry-after": "5"}),
            body=None,
        )
        provider.client.chat.completions.create.side_effect = rate_limit

        events = []
        with patch("ppxai.usage.record_provider_error") as mock_record:
            async for ev in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="gpt-5.4-mini",
                stream=True,
            ):
                events.append(ev)

        types = [e.type for e in events]
        assert EventType.PROVIDER_THROTTLED in types
        assert EventType.ERROR not in types

        throttle = next(e for e in events if e.type == EventType.PROVIDER_THROTTLED)
        assert throttle.data["status_code"] == 429
        assert throttle.data["provider"] == "openai"
        assert throttle.data["model"] == "gpt-5.4-mini"
        assert throttle.data["retry_after"] == 5.0

        mock_record.assert_called_once()
        assert mock_record.call_args.kwargs["status_code"] == 429
        assert mock_record.call_args.kwargs["model"] == "gpt-5.4-mini"

    @pytest.mark.asyncio
    async def test_403_emits_provider_throttled(self):
        provider = _make_provider()
        provider.client = MagicMock()
        forbidden = openai_module.PermissionDeniedError(
            message="forbidden",
            response=MagicMock(status_code=403, headers={}),
            body=None,
        )
        provider.client.chat.completions.create.side_effect = forbidden

        events = []
        with patch("ppxai.usage.record_provider_error"):
            async for ev in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="gpt-5.4-mini",
                stream=True,
            ):
                events.append(ev)

        assert EventType.PROVIDER_THROTTLED in [e.type for e in events]

    @pytest.mark.asyncio
    async def test_404_not_a_chat_model_still_falls_back_to_responses(self):
        """The pre-existing 404 fallback to Responses API must keep working
        — throttle classification only kicks in for 403/429, so a 404 stays
        on the existing fallback path."""
        provider = _make_provider()
        provider.client = MagicMock()
        not_found = openai_module.NotFoundError(
            message="The model is not a chat model",
            response=MagicMock(status_code=404, headers={}),
            body=None,
        )
        provider.client.chat.completions.create.side_effect = not_found
        # Responses API path uses responses.create — return empty stream
        provider.client.responses.create.return_value = iter([])

        events = []
        async for ev in provider.chat(
            messages=[Message(role="user", content="hi")],
            model="gpt-5.1-codex",
            stream=True,
        ):
            events.append(ev)

        # Should have invoked responses.create as the fallback, not raised
        # PROVIDER_THROTTLED
        assert provider.client.responses.create.called
        types = [e.type for e in events]
        assert EventType.PROVIDER_THROTTLED not in types

    @pytest.mark.asyncio
    async def test_500_falls_through_to_generic_error(self):
        provider = _make_provider()
        provider.client = MagicMock()
        server_err = openai_module.InternalServerError(
            message="server error",
            response=MagicMock(status_code=500, headers={}),
            body=None,
        )
        provider.client.chat.completions.create.side_effect = server_err

        events = []
        async for ev in provider.chat(
            messages=[Message(role="user", content="hi")],
            model="gpt-5.4-mini",
            stream=True,
        ):
            events.append(ev)

        types = [e.type for e in events]
        assert EventType.ERROR in types
        assert EventType.PROVIDER_THROTTLED not in types


# ---------------------------------------------------------------------------
# Responses API path (gpt-5.1-codex*, gpt-*-pro)
# ---------------------------------------------------------------------------


class TestResponsesApiExtraBody:
    @pytest.mark.asyncio
    async def test_extra_body_forwarded(self):
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.responses.create.return_value = iter([])

        with patch(
            "ppxai.engine.providers.base.get_extra_body",
            return_value={"reasoning": {"effort": "high"}},
        ):
            async for _ in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="gpt-5.1-codex",
                stream=True,
            ):
                pass

        kwargs = provider.client.responses.create.call_args.kwargs
        assert kwargs.get("extra_body") == {"reasoning": {"effort": "high"}}

    @pytest.mark.asyncio
    async def test_empty_extra_body_omitted(self):
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.responses.create.return_value = iter([])

        with patch(
            "ppxai.engine.providers.base.get_extra_body",
            return_value={},
        ):
            async for _ in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="gpt-5.1-codex",
                stream=True,
            ):
                pass

        kwargs = provider.client.responses.create.call_args.kwargs
        assert "extra_body" not in kwargs


class TestResponsesApiThrottle:
    @pytest.mark.asyncio
    async def test_429_emits_provider_throttled(self):
        provider = _make_provider()
        provider.client = MagicMock()
        rate_limit = openai_module.RateLimitError(
            message="Rate limit",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        provider.client.responses.create.side_effect = rate_limit

        events = []
        with patch("ppxai.usage.record_provider_error") as mock_record:
            async for ev in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="gpt-5.1-codex",
                stream=True,
            ):
                events.append(ev)

        types = [e.type for e in events]
        assert EventType.PROVIDER_THROTTLED in types
        assert EventType.ERROR not in types

        throttle = next(e for e in events if e.type == EventType.PROVIDER_THROTTLED)
        assert throttle.data["status_code"] == 429
        assert throttle.data["model"] == "gpt-5.1-codex"
        assert mock_record.call_args.kwargs["model"] == "gpt-5.1-codex"

    @pytest.mark.asyncio
    async def test_400_falls_through_to_generic_error(self):
        provider = _make_provider()
        provider.client = MagicMock()
        bad = openai_module.BadRequestError(
            message="bad params",
            response=MagicMock(status_code=400, headers={}),
            body=None,
        )
        provider.client.responses.create.side_effect = bad

        events = []
        async for ev in provider.chat(
            messages=[Message(role="user", content="hi")],
            model="gpt-5.1-codex",
            stream=True,
        ):
            events.append(ev)

        types = [e.type for e in events]
        assert EventType.ERROR in types
        assert EventType.PROVIDER_THROTTLED not in types

    @pytest.mark.asyncio
    async def test_telemetry_failure_does_not_break_chat(self):
        provider = _make_provider()
        provider.client = MagicMock()
        rate_limit = openai_module.RateLimitError(
            message="Rate limit",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        provider.client.responses.create.side_effect = rate_limit

        events = []
        with patch(
            "ppxai.usage.record_provider_error",
            side_effect=RuntimeError("disk full"),
        ):
            async for ev in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="gpt-5.1-codex",
                stream=True,
            ):
                events.append(ev)

        assert EventType.PROVIDER_THROTTLED in [e.type for e in events]


# ---------------------------------------------------------------------------
# oneshot() routing (v1.19.0 review fix): Codex/Pro models 404 on Chat
# Completions, so oneshot must route them through the Responses API — exactly
# like chat() does. Regression for /v1/oneshot + /v1/agent/run failing for a
# whole model class that works over /chat.
# ---------------------------------------------------------------------------


class TestOneshotResponsesRouting:
    def _responses_reply(self, model: str, text: str):
        resp = MagicMock()
        resp.output = []            # no message items → falls back to output_text
        resp.output_text = text
        resp.usage = None
        resp.model = model
        return resp

    def _chat_reply(self, model: str, text: str):
        msg = MagicMock()
        msg.content = text
        choice = MagicMock()
        choice.message = msg
        choice.finish_reason = "stop"
        resp = MagicMock()
        resp.choices = [choice]
        resp.usage = None
        resp.model = model
        return resp

    def test_pro_model_routes_to_responses_api(self):
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.responses.create.return_value = self._responses_reply(
            "gpt-5-pro", "from-responses"
        )
        result = provider.oneshot(prompt="hi", model="gpt-5-pro")
        assert provider.client.responses.create.called
        assert not provider.client.chat.completions.create.called
        assert result["content"] == "from-responses"
        assert result["model"] == "gpt-5-pro"

    def test_codex_model_routes_to_responses_api(self):
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.responses.create.return_value = self._responses_reply(
            "gpt-5.1-codex", "codex-out"
        )
        result = provider.oneshot(prompt="hi", model="gpt-5.1-codex")
        assert provider.client.responses.create.called
        assert not provider.client.chat.completions.create.called
        assert result["content"] == "codex-out"

    def test_regular_model_still_uses_chat_completions(self):
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.chat.completions.create.return_value = self._chat_reply(
            "gpt-5.4-mini", "from-chat"
        )
        result = provider.oneshot(prompt="hi", model="gpt-5.4-mini")
        assert provider.client.chat.completions.create.called
        assert not provider.client.responses.create.called
        assert result["content"] == "from-chat"

    def test_chat_sync_simple_routes_pro_to_responses(self):
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.responses.create.return_value = self._responses_reply(
            "gpt-5-pro", "sync-out"
        )
        out = provider.chat_sync_simple(
            messages=[Message(role="user", content="hi")], model="gpt-5-pro"
        )
        assert provider.client.responses.create.called
        assert not provider.client.chat.completions.create.called
        assert out == "sync-out"

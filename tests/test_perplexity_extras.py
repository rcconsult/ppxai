"""Tests for v1.18.3 follow-up: Perplexity provider wiring of
``extra_body`` pass-through and throttle telemetry.

The base helpers (`_get_extra_body`, `_classify_throttle`,
`record_provider_error`) live on `BaseProvider` and are unit-tested in
`test_extra_body.py` / `test_provider_throttle.py`. These tests only
verify that `PerplexityProvider` actually CALLS them in its
`chat()` request path — without that wiring the helpers exist but
do nothing for Perplexity users.
"""

from unittest.mock import MagicMock, patch

import openai as openai_module
import pytest

from ppxai.engine.providers.perplexity import PerplexityProvider
from ppxai.engine.types import EventType, Message


def _make_provider() -> PerplexityProvider:
    with patch("ppxai.engine.providers.base.OpenAI"):
        return PerplexityProvider(
            api_key="test-key",
            base_url="https://api.perplexity.ai",
            provider_id="perplexity",
        )


class TestExtraBodyForwardedToSdk:
    """When `get_extra_body` is configured, Perplexity must pass it as
    `extra_body=...` to the OpenAI SDK call. Empty config is omitted."""

    @pytest.mark.asyncio
    async def test_extra_body_forwarded_in_stream(self):
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.chat.completions.create.return_value = iter([])

        with patch(
            "ppxai.engine.providers.base.get_extra_body",
            return_value={"search_recency_filter": "month"},
        ):
            async for _ in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="sonar",
                stream=True,
            ):
                pass

        kwargs = provider.client.chat.completions.create.call_args.kwargs
        assert kwargs.get("extra_body") == {"search_recency_filter": "month"}

    @pytest.mark.asyncio
    async def test_extra_body_forwarded_in_non_stream(self):
        provider = _make_provider()
        provider.client = MagicMock()
        # Mock non-stream response shape
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content="ok"))]
        response.usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        # No citations attribute
        del response.citations
        provider.client.chat.completions.create.return_value = response

        with patch(
            "ppxai.engine.providers.base.get_extra_body",
            return_value={"return_images": False},
        ):
            async for _ in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="sonar",
                stream=False,
            ):
                pass

        kwargs = provider.client.chat.completions.create.call_args.kwargs
        assert kwargs.get("extra_body") == {"return_images": False}

    @pytest.mark.asyncio
    async def test_empty_extra_body_omitted(self):
        """Empty dict must not become `extra_body={}` in the SDK call —
        some endpoints reject unknown empty top-level keys."""
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.chat.completions.create.return_value = iter([])

        with patch(
            "ppxai.engine.providers.base.get_extra_body",
            return_value={},
        ):
            async for _ in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="sonar",
                stream=True,
            ):
                pass

        kwargs = provider.client.chat.completions.create.call_args.kwargs
        assert "extra_body" not in kwargs


class TestThrottleEmitsTypedEventAndTelemetry:
    """A 403/429 raised by the SDK should produce
    `EventType.PROVIDER_THROTTLED` (not generic ERROR) and increment the
    persistent provider-error counter via `record_provider_error`."""

    @pytest.mark.asyncio
    async def test_429_emits_provider_throttled_event(self):
        provider = _make_provider()
        provider.client = MagicMock()
        rate_limit = openai_module.RateLimitError(
            message="Rate limit",
            response=MagicMock(status_code=429, headers={"retry-after": "10"}),
            body=None,
        )
        provider.client.chat.completions.create.side_effect = rate_limit

        events = []
        with patch(
            "ppxai.usage.record_provider_error",
        ) as mock_record:
            async for ev in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="sonar",
                stream=True,
            ):
                events.append(ev)

        # STREAM_START + PROVIDER_THROTTLED (no generic ERROR)
        types = [e.type for e in events]
        assert EventType.PROVIDER_THROTTLED in types
        assert EventType.ERROR not in types

        throttle_event = next(e for e in events if e.type == EventType.PROVIDER_THROTTLED)
        payload = throttle_event.data
        assert payload["status_code"] == 429
        assert payload["provider"] == "perplexity"
        assert payload["model"] == "sonar"
        assert payload["retry_after"] == 10.0

        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["provider"] == "perplexity"
        assert call_kwargs["status_code"] == 429
        assert call_kwargs["model"] == "sonar"

    @pytest.mark.asyncio
    async def test_403_emits_provider_throttled_event(self):
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
                model="sonar",
                stream=True,
            ):
                events.append(ev)

        types = [e.type for e in events]
        assert EventType.PROVIDER_THROTTLED in types
        assert EventType.ERROR not in types

    @pytest.mark.asyncio
    async def test_non_throttle_error_still_emits_generic_error(self):
        """A 400/500/generic exception should fall through to the existing
        ERROR path — throttle classification only fires for 403/429."""
        provider = _make_provider()
        provider.client = MagicMock()
        bad = openai_module.BadRequestError(
            message="bad params",
            response=MagicMock(status_code=400, headers={}),
            body=None,
        )
        provider.client.chat.completions.create.side_effect = bad

        events = []
        async for ev in provider.chat(
            messages=[Message(role="user", content="hi")],
            model="sonar",
            stream=True,
        ):
            events.append(ev)

        types = [e.type for e in events]
        assert EventType.ERROR in types
        assert EventType.PROVIDER_THROTTLED not in types

    @pytest.mark.asyncio
    async def test_telemetry_failure_does_not_break_chat(self):
        """If `record_provider_error` itself raises (corrupted usage.json,
        disk full), the throttle event must still reach the user."""
        provider = _make_provider()
        provider.client = MagicMock()
        rate_limit = openai_module.RateLimitError(
            message="Rate limit",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        provider.client.chat.completions.create.side_effect = rate_limit

        events = []
        with patch(
            "ppxai.usage.record_provider_error",
            side_effect=RuntimeError("disk full"),
        ):
            async for ev in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="sonar",
                stream=True,
            ):
                events.append(ev)

        types = [e.type for e in events]
        assert EventType.PROVIDER_THROTTLED in types

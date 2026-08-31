"""Tests for v1.18.3 follow-up: Gemini-native provider throttle
classification + telemetry.

Gemini uses ``google-genai``, not the OpenAI SDK, so the base
``_classify_throttle`` (which checks ``openai.APIStatusError``) returns
``None`` for every Gemini error. ``GeminiProvider`` overrides
``_classify_throttle`` to recognize ``google.genai.errors.APIError``
with HTTP code 403 / 429 and emit ``EventType.PROVIDER_THROTTLED`` with
the same payload shape the rest of ppxai expects.
"""

from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.providers.gemini import GeminiProvider, is_available
from ppxai.engine.types import EventType, Message

pytestmark = pytest.mark.skipif(
    not is_available(),
    reason="google-genai not installed",
)


def _make_provider() -> GeminiProvider:
    with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
        mock_genai.Client.return_value = MagicMock()
        return GeminiProvider(api_key="test-key", provider_id="gemini")


# ---------------------------------------------------------------------------
# Classification (unit-level)
# ---------------------------------------------------------------------------


class TestGeminiClassifyThrottle:
    def test_429_resource_exhausted_classified(self):
        from google.genai.errors import APIError
        provider = _make_provider()
        e = APIError(
            code=429,
            response_json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}},
        )
        payload = provider._classify_throttle(e)
        assert payload is not None
        assert payload["status_code"] == 429
        assert payload["provider"] == "gemini"
        assert payload["retry_after"] is None  # no headers on synthetic APIError

    def test_403_permission_denied_classified(self):
        from google.genai.errors import APIError
        provider = _make_provider()
        e = APIError(
            code=403,
            response_json={"error": {"status": "PERMISSION_DENIED", "message": "Region not supported"}},
        )
        payload = provider._classify_throttle(e)
        assert payload is not None
        assert payload["status_code"] == 403

    def test_400_bad_request_not_classified(self):
        from google.genai.errors import APIError
        provider = _make_provider()
        e = APIError(
            code=400,
            response_json={"error": {"status": "INVALID_ARGUMENT", "message": "bad"}},
        )
        assert provider._classify_throttle(e) is None

    def test_500_server_error_not_classified(self):
        from google.genai.errors import APIError
        provider = _make_provider()
        e = APIError(
            code=500,
            response_json={"error": {"status": "INTERNAL", "message": "boom"}},
        )
        assert provider._classify_throttle(e) is None

    def test_generic_exception_not_classified(self):
        provider = _make_provider()
        assert provider._classify_throttle(ValueError("oops")) is None
        assert provider._classify_throttle(RuntimeError("boom")) is None

    def test_provider_id_propagated(self):
        from google.genai.errors import APIError
        with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            provider = GeminiProvider(api_key="test", provider_id="gemini-eu")
        e = APIError(
            code=429,
            response_json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "x"}},
        )
        assert provider._classify_throttle(e)["provider"] == "gemini-eu"

    def test_retry_after_parsed_when_response_headers_present(self):
        from google.genai.errors import APIError
        provider = _make_provider()
        e = APIError(
            code=429,
            response_json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "x"}},
        )
        # Simulate google-genai populating .response with an httpx-like object
        e.response = MagicMock(headers={"retry-after": "60"})
        payload = provider._classify_throttle(e)
        assert payload["retry_after"] == 60.0


# ---------------------------------------------------------------------------
# Wiring — chat() emits PROVIDER_THROTTLED + records telemetry
# ---------------------------------------------------------------------------


class TestGeminiThrottleWiring:
    @pytest.mark.asyncio
    async def test_429_emits_provider_throttled_and_records(self):
        from google.genai.errors import APIError
        provider = _make_provider()

        # Make the streaming generate_content call raise an APIError
        provider.client = MagicMock()
        rate_limit = APIError(
            code=429,
            response_json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota"}},
        )
        provider.client.models.generate_content_stream.side_effect = rate_limit
        provider.client.models.generate_content.side_effect = rate_limit

        events = []
        with patch("ppxai.usage.record_provider_error") as mock_record:
            async for ev in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="gemini-2.5-flash",
                stream=True,
            ):
                events.append(ev)

        types = [e.type for e in events]
        assert EventType.PROVIDER_THROTTLED in types
        assert EventType.ERROR not in types

        throttle = next(e for e in events if e.type == EventType.PROVIDER_THROTTLED)
        assert throttle.data["status_code"] == 429
        assert throttle.data["provider"] == "gemini"
        assert throttle.data["model"] == "gemini-2.5-flash"

        mock_record.assert_called_once()
        assert mock_record.call_args.kwargs["provider"] == "gemini"
        assert mock_record.call_args.kwargs["status_code"] == 429
        assert mock_record.call_args.kwargs["model"] == "gemini-2.5-flash"

    @pytest.mark.asyncio
    async def test_403_emits_provider_throttled(self):
        from google.genai.errors import APIError
        provider = _make_provider()
        provider.client = MagicMock()
        forbidden = APIError(
            code=403,
            response_json={"error": {"status": "PERMISSION_DENIED", "message": "x"}},
        )
        provider.client.models.generate_content_stream.side_effect = forbidden
        provider.client.models.generate_content.side_effect = forbidden

        events = []
        with patch("ppxai.usage.record_provider_error"):
            async for ev in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="gemini-2.5-flash",
                stream=True,
            ):
                events.append(ev)

        assert EventType.PROVIDER_THROTTLED in [e.type for e in events]

    @pytest.mark.asyncio
    async def test_non_throttle_error_still_emits_generic_error(self):
        """Non-APIError exceptions should fall through to the existing
        ERROR path (e.g. SAFETY-blocked responses, value errors)."""
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.models.generate_content_stream.side_effect = ValueError(
            "Response blocked by SAFETY"
        )
        provider.client.models.generate_content.side_effect = ValueError(
            "Response blocked by SAFETY"
        )

        events = []
        async for ev in provider.chat(
            messages=[Message(role="user", content="hi")],
            model="gemini-2.5-flash",
            stream=True,
        ):
            events.append(ev)

        types = [e.type for e in events]
        assert EventType.ERROR in types
        assert EventType.PROVIDER_THROTTLED not in types

    @pytest.mark.asyncio
    async def test_telemetry_failure_does_not_break_chat(self):
        from google.genai.errors import APIError
        provider = _make_provider()
        provider.client = MagicMock()
        rate_limit = APIError(
            code=429,
            response_json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "x"}},
        )
        provider.client.models.generate_content_stream.side_effect = rate_limit
        provider.client.models.generate_content.side_effect = rate_limit

        events = []
        with patch(
            "ppxai.usage.record_provider_error",
            side_effect=RuntimeError("disk full"),
        ):
            async for ev in provider.chat(
                messages=[Message(role="user", content="hi")],
                model="gemini-2.5-flash",
                stream=True,
            ):
                events.append(ev)

        assert EventType.PROVIDER_THROTTLED in [e.type for e in events]

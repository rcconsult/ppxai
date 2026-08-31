"""Tests for v1.18.3 provider throttle classification.

Verifies that the BaseProvider correctly distinguishes provider-side
rate-limit / quota errors (HTTP 403, 429) from generic API errors,
producing structured payloads suitable for ``EventType.PROVIDER_THROTTLED``.

Motivated by NVIDIA NIM free-tier behavior: per-model quota exhaustion
returns ``HTTP 403 {"message":"Operation not allowed"}`` which previously
looked identical to a model failure in the result JSON. See
``feedback_benchmark_rate_limit_contamination.md``.
"""

from unittest.mock import MagicMock

import openai as openai_module

from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider


def _make_provider(provider_id: str = "nvidia") -> OpenAICompatibleProvider:
    """Build a minimal OpenAICompatibleProvider for classify-only tests."""
    return OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://integrate.api.nvidia.com/v1",
        models={},
        provider_id=provider_id,
    )


class TestClassifyThrottle:
    """``_classify_throttle`` returns structured payload for 403/429,
    None for everything else."""

    def test_403_operation_not_allowed_classified_as_throttle(self):
        provider = _make_provider("nvidia")
        response = MagicMock(status_code=403, headers={})
        e = openai_module.PermissionDeniedError(
            message='{"message":"Operation not allowed"}',
            response=response,
            body=None,
        )
        payload = provider._classify_throttle(e)
        assert payload is not None
        assert payload["status_code"] == 403
        assert payload["provider"] == "nvidia"
        assert "quota" in payload["message"].lower() or "permission" in payload["message"].lower()
        assert payload["retry_after"] is None

    def test_429_rate_limit_classified_as_throttle(self):
        provider = _make_provider("nvidia")
        response = MagicMock(status_code=429, headers={"retry-after": "30"})
        e = openai_module.RateLimitError(
            message="Rate limit exceeded",
            response=response,
            body=None,
        )
        payload = provider._classify_throttle(e)
        assert payload is not None
        assert payload["status_code"] == 429
        assert payload["retry_after"] == 30.0

    def test_400_bad_request_not_classified_as_throttle(self):
        provider = _make_provider("nvidia")
        e = openai_module.BadRequestError(
            message="bad params",
            response=MagicMock(status_code=400, headers={}),
            body=None,
        )
        assert provider._classify_throttle(e) is None

    def test_500_server_error_not_classified_as_throttle(self):
        """5xx is genuinely server-side, not a quota block."""
        provider = _make_provider("nvidia")
        e = openai_module.InternalServerError(
            message="server error",
            response=MagicMock(status_code=500, headers={}),
            body=None,
        )
        assert provider._classify_throttle(e) is None

    def test_generic_exception_not_classified(self):
        """Non-OpenAI exceptions fall through to ERROR path."""
        provider = _make_provider("nvidia")
        assert provider._classify_throttle(ValueError("oops")) is None
        assert provider._classify_throttle(RuntimeError("boom")) is None

    def test_provider_id_propagated(self):
        provider = _make_provider("custom-vllm")
        e = openai_module.PermissionDeniedError(
            message="quota exceeded",
            response=MagicMock(status_code=403, headers={}),
            body=None,
        )
        payload = provider._classify_throttle(e)
        assert payload["provider"] == "custom-vllm"


class TestFormatErrorThrottleMessages:
    """The user-facing messages for 403 / 429 should mention quota /
    rate-limit so users understand it's provider-side, not a model bug."""

    def test_403_nim_operation_not_allowed_mentions_quota(self):
        provider = _make_provider("nvidia")
        e = openai_module.PermissionDeniedError(
            message='{"message":"Operation not allowed"}',
            response=MagicMock(status_code=403, headers={}),
            body=None,
        )
        msg = provider._format_error(e)
        assert "403" in msg
        assert "quota" in msg.lower() or "rate limit" in msg.lower()
        # The hint should suggest concrete recovery actions
        assert "wait" in msg.lower() or "switch" in msg.lower() or "paid" in msg.lower()

    def test_403_generic_keeps_clear_signal(self):
        """Non-NIM 403 still routes through the new branch with status code."""
        provider = _make_provider("openai")
        e = openai_module.PermissionDeniedError(
            message="forbidden",
            response=MagicMock(status_code=403, headers={}),
            body=None,
        )
        msg = provider._format_error(e)
        assert "403" in msg

    def test_429_message_clear(self):
        provider = _make_provider("nvidia")
        e = openai_module.RateLimitError(
            message="Too many requests",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        msg = provider._format_error(e)
        # _format_error catches RateLimitError before it reaches APIStatusError
        # branch — we just need it to mention rate-limit.
        assert "rate limit" in msg.lower()

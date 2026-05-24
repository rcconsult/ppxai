"""Tests for the v1 gateway primitive: POST /v1/oneshot.

Covers:
1. Request validation (empty prompt, missing model with no default, etc.)
2. Provider construction failure (unknown provider, no API key)
3. Response shape — pinned as part of the stable v1 contract
4. response_format / max_tokens / temperature plumb through to the
   provider call
5. Provider exceptions surface as 502 (not 500 / 200-with-error)

The provider call is mocked at the boundary — these tests exercise the
route's contract, not OpenAI SDK behavior. End-to-end provider tests
live in tests/test_provider_throttle.py and the per-provider modules.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient


@pytest.fixture
def http_client():
    import ppxai.server.http as http_module
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def stub_provider():
    """Patch _build_provider so we don't need a real API key configured.

    Returns the mock so individual tests can assert call_args.
    """
    fake = MagicMock()
    fake.oneshot.return_value = {
        "content": "stub-response",
        "finish_reason": "stop",
        "model": "stub-model",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
    # Make isinstance(fake, OpenAICompatibleProvider) pass.
    from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
    fake.__class__ = OpenAICompatibleProvider
    with patch(
        "ppxai.server.routes.oneshot._build_provider", return_value=fake
    ):
        yield fake


class TestRequestValidation:
    def test_empty_prompt_rejected(self, http_client):
        r = http_client.post("/v1/oneshot", json={"prompt": ""})
        assert r.status_code == 422  # pydantic min_length

    def test_missing_prompt_rejected(self, http_client):
        r = http_client.post("/v1/oneshot", json={})
        assert r.status_code == 422

    def test_negative_max_tokens_rejected(self, http_client):
        r = http_client.post(
            "/v1/oneshot", json={"prompt": "hi", "max_tokens": -1}
        )
        assert r.status_code == 422

    def test_temperature_above_2_rejected(self, http_client):
        r = http_client.post(
            "/v1/oneshot", json={"prompt": "hi", "temperature": 3.0}
        )
        assert r.status_code == 422


class TestProviderResolution:
    def test_unknown_provider_400(self, http_client):
        r = http_client.post(
            "/v1/oneshot",
            json={"prompt": "hi", "provider": "no_such_provider", "model": "x"},
        )
        assert r.status_code == 400
        assert "no_such_provider" in r.json()["detail"]

    def test_no_default_model_falls_through_helpfully(self, http_client):
        # Provider exists but no model specified and no default_model →
        # 400 with a clear message. We patch get_default_model to None
        # to simulate this, alongside _build_provider so we don't need
        # a real provider config / API key.
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
        fake = MagicMock()
        fake.__class__ = OpenAICompatibleProvider
        with patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value=None
        ), patch(
            "ppxai.server.routes.oneshot._build_provider", return_value=fake
        ):
            r = http_client.post(
                "/v1/oneshot",
                json={"prompt": "hi", "provider": "perplexity"},
            )
        assert r.status_code == 400
        assert "default_model" in r.json()["detail"]


class TestResponseShape:
    """Pin the v1 response contract — semver-stable per docs/api-gateway.md."""

    def test_success_returns_full_envelope(self, http_client, stub_provider):
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            r = http_client.post("/v1/oneshot", json={"prompt": "Hello"})

        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {
            "content", "finish_reason", "model", "provider", "usage"
        }
        assert body["content"] == "stub-response"
        assert body["finish_reason"] == "stop"
        assert body["model"] == "stub-model"
        assert body["provider"] == "custom"
        assert body["usage"] == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }

    def test_usage_can_be_null(self, http_client, stub_provider):
        stub_provider.oneshot.return_value = {
            "content": "x",
            "finish_reason": "stop",
            "model": "m",
            "usage": None,
        }
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            r = http_client.post("/v1/oneshot", json={"prompt": "Hello"})
        assert r.status_code == 200
        assert r.json()["usage"] is None


class TestParameterPlumbing:
    """response_format / max_tokens / temperature must reach the provider."""

    def test_response_format_forwarded(self, http_client, stub_provider):
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            http_client.post(
                "/v1/oneshot",
                json={
                    "prompt": "Hello",
                    "response_format": {"type": "json_object"},
                },
            )
        kwargs = stub_provider.oneshot.call_args.kwargs
        assert kwargs["response_format"] == {"type": "json_object"}

    def test_max_tokens_forwarded(self, http_client, stub_provider):
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            http_client.post(
                "/v1/oneshot", json={"prompt": "Hello", "max_tokens": 256}
            )
        assert stub_provider.oneshot.call_args.kwargs["max_tokens"] == 256

    def test_temperature_forwarded(self, http_client, stub_provider):
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            http_client.post(
                "/v1/oneshot", json={"prompt": "Hello", "temperature": 0.0}
            )
        assert stub_provider.oneshot.call_args.kwargs["temperature"] == 0.0

    def test_system_message_forwarded(self, http_client, stub_provider):
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            http_client.post(
                "/v1/oneshot",
                json={"prompt": "Hello", "system": "You are terse."},
            )
        assert stub_provider.oneshot.call_args.kwargs["system"] == "You are terse."


class TestProviderErrors:
    def test_provider_exception_surfaces_as_502(self, http_client, stub_provider):
        stub_provider.oneshot.side_effect = RuntimeError("API down")
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            r = http_client.post("/v1/oneshot", json={"prompt": "Hello"})
        assert r.status_code == 502
        assert "API down" in r.json()["detail"]


class TestProviderCapabilityCheck:
    """v1 only supports OpenAI-compatible providers; others get a clear 400."""

    def test_non_openai_compat_provider_400(self, http_client):
        # Build a provider that's NOT an OpenAICompatibleProvider instance.
        non_compat = MagicMock()
        # Don't set __class__ to OpenAICompatibleProvider — leave as MagicMock.
        with patch(
            "ppxai.server.routes.oneshot._build_provider", return_value=non_compat
        ), patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="some_provider"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="some_model"
        ):
            r = http_client.post("/v1/oneshot", json={"prompt": "Hello"})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "doesn't support /v1/oneshot" in detail
        assert "POST /chat" in detail  # workaround hint

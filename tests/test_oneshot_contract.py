"""oneshot() is part of the BaseProvider contract (v1.19.x).

Every provider implements `oneshot(prompt, model, ...) -> {content,
finish_reason, model, usage}`, so the v1 gateway tiers (`/v1/oneshot`,
tool-free `/v1/agent/run`) are provider-agnostic. Previously oneshot lived
only on OpenAICompatibleProvider, forcing an isinstance-by-class guard on
the v1 routes (the "v1 agent tier only accepts OpenAI-compatible providers"
gotcha). These tests pin the contract on each provider — especially the
per-vendor USAGE extraction, the one non-trivial bit (OpenAI/Perplexity
`response.usage`; Gemini `usage_metadata`).
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.providers.base import BaseProvider
from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
from ppxai.engine.providers.openai_native import OpenAINativeProvider
from ppxai.engine.providers.gemini import GeminiProvider
from ppxai.engine.providers.perplexity import PerplexityProvider


ALL_PROVIDER_CLASSES = [
    OpenAICompatibleProvider,
    OpenAINativeProvider,
    GeminiProvider,
    PerplexityProvider,
]


# --------------------------------------------------------------------------
# Contract conformance — the regression guard
# --------------------------------------------------------------------------
class TestContractConformance:
    def test_oneshot_is_abstract_on_base(self):
        # If oneshot stops being abstract, a future provider could silently
        # skip it and reintroduce the class-guard problem.
        assert "oneshot" in BaseProvider.__abstractmethods__

    @pytest.mark.parametrize("cls", ALL_PROVIDER_CLASSES)
    def test_every_provider_implements_oneshot(self, cls):
        # Defined on the class itself (not just inherited-abstract).
        assert "oneshot" in cls.__dict__, f"{cls.__name__} must define oneshot"
        assert callable(cls.__dict__["oneshot"])

    @pytest.mark.parametrize("cls", ALL_PROVIDER_CLASSES)
    def test_oneshot_signature_matches_contract(self, cls):
        params = set(inspect.signature(cls.oneshot).parameters) - {"self"}
        assert {"prompt", "model", "system", "response_format",
                "max_tokens", "temperature"} <= params


# --------------------------------------------------------------------------
# Per-provider behavior — content + USAGE extraction
# --------------------------------------------------------------------------
def _openai_sdk_response(content="hi", pt=3, ct=5, tt=8, model="m"):
    """Shape OpenAI/Perplexity SDK responses (response.usage.*)."""
    resp = MagicMock()
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = "stop"
    resp.model = model
    resp.usage.prompt_tokens = pt
    resp.usage.completion_tokens = ct
    resp.usage.total_tokens = tt
    return resp


class TestOpenAINativeOneshot:
    def _provider(self):
        with patch("ppxai.engine.providers.base.OpenAI"):
            return OpenAINativeProvider(api_key="k", provider_id="openai")

    def test_content_and_usage(self):
        p = self._provider()
        p.client = MagicMock()
        p.client.chat.completions.create.return_value = _openai_sdk_response()
        out = p.oneshot(prompt="hello", model="gpt-x")
        assert out["content"] == "hi"
        assert out["finish_reason"] == "stop"
        assert out["usage"] == {"prompt_tokens": 3, "completion_tokens": 5,
                                "total_tokens": 8}


class TestPerplexityOneshot:
    def _provider(self):
        with patch("ppxai.engine.providers.base.OpenAI"):
            return PerplexityProvider(api_key="k", base_url="https://api.perplexity.ai",
                                      provider_id="perplexity")

    def test_content_and_usage(self):
        p = self._provider()
        p.client = MagicMock()
        p.client.chat.completions.create.return_value = _openai_sdk_response(
            content="pong", pt=1, ct=2, tt=3)
        out = p.oneshot(prompt="ping", model="sonar")
        assert out["content"] == "pong"
        assert out["usage"]["total_tokens"] == 3


class TestGeminiOneshot:
    def _provider(self):
        with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            return GeminiProvider(api_key="k", provider_id="gemini")

    def test_content_and_usage_from_metadata(self):
        p = self._provider()
        p.client = MagicMock()

        # Gemini response: candidates[0].content.parts[*].text + usage_metadata.
        part = MagicMock()
        part.text = "gem"
        resp = MagicMock()
        resp.candidates[0].content.parts = [part]
        resp.candidates[0].finish_reason = "STOP"
        um = MagicMock()
        um.prompt_token_count = 4
        um.candidates_token_count = 6
        um.total_token_count = 10
        resp.usage_metadata = um
        p.client.models.generate_content.return_value = resp

        out = p.oneshot(prompt="hi", model="gemini-x")
        assert out["content"] == "gem"
        # Gemini's _parse_usage maps the differently-named fields.
        assert out["usage"] == {"prompt_tokens": 4, "completion_tokens": 6,
                                "total_tokens": 10}

    def test_usage_none_when_no_metadata(self):
        p = self._provider()
        p.client = MagicMock()
        part = MagicMock(); part.text = "x"
        resp = MagicMock()
        resp.candidates[0].content.parts = [part]
        resp.candidates[0].finish_reason = "STOP"
        resp.usage_metadata = None
        p.client.models.generate_content.return_value = resp
        out = p.oneshot(prompt="hi", model="gemini-x")
        assert out["usage"] is None

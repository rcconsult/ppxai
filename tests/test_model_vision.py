"""Tests for supports_vision flag on ModelProfile (Phase 2.5, v1.17.4).

The `supports_vision` flag is the single source of truth for
`file_preprocessing` deciding whether to send an image_url content part
directly or route through a VL sidecar for captioning. Getting it wrong
means either:
    (a) Sending images to a text-only model (API error or silent drop)
    (b) Wastefully captioning images for a vision-capable model

These tests pin the expected classification for every model family in
BUILTIN_PROFILES, so accidentally flipping a flag during a future profile
update is caught immediately. Verified against official provider docs
(OpenAI, Google AI, Perplexity, Mistral) as of April 2026.
"""

from __future__ import annotations

import pytest

from ppxai.engine.model_profiles import (
    ModelProfile,
    ModelProfileRegistry,
    ToolCallingProfile,
    get_profile,
    supports_vision,
)


# -----------------------------------------------------------------------------
# ModelProfile dataclass — new field
# -----------------------------------------------------------------------------


class TestModelProfileField:
    def test_default_is_false(self):
        profile = ModelProfile()
        assert profile.supports_vision is False

    def test_field_is_settable(self):
        profile = ModelProfile(supports_vision=True)
        assert profile.supports_vision is True

    def test_field_coexists_with_other_flags(self):
        profile = ModelProfile(
            supports_reasoning=True,
            supports_vision=True,
            tier="A",
        )
        assert profile.supports_reasoning is True
        assert profile.supports_vision is True
        assert profile.tier == "A"


# -----------------------------------------------------------------------------
# OpenAI family — GPT-5.x, GPT-4.x, GPT-4o
#
# Per OpenAI docs (April 2026): all chat models in the GPT-5 and GPT-4
# families accept image_url input. Reasoning models are a mix — o1, o3,
# o3-pro, o4-mini support vision; o1-mini, o3-mini are text-only.
# -----------------------------------------------------------------------------


class TestOpenAIVisionCapability:
    @pytest.mark.parametrize("model", [
        "gpt-5", "gpt-5.2", "gpt-5-mini", "gpt-5-nano",
        "gpt-5.1-codex", "gpt-5.1-codex-mini",
        # gpt-5.4 family — registry entry added 2026-05-14 (closed gap
        # surfaced when an attached screenshot was silently routed to the
        # text-placeholder fallback because supports_vision returned False
        # via conservative default).
        "gpt-5.4", "gpt-5.4-pro", "gpt-5.4-mini",
        # gpt-5.5 family — registered alongside gpt-5.4 to keep the
        # whole flagship line covered.
        "gpt-5.5", "gpt-5.5-mini",
        "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
        "gpt-4o", "gpt-4o-mini",
    ])
    def test_chat_models_support_vision(self, model):
        assert supports_vision(model) is True, f"{model} should support vision"

    @pytest.mark.parametrize("model", [
        "o1", "o3", "o3-pro", "o4-mini",
    ])
    def test_vision_capable_reasoning_models(self, model):
        assert supports_vision(model) is True, f"{model} should support vision"

    @pytest.mark.parametrize("model", [
        "o1-mini", "o3-mini",
    ])
    def test_text_only_reasoning_models(self, model):
        # These are explicitly text-only per OpenAI — shipping images to
        # them returns an API error.
        assert supports_vision(model) is False, f"{model} should NOT support vision"


# -----------------------------------------------------------------------------
# Google family — Gemini 2.5, 3, 3.1
# -----------------------------------------------------------------------------


class TestGeminiVisionCapability:
    @pytest.mark.parametrize("model", [
        "gemini-2.5-pro", "gemini-2.5-pro-preview",
        "gemini-2.5-flash", "gemini-2.5-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite",
        "gemini-3.1-pro-preview",
        "gemini-3.1-pro-preview-customtools",
    ])
    def test_gemini_chat_models_support_vision(self, model):
        assert supports_vision(model) is True, f"{model} should support vision"


class TestGemma4VisionCapability:
    """Gemma 4 family — v1.17.4 Phase 2.3.

    All variants (31B dense, 26B MoE, E4B edge, E2B edge) include vision.
    The edge variants (E*) additionally support audio but that's tracked
    separately when audio input lands as a feature.
    """

    @pytest.mark.parametrize("model", [
        "gemma-4-31b-it",
        "gemma-4-26b-a4b-it",
        "gemma-4-e4b-it",
        "gemma-4-e2b-it",
    ])
    def test_gemma4_supports_vision(self, model):
        assert supports_vision(model) is True, f"{model} should support vision"


# -----------------------------------------------------------------------------
# Perplexity family — Sonar (selective)
#
# Per Perplexity docs (April 2026): `sonar` and `sonar-pro` accept image
# input. `sonar-reasoning-pro`, `sonar-deep-research`, and the legacy
# `llama-3.1-sonar-*` family are text-only.
# -----------------------------------------------------------------------------


class TestPerplexityVisionCapability:
    @pytest.mark.parametrize("model", [
        "sonar", "sonar-pro",
    ])
    def test_vision_capable_sonar_models(self, model):
        assert supports_vision(model) is True, f"{model} should support vision"

    @pytest.mark.parametrize("model", [
        "sonar-reasoning-pro",
        "sonar-deep-research",
        "llama-3.1-sonar-small-128k-online",
        "llama-3.1-sonar-large-128k-online",
    ])
    def test_text_only_perplexity_models(self, model):
        # These are explicitly text-only — shipping images silently
        # drops them or returns a provider error.
        assert supports_vision(model) is False, f"{model} should NOT support vision"


# -----------------------------------------------------------------------------
# Local VL models — served via Ollama, vLLM, etc.
# -----------------------------------------------------------------------------


class TestLocalVisionModels:
    @pytest.mark.parametrize("model", [
        "qwen3-vl-8b",
        "Qwen/Qwen3-VL-8B-Instruct",
        "qwen2-vl-7b",
        "llava-1.6-34b",
        "llava:latest",
        "pixtral-12b",
        "mistralai/Pixtral-12B-2409",
        "minicpm-v-2.6",
        "openbmb/MiniCPM-V-2_6",
    ])
    def test_local_vl_models_support_vision(self, model):
        assert supports_vision(model) is True, f"{model} should support vision"


# -----------------------------------------------------------------------------
# Text-only local models — qwen coder, gpt-oss, etc.
# -----------------------------------------------------------------------------


class TestTextOnlyLocalModels:
    @pytest.mark.parametrize("model", [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen3-coder-30b",
        "qwen3-coder-next",
        "qwen2.5-coder-7b",
        "qwen2.5-coder:32b-64k",
        "*/qwen3-next-80b-instruct",
        "*/qwen3-30b-a3b",
        "qwen3:30b",
    ])
    def test_text_only_coder_models(self, model):
        assert supports_vision(model) is False, f"{model} should NOT support vision"


# -----------------------------------------------------------------------------
# Unknown / unregistered models → False (conservative default)
# -----------------------------------------------------------------------------


class TestUnknownModels:
    @pytest.mark.parametrize("model", [
        "",
        "not-a-real-model",
        "future-model-2030",
        "fictional/mega-large-xxl",
    ])
    def test_unknown_model_returns_false(self, model):
        # The default ModelProfile() has supports_vision=False, so
        # unknown models fall through to the conservative default.
        assert supports_vision(model) is False


# -----------------------------------------------------------------------------
# Custom profiles override built-ins
# -----------------------------------------------------------------------------


class TestCustomProfiles:
    def test_custom_profile_can_enable_vision(self):
        # A user could register a custom profile claiming vision support
        # for a model we don't know about.
        registry = ModelProfileRegistry()
        registry.register(
            "my-custom-vision-*",
            ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
                supports_vision=True,
            ),
        )
        profile = registry.get("my-custom-vision-7b")
        assert profile.supports_vision is True

    def test_custom_profile_takes_priority_over_builtin(self):
        # If a user overrides gpt-5 with supports_vision=False (unlikely
        # but allowed), the override wins.
        registry = ModelProfileRegistry()
        registry.register(
            "gpt-5*",
            ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
                supports_vision=False,
            ),
        )
        profile = registry.get("gpt-5.2")
        assert profile.supports_vision is False


# -----------------------------------------------------------------------------
# supports_vision() convenience vs get_profile().supports_vision
# -----------------------------------------------------------------------------


class TestConvenienceFunction:
    def test_matches_get_profile(self):
        # supports_vision(m) is sugar for get_profile(m).supports_vision —
        # both paths must return identical results.
        for model in [
            "gpt-5.2",
            "gemini-3-flash-preview",
            "sonar-pro",
            "sonar-reasoning-pro",
            "o3-mini",
            "unknown",
        ]:
            assert supports_vision(model) == get_profile(model).supports_vision

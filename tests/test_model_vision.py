"""Tests for the supports_vision fact (Phase 2.5, v1.17.4; retargeted Item 65).

Originally written against `ModelProfile.supports_vision`. Item 65 retired
the profile vocabulary, so these now assert the same behaviour against
`ModelFacts` and the operator-config override path that replaced the custom
profile registry. The model-by-model expectations are unchanged.

The `supports_vision` flag is the single source of truth for
`file_preprocessing` deciding whether to send an image_url content part
directly or route through a VL sidecar for captioning. Getting it wrong
means either:
    (a) Sending images to a text-only model (API error or silent drop)
    (b) Wastefully captioning images for a vision-capable model

These tests pin the expected classification for every model family in
the shipped facts table, so flipping a flag during a future
update is caught immediately. Verified against official provider docs
(OpenAI, Google AI, Perplexity, Mistral) as of April 2026.
"""

from __future__ import annotations

import pytest

from ppxai.engine.model_facts import (
    ModelFacts,
    shipped_facts_for_model,
    supports_vision,
)

# -----------------------------------------------------------------------------
# ModelFacts dataclass — the supports_vision field
# -----------------------------------------------------------------------------


class TestModelFactsField:
    """Item 65 retargeted this from `ModelProfile` to `ModelFacts`.

    Same three properties, asserted against the record that survived. The
    conservative default is the one that matters: an unmeasured model must
    not claim vision, because a wrong True sends an image to a provider that
    cannot read it.
    """

    def test_default_is_false(self):
        assert ModelFacts().supports_vision is False

    def test_field_is_settable(self):
        assert ModelFacts(supports_vision=True).supports_vision is True

    def test_field_coexists_with_other_flags(self):
        facts = ModelFacts(
            supports_reasoning=True,
            supports_vision=True,
            tier="A",
        )
        assert facts.supports_reasoning is True
        assert facts.supports_vision is True
        assert facts.tier == "A"


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
        # The default ModelFacts() has supports_vision=False, so
        # unknown models fall through to the conservative default.
        assert supports_vision(model) is False


# -----------------------------------------------------------------------------
# Custom profiles override built-ins
# -----------------------------------------------------------------------------


class TestOperatorOverrides:
    """The capability the retired `ModelProfileRegistry` provided.

    Item 65 deleted that registry; the same need — an operator declaring
    vision for a model our table does not know, or correcting one it gets
    wrong — is served by `providers.<p>.models.<m>.facts.supports_vision`,
    which `resolve_model_facts` applies over the shipped row. Testing it here
    keeps the CAPABILITY fenced rather than the vanished implementation.
    """

    def test_an_operator_can_declare_vision_for_an_unknown_model(self, monkeypatch):
        import ppxai.config.facts_config as fc

        monkeypatch.setattr(
            fc, "model_fact_overrides",
            lambda provider, model, block=None: {"supports_vision": True},
        )
        base = shipped_facts_for_model("my-custom-vision-7b")
        assert base.supports_vision is False, "fixture drifted: expected the floor"
        assert fc.resolve_model_facts(
            base, "local-vllm", "my-custom-vision-7b"
        ).supports_vision is True

    def test_an_operator_override_beats_the_shipped_row(self, monkeypatch):
        """The other direction, and the one with teeth: turning vision OFF
        for a model we ship as vision-capable."""
        import ppxai.config.facts_config as fc

        shipped = shipped_facts_for_model("gpt-5.2")
        assert shipped.supports_vision is True, "fixture drifted: gpt-5.2 was vision"
        monkeypatch.setattr(
            fc, "model_fact_overrides",
            lambda provider, model, block=None: {"supports_vision": False},
        )
        assert fc.resolve_model_facts(
            shipped, "openai", "gpt-5.2"
        ).supports_vision is False


class TestConvenienceFunction:
    """`supports_vision(m)` was sugar for `get_profile(m).supports_vision`.

    `get_profile` is gone with the profile registry, so the old "both paths
    agree" test has no second path to compare against. What remains true and
    worth pinning is that the helper reads the SHIPPED FACTS record — the
    same record every other consumer resolves — rather than keeping a private
    answer.
    """

    @pytest.mark.parametrize("model", [
        "gpt-5.2",
        "gemini-3-flash-preview",
        "sonar-pro",
        "sonar-reasoning-pro",
        "o3-mini",
        "unknown-model-xyz",
    ])
    def test_it_reads_the_shipped_facts_record(self, model):
        assert supports_vision(model) is shipped_facts_for_model(model).supports_vision

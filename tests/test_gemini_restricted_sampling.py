"""Gemini 3.6+ is never sent temperature / top_p / top_k (2026-10-08).

Google's deprecation notice: since Gemini 3.6 Flash, sampling parameters are
fixed at their defaults (custom values change nothing), and the upcoming
models answer 400 INVALID_ARGUMENT to `temperature`, `top_p` and `top_k`.
`thinking_budget` likewise stops being remapped to `thinking_level`.

Until this change a provider-level `generation_params` reached every Gemini
model unfiltered: the shipped configs sent temperature 0.2 / top_p 0.9 on
every chat and oneshot request. `ModelFacts.restricted_params` already
existed; `GeminiProvider` did not read it.

The floor matters as much as the rows: an UNLISTED Gemini model is a newer
one, so `GeminiProvider.unmeasured_facts` restricts the three too.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.model_facts import shipped_facts_for_model
from ppxai.engine.providers.gemini import GeminiProvider, is_available
from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

pytestmark = pytest.mark.skipif(
    not is_available(), reason="google-genai not installed"
)

SAMPLING = {"temperature": 0.2, "top_p": 0.9}
RESTRICTED = {"temperature", "top_p", "top_k"}


def _make_provider() -> GeminiProvider:
    with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
        mock_genai.Client.return_value = MagicMock()
        return GeminiProvider(api_key="test-key", provider_id="gemini")


@pytest.mark.parametrize(
    "model",
    [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        # Unlisted: resolves to the provider floor, which must restrict too.
        "gemini-3.9-flash",
        "gemini-4-pro-preview",
    ],
)
def test_sampling_params_are_not_sent_to_36_and_newer(model):
    config = _make_provider()._build_config(
        model=model, use_grounding=False, generation_params=dict(SAMPLING)
    )
    sent = config.model_dump(exclude_none=True) if config is not None else {}
    assert not RESTRICTED & set(sent), f"{model} was sent {RESTRICTED & set(sent)}"


@pytest.mark.parametrize(
    "model", ["gemini-3.5-flash", "gemini-3.1-pro-preview", "gemma-4-31b-it"]
)
def test_older_models_still_get_them(model):
    """Positive control: the filter is per model, not a blanket drop."""
    config = _make_provider()._build_config(
        model=model, use_grounding=False, generation_params=dict(SAMPLING)
    )
    assert config.temperature == 0.2
    assert config.top_p == 0.9


def test_other_generation_params_survive_the_filter():
    config = _make_provider()._build_config(
        model="gemini-3.8-flash",
        use_grounding=False,
        generation_params={**SAMPLING, "max_tokens": 1234, "stop": ["END"]},
    )
    assert config.max_output_tokens == 1234
    assert config.stop_sequences == ["END"]


def test_thinking_config_never_carries_a_budget():
    """`thinking_budget` 400s on the upcoming models; ppxai sends a level."""
    provider = _make_provider()
    provider.thinking_level = "low"
    config = provider._build_config(model="gemini-3.8-flash", use_grounding=False)
    thinking = config.thinking_config.model_dump(exclude_none=True)
    assert "thinking_budget" not in thinking
    assert thinking.get("thinking_level") is not None


def test_the_floor_restricts_sampling():
    floor = GeminiProvider.unmeasured_facts
    assert floor.wire_protocol == "generate_content"
    assert RESTRICTED <= set(floor.restricted_params)


@pytest.mark.parametrize(
    "model", ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"]
)
def test_the_seed_rows_restrict_sampling(model):
    assert RESTRICTED <= set(shipped_facts_for_model(model).restricted_params)


def test_openai_compat_fallback_honours_the_facts():
    """Without google-genai the `gemini` id is an OpenAI-compat provider on
    `/v1beta/openai`; the per-model restriction must apply there too."""
    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="http://127.0.0.1:9/v1",
        provider_id="gemini",
    )
    captured: dict = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop after capture")

    provider.client = MagicMock()
    provider.client.chat.completions.create.side_effect = fake_create
    with patch.object(provider, "_get_generation_params", return_value=dict(SAMPLING)):
        with pytest.raises(Exception):
            provider.oneshot(prompt="hi", model="gemini-3.8-flash")
    assert captured, "request was never built"
    assert not RESTRICTED & set(captured)

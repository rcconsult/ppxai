"""Claude 4.7+ on an OpenAI-compatible aggregator never gets sampling params.

Measured 2026-10-08 on OpenRouter with `require_parameters`: sonnet, opus
and haiku 5.5 each answered 404 "No endpoints found that can handle the
requested parameters" to `temperature` alone and to `top_p` alone, and made
a native tool call once neither was sent. The shipped OpenRouter config
sends both from provider-level `generation_params`, so without these seed
rows every Claude request on it failed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.model_facts import shipped_facts_for_model
from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

RESTRICTED = {"temperature", "top_p", "top_k"}


@pytest.mark.parametrize(
    "model",
    [
        "anthropic/claude-sonnet-5.5",
        "anthropic/claude-opus-5.5",
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5",
        "anthropic/claude-opus-4.7",
        "anthropic/claude-opus-4.8",
    ],
)
def test_the_seed_restricts_sampling_and_is_native(model):
    facts = shipped_facts_for_model(model)
    assert RESTRICTED <= set(facts.restricted_params)
    assert facts.tool_mode == "native"
    assert facts.wire_protocol == "chat_completions"


@pytest.mark.parametrize(
    "model", ["anthropic/claude-sonnet-4", "anthropic/claude-sonnet-4.5"]
)
def test_older_claude_ids_are_not_swept_in(model):
    """Positive control: the globs name the restricted family only."""
    assert not RESTRICTED & set(shipped_facts_for_model(model).restricted_params)


def test_the_compat_provider_drops_them_on_the_wire():
    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="http://127.0.0.1:9/v1",
        provider_id="openrouter",
    )
    captured: dict = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop after capture")

    provider.client = MagicMock()
    provider.client.chat.completions.create.side_effect = fake_create
    with patch.object(
        provider,
        "_get_generation_params",
        return_value={"temperature": 0.2, "top_p": 0.9},
    ):
        with pytest.raises(Exception):
            provider.oneshot(prompt="hi", model="anthropic/claude-haiku-5.5")
    assert captured, "request was never built"
    assert not RESTRICTED & set(captured)

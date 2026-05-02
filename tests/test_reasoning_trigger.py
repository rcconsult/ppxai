"""Tests for v1.18.3 reasoning_trigger config + system-prompt injection.

Some models (notably ``nvidia/llama-3.3-nemotron-super-49b-v1.5``)
toggle reasoning via an in-prompt marker: appending ``/think`` enables
it, ``/no_think`` disables it. v1.18.3 adds a per-model
``reasoning_trigger`` config field plus a base-class helper that
appends the marker to the system message before sending.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ppxai.config import get_reasoning_trigger
from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider


def _write_config(tmp_path: Path, providers: dict) -> Path:
    cfg_path = tmp_path / "ppxai-config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "version": "1.3",
                "default_provider": next(iter(providers)),
                "providers": providers,
            }
        ),
        encoding="utf-8",
    )
    return cfg_path


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PPXAI_CONFIG_FILE", "")
    yield tmp_path


# ---------------------------------------------------------------------------
# Config-layer behavior
# ---------------------------------------------------------------------------


class TestGetReasoningTrigger:
    def test_no_config_returns_none(self, isolated_config, monkeypatch):
        cfg = _write_config(
            isolated_config,
            {"nvidia": {"name": "X", "base_url": "https://x", "api_key_env": "K"}},
        )
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))
        assert get_reasoning_trigger("nvidia", "any-model") is None

    def test_provider_level_only(self, isolated_config, monkeypatch):
        cfg = _write_config(
            isolated_config,
            {
                "nvidia": {
                    "name": "X",
                    "base_url": "https://x",
                    "api_key_env": "K",
                    "reasoning_trigger": "/think",
                }
            },
        )
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))
        assert get_reasoning_trigger("nvidia", "any-model") == "/think"

    def test_model_level_overrides_provider(self, isolated_config, monkeypatch):
        cfg = _write_config(
            isolated_config,
            {
                "nvidia": {
                    "name": "X",
                    "base_url": "https://x",
                    "api_key_env": "K",
                    "reasoning_trigger": "/no_think",  # provider default off
                    "models": {
                        "nvidia/llama-3.3-nemotron-super-49b-v1.5": {
                            "reasoning_trigger": "/think"  # opt back in for this model
                        }
                    },
                }
            },
        )
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))
        assert (
            get_reasoning_trigger("nvidia", "nvidia/llama-3.3-nemotron-super-49b-v1.5")
            == "/think"
        )
        # Other models still see the provider default
        assert get_reasoning_trigger("nvidia", "qwen/qwen3.5-122b-a10b") == "/no_think"

    def test_empty_string_treated_as_none(self, isolated_config, monkeypatch):
        cfg = _write_config(
            isolated_config,
            {
                "nvidia": {
                    "name": "X",
                    "base_url": "https://x",
                    "api_key_env": "K",
                    "reasoning_trigger": "   ",  # whitespace only
                }
            },
        )
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))
        assert get_reasoning_trigger("nvidia", "any-model") is None


# ---------------------------------------------------------------------------
# Provider-layer wiring
# ---------------------------------------------------------------------------


def _make_provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://integrate.api.nvidia.com/v1",
        models={},
        provider_id="nvidia",
    )


class TestApplyReasoningTrigger:
    def test_no_trigger_returns_input_unchanged(self):
        provider = _make_provider()
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
        ]
        with patch(
            "ppxai.engine.providers.base.get_reasoning_trigger",
            return_value=None,
        ):
            result = provider._apply_reasoning_trigger(msgs, "any-model")
        assert result == msgs
        assert result is msgs  # no-op returns same list

    def test_trigger_appended_to_existing_system_message(self):
        provider = _make_provider()
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
        ]
        with patch(
            "ppxai.engine.providers.base.get_reasoning_trigger",
            return_value="/think",
        ):
            result = provider._apply_reasoning_trigger(msgs, "nemotron")
        assert result[0]["role"] == "system"
        assert result[0]["content"].endswith("/think")
        assert "You are helpful." in result[0]["content"]
        # Original list NOT mutated
        assert msgs[0]["content"] == "You are helpful."
        # Other messages preserved
        assert result[1] == {"role": "user", "content": "hi"}

    def test_trigger_idempotent(self):
        provider = _make_provider()
        msgs = [{"role": "system", "content": "Be brief.\n\n/think"}]
        with patch(
            "ppxai.engine.providers.base.get_reasoning_trigger",
            return_value="/think",
        ):
            result = provider._apply_reasoning_trigger(msgs, "nemotron")
        # Should not duplicate /think when already present at end
        assert result[0]["content"].count("/think") == 1

    def test_trigger_prepended_when_no_system_message(self):
        provider = _make_provider()
        msgs = [{"role": "user", "content": "hi"}]
        with patch(
            "ppxai.engine.providers.base.get_reasoning_trigger",
            return_value="/think",
        ):
            result = provider._apply_reasoning_trigger(msgs, "nemotron")
        assert result[0] == {"role": "system", "content": "/think"}
        assert result[1] == {"role": "user", "content": "hi"}

    def test_only_first_system_message_modified(self):
        """Defensive: even if multiple system messages exist (unusual but
        legal), only the first one is touched — matches OpenAI's
        convention of treating the first system as the primary."""
        provider = _make_provider()
        msgs = [
            {"role": "system", "content": "Primary."},
            {"role": "user", "content": "x"},
            {"role": "system", "content": "Secondary."},
        ]
        with patch(
            "ppxai.engine.providers.base.get_reasoning_trigger",
            return_value="/think",
        ):
            result = provider._apply_reasoning_trigger(msgs, "nemotron")
        assert result[0]["content"].endswith("/think")
        assert result[2]["content"] == "Secondary."  # untouched

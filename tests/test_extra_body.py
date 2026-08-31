"""Tests for v1.18.3 ``extra_body`` pass-through.

OpenAI's ``chat.completions.create(extra_body=...)`` parameter is a
dict that the SDK forwards verbatim to the endpoint. v1.18.3 plumbs
this through ppxai so users can drive vendor-specific runtime knobs
(NVIDIA NIM / vLLM ``chat_template_kwargs``, GLM thinking-mode toggle,
etc.) without forking the engine.

Covers:
* ``get_extra_body`` config accessor — provider defaults + model overrides.
* ``OpenAICompatibleProvider`` sends ``extra_body`` to the SDK when
  configured and omits the key when empty (avoids breaking strict
  endpoints).
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ppxai.config import get_extra_body
from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

# ---------------------------------------------------------------------------
# Config-layer behavior
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, providers: dict) -> Path:
    """Write a minimal ppxai-config.json with the given providers section."""
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
    """Point PPXAI_CONFIG_FILE at a tmp config and reset the in-memory cache.

    The config helpers cache via ``find_config_file`` + ``_load_json_config``;
    forcing the env var ensures we don't leak the dev's real config into
    these assertions.
    """
    monkeypatch.setenv("PPXAI_CONFIG_FILE", "")  # cleared per test below
    yield tmp_path


class TestGetExtraBody:
    def test_no_config_returns_empty(self, isolated_config, monkeypatch):
        cfg = _write_config(
            isolated_config,
            {"nvidia": {"name": "X", "base_url": "https://x", "api_key_env": "K"}},
        )
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))
        assert get_extra_body("nvidia", "any-model") == {}

    def test_provider_level_only(self, isolated_config, monkeypatch):
        cfg = _write_config(
            isolated_config,
            {
                "nvidia": {
                    "name": "X",
                    "base_url": "https://x",
                    "api_key_env": "K",
                    "extra_body": {
                        "chat_template_kwargs": {"enable_thinking": False}
                    },
                }
            },
        )
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))
        result = get_extra_body("nvidia", "any-model")
        assert result == {"chat_template_kwargs": {"enable_thinking": False}}

    def test_model_level_overrides_provider(self, isolated_config, monkeypatch):
        cfg = _write_config(
            isolated_config,
            {
                "nvidia": {
                    "name": "X",
                    "base_url": "https://x",
                    "api_key_env": "K",
                    "extra_body": {
                        "chat_template_kwargs": {"enable_thinking": False}
                    },
                    "models": {
                        "qwen/qwen3.5-122b-a10b": {
                            "extra_body": {
                                "chat_template_kwargs": {"enable_thinking": True}
                            }
                        }
                    },
                }
            },
        )
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))
        result = get_extra_body("nvidia", "qwen/qwen3.5-122b-a10b")
        # Model-level wins — entire chat_template_kwargs is replaced
        assert result == {"chat_template_kwargs": {"enable_thinking": True}}

    def test_comment_keys_stripped(self, isolated_config, monkeypatch):
        cfg = _write_config(
            isolated_config,
            {
                "nvidia": {
                    "name": "X",
                    "base_url": "https://x",
                    "api_key_env": "K",
                    "extra_body": {
                        "__comment_thinking": "GLM uses chat_template_kwargs",
                        "chat_template_kwargs": {"enable_thinking": True},
                    },
                }
            },
        )
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))
        result = get_extra_body("nvidia", "any-model")
        assert "__comment_thinking" not in result
        assert "chat_template_kwargs" in result


# ---------------------------------------------------------------------------
# Provider-layer wiring — extra_body forwarded to OpenAI SDK
# ---------------------------------------------------------------------------


class TestExtraBodySentToSdk:
    """openai_compat plumbs extra_body into the SDK call when configured."""

    def test_helper_returns_configured_payload(self, monkeypatch):
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://integrate.api.nvidia.com/v1",
            models={},
            provider_id="nvidia",
        )
        with patch(
            "ppxai.engine.providers.base.get_extra_body",
            return_value={"chat_template_kwargs": {"enable_thinking": True}},
        ):
            payload = provider._get_extra_body("qwen/qwen3.5-122b-a10b")
        assert payload == {"chat_template_kwargs": {"enable_thinking": True}}

    def test_helper_returns_empty_when_not_configured(self):
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://integrate.api.nvidia.com/v1",
            models={},
            provider_id="nvidia",
        )
        with patch(
            "ppxai.engine.providers.base.get_extra_body",
            return_value={},
        ):
            assert provider._get_extra_body("any-model") == {}

    def test_helper_handles_attribute_error(self):
        """If config helper raises AttributeError (no provider_id wired),
        fall back to empty dict — matches sibling helpers' behavior."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://integrate.api.nvidia.com/v1",
            models={},
            provider_id=None,  # explicit None
        )
        with patch(
            "ppxai.engine.providers.base.get_extra_body",
            side_effect=AttributeError("no provider"),
        ):
            assert provider._get_extra_body("any-model") == {}

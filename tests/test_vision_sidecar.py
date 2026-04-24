"""Tests for vision-language sidecar (Phase 2.7, v1.17.4).

Exercises:

1. `get_vision_model_config` — defaults and overrides via the config store
2. `EngineClient.has_vision_sidecar` — truthiness across config states
3. `EngineClient.caption_image` — successful captioning via a mocked
   OpenAI client, plus every failure mode (disabled, missing endpoint,
   SDK missing, HTTP error, malformed response)
4. End-to-end preprocessing integration — when the captioner returns a
   string, `preprocess_file` routes a text-only-model image through
   the VL path instead of the placeholder

The OpenAI SDK is mocked at the `openai.OpenAI` import site inside
`caption_image`, so no real network calls are made.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.client import EngineClient


# -----------------------------------------------------------------------------
# Config loader
# -----------------------------------------------------------------------------


class TestGetVisionModelConfig:
    def test_defaults_when_section_missing(self):
        """Unconfigured section returns sensible disabled defaults."""
        from ppxai.config import get_vision_model_config
        from ppxai.config.store import ConfigStore

        store = ConfigStore.get_instance()
        original = dict(store.config)
        store.set_for_testing({"tools": {}})  # no vision_model section
        try:
            cfg = get_vision_model_config()
        finally:
            store.set_for_testing(original)

        assert cfg["enabled"] is False
        assert cfg["endpoint"] == ""
        assert cfg["model"] == ""
        assert cfg["auto_caption"] is True
        assert cfg["timeout"] == 30
        assert cfg["max_tokens"] == 200
        assert "Describe this image" in cfg["prompt"]

    def test_reads_configured_values(self):
        from ppxai.config import get_vision_model_config
        from ppxai.config.store import ConfigStore

        store = ConfigStore.get_instance()
        original = dict(store.config)
        store.set_for_testing({
            "tools": {
                "vision_model": {
                    "enabled": True,
                    "endpoint": "http://localhost:11434/v1",
                    "model": "qwen2.5vl:7b",
                    "api_key_env": "MY_KEY",
                    "timeout": 60,
                    "max_tokens": 150,
                    "prompt": "Caption this.",
                },
            },
        })
        try:
            cfg = get_vision_model_config()
        finally:
            store.set_for_testing(original)

        assert cfg["enabled"] is True
        assert cfg["endpoint"] == "http://localhost:11434/v1"
        assert cfg["model"] == "qwen2.5vl:7b"
        assert cfg["api_key_env"] == "MY_KEY"
        assert cfg["timeout"] == 60
        assert cfg["max_tokens"] == 150
        assert cfg["prompt"] == "Caption this."


# -----------------------------------------------------------------------------
# has_vision_sidecar
# -----------------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """Fresh EngineClient with store redirected to tmp_path."""
    import ppxai.engine.session_store as store_mod
    monkeypatch.setattr(store_mod, "_DEFAULT_STAGING_DIR", tmp_path / "staging")
    (tmp_path / "staging").mkdir()
    client = EngineClient()
    client.session.sessions_dir = tmp_path / "sessions"
    client.session.sessions_dir.mkdir(parents=True, exist_ok=True)
    return client


def _set_vision_config(values: dict):
    """Helper to inject a vision_model config section for tests.

    Uses ConfigStore.set_for_testing() to replace the config atomically,
    returning the previous config dict so the caller can restore it.
    """
    from ppxai.config.store import ConfigStore
    store = ConfigStore.get_instance()
    original = dict(store.config) if store.config else {}

    new_config = {**original}
    existing_tools = dict(new_config.get("tools", {}))
    existing_tools["vision_model"] = values
    new_config["tools"] = existing_tools
    store.set_for_testing(new_config)
    return original


def _restore_config(original):
    from ppxai.config.store import ConfigStore
    ConfigStore.get_instance().set_for_testing(original)


class TestHasVisionModel:
    def test_disabled_returns_false(self, engine):
        original = _set_vision_config({"enabled": False})
        try:
            assert engine.has_vision_sidecar() is False
        finally:
            _restore_config(original)

    def test_enabled_but_no_endpoint_returns_false(self, engine):
        original = _set_vision_config({
            "enabled": True,
            "endpoint": "",
            "model": "qwen2.5vl",
        })
        try:
            assert engine.has_vision_sidecar() is False
        finally:
            _restore_config(original)

    def test_enabled_but_no_model_returns_false(self, engine):
        original = _set_vision_config({
            "enabled": True,
            "endpoint": "http://localhost:11434",
            "model": "",
        })
        try:
            assert engine.has_vision_sidecar() is False
        finally:
            _restore_config(original)

    def test_fully_configured_returns_true(self, engine):
        original = _set_vision_config({
            "enabled": True,
            "endpoint": "http://localhost:11434/v1",
            "model": "qwen2.5vl:7b",
        })
        try:
            assert engine.has_vision_sidecar() is True
        finally:
            _restore_config(original)


# -----------------------------------------------------------------------------
# caption_image
# -----------------------------------------------------------------------------


class TestCaptionImage:
    def _mock_response(self, text: str):
        """Build a fake OpenAI SDK response with the given caption text."""
        choice = SimpleNamespace(
            message=SimpleNamespace(content=text),
        )
        return SimpleNamespace(choices=[choice])

    def test_returns_empty_when_disabled(self, engine):
        original = _set_vision_config({"enabled": False})
        try:
            result = engine.caption_image("x.png", "image/png", b"bytes")
            assert result == ""
        finally:
            _restore_config(original)

    def test_returns_empty_when_endpoint_missing(self, engine):
        original = _set_vision_config({
            "enabled": True,
            "endpoint": "",
            "model": "qwen2.5vl",
        })
        try:
            result = engine.caption_image("x.png", "image/png", b"bytes")
            assert result == ""
        finally:
            _restore_config(original)

    def test_successful_caption(self, engine):
        original = _set_vision_config({
            "enabled": True,
            "endpoint": "http://localhost:11434/v1",
            "model": "qwen2.5vl:7b",
            "timeout": 30,
            "max_tokens": 200,
            "prompt": "Describe this.",
        })
        try:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = (
                self._mock_response("a red square on a white background")
            )

            with patch("openai.OpenAI", return_value=mock_client):
                result = engine.caption_image(
                    "chart.png", "image/png", b"fake_bytes"
                )

            assert result == "a red square on a white background"
            # Verify the request was built correctly.
            call = mock_client.chat.completions.create.call_args
            assert call.kwargs["model"] == "qwen2.5vl:7b"
            assert call.kwargs["max_tokens"] == 200
            messages = call.kwargs["messages"]
            assert len(messages) == 1
            content = messages[0]["content"]
            assert content[0]["type"] == "text"
            assert "Describe this" in content[0]["text"]
            assert content[1]["type"] == "image_url"
            assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        finally:
            _restore_config(original)

    def test_caption_stripped_of_whitespace(self, engine):
        original = _set_vision_config({
            "enabled": True,
            "endpoint": "http://localhost:11434/v1",
            "model": "qwen2.5vl",
        })
        try:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = (
                self._mock_response("  leading and trailing spaces  \n\n")
            )
            with patch("openai.OpenAI", return_value=mock_client):
                result = engine.caption_image("x.png", "image/png", b"bytes")
            assert result == "leading and trailing spaces"
        finally:
            _restore_config(original)

    def test_http_error_returns_empty(self, engine):
        original = _set_vision_config({
            "enabled": True,
            "endpoint": "http://localhost:11434/v1",
            "model": "qwen2.5vl",
        })
        try:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = RuntimeError("network")
            with patch("openai.OpenAI", return_value=mock_client):
                result = engine.caption_image("x.png", "image/png", b"bytes")
            assert result == ""
        finally:
            _restore_config(original)

    def test_malformed_response_returns_empty(self, engine):
        original = _set_vision_config({
            "enabled": True,
            "endpoint": "http://localhost:11434/v1",
            "model": "qwen2.5vl",
        })
        try:
            mock_client = MagicMock()
            # Response with no choices — IndexError path
            mock_client.chat.completions.create.return_value = SimpleNamespace(choices=[])
            with patch("openai.OpenAI", return_value=mock_client):
                result = engine.caption_image("x.png", "image/png", b"bytes")
            assert result == ""
        finally:
            _restore_config(original)

    def test_none_content_returns_empty(self, engine):
        """OpenAI SDK sometimes returns content=None for empty responses."""
        original = _set_vision_config({
            "enabled": True,
            "endpoint": "http://localhost:11434/v1",
            "model": "qwen2.5vl",
        })
        try:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
            )
            with patch("openai.OpenAI", return_value=mock_client):
                result = engine.caption_image("x.png", "image/png", b"bytes")
            assert result == ""
        finally:
            _restore_config(original)

    def test_api_key_env_read_from_environment(self, engine, monkeypatch):
        monkeypatch.setenv("MY_VL_KEY", "secret123")
        original = _set_vision_config({
            "enabled": True,
            "endpoint": "http://localhost:8001/v1",
            "model": "qwen2.5vl",
            "api_key_env": "MY_VL_KEY",
        })
        try:
            mock_client_factory = MagicMock()
            mock_client_factory.return_value.chat.completions.create.return_value = (
                self._mock_response("caption")
            )
            with patch("openai.OpenAI", mock_client_factory):
                engine.caption_image("x.png", "image/png", b"bytes")
            # OpenAI() should have been called with the env-sourced key.
            call = mock_client_factory.call_args
            assert call.kwargs["api_key"] == "secret123"
        finally:
            _restore_config(original)


# -----------------------------------------------------------------------------
# End-to-end: preprocessing integration with a captioner
# -----------------------------------------------------------------------------


class TestPreprocessingWithSidecar:
    def test_engine_caption_image_threaded_through_preprocess(self, engine):
        """When the sidecar is configured and the model is text-only,
        `build_multimodal_content` feeds `engine.caption_image` into
        `preprocess_file`, which returns a text caption block.
        """
        from ppxai.commands.attach import PendingFile, build_multimodal_content
        import base64

        # Real PNG bytes so image validation passes.
        red_png = base64.b64decode(
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP"
            b"4z8DwHwAFAQH/c4X0gAAAAABJRU5ErkJggg=="
        )

        pf = PendingFile(
            name="chart.png",
            path="/tmp/chart.png",
            media_type="image/png",
            size=len(red_png),
            kind="image",
            data=red_png,
        )

        original = _set_vision_config({
            "enabled": True,
            "endpoint": "http://localhost:11434/v1",
            "model": "qwen2.5vl",
        })
        try:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="a minimalist red square")
                )]
            )
            with patch("openai.OpenAI", return_value=mock_client):
                # Text-only model → preprocess_file should call the
                # captioner rather than emit a placeholder.
                parts = build_multimodal_content(
                    "describe",
                    [pf],
                    model="openai/gpt-oss-120b",  # text-only
                    provider="local",
                    file_store=engine.file_store,
                    vl_captioner=engine.caption_image,
                )

            # Result should contain text describing the image, not an
            # image_url part (text-only model can't receive images).
            text_parts = [p for p in parts if p.get("type") == "text"]
            image_parts = [p for p in parts if p.get("type") == "image_url"]
            assert image_parts == []
            assert len(text_parts) >= 1
            # Caption should appear in the merged text.
            merged = "\n".join(p["text"] for p in text_parts)
            assert "a minimalist red square" in merged
            assert "chart.png" in merged
        finally:
            _restore_config(original)

    def test_placeholder_when_sidecar_unavailable(self, engine):
        """Without a sidecar, text-only models get the placeholder path."""
        from ppxai.commands.attach import PendingFile, build_multimodal_content
        import base64

        red_png = base64.b64decode(
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP"
            b"4z8DwHwAFAQH/c4X0gAAAAABJRU5ErkJggg=="
        )
        pf = PendingFile(
            name="chart.png",
            path="/tmp/chart.png",
            media_type="image/png",
            size=len(red_png),
            kind="image",
            data=red_png,
        )

        parts = build_multimodal_content(
            "describe",
            [pf],
            model="openai/gpt-oss-120b",
            provider="local",
            file_store=engine.file_store,
            vl_captioner=None,  # no sidecar
        )
        # Placeholder text should surface the "vision not supported" reason.
        merged = "\n".join(
            p["text"] for p in parts if p.get("type") == "text"
        )
        assert "does not support images" in merged

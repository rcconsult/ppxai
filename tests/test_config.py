"""Unit tests for ppxai.config module."""
import os
import pytest
from unittest.mock import patch
from ppxai.config import (
    SESSIONS_DIR,
    EXPORTS_DIR,
    USAGE_FILE,
    MODEL_PRICING,
    MODELS,
    CODING_MODEL,
    MODEL_PROVIDER,
    PROVIDERS,
    get_provider_config,
    get_active_models,
    get_active_pricing,
    get_api_key,
    get_base_url,
    get_coding_model,
)


class TestConfig:
    """Tests for configuration constants."""

    def test_sessions_dir_exists(self):
        """Test that sessions directory is created."""
        assert SESSIONS_DIR.exists()
        assert SESSIONS_DIR.is_dir()

    def test_exports_dir_exists(self):
        """Test that exports directory is created."""
        assert EXPORTS_DIR.exists()
        assert EXPORTS_DIR.is_dir()

    def test_usage_file_path(self):
        """Test that usage file path is valid."""
        assert USAGE_FILE.name == "usage.json"
        assert USAGE_FILE.parent.name == ".ppxai"

    def test_model_pricing_structure(self):
        """Test that model pricing has correct structure."""
        assert len(MODEL_PRICING) > 0
        for model, pricing in MODEL_PRICING.items():
            assert "input" in pricing
            assert "output" in pricing
            assert isinstance(pricing["input"], (int, float))
            assert isinstance(pricing["output"], (int, float))
            assert pricing["input"] >= 0
            assert pricing["output"] >= 0

    def test_models_structure(self):
        """Test that models have correct structure."""
        assert len(MODELS) > 0
        for key, model in MODELS.items():
            assert "id" in model
            assert "name" in model
            assert "description" in model
            assert isinstance(model["id"], str)
            assert isinstance(model["name"], str)
            assert isinstance(model["description"], str)

    def test_coding_model_valid(self):
        """Test that coding model is a valid model ID."""
        model_ids = [m["id"] for m in MODELS.values()]
        assert CODING_MODEL in model_ids

    def test_all_models_have_pricing(self):
        """Test that all models have pricing defined."""
        for model in MODELS.values():
            assert model["id"] in MODEL_PRICING, f"No pricing for {model['id']}"


class TestProviderConfig:
    """Tests for multi-provider configuration."""

    def test_providers_dict_exists(self):
        """Test that PROVIDERS dictionary exists with expected providers."""
        assert "perplexity" in PROVIDERS
        assert "custom" in PROVIDERS

    def test_perplexity_provider_structure(self):
        """Test Perplexity provider has all required fields."""
        provider = PROVIDERS["perplexity"]
        assert "name" in provider
        assert "base_url" in provider
        assert "api_key_env" in provider
        assert "models" in provider
        assert "pricing" in provider
        assert "coding_model" in provider
        assert provider["base_url"] == "https://api.perplexity.ai"
        assert provider["api_key_env"] == "PERPLEXITY_API_KEY"

    def test_custom_provider_structure(self):
        """Test custom provider has all required fields."""
        provider = PROVIDERS["custom"]
        assert "name" in provider
        assert "base_url" in provider
        assert "api_key_env" in provider
        assert "models" in provider
        assert "pricing" in provider
        assert "coding_model" in provider
        assert provider["api_key_env"] == "CUSTOM_API_KEY"

    def test_provider_models_have_required_fields(self):
        """Test that all provider models have required fields."""
        for provider_name, config in PROVIDERS.items():
            for key, model in config["models"].items():
                assert "id" in model, f"{provider_name} model {key} missing 'id'"
                assert "name" in model, f"{provider_name} model {key} missing 'name'"
                assert "description" in model, f"{provider_name} model {key} missing 'description'"

    def test_get_provider_config_default(self):
        """Test get_provider_config returns default provider config."""
        config = get_provider_config()
        assert config == PROVIDERS[MODEL_PROVIDER]

    def test_get_provider_config_perplexity(self):
        """Test get_provider_config for perplexity provider."""
        config = get_provider_config("perplexity")
        assert config["name"] == "Perplexity AI"
        assert config["base_url"] == "https://api.perplexity.ai"

    def test_get_provider_config_custom(self):
        """Test get_provider_config for custom provider."""
        config = get_provider_config("custom")
        assert config["api_key_env"] == "CUSTOM_API_KEY"
        assert len(config["models"]) >= 1

    def test_get_provider_config_invalid_falls_back(self):
        """Test get_provider_config falls back to perplexity for invalid provider."""
        config = get_provider_config("nonexistent")
        assert config == PROVIDERS["perplexity"]

    def test_get_active_models(self):
        """Test get_active_models returns models dict."""
        models = get_active_models()
        assert isinstance(models, dict)
        assert len(models) > 0

    def test_get_active_pricing(self):
        """Test get_active_pricing returns pricing dict."""
        pricing = get_active_pricing()
        assert isinstance(pricing, dict)
        assert len(pricing) > 0

    def test_get_base_url_perplexity(self):
        """Test get_base_url for perplexity."""
        url = get_base_url("perplexity")
        assert url == "https://api.perplexity.ai"

    def test_get_base_url_custom(self):
        """Test get_base_url for custom provider."""
        url = get_base_url("custom")
        # Should return whatever is configured (default or from env)
        assert isinstance(url, str)
        assert len(url) > 0

    def test_get_coding_model_perplexity(self):
        """Test get_coding_model for perplexity."""
        model = get_coding_model("perplexity")
        assert model == "sonar-pro"

    def test_get_coding_model_custom(self):
        """Test get_coding_model for custom provider."""
        model = get_coding_model("custom")
        # Should return whatever is configured
        assert isinstance(model, str)
        assert len(model) > 0

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key-123"})
    def test_get_api_key_perplexity(self):
        """Test get_api_key retrieves perplexity key from env."""
        key = get_api_key("perplexity")
        assert key == "test-key-123"

    @patch.dict(os.environ, {"CUSTOM_API_KEY": "custom-test-key"})
    def test_get_api_key_custom(self):
        """Test get_api_key retrieves custom key from env."""
        key = get_api_key("custom")
        assert key == "custom-test-key"

    def test_get_api_key_missing(self):
        """Test get_api_key returns empty string if not set."""
        # Clear the env var if it exists
        with patch.dict(os.environ, {}, clear=True):
            key = get_api_key("perplexity")
            assert key == ""


class TestCustomProviderEnvConfig:
    """Tests for custom provider environment variable configuration."""

    @patch.dict(os.environ, {
        "CUSTOM_PROVIDER_NAME": "My Test LLM",
        "CUSTOM_MODEL_ENDPOINT": "https://test.example.com/v1",
        "CUSTOM_MODEL_ID": "test-model-v1",
        "CUSTOM_MODEL_NAME": "Test Model V1",
        "CUSTOM_MODEL_DESC": "A test model for unit testing",
    })
    def test_custom_provider_uses_env_vars(self):
        """Test that custom provider config reads from environment variables."""
        # Need to reimport to pick up new env vars
        import importlib
        import ppxai.config as config_module
        importlib.reload(config_module)

        config = config_module.PROVIDERS["custom"]
        assert config["name"] == "My Test LLM"
        assert config["base_url"] == "https://test.example.com/v1"
        assert config["models"]["1"]["id"] == "test-model-v1"
        assert config["models"]["1"]["name"] == "Test Model V1"
        assert config["models"]["1"]["description"] == "A test model for unit testing"

        # Reload again to restore defaults
        importlib.reload(config_module)

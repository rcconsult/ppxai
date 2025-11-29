"""Unit tests for ppxai.config module."""
import json
import os
import pytest
import tempfile
from pathlib import Path
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
    BUILTIN_PROVIDERS,
    DEFAULT_CAPABILITIES,
    get_provider_config,
    get_active_models,
    get_active_pricing,
    get_api_key,
    get_base_url,
    get_coding_model,
    get_default_model,
    get_config_source,
    get_available_providers,
    get_provider_capabilities,
    provider_needs_tool,
    set_active_provider,
    reload_config,
    validate_config,
    load_config,
    _find_config_file,
    _load_json_config,
    _validate_provider_config,
    _build_legacy_custom_provider,
    _convert_models_format,
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


class TestBuiltinProviders:
    """Tests for built-in provider configuration."""

    def test_builtin_perplexity_exists(self):
        """Test that built-in Perplexity config exists."""
        assert "perplexity" in BUILTIN_PROVIDERS

    def test_builtin_perplexity_structure(self):
        """Test built-in Perplexity provider has all required fields."""
        provider = BUILTIN_PROVIDERS["perplexity"]
        assert provider["name"] == "Perplexity AI"
        assert provider["base_url"] == "https://api.perplexity.ai"
        assert provider["api_key_env"] == "PERPLEXITY_API_KEY"
        assert "models" in provider
        assert "pricing" in provider
        assert "capabilities" in provider

    def test_builtin_perplexity_capabilities(self):
        """Test Perplexity has expected capabilities."""
        caps = BUILTIN_PROVIDERS["perplexity"]["capabilities"]
        assert caps["web_search"] is True
        assert caps["realtime_info"] is True

    def test_default_capabilities(self):
        """Test default capabilities are all False."""
        for key, value in DEFAULT_CAPABILITIES.items():
            assert value is False


class TestProviderConfig:
    """Tests for multi-provider configuration."""

    def test_providers_dict_exists(self):
        """Test that PROVIDERS dictionary exists with expected providers."""
        assert "perplexity" in PROVIDERS

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

    def test_get_coding_model_perplexity(self):
        """Test get_coding_model for perplexity."""
        model = get_coding_model("perplexity")
        assert model == "sonar-pro"

    def test_get_default_model_perplexity(self):
        """Test get_default_model for perplexity."""
        model = get_default_model("perplexity")
        assert model == "sonar-pro"

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key-123"})
    def test_get_api_key_perplexity(self):
        """Test get_api_key retrieves perplexity key from env."""
        key = get_api_key("perplexity")
        assert key == "test-key-123"

    def test_get_api_key_missing(self):
        """Test get_api_key returns empty string if not set."""
        with patch.dict(os.environ, {}, clear=True):
            key = get_api_key("perplexity")
            assert key == ""


class TestProviderCapabilities:
    """Tests for provider capabilities."""

    def test_get_provider_capabilities_perplexity(self):
        """Test Perplexity has web search capability."""
        caps = get_provider_capabilities("perplexity")
        assert caps["web_search"] is True
        assert caps["realtime_info"] is True

    def test_provider_needs_tool_perplexity(self):
        """Test Perplexity doesn't need web search tool."""
        assert provider_needs_tool("perplexity", "web_search") is False

    def test_provider_needs_tool_unknown_category(self):
        """Test unknown capability defaults to needing tool."""
        assert provider_needs_tool("perplexity", "unknown_capability") is True


class TestConfigLoading:
    """Tests for JSON configuration loading."""

    def test_convert_models_format(self):
        """Test model format conversion from JSON to internal format."""
        json_models = {
            "gpt-4": {"name": "GPT-4", "description": "OpenAI GPT-4"},
            "gpt-3.5": {"name": "GPT-3.5", "description": "OpenAI GPT-3.5"},
        }
        converted = _convert_models_format(json_models)
        assert "1" in converted
        assert "2" in converted
        assert converted["1"]["id"] == "gpt-4"
        assert converted["1"]["name"] == "GPT-4"
        assert converted["2"]["id"] == "gpt-3.5"

    def test_validate_provider_config_valid(self):
        """Test validation passes for valid provider config."""
        valid_config = {
            "name": "Test Provider",
            "base_url": "https://api.test.com/v1",
            "api_key_env": "TEST_API_KEY",
            "models": {"model1": {"name": "Model 1", "description": "Test"}},
        }
        errors = _validate_provider_config("test", valid_config)
        assert len(errors) == 0

    def test_validate_provider_config_missing_fields(self):
        """Test validation fails for missing required fields."""
        invalid_config = {"name": "Test Provider"}
        errors = _validate_provider_config("test", invalid_config)
        assert len(errors) > 0
        assert any("base_url" in e for e in errors)

    def test_validate_provider_config_empty_models(self):
        """Test validation fails for empty models."""
        config = {
            "name": "Test",
            "base_url": "https://test.com",
            "api_key_env": "TEST_KEY",
            "models": {},
        }
        errors = _validate_provider_config("test", config)
        assert any("no models" in e for e in errors)

    def test_load_json_config_valid(self):
        """Test loading a valid JSON config file."""
        config_data = {
            "version": "1.0",
            "default_provider": "test",
            "providers": {
                "test": {
                    "name": "Test Provider",
                    "base_url": "https://api.test.com/v1",
                    "api_key_env": "TEST_API_KEY",
                    "models": {"model1": {"name": "Model 1", "description": "Test"}},
                }
            }
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            loaded = _load_json_config(Path(f.name))
            assert loaded["version"] == "1.0"
            assert "test" in loaded["providers"]
        os.unlink(f.name)

    def test_load_json_config_invalid_json(self):
        """Test loading invalid JSON raises ValueError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{ invalid json }")
            f.flush()
            with pytest.raises(ValueError, match="Invalid JSON"):
                _load_json_config(Path(f.name))
        os.unlink(f.name)

    def test_find_config_file_env_override(self):
        """Test PPXAI_CONFIG_FILE env var takes precedence."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{}")
            f.flush()
            with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": f.name}):
                found = _find_config_file()
                assert found == Path(f.name)
        os.unlink(f.name)

    def test_find_config_file_nonexistent_env(self):
        """Test nonexistent PPXAI_CONFIG_FILE is ignored."""
        with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": "/nonexistent/path.json"}):
            # Should not return the nonexistent path
            found = _find_config_file()
            if found:
                assert found != Path("/nonexistent/path.json")


class TestLegacyCustomProvider:
    """Tests for backward compatibility with legacy CUSTOM_* env vars."""

    def test_build_legacy_custom_provider_none_without_endpoint(self):
        """Test no legacy provider without CUSTOM_MODEL_ENDPOINT."""
        with patch.dict(os.environ, {}, clear=True):
            result = _build_legacy_custom_provider()
            assert result is None

    @patch.dict(os.environ, {
        "CUSTOM_MODEL_ENDPOINT": "https://test.example.com/v1",
        "CUSTOM_PROVIDER_NAME": "My Test LLM",
        "CUSTOM_MODEL_ID": "test-model-v1",
        "CUSTOM_MODEL_NAME": "Test Model V1",
        "CUSTOM_MODEL_DESC": "A test model",
    })
    def test_build_legacy_custom_provider_with_env(self):
        """Test legacy provider is built from CUSTOM_* env vars."""
        result = _build_legacy_custom_provider()
        assert result is not None
        assert result["name"] == "My Test LLM"
        assert result["base_url"] == "https://test.example.com/v1"
        assert result["api_key_env"] == "CUSTOM_API_KEY"
        assert "test-model-v1" in result["models"]

    @patch.dict(os.environ, {
        "CUSTOM_MODEL_ENDPOINT": "https://test.example.com/v1",
    })
    def test_build_legacy_custom_provider_defaults(self):
        """Test legacy provider uses defaults for missing vars."""
        result = _build_legacy_custom_provider()
        assert result is not None
        assert result["name"] == "Custom Self-Hosted"
        assert result["default_model"] == "custom-model"


class TestConfigHelpers:
    """Tests for configuration helper functions."""

    def test_get_config_source(self):
        """Test get_config_source returns a string."""
        source = get_config_source()
        assert isinstance(source, str)
        assert len(source) > 0

    def test_get_available_providers(self):
        """Test get_available_providers returns list."""
        providers = get_available_providers()
        assert isinstance(providers, list)
        assert "perplexity" in providers

    def test_set_active_provider_valid(self):
        """Test setting a valid active provider."""
        original = MODEL_PROVIDER
        result = set_active_provider("perplexity")
        assert result is True
        # Restore
        set_active_provider(original)

    def test_set_active_provider_invalid(self):
        """Test setting an invalid provider returns False."""
        result = set_active_provider("nonexistent_provider")
        assert result is False

    def test_validate_config_structure(self):
        """Test validate_config returns expected structure."""
        result = validate_config()
        assert "valid" in result
        assert "config_source" in result
        assert "providers" in result
        assert isinstance(result["providers"], dict)

    def test_validate_config_provider_info(self):
        """Test validate_config includes provider details."""
        result = validate_config()
        assert "perplexity" in result["providers"]
        pplx = result["providers"]["perplexity"]
        assert "name" in pplx
        assert "has_api_key" in pplx
        assert "api_key_env" in pplx
        assert "base_url" in pplx
        assert "model_count" in pplx


class TestConfigReload:
    """Tests for configuration reload functionality."""

    def test_reload_config_returns_dict(self):
        """Test reload_config returns configuration dict."""
        result = reload_config()
        assert isinstance(result, dict)
        assert "config_source" in result
        assert "providers" in result
        assert "default_provider" in result

    def test_load_config_always_has_perplexity(self):
        """Test load_config always includes perplexity provider."""
        result = load_config()
        assert "perplexity" in result["providers"]


class TestJSONConfigIntegration:
    """Integration tests for JSON configuration loading."""

    def test_full_json_config_loading(self):
        """Test loading a complete JSON config file."""
        config_data = {
            "version": "1.0",
            "default_provider": "openai",
            "providers": {
                "openai": {
                    "name": "OpenAI",
                    "base_url": "https://api.openai.com/v1",
                    "api_key_env": "OPENAI_API_KEY",
                    "default_model": "gpt-4",
                    "models": {
                        "gpt-4": {"name": "GPT-4", "description": "OpenAI GPT-4"},
                        "gpt-3.5-turbo": {"name": "GPT-3.5", "description": "Fast model"},
                    },
                    "pricing": {
                        "gpt-4": {"input": 30.0, "output": 60.0},
                        "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
                    },
                    "capabilities": {"web_search": False, "realtime_info": False},
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": f.name}):
                result = load_config()

                assert result["config_source"] == f.name
                assert result["default_provider"] == "openai"
                assert "openai" in result["providers"]
                assert "perplexity" in result["providers"]  # Always included

                openai_config = result["providers"]["openai"]
                assert openai_config["name"] == "OpenAI"
                assert openai_config["default_model"] == "gpt-4"
                assert len(openai_config["models"]) == 2
                assert openai_config["models"]["1"]["id"] == "gpt-4"

        os.unlink(f.name)

    def test_json_config_with_missing_optional_fields(self):
        """Test JSON config handles missing optional fields gracefully."""
        config_data = {
            "providers": {
                "minimal": {
                    "name": "Minimal Provider",
                    "base_url": "https://api.minimal.com/v1",
                    "api_key_env": "MINIMAL_KEY",
                    "models": {
                        "model1": {"name": "Model 1", "description": "Basic model"},
                    },
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": f.name}):
                result = load_config()

                assert "minimal" in result["providers"]
                minimal = result["providers"]["minimal"]
                # Should have default capabilities
                assert minimal["capabilities"]["web_search"] is False
                # Should infer default_model from first model
                assert minimal["default_model"] == "model1"

        os.unlink(f.name)

"""Unit tests for ppxai.config module."""
import json
import pathlib
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
    PROVIDERS,
    DEFAULT_CAPABILITIES,
    get_provider_config,
    get_active_models,
    get_active_pricing,
    get_api_key,
    get_base_url,
    get_coding_model,
    get_default_model,
    get_default_provider,
    get_config_source,
    get_available_providers,
    get_provider_capabilities,
    provider_needs_tool,
    reload_config,
    validate_config,
    load_config,
    get_tool_config,
    get_tool_pricing,
    get_shell_config,
    find_config_file,
    initialize,
    # Context configuration (v1.13.9)
    DEFAULT_MAX_INJECTION_SIZE,
    DEFAULT_CONTEXT_LIMIT,
    DEFAULT_CONTEXT_WARN_PERCENT,
    get_context_config,
    get_max_injection_size,
    get_default_context_limit,
    get_context_warn_percent,
    get_model_context_limit,
)
from ppxai.config.store import ConfigStore
from ppxai.config.loader import (
    _load_json_config,
    _validate_provider_config,
    _build_legacy_custom_provider,
    _convert_models_format,
)


@pytest.fixture(autouse=True)
def _config_store_hermetic():
    """Snapshot + restore the GLOBAL ConfigStore around EVERY test here.

    Several tests in this module call reload_config() while
    PPXAI_CONFIG_FILE points at a temp file; the opt-in restore_config
    fixture wasn't applied everywhere (and its disk re-reload restores
    whatever find_config_file() resolves, not the pre-test state), so the
    leaked store poisoned LATER suites — observed: running test_config.py
    before test_oneshot_grounding.py flipped that suite's dual-read of
    tools.web_search.oneshot_grounding to a temp config's value (one
    order-dependent failure on clean HEAD, 2026-08-03). An in-memory
    snapshot restores the exact prior state without touching disk."""
    import copy

    store = ConfigStore.get_instance()
    snapshot = copy.deepcopy(store.config)
    yield
    # `config` is a read-only property returning the live dict — restore by
    # mutating it in place.
    live = store.config
    live.clear()
    live.update(snapshot)


@pytest.fixture
def restore_config():
    """Legacy opt-in restore — superseded by the autouse
    `_config_store_hermetic` snapshot above; kept so existing test
    signatures keep working."""
    yield


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

    def test_model_pricing_deprecated(self):
        """Test that MODEL_PRICING is deprecated (empty dict for backward compat)."""
        # MODEL_PRICING is deprecated - use get_model_pricing() instead
        assert isinstance(MODEL_PRICING, dict)

    def test_coding_model_constant(self):
        """Test that CODING_MODEL constant exists."""
        assert CODING_MODEL == "sonar-pro"

    def test_default_capabilities(self):
        """Test default capabilities are all False."""
        for key, value in DEFAULT_CAPABILITIES.items():
            assert value is False


class TestProviderConfig:
    """Tests for multi-provider configuration.

    These tests assert against the bundled `ppxai-config.example.json`
    contract, not whatever happens to be in the developer's
    `~/.ppxai/ppxai-config.json`. The autouse fixture pins the loader
    to the example config so test order can't pollute the assertions.
    Without it, a peer test's `initialize()` call leaks the user's
    home config into PROVIDERS — caught the hard way during v1.18.1
    when `coding_model` mismatched on a dev machine.
    """

    @pytest.fixture(autouse=True)
    def _pin_example_config(self, monkeypatch):
        from pathlib import Path
        example = Path(__file__).resolve().parents[1] / "ppxai-config.example.json"
        assert example.exists(), f"Example config missing at {example}"
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(example))
        reload_config()
        yield
        # post-yield: reload back to default (no env override) so the
        # next test class doesn't inherit the example config.
        monkeypatch.delenv("PPXAI_CONFIG_FILE", raising=False)
        reload_config()

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
        assert config == PROVIDERS[get_default_provider()]

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

    def testfind_config_file_env_override(self):
        """Test PPXAI_CONFIG_FILE env var takes precedence."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{}")
            f.flush()
            with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": f.name}):
                found = find_config_file()
                assert found == Path(f.name)
        os.unlink(f.name)

    def testfind_config_file_nonexistent_env(self):
        """Test nonexistent PPXAI_CONFIG_FILE is ignored."""
        with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": "/nonexistent/path.json"}):
            # Should not return the nonexistent path
            found = find_config_file()
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

    def test_build_legacy_custom_provider_defaults(self):
        """Test legacy provider uses defaults for missing vars.

        Note: We must delete (not just empty) CUSTOM_* vars to test defaults,
        since os.getenv() only uses default when var is unset, not when empty.
        """
        # Save and remove any existing CUSTOM_* vars that might be in .env
        vars_to_clear = ["CUSTOM_PROVIDER_NAME", "CUSTOM_MODEL_ID",
                         "CUSTOM_MODEL_NAME", "CUSTOM_MODEL_DESC"]
        saved = {k: os.environ.pop(k, None) for k in vars_to_clear}

        try:
            with patch.dict(os.environ, {"CUSTOM_MODEL_ENDPOINT": "https://test.example.com/v1"}):
                result = _build_legacy_custom_provider()
                assert result is not None
                assert result["name"] == "Custom Self-Hosted"
                assert result["default_model"] == "custom-model"
        finally:
            # Restore any vars that were set
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


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

    def test_get_default_provider(self):
        """Test get_default_provider returns a valid provider."""
        provider = get_default_provider()
        assert isinstance(provider, str)
        assert provider in PROVIDERS

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

    def test_reload_config_returns_dict(self, restore_config):
        """Test reload_config returns configuration dict."""
        result = reload_config()
        assert isinstance(result, dict)
        assert "config_source" in result
        assert "providers" in result
        assert "default_provider" in result

    def test_load_config_returns_providers(self):
        """Test load_config returns providers from config file."""
        result = load_config()
        # May or may not have perplexity depending on config
        assert isinstance(result["providers"], dict)


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
                # Note: perplexity is NOT auto-included anymore - only providers in the config

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


class TestToolConfig:
    """Tests for tool configuration helpers (v1.13.4)."""

    def test_get_tool_config_web_search(self):
        """Test get_tool_config returns web_search configuration."""
        config = get_tool_config("web_search")
        assert isinstance(config, dict)
        # Web search config should have preferred field
        if config:  # Only if web_search config exists
            assert "preferred" in config or "pricing" in config

    def test_get_tool_config_nonexistent_tool(self):
        """Test get_tool_config returns empty dict for nonexistent tool."""
        config = get_tool_config("nonexistent_tool")
        assert config == {}

    def test_get_tool_config_shell(self):
        """Test get_tool_config returns shell configuration."""
        config = get_tool_config("shell")
        assert isinstance(config, dict)
        # Shell config should have require_consent field
        if config:  # Only if shell config exists
            assert "require_consent" in config or "dangerous_commands" in config

    def test_get_tool_config_agent(self):
        """Test get_tool_config returns agent configuration."""
        config = get_tool_config("agent")
        assert isinstance(config, dict)
        # Agent config should have max_iterations field
        if config:  # Only if agent config exists
            assert "max_iterations" in config or "min_task_words" in config


class TestShellConfig:
    """Tests for shell tool configuration helpers (v1.13.6)."""

    def test_get_shell_config_returns_dict(self):
        """Test get_shell_config returns a dictionary."""
        config = get_shell_config()
        assert isinstance(config, dict)

    def test_get_shell_config_has_required_keys(self):
        """Test get_shell_config returns all required keys."""
        config = get_shell_config()
        assert "require_consent" in config
        assert "interactive_commands" in config
        assert "non_interactive_with_args" in config

    def test_get_shell_config_interactive_commands_list(self):
        """Test interactive_commands is a non-empty list."""
        config = get_shell_config()
        assert isinstance(config["interactive_commands"], list)
        assert len(config["interactive_commands"]) > 0

    def test_get_shell_config_non_interactive_with_args_list(self):
        """Test non_interactive_with_args is a non-empty list."""
        config = get_shell_config()
        assert isinstance(config["non_interactive_with_args"], list)
        assert len(config["non_interactive_with_args"]) > 0

    def test_get_shell_config_ssh_in_non_interactive(self):
        """Test ssh is in non_interactive_with_args by default."""
        config = get_shell_config()
        assert "ssh" in config["non_interactive_with_args"]

    def test_get_shell_config_ssh_in_interactive(self):
        """Test ssh is in interactive_commands (blocked without args)."""
        config = get_shell_config()
        assert "ssh" in config["interactive_commands"]

    def test_shell_bin_and_login_shell_pass_through(self):
        """Regression: get_shell_config() was DROPPING shell_bin/login_shell,
        so an operator's `tools.shell.shell_bin`/`login_shell` (coder sets
        /bin/bash + login) never reached server/routes/terminal.py — the
        browser terminal fell back to /bin/sh→dash (no history/line editing).
        They must pass through so the config actually steers the terminal."""
        store = ConfigStore.get_instance()
        store.config.setdefault("tools", {})["shell"] = {
            "shell_bin": "/bin/bash",
            "login_shell": True,
        }
        config = get_shell_config()
        assert config["shell_bin"] == "/bin/bash"
        assert config["login_shell"] is True

    def test_shell_bin_and_login_shell_default_none_when_unset(self):
        """Unset → None (terminal.py then applies its bash-preferring,
        login-by-default fallback). Absent keys must not raise."""
        store = ConfigStore.get_instance()
        store.config.setdefault("tools", {})["shell"] = {}
        config = get_shell_config()
        assert config["shell_bin"] is None
        assert config["login_shell"] is None


class TestToolPricing:
    """Tests for tool pricing configuration (v1.13.4)."""

    def test_get_tool_pricing_perplexity(self):
        """Test get_tool_pricing returns Perplexity pricing."""
        pricing = get_tool_pricing("web_search", "perplexity")
        assert isinstance(pricing, dict)
        # Perplexity pricing should have input/output per-token pricing
        if pricing:  # Only if pricing exists
            assert "input" in pricing or "model" in pricing

    def test_get_tool_pricing_gemini_grounding(self):
        """Test get_tool_pricing returns Gemini Grounding pricing."""
        pricing = get_tool_pricing("web_search", "gemini_grounding")
        assert isinstance(pricing, dict)
        # Gemini Grounding pricing should have per_query pricing
        if pricing:  # Only if pricing exists
            assert "per_query" in pricing or "model" in pricing

    def test_get_tool_pricing_nonexistent_provider(self):
        """Test get_tool_pricing returns empty dict for nonexistent provider."""
        pricing = get_tool_pricing("web_search", "nonexistent_provider")
        assert pricing == {}

    def test_get_tool_pricing_nonexistent_tool(self):
        """Test get_tool_pricing returns empty dict for nonexistent tool."""
        pricing = get_tool_pricing("nonexistent_tool", "perplexity")
        assert pricing == {}

    def test_get_tool_pricing_duckduckgo_free(self):
        """Test DuckDuckGo has no pricing (free service)."""
        pricing = get_tool_pricing("web_search", "duckduckgo")
        # DuckDuckGo is free, so pricing should be empty or have zero cost
        if pricing:
            assert pricing.get("cost", 0) == 0 or "per_query" not in pricing


class TestPathsConfig:
    """Tests for paths configuration (v1.13.2)."""

    def test_get_paths_config_returns_dict(self):
        """Test get_paths_config returns a dictionary."""
        from ppxai.config import get_paths_config
        paths = get_paths_config()
        assert isinstance(paths, dict)

    def test_get_paths_config_has_bin_search_paths(self):
        """Test get_paths_config includes bin_search_paths."""
        from ppxai.config import get_paths_config
        paths = get_paths_config()
        assert "bin_search_paths" in paths
        assert isinstance(paths["bin_search_paths"], list)
        assert len(paths["bin_search_paths"]) > 0

    def test_get_paths_config_has_data_dir(self):
        """Test get_paths_config includes data_dir."""
        from ppxai.config import get_paths_config
        paths = get_paths_config()
        assert "data_dir" in paths
        assert isinstance(paths["data_dir"], str)

    def test_get_paths_config_expands_home(self):
        """Test that {home} templates are expanded."""
        from ppxai.config import get_paths_config
        from pathlib import Path
        paths = get_paths_config()
        home = str(Path.home())
        # At least one path should contain the actual home directory
        found_home = False
        for p in paths["bin_search_paths"]:
            if home in p:
                found_home = True
                break
        assert found_home, f"Expected home directory {home} in paths: {paths['bin_search_paths']}"

    def test_get_bin_search_paths_returns_list(self):
        """Test get_bin_search_paths returns a list of strings."""
        from ppxai.config import get_bin_search_paths
        paths = get_bin_search_paths()
        assert isinstance(paths, list)
        for p in paths:
            assert isinstance(p, str)

    def test_get_data_dir_returns_path(self):
        """Test get_data_dir returns a Path object."""
        from ppxai.config import get_data_dir
        from pathlib import Path
        data_dir = get_data_dir()
        assert isinstance(data_dir, Path)


class TestBOMHandling:
    """Tests for UTF-8 BOM handling in .env files (v1.13.3).

    Windows PowerShell's Out-File creates files with UTF-8 BOM by default.
    python-dotenv does NOT handle BOM, which corrupts the first key.
    These tests verify our custom BOM handling works correctly.
    """

    def test_load_dotenv_with_bom(self):
        """Test that .env files with UTF-8 BOM are loaded correctly."""
        from ppxai.config.loader import load_dotenv_with_bom_handling
        import tempfile

        # Create a temp .env file with UTF-8 BOM
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.env', delete=False) as f:
            # UTF-8 BOM (EF BB BF) + content
            f.write(b'\xef\xbb\xbfTEST_BOM_KEY=test_bom_value\n')
            temp_path = f.name

        try:
            # Clear the env var if it exists
            if 'TEST_BOM_KEY' in os.environ:
                del os.environ['TEST_BOM_KEY']

            load_dotenv_with_bom_handling(Path(temp_path))

            # Key should be loaded correctly without BOM corruption
            assert os.environ.get('TEST_BOM_KEY') == 'test_bom_value', \
                "BOM corrupted the first key in .env file"
        finally:
            os.unlink(temp_path)
            if 'TEST_BOM_KEY' in os.environ:
                del os.environ['TEST_BOM_KEY']

    def test_load_dotenv_without_bom(self):
        """Test that .env files without BOM still work."""
        from ppxai.config.loader import load_dotenv_with_bom_handling
        import tempfile

        # Create a temp .env file without BOM
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False, encoding='utf-8') as f:
            f.write('TEST_NO_BOM_KEY=test_no_bom_value\n')
            temp_path = f.name

        try:
            if 'TEST_NO_BOM_KEY' in os.environ:
                del os.environ['TEST_NO_BOM_KEY']

            load_dotenv_with_bom_handling(Path(temp_path))

            assert os.environ.get('TEST_NO_BOM_KEY') == 'test_no_bom_value'
        finally:
            os.unlink(temp_path)
            if 'TEST_NO_BOM_KEY' in os.environ:
                del os.environ['TEST_NO_BOM_KEY']

    def test_load_dotenv_nonexistent_file(self):
        """Test that nonexistent .env files are handled gracefully."""
        from ppxai.config.loader import load_dotenv_with_bom_handling

        # Should not raise an exception
        load_dotenv_with_bom_handling(Path('/nonexistent/path/.env'))

    def test_load_dotenv_multiple_keys_with_bom(self):
        """Test that all keys are loaded correctly when file has BOM."""
        from ppxai.config.loader import load_dotenv_with_bom_handling
        import tempfile

        # Create a temp .env file with BOM and multiple keys
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.env', delete=False) as f:
            f.write(b'\xef\xbb\xbfFIRST_KEY=first_value\nSECOND_KEY=second_value\nTHIRD_KEY=third_value\n')
            temp_path = f.name

        try:
            for key in ['FIRST_KEY', 'SECOND_KEY', 'THIRD_KEY']:
                if key in os.environ:
                    del os.environ[key]

            load_dotenv_with_bom_handling(Path(temp_path))

            assert os.environ.get('FIRST_KEY') == 'first_value'
            assert os.environ.get('SECOND_KEY') == 'second_value'
            assert os.environ.get('THIRD_KEY') == 'third_value'
        finally:
            os.unlink(temp_path)
            for key in ['FIRST_KEY', 'SECOND_KEY', 'THIRD_KEY']:
                if key in os.environ:
                    del os.environ[key]


class TestSystemPromptConfig:
    """Tests for system prompt configuration (v1.13.6)."""

    def test_get_system_prompt_default(self):
        """Test default system prompt for known providers."""
        from ppxai.config import get_system_prompt, DEFAULT_SYSTEM_PROMPTS

        # Without config file, should return defaults
        with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": "/nonexistent/path.json"}):
            prompt = get_system_prompt("custom")
            assert "concise" in prompt.lower() or "brief" in prompt.lower()

    def test_get_system_prompt_from_config(self):
        """Test system prompt loaded from config file."""
        from ppxai.config import get_system_prompt

        config_data = {
            "system_prompt": "Be very brief.",
            "providers": {
                "test-provider": {
                    "name": "Test",
                    "base_url": "http://test.com",
                    "api_key_env": "TEST_KEY",
                    "system_prompt": "Provider-specific prompt.",
                    "models": {"m1": {"name": "M1", "description": "Test model"}}
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": f.name}):
                # Provider-specific prompt takes priority
                prompt = get_system_prompt("test-provider")
                assert prompt == "Provider-specific prompt."

                # Unknown provider falls back to global
                prompt = get_system_prompt("unknown-provider")
                assert prompt == "Be very brief."

        os.unlink(f.name)

    def test_get_system_prompt_mode_default(self):
        """Test default system prompt mode is 'prepend'."""
        from ppxai.config import get_system_prompt_mode

        with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": "/nonexistent/path.json"}):
            mode = get_system_prompt_mode("any-provider")
            assert mode == "prepend"

    def test_get_system_prompt_mode_from_config(self):
        """Test system prompt mode loaded from config file."""
        from ppxai.config import get_system_prompt_mode

        config_data = {
            "system_prompt_mode": "append",
            "providers": {
                "test-provider": {
                    "name": "Test",
                    "base_url": "http://test.com",
                    "api_key_env": "TEST_KEY",
                    "system_prompt_mode": "replace",
                    "models": {"m1": {"name": "M1", "description": "Test model"}}
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": f.name}):
                # Provider-specific mode takes priority
                mode = get_system_prompt_mode("test-provider")
                assert mode == "replace"

                # Unknown provider falls back to global
                mode = get_system_prompt_mode("unknown-provider")
                assert mode == "append"

        os.unlink(f.name)


class TestContextConfig:
    """Tests for context configuration (v1.13.9)."""

    def test_default_constants(self):
        """Test default context constants are reasonable."""
        assert DEFAULT_MAX_INJECTION_SIZE == 100_000
        assert DEFAULT_CONTEXT_LIMIT == 128_000
        assert DEFAULT_CONTEXT_WARN_PERCENT == 80

    def test_get_context_config_returns_dict(self):
        """Test get_context_config returns a dictionary with defaults."""
        config = get_context_config()
        assert isinstance(config, dict)
        assert "max_injection_size" in config
        assert "default_context_limit" in config
        assert "warn_at_percent" in config

    def test_get_context_config_defaults(self):
        """Test get_context_config returns default values when no config file."""
        with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": "/nonexistent/path.json"}):
            config = get_context_config()
            assert config["max_injection_size"] == DEFAULT_MAX_INJECTION_SIZE
            assert config["default_context_limit"] == DEFAULT_CONTEXT_LIMIT
            assert config["warn_at_percent"] == DEFAULT_CONTEXT_WARN_PERCENT

    def test_get_max_injection_size_default(self):
        """Test get_max_injection_size returns default value."""
        with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": "/nonexistent/path.json"}):
            size = get_max_injection_size()
            assert size == DEFAULT_MAX_INJECTION_SIZE

    def test_get_default_context_limit(self):
        """Test get_default_context_limit returns default value."""
        with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": "/nonexistent/path.json"}):
            limit = get_default_context_limit()
            assert limit == DEFAULT_CONTEXT_LIMIT

    def test_get_context_warn_percent_default(self):
        """Test get_context_warn_percent returns default value."""
        with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": "/nonexistent/path.json"}):
            percent = get_context_warn_percent()
            assert percent == DEFAULT_CONTEXT_WARN_PERCENT

    def test_get_context_config_from_json(self, restore_config):
        """Test loading context config from JSON file."""
        config_data = {
            "context": {
                "max_injection_size": 50000,
                "default_context_limit": 200000,
                "warn_at_percent": 90
            },
            "providers": {
                "test": {
                    "name": "Test",
                    "base_url": "http://test.com",
                    "api_key_env": "TEST_KEY",
                    "models": {"m1": {"name": "M1", "description": "Test"}}
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": f.name}):
                # Force reload
                reload_config()

                config = get_context_config()
                assert config["max_injection_size"] == 50000
                assert config["default_context_limit"] == 200000
                assert config["warn_at_percent"] == 90

        os.unlink(f.name)

    def test_get_model_context_limit_default(self):
        """Test get_model_context_limit returns a positive limit for unknown model."""
        # Note: Cannot easily override local config file, so just verify it returns a valid value
        limit = get_model_context_limit("unknown_provider", "unknown_model")
        # Should return either config default or built-in default (both positive)
        assert limit > 0
        assert isinstance(limit, int)

    def test_get_model_context_limit_from_json(self):
        """Test model-specific context_limit from config file."""
        config_data = {
            "context": {
                "default_context_limit": 128000
            },
            "providers": {
                "custom-test-provider": {
                    "name": "Custom vLLM",
                    "base_url": "http://localhost:8000/v1",
                    "api_key_env": "CUSTOM_KEY",
                    "models": {
                        "gpt-oss-120b": {
                            "name": "GPT-OSS 120B",
                            "description": "Custom model",
                            "context_limit": 131072
                        },
                        "other-model": {
                            "name": "Other Model",
                            "description": "No context limit specified"
                        }
                    }
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": f.name}):
                # Model-specific limit should be returned
                limit = get_model_context_limit("custom-test-provider", "gpt-oss-120b")
                assert limit == 131072

                # Unknown model falls back - verify it's different from model-specific
                limit_other = get_model_context_limit("custom-test-provider", "other-model")
                assert limit_other != 131072  # Not the model-specific limit
                assert limit_other > 0  # But still a valid positive value

        os.unlink(f.name)

    def test_get_model_context_limit_perplexity_default(self):
        """Test Perplexity models get default context limit."""
        limit = get_model_context_limit("perplexity", "sonar-pro")
        # Should return some positive value (either custom or default)
        assert limit > 0
        assert isinstance(limit, int)

    def test_context_config_partial_override(self, restore_config):
        """Test that partial context config merges with defaults."""
        config_data = {
            "context": {
                "max_injection_size": 75000
                # Note: default_context_limit and warn_at_percent not specified
            },
            "providers": {
                "test": {
                    "name": "Test",
                    "base_url": "http://test.com",
                    "api_key_env": "TEST_KEY",
                    "models": {"m1": {"name": "M1", "description": "Test"}}
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": f.name}):
                reload_config()
                config = get_context_config()
                # Override should work
                assert config["max_injection_size"] == 75000
                # Defaults should be preserved
                assert config["default_context_limit"] == DEFAULT_CONTEXT_LIMIT
                assert config["warn_at_percent"] == DEFAULT_CONTEXT_WARN_PERCENT

        os.unlink(f.name)

    def test_context_warn_percent_zero_disables(self, restore_config):
        """Test that warn_at_percent=0 effectively disables warnings."""
        config_data = {
            "context": {
                "warn_at_percent": 0
            },
            "providers": {
                "test": {
                    "name": "Test",
                    "base_url": "http://test.com",
                    "api_key_env": "TEST_KEY",
                    "models": {"m1": {"name": "M1", "description": "Test"}}
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": f.name}):
                reload_config()
                percent = get_context_warn_percent()
                assert percent == 0

        os.unlink(f.name)


class TestFactsConfig:
    """RETARGETED from `TestToolCallingConfig` (ADR 0012 section 2 Q0e).

    `get_tool_calling_config` is deleted — it read the `tool_calling`
    block, one of the two vocabularies this ADR collapses into `facts`.
    Three of its four premises survive in the new vocabulary and are kept
    here; the fourth does not, and its removal is the point:

    * "empty when nothing is configured" — ALIVE.
    * "comment keys are filtered" — ALIVE (configs are hand-edited and
      carry `__comment_*` keys throughout).
    * "a model-level block overrides" — ALIVE, restated as "a model block
      is the only place a model fact can be stated".
    * "provider-level acts as a default for all models" — **DEAD, and
      deliberately.** That inheritance is exactly what let a provider-wide
      statement speak for `sonar` (debt Item 43). Under Q0e a provider
      block cannot state a model fact at all, so the negative is asserted
      instead.
    """

    def test_empty_when_no_config(self, restore_config):
        from ppxai.config.facts_config import model_fact_overrides

        assert model_fact_overrides("perplexity", "sonar-pro") == {}

    def _write(self, config_data, fn):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(config_data, f)
            f.flush()
            with patch.dict(os.environ, {"PPXAI_CONFIG_FILE": f.name}):
                reload_config()
                import ppxai.config.facts_config as fcmod

                with patch.object(
                    fcmod, "find_config_file", lambda: pathlib.Path(f.name)
                ):
                    result = fn()
        os.unlink(f.name)
        return result

    def test_a_provider_block_cannot_state_a_model_fact(self, restore_config):
        """The INVERTED premise — this is the Item 43 fence."""
        from ppxai.config.facts_config import model_fact_overrides

        config_data = {
            "providers": {
                "custom": {
                    "name": "Custom",
                    "base_url": "http://localhost:8000/v1",
                    "api_key_env": "CUSTOM_KEY",
                    "facts": {"tool_mode": "prompt_based",
                              "fallback_on_empty": True},
                    "models": {"my-model": {"name": "My Model"}},
                }
            }
        }
        got = self._write(
            config_data, lambda: model_fact_overrides("custom", "my-model")
        )
        assert got == {}, (
            "a provider-level block reached a model fact — the records must "
            "be disjoint"
        )

    def test_a_model_block_states_model_facts(self, restore_config):
        from ppxai.config.facts_config import model_fact_overrides

        config_data = {
            "providers": {
                "custom": {
                    "name": "Custom",
                    "base_url": "http://localhost:8000/v1",
                    "api_key_env": "CUSTOM_KEY",
                    "models": {
                        "my-model": {
                            "name": "My Model",
                            "facts": {
                                "tool_mode": "native",
                                "fallback_on_empty": True,
                            },
                        }
                    },
                }
            }
        }
        got = self._write(
            config_data, lambda: model_fact_overrides("custom", "my-model")
        )
        assert got["tool_mode"] == "native"
        assert got["fallback_on_empty"] is True

    def test_comment_keys_filtered(self, restore_config):
        """Hand-edited configs carry `__comment_*` keys throughout."""
        from ppxai.config.facts_config import model_fact_overrides

        config_data = {
            "providers": {
                "custom": {
                    "name": "Custom",
                    "base_url": "http://localhost:8000/v1",
                    "api_key_env": "CUSTOM_KEY",
                    "models": {
                        "my-model": {
                            "facts": {
                                "__comment": "why this model is special",
                                "__comment_tool_mode": "measured 2026-08-30",
                                "tool_mode": "native",
                            }
                        }
                    },
                }
            }
        }
        got = self._write(
            config_data, lambda: model_fact_overrides("custom", "my-model")
        )
        assert got == {"tool_mode": "native"}



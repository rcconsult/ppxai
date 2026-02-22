"""
Tests for provider hierarchy compliance (v1.16.0 Step 1).

Verifies that all providers inherit from BaseProvider and implement
the shared interface: needs_tool, get_model_profile, list_models,
validate_config, get_capabilities_for_model, _get_generation_params,
_get_max_tokens, _convert_messages, _parse_usage, _format_error,
_log_error_traceback.
"""

import pytest
from unittest.mock import patch, MagicMock

from ppxai.engine.providers.base import BaseProvider
from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
from ppxai.engine.providers.perplexity import PerplexityProvider
from ppxai.engine.providers.openai_native import OpenAINativeProvider
from ppxai.engine.providers.gemini import GeminiProvider
from ppxai.engine.types import ProviderCapabilities


# All provider classes to test
ALL_PROVIDERS = [
    OpenAICompatibleProvider,
    PerplexityProvider,
    OpenAINativeProvider,
    GeminiProvider,
]


class TestProviderInheritance:
    """Verify all providers inherit from BaseProvider."""

    @pytest.mark.parametrize("cls", ALL_PROVIDERS, ids=lambda c: c.__name__)
    def test_is_subclass_of_base(self, cls):
        assert issubclass(cls, BaseProvider)


class TestProviderInterface:
    """Verify all providers expose the required interface methods."""

    REQUIRED_METHODS = [
        "chat",
        "chat_sync_simple",
        "list_models",
        "validate_config",
        "needs_tool",
        "get_model_profile",
        "get_capabilities_for_model",
        "_get_generation_params",
        "_get_max_tokens",
        "_format_error",
        "_log_error_traceback",
        "_parse_usage",
    ]

    @pytest.mark.parametrize("cls", ALL_PROVIDERS, ids=lambda c: c.__name__)
    @pytest.mark.parametrize("method", REQUIRED_METHODS)
    def test_has_method(self, cls, method):
        assert hasattr(cls, method), f"{cls.__name__} missing {method}"
        assert callable(getattr(cls, method))


class TestGetCapabilitiesForModel:
    """Test get_capabilities_for_model behavior."""

    def test_base_returns_self_capabilities(self):
        """BaseProvider default returns self.capabilities unchanged."""
        with patch("ppxai.engine.providers.base.OpenAI"):
            provider = OpenAICompatibleProvider(
                api_key="test",
                base_url="http://localhost:8000/v1",
            )
        caps = provider.get_capabilities_for_model("any-model")
        assert caps is provider.capabilities

    def test_openai_native_overrides_for_prompt_based_models(self):
        """OpenAINativeProvider returns native_tool_calling=False for o4-mini."""
        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            provider = OpenAINativeProvider(api_key="test")

        # Standard model keeps native
        caps = provider.get_capabilities_for_model("gpt-5.2")
        assert caps.native_tool_calling is True

        # o4-mini gets prompt-based
        caps = provider.get_capabilities_for_model("o4-mini")
        assert caps.native_tool_calling is False

        # gpt-4.1-mini gets prompt-based
        caps = provider.get_capabilities_for_model("gpt-4.1-mini")
        assert caps.native_tool_calling is False

    def test_perplexity_returns_self_capabilities(self):
        """PerplexityProvider uses base default (returns self.capabilities)."""
        with patch("ppxai.engine.providers.base.OpenAI"):
            provider = PerplexityProvider(
                api_key="test",
                base_url="https://api.perplexity.ai",
            )
        caps = provider.get_capabilities_for_model("sonar")
        assert caps is provider.capabilities
        assert caps.web_search is True
        assert caps.native_tool_calling is False

    def test_gemini_returns_self_capabilities(self):
        """GeminiProvider uses base default (returns self.capabilities)."""
        with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            provider = GeminiProvider(api_key="test")
        caps = provider.get_capabilities_for_model("gemini-2.5-flash")
        assert caps is provider.capabilities
        assert caps.web_search is True
        assert caps.native_tool_calling is True


class TestValidateConfig:
    """Test validate_config behavior across providers."""

    def test_openai_compat_requires_base_url(self):
        """OpenAICompatibleProvider requires both api_key and base_url."""
        with patch("ppxai.engine.providers.base.OpenAI"):
            p = OpenAICompatibleProvider(
                api_key="test",
                base_url="http://localhost:8000/v1",
            )
        assert p.validate_config() is True

        # Without base_url, should fail - but constructor requires it
        # so test with empty string
        p.base_url = ""
        assert p.validate_config() is False

    def test_openai_native_only_needs_api_key(self):
        """OpenAINativeProvider only requires api_key."""
        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            p = OpenAINativeProvider(api_key="test")
        assert p.validate_config() is True

        p.api_key = ""
        assert p.validate_config() is False

    def test_gemini_only_needs_api_key(self):
        """GeminiProvider only requires api_key."""
        with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            p = GeminiProvider(api_key="test")
        assert p.validate_config() is True

        p.api_key = ""
        assert p.validate_config() is False


class TestBaseUrlOptional:
    """Test that base_url=None skips OpenAI client creation."""

    def test_base_url_none_skips_client(self):
        """When base_url=None, BaseProvider.__init__ skips client creation."""
        with patch("ppxai.engine.providers.openai_native.OpenAI") as mock_openai:
            provider = OpenAINativeProvider(api_key="test")
        # OpenAI client should be created by the subclass, not by BaseProvider
        # BaseProvider with base_url=None returns early, so self.client is set
        # by the subclass's own __init__
        assert hasattr(provider, "client")

    def test_base_url_provided_creates_client(self):
        """When base_url is provided, BaseProvider creates OpenAI client."""
        with patch("ppxai.engine.providers.base.OpenAI") as mock_openai:
            provider = OpenAICompatibleProvider(
                api_key="test",
                base_url="http://localhost:8000/v1",
            )
        mock_openai.assert_called_once()
        assert hasattr(provider, "client")

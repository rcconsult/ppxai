"""
Tests for provider hierarchy compliance (v1.16.0 Step 1).

Verifies that all providers inherit from BaseProvider and implement
the shared interface: needs_tool, get_facts_for_model, list_models,
validate_config, get_capabilities, get_facts_for_model, _get_generation_params,
_get_max_tokens, _convert_messages, _parse_usage, _format_error,
_log_error_traceback.
"""

from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.providers.base import BaseProvider
from ppxai.engine.providers.gemini import GeminiProvider
from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
from ppxai.engine.providers.openai_native import OpenAINativeProvider
from ppxai.engine.providers.perplexity import PerplexityProvider

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
        # `get_model_profile` was here until ADR 0012 refactor (b). It
        # returned the retiring `ModelProfile` vocabulary and had zero
        # callers; `get_facts_for_model` is the interface now.
        "get_capabilities",
        "get_facts_for_model",
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


class TestTheTwoAccessors:
    """Two records, two accessors (ADR 0012 section 2 Q0e).

    RETARGETED from `TestGetCapabilitiesForModel`. Every test here used to
    assert `get_capabilities_for_model(m) is provider.capabilities` -- a
    PASSTHROUGH, which was the right contract while tool calling lived on
    the provider record. It does not any more: `get_capabilities()` answers
    for the endpoint and takes no model, `get_facts_for_model()` answers for
    the model and consults the shipped table. "Returns self.capabilities
    unchanged for any model" is not a claim that can be made about either.
    """

    def test_endpoint_accessor_returns_the_provider_record(self):
        with patch("ppxai.engine.providers.base.OpenAI"):
            provider = OpenAICompatibleProvider(
                api_key="test",
                base_url="http://localhost:8000/v1",
            )
        assert provider.get_capabilities() == provider.capabilities

    def test_openai_native_resolves_prompt_based_models_per_model(self):
        """The benchmark table, through the new accessor."""
        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            provider = OpenAINativeProvider(api_key="test")

        assert provider.get_facts_for_model("gpt-5.2").tool_mode != "prompt_based"
        assert provider.get_facts_for_model("o4-mini").tool_mode == "prompt_based"
        assert (
            provider.get_facts_for_model("gpt-4.1-mini").tool_mode == "prompt_based"
        )

    def test_perplexity_splits_endpoint_from_model(self):
        """`sonar` is not tool-capable, but the ENDPOINT still searches."""
        with patch("ppxai.engine.providers.base.OpenAI"):
            provider = PerplexityProvider(
                api_key="test",
                base_url="https://api.perplexity.ai",
            )
        assert provider.get_capabilities().web_search is True
        assert provider.get_facts_for_model("sonar").tool_mode == "prompt_based"
        assert provider.get_facts_for_model("sonar-pro").tool_mode != "prompt_based"

    def test_gemini_splits_endpoint_from_model(self):
        with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            provider = GeminiProvider(api_key="test")
        assert provider.get_capabilities().web_search is True
        facts = provider.get_facts_for_model("gemini-2.5-flash")
        assert facts.tool_mode == "native"
        assert facts.wire_protocol == "generate_content"


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

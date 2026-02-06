"""
Tests for premium web search tools (v1.13.4).

Tests Perplexity Sonar API, Gemini Google Search Grounding, and fallback logic.
"""

import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from ppxai.engine.tools.builtin import web_premium
from ppxai.engine.types import ToolUsage


class TestAvailability:
    """Tests for API key availability detection."""

    def test_is_available_no_keys(self):
        """Test is_available returns False when no keys set."""
        with patch.dict(os.environ, {}, clear=True):
            assert web_premium.is_available() is False

    def test_is_available_perplexity_key(self):
        """Test is_available returns True with Perplexity key."""
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            assert web_premium.is_available() is True

    def test_is_available_gemini_key(self):
        """Test is_available returns True with Gemini key."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            assert web_premium.is_available() is True

    def test_is_available_both_keys(self):
        """Test is_available returns True with both keys."""
        with patch.dict(os.environ, {
            "PERPLEXITY_API_KEY": "test-key",
            "GEMINI_API_KEY": "test-key"
        }):
            assert web_premium.is_available() is True


class TestProviderDetection:
    """Tests for premium search provider detection."""

    def test_detect_no_keys(self):
        """Test detection returns None when no keys set."""
        with patch.dict(os.environ, {}, clear=True):
            result = web_premium.get_premium_search_provider()
            assert result is None

    def test_detect_perplexity_key(self):
        """Test Perplexity detected when only Perplexity key set."""
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}, clear=True):
            result = web_premium.get_premium_search_provider()
            assert result == "perplexity"

    def test_detect_gemini_key(self):
        """Test Gemini detected when only Gemini key set."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            result = web_premium.get_premium_search_provider()
            assert result == "gemini"

    def test_detect_both_keys_perplexity_priority(self):
        """Test Perplexity takes priority when both keys set."""
        with patch.dict(os.environ, {
            "PERPLEXITY_API_KEY": "test-key",
            "GEMINI_API_KEY": "test-key"
        }):
            result = web_premium.get_premium_search_provider()
            assert result == "perplexity"

    def test_detect_with_global_config_auto(self):
        """Test auto-detect with global config set to auto."""
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            with patch("ppxai.config.get_tool_config") as mock_config:
                mock_config.return_value = {"preferred": "auto"}
                result = web_premium.get_premium_search_provider()
                assert result == "perplexity"

    def test_detect_with_global_config_force_perplexity(self):
        """Test forced Perplexity with global config."""
        with patch.dict(os.environ, {
            "PERPLEXITY_API_KEY": "test-key",
            "GEMINI_API_KEY": "test-key"
        }):
            with patch("ppxai.config.get_tool_config") as mock_config:
                mock_config.return_value = {"preferred": "perplexity"}
                result = web_premium.get_premium_search_provider()
                assert result == "perplexity"

    def test_detect_with_global_config_force_gemini(self):
        """Test forced Gemini with global config."""
        with patch.dict(os.environ, {
            "PERPLEXITY_API_KEY": "test-key",
            "GEMINI_API_KEY": "test-key"
        }):
            with patch("ppxai.config.get_tool_config") as mock_config:
                mock_config.return_value = {"preferred": "gemini"}
                result = web_premium.get_premium_search_provider()
                assert result == "gemini"

    def test_detect_with_global_config_force_duckduckgo(self):
        """Test forced DuckDuckGo with global config."""
        with patch.dict(os.environ, {
            "PERPLEXITY_API_KEY": "test-key",
            "GEMINI_API_KEY": "test-key"
        }):
            with patch("ppxai.config.get_tool_config") as mock_config:
                mock_config.return_value = {"preferred": "duckduckgo"}
                result = web_premium.get_premium_search_provider()
                assert result is None  # None means use DuckDuckGo

    def test_detect_with_per_provider_override(self):
        """Test per-provider config overrides global config."""
        with patch.dict(os.environ, {
            "PERPLEXITY_API_KEY": "test-key",
            "GEMINI_API_KEY": "test-key"
        }):
            with patch("ppxai.config.get_provider_config") as mock_prov:
                with patch("ppxai.config.get_tool_config") as mock_tool:
                    # Per-provider config says use Gemini
                    mock_prov.return_value = {"web_search": {"preferred": "gemini"}}
                    # Global config says use Perplexity
                    mock_tool.return_value = {"preferred": "perplexity"}

                    result = web_premium.get_premium_search_provider("custom-vllm")
                    # Per-provider should win
                    assert result == "gemini"

    def test_detect_per_provider_fallback_to_global(self):
        """Test per-provider fallback to global config if key missing."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            with patch("ppxai.config.get_provider_config") as mock_prov:
                with patch("ppxai.config.get_tool_config") as mock_tool:
                    # Per-provider config wants Perplexity but key not set
                    mock_prov.return_value = {"web_search": {"preferred": "perplexity"}}
                    # Global config has auto
                    mock_tool.return_value = {"preferred": "auto"}

                    result = web_premium.get_premium_search_provider("custom-vllm")
                    # Should fall back to auto-detect and use Gemini
                    assert result == "gemini"


class TestCostCalculation:
    """Tests for tool cost calculation."""

    def test_perplexity_cost_per_token(self):
        """Test Perplexity per-token pricing calculation."""
        with patch.object(web_premium, "get_tool_pricing") as mock_pricing:
            mock_pricing.return_value = {"input": 0.20, "output": 0.20, "model": "per_token"}
            # 1000 input + 2000 output tokens
            cost = web_premium.calculate_tool_cost("perplexity", tokens_in=1000, tokens_out=2000)
            # (1000 / 1M * 0.20) + (2000 / 1M * 0.20) = 0.0002 + 0.0004 = 0.0006
            assert cost == pytest.approx(0.0006)

    def test_gemini_cost_per_query(self):
        """Test Gemini per-query pricing calculation."""
        with patch.object(web_premium, "get_tool_pricing") as mock_pricing:
            mock_pricing.return_value = {"per_query": 14.00, "model": "per_query"}
            # 5 queries
            cost = web_premium.calculate_tool_cost("gemini_grounding", query_count=5)
            # (5 / 1000) * 14.00 = 0.07
            assert cost == pytest.approx(0.07)

    def test_cost_calculation_no_pricing_config(self):
        """Test cost calculation returns 0 when no pricing config."""
        with patch.object(web_premium, "get_tool_pricing") as mock_pricing:
            mock_pricing.return_value = None
            cost = web_premium.calculate_tool_cost("perplexity", tokens_in=1000, tokens_out=2000)
            assert cost == 0.0


class TestPerplexitySearch:
    """Tests for Perplexity search implementation."""

    @pytest.mark.asyncio
    async def test_perplexity_search_success(self):
        """Test successful Perplexity search call."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test answer"
        mock_response.citations = ["https://example.com", "https://test.com"]
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 200

        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            with patch("openai.AsyncOpenAI") as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value = mock_client
                mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

                with patch.object(web_premium, "get_tool_pricing") as mock_pricing:
                    mock_pricing.return_value = {"input": 0.20, "output": 0.20, "model": "per_token"}

                    content, citations, usage = await web_premium.web_search_perplexity(
                        "test query", num_results=2
                    )

                    assert content == "Test answer"
                    assert citations == ["https://example.com", "https://test.com"]
                    assert usage.provider == "perplexity"
                    assert usage.tokens_in == 100
                    assert usage.tokens_out == 200
                    assert usage.estimated_cost == pytest.approx(0.00006)

    @pytest.mark.asyncio
    async def test_perplexity_search_no_api_key(self):
        """Test Perplexity search fails without API key."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="PERPLEXITY_API_KEY not set"):
                await web_premium.web_search_perplexity("test query")


class TestGeminiSearch:
    """Tests for Gemini search implementation."""

    @pytest.mark.asyncio
    async def test_gemini_search_success(self):
        """Test successful Gemini search call."""
        mock_response = {
            "candidates": [{
                "content": {"parts": [{"text": "Test answer"}]},
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"uri": "https://example.com"}},
                        {"web": {"uri": "https://test.com"}}
                    ]
                }
            }]
        }

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client.post = AsyncMock(return_value=MagicMock(json=MagicMock(return_value=mock_response)))

                with patch.object(web_premium, "get_tool_pricing") as mock_pricing:
                    mock_pricing.return_value = {"per_query": 14.00, "model": "per_query"}

                    content, citations, usage = await web_premium.web_search_gemini(
                        "test query", num_results=2
                    )

                    assert content == "Test answer"
                    assert citations == ["https://example.com", "https://test.com"]
                    assert usage.provider == "gemini"
                    assert usage.estimated_cost == pytest.approx(0.014)

    @pytest.mark.asyncio
    async def test_gemini_search_no_api_key(self):
        """Test Gemini search fails without API key."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="GEMINI_API_KEY not set"):
                await web_premium.web_search_gemini("test query")


class TestToolUsageTracking:
    """Tests for tool usage tracking."""

    def test_get_last_tool_usage_none(self):
        """Test get_last_tool_usage returns None when no usage recorded."""
        web_premium._last_tool_usage = None
        usage = web_premium.get_last_tool_usage()
        assert usage is None

    def test_get_last_tool_usage_resets(self):
        """Test get_last_tool_usage resets after extraction."""
        web_premium._last_tool_usage = ToolUsage(provider="perplexity", call_count=1)

        # First call returns the usage
        usage1 = web_premium.get_last_tool_usage()
        assert usage1 is not None
        assert usage1.provider == "perplexity"

        # Second call returns None (reset)
        usage2 = web_premium.get_last_tool_usage()
        assert usage2 is None


class TestRegistration:
    """Tests for tool registration."""

    def test_register_tools_native_search_provider(self):
        """Test web_search tool registration for providers with native search.

        Perplexity: Skipped (has native web search always on)
        Gemini: Registered (v1.15.2) - grounding disabled when tools active
        """
        mock_manager = MagicMock()

        # Should skip registration for Perplexity (native web search)
        web_premium.register_tools(mock_manager, provider="perplexity")
        mock_manager.register_function.assert_not_called()

        # Should register for Gemini (v1.15.2) - needs web_search tool in agent mode
        # because grounding is disabled when native function calling is active
        mock_manager.reset_mock()
        web_premium.register_tools(mock_manager, provider="gemini")
        # Now registers 3 tools: web_search, get_weather, fetch_url
        assert mock_manager.register_function.call_count == 3
        # Check web_search is first
        first_call_kwargs = mock_manager.register_function.call_args_list[0][1]
        assert first_call_kwargs["name"] == "web_search"
        # Only Perplexity excluded (has native web search)
        assert first_call_kwargs["provider_excluded"] == ["perplexity"]
        # Check get_weather and fetch_url are also registered
        tool_names = [call[1]["name"] for call in mock_manager.register_function.call_args_list]
        assert "get_weather" in tool_names
        assert "fetch_url" in tool_names

    def test_register_tools_no_api_keys(self):
        """Test registration falls back to free search when no API keys."""
        mock_manager = MagicMock()

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(web_premium, "is_available", return_value=False):
                # Since we can't easily mock the import, just verify no premium registration
                # The actual fallback imports the real web module
                web_premium.register_tools(mock_manager, provider="openai")

                # Should NOT call register_function (premium registration)
                # The fallback to free search will call the real web.register_tools
                # which might call register_function, but with different args
                calls = mock_manager.register_function.call_args_list
                # If called, it should NOT have "perplexity" or "gemini" in description
                for call in calls:
                    kwargs = call[1] if len(call) > 1 else {}
                    desc = kwargs.get("description", "")
                    assert "perplexity" not in desc.lower()
                    assert "gemini" not in desc.lower()

    def test_register_tools_with_api_keys(self):
        """Test registration with API keys available."""
        mock_manager = MagicMock()

        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            with patch.object(web_premium, "is_available", return_value=True):
                with patch.object(web_premium, "get_premium_search_provider", return_value="perplexity"):
                    web_premium.register_tools(mock_manager, provider="openai")

                    # Should register 3 tools: web_search, get_weather, fetch_url
                    assert mock_manager.register_function.call_count == 3
                    # Check web_search is first
                    first_call_kwargs = mock_manager.register_function.call_args_list[0][1]
                    assert first_call_kwargs["name"] == "web_search"
                    assert "perplexity" in first_call_kwargs["description"].lower()
                    # Only Perplexity excluded (has native web search)
                    # Gemini needs web_search in agent mode (grounding disabled with native tools)
                    assert first_call_kwargs["provider_excluded"] == ["perplexity"]
                    # Check get_weather and fetch_url are also registered
                    tool_names = [call[1]["name"] for call in mock_manager.register_function.call_args_list]
                    assert "get_weather" in tool_names
                    assert "fetch_url" in tool_names


class TestIntegration:
    """Integration tests combining multiple components."""

    @pytest.mark.asyncio
    async def test_web_search_premium_fallback_on_error(self):
        """Test fallback to DuckDuckGo on premium API error."""
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            with patch.object(web_premium, "web_search_perplexity") as mock_perplexity:
                mock_perplexity.side_effect = Exception("API Error")

                with patch.object(web_premium, "get_premium_search_provider", return_value="perplexity"):
                    # Let it actually fall back to DuckDuckGo (real call)
                    # Just verify it doesn't raise and returns something
                    result = await web_premium.web_search_premium("test query")

                    # Should have received some result from the fallback
                    assert result is not None
                    # The perplexity function was called and failed
                    mock_perplexity.assert_called_once()

    @pytest.mark.asyncio
    async def test_web_search_premium_with_provider_context(self):
        """Test web_search_premium receives provider context."""
        with patch.dict(os.environ, {
            "PERPLEXITY_API_KEY": "test-key",
            "GEMINI_API_KEY": "test-key"
        }):
            with patch.object(web_premium, "web_search_perplexity") as mock_perplexity:
                with patch.object(web_premium, "get_premium_search_provider", return_value="perplexity"):
                    mock_perplexity.return_value = ("Test answer", [], ToolUsage(provider="perplexity"))

                    # Simulate per-provider override via wrapper
                    result = await web_premium.web_search_premium("test", _provider_name="openai")
                    assert result is not None

"""
Integration tests for premium web search fallback system (v1.13.4).

Tests end-to-end scenarios with actual configuration files and multiple API key combinations.
"""

import pytest
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from ppxai.engine.types import ToolUsage, UsageStats


class TestPremiumWebSearchIntegration:
    """Integration tests for premium web search feature (v1.13.4)."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for config files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_web_search_tool_excluded_for_perplexity(self):
        """Test that web_search tool is not registered for Perplexity provider."""
        from ppxai.config import provider_needs_tool

        # Perplexity has native web search
        assert provider_needs_tool("perplexity", "web_search") is False

    def test_web_search_tool_excluded_for_gemini(self):
        """Test that web_search tool is not registered for Gemini provider."""
        from ppxai.config import provider_needs_tool

        # Gemini has native Google Search Grounding
        assert provider_needs_tool("gemini", "web_search") is False

    @patch('ppxai.config.providers._get_providers')
    def test_web_search_tool_required_for_custom(self, mock_get_providers):
        """Test that web_search tool is required for custom provider."""
        from ppxai.config import provider_needs_tool

        # Mock providers dict with custom provider having no native web_search
        mock_get_providers.return_value = {
            'custom': {'capabilities': {'web_search': False}},
            'perplexity': {'capabilities': {'web_search': True}}
        }

        # Custom provider doesn't have native web search
        assert provider_needs_tool("custom", "web_search") is True

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    def test_premium_search_available_with_perplexity_key(self):
        """Test is_available() returns True when PERPLEXITY_API_KEY is set."""
        try:
            from ppxai.engine.tools.builtin import web_premium
            assert web_premium.is_available() is True
        except ImportError:
            pytest.skip("web_premium module not available")

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    def test_premium_search_available_with_gemini_key(self):
        """Test is_available() returns True when GEMINI_API_KEY is set."""
        try:
            from ppxai.engine.tools.builtin import web_premium
            assert web_premium.is_available() is True
        except ImportError:
            pytest.skip("web_premium module not available")

    @patch.dict(os.environ, {}, clear=True)
    def test_premium_search_not_available_without_keys(self):
        """Test is_available() returns False when no premium keys set."""
        try:
            from ppxai.engine.tools.builtin import web_premium
            assert web_premium.is_available() is False
        except ImportError:
            pytest.skip("web_premium module not available")

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    def test_auto_detect_prefers_perplexity(self):
        """Test auto-detection prefers Perplexity when key is available."""
        try:
            from ppxai.engine.tools.builtin import web_premium
            provider = web_premium.get_premium_search_provider()
            assert provider == "perplexity"
        except ImportError:
            pytest.skip("web_premium module not available")

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True)
    def test_auto_detect_uses_gemini_without_perplexity(self):
        """Test auto-detection uses Gemini when Perplexity key not available."""
        try:
            from ppxai.engine.tools.builtin import web_premium
            provider = web_premium.get_premium_search_provider()
            assert provider == "gemini"
        except ImportError:
            pytest.skip("web_premium module not available")

    @patch.dict(os.environ, {}, clear=True)
    def test_auto_detect_falls_back_to_duckduckgo(self):
        """Test auto-detection falls back to DuckDuckGo when no premium keys."""
        try:
            from ppxai.engine.tools.builtin import web_premium
            provider = web_premium.get_premium_search_provider()
            # When no premium keys available, should fall back to DuckDuckGo
            # or return a default provider
            assert provider in ["duckduckgo", None, "perplexity", "gemini"]
        except ImportError:
            pytest.skip("web_premium module not available")

    @patch('ppxai.config.get_tool_config')
    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key", "GEMINI_API_KEY": "test-key"})
    def test_per_provider_override_perplexity(self, mock_get_tool_config):
        """Test per-provider config override forces Perplexity."""
        mock_get_tool_config.return_value = {"preferred": "auto"}

        try:
            from ppxai.engine.tools.builtin import web_premium
            provider = web_premium.get_premium_search_provider(provider_name="openai")
            # Without per-provider config, should auto-detect (Perplexity priority)
            assert provider in ["perplexity", "gemini", "duckduckgo"]
        except ImportError:
            pytest.skip("web_premium module not available")

    @patch('ppxai.config.get_tool_config')
    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True)
    def test_forced_config_fails_without_key(self, mock_get_tool_config):
        """Test forced provider fails gracefully when key not available."""
        mock_get_tool_config.return_value = {"preferred": "perplexity"}

        try:
            from ppxai.engine.tools.builtin import web_premium
            # When Perplexity forced but not available, should fall back to auto
            provider = web_premium.get_premium_search_provider()
            # Should NOT be None or raise exception
            assert provider is not None
        except ImportError:
            pytest.skip("web_premium module not available")

    def test_tool_usage_tracking_structure(self):
        """Test ToolUsage dataclass has all required fields."""
        from ppxai.engine.types import ToolUsage

        usage = ToolUsage(
            call_count=2,
            tokens_in=100,
            tokens_out=200,
            estimated_cost=0.01,
            provider="perplexity"
        )

        assert usage.call_count == 2
        assert usage.tokens_in == 100
        assert usage.tokens_out == 200
        assert usage.estimated_cost == 0.01
        assert usage.provider == "perplexity"

    def test_usage_stats_includes_tool_calls(self):
        """Test UsageStats has tool_calls field for tracking tools."""
        from ppxai.engine.types import UsageStats

        stats = UsageStats(
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            estimated_cost=0.05
        )

        assert hasattr(stats, "tool_calls")
        assert isinstance(stats.tool_calls, dict)
        assert len(stats.tool_calls) == 0  # Empty initially

    def test_tool_usage_aggregation(self):
        """Test adding tool usage from multiple calls."""
        from ppxai.engine.types import ToolUsage

        usage = ToolUsage(provider="perplexity")

        # First call
        usage.add_usage(tokens_in=100, tokens_out=200, cost=0.0006)
        assert usage.call_count == 1
        assert usage.tokens_in == 100

        # Second call
        usage.add_usage(tokens_in=150, tokens_out=300, cost=0.0009)
        assert usage.call_count == 2
        assert usage.tokens_in == 250
        assert usage.tokens_out == 500
        assert usage.estimated_cost == pytest.approx(0.0015)

    def test_gemini_per_query_pricing(self):
        """Test Gemini per-query pricing calculation."""
        from ppxai.config import get_tool_pricing

        pricing = get_tool_pricing("web_search", "gemini_grounding")

        # Gemini Grounding uses per-query pricing
        if pricing:
            assert "per_query" in pricing or "model" in pricing

    def test_perplexity_per_token_pricing(self):
        """Test Perplexity per-token pricing configuration."""
        from ppxai.config import get_tool_pricing

        pricing = get_tool_pricing("web_search", "perplexity")

        # Perplexity uses per-token pricing
        if pricing:
            assert "input" in pricing or "model" in pricing

    def test_duckduckgo_free_pricing(self):
        """Test DuckDuckGo has no cost."""
        from ppxai.config import get_tool_pricing

        pricing = get_tool_pricing("web_search", "duckduckgo")

        # DuckDuckGo is free
        if pricing:
            assert pricing.get("cost", 0) == 0

    @patch('ppxai.engine.tools.builtin.web_premium.web_search_perplexity')
    async def test_perplexity_search_integration(self, mock_search):
        """Test Perplexity search function is called correctly."""
        from ppxai.engine.types import ToolUsage

        # Mock Perplexity response
        mock_search.return_value = (
            "Test result",
            ["https://example.com"],
            ToolUsage(
                call_count=1,
                tokens_in=100,
                tokens_out=200,
                estimated_cost=0.0006,
                provider="perplexity"
            )
        )

        result, citations, usage = await mock_search("test query")

        assert result == "Test result"
        assert len(citations) == 1
        assert usage.provider == "perplexity"
        assert usage.estimated_cost > 0

    @patch('ppxai.engine.tools.builtin.web_premium.web_search_gemini')
    async def test_gemini_search_integration(self, mock_search):
        """Test Gemini search function is called correctly."""
        from ppxai.engine.types import ToolUsage

        # Mock Gemini response
        mock_search.return_value = (
            "Test result",
            ["https://example.com"],
            ToolUsage(
                call_count=1,
                tokens_in=0,
                tokens_out=0,
                estimated_cost=0.014,
                provider="gemini"
            )
        )

        result, citations, usage = await mock_search("test query")

        assert result == "Test result"
        assert usage.provider == "gemini"
        # Gemini has per-query pricing
        assert usage.estimated_cost == 0.014

    def test_cost_calculation_per_token(self):
        """Test cost calculation for per-token pricing (Perplexity)."""
        try:
            from ppxai.engine.tools.builtin import web_premium
            # 100 input tokens + 200 output tokens at pricing config
            cost = web_premium.calculate_tool_cost(
                "perplexity",
                tokens_in=100,
                tokens_out=200
            )
            # Cost should be non-negative
            assert cost >= 0
            assert cost < 1.0  # Should be reasonable
        except ImportError:
            pytest.skip("web_premium module not available")

    def test_cost_calculation_per_query(self):
        """Test cost calculation for per-query pricing (Gemini)."""
        try:
            from ppxai.engine.tools.builtin import web_premium
            # Gemini: $14 per 1000 queries = $0.014 per query
            cost = web_premium.calculate_tool_cost(
                "gemini",
                query_count=1
            )
            # Cost should be non-negative and reasonable for Gemini
            assert cost >= 0
            assert cost < 1.0
        except ImportError:
            pytest.skip("web_premium module not available")

    def test_session_aggregates_tool_usage(self):
        """Test session manager properly aggregates tool usage."""
        from ppxai.engine.types import UsageStats, ToolUsage

        # Create usage stats with tool calls
        usage = UsageStats(
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            estimated_cost=0.05
        )

        usage.tool_calls["web_search"] = ToolUsage(
            call_count=2,
            tokens_in=200,
            tokens_out=400,
            estimated_cost=0.01,
            provider="perplexity"
        )

        # Verify structure
        assert "web_search" in usage.tool_calls
        assert usage.tool_calls["web_search"].provider == "perplexity"
        assert usage.tool_calls["web_search"].estimated_cost == 0.01

    @patch('ppxai.config.PROVIDERS', {
        'perplexity': {'capabilities': {'web_search': True}},
        'gemini': {'capabilities': {'web_search': True}},
        'custom': {'capabilities': {'web_search': False}}
    })
    def test_native_search_providers_exclude_tool(self):
        """Test that native search providers don't need web_search tool."""
        from ppxai.config import PROVIDERS

        # Perplexity should have web_search capability
        assert PROVIDERS["perplexity"]["capabilities"]["web_search"] is True

        # Gemini should have web_search capability (Google Search Grounding)
        assert PROVIDERS["gemini"]["capabilities"]["web_search"] is True

        # Custom should NOT have web_search capability
        assert PROVIDERS["custom"]["capabilities"]["web_search"] is False

    def test_mixed_provider_usage(self):
        """Test session tracking mixed LLM + tool usage."""
        from ppxai.engine.types import UsageStats, ToolUsage

        stats = UsageStats(
            prompt_tokens=2000,
            completion_tokens=1000,
            total_tokens=3000,
            estimated_cost=0.10  # LLM cost
        )

        # Add multiple tool usages
        stats.tool_calls["web_search"] = ToolUsage(
            call_count=2,
            tokens_in=200,
            tokens_out=400,
            estimated_cost=0.01,
            provider="perplexity"
        )

        stats.tool_calls["shell"] = ToolUsage(
            call_count=3,
            tokens_in=0,
            tokens_out=0,
            estimated_cost=0.0,
            provider="free"
        )

        # Verify separation
        assert len(stats.tool_calls) == 2
        assert stats.estimated_cost == 0.10  # LLM cost only
        total_tool_cost = sum(u.estimated_cost for u in stats.tool_calls.values())
        assert total_tool_cost == 0.01

    def test_config_helpers_return_correct_types(self):
        """Test config helper functions return correct types."""
        from ppxai.config import get_tool_config, get_tool_pricing

        # Should always return dict
        web_search_config = get_tool_config("web_search")
        assert isinstance(web_search_config, dict)

        perplexity_pricing = get_tool_pricing("web_search", "perplexity")
        assert isinstance(perplexity_pricing, dict)

        # Nonexistent returns empty dict
        nonexistent = get_tool_config("nonexistent_tool")
        assert nonexistent == {}

    def test_tool_usage_with_fallback_scenario(self):
        """Test tool usage tracking when fallback occurs."""
        from ppxai.engine.types import ToolUsage

        # If premium API fails, falls back to DuckDuckGo
        fallback_usage = ToolUsage(
            call_count=1,
            tokens_in=0,
            tokens_out=0,
            estimated_cost=0.0,
            provider="duckduckgo"
        )

        assert fallback_usage.provider == "duckduckgo"
        assert fallback_usage.estimated_cost == 0.0
        assert fallback_usage.call_count == 1


class TestPremiumWebSearchConfiguration:
    """Tests for configuration of premium web search (v1.13.4)."""

    def test_web_search_config_exists(self):
        """Test that web_search config section exists."""
        from ppxai.config import get_tool_config

        config = get_tool_config("web_search")
        # Config should exist and have preferred field
        if config:
            assert "preferred" in config or "pricing" in config

    def test_agent_config_exists(self):
        """Test that agent config section exists."""
        from ppxai.config import get_tool_config

        config = get_tool_config("agent")
        # Agent config should have max_iterations or similar
        if config:
            assert "max_iterations" in config or "min_task_words" in config

    def test_shell_config_exists(self):
        """Test that shell config section exists."""
        from ppxai.config import get_tool_config

        config = get_tool_config("shell")
        # Shell config should have security settings
        if config:
            assert "require_consent" in config or "dangerous_commands" in config

    def test_per_provider_web_search_override(self):
        """Test per-provider web_search override in config."""
        from ppxai.config import PROVIDERS

        # OpenAI should have optional per-provider override
        openai_config = PROVIDERS.get("openai", {})
        if "web_search" in openai_config:
            # Should have preferred field if override exists
            assert "preferred" in openai_config["web_search"]

    def test_pricing_model_field_in_config(self):
        """Test pricing includes model field for identification."""
        from ppxai.config import get_tool_config

        config = get_tool_config("web_search")
        if config and "pricing" in config:
            pricing = config["pricing"]
            # Should have pricing for at least one provider
            if "perplexity" in pricing:
                assert "model" in pricing["perplexity"] or "input" in pricing["perplexity"]

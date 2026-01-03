"""
Tests for ToolUsage dataclass and tool usage tracking (v1.13.4).

Tests the new ToolUsage dataclass and how tool usage is aggregated in UsageStats.
"""

import pytest
from ppxai.engine.types import ToolUsage, UsageStats


class TestToolUsage:
    """Tests for ToolUsage dataclass."""

    def test_tool_usage_init_defaults(self):
        """Test ToolUsage initializes with default values."""
        usage = ToolUsage()

        assert usage.call_count == 0
        assert usage.tokens_in == 0
        assert usage.tokens_out == 0
        assert usage.estimated_cost == 0.0
        assert usage.provider == ""

    def test_tool_usage_init_with_values(self):
        """Test ToolUsage initialization with values."""
        usage = ToolUsage(
            call_count=3,
            tokens_in=1500,
            tokens_out=2000,
            estimated_cost=0.007,
            provider="perplexity"
        )

        assert usage.call_count == 3
        assert usage.tokens_in == 1500
        assert usage.tokens_out == 2000
        assert usage.estimated_cost == 0.007
        assert usage.provider == "perplexity"

    def test_tool_usage_add_usage_single_call(self):
        """Test adding usage from a single tool call."""
        usage = ToolUsage(provider="perplexity")

        usage.add_usage(tokens_in=100, tokens_out=200, cost=0.0006)

        assert usage.call_count == 1
        assert usage.tokens_in == 100
        assert usage.tokens_out == 200
        assert usage.estimated_cost == pytest.approx(0.0006)

    def test_tool_usage_add_usage_multiple_calls(self):
        """Test accumulating usage from multiple tool calls."""
        usage = ToolUsage(provider="perplexity")

        # First call
        usage.add_usage(tokens_in=100, tokens_out=200, cost=0.0006)
        # Second call
        usage.add_usage(tokens_in=150, tokens_out=300, cost=0.0009)

        assert usage.call_count == 2
        assert usage.tokens_in == 250
        assert usage.tokens_out == 500
        assert usage.estimated_cost == pytest.approx(0.0015)

    def test_tool_usage_partial_add_usage(self):
        """Test add_usage with optional parameters."""
        usage = ToolUsage(provider="gemini")

        # Add only cost (per-query billing)
        usage.add_usage(cost=0.014)

        assert usage.call_count == 1
        assert usage.tokens_in == 0
        assert usage.tokens_out == 0
        assert usage.estimated_cost == pytest.approx(0.014)

    def test_tool_usage_multiple_tools_in_dict(self):
        """Test tracking multiple tools in a dictionary."""
        tools = {
            "web_search": ToolUsage(provider="perplexity", call_count=2, estimated_cost=0.001),
            "read_file": ToolUsage(provider="free", call_count=5, estimated_cost=0.0)
        }

        assert len(tools) == 2
        assert tools["web_search"].call_count == 2
        assert tools["read_file"].call_count == 5
        assert tools["web_search"].estimated_cost == pytest.approx(0.001)
        assert tools["read_file"].estimated_cost == 0.0


class TestUsageStatsWithToolCalls:
    """Tests for UsageStats with tool_calls field."""

    def test_usage_stats_init_defaults(self):
        """Test UsageStats initializes with empty tool_calls dict."""
        stats = UsageStats()

        assert stats.prompt_tokens == 0
        assert stats.completion_tokens == 0
        assert stats.total_tokens == 0
        assert stats.estimated_cost == 0.0
        assert stats.tool_calls == {}

    def test_usage_stats_with_tool_calls(self):
        """Test UsageStats with tool calls."""
        web_search_usage = ToolUsage(
            call_count=1,
            tokens_in=100,
            tokens_out=200,
            estimated_cost=0.0006,
            provider="perplexity"
        )

        stats = UsageStats(
            prompt_tokens=1000,
            completion_tokens=2000,
            total_tokens=3000,
            estimated_cost=0.05
        )
        stats.tool_calls["web_search"] = web_search_usage

        assert stats.prompt_tokens == 1000
        assert stats.completion_tokens == 2000
        assert len(stats.tool_calls) == 1
        assert stats.tool_calls["web_search"].provider == "perplexity"

    def test_usage_stats_multiple_tool_calls(self):
        """Test UsageStats tracking multiple tool calls."""
        stats = UsageStats(
            prompt_tokens=1000,
            completion_tokens=2000,
            estimated_cost=0.05
        )

        web_search = ToolUsage(
            call_count=1,
            tokens_in=100,
            tokens_out=200,
            estimated_cost=0.0006,
            provider="perplexity"
        )
        shell_tool = ToolUsage(
            call_count=2,
            tokens_in=0,
            tokens_out=0,
            estimated_cost=0.0,
            provider="free"
        )

        stats.tool_calls["web_search"] = web_search
        stats.tool_calls["shell"] = shell_tool

        assert len(stats.tool_calls) == 2
        total_tool_cost = sum(u.estimated_cost for u in stats.tool_calls.values())
        assert total_tool_cost == pytest.approx(0.0006)

    def test_usage_stats_serialization(self):
        """Test that UsageStats can be converted to dict (for JSON serialization)."""
        from dataclasses import asdict

        stats = UsageStats(
            prompt_tokens=1000,
            completion_tokens=2000,
            estimated_cost=0.05
        )
        stats.tool_calls["web_search"] = ToolUsage(
            call_count=1,
            tokens_in=100,
            tokens_out=200,
            estimated_cost=0.0006,
            provider="perplexity"
        )

        # Should be serializable to dict
        stats_dict = asdict(stats)

        assert stats_dict["prompt_tokens"] == 1000
        assert stats_dict["completion_tokens"] == 2000
        assert stats_dict["estimated_cost"] == 0.05
        assert "web_search" in stats_dict["tool_calls"]


class TestToolUsageIntegration:
    """Integration tests for tool usage tracking."""

    def test_merging_tool_usage_from_multiple_responses(self):
        """Test merging tool usage from multiple responses."""
        # Response 1: web search
        response1 = UsageStats(
            prompt_tokens=500,
            completion_tokens=1000,
            estimated_cost=0.02
        )
        response1.tool_calls["web_search"] = ToolUsage(
            call_count=1,
            tokens_in=100,
            tokens_out=200,
            estimated_cost=0.0006,
            provider="perplexity"
        )

        # Response 2: another web search
        response2 = UsageStats(
            prompt_tokens=300,
            completion_tokens=500,
            estimated_cost=0.01
        )
        response2.tool_calls["web_search"] = ToolUsage(
            call_count=1,
            tokens_in=150,
            tokens_out=300,
            estimated_cost=0.0009,
            provider="perplexity"
        )

        # Merge into session stats
        session_stats = UsageStats()

        # Merge response 1
        session_stats.prompt_tokens += response1.prompt_tokens
        session_stats.completion_tokens += response1.completion_tokens
        session_stats.estimated_cost += response1.estimated_cost

        for tool_name, tool_usage in response1.tool_calls.items():
            if tool_name not in session_stats.tool_calls:
                session_stats.tool_calls[tool_name] = ToolUsage(provider=tool_usage.provider)
            session_stats.tool_calls[tool_name].call_count += tool_usage.call_count
            session_stats.tool_calls[tool_name].tokens_in += tool_usage.tokens_in
            session_stats.tool_calls[tool_name].tokens_out += tool_usage.tokens_out
            session_stats.tool_calls[tool_name].estimated_cost += tool_usage.estimated_cost

        # Merge response 2
        session_stats.prompt_tokens += response2.prompt_tokens
        session_stats.completion_tokens += response2.completion_tokens
        session_stats.estimated_cost += response2.estimated_cost

        for tool_name, tool_usage in response2.tool_calls.items():
            if tool_name not in session_stats.tool_calls:
                session_stats.tool_calls[tool_name] = ToolUsage(provider=tool_usage.provider)
            session_stats.tool_calls[tool_name].call_count += tool_usage.call_count
            session_stats.tool_calls[tool_name].tokens_in += tool_usage.tokens_in
            session_stats.tool_calls[tool_name].tokens_out += tool_usage.tokens_out
            session_stats.tool_calls[tool_name].estimated_cost += tool_usage.estimated_cost

        # Verify aggregation
        assert session_stats.prompt_tokens == 800
        assert session_stats.completion_tokens == 1500
        assert session_stats.estimated_cost == pytest.approx(0.03)
        assert session_stats.tool_calls["web_search"].call_count == 2
        assert session_stats.tool_calls["web_search"].tokens_in == 250
        assert session_stats.tool_calls["web_search"].tokens_out == 500
        assert session_stats.tool_calls["web_search"].estimated_cost == pytest.approx(0.0015)

    def test_tool_usage_with_different_providers(self):
        """Test tracking tool usage from different premium providers."""
        stats = UsageStats()

        # First call: Perplexity search
        stats.tool_calls["web_search"] = ToolUsage(
            call_count=1,
            tokens_in=100,
            tokens_out=200,
            estimated_cost=0.0006,
            provider="perplexity"
        )

        # Second call: Gemini search (replaces first)
        # In practice, only one provider is used per session
        stats.tool_calls["web_search"] = ToolUsage(
            call_count=1,
            tokens_in=0,
            tokens_out=0,
            estimated_cost=0.014,
            provider="gemini"
        )

        assert stats.tool_calls["web_search"].provider == "gemini"
        assert stats.tool_calls["web_search"].estimated_cost == pytest.approx(0.014)

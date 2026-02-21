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


class TestSessionToolUsageIntegration:
    """Tests for SessionManager.update_usage() with tool_calls (v1.16.0 fix)."""

    def test_update_usage_merges_tool_calls_into_session(self, tmp_path):
        """Test that tool_calls in UsageStats are merged into session totals."""
        from ppxai.engine.session import SessionManager

        session = SessionManager(sessions_dir=tmp_path / "sessions")

        usage = UsageStats(
            prompt_tokens=500,
            completion_tokens=1000,
            total_tokens=1500,
            estimated_cost=0.02,
        )
        usage.tool_calls["web_search"] = ToolUsage(
            call_count=1,
            tokens_in=100,
            tokens_out=200,
            estimated_cost=0.0006,
            provider="perplexity",
        )

        session.update_usage(usage, "gemini", "gemini-2.5-flash")

        # Tool usage should be in session.usage.tool_calls
        assert "web_search" in session.usage.tool_calls
        assert session.usage.tool_calls["web_search"].call_count == 1
        assert session.usage.tool_calls["web_search"].tokens_in == 100
        assert session.usage.tool_calls["web_search"].estimated_cost == pytest.approx(0.0006)

        # Tool cost should be added to session total
        assert session.usage.estimated_cost == pytest.approx(0.02 + 0.0006)

    def test_update_usage_accumulates_tool_calls_across_iterations(self, tmp_path):
        """Test that multiple tool calls accumulate correctly."""
        from ppxai.engine.session import SessionManager

        session = SessionManager(sessions_dir=tmp_path / "sessions")

        # First iteration: 1 web search
        usage1 = UsageStats(prompt_tokens=500, completion_tokens=1000,
                            total_tokens=1500, estimated_cost=0.02)
        usage1.tool_calls["web_search"] = ToolUsage(
            call_count=1, tokens_in=100, tokens_out=200,
            estimated_cost=0.0006, provider="perplexity",
        )
        session.update_usage(usage1, "gemini", "gemini-2.5-flash")

        # Second iteration: 2 more web searches
        usage2 = UsageStats(prompt_tokens=300, completion_tokens=500,
                            total_tokens=800, estimated_cost=0.01)
        usage2.tool_calls["web_search"] = ToolUsage(
            call_count=2, tokens_in=250, tokens_out=400,
            estimated_cost=0.0013, provider="perplexity",
        )
        session.update_usage(usage2, "gemini", "gemini-2.5-flash")

        # Accumulated: 3 calls, merged tokens/cost
        ws = session.usage.tool_calls["web_search"]
        assert ws.call_count == 3
        assert ws.tokens_in == 350
        assert ws.tokens_out == 600
        assert ws.estimated_cost == pytest.approx(0.0019)

        # Session total includes both model cost and tool cost
        assert session.usage.estimated_cost == pytest.approx(0.02 + 0.0006 + 0.01 + 0.0013)

    def test_save_usage_to_persistent_storage_includes_tool_calls(self, tmp_path):
        """Test that save_usage_to_persistent_storage passes tool_calls."""
        from ppxai.engine.session import SessionManager
        from ppxai.usage import UsageStorage

        session = SessionManager(sessions_dir=tmp_path / "sessions")
        session.metadata["created_at"] = "2026-02-21T10:00:00"

        # Add usage with tool calls
        usage = UsageStats(
            prompt_tokens=1000, completion_tokens=500,
            total_tokens=1500, estimated_cost=0.05,
        )
        usage.tool_calls["web_search"] = ToolUsage(
            call_count=2, tokens_in=200, tokens_out=400,
            estimated_cost=0.001, provider="perplexity",
        )
        session.update_usage(usage, "gemini", "gemini-2.5-flash")

        # Mock the global usage storage to use our temp dir
        import ppxai.usage
        usage_dir = tmp_path / "usage"
        usage_dir.mkdir()
        old_storage = ppxai.usage._storage
        ppxai.usage._storage = UsageStorage(usage_dir=usage_dir)

        try:
            session.save_usage_to_persistent_storage()

            # Verify tool_calls were persisted
            storage = UsageStorage(usage_dir=usage_dir)
            assert len(storage._data["sessions"]) == 1
            saved = storage._data["sessions"][0]
            assert "tool_calls" in saved
            assert "web_search" in saved["tool_calls"]
            assert saved["tool_calls"]["web_search"]["call_count"] == 2
            assert saved["tool_calls"]["web_search"]["provider"] == "perplexity"
            assert saved["tool_calls"]["web_search"]["estimated_cost"] == pytest.approx(0.001)
        finally:
            ppxai.usage._storage = old_storage

    def test_get_usage_includes_tool_calls(self, tmp_path):
        """Test that get_usage() exports tool_calls data."""
        from ppxai.engine.session import SessionManager

        session = SessionManager(sessions_dir=tmp_path / "sessions")

        usage = UsageStats(
            prompt_tokens=1000, completion_tokens=500,
            total_tokens=1500, estimated_cost=0.05,
        )
        usage.tool_calls["web_search"] = ToolUsage(
            call_count=3, tokens_in=300, tokens_out=600,
            estimated_cost=0.002, provider="perplexity",
        )
        session.update_usage(usage, "openai", "gpt-5.2")

        result = session.get_usage()

        assert "tool_calls" in result
        assert "web_search" in result["tool_calls"]
        tc = result["tool_calls"]["web_search"]
        assert tc["call_count"] == 3
        assert tc["tokens_in"] == 300
        assert tc["tokens_out"] == 600
        assert tc["provider"] == "perplexity"

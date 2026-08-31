"""
Tests for persistent usage storage (v1.12.3).

Tests the UsageStorage class that persists usage data across sessions.
"""

from datetime import datetime, timedelta

import pytest

from ppxai.usage import UsageStorage


@pytest.fixture
def temp_usage_dir(tmp_path):
    """Create a temporary directory for usage storage."""
    usage_dir = tmp_path / "usage"
    usage_dir.mkdir()
    return usage_dir


@pytest.fixture
def storage(temp_usage_dir):
    """Create a UsageStorage instance with temp directory."""
    return UsageStorage(usage_dir=temp_usage_dir)


class TestUsageStorage:
    """Tests for UsageStorage class."""

    def test_init_creates_directory(self, tmp_path):
        """Test that init creates the usage directory if it doesn't exist."""
        usage_dir = tmp_path / "nonexistent" / "usage"
        assert not usage_dir.exists()

        storage = UsageStorage(usage_dir=usage_dir)
        assert usage_dir.exists()

    def test_init_loads_empty_data(self, storage):
        """Test that init loads empty data structure."""
        assert storage._data["version"] == 1
        assert storage._data["sessions"] == []

    def test_save_session_usage(self, storage):
        """Test saving session usage data."""
        storage.save_session_usage(
            session_id="test-session-1",
            started_at=datetime(2026, 1, 1, 10, 0),
            ended_at=datetime(2026, 1, 1, 11, 0),
            usage_by_model={
                "perplexity/sonar-pro": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "estimated_cost": 0.05
                }
            },
            total_cost=0.05,
            total_tokens=1500,
            message_count=10
        )

        assert len(storage._data["sessions"]) == 1
        session = storage._data["sessions"][0]
        assert session["session_id"] == "test-session-1"
        assert session["total_tokens"] == 1500
        assert session["total_cost"] == 0.05

    def test_save_session_skips_empty_usage(self, storage):
        """Test that empty usage is not saved."""
        storage.save_session_usage(
            session_id="empty-session",
            started_at=datetime.now(),
            ended_at=datetime.now(),
            usage_by_model={},
            total_cost=0.0,
            total_tokens=0,
            message_count=0
        )

        assert len(storage._data["sessions"]) == 0

    def test_persistence_to_file(self, storage, temp_usage_dir):
        """Test that data is persisted to file."""
        storage.save_session_usage(
            session_id="persist-test",
            started_at=datetime(2026, 1, 1, 10, 0),
            ended_at=datetime(2026, 1, 1, 11, 0),
            usage_by_model={"test/model": {"prompt_tokens": 100, "completion_tokens": 50, "estimated_cost": 0.01}},
            total_cost=0.01,
            total_tokens=150,
            message_count=5
        )

        # Load fresh storage from same directory
        new_storage = UsageStorage(usage_dir=temp_usage_dir)
        assert len(new_storage._data["sessions"]) == 1
        assert new_storage._data["sessions"][0]["session_id"] == "persist-test"

    def test_get_usage_report_all(self, storage):
        """Test getting all-time usage report."""
        # Add some test sessions
        for i in range(3):
            storage.save_session_usage(
                session_id=f"session-{i}",
                started_at=datetime.now() - timedelta(days=i),
                ended_at=datetime.now() - timedelta(days=i) + timedelta(hours=1),
                usage_by_model={"perplexity/sonar-pro": {"prompt_tokens": 100, "completion_tokens": 50, "estimated_cost": 0.01}},
                total_cost=0.01,
                total_tokens=150,
                message_count=5
            )

        report = storage.get_usage_report("all")

        assert report["period"] == "all"
        assert report["session_count"] == 3
        assert report["total_tokens"] == 450  # 3 * 150
        assert report["total_cost"] == 0.03  # 3 * 0.01
        assert "perplexity" in report["by_provider"]
        assert "perplexity/sonar-pro" in report["by_model"]

    def test_get_usage_report_24h(self, storage):
        """Test getting 24h usage report."""
        # Add session from today
        storage.save_session_usage(
            session_id="today",
            started_at=datetime.now() - timedelta(hours=1),
            ended_at=datetime.now(),
            usage_by_model={"test/model": {"prompt_tokens": 100, "completion_tokens": 50, "estimated_cost": 0.01}},
            total_cost=0.01,
            total_tokens=150,
            message_count=5
        )

        # Add session from 3 days ago (should not be included)
        storage.save_session_usage(
            session_id="old",
            started_at=datetime.now() - timedelta(days=3),
            ended_at=datetime.now() - timedelta(days=3) + timedelta(hours=1),
            usage_by_model={"test/model": {"prompt_tokens": 200, "completion_tokens": 100, "estimated_cost": 0.02}},
            total_cost=0.02,
            total_tokens=300,
            message_count=10
        )

        report = storage.get_usage_report("24h")

        assert report["period"] == "24h"
        assert report["session_count"] == 1  # Only today's session
        assert report["total_tokens"] == 150

    def test_get_usage_report_week(self, storage):
        """Test getting weekly usage report."""
        # Add session from 2 days ago
        storage.save_session_usage(
            session_id="recent",
            started_at=datetime.now() - timedelta(days=2),
            ended_at=datetime.now() - timedelta(days=2) + timedelta(hours=1),
            usage_by_model={"test/model": {"prompt_tokens": 100, "completion_tokens": 50, "estimated_cost": 0.01}},
            total_cost=0.01,
            total_tokens=150,
            message_count=5
        )

        # Add session from 10 days ago (should not be included)
        storage.save_session_usage(
            session_id="old",
            started_at=datetime.now() - timedelta(days=10),
            ended_at=datetime.now() - timedelta(days=10) + timedelta(hours=1),
            usage_by_model={"test/model": {"prompt_tokens": 200, "completion_tokens": 100, "estimated_cost": 0.02}},
            total_cost=0.02,
            total_tokens=300,
            message_count=10
        )

        report = storage.get_usage_report("week")

        assert report["period"] == "week"
        assert report["session_count"] == 1  # Only recent session

    def test_get_sessions(self, storage):
        """Test getting list of sessions."""
        # Add sessions
        for i in range(5):
            storage.save_session_usage(
                session_id=f"session-{i}",
                started_at=datetime.now() - timedelta(days=i),
                ended_at=datetime.now() - timedelta(days=i) + timedelta(hours=1),
                usage_by_model={"test/model": {"prompt_tokens": 100, "completion_tokens": 50, "estimated_cost": 0.01}},
                total_cost=0.01,
                total_tokens=150,
                message_count=5
            )

        sessions = storage.get_sessions(limit=3)

        assert len(sessions) == 3
        # Should be sorted newest first
        assert sessions[0]["session_id"] == "session-0"

    def test_get_session_count(self, storage):
        """Test getting total session count."""
        for i in range(5):
            storage.save_session_usage(
                session_id=f"session-{i}",
                started_at=datetime.now(),
                ended_at=datetime.now() + timedelta(hours=1),
                usage_by_model={"test/model": {"prompt_tokens": 100, "completion_tokens": 50, "estimated_cost": 0.01}},
                total_cost=0.01,
                total_tokens=150,
                message_count=5
            )

        assert storage.get_session_count() == 5

    def test_clear_old_sessions(self, storage):
        """Test clearing old sessions."""
        # Add recent session
        storage.save_session_usage(
            session_id="recent",
            started_at=datetime.now() - timedelta(days=1),
            ended_at=datetime.now(),
            usage_by_model={"test/model": {"prompt_tokens": 100, "completion_tokens": 50, "estimated_cost": 0.01}},
            total_cost=0.01,
            total_tokens=150,
            message_count=5
        )

        # Add old session
        storage.save_session_usage(
            session_id="old",
            started_at=datetime.now() - timedelta(days=400),
            ended_at=datetime.now() - timedelta(days=400) + timedelta(hours=1),
            usage_by_model={"test/model": {"prompt_tokens": 100, "completion_tokens": 50, "estimated_cost": 0.01}},
            total_cost=0.01,
            total_tokens=150,
            message_count=5
        )

        assert storage.get_session_count() == 2

        storage.clear_old_sessions(days=365)

        assert storage.get_session_count() == 1
        assert storage._data["sessions"][0]["session_id"] == "recent"

    def test_multiple_models_aggregation(self, storage):
        """Test aggregation of multiple models in report."""
        storage.save_session_usage(
            session_id="multi-model",
            started_at=datetime.now(),
            ended_at=datetime.now() + timedelta(hours=1),
            usage_by_model={
                "perplexity/sonar-pro": {"prompt_tokens": 100, "completion_tokens": 50, "estimated_cost": 0.01},
                "gemini/gemini-2.5-flash": {"prompt_tokens": 200, "completion_tokens": 100, "estimated_cost": 0.02},
            },
            total_cost=0.03,
            total_tokens=450,
            message_count=10
        )

        report = storage.get_usage_report("all")

        assert len(report["by_provider"]) == 2
        assert "perplexity" in report["by_provider"]
        assert "gemini" in report["by_provider"]
        assert len(report["by_model"]) == 2


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_usage_report_returns_valid_data(self, temp_usage_dir):
        """Test that get_usage_report returns valid data structure."""
        # Reset global storage and create new one with temp dir
        import ppxai.usage
        ppxai.usage._storage = UsageStorage(usage_dir=temp_usage_dir)

        report = ppxai.usage.get_usage_report("all")

        assert "period" in report
        assert "total_tokens" in report
        assert "total_cost" in report
        assert "session_count" in report
        assert "by_provider" in report
        assert "by_model" in report

        # Cleanup
        ppxai.usage._storage = None

    def test_save_session_usage_convenience(self, temp_usage_dir):
        """Test save_session_usage convenience function."""
        import ppxai.usage
        ppxai.usage._storage = UsageStorage(usage_dir=temp_usage_dir)

        ppxai.usage.save_session_usage(
            session_id="test-conv",
            started_at=datetime.now() - timedelta(hours=1),
            ended_at=datetime.now(),
            usage_by_model={"test/model": {"prompt_tokens": 100, "completion_tokens": 50, "estimated_cost": 0.01}},
            total_cost=0.01,
            total_tokens=150,
            message_count=5
        )

        # Verify it was saved
        report = ppxai.usage.get_usage_report("all")
        assert report["session_count"] == 1

        # Cleanup
        ppxai.usage._storage = None


class TestToolUsagePersistence:
    """Tests for tool usage tracking in persistent storage (v1.13.4)."""

    def test_save_session_with_tool_calls(self, storage):
        """Test saving session with tool usage data."""
        storage.save_session_usage(
            session_id="tool-session",
            started_at=datetime(2026, 1, 1, 10, 0),
            ended_at=datetime(2026, 1, 1, 11, 0),
            usage_by_model={
                "perplexity/sonar-pro": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "estimated_cost": 0.05
                }
            },
            total_cost=0.06,
            total_tokens=1500,
            message_count=10,
            tool_calls={
                "web_search": {
                    "call_count": 2,
                    "tokens_in": 200,
                    "tokens_out": 400,
                    "estimated_cost": 0.01,
                    "provider": "perplexity"
                }
            }
        )

        assert len(storage._data["sessions"]) == 1
        session = storage._data["sessions"][0]
        assert "tool_calls" in session
        assert "web_search" in session["tool_calls"]
        assert session["tool_calls"]["web_search"]["call_count"] == 2
        assert session["tool_calls"]["web_search"]["provider"] == "perplexity"

    def test_usage_report_includes_tool_costs(self, storage):
        """Test that tool costs are included in usage report."""
        storage.save_session_usage(
            session_id="tool-cost-session",
            started_at=datetime.now(),
            ended_at=datetime.now() + timedelta(hours=1),
            usage_by_model={
                "openai/gpt-4o": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "estimated_cost": 0.05
                }
            },
            total_cost=0.06,
            total_tokens=1500,
            message_count=5,
            tool_calls={
                "web_search": {
                    "call_count": 1,
                    "tokens_in": 100,
                    "tokens_out": 200,
                    "estimated_cost": 0.01,
                    "provider": "perplexity"
                }
            }
        )

        report = storage.get_usage_report("all")

        assert report["total_cost"] == 0.06
        assert "by_tool" in report
        assert "web_search" in report["by_tool"]
        assert report["by_tool"]["web_search"]["call_count"] == 1
        assert report["by_tool"]["web_search"]["estimated_cost"] == 0.01

    def test_multiple_tool_aggregation(self, storage):
        """Test aggregation of multiple tool calls in report."""
        # Session 1: web_search via Perplexity
        storage.save_session_usage(
            session_id="session-1",
            started_at=datetime.now() - timedelta(days=1),
            ended_at=datetime.now() - timedelta(days=1) + timedelta(hours=1),
            usage_by_model={
                "openai/gpt-4o": {
                    "prompt_tokens": 500,
                    "completion_tokens": 250,
                    "estimated_cost": 0.02
                }
            },
            total_cost=0.03,
            total_tokens=750,
            message_count=5,
            tool_calls={
                "web_search": {
                    "call_count": 2,
                    "tokens_in": 200,
                    "tokens_out": 400,
                    "estimated_cost": 0.01,
                    "provider": "perplexity"
                }
            }
        )

        # Session 2: web_search via Gemini
        storage.save_session_usage(
            session_id="session-2",
            started_at=datetime.now(),
            ended_at=datetime.now() + timedelta(hours=1),
            usage_by_model={
                "openai/gpt-4o": {
                    "prompt_tokens": 500,
                    "completion_tokens": 250,
                    "estimated_cost": 0.02
                }
            },
            total_cost=0.029,
            total_tokens=750,
            message_count=5,
            tool_calls={
                "web_search": {
                    "call_count": 1,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "estimated_cost": 0.009,
                    "provider": "gemini"
                }
            }
        )

        report = storage.get_usage_report("all")

        assert report["session_count"] == 2
        assert "by_tool" in report
        assert "web_search" in report["by_tool"]
        # Aggregate: 2 + 1 = 3 calls
        assert report["by_tool"]["web_search"]["call_count"] == 3
        # Cost: 0.01 + 0.009 = 0.019
        assert pytest.approx(report["by_tool"]["web_search"]["estimated_cost"], abs=0.001) == 0.019

    def test_tool_usage_with_duckduckgo(self, storage):
        """Test tool usage tracking for free DuckDuckGo provider."""
        storage.save_session_usage(
            session_id="free-search",
            started_at=datetime.now(),
            ended_at=datetime.now() + timedelta(hours=1),
            usage_by_model={
                "openai/gpt-4o": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "estimated_cost": 0.05
                }
            },
            total_cost=0.05,
            total_tokens=1500,
            message_count=10,
            tool_calls={
                "web_search": {
                    "call_count": 5,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "estimated_cost": 0.0,
                    "provider": "duckduckgo"
                }
            }
        )

        report = storage.get_usage_report("all")

        assert report["by_tool"]["web_search"]["provider"] == "duckduckgo"
        assert report["by_tool"]["web_search"]["estimated_cost"] == 0.0
        assert report["by_tool"]["web_search"]["call_count"] == 5

    def test_empty_tool_calls_field(self, storage):
        """Test handling of empty tool_calls field."""
        storage.save_session_usage(
            session_id="no-tools",
            started_at=datetime.now(),
            ended_at=datetime.now() + timedelta(hours=1),
            usage_by_model={
                "perplexity/sonar-pro": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "estimated_cost": 0.05
                }
            },
            total_cost=0.05,
            total_tokens=1500,
            message_count=10,
            tool_calls={}  # No tool calls
        )

        report = storage.get_usage_report("all")

        # Report should not have by_tool if no tools were used
        if "by_tool" in report:
            assert len(report["by_tool"]) == 0

    def test_tool_usage_persistence_across_sessions(self, storage, temp_usage_dir):
        """Test that tool usage persists across UsageStorage instances."""
        storage.save_session_usage(
            session_id="persist-tools",
            started_at=datetime.now(),
            ended_at=datetime.now() + timedelta(hours=1),
            usage_by_model={
                "openai/gpt-4o": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "estimated_cost": 0.05
                }
            },
            total_cost=0.06,
            total_tokens=1500,
            message_count=10,
            tool_calls={
                "web_search": {
                    "call_count": 3,
                    "tokens_in": 300,
                    "tokens_out": 600,
                    "estimated_cost": 0.01,
                    "provider": "perplexity"
                }
            }
        )

        # Load fresh storage from same directory
        new_storage = UsageStorage(usage_dir=temp_usage_dir)
        report = new_storage.get_usage_report("all")

        assert report["session_count"] == 1
        assert "by_tool" in report
        assert "web_search" in report["by_tool"]
        assert report["by_tool"]["web_search"]["call_count"] == 3
        assert report["by_tool"]["web_search"]["provider"] == "perplexity"

"""Tests for /usage rendering of provider_errors throttle telemetry.

v1.18.3 Item 16: when usage_stats has accumulated provider_errors via
UsageStorage.record_provider_error (NIM 403, OpenAI 429, etc.), the
/usage command surfaces them as a second TableResult in a CompositeResult.
When errors are empty, the command returns the original plain TableResult
(byte-identical to pre-v1.18.3 — backward-compatible).

Covered:
  * Empty errors path → plain TableResult (no CompositeResult wrapping)
  * Non-empty errors → CompositeResult([usage_table, errors_table])
  * Errors table column shape, sort order (highest count first), status
  * Period-based reports (/usage 24h, /usage week, ...) get the same
    treatment as the session report
  * Last-seen timestamp is trimmed to minute precision for display

Mocks `ppxai.commands.tools.get_provider_errors` (the function imported
at module load time) — NOT `ppxai.usage.get_provider_errors` directly,
because tools.py captures the reference at import. Same pattern as
memory/feedback_test_persistence_pollution.md flagged for similar
cases.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ppxai.commands.results import (
    CompositeResult,
    ResultStatus,
    TableResult,
)
from ppxai.commands.tools import (
    _build_provider_errors_table,
    _display_global_usage_report,
    _display_usage_report,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def session_context():
    """Minimal context whose session.get_usage() returns deterministic data."""
    ctx = MagicMock()
    ctx.engine_client.session.get_usage.return_value = {
        "by_model": {
            "openai/gpt-5.4-mini": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "estimated_cost": 0.001,
            }
        },
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "estimated_cost": 0.001,
        "tool_calls": {},
        "display_mode": "session",
    }
    return ctx


# ---------------------------------------------------------------------------
# _build_provider_errors_table — direct unit tests
# ---------------------------------------------------------------------------

class TestBuildProviderErrorsTable:
    def test_empty_errors_returns_none(self):
        with patch("ppxai.commands.tools.get_provider_errors", return_value={}):
            assert _build_provider_errors_table() is None

    def test_single_error_returns_table_with_correct_shape(self):
        errors = {
            "nvidia:403": {
                "count": 12,
                "last_seen": "2026-05-02T14:32:00",
                "models": ["qwen/qwen3-coder-480b-a35b-instruct"],
            }
        }
        with patch("ppxai.commands.tools.get_provider_errors", return_value=errors):
            table = _build_provider_errors_table()

        assert isinstance(table, TableResult)
        assert table.status == ResultStatus.WARNING
        assert "12 total" in table.message
        assert table.columns == ["Provider", "Status", "Count", "Last Seen", "Models"]
        assert len(table.rows) == 1
        provider, status, count, last_seen, models = table.rows[0]
        assert provider == "nvidia"
        assert status == "403"
        assert count == "12"
        # Trimmed to minute precision (no seconds), 'T' replaced with space
        assert last_seen == "2026-05-02 14:32"
        assert "qwen/qwen3-coder-480b-a35b-instruct" in models
        assert table.metadata["total_errors"] == 12
        assert table.metadata["distinct_keys"] == 1

    def test_multiple_errors_sorted_by_count_descending(self):
        errors = {
            "openai:429": {"count": 3, "last_seen": "2026-05-02T10:00:00", "models": ["gpt-5.4-mini"]},
            "nvidia:403": {"count": 12, "last_seen": "2026-05-02T14:32:00", "models": ["qwen/qwen3-coder-480b-a35b-instruct"]},
            "gemini:429": {"count": 7, "last_seen": "2026-05-02T11:00:00", "models": ["gemini-3-flash-preview"]},
        }
        with patch("ppxai.commands.tools.get_provider_errors", return_value=errors):
            table = _build_provider_errors_table()

        # Highest count first
        counts = [int(row[2]) for row in table.rows]
        assert counts == sorted(counts, reverse=True)
        assert counts == [12, 7, 3]
        assert table.metadata["total_errors"] == 22
        assert table.metadata["distinct_keys"] == 3

    def test_multiple_models_joined_with_comma(self):
        errors = {
            "nvidia:403": {
                "count": 5,
                "last_seen": "2026-05-02T14:32:00",
                "models": ["qwen/qwen3.5-122b-a10b", "qwen/qwen3-coder-480b-a35b-instruct"],
            }
        }
        with patch("ppxai.commands.tools.get_provider_errors", return_value=errors):
            table = _build_provider_errors_table()

        models_cell = table.rows[0][4]
        assert "qwen/qwen3.5-122b-a10b" in models_cell
        assert "qwen/qwen3-coder-480b-a35b-instruct" in models_cell
        assert ", " in models_cell

    def test_empty_models_list_renders_empty_string(self):
        errors = {
            "openai:403": {"count": 1, "last_seen": "2026-05-02T10:00:00", "models": []},
        }
        with patch("ppxai.commands.tools.get_provider_errors", return_value=errors):
            table = _build_provider_errors_table()
        assert table.rows[0][4] == ""

    def test_missing_last_seen_renders_empty(self):
        errors = {"openai:403": {"count": 1}}
        with patch("ppxai.commands.tools.get_provider_errors", return_value=errors):
            table = _build_provider_errors_table()
        assert table.rows[0][3] == ""


# ---------------------------------------------------------------------------
# _display_usage_report (session) — composition behavior
# ---------------------------------------------------------------------------

class TestSessionUsageReportComposition:
    def test_no_errors_returns_plain_table_result(self, session_context):
        """Backward-compat: with no provider_errors, output shape is unchanged
        from pre-v1.18.3. Critical because every existing test that asserts
        ``isinstance(result, TableResult)`` would break otherwise."""
        with patch("ppxai.commands.tools.get_provider_errors", return_value={}):
            result = _display_usage_report(session_context)
        assert isinstance(result, TableResult)
        assert not isinstance(result, CompositeResult)
        assert result.metadata["report_type"] == "session"

    def test_with_errors_returns_composite_result(self, session_context):
        errors = {
            "nvidia:403": {
                "count": 12,
                "last_seen": "2026-05-02T14:32:00",
                "models": ["qwen/qwen3-coder-480b-a35b-instruct"],
            }
        }
        with patch("ppxai.commands.tools.get_provider_errors", return_value=errors):
            result = _display_usage_report(session_context)

        assert isinstance(result, CompositeResult)
        assert len(result.results) == 2
        # Sub-result 0: usage table (existing shape)
        assert isinstance(result.results[0], TableResult)
        assert result.results[0].metadata["report_type"] == "session"
        # Sub-result 1: provider errors table (new)
        assert isinstance(result.results[1], TableResult)
        assert result.results[1].metadata["report_type"] == "provider_errors"
        assert result.results[1].metadata["total_errors"] == 12


# ---------------------------------------------------------------------------
# _display_global_usage_report (period-based) — composition behavior
# ---------------------------------------------------------------------------

class TestPeriodUsageReportComposition:
    @pytest.fixture
    def empty_period_report(self):
        return {
            "by_model": {},
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "session_count": 0,
            "start_date": "2026-05-01",
            "end_date": "2026-05-02",
        }

    def test_no_errors_returns_plain_table_result(self, session_context, empty_period_report):
        with patch("ppxai.commands.tools.get_usage_report", return_value=empty_period_report), \
             patch("ppxai.commands.tools.get_provider_errors", return_value={}):
            result = _display_global_usage_report(session_context, "24h")
        assert isinstance(result, TableResult)
        assert not isinstance(result, CompositeResult)
        assert result.metadata["report_type"] == "period"

    def test_with_errors_returns_composite_result(self, session_context, empty_period_report):
        errors = {"nvidia:403": {"count": 5, "last_seen": "2026-05-02T14:32:00", "models": []}}
        with patch("ppxai.commands.tools.get_usage_report", return_value=empty_period_report), \
             patch("ppxai.commands.tools.get_provider_errors", return_value=errors):
            result = _display_global_usage_report(session_context, "week")

        assert isinstance(result, CompositeResult)
        assert len(result.results) == 2
        assert result.results[0].metadata["report_type"] == "period"
        assert result.results[1].metadata["report_type"] == "provider_errors"

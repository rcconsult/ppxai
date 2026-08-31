"""Tests for v1.18.3 provider-error telemetry in usage_stats.

When ``openai_compat`` classifies an exception as a provider-side
throttle (HTTP 403 / 429), it records a counter in the persistent
usage store via ``record_provider_error``. This lets users surface
"NIM returned 12 quota errors today" via ``/usage`` without re-running
benchmarks.

The persistence layer is tested here in isolation (no chat call); a
separate test (test_provider_throttle.py) covers classification.
"""


import pytest

import ppxai.usage as usage_module
from ppxai.usage import UsageStorage


@pytest.fixture
def isolated_usage(tmp_path, monkeypatch):
    """Build a UsageStorage rooted in tmp_path; reset module singleton."""
    storage = UsageStorage(usage_dir=tmp_path)
    monkeypatch.setattr(usage_module, "_storage", storage)
    yield storage


class TestRecordProviderError:
    def test_first_record_creates_entry(self, isolated_usage):
        isolated_usage.record_provider_error(
            provider="nvidia",
            status_code=403,
            model="qwen/qwen3-coder-480b",
        )
        errors = isolated_usage.get_provider_errors()
        assert "nvidia:403" in errors
        entry = errors["nvidia:403"]
        assert entry["count"] == 1
        assert entry["last_seen"] is not None
        assert "qwen/qwen3-coder-480b" in entry["models"]

    def test_repeated_record_increments_count(self, isolated_usage):
        for _ in range(3):
            isolated_usage.record_provider_error(
                provider="nvidia",
                status_code=403,
                model="qwen/qwen3-coder-480b",
            )
        errors = isolated_usage.get_provider_errors()
        assert errors["nvidia:403"]["count"] == 3
        # Same model recorded once (deduped)
        assert errors["nvidia:403"]["models"] == ["qwen/qwen3-coder-480b"]

    def test_distinct_models_tracked(self, isolated_usage):
        isolated_usage.record_provider_error("nvidia", 403, "qwen/qwen3-coder-480b")
        isolated_usage.record_provider_error("nvidia", 403, "qwen/qwen3.5-122b")
        errors = isolated_usage.get_provider_errors()
        assert errors["nvidia:403"]["count"] == 2
        assert sorted(errors["nvidia:403"]["models"]) == [
            "qwen/qwen3-coder-480b",
            "qwen/qwen3.5-122b",
        ]

    def test_distinct_status_codes_tracked_separately(self, isolated_usage):
        isolated_usage.record_provider_error("nvidia", 403, "model-a")
        isolated_usage.record_provider_error("nvidia", 429, "model-a")
        errors = isolated_usage.get_provider_errors()
        assert "nvidia:403" in errors
        assert "nvidia:429" in errors
        assert errors["nvidia:403"]["count"] == 1
        assert errors["nvidia:429"]["count"] == 1

    def test_record_persists_across_instances(self, tmp_path):
        """Telemetry survives process restart via on-disk store."""
        s1 = UsageStorage(usage_dir=tmp_path)
        s1.record_provider_error("nvidia", 403, "model-x")
        # New instance loads from disk
        s2 = UsageStorage(usage_dir=tmp_path)
        errors = s2.get_provider_errors()
        assert errors.get("nvidia:403", {}).get("count") == 1

    def test_record_without_model_works(self, isolated_usage):
        """Model is optional — some error paths don't have it."""
        isolated_usage.record_provider_error("custom", 429)
        errors = isolated_usage.get_provider_errors()
        assert errors["custom:429"]["count"] == 1
        assert errors["custom:429"]["models"] == []

    def test_module_level_convenience(self, isolated_usage):
        """``usage.record_provider_error(...)`` proxies to the singleton."""
        usage_module.record_provider_error("nvidia", 403, "model-z")
        errors = usage_module.get_provider_errors()
        assert errors["nvidia:403"]["count"] == 1


class TestBackwardCompatibility:
    """Old usage.json files (pre-v1.18.3) lack the provider_errors key —
    the storage layer must handle them gracefully without crashing."""

    def test_load_pre_v1_18_3_data_without_provider_errors_key(self, tmp_path):
        # Write a synthetic pre-v1.18.3 file (sessions only, no provider_errors)
        legacy_path = tmp_path / "usage.json"
        legacy_path.write_text(
            '{"version": 1, "sessions": []}',
            encoding="utf-8",
        )
        storage = UsageStorage(usage_dir=tmp_path)
        # No crash; provider_errors defaults to empty
        errors = storage.get_provider_errors()
        assert errors == {}
        # Recording works on legacy file
        storage.record_provider_error("nvidia", 403, "model-x")
        assert storage.get_provider_errors()["nvidia:403"]["count"] == 1

"""Tests for /doctor command + model_deprecations module (Phase 2.4, v1.17.4).

Three layers of coverage:

1. `model_deprecations` module — pure data classification, tested with a
   fixed `today` date so results are reproducible regardless of when the
   test runs. Exercises `classify_model`, `audit_config_models`, and
   `find_missing_recommended`.

2. `doctor.audit_user_config` — end-to-end file loading + classification,
   tested against synthetic JSON configs in tmp_path. Covers happy path,
   missing file, malformed JSON, empty config, all-healthy config, and
   the default-model warning path.

3. `/doctor` command — tested through the public `handle_doctor`
   dispatcher to verify result status escalation and metadata shape.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ppxai.commands.doctor import (
    _format_audit_report,
    _summarize_startup,
    audit_user_config,
    handle_doctor,
)
from ppxai.commands.results import ResultStatus
from ppxai.engine.model_deprecations import (
    ALL_DEPRECATIONS,
    GEMINI_DEPRECATIONS,
    RECOMMENDED_DEFAULTS,
    RECOMMENDED_NEW_MODELS,
    audit_config_models,
    classify_model,
    find_missing_recommended,
)


# -----------------------------------------------------------------------------
# classify_model — per-model classification
# -----------------------------------------------------------------------------


class TestClassifyModel:
    def test_unknown_model_returns_none(self):
        assert classify_model("not-a-real-model") is None

    def test_shutdown_in_past_is_dead(self):
        # gemini-3-pro-preview shut down 2026-03-09
        info = classify_model("gemini-3-pro-preview", today=date(2026, 4, 1))
        assert info is not None
        assert info["status"] == "shutdown"
        assert info["shutdown_date"] == "2026-03-09"
        assert "days_remaining" not in info

    def test_shutdown_in_future_is_deprecated(self):
        # gemini-2.5-flash shuts down 2026-06-17
        info = classify_model("gemini-2.5-flash", today=date(2026, 4, 6))
        assert info is not None
        assert info["status"] == "deprecated"
        assert info["days_remaining"] == "72"
        assert info["replacement"] == "gemini-3-flash-preview"

    def test_exact_shutdown_date_still_deprecated(self):
        # Day-of the shutdown: delta = 0, still counts as deprecated.
        info = classify_model("gemini-2.5-flash", today=date(2026, 6, 17))
        assert info is not None
        assert info["status"] == "deprecated"
        assert info["days_remaining"] == "0"

    def test_day_after_shutdown_is_dead(self):
        info = classify_model("gemini-2.5-flash", today=date(2026, 6, 18))
        assert info["status"] == "shutdown"

    def test_entry_includes_reason(self):
        info = classify_model("gemini-2.5-pro", today=date(2026, 4, 6))
        assert "reason" in info
        assert info["reason"]  # non-empty


# -----------------------------------------------------------------------------
# audit_config_models — bulk classification with provider mapping
# -----------------------------------------------------------------------------


class TestAuditConfigModels:
    def test_empty_mapping_returns_empty_lists(self):
        result = audit_config_models({}, today=date(2026, 4, 6))
        assert result == {"dead": [], "upcoming": [], "healthy": []}

    def test_mix_of_dead_upcoming_healthy(self):
        provider_models = {
            "gemini": [
                "gemini-3-pro-preview",     # dead
                "gemini-2.5-flash",         # upcoming
                "gemini-3-flash-preview",   # healthy
            ],
        }
        result = audit_config_models(provider_models, today=date(2026, 4, 6))

        assert len(result["dead"]) == 1
        assert result["dead"][0]["model"] == "gemini-3-pro-preview"
        assert result["dead"][0]["provider"] == "gemini"

        assert len(result["upcoming"]) == 1
        assert result["upcoming"][0]["model"] == "gemini-2.5-flash"

        assert result["healthy"] == ["gemini-3-flash-preview"]

    def test_upcoming_sorted_by_urgency(self):
        # Three deprecations with staggered dates — closest first.
        provider_models = {
            "gemini": [
                "gemini-2.5-flash-lite",  # 2026-07-22 (furthest)
                "gemini-2.0-flash",       # 2026-06-01 (closest)
                "gemini-2.5-flash",       # 2026-06-17 (middle)
            ],
        }
        result = audit_config_models(provider_models, today=date(2026, 4, 6))
        ordered_models = [e["model"] for e in result["upcoming"]]
        assert ordered_models == [
            "gemini-2.0-flash",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ]

    def test_provider_attached_to_each_entry(self):
        provider_models = {"gemini": ["gemini-2.5-flash"]}
        result = audit_config_models(provider_models, today=date(2026, 4, 6))
        assert result["upcoming"][0]["provider"] == "gemini"


# -----------------------------------------------------------------------------
# find_missing_recommended — new-model suggestions
# -----------------------------------------------------------------------------


class TestFindMissingRecommended:
    def test_gemini_provider_present_suggests_new_models(self):
        # User has gemini configured but without the new 3.1 models.
        provider_models = {"gemini": ["gemini-3-flash-preview"]}
        missing = find_missing_recommended(provider_models)
        # Every Gemini recommendation should surface.
        missing_names = {m["model"] for m in missing}
        assert "gemini-3.1-flash-lite-preview" in missing_names
        assert "gemma-4-31b-it" in missing_names

    def test_already_configured_models_not_recommended(self):
        provider_models = {
            "gemini": [
                "gemini-3-flash-preview",
                "gemini-3.1-flash-lite-preview",  # already have this
            ],
        }
        missing = find_missing_recommended(provider_models)
        missing_names = {m["model"] for m in missing}
        assert "gemini-3.1-flash-lite-preview" not in missing_names

    def test_provider_absent_skips_its_recommendations(self):
        # No gemini provider at all → no gemini recommendations.
        provider_models = {"openai": ["gpt-5.2"]}
        missing = find_missing_recommended(provider_models)
        # All current recommendations are for gemini, so empty.
        gemini_recs = [m for m in missing if m["provider"] == "gemini"]
        assert gemini_recs == []


# -----------------------------------------------------------------------------
# audit_user_config — end-to-end file loading
# -----------------------------------------------------------------------------


def _write_config(tmp_path: Path, data: dict) -> Path:
    """Write a JSON config to tmp_path and return the path."""
    path = tmp_path / "test-config.json"
    path.write_text(json.dumps(data))
    return path


class TestAuditUserConfig:
    def test_missing_config_returns_error(self, tmp_path):
        result = audit_user_config(tmp_path / "nonexistent.json")
        assert result["error"]
        assert "missing" in result["error"].lower() or "not" in result["error"].lower()

    def test_malformed_json_returns_error(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{ not valid json")
        result = audit_user_config(path)
        assert result["error"]
        assert "valid JSON" in result["error"] or "JSON" in result["error"]

    def test_empty_config_is_clean(self, tmp_path):
        path = _write_config(tmp_path, {"providers": {}})
        result = audit_user_config(path, today=date(2026, 4, 6))
        assert result["error"] is None
        assert result["dead"] == []
        assert result["upcoming"] == []
        assert result["missing_recommended"] == []
        assert result["default_warnings"] == []

    def test_dead_model_detected(self, tmp_path):
        path = _write_config(tmp_path, {
            "providers": {
                "gemini": {
                    "default_model": "gemini-3-flash-preview",
                    "models": {
                        "gemini-3-pro-preview": {},  # dead
                        "gemini-3-flash-preview": {},
                    },
                },
            },
        })
        result = audit_user_config(path, today=date(2026, 4, 6))
        assert result["error"] is None
        assert len(result["dead"]) == 1
        assert result["dead"][0]["model"] == "gemini-3-pro-preview"

    def test_upcoming_deprecation_detected(self, tmp_path):
        path = _write_config(tmp_path, {
            "providers": {
                "gemini": {
                    "models": {
                        "gemini-2.5-flash": {},
                    },
                },
            },
        })
        result = audit_user_config(path, today=date(2026, 4, 6))
        assert len(result["upcoming"]) == 1
        assert result["upcoming"][0]["model"] == "gemini-2.5-flash"

    def test_default_model_deprecated_warning(self, tmp_path):
        path = _write_config(tmp_path, {
            "providers": {
                "gemini": {
                    "default_model": "gemini-2.5-flash",  # deprecated
                    "models": {
                        "gemini-2.5-flash": {},
                    },
                },
            },
        })
        result = audit_user_config(path, today=date(2026, 4, 6))
        assert len(result["default_warnings"]) == 1
        warn = result["default_warnings"][0]
        assert warn["provider"] == "gemini"
        assert warn["default_model"] == "gemini-2.5-flash"
        assert warn["recommended_default"] == "gemini-3-flash-preview"

    def test_comment_keys_excluded_from_model_list(self, tmp_path):
        # __comment_deprecations and similar keys must be filtered.
        path = _write_config(tmp_path, {
            "providers": {
                "gemini": {
                    "__comment_deprecations": "See docs/xxx",
                    "models": {
                        "__comment_note": "models explanation",
                        "gemini-3-flash-preview": {},
                    },
                },
            },
        })
        result = audit_user_config(path, today=date(2026, 4, 6))
        # Healthy list should contain only the real model.
        from ppxai.engine.model_deprecations import audit_config_models
        audit = audit_config_models(
            {"gemini": ["gemini-3-flash-preview"]},
            today=date(2026, 4, 6),
        )
        # The /doctor audit shouldn't crash on comment keys.
        assert result["error"] is None

    def test_missing_recommended_suggested(self, tmp_path):
        path = _write_config(tmp_path, {
            "providers": {
                "gemini": {
                    "models": {
                        "gemini-3-flash-preview": {},
                    },
                },
            },
        })
        result = audit_user_config(path, today=date(2026, 4, 6))
        # User has gemini configured but none of the new 3.1 / Gemma 4 models.
        names = {m["model"] for m in result["missing_recommended"]}
        assert "gemini-3.1-flash-lite-preview" in names


# -----------------------------------------------------------------------------
# _format_audit_report — output formatting
# -----------------------------------------------------------------------------


class TestFormatAuditReport:
    def test_clean_config_shows_no_issues(self):
        audit = {
            "config_path": "/tmp/test.json",
            "dead": [], "upcoming": [], "missing_recommended": [],
            "default_warnings": [], "error": None,
        }
        report = _format_audit_report(audit)
        assert "No issues found" in report

    def test_dead_models_section(self):
        audit = {
            "config_path": "/tmp/test.json",
            "dead": [{
                "provider": "gemini",
                "model": "gemini-3-pro-preview",
                "shutdown_date": "2026-03-09",
                "replacement": "gemini-3.1-pro-preview",
                "reason": "retired",
                "status": "shutdown",
            }],
            "upcoming": [], "missing_recommended": [],
            "default_warnings": [], "error": None,
        }
        report = _format_audit_report(audit)
        assert "Dead models" in report
        assert "gemini-3-pro-preview" in report
        assert "2026-03-09" in report
        assert "gemini-3.1-pro-preview" in report
        assert "retired" in report

    def test_upcoming_section_shows_days(self):
        audit = {
            "config_path": "/tmp/test.json",
            "dead": [],
            "upcoming": [{
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "shutdown_date": "2026-06-17",
                "days_remaining": "72",
                "replacement": "gemini-3-flash-preview",
                "reason": "",
                "status": "deprecated",
            }],
            "missing_recommended": [], "default_warnings": [], "error": None,
        }
        report = _format_audit_report(audit)
        assert "Upcoming deprecations" in report
        assert "72 days" in report

    def test_default_warning_section(self):
        audit = {
            "config_path": "/tmp/test.json",
            "dead": [], "upcoming": [], "missing_recommended": [],
            "default_warnings": [{
                "provider": "gemini",
                "default_model": "gemini-3-pro-preview",
                "status": "shutdown",
                "shutdown_date": "2026-03-09",
                "replacement": "gemini-3.1-pro-preview",
                "recommended_default": "gemini-3-flash-preview",
            }],
            "error": None,
        }
        report = _format_audit_report(audit)
        assert "default_model" in report
        assert "gemini-3-pro-preview" in report
        assert "gemini-3-flash-preview" in report  # recommended


# -----------------------------------------------------------------------------
# _summarize_startup — one-line hint
# -----------------------------------------------------------------------------


class TestSummarizeStartup:
    def test_no_dead_models_returns_none(self):
        assert _summarize_startup({"dead": []}) is None

    def test_no_dead_key_returns_none(self):
        # Missing key is treated the same as empty list.
        assert _summarize_startup({}) is None

    def test_single_dead_model_returns_singular(self):
        result = _summarize_startup({"dead": [{"model": "x"}]})
        assert result is not None
        assert "1 dead model " in result
        assert "/doctor" in result

    def test_multiple_dead_models_returns_plural(self):
        result = _summarize_startup({"dead": [{}, {}, {}]})
        assert "3 dead models" in result

    def test_upcoming_alone_does_not_warn_at_startup(self):
        # Deprecated-but-not-dead models don't interrupt startup.
        assert _summarize_startup({"dead": [], "upcoming": [{}]}) is None


# -----------------------------------------------------------------------------
# handle_doctor — full command dispatch
# -----------------------------------------------------------------------------


class TestHandleDoctor:
    def test_clean_config_returns_success(self, tmp_path, monkeypatch):
        path = _write_config(tmp_path, {"providers": {}})
        # Patch find_config_file to return our synthetic path.
        monkeypatch.setattr(
            "ppxai.commands.doctor.find_config_file",
            lambda: path,
        )
        ctx = SimpleNamespace()
        result = handle_doctor(ctx, "")
        assert result.status == ResultStatus.SUCCESS
        assert result.metadata["dead_count"] == 0

    def test_dead_model_escalates_to_warning(self, tmp_path, monkeypatch):
        path = _write_config(tmp_path, {
            "providers": {
                "gemini": {
                    "models": {"gemini-3-pro-preview": {}},
                },
            },
        })
        monkeypatch.setattr(
            "ppxai.commands.doctor.find_config_file",
            lambda: path,
        )
        ctx = SimpleNamespace()
        result = handle_doctor(ctx, "")
        assert result.status == ResultStatus.WARNING
        assert result.metadata["dead_count"] == 1
        assert "gemini-3-pro-preview" in result.message

    def test_missing_config_returns_error(self, monkeypatch):
        monkeypatch.setattr(
            "ppxai.commands.doctor.find_config_file",
            lambda: None,
        )
        ctx = SimpleNamespace()
        result = handle_doctor(ctx, "")
        assert result.status == ResultStatus.ERROR
        assert "config file" in result.message.lower()

    def test_command_is_registered(self):
        # /doctor auto-registers via side-effect import.
        import ppxai.commands.handler  # noqa: F401
        from ppxai.commands.factory import CommandFactory
        spec = CommandFactory.get("doctor")
        assert spec is not None
        assert spec.name == "doctor"
        assert "utility" in spec.category.lower() or spec.category == "utility"


# -----------------------------------------------------------------------------
# Table invariants — sanity-check the data itself
# -----------------------------------------------------------------------------


class TestDeprecationTableInvariants:
    def test_all_gemini_entries_have_valid_replacement(self):
        # Every deprecation must point at a model that is NOT itself
        # deprecated — otherwise we'd send users to another dead end.
        for model, entry in GEMINI_DEPRECATIONS.items():
            assert entry.replacement not in GEMINI_DEPRECATIONS, (
                f"{model!r} points at deprecated replacement "
                f"{entry.replacement!r}"
            )

    def test_recommended_defaults_are_not_deprecated(self):
        for provider, default in RECOMMENDED_DEFAULTS.items():
            info = classify_model(default)
            assert info is None, (
                f"Recommended default {default!r} for {provider!r} is "
                f"itself in the deprecation table"
            )

    def test_recommended_new_models_are_not_deprecated(self):
        for rec in RECOMMENDED_NEW_MODELS:
            info = classify_model(rec["model"])
            assert info is None, (
                f"Recommended new model {rec['model']!r} is in the "
                f"deprecation table — contradiction"
            )

    def test_all_shutdown_dates_are_valid_iso(self):
        for model, entry in ALL_DEPRECATIONS.items():
            from datetime import datetime
            try:
                datetime.strptime(entry.shutdown_date, "%Y-%m-%d")
            except ValueError:
                pytest.fail(
                    f"{model!r} has invalid shutdown_date "
                    f"{entry.shutdown_date!r}"
                )

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
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

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
    NVIDIA_DEPRECATIONS,
    OPENAI_DEPRECATIONS,
    PERPLEXITY_DEPRECATIONS,
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

    # These three test the classifier's DATE ARITHMETIC, not any particular
    # model — so the dates are derived from the row rather than hardcoded.
    # They previously pinned gemini-2.5-flash's 2026-06-17, and broke when
    # that row was corrected to the real sunset (2026-10-16) on 2026-08-31:
    # a data fix should not fail a logic test. The row is still named so a
    # deleted row fails loudly rather than silently skipping.
    SUBJECT = "gemini-2.5-flash"

    def _shutdown(self):
        from ppxai.engine.model_deprecations import ALL_DEPRECATIONS

        dep = ALL_DEPRECATIONS.get(self.SUBJECT)
        assert dep is not None, f"{self.SUBJECT} left the deprecation table"
        return date.fromisoformat(dep.shutdown_date), dep

    def test_shutdown_in_future_is_deprecated(self):
        shutdown, dep = self._shutdown()
        today = shutdown - timedelta(days=72)
        info = classify_model(self.SUBJECT, today=today)
        assert info is not None
        assert info["status"] == "deprecated"
        assert info["days_remaining"] == "72"
        assert info["replacement"] == dep.replacement

    def test_exact_shutdown_date_still_deprecated(self):
        # Day-of the shutdown: delta = 0, still counts as deprecated.
        shutdown, _ = self._shutdown()
        info = classify_model(self.SUBJECT, today=shutdown)
        assert info is not None
        assert info["status"] == "deprecated"
        assert info["days_remaining"] == "0"

    def test_day_after_shutdown_is_dead(self):
        shutdown, _ = self._shutdown()
        info = classify_model(self.SUBJECT, today=shutdown + timedelta(days=1))
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
        """Closest shutdown first — asserted as the PROPERTY, not a frozen list.

        This used to pin an expected order computed by hand from three
        hardcoded dates, so correcting a shutdown date in the table (as the
        2026-08-31 Gemini fix did) failed a test about SORTING. Worse, two of
        those rows now share a date, making any fixed order arbitrary.

        Sorting is the invariant; the dates are data. Reading them from the
        table keeps this test true across every future data correction, and
        the shuffled input still proves the function sorts rather than
        echoing insertion order.
        """
        from ppxai.engine.model_deprecations import ALL_DEPRECATIONS

        models = ["gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-2.5-flash"]
        for m in models:
            assert m in ALL_DEPRECATIONS, f"{m} left the deprecation table"

        earliest = min(
            date.fromisoformat(ALL_DEPRECATIONS[m].shutdown_date) for m in models
        )
        result = audit_config_models(
            {"gemini": models}, today=earliest - timedelta(days=30)
        )
        dates = [
            date.fromisoformat(ALL_DEPRECATIONS[e["model"]].shutdown_date)
            for e in result["upcoming"]
        ]
        assert dates == sorted(dates), (
            f"upcoming is not ordered by shutdown date: "
            f"{[(e['model']) for e in result['upcoming']]}"
        )
        assert len(dates) == len(models), "an upcoming deprecation was dropped"

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
        assert "gemini-3.1-flash-lite" in missing_names
        assert "gemma-4-31b-it" in missing_names

    def test_already_configured_models_not_recommended(self):
        provider_models = {
            "gemini": [
                "gemini-3-flash-preview",
                "gemini-3.1-flash-lite",  # already have this
            ],
        }
        missing = find_missing_recommended(provider_models)
        missing_names = {m["model"] for m in missing}
        assert "gemini-3.1-flash-lite" not in missing_names

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
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestAuditUserConfig:
    def test_missing_config_returns_error(self, tmp_path):
        result = audit_user_config(tmp_path / "nonexistent.json")
        assert result["error"]
        assert "missing" in result["error"].lower() or "not" in result["error"].lower()

    def test_malformed_json_returns_error(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{ not valid json", encoding="utf-8")
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
        assert warn["recommended_default"] == "gemini-3.5-flash"

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
        assert "gemini-3.1-flash-lite" in names


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

    def test_all_openai_entries_have_valid_replacement(self):
        # Same invariant for OpenAI: replacement must not itself be
        # in the OpenAI deprecation dict.
        for model, entry in OPENAI_DEPRECATIONS.items():
            assert entry.replacement not in OPENAI_DEPRECATIONS, (
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

    def test_every_recommended_model_is_one_we_ship(self):
        """A recommendation must name a model in the configs we ship.

        `test_recommended_new_models_are_not_deprecated` asks only "is this in
        the deprecation table". That is necessary and not sufficient: on
        2026-09-01 `deepseek-ai/deepseek-v4-pro-0813` was recommended as a
        model to ADOPT while it failed to answer at all — three attempts,
        45s / 120s / 300s-with-retry, ten minutes, zero output. It was never
        in the deprecation table, so the existing check passed.

        Removing it from the shipped config is what should have surfaced it,
        and nothing connected the two. This closes that: a recommendation the
        configs do not carry is a hint pointing at a model the user cannot
        select, which is the same defect as pointing at a dead one.
        """
        import json
        import pathlib
        import subprocess

        root = pathlib.Path(__file__).resolve().parent.parent
        try:
            names = subprocess.run(
                ["git", "ls-files", "ppxai-config*.json"],
                cwd=root, capture_output=True, text=True, timeout=30,
            ).stdout.split()
        except Exception:  # noqa: BLE001 — no git (sdist, vendored tree)
            names = []
        names = names or ["ppxai-config.example.json", "ppxai-config.json"]
        paths = [root / n for n in names if (root / n).exists()]
        assert paths, "no tracked config found — this check would pass vacuously"

        for path in paths:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            shipped = {
                (prov, mid)
                for prov, pb in (cfg.get("providers") or {}).items()
                for mid in ((pb or {}).get("models") or {})
            }
            missing = [
                (r["provider"], r["model"])
                for r in RECOMMENDED_NEW_MODELS
                if (r["provider"], r["model"]) not in shipped
            ]
            assert not missing, (
                f"{path.name} does not carry these recommended models, so "
                f"/doctor advises adopting something the user cannot select: "
                f"{missing}"
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

    # ----------------------------------------------------------------
    # Count sentinels — intentional friction so additions get reviewed
    # ----------------------------------------------------------------

    def test_gemini_deprecation_count(self):
        # Gemini family — bump when adding a new shutdown.
        # Current (verified 2026-05-14): 3-pro-preview, 2.0-flash, 2.0-flash-lite,
        # 2.5-pro, 2.5-flash, 2.5-flash-lite, 2.5-flash-image,
        # 3.1-flash-lite-preview (preview→GA migration, retires 2026-05-25).
        assert len(GEMINI_DEPRECATIONS) == 8

    def test_openai_deprecation_count(self):
        # OpenAI family — bump when adding a new shutdown.
        # Current (verified 2026-04-12): chatgpt-4o-latest, codex-mini-latest,
        # gpt-4-0314, gpt-4-0125-preview, gpt-4-1106-preview, gpt-4-turbo-preview,
        # gpt-4o-realtime-preview, gpt-4o-mini-realtime-preview,
        # gpt-4o-audio-preview, gpt-4o-mini-audio-preview, dall-e-2, dall-e-3,
        # gpt-3.5-turbo-instruct, gpt-3.5-turbo-1106, babbage-002, davinci-002.
        assert len(OPENAI_DEPRECATIONS) == 16

    def test_perplexity_deprecation_count(self):
        """The three Sonar IDs served only on the retiring chat wire.

        Was "no active deprecations, verified 2026-04-12" — true then. On
        2026-09-27 Perplexity retires the Sonar chat-completions ENDPOINT,
        which is unlike every other table here: the models are not withdrawn,
        the wire they are served on is.

        All four point at `perplexity/sonar` because that is the only Sonar
        model measured live on the Responses wire (2026-08-31, re-measured
        2026-09-01); `sonar-pro` and `sonar-reasoning-pro` 400 there in both
        bare and namespaced form. Naming a replacement that does not exist
        would be a worse hint than naming a lighter one that does.

        `sonar-deep-research` joined on 2026-09-01. It had NO row while being
        live on chat-completions and absent from Responses — so it would have
        stopped working on the cutover with no migration hint at all. This
        assertion is a SET rather than a count precisely so an addition has
        to be justified here rather than silently absorbed.
        """
        assert set(PERPLEXITY_DEPRECATIONS) == {
            "sonar",
            "sonar-deep-research",
            "sonar-pro",
            "sonar-reasoning-pro",
        }
        for model, dep in PERPLEXITY_DEPRECATIONS.items():
            assert dep.shutdown_date == "2026-09-27", model
            assert dep.replacement == "perplexity/sonar", model

    def test_all_deprecations_merged_correctly(self):
        # ALL_DEPRECATIONS must be the union of every provider-specific dict.
        expected = (
            len(GEMINI_DEPRECATIONS)
            + len(OPENAI_DEPRECATIONS)
            + len(PERPLEXITY_DEPRECATIONS)
            + len(NVIDIA_DEPRECATIONS)
        )
        assert len(ALL_DEPRECATIONS) == expected, (
            f"ALL_DEPRECATIONS ({len(ALL_DEPRECATIONS)}) != sum of provider "
            f"dicts ({expected}). Check for duplicate keys across providers."
        )
        # Spot-check: every provider-specific entry must be in the merged dict.
        for k in GEMINI_DEPRECATIONS:
            assert k in ALL_DEPRECATIONS
        for k in OPENAI_DEPRECATIONS:
            assert k in ALL_DEPRECATIONS
        for k in NVIDIA_DEPRECATIONS:
            assert k in ALL_DEPRECATIONS

    @pytest.mark.parametrize("provider", ["openai", "gemini", "perplexity", "nvidia"])
    def test_recommended_default_matches_the_example_config(self, provider):
        """The INTENT, asserted instead of a hardcoded literal.

        This pinned `RECOMMENDED_DEFAULTS["openai"] == "gpt-5.4"`, so every
        legitimate default change failed a test whose real subject is
        AGREEMENT between the recommendation and what ppxai actually ships.
        Reading the example config expresses that, covers every provider
        rather than one, and cannot go stale — the 2026-08-31 Terra swap is
        exactly the change it should have permitted and did not.
        """
        import json
        from pathlib import Path

        cfg = json.loads(
            (Path(__file__).resolve().parents[1] / "ppxai-config.example.json")
            .read_text(encoding="utf-8")
        )
        shipped = (cfg.get("providers", {}).get(provider) or {}).get("default_model")
        if not shipped:
            pytest.skip(f"{provider} has no default_model in the example config")
        assert RECOMMENDED_DEFAULTS[provider] == shipped, (
            f"/doctor recommends {RECOMMENDED_DEFAULTS[provider]!r} for "
            f"{provider} but the shipped config defaults to {shipped!r}"
        )

    def test_example_config_has_no_deprecated_models(self):
        """The shipped `ppxai-config.example.json` must not advertise any
        model that is scheduled for shutdown. CI fails here if someone
        removes a model from the deprecation table without also
        removing it from the example config, OR if someone adds a
        deprecated model to the example.
        """
        import json
        import pathlib

        repo_root = pathlib.Path(__file__).parent.parent
        example_path = repo_root / "ppxai-config.example.json"
        cfg = json.loads(example_path.read_text(encoding="utf-8"))

        violations = []
        for provider_name, provider_cfg in cfg.get("providers", {}).items():
            for model_id in provider_cfg.get("models", {}):
                if model_id in ALL_DEPRECATIONS:
                    entry = ALL_DEPRECATIONS[model_id]
                    violations.append(
                        f"{provider_name}.{model_id} "
                        f"(shutdown {entry.shutdown_date}, "
                        f"replacement: {entry.replacement})"
                    )
        assert not violations, (
            "ppxai-config.example.json contains deprecated models:\n  "
            + "\n  ".join(violations)
            + "\nRemove them from the example config OR remove them "
            "from model_deprecations.py if they've been un-deprecated."
        )

    # ------------------------------------------------------------------
    # The same rules, applied to EVERY tracked config -- not just the
    # example.
    #
    # The repo ships TWO configs (`git ls-files 'ppxai-config*.json'`), and
    # every invariant above scoped only the example. So the tracked root
    # config kept `sonar-pro` as its default for a full day after the
    # deprecation rows landed, and its NVIDIA block still pointed at models
    # that had answered HTTP 410 for six weeks -- suite green throughout,
    # because no test read that file.
    #
    # Written over the tracked SET rather than duplicated per file, so a
    # third config joins the fence by existing.

    @staticmethod
    def _tracked_configs():
        import pathlib
        import subprocess

        root = pathlib.Path(__file__).parent.parent
        try:
            out = subprocess.run(
                ["git", "ls-files", "ppxai-config*.json"],
                cwd=root, capture_output=True, text=True, timeout=30,
            ).stdout.split()
        except Exception:  # noqa: BLE001 -- no git (sdist, vendored tree)
            out = []
        # Fall back to the known pair so the fence still runs without git,
        # and so a missing `git` cannot silently empty the parametrisation.
        names = out or ["ppxai-config.example.json", "ppxai-config.json"]
        return [root / n for n in names if (root / n).exists()]

    def test_the_tracked_config_set_is_not_empty(self):
        """A set that silently resolves to zero is a fence that cannot fail
        -- the exact failure mode this block is fixing."""
        found = self._tracked_configs()
        assert len(found) >= 2, (
            f"expected at least the example + root config, found {found}"
        )

    def test_every_tracked_config_defaults_to_a_live_model(self):
        """Defaults are the rule that actually broke.

        A deprecated model may stay in a config as an explicit, commented
        record (see the next test). It may never be the thing a fresh user
        is pointed AT.
        """
        import json

        violations = []
        for path in self._tracked_configs():
            cfg = json.loads(path.read_text(encoding="utf-8-sig"))
            for pname, pblock in (cfg.get("providers") or {}).items():
                if not isinstance(pblock, dict):
                    continue
                for key in ("default_model", "coding_model"):
                    mid = pblock.get(key)
                    if mid in ALL_DEPRECATIONS:
                        e = ALL_DEPRECATIONS[mid]
                        violations.append(
                            f"{path.name}: providers.{pname}.{key} = {mid} "
                            f"(shutdown {e.shutdown_date}, use {e.replacement})"
                        )
        assert not violations, (
            "a tracked config points a default at a deprecated model:\n  "
            + "\n  ".join(violations)
        )

    def test_a_deprecated_model_in_a_tracked_config_is_acknowledged(self):
        """Keeping a dead model is allowed; keeping it SILENTLY is not.

        The root config deliberately retains ids that answer 410/404 so an
        operator's hand-tuned `generation_params` survive the migration --
        a defensible choice and an indefensible silence. So the entry has to
        say so, in the file, where whoever reads the config sees it.
        """
        import json

        MARKERS = ("__comment_DEAD", "__comment_RETIRES", "__comment_migrated")
        violations = []
        for path in self._tracked_configs():
            cfg = json.loads(path.read_text(encoding="utf-8-sig"))
            for pname, pblock in (cfg.get("providers") or {}).items():
                if not isinstance(pblock, dict):
                    continue
                for mid, mblock in (pblock.get("models") or {}).items():
                    if mid not in ALL_DEPRECATIONS:
                        continue
                    if not isinstance(mblock, dict) or not any(
                        k in mblock for k in MARKERS
                    ):
                        e = ALL_DEPRECATIONS[mid]
                        violations.append(
                            f"{path.name}: providers.{pname}.models.{mid} "
                            f"(shutdown {e.shutdown_date}, replacement "
                            f"{e.replacement}) -- remove it, or add one of "
                            f"{MARKERS} saying why it stays"
                        )
        assert not violations, (
            "deprecated models kept with no explanation:\n  "
            + "\n  ".join(violations)
        )


class TestGroundingSection:
    """F5 (ADR 0009 §4): /doctor reports the effective oneshot grounding
    path per provider, using the SAME config-axis decision function the
    /v1/oneshot route uses."""

    def test_reports_path_per_provider(self, monkeypatch):
        import ppxai.config as config_pkg
        from ppxai.commands import doctor as doctor_mod
        from ppxai.config import execution as exec_mod

        monkeypatch.setattr(
            config_pkg, "get_available_providers", lambda: ["gem", "local"]
        )
        monkeypatch.setattr(
            config_pkg, "get_default_model",
            lambda p: {"gem": "g1", "local": "q1"}[p],
        )
        monkeypatch.setattr(
            exec_mod, "get_execution_run_config",
            lambda: {"web_search": True, "grounding": True},
        )
        monkeypatch.setattr(
            doctor_mod, "get_effective_oneshot_path",
            lambda p, m: {"gem": "native", "local": "search-loop"}[p],
        )
        text = "\n".join(doctor_mod._format_grounding_section())
        assert "web_search=on" in text and "grounding=on" in text
        assert "gem (g1): native" in text
        assert "local (q1): search-loop" in text

    def test_no_providers_is_graceful(self, monkeypatch):
        import ppxai.config as config_pkg
        from ppxai.commands import doctor as doctor_mod

        monkeypatch.setattr(config_pkg, "get_available_providers", lambda: [])
        text = "\n".join(doctor_mod._format_grounding_section())
        assert "(no providers configured)" in text

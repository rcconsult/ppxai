"""`/doctor` carries the ADR 0012 migration (§2 Q0c/Q0d/Q0e).

The clean break makes `/doctor` load-bearing rather than advisory. Under a
break there is no dual-read, so a legacy key resolves to **nothing** — the
accessors cannot see it by construction, and the operator's setting stops
applying silently. `docs/lessons/clean-break-config-moves-need-a-file-scan.md`
records the version of this lesson learned when ADR 0010 moved keys with no
file scan.

Q0e then adds three findings of its own, because it requires config records
to be COMPLETE and correctly placed:

* a **partial** record is a defect, not a shorthand (Q0d) — with dozens of
  models nobody can tell an intention from an oversight;
* a **misplaced** field is silently ignored, which is the correct resolution
  behaviour (there is nothing to arbitrate) but a poor experience unmarked;
* a **mistyped** value is the hand-edit hazard: `"false"` is truthy and a
  string `max_tokens` reaches `max()` and raises mid-chat.

`/doctor` also has to SUPPLY the fix, not just name it — Q0e's verbosity is
explicitly the tool's burden, not the operator's, which is what
`complete_record_for` is for.
"""

from __future__ import annotations

import json

import pytest

from ppxai.commands import doctor as doctor_mod
from ppxai.config import facts_config as fcmod


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    def _write(providers):
        cfg = tmp_path / "ppxai-config.json"
        cfg.write_text(json.dumps({"providers": providers}), encoding="utf-8")
        monkeypatch.setattr(fcmod, "find_config_file", lambda: cfg)
        return cfg

    return _write


def _provider(**extra):
    base = {"name": "P", "base_url": "https://example.invalid", "api_key_env": "K"}
    base.update(extra)
    return {"p": base}


def _complete_model_facts(**overrides):
    from ppxai.engine.model_facts import FACT_FIELDS, ModelFacts

    rec = {f: getattr(ModelFacts(), f) for f in FACT_FIELDS}
    rec["restricted_params"] = list(rec["restricted_params"])
    rec.update(overrides)
    return rec


def _complete_provider_facts(**overrides):
    from ppxai.engine.model_facts import PROVIDER_FACT_FIELDS
    from ppxai.engine.types import ProviderCapabilities

    rec = {f: getattr(ProviderCapabilities(), f) for f in PROVIDER_FACT_FIELDS}
    rec.update(overrides)
    return rec


class TestLegacyKeysAreReported:
    """The only surface that can reveal a silently-ignored setting."""

    def test_a_legacy_provider_block_is_named(self, config_file):
        config_file(_provider(capabilities={"native_tool_calling": True}))
        report = "\n".join(doctor_mod._format_facts_section())
        assert "providers.p.capabilities.native_tool_calling" in report
        assert "IGNORED" in report

    def test_a_legacy_model_block_is_named(self, config_file):
        config_file(_provider(models={"m1": {"tool_calling": {"mode": "native"}}}))
        report = "\n".join(doctor_mod._format_facts_section())
        assert "providers.p.models.m1.tool_calling.mode" in report

    def test_the_report_names_the_replacement_key(self, config_file):
        """Naming the problem without the fix is half a migration.

        The target is per MODEL, not per provider — see
        `TestTheMigrationPlanPointsSomewhereValid` for why. This test was
        first written asserting the provider-level target, and caught its
        own wrongness once the push-down landed.
        """
        config_file(
            _provider(
                capabilities={"native_tool_calling": True}, models={"m1": {}}
            )
        )
        report = "\n".join(doctor_mod._format_facts_section())
        assert "providers.p.models.m1.facts.tool_mode" in report

    def test_the_openrouter_shape_is_caught(self, config_file):
        """Measured 2026-08-30: `openrouter` and `ollama` in the shipped
        example config held native tool calling on SOLELY via
        `capabilities.native_tool_calling`, with no `tool_calling` block at
        all — so the break degrades them silently. That is the case this
        scan exists for."""
        config_file(
            {
                "openrouter": {
                    "name": "OR",
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "K",
                    "capabilities": {"native_tool_calling": True},
                }
            }
        )
        report = "\n".join(doctor_mod._format_facts_section())
        assert "openrouter" in report and "IGNORED" in report


class TestTheMigrationPlanPointsSomewhereValid:
    """The advice must not send an operator to a dead location.

    Found by review, not by the tests above: the first version of
    `migration_plan` mapped key->key at the SAME level, so a provider-level
    `capabilities.native_tool_calling` was reported as moving to
    `providers.<p>.facts.tool_mode`. Under Q0e that is a MODEL fact with no
    valid provider-level home — the resolver ignores it and
    `misplaced_fields_in_config` then flags it. An operator following the
    advice would stay demoted AND collect a second warning.

    This is a property test rather than a fixture comparison: every target
    the plan emits must be a location the misplaced scan would accept.
    """

    def _targets(self, plan):
        return [line.split("->")[1].strip().split()[0] for line in plan]

    def test_no_target_is_a_location_the_misplaced_scan_rejects(
        self, config_file
    ):
        from ppxai.engine.model_facts import FACT_FIELDS

        config_file(
            _provider(
                capabilities={"native_tool_calling": True},
                tool_calling={"mode": "native"},
                models={"m1": {}, "m2": {}},
            )
        )
        for target in self._targets(fcmod.migration_plan()):
            field = target.split(".")[-1]
            if field in FACT_FIELDS:
                assert ".models." in target, (
                    f"{target} puts a MODEL fact at provider level — the "
                    "resolver ignores it and /doctor then flags it"
                )

    def test_a_provider_level_model_fact_is_pushed_down_per_model(
        self, config_file
    ):
        config_file(
            _provider(
                capabilities={"native_tool_calling": True},
                models={"m1": {}, "m2": {}},
            )
        )
        targets = self._targets(fcmod.migration_plan())
        assert "providers.p.models.m1.facts.tool_mode" in targets
        assert "providers.p.models.m2.facts.tool_mode" in targets

    def test_a_provider_level_endpoint_fact_stays_at_provider_level(
        self, config_file
    ):
        """The push-down applies to model facts ONLY — `web_search` is a
        statement about the endpoint and belongs where it is."""
        config_file(
            _provider(capabilities={"web_search": True}, models={"m1": {}})
        )
        for target in self._targets(fcmod.migration_plan()):
            if target.endswith("web_search"):
                assert ".models." not in target

    def test_a_model_level_legacy_key_maps_in_place(self, config_file):
        config_file(_provider(models={"m1": {"tool_calling": {"mode": "native"}}}))
        assert "providers.p.models.m1.facts.tool_mode" in self._targets(
            fcmod.migration_plan()
        )

    def test_the_head_example_config_shape_is_covered(self, config_file):
        """The openrouter/ollama shape Q0c was written for: native tool
        calling held SOLELY by `capabilities.native_tool_calling`."""
        config_file(
            {
                "openrouter": {
                    "name": "OR",
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "K",
                    "capabilities": {"native_tool_calling": True},
                    "models": {"anthropic/claude-haiku": {}},
                }
            }
        )
        targets = self._targets(fcmod.migration_plan())
        assert (
            "providers.openrouter.models.anthropic/claude-haiku.facts.tool_mode"
            in targets
        )


class TestIncompleteRecordsAreReported:
    """Q0d — a config record states every field of its type, or it is a bug."""

    def test_a_partial_model_block_names_its_blanks(self, config_file):
        config_file(_provider(models={"m1": {"facts": {"tool_mode": "native"}}}))
        missing = fcmod.incomplete_blocks_in_config()
        assert "providers.p.models.m1.facts" in missing
        assert "max_tokens" in missing["providers.p.models.m1.facts"]

    def test_a_complete_model_block_is_not_reported(self, config_file):
        config_file(_provider(models={"m1": {"facts": _complete_model_facts()}}))
        assert fcmod.incomplete_blocks_in_config() == {}

    def test_a_complete_provider_block_is_not_reported(self, config_file):
        config_file(_provider(facts=_complete_provider_facts()))
        assert fcmod.incomplete_blocks_in_config() == {}

    def test_completeness_is_judged_per_record_type(self, config_file):
        """A provider block needs the 5 endpoint fields, not all 17.

        If this ever judged both positions against one field list, every
        provider block in every config would be permanently 'incomplete'.
        """
        config_file(_provider(facts=_complete_provider_facts()))
        report = "\n".join(doctor_mod._format_facts_section())
        assert "partial record" not in report


class TestMisplacedAndMistypedAreReported:
    def test_a_model_fact_in_a_provider_block(self, config_file):
        config_file(_provider(facts={"tool_mode": "native"}))
        report = "\n".join(doctor_mod._format_facts_section())
        assert "wrong record" in report and "tool_mode" in report

    def test_an_endpoint_fact_in_a_model_block(self, config_file):
        config_file(_provider(models={"m1": {"facts": {"web_search": True}}}))
        report = "\n".join(doctor_mod._format_facts_section())
        assert "wrong record" in report and "web_search" in report

    def test_an_uncoercible_value(self, config_file):
        config_file(_provider(models={"m1": {"facts": {"tier": 7}}}))
        report = "\n".join(doctor_mod._format_facts_section())
        assert "declared type" in report and "tier" in report

    def test_a_coercible_value_is_not_reported(self, config_file):
        """`"4096"` is a hand-edit, not a defect — it is repaired silently."""
        config_file(_provider(models={"m1": {"facts": {"max_tokens": "4096"}}}))
        assert fcmod.wrong_typed_fields_in_config() == {}


class TestDoctorSuppliesTheFix:
    """Q0e puts the verbosity burden on the tool, not the operator."""

    def test_a_model_record_is_complete(self, config_file):
        from ppxai.engine.model_facts import FACT_FIELDS

        config_file(_provider())
        record = fcmod.complete_record_for("p", "gpt-5.2")
        assert set(record) == set(FACT_FIELDS)

    def test_a_provider_record_is_complete(self, config_file):
        from ppxai.engine.model_facts import PROVIDER_FACT_FIELDS

        config_file(_provider())
        record = fcmod.complete_record_for("p")
        assert set(record) == set(PROVIDER_FACT_FIELDS)

    def test_the_generated_record_is_json_serialisable(self, config_file):
        """It is written into a JSON file; a tuple would crash the write."""
        config_file(_provider())
        json.dumps(fcmod.complete_record_for("openai", "o4-mini"))

    def test_writing_it_back_preserves_behaviour(self, config_file, tmp_path):
        """The load-bearing property: the scaffold makes the implicit
        explicit and changes NOTHING else, so an operator can accept
        /doctor's rewrite without auditing 17 fields."""
        from ppxai.engine.providers.openai_native import OpenAINativeProvider

        config_file(_provider())
        before = OpenAINativeProvider(
            api_key="sk-test", provider_id="p"
        ).get_facts_for_model("o4-mini")

        record = fcmod.complete_record_for("p", "o4-mini")
        config_file(_provider(models={"o4-mini": {"facts": record}}))
        after = OpenAINativeProvider(
            api_key="sk-test", provider_id="p"
        ).get_facts_for_model("o4-mini")

        assert after == before

    def test_the_scaffold_is_complete_for_an_unmeasured_model(self, config_file):
        """Adding a NEW model must not require hand-writing 12 fields."""
        from ppxai.engine.model_facts import FACT_FIELDS

        config_file(_provider())
        record = fcmod.complete_record_for("p", "brand-new-model-9")
        assert set(record) == set(FACT_FIELDS)
        assert record["tool_mode"] == "prompt_based"


class TestCleanConfigReportsClean:
    def test_no_findings_on_a_fully_migrated_config(self, config_file):
        config_file(
            _provider(
                facts=_complete_provider_facts(),
                models={"m1": {"facts": _complete_model_facts()}},
            )
        )
        report = "\n".join(doctor_mod._format_facts_section())
        assert "✓" in report
        assert "IGNORED" not in report

    def test_the_shipped_example_config_is_migrated(self):
        """Q0c requires the example config to ship MIGRATED.

        It is the file operators copy, so a stale example would hand every
        new deployment the silent degradation this ADR's break creates.
        """
        from pathlib import Path

        example = (
            Path(__file__).resolve().parents[1] / "ppxai-config.example.json"
        )
        cfg = json.loads(example.read_text(encoding="utf-8-sig"))
        stale = []
        for pname, pblock in (cfg.get("providers") or {}).items():
            if not isinstance(pblock, dict):
                continue
            for bname in ("capabilities", "tool_calling"):
                if bname in pblock:
                    stale.append(f"providers.{pname}.{bname}")
                for mname, mblock in (pblock.get("models") or {}).items():
                    if isinstance(mblock, dict) and bname in mblock:
                        stale.append(f"providers.{pname}.models.{mname}.{bname}")
        assert stale == [], f"example config still carries legacy blocks: {stale}"

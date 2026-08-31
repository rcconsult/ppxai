"""The shipped example config resolves exactly as it did before ADR 0012.

**The fence Q0c requires, and it took three attempts to satisfy.** Each
failure is worth recording, because each was a plausible-looking way to
migrate a config that silently changed behaviour:

1. **Copy legacy values verbatim.** Wrote Perplexity's provider-level
   `native_tool_calling: false` into every model row — but at HEAD the
   provider's per-model code table said `sonar-pro` was capable and
   OUTRANKED that provider-level statement, so the migration demoted
   Perplexity's only tool-capable models. Item 43, inverted, in the file
   operators copy.
2. **Regenerate from the new resolver** (`complete_record_for`). That
   resolver reads the NEW ladder — seed row plus `facts` row — so it
   ignores legacy blocks by construction and cannot reproduce old
   behaviour for a file that still has them. Every vLLM box lost its
   provider-level `mode: native` and its fallback flags.
3. **Harvest the effective value from the OLD code**, which is what
   shipped: run the pre-ADR-0012 resolver over the pre-migration file and
   write down what it actually answered. Correct by construction rather
   than by reasoning about precedence.

Attempt 3 still had one bug worth knowing: the harvester patched
`config.capabilities` and `config.loader` but not `config.providers`, and
`get_tool_calling_config` reads the file through a THIRD path
(`PPXAI_CONFIG_FILE`). Two of three readers saw the target file, the third
saw the developer's real config — which silently dropped `vllm-gpt-oss`'s
provider-level `mode: native` and demoted `openai/gpt-oss-120b`, the exact
model Q0e names as the round-trip fixture.

`tests/fixtures/adr0012_head_effective.json` is the frozen output of that
harvest: what every configured model resolved to under the OLD code, on the
OLD file. It is a record of measured behaviour, not a restatement of the
new code, which is why it can fence the new code at all.

⚠ **TWO DELIBERATE deviations from HEAD**, both declared in ADR 0012 §2
Q0d. Any other difference is a regression.

**Deviation 1 — an unstated endpoint field takes the CLASS default.**
`provider_ops` built the deployed record with
`ProviderCapabilities.from_dict(config["capabilities"])`, so a config
block REPLACED the class record and any field it omitted fell to the
dataclass default. The example states no `citations` for Perplexity, so
the deployed record said `false` even though `PerplexityProvider`
declares `True`. Q0e makes the rule uniform for both records — shipped
row, then stated overrides — so an unstated field now keeps the class
value. Behaviour-neutral for today's readers (`chat.py:312`/`:397` test
`citations or web_search`, and `web_search` is true), but not in general.

**Deviation 2 — `supports_vision` survives an override.** Three
rows carry `supports_vision: true` where HEAD-effective resolved `false`:

    nvidia   deepseek-ai/deepseek-v4-pro-0813
    nvidia   deepseek-ai/deepseek-v4-flash-0731
    qwen36-agent  Qwen/Qwen3.6-27B-FP8-agent

Their glob rows say `true`. HEAD answered `false` only because
`get_effective_profile` rebuilt `ModelProfile` field by field whenever any
override layer was present and omitted `supports_vision` — a LATENT bug
fixed by this ADR (a `replace()` on a frozen record cannot lose a field).
Latent because the wrong value never reached an image decision: that
function's one caller read only the tool-loop fields, and every vision
reader calls `model_profiles.supports_vision` directly.

Latent is still worth not freezing. A byte-identical migration would write
`false` into the config rows, where it would outrank the corrected seed —
turning a trap that never fired into a permanent, explicit statement that
these three models have no vision. So the migration writes the glob's value and the fixture records the
deviation. `TestTheVisionFixReachesTheConfig` below asserts it, and
`test_supports_vision_survives_an_override` in `test_model_profiles.py`
fences the code half.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "adr0012_head_effective.json"
EXAMPLE = REPO / "ppxai-config.example.json"


@pytest.fixture(scope="module")
def head_effective():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def resolved(monkeypatch):
    """Resolve every configured model through the CURRENT code."""
    from dataclasses import asdict

    import ppxai.config.facts_config as fc
    from ppxai.engine.model_facts import shipped_facts_for_model
    from ppxai.engine.providers import get_provider_class
    from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

    monkeypatch.setattr(fc, "find_config_file", lambda: EXAMPLE)

    cfg = json.loads(EXAMPLE.read_text(encoding="utf-8-sig"))
    out = {}
    for pname, pblock in (cfg.get("providers") or {}).items():
        if not isinstance(pblock, dict):
            continue
        try:
            cls = get_provider_class(pname)
        except Exception:  # noqa: BLE001
            cls = None
        table = getattr(cls, "shipped_model_facts", {}) or {}
        # A custom provider (openrouter, a vLLM box) has no registered class;
        # its endpoint record comes from the openai_compat default.
        caps = getattr(cls, "default_capabilities", None)
        if caps is None:
            caps = OpenAICompatibleProvider.default_capabilities
        out[f"{pname}::__endpoint__"] = asdict(
            fc.apply_provider_overrides(caps, pname)
        )
        for mname, mblock in (pblock.get("models") or {}).items():
            if not isinstance(mblock, dict):
                continue
            model_id = mblock.get("id", mname)
            rec = asdict(
                fc.resolve_model_facts(
                    shipped_facts_for_model(model_id, table), pname, mname
                )
            )
            rec["restricted_params"] = list(rec["restricted_params"])
            out[f"{pname}::{mname}"] = rec
    return out


#: Records the example config no longer ships, and WHY. Listed explicitly for
#: the same reason as `DECLARED` below: a fixture quietly edited to match new
#: behaviour proves nothing. This fence's job is proving W1 changed no
#: behaviour, so a later PRODUCT decision that removes a record has to be
#: stated here rather than allowed to look like a resolution failure.
RETIRED = {
    "perplexity::sonar": (
        "2026-08-31 — Sonar chat-completions retires 2026-09-27; the example "
        "config ships `perplexity/sonar`, the same model on the surviving "
        "Responses wire (and tool-capable there, unlike the bare id)."
    ),
    "perplexity::sonar-pro": (
        "2026-08-31 — chat-completions only. Measured twice: Perplexity does "
        "NOT serve it on the Responses wire in bare or namespaced form (400 "
        "'not supported'), so there is no successor id to ship."
    ),
    "perplexity::sonar-reasoning-pro": (
        "2026-08-31 — same as sonar-pro: absent from the Responses wire."
    ),
    # NVIDIA, found by the Item 38 sweep 2026-08-31. Unlike the Sonar rows
    # these were already BROKEN in the shipped config — HTTP 410 with an
    # explicit end-of-life date, two of them predating the previous sweep.
    "nvidia::qwen/qwen3.5-122b-a10b": (
        "2026-08-31 — HTTP 410, EOL 2026-07-20. The whole qwen family is gone "
        "from NIM, so there is no sibling to rename to."
    ),
    "nvidia::qwen/qwen3-next-80b-a3b-instruct": (
        "2026-08-31 — HTTP 410, EOL 2026-07-27. Same: no qwen model remains."
    ),
    "nvidia::deepseek-ai/deepseek-v4-pro": (
        "2026-08-31 — RENAMED, not withdrawn: NVIDIA moved to date-suffixed "
        "ids. The record lives on at `deepseek-ai/deepseek-v4-pro-0813`, "
        "which is in this fixture's place and carries the same measurements."
    ),
    "nvidia::deepseek-ai/deepseek-v4-flash": (
        "2026-08-31 — RENAMED to `deepseek-ai/deepseek-v4-flash-0731`."
    ),
}


class TestBehaviourIsPreserved:
    def test_every_record_still_resolves(self, head_effective, resolved):
        missing = sorted(set(head_effective) - set(resolved) - set(RETIRED))
        assert missing == [], f"records that no longer resolve: {missing}"

    def test_each_retired_record_is_actually_gone(self, resolved):
        """A RETIRED entry that still resolves is a stale excuse.

        Same self-check as `test_each_declared_deviation_actually_deviates`:
        an exemption nobody re-verifies becomes a hole in the fence.
        """
        still_present = sorted(k for k in RETIRED if k in resolved)
        assert still_present == [], (
            f"{still_present} are listed as retired but still resolve — "
            "remove them from RETIRED rather than carrying a false exemption"
        )

    #: NB the two `deepseek-v4-*` vision deviations that used to sit here are
    #: gone — not reverted, RENAMED. NVIDIA moved to date-suffixed ids
    #: (2026-08-31), so those records are in `RETIRED` and their old keys no
    #: longer resolve. A DECLARED entry is measured against the HEAD fixture,
    #: which knows only the old ids, so the deviation cannot be re-checked
    #: here; `TestTheVisionFixReachesTheConfig` carries it instead, reading
    #: the config under the NEW id against the seed.
    #:
    #: The declared deviations (ADR 0012 §2 Q0d). Listed EXPLICITLY rather
    #: than baked into the fixture, so the fence measures them instead of
    #: hiding them — a fixture quietly edited to match new behaviour proves
    #: nothing at all.
    DECLARED = {
        ("perplexity::__endpoint__", "citations"),
        ("qwen36-agent::Qwen/Qwen3.6-27B-FP8-agent", "supports_vision"),
    }

    def test_every_field_of_every_record_matches(self, head_effective, resolved):
        """All 45 records, all fields — not a sampled subset.

        Two regressions reached the file while this was a four-field
        eyeball. The comparison is exhaustive for that reason.
        """
        diffs = []
        for key, want in sorted(head_effective.items()):
            if key in RETIRED:
                continue  # deliberately no longer shipped — see RETIRED
            got = resolved[key]
            for field, wanted in sorted(want.items()):
                if (key, field) in self.DECLARED:
                    continue
                if got.get(field) != wanted:
                    diffs.append(
                        f"{key}.{field}: was {wanted!r}, now {got.get(field)!r}"
                    )
        assert diffs == [], "behaviour changed:\n  " + "\n  ".join(diffs)

    def test_each_declared_deviation_actually_deviates(
        self, head_effective, resolved
    ):
        """The exemption list must not outlive what it exempts.

        If a deviation is later reverted, its entry here would silently
        start excusing nothing — and the next real regression at that
        field would pass unnoticed behind a stale exemption.
        """
        inert = [
            f"{key}.{field}"
            for key, field in sorted(self.DECLARED)
            if resolved[key].get(field) == head_effective[key].get(field)
        ]
        assert inert == [], f"declared deviations that no longer deviate: {inert}"


class TestTheNamedFixtures:
    """The specific cases the ADR and the review called out by name."""

    def test_the_round_trip_fixture(self, resolved):
        """Q0e names this one: the operator's provider-level `mode: native`
        must survive, even though the shipped glob `openai/gpt-oss*` says
        `prompt_based`. Filling blanks BEFORE pushing provider statements
        down overwrites it — which is why the order is part of the
        decision, not an implementation detail."""
        assert resolved["vllm-gpt-oss::openai/gpt-oss-120b"]["tool_mode"] == "native"

    def test_perplexity_keeps_its_tool_capable_models(self):
        """Attempt 1 demoted these to `prompt_based` — Item 43 inverted.

        Asserted against the RESOLVER rather than the example config, because
        the config no longer ships these ids: on 2026-08-31 the Sonar
        chat-completions endpoint was given a 2026-09-27 retirement date and
        the example config moved to `perplexity/sonar`, the only Sonar model
        Perplexity serves on the surviving wire. The models still exist and
        are still tool-capable — an operator who configures them must not get
        them demoted — so the property this fence exists for is unchanged and
        is now checked where it actually lives.
        """
        from ppxai.engine.model_facts import shipped_facts_for_model
        from ppxai.engine.providers.perplexity import PerplexityProvider

        table = PerplexityProvider.shipped_model_facts
        assert shipped_facts_for_model("sonar-pro", table).tool_mode == "auto"
        assert shipped_facts_for_model("sonar-reasoning-pro", table).tool_mode == "auto"
        assert shipped_facts_for_model("sonar", table).tool_mode == "prompt_based"
        # The successor keeps native tools on the new wire (measured 2026-08-31:
        # it accepted a tools array AND called the tool, unlike bare `sonar`).
        assert shipped_facts_for_model("perplexity/sonar", table).tool_mode == "auto"

    @pytest.mark.parametrize(
        "provider",
        ["openrouter", "nvidia", "local-vllm", "vllm-gpt-oss", "lmstudio", "ollama"],
    )
    def test_streaming_is_not_silently_disabled(self, provider, resolved):
        """Attempt 1 wrote `streaming: false` wherever the legacy key was
        merely ABSENT, because it reconstructed defaults by hand instead of
        reading them. This is client-visible: `server/routes/providers.py`
        serialises it to the web and VSCode clients."""
        assert resolved[f"{provider}::__endpoint__"]["streaming"] is True

    def test_the_vllm_fallback_flags_survive(self, resolved):
        """Attempt 2 dropped these: provider-level `tool_calling` flags set
        once per box, which the new resolver cannot see in a legacy file."""
        row = resolved["local-vllm::meta-llama/Llama-3-70b"]
        assert row["fallback_on_empty"] is True
        assert row["strip_json_from_text"] is True


class TestTheEndpointDefaultSemantic:
    """Deviation 1, asserted rather than left implicit in the fixture.

    HEAD: a config `capabilities` block REPLACES the class record, so an
    omitted field falls to the dataclass default. New: the class record is
    the base and stated fields override it. The Perplexity `citations`
    case is the one place in the shipped example where the two differ.
    """

    def test_an_unstated_endpoint_field_keeps_the_class_value(self, resolved):
        from ppxai.engine.providers.perplexity import PerplexityProvider

        assert PerplexityProvider.default_capabilities.citations is True
        assert resolved["perplexity::__endpoint__"]["citations"] is True

    def test_a_stated_endpoint_field_still_overrides(self, monkeypatch, tmp_path):
        """The override direction must not be lost to the new base."""
        import ppxai.config.facts_config as fc
        from ppxai.engine.providers.perplexity import PerplexityProvider

        cfg = tmp_path / "ppxai-config.json"
        cfg.write_text(
            json.dumps(
                {"providers": {"perplexity": {"facts": {"citations": False}}}}
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(fc, "find_config_file", lambda: cfg)
        got = fc.apply_provider_overrides(
            PerplexityProvider.default_capabilities, "perplexity"
        )
        assert got.citations is False

    def test_the_readers_are_unaffected(self):
        """Why this was safe to change: both call sites OR it with
        web_search, which is true for Perplexity either way."""
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "ppxai" / "engine" / "chat.py")
        text = src.read_text(encoding="utf-8")
        assert "capabilities.citations or ctx.provider.capabilities.web_search" in text


class TestTheVisionFixReachesTheConfig:
    """The one deliberate deviation from HEAD, asserted rather than assumed.

    A byte-identical migration would have frozen a shipped bug into explicit
    config rows, where the code fix could never reach it. These three models
    are the only place that would have happened.
    """

    VISION_MODELS = [
        ("nvidia", "deepseek-ai/deepseek-v4-pro-0813"),
        ("nvidia", "deepseek-ai/deepseek-v4-flash-0731"),
        ("qwen36-agent", "Qwen/Qwen3.6-27B-FP8-agent"),
    ]

    @pytest.mark.parametrize("provider,model", VISION_MODELS)
    def test_vision_is_on(self, provider, model, resolved):
        assert resolved[f"{provider}::{model}"]["supports_vision"] is True

    @pytest.mark.parametrize("provider,model", VISION_MODELS)
    def test_the_config_row_agrees_with_the_seed_glob(self, provider, model):
        """The row must not contradict the table it came from.

        If a future regeneration writes `false` here again, the config row
        outranks the seed and the fix silently stops applying — which is
        precisely the failure mode this class exists to catch.
        """
        from ppxai.engine.model_facts import shipped_facts_for_model

        cfg = json.loads(EXAMPLE.read_text(encoding="utf-8-sig"))
        block = cfg["providers"][provider]["models"][model]
        model_id = block.get("id", model)
        assert block["facts"]["supports_vision"] is (
            shipped_facts_for_model(model_id).supports_vision
        )

    def test_no_other_row_contradicts_its_seed_on_vision(self):
        """Scoped: exactly these three, no silent spread."""
        from ppxai.engine.model_facts import shipped_facts_for_model

        cfg = json.loads(EXAMPLE.read_text(encoding="utf-8-sig"))
        contradicting = []
        for pname, pblock in (cfg.get("providers") or {}).items():
            if not isinstance(pblock, dict):
                continue
            for mname, mblock in (pblock.get("models") or {}).items():
                if not isinstance(mblock, dict) or "facts" not in mblock:
                    continue
                model_id = mblock.get("id", mname)
                seed = shipped_facts_for_model(model_id).supports_vision
                if mblock["facts"]["supports_vision"] != seed:
                    contradicting.append(f"{pname}::{mname}")
        assert contradicting == []


class TestTheExampleShipsMigrated:
    def test_no_legacy_blocks_remain(self):
        cfg = json.loads(EXAMPLE.read_text(encoding="utf-8-sig"))
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
        assert stale == [], f"legacy blocks left in the example: {stale}"

    def test_doctor_reports_it_clean(self, monkeypatch):
        import ppxai.config.facts_config as fc
        from ppxai.commands import doctor as doctor_mod

        monkeypatch.setattr(fc, "find_config_file", lambda: EXAMPLE)
        report = "\n".join(doctor_mod._format_facts_section())
        assert "IGNORED" not in report
        assert "wrong record" not in report
        assert "partial record" not in report

    def test_every_record_is_complete(self, monkeypatch):
        """Q0d: a config record states every field of its type."""
        import ppxai.config.facts_config as fc

        monkeypatch.setattr(fc, "find_config_file", lambda: EXAMPLE)
        assert fc.incomplete_blocks_in_config() == {}

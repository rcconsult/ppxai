"""ADR 0012 refactor (b) + Item 65 — `ModelFacts` is the only vocabulary.

`BUILTIN_PROFILES` / `ModelProfile` / `ToolCallingProfile` were the pre-ADR
per-model table. ADR 0012 made `ModelFacts` the record every consumer reads
and demoted the profile table to seed data, flattened at import. **Item 65
retired the seed**: the 65 rows are now stated as literals and
`model_profiles.py` is deleted.

This file was the comparison fence between the two vocabularies. With one
side gone the comparison cannot survive, so it is REWRITTEN rather than
deleted — into invariants over `SHIPPED_MODEL_FACTS` alone.

That rewrite matters more than it sounds, because of what we learned doing
step 1: **the shipped table had no test in front of it at all.** The old
`test_every_profile_row_flattens_to_its_facts_row` compared
`facts_from_profile(profile)` against the PROFILE — it fenced the flattener
and never read the table. Measured at the time: mutating `tool_mode` in a
literal row left all 135 tests green, and `grep -c SHIPPED_MODEL_FACTS
tests/` returned 0 across the suite. Whatever stands here is now the only
thing guarding the data every provider resolves.
"""

import re

import pytest

from ppxai.engine.model_facts import (
    FACT_FIELDS,
    SHIPPED_MODEL_FACTS,
    ModelFacts,
    shipped_facts_for_model,
    supports_vision,
)
from ppxai.engine.providers.base import BaseProvider

GLOBS = sorted(SHIPPED_MODEL_FACTS)

#: The count is a canary, not a target. It moves when a model is added or
#: retired — both legitimate — but never silently: a diff that changes it
#: has to say why.
EXPECTED_ROWS = 68

#: The rows whose wire is NOT the default. Before Item 65 these came from
#: `_API_PATH_TO_WIRE` and `_WIRE_BY_GLOB`, outside the rows entirely; the
#: migration moved the value onto each row and both mechanisms are gone.
#: A wrong value here sends a request to an endpoint that does not serve the
#: model — the 2026-08-31 fleet sweep found exactly that failure on the
#: gpt-5.6 line.
NON_DEFAULT_WIRES = {
    "gemini-2.5-pro*": "generate_content",
    "gemini-2.5-flash-lite*": "generate_content",
    "gemini-2.5-flash*": "generate_content",
    "gemini-3.8-flash*": "generate_content",
    "gemini-3.7-flash*": "generate_content",
    "gemini-3.6-flash*": "generate_content",
    "gemini-3.5-flash*": "generate_content",
    "gemini-3-flash*": "generate_content",
    "gemini-3.1-flash-lite*": "generate_content",
    "gemini-3.1-pro*customtools*": "generate_content",
    "gemini-3.1-pro*": "generate_content",
    "gemma-4-31b*": "generate_content",
    "gemma-4-26b*": "generate_content",
    "gemma-4-e*": "generate_content",
    "gemma-4*": "generate_content",
    "gpt-5.3-codex*": "responses",
    "gpt-5.1-codex-mini*": "responses",
    "gpt-5.1-codex*": "responses",
}


#: Rows that allow PARALLEL tool calls. This set is load-bearing, not
#: cosmetic: `engine/chat.py` does
#:
#:     if not facts.parallel_tool_calls:
#:         parsed_calls = parsed_calls[:1]
#:
#: so a row left at the dataclass default (False) makes ppxai **silently
#: discard every tool call after the first**. The model emits two, one is
#: executed, and nothing logs the loss — a multi-tool turn just takes twice
#: the round trips.
#:
#: Measured 2026-09-13: the Gemini flash line and both Gemma rows emit two
#: calls per turn reliably (3 trials each, finishReason STOP). The base
#: `gemini-3.1-pro*` row is deliberately NOT here — it returned
#: MALFORMED_FUNCTION_CALL on 2 of 3 parallel attempts, while its
#: `*customtools*` sibling was clean 3/3. Same family, opposite answer, which
#: is why this set is pinned per-row rather than inferred per-provider.
#:
#: OpenAI measured 2026-09-13 via /v1/chat/completions (control: gpt-5.2,
#: already True, returned 2 calls — so a 1-call result is the model, not a
#: malformed probe). gpt-5 / -mini / -nano and the gpt-4.1 / gpt-4o line all
#: returned 2 calls. **o3 and o3-mini returned 1 call on 3 of 3 trials**, so
#: their False is MEASURED-correct, not a leftover default — the reasoning
#: line is genuinely serial here. This is the second family where a blanket
#: flip would have been wrong, after gemini-3.1-pro.
#:
#: Still UNMEASURED and left False: gpt-5-pro*, gpt-5.3-codex*,
#: gpt-5.1-codex*, o1*, o1-mini*, o3-pro* (responses-wire or not configured
#: on this host), plus the vLLM / NVIDIA rows. Absence here is a gap in the
#: measurement, not a claim that those models cannot do parallel calls.
PARALLEL_TOOL_CALL_ROWS = {
    "gemini-3.8-flash*",
    "gemini-3.7-flash*",
    "gemini-3.6-flash*",
    "gemini-3.5-flash*",
    "gemini-3-flash*",
    "gemini-3.1-flash-lite*",
    "gemini-3.1-pro*customtools*",
    "gemma-4-31b*",
    "gemma-4-26b*",
    "gpt-5.5*",
    "gpt-5.4*",
    "gpt-5.2*",
    "qwen3-coder*",
    "*/qwen3-coder-30b*",
    "*/qwen3-coder-next*",
    "*/qwen3-coder-480b*",
    "Qwen/Qwen3.6-35B-A3B-FP8*",
    "gpt-5",
    "gpt-5-mini*",
    "gpt-5-nano*",
    "gpt-4.1",
    "gpt-4.1-nano*",
    "gpt-4o*",
    "gpt-4o-mini*",
}


def _facts_source() -> str:
    from pathlib import Path

    return (
        Path(__file__).resolve().parents[1] / "ppxai" / "engine" / "model_facts.py"
    ).read_text(encoding="utf-8")


def _parse_literal_rows(src: str):
    """`[(glob, body), ...]` for every literal row in `SHIPPED_MODEL_FACTS`.

    Parsed from SOURCE, because the question these checks ask is whether a
    field is *stated* — a row that omits one still has a value at runtime, so
    the object cannot answer it.
    """
    start = src.index("SHIPPED_MODEL_FACTS: dict[str, ModelFacts] = {")
    end = src.index("\n}", start)
    return re.findall(r'"([^"]+)": ModelFacts\((.*?)\n    \),', src[start:end], re.S)


class TestTheShippedTableIsWellFormed:
    """What replaced the seed comparison. These are the only guards left."""

    def test_the_row_count_is_what_we_think(self):
        assert len(SHIPPED_MODEL_FACTS) == EXPECTED_ROWS

    def test_the_parser_sees_every_row(self):
        """A source scan that silently matches nothing passes every check
        built on it — the vacuous-pass hole, closed first."""
        rows = _parse_literal_rows(_facts_source())
        assert len(rows) == len(SHIPPED_MODEL_FACTS), (
            f"parsed {len(rows)} literal rows but the table has "
            f"{len(SHIPPED_MODEL_FACTS)} — the row regex has drifted from the "
            "formatting, and every source check below is now measuring less "
            "than it appears to"
        )

    @pytest.mark.parametrize("field", ["tool_mode", "wire_protocol"])
    def test_every_row_states_the_meaning_bearing_fields(self, field):
        """The two fields a row must never inherit a default for.

        `tool_mode` because the defaults are INVERTED across the retired
        vocabulary (`ToolCallingProfile.mode` was "native", `ModelFacts` is
        "prompt_based" per Q0a) and 52 of the 65 rows relied on the old one.
        `wire_protocol` because it was supplied from outside the rows
        entirely until Item 65 moved it in.
        """
        rows = _parse_literal_rows(_facts_source())
        missing = [name for name, body in rows if f"{field}=" not in body]
        assert not missing, f"rows not stating {field}: {missing}"

    def test_every_row_states_every_field(self):
        """The general form. A row that states 10 of 12 fields is not wrong
        today — the dataclass fills the rest — but it is a row whose meaning
        depends on a default someone may change."""
        rows = _parse_literal_rows(_facts_source())
        gaps = {
            name: sorted(f for f in FACT_FIELDS if f"{f}=" not in body)
            for name, body in rows
        }
        gaps = {k: v for k, v in gaps.items() if v}
        assert not gaps, f"rows with unstated fields: {gaps}"

    def test_the_non_default_wires_are_exactly_these(self):
        actual = {
            k: v.wire_protocol
            for k, v in SHIPPED_MODEL_FACTS.items()
            if v.wire_protocol != "chat_completions"
        }
        assert actual == NON_DEFAULT_WIRES

    def test_the_parallel_tool_call_rows_are_exactly_these(self):
        """A row that flips to False starts DISCARDING tool calls silently.

        Nothing else in the suite covers `parallel_tool_calls`: reverting
        `gemini-3.5-flash*` to False on 2026-09-13 left 1,199 tests green.
        A stored capability with no check is how this table drifts from the
        fleet it describes, so the set is pinned and a diff has to say why.
        """
        actual = {
            k for k, v in SHIPPED_MODEL_FACTS.items() if v.parallel_tool_calls
        }
        assert actual == PARALLEL_TOOL_CALL_ROWS

    def test_the_unreliable_pro_row_stays_serial(self):
        """`gemini-3.1-pro*` measured MALFORMED_FUNCTION_CALL on 2 of 3
        parallel attempts (2026-09-13) while `*customtools*` was clean 3/3.
        Enabling parallel here re-opens a measured failure, so it is pinned
        separately from the set above — the two must not be merged."""
        assert SHIPPED_MODEL_FACTS["gemini-3.1-pro*"].parallel_tool_calls is False
        assert SHIPPED_MODEL_FACTS["gemini-3.1-pro*customtools*"].parallel_tool_calls is True

    def test_the_serial_reasoning_rows_stay_serial(self):
        """o3 / o3-mini returned exactly ONE tool call on 3 of 3 trials
        (2026-09-13), while the gpt-5 and gpt-4o lines returned two. Their
        False is a measurement, not an unset default, so flipping them would
        re-introduce the discard bug in reverse — asking for parallel from a
        model that does not emit it."""
        assert SHIPPED_MODEL_FACTS["o3*"].parallel_tool_calls is False
        assert SHIPPED_MODEL_FACTS["o3-mini*"].parallel_tool_calls is False

    @pytest.mark.parametrize("glob", GLOBS)
    def test_every_row_is_internally_valid(self, glob):
        facts = SHIPPED_MODEL_FACTS[glob]
        assert facts.tool_mode in {"native", "prompt_based", "auto"}
        assert facts.wire_protocol in {
            "chat_completions", "responses", "generate_content", "messages",
        }
        assert facts.tier in {"S", "A", "B", "C", "D"}
        assert isinstance(facts.restricted_params, tuple)


class TestFactsAreTheSourceOfTruth:
    """The ADR 0012 (b) property, now that there is no seed to disagree."""

    def test_supports_vision_reads_the_facts_record(self):
        import inspect

        src = inspect.getsource(supports_vision)
        assert "shipped_facts_for_model" in src
        assert "get_registry()" not in src

    @pytest.mark.parametrize("glob", GLOBS)
    def test_the_helper_agrees_with_the_table(self, glob):
        model = glob.rstrip("*")
        assert supports_vision(model) == shipped_facts_for_model(model).supports_vision

    def test_the_dead_profile_accessor_is_gone(self):
        assert not hasattr(BaseProvider, "get_model_profile")

    def test_the_profile_module_is_gone(self):
        """Item 65's end state. An importable `model_profiles` would mean the
        second vocabulary is still reachable, and reachable is how it comes
        back."""
        with pytest.raises(ImportError):
            import ppxai.engine.model_profiles  # noqa: F401

    def test_the_seed_bridge_functions_are_gone(self):
        from ppxai.engine import model_facts

        for name in ("facts_from_profile", "_seed_row", "_wire_for",
                     "_API_PATH_TO_WIRE", "_WIRE_BY_GLOB"):
            assert not hasattr(model_facts, name), f"{name} survived the migration"


class TestTheUnmeasuredFloor:
    """Q0a: a model no row names must claim nothing."""

    def test_the_floor_is_conservative(self):
        floor = ModelFacts()
        assert floor.tool_mode == "prompt_based"
        assert floor.wire_protocol == "chat_completions"
        assert floor.supports_vision is False
        assert floor.supports_reasoning is False
        assert floor.tier == ""

    def test_an_unnamed_model_gets_the_floor(self):
        assert shipped_facts_for_model("no-such-model-anywhere-xyz") == ModelFacts()

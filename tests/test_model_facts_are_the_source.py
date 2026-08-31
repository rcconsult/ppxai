"""ADR 0012 refactor (b) — `ModelFacts` is the source; profiles are seed data.

`BUILTIN_PROFILES` / `ModelProfile` / `ToolCallingProfile` were the pre-ADR
per-model table. ADR 0012 §2 made `ModelFacts` the record every consumer
reads, and the profile table became **seed data** for it — flattened once at
import through `facts_from_profile`.

Two vocabularies for one set of facts is exactly the two-systems problem the
ADR removes, so the seed bridge needs a scheduled death rather than an
indefinite life. This file is the fence for the part that has landed:

- `supports_vision()` reads `ModelFacts`, not the profile registry. It is the
  last behaviour-bearing reader of the old table, and the two agreed across
  every built-in glob when it moved — they had to, since one is the other's
  seed. Reading the derived record instead of the seed is what lets the seed
  retire.
- `BaseProvider.get_model_profile()` is **deleted**. It had zero callers
  outside its own docstring mentions — dead API keeping a dead vocabulary
  reachable.

What remains, deliberately: `BUILTIN_PROFILES` still exists as the 65-row
seed table, because rewriting those rows as native `ModelFacts` literals is a
data migration whose diff should not be mixed with a behaviour change. The
tests below pin the invariant that makes that migration safe whenever it
happens — every profile row and its facts row must agree, field for field.
"""

import pytest

from ppxai.engine.model_facts import FACT_FIELDS, facts_from_profile, shipped_facts_for_model
from ppxai.engine.model_profiles import BUILTIN_PROFILES, supports_vision
from ppxai.engine.providers.base import BaseProvider


GLOBS = sorted(BUILTIN_PROFILES)


class TestFactsAreTheSourceOfTruth:
    @pytest.mark.parametrize("glob", GLOBS)
    def test_vision_agrees_between_the_seed_and_the_record(self, glob):
        """The move was provably behaviour-preserving, across all 65 globs."""
        model = glob.rstrip("*")
        assert supports_vision(model) == shipped_facts_for_model(model).supports_vision

    def test_supports_vision_no_longer_reads_the_profile_registry(self):
        """Source check: the reader must be the facts path, not the seed.

        Behaviour alone cannot distinguish these while the two tables agree —
        which is the whole point of them agreeing — so the fence reads the
        source too.
        """
        import inspect

        src = inspect.getsource(supports_vision)
        assert "shipped_facts_for_model" in src
        assert "get_registry()" not in src

    def test_the_dead_profile_accessor_is_gone(self):
        """`get_model_profile()` had zero callers. Dead API keeps a dead
        vocabulary reachable, and reachable is how it comes back."""
        assert not hasattr(BaseProvider, "get_model_profile")


class TestTheSeedBridgeStaysHonest:
    """Whenever the 65 rows are re-authored as native ModelFacts, THIS is
    what makes the diff checkable: every field, every row."""

    #: `ModelFacts` field -> where it comes from on `ModelProfile`.
    #: Written out rather than inferred: a `getattr(profile, field, None)`
    #: fallback silently passes for any field the profile does NOT have,
    #: which is precisely the case this fence must catch.
    FROM_PROFILE = {
        "max_tokens": ("profile", "max_tokens"),
        "max_tool_iterations": ("profile", "max_tool_iterations"),
        "supports_reasoning": ("profile", "supports_reasoning"),
        "supports_vision": ("profile", "supports_vision"),
        "restricted_params": ("profile", "restricted_params"),
        "tier": ("profile", "tier"),
        "tool_mode": ("tool_calling", "mode"),
        "fallback_on_empty": ("tool_calling", "fallback_on_empty"),
        "fallback_on_failure": ("tool_calling", "fallback_on_failure"),
        "strip_json_from_text": ("tool_calling", "strip_json_from_text"),
        "parallel_tool_calls": ("tool_calling", "parallel_tool_calls"),
    }

    def test_the_mapping_covers_every_fact_field(self):
        """`wire_protocol` is the only field with no faithful seed source.

        The profile's `api_path` covered only OpenAI's two endpoints, and W2
        resolved three measured drifts against it, so the wire is stated per
        glob in the provider tables rather than derived from the seed.
        """
        assert set(self.FROM_PROFILE) | {"wire_protocol"} == set(FACT_FIELDS)

    @pytest.mark.parametrize("glob", GLOBS)
    def test_every_profile_row_flattens_to_its_facts_row(self, glob):
        profile = BUILTIN_PROFILES[glob]
        flattened = facts_from_profile(profile)
        for field, (owner, source) in self.FROM_PROFILE.items():
            src = profile if owner == "profile" else profile.tool_calling
            want = getattr(src, source)
            got = getattr(flattened, field)
            if isinstance(want, list):
                want = tuple(want)  # facts freeze what profiles kept mutable
            assert got == want, (glob, field)

    def test_every_profile_field_has_a_facts_home(self):
        """No field can be lost when the seed retires."""
        from ppxai.engine.model_profiles import ModelProfile

        profile_fields = set(ModelProfile.__dataclass_fields__) - {"tool_calling"}
        assert profile_fields <= set(FACT_FIELDS), (
            f"{sorted(profile_fields - set(FACT_FIELDS))} exist on ModelProfile "
            "with no ModelFacts field to migrate into — retiring the seed "
            "would silently drop them"
        )

    def test_the_seed_table_is_still_the_expected_size(self):
        """A canary on the migration: if the row count moves, the re-authoring
        either started or a profile was added to the retiring vocabulary."""
        assert len(BUILTIN_PROFILES) == 65

def _facts_source() -> str:
    """`model_facts.py` as text — the source checks below read the FILE."""
    from pathlib import Path

    return (
        Path(__file__).resolve().parents[1] / "ppxai" / "engine" / "model_facts.py"
    ).read_text(encoding="utf-8")


def _parse_literal_rows(src: str):
    """`[(glob, body), ...]` for every literal row in `SHIPPED_MODEL_FACTS`.

    Parsed from source rather than read from the dict, because the question
    these checks ask is whether a field is *stated* — and a row that omits
    one still has a value at runtime, so the object cannot answer it.
    """
    import re

    start = src.index("SHIPPED_MODEL_FACTS: Dict[str, ModelFacts] = {")
    end = src.index("\n}", start)
    return re.findall(r'"([^"]+)": ModelFacts\((.*?)\n    \),', src[start:end], re.S)


class TestTheLiteralRowsMatchTheSeed:
    """Item 65 step 1 — the fence that actually proves the transcription.

    The plan for this step named
    `test_every_profile_row_flattens_to_its_facts_row` as the proof that
    re-authoring `SHIPPED_MODEL_FACTS` as literals changed nothing. It is
    not: that test compares `facts_from_profile(profile)` against the
    PROFILE, so it validates the flattener and never reads the shipped table
    at all. Measured — mutating `tool_mode` in a literal row left all 135
    tests green, and no test file in the repo referenced
    `SHIPPED_MODEL_FACTS`.

    A migration whose safety argument rests on a test that cannot see the
    migrated data has no safety argument. This class is that missing
    comparison: every literal row against the seed output it replaced, field
    for field, for as long as both exist.

    Step 2 deletes the seed side. These tests go with it, replaced by
    invariants over the literals alone (row count, every row states
    `tool_mode`, the known non-default wires) — the same rewrite-don't-delete
    the sibling class documents.
    """

    @pytest.mark.parametrize("glob", GLOBS)
    def test_each_literal_row_equals_its_seed_row(self, glob):
        """The whole-record comparison, not field-by-field.

        Equality on the frozen dataclass covers every field including ones
        added later, which a hand-listed field loop would silently skip.
        """
        from dataclasses import replace

        from ppxai.engine.model_facts import (
            SHIPPED_MODEL_FACTS,
            _wire_for,
            facts_from_profile,
        )

        seeded = facts_from_profile(BUILTIN_PROFILES[glob])
        wire = _wire_for(glob)
        if wire:
            seeded = replace(seeded, wire_protocol=wire)
        assert SHIPPED_MODEL_FACTS[glob] == seeded, glob

    def test_the_table_has_exactly_the_seed_globs_in_order(self):
        """Key set AND order. `match_table` resolves exact ids before globs,
        so order is not load-bearing for correctness — but a dropped or
        duplicated key during transcription is, and this is what catches it.
        """
        from ppxai.engine.model_facts import SHIPPED_MODEL_FACTS

        assert list(SHIPPED_MODEL_FACTS) == list(BUILTIN_PROFILES)

    def test_every_row_states_tool_mode_explicitly(self):
        """The field that silently changes meaning (plan §1).

        `ToolCallingProfile.mode` defaulted to "native"; `ModelFacts.tool_mode`
        defaults to "prompt_based". 52 of the 65 rows relied on the profile
        default, so a row omitting `tool_mode` flips meaning with nothing
        visible in the diff. Source check, because a row that omits it still
        HAS a value — behaviour alone cannot tell stated from inherited.
        """
        rows = _parse_literal_rows(_facts_source())
        assert len(rows) == len(BUILTIN_PROFILES), (
            f"parsed {len(rows)} literal rows, expected {len(BUILTIN_PROFILES)}"
        )
        missing = [name for name, body in rows if "tool_mode=" not in body]
        assert not missing, f"rows not stating tool_mode: {missing}"

    def test_every_row_states_wire_protocol_explicitly(self):
        """`wire_protocol` was supplied from OUTSIDE the rows entirely
        (`_API_PATH_TO_WIRE` + `_WIRE_BY_GLOB`). Both vanish in step 2, so
        the value has to live on the row before they go."""
        rows = _parse_literal_rows(_facts_source())
        missing = [name for name, body in rows if "wire_protocol=" not in body]
        assert not missing, f"rows not stating wire_protocol: {missing}"

    def test_the_non_default_wires_survived_transcription(self):
        """The 15 rows whose wire was implicit before. A wrong value here
        sends a request to an endpoint that does not serve the model."""
        from ppxai.engine.model_facts import SHIPPED_MODEL_FACTS

        actual = {
            k: v.wire_protocol
            for k, v in SHIPPED_MODEL_FACTS.items()
            if v.wire_protocol != "chat_completions"
        }
        expected = {
            "gemini-2.5-pro*": "generate_content",
            "gemini-2.5-flash-lite*": "generate_content",
            "gemini-2.5-flash*": "generate_content",
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
        assert actual == expected

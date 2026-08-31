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

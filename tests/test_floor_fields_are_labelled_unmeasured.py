"""`/model info` calls a floor value a guess, not a measurement.

v1.19.3, reporting only.

`handle_model_info` labels every field `config` / `built-in` / `unmeasured`.
The label came from `is_unmeasured(model_id, provider_table)`, which answers
"did a row match" — so a matched provider row made all twelve fields print
`(built-in)`.

`PerplexityProvider` builds its gateway rows like this
(`AGENT_FLEET_FACTS`, `providers/perplexity.py`):

    replace(shipped_facts_for_model(glob.rstrip("*")), wire_protocol=...,
            max_tokens=..., tool_mode=...)

for the globs `anthropic/*`, `openai/*`, `google/*`, `xai/*`,
`perplexity/*`. `shipped_facts_for_model("openai/")` matches nothing, so the
SEED is `UNMEASURED` and only three fields are then deliberately set. The
other nine were floor values wearing a `(built-in)` label — across every
model those five globs serve, i.e. four vendors' worth.

`is_unmeasured`'s own docstring says what that defeats: *"an operator should
be told which of their models those are rather than discovering it when a
tool call silently degrades."* It was found by exactly that route — a model
reached through two providers answering `parallel_tool_calls` differently,
with one of the two answers labelled as built-in knowledge.

The floor is right as RESOLUTION (one wire, four vendors, a roster that
changes without notice) and was only ever wrong as a LABEL, so resolution and
`is_unmeasured` are untouched.

`model_fact_overrides` is patched out in every test here. Unpatched it reads
whichever `ppxai-config.json` the host resolves, which would make these
assertions depend on the operator's own file — the read-side asymmetry filed
as debt Item 69.
"""

from unittest.mock import MagicMock, patch

import pytest

import ppxai.commands.provider as provider_mod
from ppxai.commands.provider import handle_model_info
from ppxai.engine.model_facts import UNMEASURED, is_unmeasured
from ppxai.engine.providers.perplexity import AGENT_FLEET_FACTS, AGENT_FLEET_GLOBS

GATEWAY_MODEL = "openai/gpt-5.6-terra"

#: The three the fleet row states on purpose; everything else is the floor.
DELIBERATE = ("wire_protocol", "tool_mode", "max_tokens")

FLOOR_FIELDS = (
    "fallback_on_empty",
    "fallback_on_failure",
    "strip_json_from_text",
    "parallel_tool_calls",
    "max_tool_iterations",
)


def _ctx():
    ctx = MagicMock()
    ctx.engine_client._bootstrap_context = None
    return ctx


def _pairs(provider: str, model: str, overrides=None):
    with patch.object(
        provider_mod, "model_fact_overrides", return_value=overrides or {}
    ):
        result = handle_model_info(_ctx(), provider, model)
    return dict(getattr(result, "pairs", None) or getattr(result, "items", {}))


class TestThePremise:
    """The shape that makes the label wrong — pinned so it can't drift silently."""

    def test_the_fleet_row_is_the_floor_in_most_fields(self):
        row = AGENT_FLEET_FACTS["openai/*"]
        floor_valued = [
            f for f in UNMEASURED.__dataclass_fields__
            if getattr(row, f) == getattr(UNMEASURED, f)
        ]
        assert len(floor_valued) == 9, (
            "if the fleet row stops being the floor in nine fields, this whole "
            "test file is describing a shape that no longer exists"
        )
        for f in DELIBERATE:
            assert getattr(row, f) != getattr(UNMEASURED, f)

    def test_a_row_matches_so_the_model_reads_as_measured(self):
        """The trap itself: provider-aware says measured, global says not."""
        assert is_unmeasured(GATEWAY_MODEL, AGENT_FLEET_FACTS) is False
        assert is_unmeasured(GATEWAY_MODEL) is True

    def test_every_fleet_glob_is_affected(self):
        """Not two ids — four vendors' worth."""
        assert set(AGENT_FLEET_GLOBS) == {
            "anthropic/*", "openai/*", "google/*", "xai/*", "perplexity/*",
        }


class TestFloorFieldsSayUnmeasured:

    @pytest.mark.parametrize("field", FLOOR_FIELDS)
    def test_a_floor_field_is_not_called_built_in(self, field):
        pairs = _pairs("perplexity", GATEWAY_MODEL)
        assert "(unmeasured)" in pairs[field], (
            f"{field} is the UNMEASURED floor carried by the openai/* row; "
            f"printing it as (built-in) tells the operator a guess was a "
            f"measurement. Got: {pairs[field]!r}"
        )

    @pytest.mark.parametrize("field", ["wire_protocol", "tool_mode", "max_tokens"])
    def test_a_deliberate_field_still_says_built_in(self, field):
        """The fleet row's three real statements must not be maligned either."""
        pairs = _pairs("perplexity", GATEWAY_MODEL)
        assert "(built-in)" in pairs[field], (
            f"{field} IS stated by the fleet row; calling it unmeasured is the "
            f"opposite error. Got: {pairs[field]!r}"
        )

    def test_the_tier_row_says_unmeasured_too(self):
        """`tier` is one of the nine. It used to print "(no tier)" — "we have a
        row, it just has no tier" — when the truth is "no measurement"."""
        pairs = _pairs("perplexity", GATEWAY_MODEL)
        assert pairs["Tier"] == "(unmeasured)"


class TestAMeasuredFloorValueIsNotRelabelled:
    """The guard that keeps this from over-reaching.

    Comparing a value to `UNMEASURED` cannot, on its own, tell a guess from a
    measurement that agrees with the guess. `o3-mini` was MEASURED serial —
    exactly one call on every trial — so its `parallel_tool_calls=False` is a
    finding, not a floor, and must keep saying `built-in`. The discriminator
    is whether the model has a row of its own in `SHIPPED_MODEL_FACTS`.
    """

    @pytest.mark.parametrize("model", ["o3-mini", "gemini-3.1-pro-preview"])
    def test_a_measured_serial_model_still_says_built_in(self, model):
        assert is_unmeasured(model) is False, (
            f"{model} must have a global row for this test to mean anything"
        )
        provider = "openai" if model.startswith("o3") else "gemini"
        pairs = _pairs(provider, model)
        assert "False" in pairs["parallel_tool_calls"]
        assert "(built-in)" in pairs["parallel_tool_calls"], (
            "a measured serial model was relabelled as a guess — the "
            "over-reach this guard exists to prevent"
        )


class TestConfigStillWins:

    def test_an_operator_statement_is_labelled_config(self):
        """A config override outranks both other labels, floor-valued or not."""
        pairs = _pairs(
            "perplexity", GATEWAY_MODEL, overrides={"parallel_tool_calls": True}
        )
        assert "(config)" in pairs["parallel_tool_calls"]
        assert "True" in pairs["parallel_tool_calls"]

    def test_a_config_value_equal_to_the_floor_is_still_config(self):
        """Stating `False` yourself is a decision, not an absence of one."""
        pairs = _pairs(
            "perplexity", GATEWAY_MODEL, overrides={"parallel_tool_calls": False}
        )
        assert "(config)" in pairs["parallel_tool_calls"]

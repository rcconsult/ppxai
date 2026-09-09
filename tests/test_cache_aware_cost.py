"""Input is billed in three classes, not one (ADR 0008 follow-on).

`calculate_cost` knew only `input` and `output`. That is correct for every
provider ppxai spoke when it was written and wrong for a prompt-caching one:
a cache read costs a fraction of the input rate, so charging it as ordinary
input over-reports by up to 10x on the cached portion.

That is the opposite direction from debt Item 49's under-report and lands in
the same number users budget with — and it would have shipped the moment the
Anthropic provider sent its first `cache_control` request, because
`UsageStats` had nowhere to put the counts.

The load-bearing property is the LAST test: a caller that passes no cache
tokens gets the number it always got, so this is additive for every existing
provider rather than a repricing.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import ppxai.config.providers as providers
from ppxai.config.providers import (
    DEFAULT_CACHE_READ_MULTIPLIER,
    DEFAULT_CACHE_WRITE_MULTIPLIER,
    calculate_cost,
)
from ppxai.engine.types import UsageStats

MILLION = 1_000_000


@pytest.fixture
def priced():
    """One model at $10/$50 per MTok, with no explicit cache rates."""
    rows = {"m1": {"input": 10.0, "output": 50.0}}
    with patch.object(providers, "get_model_pricing", lambda provider=None: rows):
        yield rows


class TestCacheTokensArePricedByClass:
    def test_a_cache_read_costs_a_fraction_of_input(self, priced):
        read = calculate_cost(0, 0, "m1", None, 0, MILLION)
        assert read == pytest.approx(10.0 * DEFAULT_CACHE_READ_MULTIPLIER)
        assert read < calculate_cost(MILLION, 0, "m1"), (
            "a cache read priced at or above the input rate is the bug"
        )

    def test_a_cache_write_costs_more_than_input(self, priced):
        write = calculate_cost(0, 0, "m1", None, MILLION, 0)
        assert write == pytest.approx(10.0 * DEFAULT_CACHE_WRITE_MULTIPLIER)
        assert write > calculate_cost(MILLION, 0, "m1")

    def test_explicit_rates_in_the_pricing_row_win(self, priced):
        """A provider that prices caching differently states it; the
        multipliers are only the fallback."""
        priced["m1"].update(cache_write=3.0, cache_read=0.5)

        assert calculate_cost(0, 0, "m1", None, 0, MILLION) == pytest.approx(0.5)
        assert calculate_cost(0, 0, "m1", None, MILLION, 0) == pytest.approx(3.0)

    def test_the_classes_sum(self, priced):
        total = calculate_cost(MILLION, MILLION, "m1", None, MILLION, MILLION)
        assert total == pytest.approx(10.0 + 50.0 + 12.5 + 1.0)

    def test_an_unpriced_model_still_costs_nothing(self, priced):
        assert calculate_cost(MILLION, MILLION, "unknown", None, MILLION, MILLION) == 0.0


class TestUsageStatsCarriesTheCounts:
    def test_the_cache_fields_exist_and_default_to_zero(self):
        u = UsageStats()
        assert u.cache_creation_input_tokens == 0
        assert u.cache_read_input_tokens == 0


class TestExistingProvidersAreUnaffected:
    """The whole change is additive or it is a repricing, and a repricing of
    every historical number is not what this is."""

    @pytest.mark.parametrize(
        "prompt,completion", [(0, 0), (1, 1), (1000, 500), (999_999, 12_345)]
    )
    def test_omitting_cache_tokens_reproduces_the_old_number(
        self, priced, prompt, completion
    ):
        old_formula = (prompt / MILLION) * 10.0 + (completion / MILLION) * 50.0

        assert calculate_cost(prompt, completion, "m1") == pytest.approx(old_formula)
        assert calculate_cost(prompt, completion, "m1", None, 0, 0) == pytest.approx(
            old_formula
        )

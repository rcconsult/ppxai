"""Debt Item 66 — `/doctor probe` flags configured ids the catalog omits.

`MODEL_DEPRECATIONS` is hand-maintained and seeded from the ids ppxai
*ships*, so `/doctor`'s coverage is bounded by our catalog while its job is
warning about the *user's*. On 2026-08-31 that gap was five dead NVIDIA
models on one operator's machine with no deprecation row between them — one
retired five days before the sweep found it. A user running a model we never
shipped got silence, and silence reads as approval.

`detect_uncatalogued_models` closes that without a hand-maintained list, by
reusing the `/models` listing `/doctor probe` already fetches.

The tests below are mostly about what it must NOT claim. Today's sweep
established both directions of the listing's weakness, and each is a test
here:

- **Absence is not death.** A catalog can omit an alias or a private
  deployment. So a finding says "not listed, check it", never "dead" — and
  the check is skipped entirely for an unreachable provider or an empty
  catalog, because "we could not see" must never render as "yours are gone".
- **Presence is not life.** `moonshotai/kimi-k2.6` was listed by NVIDIA and
  still returned HTTP 404 "not found for account" on every call. That is why
  this function cannot be inverted into a liveness check, and why nothing
  here asserts a listed model is fine.
"""

import pytest

from ppxai.commands.doctor import (
    _format_uncatalogued_section,
    detect_uncatalogued_models,
)


def _cfg(models, provider="nvidia"):
    return {"providers": {provider: {"base_url": "https://x.invalid/v1",
                                     "models": {m: {} for m in models}}}}


def _probe(catalog, provider="nvidia", reachable=True):
    return {provider: {"reachable": reachable,
                       "endpoint_models": {m: 4096 for m in catalog}}}


class TestItFindsTheGapTheTableCannotCover:
    def test_a_configured_id_absent_from_the_catalog_is_reported(self):
        found = detect_uncatalogued_models(
            _cfg(["kept-model", "vanished-model"]), _probe(["kept-model"])
        )
        assert [f["model"] for f in found] == ["vanished-model"]

    def test_the_finding_carries_the_catalog_size(self):
        """A reader needs to know whether the catalog was plausible.

        "absent from 140 listed ids" is a real signal; "absent from 1" is a
        probe that saw almost nothing.
        """
        found = detect_uncatalogued_models(
            _cfg(["gone"]), _probe([f"m{i}" for i in range(140)])
        )
        assert found[0]["catalog_size"] == 140

    def test_a_listed_model_is_not_reported(self):
        assert detect_uncatalogued_models(_cfg(["here"]), _probe(["here"])) == []

    def test_it_catches_what_the_table_has_never_heard_of(self):
        """The Item 66 shape, stated so the premise cannot expire.

        The five NVIDIA models that filed the item are a poor fixture now:
        they all gained deprecation rows the same day, so this check
        correctly SKIPS them (see TestItDefersToTheDeprecationTable) and a
        test naming them would assert the opposite of the truth within hours
        of being written. What generalises is the shape — an id the operator
        runs, that the provider no longer lists, that our table has never
        heard of. That is the population the hand-maintained table cannot
        cover by construction, which is the whole point of Item 66.
        """
        from ppxai.engine.model_deprecations import classify_model

        unknown = [
            "vendor-x/model-we-never-shipped",
            "some-fork/private-build-2024",
        ]
        assert all(classify_model(m) is None for m in unknown), (
            "fixture drifted: these gained deprecation rows, so this test is "
            "measuring the skip path instead of the finding path"
        )
        found = detect_uncatalogued_models(
            _cfg(unknown + ["still-listed"]), _probe(["still-listed"])
        )
        assert sorted(f["model"] for f in found) == sorted(unknown)


class TestItRefusesToGuessWhenItCannotSee:
    """"We could not see the catalog" must never render as "yours are gone"."""

    def test_an_unreachable_provider_reports_nothing(self):
        probe = {"nvidia": {"reachable": False, "endpoint_models": {}}}
        assert detect_uncatalogued_models(_cfg(["a", "b"]), probe) == []

    def test_unreachable_beats_a_stale_non_empty_catalog(self):
        """The case that makes the reachability guard mean anything.

        The test above passes for the WRONG REASON: an unreachable probe also
        carries an empty `endpoint_models`, so the empty-catalog guard catches
        it first and the `reachable` check never has to work. Deleting that
        check left all 17 tests green — a guard with no fence under it.

        This is the input that separates them: unreachable, but carrying a
        non-empty catalog (a stale result, or a probe shape that populated
        models before failing). Only the `reachable` check can reject it, so
        this test fails the moment that check is weakened.

        Behaviourally it matters because "we could not reach the provider" and
        "the provider does not list your model" are different claims, and
        rendering the first as the second tells an operator their models are
        gone during an outage.
        """
        probe = {"nvidia": {"reachable": False,
                            "endpoint_models": {"stale-model": 4096}}}
        assert detect_uncatalogued_models(_cfg(["a", "b"]), probe) == []

    def test_an_empty_catalog_reports_nothing(self):
        """A parse that yielded nothing is not proof every model vanished.

        Without this, one gateway whose /models shape the probe cannot read
        would flag every model the operator has configured on it.
        """
        assert detect_uncatalogued_models(_cfg(["a", "b"]), _probe([])) == []

    def test_a_provider_missing_from_the_probe_reports_nothing(self):
        assert detect_uncatalogued_models(_cfg(["a"]), {}) == []

    @pytest.mark.parametrize("bad", [None, [], "not-a-dict", 42])
    def test_malformed_config_shapes_do_not_raise(self, bad):
        assert detect_uncatalogued_models({"providers": bad}, _probe(["x"])) == []

    def test_a_comment_key_is_not_a_model(self):
        cfg = _cfg(["real"])
        cfg["providers"]["nvidia"]["models"]["__comment_note"] = {}
        assert detect_uncatalogued_models(cfg, _probe(["real"])) == []


class TestItDefersToTheDeprecationTable:
    def test_a_model_with_a_deprecation_row_is_not_double_reported(self):
        """The table said something more precise — a DATED shutdown.

        Repeating it here as a vaguer "not listed" would be noise, and would
        make the specific finding harder to see.
        """
        # qwen3.5-122b-a10b carries a row (HTTP 410, EOL 2026-07-20).
        found = detect_uncatalogued_models(
            _cfg(["qwen/qwen3.5-122b-a10b", "unknown-to-the-table"]),
            _probe(["something-else"]),
        )
        assert [f["model"] for f in found] == ["unknown-to-the-table"]


class TestTheWordingDoesNotOverclaim:
    """The report must not assert death from an absence."""

    def test_it_is_silent_with_no_findings(self):
        assert _format_uncatalogued_section([]) == []

    def test_it_says_not_confirmed_dead(self):
        text = "\n".join(
            _format_uncatalogued_section(
                [{"provider": "nvidia", "model": "m", "catalog_size": 9}]
            )
        )
        assert "NOT confirmed dead" in text

    def test_it_names_both_failure_shapes_the_user_might_find(self):
        """410-with-a-date and 404-not-entitled mean different things, and
        the difference is what today's sweep cost a wrong default to learn."""
        text = "\n".join(
            _format_uncatalogued_section(
                [{"provider": "nvidia", "model": "m", "catalog_size": 9}]
            )
        )
        assert "410" in text and "404" in text

    def test_it_does_not_use_the_word_dead_as_a_verdict(self):
        text = "\n".join(
            _format_uncatalogued_section(
                [{"provider": "p", "model": "m", "catalog_size": 3}]
            )
        )
        # "NOT confirmed dead" is the only admissible use.
        assert text.count("dead") == text.count("NOT confirmed dead")

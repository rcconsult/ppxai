"""Operator config over the two fact records (plan I2, ADR 0012 §2 Q0e).

**Retargeted from the four-layer ladder this module used to test.** The
ladder was::

    1. providers.<p>.models.<m>.capabilities   config   (per model)
    2. provider code: per-model table                   (per model)
    3. providers.<p>.capabilities              config   (per provider)
    4. provider code: default_capabilities              (per provider)

Layers 2 and 3 had to interleave — specificity before authorship — because
a field could be stated at either level and something had to arbitrate.
Three implementations of that arbitration failed in a row, the last one
resolving `sonar` to `native` and reopening debt Item 43 on the very model
that produced it.

Q0e removed the need to arbitrate rather than fixing the arbitration: the
records are **disjoint**, so a provider block cannot state a model fact at
all. What used to be "specificity beats authorship" is now a type-level
guarantee, and the tests that asserted an ORDER between the two levels are
retargeted here into tests that assert the two levels cannot MEET —
`TestProviderConfigCannotReachAModelFact` is the same defect's fence,
stated negatively.

What survives unchanged is this module's discipline: these tests drive the
REAL config file through `find_config_file()` rather than stubbing the
block reader. That is deliberate — a per-model block is silently discarded
by `load_config()` (its `_convert_models_format` keeps only
id/name/description, verified 2026-08-15), which is the fifth time a config
key has been eaten by a whitelist on this project. A stubbed reader cannot
see that class of bug.
"""

from __future__ import annotations

import json

import pytest

from ppxai.config import facts_config as fcmod
from ppxai.engine.model_facts import shipped_facts_for_model
from ppxai.engine.providers.openai_native import OpenAINativeProvider
from ppxai.engine.providers.perplexity import PerplexityProvider
from ppxai.engine.types import ProviderCapabilities


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Write a real ppxai-config.json and point the loader at it."""

    def _write(providers):
        cfg = tmp_path / "ppxai-config.json"
        cfg.write_text(
            json.dumps(
                {"version": "1", "default_provider": "p", "providers": providers}
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(fcmod, "find_config_file", lambda: cfg)
        return cfg

    return _write


def _provider(**extra):
    base = {
        "name": "P",
        "base_url": "https://example.invalid",
        "api_key_env": "K",
    }
    base.update(extra)
    return {"p": base}


class TestModelFactsFromConfig:
    """`providers.<p>.models.<m>.facts` — the per-model record."""

    def test_nothing_configured_returns_empty(self, config_file):
        config_file(_provider())
        assert fcmod.model_fact_overrides("p", "m1") == {}

    def test_a_stated_field_is_read(self, config_file):
        config_file(_provider(models={"m1": {"facts": {"tool_mode": "native"}}}))
        assert fcmod.model_fact_overrides("p", "m1") == {"tool_mode": "native"}

    def test_one_model_does_not_leak_into_another(self, config_file):
        config_file(_provider(models={"m1": {"facts": {"tool_mode": "native"}}}))
        assert fcmod.model_fact_overrides("p", "m2") == {}

    def test_unknown_provider_yields_nothing(self, config_file):
        config_file(_provider())
        assert fcmod.model_fact_overrides("nope", "m1") == {}

    def test_no_model_yields_nothing(self, config_file):
        config_file(_provider(models={"m1": {"facts": {"tool_mode": "native"}}}))
        assert fcmod.model_fact_overrides("p", None) == {}


class TestProviderCapabilitiesFromConfig:
    """`providers.<p>.facts` — the per-endpoint record."""

    def test_a_stated_field_is_read(self, config_file):
        config_file(_provider(facts={"web_search": True}))
        assert fcmod.provider_fact_overrides("p") == {"web_search": True}

    def test_applied_onto_the_shipped_record(self, config_file):
        config_file(_provider(facts={"web_search": True}))
        got = fcmod.apply_provider_overrides(ProviderCapabilities(), "p")
        assert got.web_search is True

    def test_only_the_stated_field_moves(self, config_file):
        config_file(_provider(facts={"web_search": True}))
        got = fcmod.apply_provider_overrides(
            ProviderCapabilities(citations=True), "p"
        )
        assert got.web_search is True and got.citations is True

    def test_reaches_the_provider_accessor(self, config_file):
        config_file(_provider(facts={"web_search": True}))
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_capabilities().web_search is True


class TestProviderConfigCannotReachAModelFact:
    """The Item 43 fence, stated as a type-level guarantee.

    This class replaces `TestSpecificityBeatsAuthorship`. That class
    asserted an ORDER between a provider-wide config statement and a
    shipped per-model table — the arbitration three implementations got
    wrong. Under Q0e there is no order to get wrong: `tool_mode` is not a
    field of the provider record, so a provider-level statement about it is
    not a lower-priority answer, it is **not an answer at all**.

    The original defect was found against the developer's real config,
    which carries a provider-wide `native_tool_calling: true` for OpenAI —
    a restatement of the default written long before per-model tables
    existed. Under a flat ordering that silently re-enabled native tools for
    o4-mini and cancelled the benchmark-backed table (10.9% vs 62.5%).
    """

    def test_provider_block_does_not_cancel_a_shipped_model_row(self, config_file):
        config_file(_provider(facts={"tool_mode": "native"}))
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_facts_for_model("o4-mini").tool_mode == "prompt_based", (
            "a provider-level block reached a MODEL fact; the two records "
            "must be disjoint"
        )

    def test_sonar_cannot_be_made_tool_capable_from_a_provider_block(
        self, config_file
    ):
        """Debt Item 43's exact model, its exact regression."""
        config_file(
            {
                "perplexity": {
                    "name": "P",
                    "base_url": "https://api.perplexity.ai",
                    "api_key_env": "K",
                    "facts": {"tool_mode": "native"},
                }
            }
        )
        p = PerplexityProvider(api_key="k", provider_id="perplexity")
        assert p.get_facts_for_model("sonar").tool_mode == "prompt_based"

    def test_the_guard_agrees_end_to_end(self, config_file):
        """Not just the helper — the admission guard (the I3 lesson).

        I3 shipped a `NameError` that 38 tests missed by only ever calling
        the helper directly.
        """
        from ppxai.engine.task_authorizer import _reject_tool_incapable_model

        config_file(
            {
                "perplexity": {
                    "name": "P",
                    "base_url": "https://api.perplexity.ai",
                    "api_key_env": "K",
                    "facts": {"tool_mode": "native"},
                }
            }
        )
        with pytest.raises(Exception):
            _reject_tool_incapable_model("perplexity", "sonar", ["read_file"])

    def test_a_model_block_still_wins(self, config_file):
        """The operator CAN override the table — by naming the model."""
        config_file(
            _provider(models={"o4-mini": {"facts": {"tool_mode": "native"}}})
        )
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_facts_for_model("o4-mini").tool_mode == "native"

    def test_a_model_block_cannot_reach_an_endpoint_fact(self, config_file):
        """And the mirror direction — disjointness cuts both ways."""
        config_file(_provider(models={"m1": {"facts": {"web_search": True}}}))
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_capabilities().web_search is False
        assert fcmod.model_fact_overrides("p", "m1") == {}

    def test_the_provider_reader_itself_refuses_model_fields(self, config_file):
        """Mutation-proven fence.

        Widening `provider_fact_overrides`' whitelist to accept model fields
        left every other test in this class green: the model accessor reads
        model blocks, so it never saw the widened provider reader. The two
        readers need INDEPENDENT fences, or half the disjointness guarantee
        rests on nothing.
        """
        config_file(
            _provider(facts={"tool_mode": "native", "web_search": True})
        )
        assert fcmod.provider_fact_overrides("p") == {"web_search": True}

    def test_the_model_reader_itself_refuses_endpoint_fields(self, config_file):
        """The mirror fence, for the same reason."""
        config_file(
            _provider(
                models={"m1": {"facts": {"tool_mode": "native", "web_search": True}}}
            )
        )
        assert fcmod.model_fact_overrides("p", "m1") == {"tool_mode": "native"}

    def test_misplaced_fields_are_reported_not_silently_dropped(self, config_file):
        """Dropping is correct; dropping SILENTLY is not (Q0e)."""
        config_file(
            _provider(
                facts={"tool_mode": "native"},
                models={"m1": {"facts": {"web_search": True}}},
            )
        )
        found = fcmod.misplaced_fields_in_config()
        assert found["providers.p.facts"] == ["tool_mode"]
        assert found["providers.p.models.m1.facts"] == ["web_search"]


class TestMalformedConfigIsIgnored:
    """A hand-edited config must degrade, never crash a request."""

    @pytest.mark.parametrize(
        "providers",
        [
            {"p": {"facts": "not-a-dict"}},
            {"p": {"models": "not-a-dict"}},
            {"p": {"models": {"m1": "not-a-dict"}}},
            {"p": {"models": {"m1": {"facts": []}}}},
            {"p": []},
            [],
        ],
    )
    def test_shapes(self, config_file, providers):
        config_file(providers)
        assert fcmod.model_fact_overrides("p", "m1") == {}
        assert fcmod.provider_fact_overrides("p") == {}

    def test_unreadable_config_yields_nothing(self, monkeypatch):
        monkeypatch.setattr(
            fcmod, "find_config_file", lambda: (_ for _ in ()).throw(OSError("boom"))
        )
        assert fcmod.model_fact_overrides("p", "m1") == {}

    def test_unknown_keys_are_dropped(self, config_file):
        config_file(
            _provider(
                models={
                    "m1": {
                        "facts": {
                            "tool_mode": "native",
                            "nonsense": True,
                            "__comment": "a note",
                        }
                    }
                }
            )
        )
        assert fcmod.model_fact_overrides("p", "m1") == {"tool_mode": "native"}


class TestHandEditedValuesAreCoerced:
    """RETARGETED, not deleted — its premise is still alive.

    The predecessor module coerced `"true"`/`"1"`/`"yes"`/`"on"` because
    hand-edited JSON is the documented config path and this happened. The
    first draft of the unified reader dropped that coercion along with the
    old module, and both records regressed: `"false"` is TRUTHY, so a
    disabled flag silently enabled, and a string `max_tokens` reached
    `max()` in `chat.py` and raised `TypeError` mid-chat rather than at
    load. Both readers are covered here, for bool and for int.
    """

    def test_string_false_is_coerced_on_a_model_field(self, config_file):
        config_file(
            _provider(models={"m1": {"facts": {"fallback_on_empty": "false"}}})
        )
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_facts_for_model("m1").fallback_on_empty is False

    def test_string_true_is_coerced_on_a_model_field(self, config_file):
        config_file(
            _provider(models={"m1": {"facts": {"fallback_on_empty": "yes"}}})
        )
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_facts_for_model("m1").fallback_on_empty is True

    def test_string_false_is_coerced_on_an_endpoint_field(self, config_file):
        config_file(_provider(facts={"web_search": "false"}))
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_capabilities().web_search is False

    def test_string_int_is_coerced(self, config_file):
        """A string here reaches `max()` in chat.py and raises TypeError."""
        config_file(_provider(models={"m1": {"facts": {"max_tokens": "4096"}}}))
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        got = p.get_facts_for_model("m1").max_tokens
        assert got == 4096 and isinstance(got, int)

    def test_uncoercible_values_are_reported_not_guessed(self, config_file):
        config_file(_provider(models={"m1": {"facts": {"tier": 7}}}))
        found = fcmod.wrong_typed_fields_in_config()
        assert found["providers.p.models.m1.facts"] == ["tier"]

    def test_a_coercible_value_is_not_reported(self, config_file):
        config_file(_provider(models={"m1": {"facts": {"max_tokens": "4096"}}}))
        assert fcmod.wrong_typed_fields_in_config() == {}


class TestFieldWhitelistsTrackTheDataclasses:
    """The whitelist trap has eaten a config key five times on this project."""

    def test_model_fields_match_the_dataclass(self):
        from dataclasses import fields

        from ppxai.engine.model_facts import FACT_FIELDS, ModelFacts

        assert set(FACT_FIELDS) == {f.name for f in fields(ModelFacts)}

    def test_provider_fields_match_the_dataclass(self):
        from dataclasses import fields

        from ppxai.engine.model_facts import PROVIDER_FACT_FIELDS

        assert set(PROVIDER_FACT_FIELDS) == {
            f.name for f in fields(ProviderCapabilities)
        }

    def test_the_two_records_are_disjoint(self):
        """Q0e's load-bearing invariant, asserted as a set operation."""
        from ppxai.engine.model_facts import FACT_FIELDS, PROVIDER_FACT_FIELDS

        assert set(FACT_FIELDS) & set(PROVIDER_FACT_FIELDS) == set(), (
            "a field appears on both records, so it can be stated twice — "
            "which is the arbitration ADR 0012 exists to remove"
        )


class TestProviderIntegration:
    def test_config_overrides_a_shipped_per_model_row(self, config_file):
        config_file(
            _provider(models={"o4-mini": {"facts": {"tool_mode": "native"}}})
        )
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_facts_for_model("o4-mini").tool_mode == "native"

    def test_config_can_disable_a_shipped_capability(self, config_file):
        config_file(
            _provider(models={"gpt-5.2": {"facts": {"tool_mode": "prompt_based"}}})
        )
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_facts_for_model("gpt-5.2").tool_mode == "prompt_based"

    def test_unconfigured_model_is_untouched(self, config_file):
        config_file(
            _provider(models={"o4-mini": {"facts": {"tool_mode": "native"}}})
        )
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_facts_for_model("gpt-5.2") == shipped_facts_for_model("gpt-5.2")

    def test_shipped_table_survives_with_no_config(self, config_file):
        config_file(_provider())
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_facts_for_model("o4-mini").tool_mode == "prompt_based"
        assert p.get_facts_for_model("gpt-5.2").tool_mode != "prompt_based"


class TestTheUnmeasuredFloorIsProviderAware:
    """A conservative floor must be conservative FOR THIS PROVIDER.

    Found in review before W2 made `wire_protocol` load-bearing. The global
    floor says `chat_completions`, which is safe for every provider that
    speaks it and simply WRONG for Gemini: `GeminiProvider` has no such
    wire, so an unlisted Gemini model would have been routed to a handler
    the provider does not have — a wire bug, not a degraded answer.

    The fix stays inside Q0e: a provider supplies a COMPLETE alternative
    record, chosen whole. Nothing is merged field-by-field, so there is
    still nothing to arbitrate.
    """

    def test_an_unlisted_gemini_model_keeps_its_wire(self):
        from ppxai.engine.model_facts import facts_without_an_instance

        facts = facts_without_an_instance("gemini", "gemini-9-does-not-exist")
        assert facts.wire_protocol == "generate_content"

    def test_but_tool_mode_stays_conservative(self):
        """The wire is knowable without measuring; tool support is not."""
        from ppxai.engine.model_facts import facts_without_an_instance

        facts = facts_without_an_instance("gemini", "gemini-9-does-not-exist")
        assert facts.tool_mode == "prompt_based"

    def test_other_providers_keep_the_global_floor(self):
        from ppxai.engine.model_facts import UNMEASURED, facts_without_an_instance

        facts = facts_without_an_instance("openai", "nobody-measured-this")
        assert facts == UNMEASURED

    def test_the_floor_is_a_complete_record_not_a_partial_one(self):
        """Q0e: whole records are chosen, never merged."""
        from dataclasses import fields

        from ppxai.engine.model_facts import ModelFacts
        from ppxai.engine.providers.gemini import GeminiProvider

        floor = GeminiProvider.unmeasured_facts
        assert isinstance(floor, ModelFacts)
        for f in fields(ModelFacts):
            assert hasattr(floor, f.name)

    def test_every_provider_floor_matches_a_wire_it_can_speak(self):
        """Scoped fence: a floor naming an unreachable wire is the bug this
        class exists to prevent, so check them all rather than just Gemini."""
        from ppxai.engine.providers import _providers

        for name, cls in _providers.items():
            floor = getattr(cls, "unmeasured_facts", None)
            if floor is None:
                continue
            assert floor.wire_protocol in (
                "chat_completions",
                "responses",
                "generate_content",
                "messages",
            ), f"{name} declares an unknown wire: {floor.wire_protocol}"


class TestSubclassesOverrideTheShippedHook:
    """The split exists so a subclass cannot bypass the config layer.

    A provider that overrode the PUBLIC accessor would silently drop it —
    the same "override bypasses the shared path" shape that made the
    per-model hook unreachable before I1.
    """

    def test_no_provider_overrides_the_public_accessor(self):
        import re
        from pathlib import Path

        providers = (
            Path(__file__).resolve().parents[1] / "ppxai" / "engine" / "providers"
        )
        offenders = [
            path.name
            for path in providers.glob("*.py")
            if path.name != "base.py"
            and re.search(
                r"\n    def get_facts_for_model\(", path.read_text(encoding="utf-8")
            )
        ]
        assert offenders == [], (
            f"{offenders} override get_facts_for_model(), which skips the "
            "operator config layer. Override shipped_facts_for_model() or "
            "declare rows in shipped_model_facts instead."
        )

    def test_base_public_accessor_calls_the_shipped_hook(self):
        from dataclasses import replace

        seen = {}

        class _P(OpenAINativeProvider):
            def shipped_facts_for_model(self, model):
                seen["model"] = model
                return replace(shipped_facts_for_model(model), tool_mode="native")

        p = _P(api_key="sk-test", provider_id="p")
        p.get_facts_for_model("whatever")
        assert seen["model"] == "whatever"

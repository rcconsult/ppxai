"""ADR 0012 refactor (a) — `FactsResolver`: one rule, one resolution.

Three functions (`provider_class_for`, `capabilities_without_an_instance`,
`facts_without_an_instance`) were function-shaped carving around one missing
abstraction: each re-derived the provider class, so a caller needing two
answers resolved it twice.

Worse, the rule those functions exist to hold — *"a name that is not a
registered provider is served by `OpenAICompatibleProvider`"* — had grown
**five** spellings across the tree. Two of them bypassed
`provider_class_for` entirely:

- `task_authorizer` asked `get_provider_class(provider) is None`;
- `facts_config` fell back to a bare `ProviderCapabilities()`.

The second is the instructive one: it agreed with the real answer only
because `ProviderCapabilities()` and
`OpenAICompatibleProvider.default_capabilities` happen to be equal today.
`test_the_doctor_scaffold_is_not_a_coincidence` pins that, so the day either
changes, this fails instead of `/doctor` quietly offering a record the engine
does not use.
"""

import pytest

from ppxai.config.facts_config import complete_record_for
from ppxai.engine.model_facts import (
    FactsResolver,
    capabilities_without_an_instance,
    facts_without_an_instance,
    provider_class_for,
)
from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
from ppxai.engine.providers.perplexity import PerplexityProvider
from ppxai.engine.types import ProviderCapabilities


REGISTERED = ["perplexity", "openai", "gemini"]
TYPE_BASED = ["openrouter", "nvidia", "local-vllm", "a-name-nobody-registered"]


class TestTheOneFallbackRule:
    @pytest.mark.parametrize("provider", TYPE_BASED)
    def test_an_unregistered_name_resolves_to_the_compat_provider(self, provider):
        """Not `None`. A caller that stops at `None` disagrees with the
        deployment about what a provider is — which was a live defect on the
        oneshot enrichment gate."""
        assert FactsResolver(provider).provider_class is OpenAICompatibleProvider

    @pytest.mark.parametrize("provider", TYPE_BASED)
    def test_unregistered_is_not_the_same_as_unserviceable(self, provider):
        r = FactsResolver(provider)
        assert r.is_registered is False
        assert r.provider_class is not None
        assert r.capabilities() is not None

    def test_a_registered_name_resolves_to_its_own_class(self):
        r = FactsResolver("perplexity")
        assert r.provider_class is PerplexityProvider
        assert r.is_registered is True


class TestTheWrappersAgreeWithTheResolver:
    """The three functions survive as wrappers; they must not drift."""

    @pytest.mark.parametrize("provider", REGISTERED + TYPE_BASED)
    def test_provider_class_for(self, provider):
        assert provider_class_for(provider) is FactsResolver(provider).provider_class

    @pytest.mark.parametrize("provider", REGISTERED + TYPE_BASED)
    def test_capabilities_without_an_instance(self, provider):
        assert (
            capabilities_without_an_instance(provider)
            == FactsResolver(provider).capabilities()
        )

    @pytest.mark.parametrize(
        "provider,model",
        [
            ("perplexity", "perplexity/sonar"),
            ("perplexity", "sonar-pro"),
            ("openai", "gpt-5.1-codex"),
            ("openrouter", "anthropic/claude-sonnet-4"),
        ],
    )
    def test_facts_without_an_instance(self, provider, model):
        assert (
            facts_without_an_instance(provider, model)
            == FactsResolver(provider).facts(model)
        )


class TestTheDoctorScaffoldUsesTheSameResolution:
    """`/doctor` must offer the record the ENGINE will resolve."""

    @pytest.mark.parametrize("provider", REGISTERED + TYPE_BASED)
    def test_endpoint_scaffold_matches_the_resolver(self, provider):
        scaffold = complete_record_for(provider)
        resolved = FactsResolver(provider).capabilities()
        for field, value in scaffold.items():
            assert value == getattr(resolved, field), (provider, field)

    @pytest.mark.parametrize(
        "provider,model",
        [("perplexity", "perplexity/sonar"), ("openrouter", "some/model")],
    )
    def test_model_scaffold_matches_the_resolver(self, provider, model):
        scaffold = complete_record_for(provider, model)
        resolved = FactsResolver(provider).facts(model)
        for field, value in scaffold.items():
            want = getattr(resolved, field)
            if isinstance(want, tuple):
                want = list(want)
            assert value == want, (provider, model, field)

    def test_the_doctor_scaffold_is_not_a_coincidence(self):
        """The old fallback was right only by accident. Pin the accident.

        `facts_config` used to fall back to a bare `ProviderCapabilities()`
        for any name `get_provider_class` did not know. That matched the real
        answer solely because the dataclass defaults and
        `OpenAICompatibleProvider.default_capabilities` are equal. They are
        no longer load-bearing for `/doctor` — it goes through the resolver —
        but if they ever diverge, that is a fact worth knowing deliberately
        rather than discovering through a wrong scaffold.
        """
        assert ProviderCapabilities() == OpenAICompatibleProvider.default_capabilities, (
            "These have diverged. That is fine — /doctor no longer depends on "
            "them being equal — but check nothing else assumed it."
        )


class TestTheInstancePathAgreesWithTheClassPath:
    """The pair most likely to drift, and the one the other tests miss.

    `BaseProvider.get_facts_for_model()` (a live provider, API key in hand)
    and `FactsResolver.facts()` (no instance — the admission guard, the
    enrichment gate, `/doctor`) are two spellings of the same
    shipped -> resolve sequence. They share leaves, but each orchestrates
    the sequence itself, so a step added to one silently diverges from the
    other. Nothing else in this file compares them: the wrapper tests
    compare functions to the resolver, and the scaffold tests compare
    `/doctor` to the resolver — both class-path only.

    Divergence here is not theoretical. The whole reason the class path
    exists is that the guard cannot construct a provider, and the whole
    reason it must agree is that the guard's refusal has to predict what the
    send path will do.
    """

    @pytest.mark.parametrize(
        "model",
        ["sonar", "sonar-pro", "perplexity/sonar", "anthropic/claude-sonnet-5"],
    )
    def test_registered_provider_instance_matches_the_resolver(self, model):
        provider = PerplexityProvider(
            api_key="test-key", base_url="https://api.perplexity.ai"
        )
        assert provider.get_facts_for_model(model) == FactsResolver("perplexity").facts(
            model
        )

    @pytest.mark.parametrize("model", ["some/model", "llama-3-70b"])
    def test_type_based_provider_instance_matches_the_resolver(self, model):
        """The openai_compat case — where the class path has to FALL BACK."""
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            provider_id="openrouter",
        )
        assert provider.get_facts_for_model(model) == FactsResolver("openrouter").facts(
            model
        )

    def test_the_provider_floor_is_reached_by_both_paths(self):
        """The case that actually distinguishes them.

        My first version of this class compared Perplexity models only — and
        a mutation that dropped `unmeasured_facts` from the instance path
        passed all of it, because Perplexity HAS no floor (`None`) and every
        model tested was in a shipped table. Gemini is the provider that owns
        one, and an unlisted model is the only input that reads it: the
        global floor says `chat_completions`, which Gemini cannot speak.

        A fence that cannot fail is worse than no fence, so this is the row
        that makes the class mean something.
        """
        from ppxai.engine.providers.gemini import GeminiProvider

        model = "gemini-nothing-like-this-exists"
        resolved = FactsResolver("gemini").facts(model)
        assert resolved.wire_protocol == "generate_content", (
            "the provider floor is not being reached at all"
        )

        # __new__ + the one attribute the accessor reads: constructing a
        # real GeminiProvider needs the google-genai client, and this test is
        # about resolution, not transport.
        provider = GeminiProvider.__new__(GeminiProvider)
        provider.provider_id = "gemini"
        assert provider.get_facts_for_model(model) == resolved

    def test_the_endpoint_record_agrees_too(self):
        provider = PerplexityProvider(
            api_key="test-key", base_url="https://api.perplexity.ai"
        )
        assert provider.get_capabilities() == FactsResolver("perplexity").capabilities()


class TestOneResolutionAnswersEveryQuestion:
    def test_the_resolver_answers_all_three_from_one_construction(self):
        r = FactsResolver("perplexity")
        assert r.provider_class is PerplexityProvider
        assert r.capabilities().web_search is True
        assert r.facts("perplexity/sonar").wire_protocol == "responses"
        assert r.can_drive_a_tool_loop("perplexity/sonar") is True

    def test_can_drive_a_tool_loop_is_not_the_send_path_question(self):
        """Prompt-based tool calling is still tool calling.

        Conflating the two dropped every prompt-based model to closed-book on
        the `/v1/oneshot` enrichment gate.
        """
        r = FactsResolver("perplexity")
        assert r.facts("sonar").tool_mode == "prompt_based"
        assert r.can_drive_a_tool_loop("sonar") is True

    def test_it_is_frozen_so_it_cannot_drift_mid_use(self):
        r = FactsResolver("perplexity")
        with pytest.raises(Exception):
            r.provider = "openai"  # type: ignore[misc]

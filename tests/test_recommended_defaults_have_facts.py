"""Every model we recommend must be a model we can resolve facts for.

ADR 0012 Q0a gives unmeasured models a conservative floor: `prompt_based`
tool calling, `supports_vision=False`, zeroed budgets. That floor is right
*as a policy* — an unknown model should degrade safely rather than
optimistically.

It is the wrong answer for a model we ship as a **recommended default**,
because those we chose deliberately: an all-zeros row there does not mean
"unknown", it means "nobody added the row". The failure is silent in the
worst way — `openai_compat.py` gates native tool calling on
`get_facts_for_model(model).tool_mode != "prompt_based"`, so a floor row
turns a tool-capable model into a prompt-based one with no error, no log
line, and a plausible-looking degraded transcript.

This is debt Item 66's shape from the other direction: Item 66 flags
*configured* ids the provider's catalog never heard of; this flags
*recommended* ids that resolve to nothing.

Two measurement traps met while writing this file, both worth keeping:

1. **Resolve through `FactsResolver`, never the bare
   `shipped_facts_for_model`.** The first version used the global table and
   reported `perplexity/sonar` broken. It is not — `PerplexityProvider`
   carries its own `shipped_model_facts` with a `perplexity/*` row, and
   `FactsResolver` additionally applies operator config. Measuring a path
   production does not take invents defects.
2. **Only assert on providers that exist.** `RECOMMENDED_DEFAULTS` names
   `anthropic`, which has no provider implementation and appears in no
   shipped config — `feat/anthropic-provider` is reserved and untouched.
   Adding facts rows to satisfy it would assert measurements for a
   provider nobody can reach, which is worse than the gap.
"""

import json
from pathlib import Path

import pytest

from ppxai.config.facts_config import resolve_model_facts
from ppxai.engine.model_deprecations import RECOMMENDED_DEFAULTS
from ppxai.engine.facts_resolver import provider_class_for
from ppxai.engine.model_facts import shipped_facts_for_model

REPO_ROOT = Path(__file__).resolve().parent.parent


#: What a fresh install actually gets. `config/loader.py` bundles this file
#: into the PyInstaller binary and `/doctor` tells users to copy it, so it —
#: not the developer's working `ppxai-config.json` at the repo root — is the
#: config a recommendation has to resolve against.
SHIPPED_CONFIG = REPO_ROOT / "ppxai-config.example.json"


def _shipped_providers():
    """Providers the shipped config defines.

    Read from the file rather than the loaded config: the loader's search
    order (`PPXAI_CONFIG_FILE`, `./ppxai-config.json`, `~/.ppxai/...`) means
    the live config is whatever the developer happens to have, which is not
    what this is about.
    """
    cfg = json.loads(SHIPPED_CONFIG.read_text(encoding="utf-8"))
    return set(cfg.get("providers") or {})


def _reachable_recommendations():
    shipped = _shipped_providers()
    return sorted((p, m) for p, m in RECOMMENDED_DEFAULTS.items() if p in shipped)


def _shipped_config():
    return json.loads(SHIPPED_CONFIG.read_text(encoding="utf-8"))


def _facts(provider: str, model: str):
    """Effective facts for `model` **as shipped**: provider table, floor, config.

    Deliberately not `FactsResolver.facts()`. That reads the live config
    through `find_config_file()`, whose search order picks up the developer's
    working `./ppxai-config.json` — so a fence built on it measures whatever
    happens to be on this machine. Proven, not assumed: deleting the `facts`
    block for `gpt-5.6-terra` from the shipped config left the earlier
    version of this file passing 10/10, because it was never reading that
    file. `resolve_model_facts` takes an explicit `block`, which is the seam
    that makes "as shipped" testable.
    """
    cls = provider_class_for(provider)
    shipped = shipped_facts_for_model(
        model,
        getattr(cls, "shipped_model_facts", {}) or {},
        getattr(cls, "unmeasured_facts", None),
    )
    block = (_shipped_config().get("providers") or {}).get(provider) or {}
    return resolve_model_facts(shipped, provider, model, block)


class TestRecommendedDefaultsAreMeasured:
    def test_there_are_recommendations_to_check(self):
        """Guard against a vacuous pass.

        If `RECOMMENDED_DEFAULTS` is renamed or emptied, or the config's
        provider names drift from its keys, every parametrized test below
        collects zero cases and this file reports success while testing
        nothing.
        """
        assert _reachable_recommendations(), (
            "no recommended default is reachable from the shipped config — "
            "either RECOMMENDED_DEFAULTS or the config's provider keys moved"
        )

    @pytest.mark.parametrize("provider,model", _reachable_recommendations())
    def test_the_recommended_default_is_not_on_the_unmeasured_floor(self, provider, model):
        facts = _facts(provider, model)
        assert facts.tool_mode != "prompt_based", (
            f"{provider} recommends {model!r}, but no shipped row names it, so "
            f"it falls to the ADR 0012 Q0a floor and native tool calling is "
            f"silently disabled. Add a row to model_facts.py, or to that "
            f"provider's own `shipped_model_facts`."
        )

    @pytest.mark.parametrize("provider,model", _reachable_recommendations())
    def test_the_recommended_default_has_a_token_budget(self, provider, model):
        facts = _facts(provider, model)
        assert facts.max_tokens > 0, (
            f"{provider} recommends {model!r} with max_tokens=0 — the signature "
            f"of a missing row rather than a deliberate value."
        )


class TestTheUnreachableRecommendationIsDeliberate:
    """`anthropic` is recommended but unimplemented — pin that, don't hide it.

    Excluding it above is a judgement, so it should fail loudly if the
    situation changes rather than staying quietly excluded forever. When the
    provider lands, this test fails and the exclusion above stops applying.
    """

    def test_anthropic_is_still_the_only_unreachable_recommendation(self):
        unreachable = sorted(set(RECOMMENDED_DEFAULTS) - _shipped_providers())
        assert unreachable == ["anthropic"], (
            f"the set of recommended-but-unreachable providers changed to "
            f"{unreachable}. If a provider was added, it now needs shipped "
            f"facts rows; if anthropic shipped, drop this exclusion."
        )

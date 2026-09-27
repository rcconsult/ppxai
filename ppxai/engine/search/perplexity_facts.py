"""Perplexity model facts, kept apart from the chat provider.

Two consumers read these: `PerplexityProvider` (chat, deprecated
2026-09-27) and the `web_search` tool's Perplexity backend
(`engine/search/perplexity.py`, moved out of `tools/builtin/web_premium.py`
by ADR 0014 step 1), which picks its wire from the same rows. The
web_search backend stays when the chat provider goes, so the table cannot
live on the provider class. Data only: nothing here imports a provider —
this module lives under `ppxai/engine/search/` and is fenced by
`tests/test_search_layer_imports_no_providers.py`.
"""

from dataclasses import replace

from ..model_facts import shipped_facts_for_model

# Which Sonar models accept a `tools` array, measured live against
# api.perplexity.ai (2026-08-13, re-verified 2026-08-23):
#
#   sonar                 400  "Tool calling is not supported for this model"
#   sonar-pro             200  emits tool_calls  (full round-trip canary-verified)
#   sonar-reasoning-pro   200  emits tool_calls
#   sonar-deep-research   400  "Tool parameters must be a JSON object."
#
# The capability was per-PROVIDER until v1.19.1 and hardcoded False with the
# comment "Sonar models don't support native API tool_calls" — true when
# written, false since Perplexity shipped tool calling. That stale flag
# forced `profile.mode=prompt_based`, and debt Item 43's refusals /
# confabulations / external mis-grounding were all the prompt-based fallback
# failing, not the API. Data, not branches: add a row rather than a code path.
#
# NB the two 400s differ in kind. `sonar` states the capability is absent;
# `sonar-deep-research` complains about the SHAPE of the parameters, so it
# may be usable with a stricter schema — not chased, and it is being dropped
# from the shipped model list, so it is recorded here only as a known 400.
# ⚠ NO PRODUCTION READERS. Kept as the RECORD of a live measurement, not
# as a routing table — ADR 0012 §2 Q0e made tool mode a per-model fact, so
# the shipped seed rows decide: `sonar-pro` and `sonar-reasoning-pro`
# resolve `auto` (native with a prompt-based fallback) and `sonar` resolves
# `prompt_based`. A provider override forcing `native` here would silently
# DROP that fallback, which is why there is no override.
#
# The probe derives its expectations from the RESOLVER (see
# `expected_verdict`), not from these sets: a probe validating a table
# production does not consult reports agreement while behaviour drifts,
# which is debt Item 61's shape. `test_perplexity_model_capabilities.py`
# asserts the two still agree, so a drift between measurement and seed rows
# fails a test rather than passing silently.
PERPLEXITY_NATIVE_TOOL_MODELS = frozenset({
    "sonar-pro",
    "sonar-reasoning-pro",
})

#: Models that reject a `tools` array with HTTP 400 rather than degrading.
#: The distinction matters: a tool-capable request to one of these must be
#: refused up front, NOT routed to the prompt-based fallback, because that
#: fallback is precisely what produces Item 43's confabulated answers.
PERPLEXITY_TOOL_REJECTING_MODELS = frozenset({
    "sonar",
    "sonar-deep-research",
})


#: The Agent fleet: models reached through a Perplexity key over the
#: OpenAI **Responses** wire (ADR 0012 §5 / W3). Namespaced glob per
#: vendor, because that is exactly how Perplexity names them — a row per
#: model would be 38 rows restating one fact.
#:
#: Measured live at `https://api.perplexity.ai/v1/responses`:
#: 2026-08-15 (`anthropic/claude-sonnet-5` answered; a `tools=[...]`
#: request produced a real `function_call` item; the stock OpenAI SDK
#: drove it unchanged) and re-verified **2026-08-31** by
#: `scripts/probe-perplexity-capabilities.py --api-path responses`,
#: which reported NATIVE and the model actually calling the tool.
#:
#: `max_tokens` is NOT decoration here. The Agent API answers **400 for
#: `anthropic/*` without `max_output_tokens`** (measured at plan I2), and
#: the Responses handler only sends that key when the budget is non-zero
#: — so a fleet row resolving `max_tokens=0` would 400 on every request.
#: The budget is per-model request shaping expressed as table data,
#: which is the whole point: no code branch names a vendor.
AGENT_FLEET_GLOBS = (
    "anthropic/*",
    "openai/*",
    "google/*",
    "xai/*",
    # Sonar's OWN namespaced IDs. The bare form (`sonar`) is the
    # chat-completions name and keeps that wire; the namespaced form exists
    # on the Responses wire, and MEASURED 2026-08-31 it behaves differently
    # there — `perplexity/sonar` accepted a tools array and called the tool,
    # while bare `sonar` answers 400 "Tool calling is not supported for this
    # model" on chat-completions.
    #
    # That is the clearest evidence for this ADR's premise anywhere in the
    # tree: the SAME model has different capabilities on different wires, so
    # capability cannot be a property of the provider. Routing the namespaced
    # ID to chat-completions (which is where it landed before this row) sent
    # it to a wire that may not serve it at all.
    "perplexity/*",
)

#: The fleet does NATIVE tool calling — measured, not assumed. Without this
#: the rows would inherit the conservative `prompt_based` floor (Q0a), which
#: is the right default for an unmeasured model and simply wrong for a model
#: whose native `function_call` we have watched arrive twice:
#: 2026-08-15 (plan I2: a `tools=[...]` request produced
#: `{"type": "function_call", "name": "read_file", "call_id": "toolu_..."}`)
#: and 2026-08-31 (the probe reported NATIVE with the tool actually called).
#:
#: `auto` rather than `native`: native attempt, prompt-based fallback. The
#: fleet spans four vendors behind one wire and the roster changes without
#: notice, so a model that stops accepting a tools array degrades instead of
#: erroring. Sonar's own rows use `auto` for exactly this reason.
AGENT_FLEET_TOOL_MODE = "auto"

#: Default output budget for the fleet. Conservative and uniform: the
#: requirement being satisfied is "a budget is present", not any
#: particular size, and an operator `facts.max_tokens` override replaces
#: it per model.
AGENT_FLEET_MAX_TOKENS = 4096

#: The fleet's seed rows, assembled once at module scope. (These live here
#: rather than in the class body because a comprehension inside a class body
#: cannot see the class's own names — only module and function scopes are
#: visible to it.)
AGENT_FLEET_FACTS = {
    glob: replace(
        shipped_facts_for_model(glob.rstrip("*")),
        wire_protocol="responses",
        max_tokens=AGENT_FLEET_MAX_TOKENS,
        tool_mode=AGENT_FLEET_TOOL_MODE,
    )
    for glob in AGENT_FLEET_GLOBS
}

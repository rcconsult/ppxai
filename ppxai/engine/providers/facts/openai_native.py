"""Facts for `OpenAINativeProvider` (ADR 0016 §3). No SDK import."""

from dataclasses import replace

from ...model_facts import shipped_facts_for_model
from ...types import ProviderCapabilities
from ._record import ProviderFacts

#: Which models speak the Responses wire, as reviewed globs (ADR 0012 §3).
#: Replaces prefix matching, which drifted from the declared `api_path` table
#: in BOTH directions — measured on 2026-08-30, three disagreements:
#:
#:   gpt-5.3-codex  declared responses, routed chat  (prefix "gpt-5.1-codex"
#:                  does not match "gpt-5.3-codex"; "codex" is a PREFIX, not a
#:                  substring) -> a live 404 on oneshot, which has no fallback
#:   gpt-5.2-pro    declared chat, routed responses  -> router correct
#:   gpt-5-pro      declared chat, routed responses  -> router correct
#:
#: The pro rows are resolved in the ROUTER's favour on measured evidence:
#: commit 5e1ace2f ("Route gpt-5.2-pro to Responses API + add 404
#: auto-fallback") added them after OpenAI returned "not a chat model" for
#: Chat Completions. The declared `chat` was never exercised, because nothing
#: ever routed on `api_path`. The codex row is resolved in the PROFILE's
#: favour for the same reason: codex models 404 on Chat Completions, so
#: `responses` is what the model actually needs.
#:
#: gpt-5.5-pro was found in the same sweep: a pro model that NEITHER mechanism
#: sent to Responses (no prefix entry, profile says `chat`), registered by
#: c4b6f431 alongside gpt-5.3-codex without updating the routing tuple.
#:
#: Its row began as an ANALOGY with its siblings and is now MEASURED:
#: probed live 2026-08-31, `gpt-5.5-pro` on `/v1/chat/completions` returns
#: **404 "This is not a chat model and thus not supported in the
#: v1/chat/completions endpoint"** — the same error, verbatim, that put its
#: siblings on this list. Every row in this table now rests on an observed
#: response rather than on pattern-matching a model name.
#:
#: The 5.6 / 6 rows (2026-10-08) are a different failure with the same
#: answer: Chat Completions accepts these models but 400s on ANY tools array
#: ("Function tools with reasoning_effort are not supported"), because the
#: line defaults to a non-'none' reasoning effort. Measured for gpt-5.6-terra
#: (benchmarks/tuning/openai-5.6-tools-hazard.json); gpt-6-sol and gpt-6-luna
#: were each called on Responses with a function tool and answered with a
#: native function_call (2026-10-03, commit 6f0285bc). Until now only the
#: example config's rows said `responses`. Without those rows the three fell
#: to the unmeasured floor: Chat Completions with `prompt_based` tools, so no
#: tools array was sent and nothing 400'd. Since 2026-10-09 they have native
#: seed rows of their own in `model_facts.py`.
#:
#: gpt-5.4-pro (2026-10-08): the same 404 as its siblings, verbatim, probed
#: live on /v1/chat/completions — "This is not a chat model and thus not
#: supported". Its seed row (`gpt-5.4*`) said chat_completions and the example
#: config agreed; only the root config said responses.
RESPONSES_WIRE_GLOBS = (
    "gpt-5.1-codex*",
    "gpt-5.3-codex*",
    "codex*",
    "gpt-5-pro*",
    "gpt-5.2-pro*",
    "gpt-5.4-pro*",
    "gpt-5.5-pro*",
    "gpt-5.6*",
    "gpt-6-pro*",
    "gpt-6-sol*",
    "gpt-6-luna*",
)

# Models that perform better with prompt-based tool calling than native.
# Benchmark evidence:
#   o4-mini: 10.9% native → 62.5% prompt-based (native returns empty responses)
#   gpt-4.1-mini: 60.9% native → 71.9% prompt-based (hybrid tool_json_in_content)
PROMPT_BASED_MODEL_PREFIXES = ("o4-mini", "gpt-4.1-mini")


#: Benchmark-derived per-model rows (ADR 0012 §2 Q0e). Was
#: `shipped_capabilities_for_model`, which answered only the tool-calling
#: boolean while `BUILTIN_PROFILES` answered mode, limits and routing for
#: the same models — the two-systems split this ADR removes.
#:
#: `PROMPT_BASED_MODEL_PREFIXES` are benchmark-proven to score
#: significantly HIGHER with prompt-based tool calling (o4-mini: 10.9%%
#: native -> 62.5%% prompt-based, native returns empty responses;
#: gpt-4.1-mini: 60.9%% -> 71.9%%, hybrid tool_json_in_content).
#:
#: `RESPONSES_WIRE_GLOBS` (ADR 0012 W2) carry the OTHER fact: which wire
#: the model speaks. Both sets write into ONE table because they are
#: fields of one record — that is the whole point of Q0e. A model in both
#: sets would need one row stating both facts; none is today, and the
#: disjointness fence would catch it if that changed.
#:
#: A wire row overrides ONLY `wire_protocol`, so `codex*` and `gpt-6-pro*`
#: (which have no built-in profile) keep the conservative `prompt_based`
#: floor while still routing to Responses. That asymmetry is deliberate
#: per Q0a: the wire is a property of the endpoint and is knowable without
#: measuring, tool support is not.
SHIPPED_MODEL_FACTS = {
    **{
        prefix + "*": replace(shipped_facts_for_model(prefix), tool_mode="prompt_based")
        for prefix in PROMPT_BASED_MODEL_PREFIXES
    },
    **{
        glob: replace(
            shipped_facts_for_model(glob.rstrip("*")), wire_protocol="responses"
        )
        for glob in RESPONSES_WIRE_GLOBS
    },
}

FACTS = ProviderFacts(
    shipped_model_facts=SHIPPED_MODEL_FACTS,
    default_capabilities=ProviderCapabilities(
        web_search=False,
        web_fetch=False,
        weather=False,
        citations=False,
        streaming=True,
    ),
)

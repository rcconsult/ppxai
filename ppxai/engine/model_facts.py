"""Two per-model fact records and their resolvers (ADR 0012 §2 Q0e/Q0g).

Before this module ppxai answered per-model questions with **two** parallel
systems, each with its own table, its own config keys, its own merge site and
its own precedence order:

===========================  ===========================================
`ProviderCapabilities`       `ModelProfile` / `ToolCallingProfile`
===========================  ===========================================
6 booleans                   tool-calling strategy, limits, vision, tier
keyed by exact model id      keyed by glob (65 patterns)
`providers.<p>.capabilities` `providers.<p>.tool_calling`
merged in `BaseProvider`     merged in `chat.py::get_effective_profile`
===========================  ===========================================

They overlapped on the question that matters most — `native_tool_calling`
(bool) versus `tool_calling.mode` (`native`/`prompt_based`/`auto`) — and
**debt Item 43's Layer-2 bug lived exactly in that seam**: `chat.py` checked
`mode` first and short-circuited, so a capability resolving `native=True`
never reached the wire. Two systems answering one question in two orders is
how that survives review.

The fix is NOT a merge order. Three attempts to arbitrate the overlap failed
in a row (drop-if-default, an exemption list, then a value-comparison
heuristic that resolved `sonar` to `native` and reopened Item 43 on the very
model that produced it). The root cause was needing arbitration at all:
provider and model were modelled as two *levels of the same fields*, so every
field could be stated twice.

**The measurement said the domain does not work that way** (example config,
all 10 providers): endpoint abilities (`web_search`, `web_fetch`, `weather`,
`citations`) are stated 10× per provider and **0× per model**, because they
are facts about the *service* — Perplexity has built-in search, the OpenAI
API does not, and no model changes that. Tool-calling strategy is the
mirror image.

So the records are **disjoint** (Q0e):

* `ProviderCapabilities` (in `types.py`, retargeted in place per Q0g) — what
  the ENDPOINT does. `native_tool_calling` was removed from it here.
* `ModelFacts` (below) — what THIS MODEL does.

No field appears in both, so a provider block cannot state a model fact and
vice versa: **there is nothing to arbitrate**, and the five-rung ladder
collapses to two independent lookups. `tool_mode` living on the model record
is what makes the `sonar` regression structurally impossible — no
provider-wide setting can reach it.

Two further design points are load-bearing and were measured, not assumed:

**The conservative default wins (Q0a).** `native_tool_calling` defaulted
`False` ("unmeasured ⇒ assume not capable") while `ToolCallingProfile.mode`
defaulted `"native"`. Unifying on the profile's default would have flipped
every model absent from both tables to tool-capable — silently, through the
task-tier gate and oneshot enrichment. `tool_mode` therefore defaults to
`prompt_based`: a model that degrades is recoverable, one that answers HTTP
400 is not.

**Exact ids beat globs (Q0b).** "Specific before generic" was a *comment* in
`BUILTIN_PROFILES`, maintained by insertion order. :func:`match_table` is
two-pass — every wildcard-free key is tried before any glob — so correctness
no longer depends on where a row sits in a dict.

This is a LEAF MODULE — no ppxai imports except `model_profiles` (seed data)
and `types` (the provider record).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, fields as dataclass_fields, replace
from typing import Any, Dict, List, Literal, Optional

from .model_profiles import BUILTIN_PROFILES, ModelProfile
from .types import ProviderCapabilities

#: Wire protocols a model can be reached over. `chat_completions` is the
#: default because it is what every provider spoke before ADR 0012.
WireProtocol = Literal["chat_completions", "responses", "generate_content", "messages"]

#: Tool-calling strategy. `auto` tries native and falls back to prompt-based.
ToolMode = Literal["native", "prompt_based", "auto"]


@dataclass(frozen=True)
class ModelFacts:
    """Everything the engine knows about ONE MODEL (ADR 0012 §2 Q0e).

    Disjoint from `ProviderCapabilities` by construction: nothing here is a
    fact about the endpoint, and nothing there is a fact about the model.

    Frozen because a fact record is a *resolved answer*: callers that need a
    variation build one with `replace()` rather than mutating a value another
    caller may already hold.
    """

    # ── wire ──────────────────────────────────────────────────────────
    #: Which protocol handler reaches this model. Was `ToolCallingProfile.
    #: api_path`, which was declared, config-overridable, `/provider`-displayed
    #: and **never routed on** (debt Item 61). W2 makes routing consume it.
    wire_protocol: WireProtocol = "chat_completions"

    # ── tool calling ──────────────────────────────────────────────────
    #: Strategy. Defaults to the CONSERVATIVE value — see the module
    #: docstring; this is NOT the old `ToolCallingProfile` default.
    tool_mode: ToolMode = "prompt_based"
    fallback_on_empty: bool = False
    fallback_on_failure: bool = False
    strip_json_from_text: bool = False
    parallel_tool_calls: bool = False

    # ── limits and behaviour ──────────────────────────────────────────
    max_tokens: int = 0
    max_tool_iterations: int = 0
    supports_reasoning: bool = False
    supports_vision: bool = False
    restricted_params: tuple = ()
    tier: str = ""


#: Migration note: there is deliberately NO `native_tool_calling` property
#: here. ADR 0012 §2 Q0a deletes the boolean rather than keeping a readable
#: alias, because two spellings of one answer is precisely how Item 43's seam
#: bug survived review. Call sites ask `facts.tool_mode != "prompt_based"`.


#: Fields an operator may state in a `providers.<p>.models.<m>.facts` block.
#: Pinned to the dataclass so a new field cannot be silently unsettable — the
#: whitelist trap that has bitten this project five times.
FACT_FIELDS = tuple(f.name for f in dataclass_fields(ModelFacts))

#: Fields an operator may state in a `providers.<p>.facts` block. DERIVED
#: from `ProviderCapabilities`, for the same reason `FACT_FIELDS` is derived
#: from `ModelFacts`: a hand-typed whitelist silently stops covering a field
#: the moment someone adds one, which is the trap this project has hit five
#: times. Q0g removes `native_tool_calling` from that dataclass, so this
#: tuple follows automatically rather than needing a paired edit.
PROVIDER_FACT_FIELDS = tuple(f.name for f in dataclass_fields(ProviderCapabilities))


def match_table(table: Dict[str, Any], model: str) -> Optional[Any]:
    """Look `model` up in a glob-keyed table, exact keys first.

    Two passes, and the order is the point (ADR 0012 §2 Q0b):

    1. every wildcard-free key, compared case-insensitively;
    2. only then glob patterns, in insertion order.

    Without pass 1, an exact row for `gpt-5.1` placed after a generic
    `gpt-5*` glob would never win, and correctness would depend on where a
    maintainer happened to paste the row.
    """
    if not model:
        return None
    needle = model.lower()

    for key, value in table.items():
        if not _is_glob(key) and key.lower() == needle:
            return value

    for key, value in table.items():
        if _is_glob(key) and fnmatch.fnmatch(needle, key.lower()):
            return value

    return None


def _is_glob(key: str) -> bool:
    return any(ch in key for ch in "*?[")


def apply_overrides(facts: ModelFacts, overrides: Dict[str, Any]) -> ModelFacts:
    """Return `facts` with `overrides` applied, ignoring unknown keys.

    An unknown key is far more likely a typo or a future field than an
    instruction we can honour, and a config typo must never take the app
    down — the stance the superseded `config/capabilities.py` took, kept.
    """
    if not overrides:
        return facts
    clean = {k: v for k, v in overrides.items() if k in FACT_FIELDS}
    if not clean:
        return facts
    if "restricted_params" in clean and isinstance(clean["restricted_params"], list):
        clean["restricted_params"] = tuple(clean["restricted_params"])
    return replace(facts, **clean)


# ──────────────────────────────────────────────────────────────────────
# Shipped table
#
# Derived mechanically from `BUILTIN_PROFILES` rather than hand-rewritten.
# Q0e permits this: "code rows may rely on dataclass defaults; config rows
# may not" — a code row is complete *by construction* because the dataclass
# guarantees every field a value and the row is reviewed in a diff alongside
# the type. Re-typing 65 reviewed, benchmark-derived rows to restate defaults
# would add noise and a transcription-error surface without adding
# information.
#
# The ONE value that is not carried across is `mode`. `ToolCallingProfile`
# defaults it to "native" and `ModelFacts` to "prompt_based" (Q0a), so a row
# that never stated `mode` would silently flip meaning. `_facts_from_profile`
# therefore reads the profile's own default explicitly instead of letting the
# two defaults meet.
# ──────────────────────────────────────────────────────────────────────

#: `ToolCallingProfile.api_path` → `ModelFacts.wire_protocol`. `auto` (try
#: chat, fall back to responses on 404) is DOCUMENTED but was never
#: implemented, and ADR 0012 "Future" keeps it that way until a consumer
#: needs it — mapping it to a handler name would route to one that does not
#: exist, so it lands on the default and `/doctor` reports it.
_API_PATH_TO_WIRE: Dict[str, str] = {
    "chat": "chat_completions",
    "responses": "responses",
    "auto": "chat_completions",
}


def facts_from_profile(profile: ModelProfile) -> ModelFacts:
    """Flatten a legacy `ModelProfile` into a `ModelFacts` record.

    Public because it is the seed-data bridge AND the migration helper
    `/doctor` uses to show an operator what a legacy row becomes.
    """
    tc = profile.tool_calling
    return ModelFacts(
        wire_protocol=_API_PATH_TO_WIRE.get(tc.api_path, "chat_completions"),
        tool_mode=tc.mode,
        fallback_on_empty=tc.fallback_on_empty,
        fallback_on_failure=tc.fallback_on_failure,
        strip_json_from_text=tc.strip_json_from_text,
        parallel_tool_calls=tc.parallel_tool_calls,
        max_tokens=profile.max_tokens,
        max_tool_iterations=profile.max_tool_iterations,
        supports_reasoning=profile.supports_reasoning,
        supports_vision=profile.supports_vision,
        restricted_params=tuple(profile.restricted_params),
        tier=profile.tier,
    )


#: Model globs reached over a non-default wire. `ToolCallingProfile` had no
#: way to say this — its `api_path` covered only OpenAI's two endpoints — so
#: `generate_content` was implicit in "the Gemini provider is the only thing
#: that can serve these". ADR 0012 makes it a stated model fact.
#:
#: Uniform across a fleet is NOT the same as provider-level: every Gemini
#: model happens to share this wire today, but the statement still belongs
#: on the model, because `anthropic/claude-sonnet-5` is `responses` on
#: Perplexity and `chat_completions` on OpenRouter. Stating it per row keeps
#: the one case and the many cases in the same vocabulary.
_WIRE_BY_GLOB: Dict[str, str] = {
    "gemini-*": "generate_content",
    "gemma-*": "generate_content",
}


def _wire_for(pattern: str) -> Optional[str]:
    """The non-default wire for a seed glob, if it has one."""
    for glob, wire in _WIRE_BY_GLOB.items():
        if fnmatch.fnmatch(pattern.lower(), glob):
            return wire
    return None


def _seed_row(pattern: str, profile: ModelProfile) -> ModelFacts:
    """One seed row: the legacy profile, plus the wire it is reached over."""
    facts = facts_from_profile(profile)
    wire = _wire_for(pattern)
    return replace(facts, wire_protocol=wire) if wire else facts


#: The shipped per-model table: `{model_or_glob: complete ModelFacts}`.
#: Consulted via `match_table`, so exact ids beat globs regardless of
#: insertion order (Q0b) — unlike `ModelProfileRegistry`, which matched in
#: dict order and relied on a comment to keep specific rows above generic.
SHIPPED_MODEL_FACTS: Dict[str, ModelFacts] = {
    pattern: _seed_row(pattern, profile)
    for pattern, profile in BUILTIN_PROFILES.items()
}

#: The floor for a model no table names. Q0e calls this out as the *one*
#: fallback this ADR owns: not a layer anything inherits from, but a
#: conservative answer for the unmeasured — and `/doctor` reports every model
#: that lands on it, so "unmeasured" is visible rather than silent.
UNMEASURED = ModelFacts()


def shipped_facts_for_model(
    model: str,
    provider_table: Optional[Dict[str, ModelFacts]] = None,
    unmeasured: Optional[ModelFacts] = None,
) -> ModelFacts:
    """The shipped answer for `model`, or the conservative floor.

    Two tables, narrowest first: the provider's own rows, then the global
    baseline. **The provider dimension is load-bearing, not decoration** —
    one model id can be a different model, or the same model over a
    different wire, depending on whose endpoint serves it. The case that
    forced it: `anthropic/claude-sonnet-5` is reached over `responses` on
    Perplexity and over `chat_completions` on OpenRouter (ADR 0012 §"The
    fourth protocol"), so a single global row cannot state its
    `wire_protocol` correctly for both.

    Within each table, exact ids beat globs (Q0b). Between tables, the
    provider's row wins whole — a provider row is a complete record, so
    there is no field-level merge here and nothing to arbitrate.

    `unmeasured` is the provider's own floor for a model no table names.
    The global `UNMEASURED` says `wire_protocol="chat_completions"`, which
    is the safe answer for most providers and the WRONG one for Gemini —
    `GeminiProvider` can only speak `generate_content`, so an unlisted
    Gemini model would be routed to a handler the provider does not have
    once W2 makes `wire_protocol` load-bearing. A provider therefore
    supplies a COMPLETE alternative record (`BaseProvider.unmeasured_facts`),
    not a per-field default: Q0e's "nothing to arbitrate" holds because
    one whole record is chosen, never merged.
    """
    if provider_table:
        found = match_table(provider_table, model)
        if found is not None:
            return found
    found = match_table(SHIPPED_MODEL_FACTS, model)
    if found is not None:
        return found
    return unmeasured if unmeasured is not None else UNMEASURED


def provider_class_for(provider: str):
    """The class that will actually serve `provider`.

    Thin wrapper over :attr:`FactsResolver.provider_class` — kept because it
    has callers and reads well at a call site that needs only the class.
    """
    return FactsResolver(provider).provider_class


def capabilities_without_an_instance(provider: str):
    """Resolve the ENDPOINT record from the provider CLASS.

    Thin wrapper over :meth:`FactsResolver.capabilities`.
    """
    return FactsResolver(provider).capabilities()


def can_drive_a_tool_loop(facts: ModelFacts) -> bool:
    """Whether a model can run a tool loop AT ALL — any strategy.

    Distinct from "should we send a native tools array"
    (`tool_mode != "prompt_based"`), and conflating the two was a defect on
    the `/v1/oneshot` enrichment gate: prompt-based tool calling is still
    tool calling — `chat.py` parses tool JSON out of the response text,
    which is what `prompt_based` MEANS — so a model marked prompt-based
    dropped to closed-book instead of running the loop. Latent rather than
    live: `execution.run.web_search` defaults OFF, so the gate answered
    `closed-book` for every model regardless until an operator opted in.

    Pre-ADR the gate asked `mode != "none"`, and `"none"` is the only value
    that ever meant incapable. It has no successor in `ToolMode`, so every
    current value can drive a loop. If a "no tools" state is ever wanted it
    is a new `ToolMode` value and an ADR line, not a re-reading of this
    one.
    """
    return facts.tool_mode in ("native", "prompt_based", "auto")


def facts_without_an_instance(provider: str, model: str) -> ModelFacts:
    """Resolve `model` on `provider` from the provider CLASS.

    Thin wrapper over :meth:`FactsResolver.facts`. The one resolution path
    for callers with no provider instance — the admission guard (no API key
    at admission time), the oneshot enrichment gate, `/doctor`, `/provider`.
    Each used to spell out the same four-line incantation; four copies of one
    sequence is how a fifth caller gets a rung wrong, which had already
    happened twice when this was written.
    """
    return FactsResolver(provider).facts(model)


@dataclass(frozen=True)
class FactsResolver:
    """Everything resolvable about a provider from its NAME alone.

    Constructed from a provider key; resolves the class once (by the one
    fallback rule), then answers the endpoint record, any model's facts, and
    whether a model can drive a tool loop.

    **Why a type rather than three functions.** `provider_class_for`,
    `capabilities_without_an_instance` and `facts_without_an_instance` were
    function-shaped carving around one missing abstraction: each re-derived
    the class, and callers that needed two answers resolved it twice. Worse,
    the "unknown name means `OpenAICompatibleProvider`" rule had grown FIVE
    spellings across the tree — `provider_class_for`, `provider_ops`'s
    construction fallback, `task_authorizer`'s `get_provider_class(...) is
    None` early return, and `facts_config`'s fallback to a bare
    `ProviderCapabilities()`. That last one agrees with the real answer only
    because `ProviderCapabilities()` and
    `OpenAICompatibleProvider.default_capabilities` happen to be equal today;
    change either and `/doctor` starts scaffolding a record the engine does
    not use, silently.

    One type, one rule, one resolution. The three functions remain as thin
    wrappers — they have callers, and a resolver whose adoption requires
    touching every call site in one commit is a worse trade than one that
    can be adopted where it helps.
    """

    provider: str

    @property
    def provider_class(self):
        """The class that will actually serve this provider.

        `get_provider_class()` alone is NOT the answer: it returns `None`
        for every openai_compat-TYPE provider — openrouter, nvidia, a vLLM
        box, an Ollama host — because those are configured by name, not
        registered. A caller that stops at `None` disagrees with the
        deployment about what a provider is, which was a live defect on the
        oneshot enrichment gate.
        """
        from .providers import get_provider_class
        from .providers.openai_compat import OpenAICompatibleProvider

        try:
            cls = get_provider_class(self.provider)
        except Exception:  # noqa: BLE001
            cls = None
        return cls if cls is not None else OpenAICompatibleProvider

    @property
    def is_registered(self) -> bool:
        """Whether this name is a REGISTERED provider, not a type-based one.

        The honest form of `get_provider_class(p) is None`. Callers wanting
        "do we know this provider at all?" should ask this rather than
        re-deriving it — and should notice that the answer being `False`
        does not mean unserviceable, only unregistered.
        """
        from .providers import get_provider_class

        try:
            return get_provider_class(self.provider) is not None
        except Exception:  # noqa: BLE001
            return False

    def capabilities(self):
        """The ENDPOINT record, with operator overrides applied."""
        from ..config.facts_config import apply_provider_overrides

        return apply_provider_overrides(
            self.provider_class.default_capabilities, self.provider
        )

    def facts(self, model: str) -> ModelFacts:
        """The MODEL record: shipped table, provider floor, operator config."""
        from ..config.facts_config import resolve_model_facts

        cls = self.provider_class
        table = getattr(cls, "shipped_model_facts", {}) or {}
        floor = getattr(cls, "unmeasured_facts", None)
        return resolve_model_facts(
            shipped_facts_for_model(model, table, floor), self.provider, model
        )

    def can_drive_a_tool_loop(self, model: str) -> bool:
        """Whether `model` can run a tool loop at all — any strategy."""
        return can_drive_a_tool_loop(self.facts(model))


def is_unmeasured(
    model: str, provider_table: Optional[Dict[str, ModelFacts]] = None
) -> bool:
    """True when no shipped row names `model` (what `/doctor` reports).

    Q0e requires the floor to be *visible*: a model landing on `UNMEASURED`
    is running on an assumption, not a measurement, and an operator should
    be told which of their models those are rather than discovering it when
    a tool call silently degrades.
    """
    if provider_table and match_table(provider_table, model) is not None:
        return False
    return match_table(SHIPPED_MODEL_FACTS, model) is None


# ──────────────────────────────────────────────────────────────────────
# Legacy config vocabulary — for `/doctor` only, never for resolution
# ──────────────────────────────────────────────────────────────────────

#: Legacy config keys and where they moved. Used by `/doctor` to REPORT and
#: REWRITE a stale config (ADR 0012 §2 Q0c) — **not** by the resolver, which
#: reads one vocabulary only. Accepting these at resolution time would be a
#: permanent dual-read, which is what the clean break exists to prevent.
#:
#: Measured 2026-08-30: `openrouter` and `ollama` in the shipped example
#: config carry `capabilities.native_tool_calling: true` and **no
#: `tool_calling` block at all**, so that key is the only thing holding
#: native tool calling on for them. An unmigrated config therefore DEGRADES
#: those models to the conservative default rather than failing loudly —
#: which is why `/doctor` must surface them and why the example config ships
#: migrated. The migration cost of ADR 0012 lives in field configs.
#: Legacy `tool_calling.mode` values with no successor in `ToolMode`.
#: `"none"` meant "this model cannot call tools at all" — the only value the
#: pre-ADR oneshot gate treated as incapable. `ToolMode` has no equivalent
#: (`prompt_based` still calls tools, just differently), so translating it
#: would silently invent a meaning. `/doctor` reports it instead.
UNTRANSLATABLE_MODES = frozenset({"none"})

LEGACY_KEY_TRANSLATIONS: Dict[str, Any] = {
    "native_tool_calling": ("tool_mode", lambda v: "native" if v else "prompt_based"),
    "mode": ("tool_mode", lambda v: v),
    "api_path": (
        "wire_protocol",
        lambda v: _API_PATH_TO_WIRE.get(v, "chat_completions"),
    ),
}


def translate_legacy(block: Dict[str, Any]) -> Dict[str, Any]:
    """Map a legacy `capabilities`/`tool_calling` block onto fact keys.

    Used by `/doctor` to compute a rewrite. **Not** used when resolving
    operator config — see `LEGACY_KEY_TRANSLATIONS`.
    """
    out: Dict[str, Any] = {}
    for key, value in (block or {}).items():
        if key.startswith("__comment"):
            continue
        if key in LEGACY_KEY_TRANSLATIONS:
            new_key, convert = LEGACY_KEY_TRANSLATIONS[key]
            out[new_key] = convert(value)
        elif key in FACT_FIELDS or key in PROVIDER_FACT_FIELDS:
            out[key] = value
    return out


def legacy_keys_in(block: Dict[str, Any]) -> List[str]:
    """Legacy keys present in `block` — what `/doctor` reports and rewrites."""
    return [k for k in (block or {}) if k in LEGACY_KEY_TRANSLATIONS]

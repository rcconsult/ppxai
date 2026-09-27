# ADR 0014: Web search is its own layer; grounding retrieves before the model call

- **Status:** Proposed (2026-09-27)
- **Deciders:** owner
- **Target:** the v1.19.x cycle (owner, 2026-09-27). Which patch it lands in
  is still open (question 1 below).
- **Related:** ADR 0009 (task execution profiles, the shared backend
  resolver, the §4 oneshot gating table), ADR 0011 (`execution.run.*`,
  which owns `grounding`), ADR 0012 (per-model facts; Perplexity's two
  wires), ADR 0008 (cross-tier cost), and ADR 0015 (removal of the Perplexity
  chat provider, which depends on this record).

## Context

On 2026-09-27 the owner deprecated Perplexity as a chat provider and kept
it as a web-search backend (phase 1, `a6500041`). Two instructions came
with the next step:

1. Perplexity must stay available **as the grounding option**.
2. Web search should be an abstraction **separate from calling a provider's
   model API**.

### What already exists

Half of the separation is built:

- **The search backends are provider-independent.**
  `web_search_perplexity(query, n)` and `web_search_gemini(query, n)` in
  `ppxai/engine/tools/builtin/web_premium.py` build their own clients and
  return `(answer, citations, ToolUsage)`. DuckDuckGo lives in
  `tools/builtin/web.py`. None of them call a chat provider. Since
  `a6500041` the web_search tool no longer imports the Perplexity provider
  class either; its wire fact comes from `providers/perplexity_facts.py`.
- **One resolver picks the backend.** `tools/search_backends.py::
  resolve_web_search_backend()` (ADR 0009 step 4) applies
  `tools.web_search.order`, per-provider `preferred`/`strict`, backend
  usability (keys), and the egress predicate. Its `BACKEND_HOSTS` feeds
  egress enumeration. `web_search_premium()` walks the resolved candidates.

### What is still tangled

- **Grounding belongs to the chat provider.** `execution.run.grounding`
  (ADR 0011 Q5) resolves to the `native` path in
  `facts_resolver.get_effective_oneshot_path`: *grounding on AND the
  provider's `capabilities.web_search`*. `oneshot.py::
  _apply_oneshot_grounding` then flips the provider's own search:
  `enable_grounding = True` for Gemini, and nothing for Perplexity, because
  Sonar always searches. **For Perplexity, grounding IS the chat
  provider.** Removing the chat provider (ADR 0015) would remove Perplexity
  grounding with it, which the owner has ruled out.
- **Grounding is provider-limited.** Only providers with a native search
  hook can ground. An OpenAI, NVIDIA, local vLLM or Anthropic model cannot,
  even though the search layer could serve it.
- **The search backends live in a tool module.** They are functions inside
  `web_premium.py`, reached by the tool, and have no home that grounding,
  `/doctor` or a future consumer can depend on without importing a tool
  module.

### Why the current design was chosen, and what changes

The native path ("Option A", `docs/archive/plan-oneshot-grounding.md`)
was chosen for its **egress property**: retrieval happens inside the
provider's own API call, so a grounded oneshot reaches no host beyond the
one it already calls, and no model-named URL is ever fetched. Retrieval
before the call gives that up in one specific way. The prompt, or a query
derived from it, now also goes to the **search backend's host**. If the
chat model is a local vLLM and the search backend is Perplexity, a
grounded prompt leaves the machine where before it did not. This is the
central trade-off of this record. It is handled by the rules in Decision 4.
It does not re-open the tool-loop exfiltration surface: no model-named URL
fetch, no `fetch_url`, no model-chosen query.

## Decision

### 1. A search layer: `ppxai/engine/search/`

A package that owns web search and knows nothing about chat providers.

- **`SearchBackend`** (a `Protocol`): `id: str`, `hosts: tuple[str, ...]`,
  `usable() -> bool` (key present, etc.), and
  `async search(query: str, n: int) -> SearchResult`.
- **`SearchResult`**: `backend`, `answer: str`, `citations: list[str]`,
  `usage: ToolUsage | None`.
- **Backends:** `perplexity` (Sonar, wire from `perplexity_facts`),
  `gemini` (Google Search over REST, as today; not the chat provider), and
  `duckduckgo`. The code moves out of `web_premium.py` and `web.py`
  unchanged in behaviour.
- **The resolver moves in**: `search_backends.py` becomes
  `search/resolver.py`, with the same function and the same semantics
  (order, preferred, strict, egress predicate). Internal module: every
  importer is updated, with no re-export shim. It is not on ppxai-sre's
  pinned import surface (`tests/test_consumer_import_surface.py`), which
  was checked on 2026-09-27.
- **A fence:** `ppxai/engine/search/` imports nothing from
  `ppxai.engine.providers`, pinned by a test in the style of
  `TestEngineImportsNoCommands`.

### 2. The `web_search` tool becomes an adapter

`web_search_premium()` becomes: resolve, walk the candidates, format. The
walk calls `SearchBackend.search()`. Output format, fallback, `strict`,
usage recording and the per-turn budgets (`tool_call_budgets`) are
unchanged. The tool, grounding and `/task` grants then share one
implementation, one cost record and one egress check.

### 3. Grounding retrieves before the model call

With grounding on, the oneshot tier (`/v1/oneshot`, `/v1/agent/run`) does
the following:

1. Resolves the backend chain exactly as `web_search` does, scoped to the
   request's provider.
2. Searches once with the user's prompt as the query, walking the chain on
   failure unless the resolution is `strict`.
3. Adds the result to the request as context: the backend's answer plus a
   numbered source list, inside a clearly delimited block the model is
   told to use and cite.
4. Makes the model call with **no tools**, exactly as the ungrounded
   oneshot does.

Consequences:

- **Perplexity is the grounding backend by default.** It is first in
  `AUTO_ORDER` and is used whenever `PERPLEXITY_API_KEY` is set, whichever
  provider answers. An operator reorders or pins it with the existing
  `tools.web_search.order` / `preferred` / `strict`. No new keys are needed.
- **Every chat provider can be grounded**, not only those with a native
  hook.
- **Grounding is guaranteed**: the search always runs, unlike the tool
  loop, where the model decides whether to call it.
- **The gating table** (`get_effective_oneshot_path`) gains the new path,
  `"retrieve"`, and keeps "enrichment XOR grounding, never both" from
  ADR 0009 §4.
- **Provider-native search becomes an explicit option.** Gemini's
  in-call Google Search remains available as `grounding: "native"`, with
  today's egress property, for operators who want it. It is no longer what
  `grounding: true` means (question 2).

### 4. Egress and data-flow rules for retrieval

- **Default OFF, unchanged.** No grounding config means no search.
- **The backend host must pass the egress ceiling.** `execution.
  egress_ceiling` and the per-request egress predicate apply to the
  backend's `hosts`, exactly as they do for the web_search tool. A
  resolution with no allowed backend grounds nothing and says so. It never
  falls back to an unchecked host.
- **`strict` pins one backend**, so a run can be held to one known search
  host.
- **Only the prompt text is sent**, never history, attachments or
  retrieved content from another call. The query is not model-written
  (question 3).
- **`/doctor` shows it**: the effective grounding path per configured
  model, the backend it would use, and the host the prompt would reach.

### 5. Wire contract

`POST /v1/oneshot` stays byte-identical: same request, same response
fields. Citations reach the caller inside the answer text. A structured
`citations` field would be an additive change to the one stable external
surface, and is deferred to its own decision (question 4).

### 6. Cost

Retrieval usage is recorded through the existing `ToolUsage` path, so it
appears in `/cost` under the run tier (ADR 0008) and in the run's usage
events, like a web_search tool call.

## Why this and not the alternatives

- **Keep grounding on the chat provider (status quo).** This is what makes
  ADR 0015 impossible without losing Perplexity grounding, and it limits
  grounding to providers with a native hook.
- **Grounding through the tool loop (`execution.run.web_search`).** It
  already exists, but the model may answer without searching. It costs a
  second model's tokens and a round trip, and the citations are whatever
  the model chooses to repeat. Retrieval before the call is deterministic
  and cheaper, and it keeps the oneshot model call tool-free.
- **A dedicated "Perplexity grounding" call, special-cased.** This solves
  the owner's first instruction but not the second. Every backend would
  need its own special case, and grounding would stay outside the resolver
  that already carries order, strict and egress.

## Open questions (owner)

1. **Which patch release** carries this: v1.19.3 (prepared, not yet
   released, already large) or v1.19.4. The recommendation is v1.19.4, so
   v1.19.3 ships the phase-1 deprecation warning first.
2. **What `grounding: true` means from now on.** Recommendation: `true`
   means `"retrieve"`, and `"native"` is the explicit opt-in. That changes
   behaviour for an operator who set `true` and serves Gemini: the search
   moves from Gemini's in-call Google Search to the resolved backend,
   Perplexity first. The alternative keeps `true` = `native` where
   available and `retrieve` otherwise, which is more compatible and less
   predictable.
3. **The query.** The raw prompt (recommended to start), or a query
   rewritten by a cheap model. Rewriting improves recall but adds a model
   call, and a model-written query is a small step back toward the
   model-steered surface Option A avoided.
4. **Structured citations** on `/v1/oneshot` (an additive response
   field): a separate decision on the stable surface, not bundled here.
5. **Injected size.** The cap on retrieved text, and whether it comes from
   `context.max_injection_size` or a new key.

## Future / proper solution

- `fetch_url` and the weather tool on the same layer, if a second consumer
  appears.
- Result caching per (backend, query) within a run.
- Grounding for the interactive chat path (`/chat`), which today relies on
  the tool loop, if the owner wants the same guarantee there.

## Triggers to revisit

- A search backend whose API cannot be called standalone, only as part of a
  chat call. It would not fit `SearchBackend` as defined.
- An operator requirement that grounded prompts never leave the chat
  provider's host. That is `native`, and would make it a first-class
  default again.
- ppxai-sre's Pattern-A classifier landing on `/v1/oneshot` with grounding.
  Check the query and citation choices against real use.

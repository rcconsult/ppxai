# ADR 0014: Web search is its own layer; grounding retrieves before the model call

- **Status:** Implemented and **closed** (2026-09-28). Built 2026-09-27 (`b3c66740` layer, `05bb0ddb` retrieval grounding): direction approved by the owner, open questions answered below; default backend order revised the same day (Decision 3). Closed by the owner on 2026-09-28, which also accepted the `grounding.sources` field added in `c3e56736` as the structured-citations decision §5 had deferred.
- **Deciders:** owner
- **Target:** v1.19.3, together with ADR 0015 (owner, 2026-09-27).
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

- **Perplexity stays a grounding backend.** As accepted, it was first in
  `AUTO_ORDER`. **Revised by the owner on 2026-09-27, the same day:** the
  default order is Gemini, then Perplexity, then DuckDuckGo, each when its
  key is set. Perplexity grounds whenever Gemini is unusable, or when an
  operator puts it first. Order and pinning use the existing
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

The response keeps its fields. The one addition is the optional request
field of question 4. Citations reach the caller inside the answer text:
the model is told to cite sources as `[n]`, and ppxai does **not** append a
source list to the model's content, since that would break a JSON
`response_format`. The existing optional `grounding` response record
(`searched`, `run_id`, `queries`, `backend`, `search_cost`) is set on the
retrieve path, as it already is on the search-loop path.

**Amended 2026-09-28 (owner, on closing this record).** The structured
citations field that this section first deferred shipped as
`grounding.sources` (`c3e56736`): `[{url, title}]`, the sources shown to the
model, in order, so an answer's `[n]` is `sources[n-1]`. It is an additive
key on the retrieval path only (the search-loop record has no such key), and
`title` is null unless the backend gives one. Gemini's URLs are Google's
opaque grounding redirects, so `title` carries the source's domain. The
answer text still carries the `[n]` markers, and ppxai still appends no
source list to the content. ppxai-sre checked the change against its
consumer and reported no impact. `docs/api-gateway.md` is the wire
reference.

### 6. Cost

Retrieval usage is recorded through the existing `ToolUsage` path, so it
appears in `/cost` under the run tier (ADR 0008) and in the run's usage
events, like a web_search tool call.

Two cost corrections landed after this record was built. `16ccbd98`:
`gemini_grounding.per_query` is a per-query price, but it had been divided by
1000 since v1.13.0, so each Gemini search was logged at a thousandth of its
cost. `8f031e60`: a Perplexity search records the `usage.cost.total_cost`
Perplexity reports, which includes its per-search and cache fees. The
configured token prices ($0.25 in / $2.50 out per 1M) are now only the
fallback.

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

## Owner answers (2026-09-27)

1. **Release:** v1.19.3, with ADR 0015 in the same release.
2. **`grounding: true` means `"retrieve"`.** `"native"` is the explicit
   opt-in for a provider's in-call search. An operator who set `true` and
   serves Gemini will see search move from Gemini's in-call Google Search
   to a separate search before the model call, through the resolved
   backend chain (Gemini's Google Search first under the revised order).
   The release notes carry this as an upgrade note.
3. **The query is the raw prompt.** No rewriting model call; it can be
   added later.

4. **Per-request control: add the optional field.** Raised by ppxai-sre.
   Their planned classifier sends email bodies as the prompt: often
   confidential, and **untrusted**, since anyone can send mail. Under
   server-wide retrieval grounding such a prompt would go to a third-party
   search host, and an attacker's email would steer both the query and the
   injected context. The egress ceiling and `strict` limit *where* the
   prompt goes, not *whether*. `POST /v1/oneshot` therefore gains an
   optional request field **`grounding: bool | null`**:
   - `null` (or absent) uses the server default;
   - `false` is always honoured, since it can only reduce exposure;
   - `true` on a server with grounding disabled is refused with a 400
     naming the setting, never silently ignored.

   The v1 contract permits this (`OneshotRequest`: optional fields are
   non-breaking), and the response is unchanged. Limit: pydantic ignores
   unknown fields, so a server **older** than this change ignores the
   field. A caller that depends on the opt-out gates on the server version
   from `GET /health`. Older servers only do `native` grounding, which
   reaches no new host.

## Implementation defaults (the owner may override)

- **Untrusted input.** `docs/api-gateway.md` states that retrieval
  grounding sends the prompt text to the search backend, and that callers
  with untrusted or confidential prompts should send `grounding: false`.
  `/doctor` says the same when grounding is on server-wide.
- **Citations** stay inside the answer text as `[n]` markers, which resolve
  through `grounding.sources` (§5, amended 2026-09-28).
- **Injected size** is capped by `context.max_injection_size`, the limit
  file injection already uses, rather than a new key.

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

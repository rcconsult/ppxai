# ADR 0012 — Per-model facts: one resolution system, wire protocol included

**Date:** 2026-08-30 (revised 2026-08-30 — scope widened from "add a protocol
resolver" to "unify the two per-model fact systems, protocol among them",
after the owner asked why protocol was absent from the capability table;
revised in place per the README's Proposed-records rule)
**Status:** 🟡 **Proposed** — design record, no code written. Supersedes the
`api_path` routing sketch in
[`../plan-per-model-capabilities.md`](../plan-per-model-capabilities.md) §I4b,
which assumed the slot merely needed filling in.
**Related:**
- [`../plan-per-model-capabilities.md`](../plan-per-model-capabilities.md) — the arc this lands in; I1–I4 shipped, I4b is the first consumer of this ADR
- [`../patterns/protocol-dependency-inversion.md`](../patterns/protocol-dependency-inversion.md) — the `Protocol`-in-leaf-module pattern this uses
- [`0010-config-shape-review.md`](0010-config-shape-review.md) — the config axes an operator-declared protocol would land on
- [debt Item 38](../debt-inventory.md) — Perplexity's Agent-API fleet, the fleet that surfaced this
- debt Item 43 (closed) — its four-layer lesson is the direct precedent for the drift measured below

---

## Context

The per-model capability arc (I1–I4) established one principle repeatedly: a
capability is **data resolved per model**, not a constant per provider, and
every layer that consults it must consult the *same* resolution. I1 fixed four
send paths that read a static attribute instead of the hook. I2 built the
precedence ladder. I3 found that a capability decision crosses four layers and
is inert until the lowest one is fixed.

**Wire protocol is the same kind of fact, and it is currently the same kind of
bug.**

### The provider/protocol axes are already crossed

Four providers speak three protocols. The mapping is not one-to-one and has not
been for some time:

| Protocol | Spoken by |
|---|---|
| `/chat/completions` | `perplexity`, `openai_compat`, `openai_native` |
| `/responses` | `openai_native` |
| `generate_content` | `gemini` |
| `/v1/messages` | **nobody yet — see §"The fourth protocol"** |

`OpenAINativeProvider` **already dispatches per model between two protocols**,
at three separate sites — `chat()`
([`openai_native.py:186`](../../ppxai/engine/providers/openai_native.py#L186)),
`chat_sync()` ([`:209`](../../ppxai/engine/providers/openai_native.py#L209)) and
`oneshot()` ([`:261`](../../ppxai/engine/providers/openai_native.py#L261)), each
independently re-asking `_is_responses_api_model(model)`. One provider, two
protocols, chosen per model: the multi-protocol provider is not a hypothetical
we are proposing, it is the shipped state. What is missing is that it is
expressed as a hardcoded branch repeated three times rather than as resolved
data.

### `BaseProvider._convert_messages` is one protocol's emitter in the shared base

[`base.py:346`](../../ppxai/engine/providers/base.py#L346) returns
`{role, content, tool_calls, tool_call_id}` — that is the **chat-completions
wire shape specifically**, not a neutral base-class utility. Every other
protocol already has to route around it:

| Protocol | How it converts messages | Return type |
|---|---|---|
| `chat_completions` | `BaseProvider._convert_messages` | `List[Dict]` |
| `responses` | `_convert_messages_for_responses` (separate method) | `tuple` |
| `generate_content` | **overrides** `_convert_messages` | `tuple` |

`GeminiProvider._convert_messages`
([`gemini.py:655`](../../ppxai/engine/providers/gemini.py#L655)) overrides the
base method **with an incompatible return type** — `(contents,
system_instruction)` instead of `List[Dict[str, Any]]`. That is a Liskov
violation living in shipped code, and it exists because the base class
asserts a shape only one protocol uses.

There is a second, sharper consequence. ADR 0006's wire validator
`assert_wire_blocks_clean` is called in **exactly one place**
([`base.py:384`](../../ppxai/engine/providers/base.py#L384)) — inside the
chat-completions emitter. `flatten_uploaded_file_blocks` is called by all
three paths, but the *validator* is not: the Responses and `generate_content`
paths emit to the wire without it. So ADR 0006's "spec-clean by construction"
guarantee is, in practice, **chat-completions-only**. Message conversion
belongs to the protocol, and so does the validator that checks its output.

### The fourth protocol: Anthropic's Messages API

There is **no Anthropic provider today** — no `anthropic` dependency in
`pyproject.toml`; the only production references are an image-size cap
([`image_validation.py:68`](../../ppxai/engine/image_validation.py#L68)) and a
deprecation-table row. But `/v1/messages` is arriving from two directions at
once, and a design that ignores it would bake in an assumption we already
know to be wrong:

1. **The reserved provider.** `feat/anthropic-provider` is reserved on the
   roadmap, deferred until after agent-platform Stage 2 — which has now
   shipped (v1.19.0).
2. **`anthropic/*` through Perplexity.** §5 below routes
   `anthropic/claude-sonnet-5` over Perplexity's *Responses* endpoint, and
   names it as the live-trial canary.

Those two together are the strongest argument for this ADR's whole premise:
**the same model is reachable over two different wires.**
`anthropic/claude-sonnet-5` (Perplexity, Responses) and `claude-sonnet-5`
(native, Messages) stay **two catalog entries on two providers** — §7 decides
that, and for billing/credential reasons that have nothing to do with protocol.
What per-model capability buys is not merging them; it is that **neither entry
has to be special-cased to reach its wire**. One `perplexity` provider serves
Sonar over chat-completions *and* the Agent fleet over Responses from one
identity, and the Anthropic provider speaks Messages, all through the same
resolution. Under a provider-property model, the first of those is impossible
without a second Perplexity entry that exists purely to hold a different
endpoint.

Messages differs from both existing shapes in ways that bear directly on the
handler contract:

| Concern | chat_completions | responses | **messages** |
|---|---|---|---|
| Client | OpenAI SDK | OpenAI SDK | **`anthropic` SDK** (not OpenAI-shaped) |
| System prompt | a `system` role message | `instructions` param | **top-level `system` param** |
| Tool call out | `tool_calls` | `function_call` item | **`tool_use` content block** |
| Tool result in | `tool`-role message | `function_call_output` | **`tool_result` block in a *user* message** |
| `max_tokens` | optional | optional | **required** |

Two Messages-specific hazards worth recording now, because both are the kind
of thing discovered late and expensively:

- **Parallel tool results must be returned in a *single* user message.**
  Splitting them across several user messages is accepted by the API but
  degrades the model's parallel tool use. The engine's native pairing branch
  records one tool-role message *per* result, so the handler must batch them —
  a genuine conversion, not a rename.
- **`thinking` blocks must be echoed back unchanged** on the same model
  across a tool round-trip. This is the same class of bug as debt Item 45
  (Gemini `thought_signature` round-trip), which was a real shipped defect.

Encouragingly, the hardest part is already solved once: Gemini's converter
already hoists system messages out of the turn list into a separate
`system_instruction`, which is exactly Messages' shape. Its docstring also
records the inverse hazard — Gemini's wire has **no** tool-call id, so pairing
is by function *name*, resolved from the preceding assistant turn. Messages
*does* carry `tool_use_id`, so it escapes that trap and falls into the
batching one instead. Different protocols, different failure modes; both are
conversion concerns, which is the argument for keeping conversion inside the
handler.

### The declared table and the actual router disagree — measured

`ToolCallingProfile` carries an `api_path` field
([`model_profiles.py:43`](../../ppxai/engine/model_profiles.py#L43)) documented
as *"OpenAI API endpoint routing"*, with values `chat` / `responses` / `auto`.
It is set on three built-in profiles, merged through the full config precedence
ladder ([`chat.py:206`](../../ppxai/engine/chat.py#L206)), exposed to operator
override ([`config/providers.py:385`](../../ppxai/config/providers.py#L385)),
and displayed by `/provider`
([`commands/provider.py:349`](../../ppxai/commands/provider.py#L349)).

**Nothing routes on it.** Actual routing is `_is_responses_api_model()`, a
hardcoded prefix tuple
([`openai_native.py:45`](../../ppxai/engine/providers/openai_native.py#L45)):

```python
RESPONSES_API_PREFIXES = ("gpt-5.1-codex", "codex", "gpt-5.2-pro", "gpt-5-pro", "gpt-6-pro")
```

Running the declared profile against the real predicate (2026-08-30, project
venv) gives three live disagreements, **in both directions**:

| model | `profile.api_path` | actual router | |
|---|---|---|---|
| `gpt-5.3-codex` | `responses` | `chat` | ⚠️ drift |
| `gpt-5.1-codex` | `responses` | `responses` | ok |
| `gpt-5.1-codex-mini` | `responses` | `responses` | ok |
| `gpt-5.2-pro` | `chat` | `responses` | ⚠️ drift |
| `gpt-5-pro` | `chat` | `responses` | ⚠️ drift |
| `gpt-4o` | `chat` | `chat` | ok |

`gpt-5.3-codex` is declared Responses-only and sent to Chat Completions,
because `"gpt-5.3-codex"` does not *start with* any tuple entry (`"codex"` is a
prefix, not a substring). The two mechanisms agree on `gpt-5.1-codex*` by
coincidence, not by construction.

A sweep of all 65 built-in profile globs finds two that drift on their own
glob (`gpt-5.3-codex*`, `gpt-5-pro*`). `gpt-5.2-pro` drifts as a *model* but
has no glob of its own — it falls through to a generic profile that declares
`chat` while the prefix tuple routes it to `responses`. That is the same
defect seen from the other side: the routing tuple names models the profile
table never describes, so neither source can be checked against the other.

Two consequences follow, and the second is the serious one:

1. The profile table is decorative for routing — it can be edited with no
   effect, which is how it drifted.
2. **An operator's `api_path` override is silently inert.** It passes
   validation, merges through the ladder, and displays in `/provider` as
   though it took effect. This is exactly the failure mode ADR 0010's
   config-shape file scan exists to prevent, and the shape of Item 43: every
   upper layer resolves a confident answer while the wire never sees it.

### The protocol handler is already free-standing — only lexically trapped

The plan's I4b assumed "no new protocol code" because `_chat_responses_api`
already exists. That is true of the *behaviour* but not of the *reachability*:
all five Responses helpers are private members of `OpenAINativeProvider`, so no
other provider can use them without inheriting from it.

Measuring the coupling (every `self.*` in
[`openai_native.py:609-960`](../../ppxai/engine/providers/openai_native.py#L609-L960))
shows the block is nearly pure already:

- `_convert_messages_for_responses`, `_convert_tools_for_responses`,
  `_parse_responses_usage` are **already `@staticmethod`** — zero instance
  coupling.
- `_get_max_tokens`, `_get_extra_body`, `_format_error`, `_classify_throttle`,
  `_log_error_traceback`, `get_capabilities_for_model` are **already
  `BaseProvider` API** — available to any provider.
- Only `enable_web_search` and `_build_tool_hint` are genuinely
  OpenAI-native-specific, and both are inputs to the request, not behaviour.
- `self.client` is the one real dependency: an OpenAI-SDK client, which the
  Perplexity provider also has (measured at I2 — the stock SDK's `.responses`
  client drives Perplexity's Agent API unchanged).

So the extraction is shallow: move a nearly-pure block and pass two values in.
This ADR exists because the *move* is a refactor of shipped wire code — the
highest-consequence code in the repo — and that deserves a recorded decision,
not an incidental step inside a provider-routing iteration.

---

## Decision

**Wire protocol becomes a named handler, resolved per model through the same
ladder as every other capability, and composed into a provider at registration
time.**

### 1. `ProtocolHandler` — a `Protocol` in a leaf module

Following
[`../patterns/protocol-dependency-inversion.md`](../patterns/protocol-dependency-inversion.md)
(structural `Protocol`, no `TYPE_CHECKING`, defined where it is depended on):

```python
class ProtocolHandler(Protocol):
    name: str   # "chat_completions" | "responses" | "generate_content" | "messages"

    def convert_messages(self, messages: List[Message]) -> Any: ...
    def chat(self, ctx, messages, model, stream, tools) -> AsyncIterator[Event]: ...
    def oneshot(self, ctx, messages, model, max_tokens) -> str: ...
```

**`convert_messages` belongs to the handler, not to `BaseProvider`.** This is
the direct consequence of the shared-emitter finding above: message conversion
*is* protocol-specific, every protocol already routes around the base method,
and Gemini overrides it with an incompatible return type to do so. Its return
type is deliberately `Any` — each protocol's wire shape is its own
(`List[Dict]`, `(contents, system_instruction)`, `(system, messages)`), and
pretending otherwise is what produced the Liskov violation. **ADR 0006's
`assert_wire_blocks_clean` moves with it**, so the validator finally covers all
protocols instead of chat-completions alone.

**`ctx` is deliberately not "an OpenAI SDK client."** It is whatever the handler
needs from its host, and the client type is the handler's business:

| Handler | client in `ctx` | other host inputs |
|---|---|---|
| `chat_completions` | OpenAI SDK | — |
| `responses` | OpenAI SDK | `enable_web_search`, tool-hint builder |
| `generate_content` | google-genai | — |
| `messages` | `anthropic` SDK | — |

Specifying `ctx` this way now costs nothing and is the one part that would be
expensive to relax later: three handlers written against "the OpenAI client"
would each need reworking when Messages arrives. The handler never reaches back
into a concrete provider class; that is what makes one handler usable by
several providers, and what keeps a non-OpenAI-shaped wire from being a special
case.

### 2. One per-model fact system — protocol is a field in it, not a third resolver

**This section was rewritten.** It first proposed
`shipped_protocol_for_model()` / `get_protocol_for_model()` — an accessor pair
*mirroring* `get_capabilities_for_model()`. The owner's question ("why is wire
protocol not in the capability table?") exposed the flaw: mirroring would make
**three** parallel per-model resolution systems, when the ADR's stated purpose
is to simplify and increase reuse. Duplicating a ladder to hold one more field
is the carve-out this ADR exists to remove.

#### What exists today — two systems, surveyed

| | `ProviderCapabilities` | `ModelProfile` / `ToolCallingProfile` |
|---|---|---|
| Fields | `web_search`, `web_fetch`, `weather`, `citations`, `streaming`, `native_tool_calling` | `tool_calling.{mode, fallback_on_empty, fallback_on_failure, strip_json_from_text, parallel_tool_calls, api_path}`, `max_tokens`, `max_tool_iterations`, `supports_reasoning`, `supports_vision`, `restricted_params`, `tier` |
| Keyed by | exact model id | **glob** (65 patterns, first match wins) |
| Code table | `shipped_capabilities_for_model()` — 2 providers override | `BUILTIN_PROFILES` dict |
| Config keys | `providers.<p>.capabilities`, `providers.<p>.models.<m>.capabilities` | `providers.<p>.tool_calling`, `providers.<p>.models.<m>.tool_calling` |
| Config reader | `config/capabilities.py` (reads the **raw file** — `_convert_models_format` drops per-model blocks) | `config/providers.py::get_tool_calling_config` (same raw-file workaround) |
| Merge site | `BaseProvider.get_capabilities_for_model()` | `chat.py::_merge_profile` |
| Extra layer | — | **AGENTS.md bootstrap overrides** (`_get_bootstrap_tool_calling`) |
| Precedence | model-config → model-code → provider-config → provider-code | built-in profile → AGENTS.md → config |

They already answer the *same question twice*: `native_tool_calling` (bool)
and `tool_calling.mode` (`native`/`prompt_based`/`auto`). **I3's Layer-2 bug
lived exactly in that seam** — `chat.py:693` checks `mode` first and
short-circuits, so a capability resolving `native=True` never reached the
wire. Two systems, two precedence orders, one question.

#### The decision

**One `ModelFacts` record, one resolver, one precedence ladder.** Protocol
joins it as a field; it gets no machinery of its own.

```python
@dataclass(frozen=True)
class ModelFacts:
    # wire
    wire_protocol: str = "chat_completions"   # was ToolCallingProfile.api_path
    # tool calling
    tool_mode: str = "native"                 # native | prompt_based | auto
    fallback_on_empty: bool = False
    ...
    # provider-native abilities
    web_search: bool = False
    ...
    # limits / behaviour
    max_tokens: int = 0
    supports_vision: bool = False
    ...
```

`BaseProvider` keeps the I2 split, now over facts rather than capabilities:
`shipped_facts_for_model()` (subclass-overridable) and
`get_facts_for_model()` (final; applies config). **The two old accessors and
both old merge sites are deleted, not wrapped** — an accessor that internally
called both ladders would pass every behavioural test while leaving the code
worse, which is the failure mode this section exists to prevent.

> ⚠️ **The five-rung ladder below is SUPERSEDED by Q0e.** It is kept because
> the reasoning that replaced it only makes sense against it: three
> implementations failed trying to arbitrate between its rungs, and the third
> reopened debt Item 43. With disjoint provider/model field sets there is
> nothing to arbitrate, and this ladder collapses to two independent lookups.

Resolution order, generalising I2's **specificity before authorship** and
absorbing the profile path's extra layer:

1. config `providers.<p>.models.<m>.*` (per model)
2. **AGENTS.md bootstrap** (per model, benchmark-locked)
3. code per-model table / glob (per model)
4. config `providers.<p>.*` (per provider)
5. code provider default

⚠️ **Rung 4 is a deliberate behaviour CHANGE, not a move.** Today
`get_tool_calling_config` ([`providers.py:377`](../../ppxai/config/providers.py#L377))
flattens provider-level **and** model-level config into a *single* layer that
`chat.py:187` applies **above** AGENTS.md — so an operator's *provider-level*
`tool_calling` currently beats a benchmark-locked AGENTS.md setting. Splitting
the two config levels onto rungs 1 and 4 puts AGENTS.md above provider-level
config.

That is the correct end state — a per-model benchmark result should outrank a
provider-wide operator default, which is the same specificity-before-authorship
rule I2 established — but it **must be declared and fenced, not slipped in**.
W1 ships a real-config cross-pair test (provider-level config × AGENTS.md ×
per-model glob), because this is precisely the class of ordering bug that 22
green unit tests missed in I2.

**Measured (2026-08-30): the reorder changes nothing observable today.**
Provider-level `tool_calling` blocks do exist (example config: `nvidia`,
`local-vllm`, `vllm-gpt-oss`, `qwen36-agent`, `lmstudio`; a real user config:
7 providers), but **no AGENTS.md carries a `tool_calling` section** — zero
hits across this repo, ppxai-sre and a third checkout. The two layers being
reordered never currently meet. The migration note still ships, because the
docs and example config teach *both* mechanisms and a future AGENTS.md would
land straight into the changed order.

I2's guard carries over unchanged: a test bans subclasses from overriding the
public accessor, since one that did would silently drop the config layers —
the shape that broke I1.

#### Q0e — TWO record types, disjoint fields, no defaults anywhere (supersedes the five-rung ladder)

**Owner decision 2026-08-30, after three failed implementations.** The
ladder above was wrong at the root, and the failures were the evidence:

- drop-if-default (rung 5 overwrote rung 4 for every capability field),
- a "profile-owned" exemption list (inverted precedence for a row that
  deliberately stated a default value),
- a value-comparison heuristic (**resolved `sonar` to `native` — reopening
  debt Item 43 on the very model that produced it**, because a provider-wide
  statement outranked a measured per-model fact).

Each heuristic patched the previous one's failure. That is the patchwork
pattern this project bans, and the third one should not have been written.

**The root cause was not the arbitration rules — it was needing them at
all.** Provider and model were modelled as two *levels of the same fields*,
so every field could be stated twice and something had to decide who wins.
The measurement says the domain does not work that way (example config, all
10 providers):

| Field | stated per provider | stated per model |
|---|---|---|
| `web_search`, `web_fetch`, `weather`, `citations` | 10 | **0** |
| `native_tool_calling` / `mode` | 10 / 5 | **0** |
| `fallback_on_empty`, `strip_json_from_text` | 4 | 1 |

Endpoint abilities are **never** stated per model, because they are facts
about the *service*: Perplexity has built-in search, the OpenAI API does
not, and no model changes that. The collisions were an artefact of the
schema, not of the domain.

**Decision — two records with DISJOINT fields:**

```python
@dataclass(frozen=True)
class ProviderFacts:      # what the ENDPOINT does
    web_search: bool
    web_fetch: bool
    weather: bool
    citations: bool
    streaming: bool

@dataclass(frozen=True)
class ModelFacts:         # what THIS MODEL does
    wire_protocol: str
    tool_mode: str
    fallback_on_empty: bool
    fallback_on_failure: bool
    strip_json_from_text: bool
    parallel_tool_calls: bool
    max_tokens: int
    max_tool_iterations: int
    supports_reasoning: bool
    supports_vision: bool
    restricted_params: tuple
    tier: str
```

No field appears in both. A provider block cannot state a model fact and a
model block cannot state a provider fact, so **there is nothing to
arbitrate** — the five-rung ladder collapses to two independent lookups.
`tool_mode` being a model fact is what makes the `sonar` regression
structurally impossible: no provider-wide setting can reach it.

**No inheritance, no shortcuts** (owner: *"we stop providing shortcuts for
this round"*). Stated precisely, because "no defaults anywhere" would
contradict Q0a:

- **No inheritance between records or levels.** A provider record never
  supplies a model field, and a model record never supplies a provider
  field. There is no partial record that something else completes.
- **Exactly one fallback exists**, owned by this ADR: the conservative
  `ModelFacts` used when no table names a model at all (Q0a —
  `tool_mode="prompt_based"`). It is a floor for the unmeasured, not a
  layer anything inherits from, and **`/doctor` reports every model that
  lands on it** so "unmeasured" is visible rather than silent.

Combined with Q0d this means:

- The resolver never guesses, because there is never a partial record to
  interpret.
- **Code rows may rely on dataclass defaults; config rows may not.** A code
  row is a complete record *by construction* — the dataclass guarantees
  every field has a value, and the row is reviewed in a diff alongside the
  type. A config file has no such guarantee and no reviewer, which is the
  asymmetry Q0d exists for. (Measured: a representative row states 5 of 7
  fields explicitly and inherits 2 — rewriting 65 rows to restate defaults
  would add noise without adding information.)
- Resolution is: shipped table row (complete) → operator config row
  (complete). Two rungs, one per record type, no cross-level merging.
- Fleet-wide conveniences (`fallback_on_empty` et al. set once per vLLM box)
  are **not** carried over. They become per-model statements, written by
  `/doctor`.

**Migration order matters and is part of the decision.** `/doctor` must
push legacy *provider-level* statements down into each configured model's
row **before** filling remaining blanks from the shipped table. The reverse
order silently destroys operator intent: in the shipped example config
`vllm-gpt-oss` sets `tool_calling.mode: native` at provider level while the
shipped glob `openai/gpt-oss*` says `prompt_based`, so "fill blanks from the
resolved value" would overwrite the operator's explicit `native`. That exact
case is the round-trip fixture.

**`/doctor` carries the entire burden this creates**, which is why it was
worth the investment: it reports partial records (Q0d), fills blanks with
resolved values, and **scaffolds new provider and new model definitions** so
an operator adding a box or a model gets a complete record generated rather
than hand-writing 12 fields. The verbosity is real and accepted; the tool,
not the human, produces it.

**Deferred, explicitly:** whether some fleet-level convenience returns as an
inheritance mechanism. Reviewable later, once the explicit form is in place
and its cost is measured rather than predicted.

#### Q0a — `native_tool_calling` vs `tool_mode`: mode wins, boolean **deleted**, default stays CONSERVATIVE

`tool_mode` strictly subsumes the boolean (`native`/`auto` ⇒ true,
`prompt_based` ⇒ false) and carries a distinction the boolean cannot express.
The boolean is **removed from the record**, not kept as a derived property:
a readable alias is how the seam bug survives. Call sites reading
`caps.native_tool_calling` migrate to `facts.tool_mode != "prompt_based"`.

⚠️ **The two systems disagree on their SAFE DEFAULT, and a naive merge
inverts it.** `ProviderCapabilities.native_tool_calling` defaults **False**
([`types.py:891`](../../ppxai/engine/types.py#L891); `loader.py:51` says
"Default to prompt-based"; the Perplexity probe encodes the same rule —
*unmeasured ⇒ assumed not capable*). `ToolCallingProfile.mode` defaults
**`"native"`** ([`model_profiles.py:38`](../../ppxai/engine/model_profiles.py#L38)).
Merging on the profile's default would flip **every model absent from both
code tables** from not-tool-capable to tool-capable — silently, and through
gated consumers: `task_authorizer.py:982-989` (task-tier eligibility),
`execution.py:338` (oneshot enrichment), and the I1 send paths.

**Decision: `ModelFacts.tool_mode` defaults to `"prompt_based"`** — the
capability system's conservative default wins, because an unmeasured model
that degrades is recoverable while one that 400s a user's request is not
(the Item 43 lesson, and exactly why `PerplexityProvider` sets
`native_tool_calling=False` as its provider default). A model that today
resolves `mode="native"` only via `ToolCallingProfile`'s *default* — rather
than via an explicit glob — is a model nobody measured; W1 must enumerate
those and give each an explicit row, not inherit them by default flip.

**Fence:** the seam test must include a model listed in **neither** table and
assert it resolves not-tool-capable, plus an end-to-end assertion through
`authorize_task()` (the I3 lesson: testing the helper is not testing the call
site).

**Measured demotion risk (2026-08-30, example config + a real user config,
90 configured models): 14 models resolve their mode via the profile default
alone, and the conservative default demotes effectively none of them** —
13 are held native by a provider-level `capabilities.native_tool_calling:
true` (which the translation above preserves), and the 14th
(`meta-llama/Llama-3-70b` on example `local-vllm`) is already configured
`prompt_based`, so the new default agrees with it. **One exception needs an
explicit row:** `gpt-5.1` on `openai` is native by the shipped code table
but matches no glob (`gpt-5.1-codex*` exists; bare `gpt-5.1` does not).
Applying the real ladders to all 90 found **no model where built-in profile
and resolved capability disagree in a way the unification must arbitrate.**

#### Q0b — glob vs exact key: globs win, one matcher, **exact ids matched first**

Capabilities key on exact ids, profiles on globs; globs strictly generalise
(an exact id is a glob without wildcards), and 65 patterns already depend on
them. One matcher for the merged table.

⚠️ **"Most-specific-first" is today a COMMENT, not a computed rule.**
[`model_profiles.py:82`](../../ppxai/engine/model_profiles.py#L82) says *"First
match wins — order matters (specific before generic)"* — specificity is
maintained by hand, by insertion order. Merging the exact-id tables
(`PERPLEXITY_NATIVE_TOOL_MODELS`, the openai prompt-based prefixes) into a
65-entry glob dict by insertion order would make correctness depend on where a
row happens to sit.

**Decision: matching is two-pass — every exact (wildcard-free) id is tried
before any wildcard glob**, and only then insertion order applies among globs.
A test enforces both passes, including the case that motivates it: an exact id
that also matches an earlier generic glob must resolve to the exact row.

#### Q0d — records are COMPLETE at every level; `/doctor` enforces it

**Owner decision 2026-08-30.** Every `facts` block — in code and in config —
states **all** `ModelFacts` fields. A partial block is a defect `/doctor`
reports and rewrites, filling each unstated field with the value it
currently resolves to.

This came out of a live defect in the first implementation. The shipped
tables are full records, so "deliberately `false`" and "nobody filled this
in" are indistinguishable; the resolver tried to bridge that with a
drop-if-default heuristic, which (a) let rung 5 overwrite rung 4 for every
capability field and (b) inverted precedence for a row that deliberately
stated a default value. Both were symptoms of one thing: **a merge that has
to guess what a partial record meant.**

The sparse-row alternative was considered and rejected by the owner:
partial rows push the guessing onto every reader, and with dozens of models
an operator cannot tell whether an absent field is an intention or an
oversight. *"Having incomplete records always risks being missed, or default
guesses might fail, and adds burden to the user."*

Consequences, accepted deliberately:

- **The resolver stops guessing.** With complete records at every rung, a
  merge is a straight field-wise overwrite — no drop-if-default, no
  "profile-owned" exemption list, no ambiguity about capability fields.
- **Config becomes verbose**, and that is the point: a config diff shows an
  operator exactly what their deployment does, rather than what it
  inherits.
- **Adding a field to `ModelFacts` makes every existing config block
  incomplete.** `/doctor` is the migration path, and this is the same
  mechanism as Q0c's legacy-key rewrite — one scan, two findings
  (legacy keys, incomplete records), one rewrite.
- `/doctor` must therefore be able to **render the resolved record**, which
  it can: every rung is available to it.

#### Q0c — config migration: clean break, with the file scan shipped alongside

Two key families merge into one. Following **ADR 0010**'s precedent and the
lesson it produced (`docs/lessons/clean-break-config-moves-need-a-file-scan.md`):
no dual-read, and **`/doctor` gains the config-shape scan in the same
commit** — a moved key with no dual-read is invisible to every accessor, so
only a check that reads the config *file* can report it. Both old families
already have raw-file readers, so the scan has a working precedent to copy.

**Clean-break inventory (grep-verified 2026-08-30) — the scan is necessary
but not sufficient.** ADR 0010's trap was flagging a key in `/doctor` while
the docs still taught it. Every one of these moves in the same change:

*Production readers outside `config/capabilities.py`:*
`config/execution.py:338` (oneshot enrichment gate) ·
`config/loader.py:51` (the `False` default itself) ·
`engine/chat.py:696,698` (the native-vs-prompt branch) ·
`engine/task_authorizer.py:982,986,989` (task-tier eligibility, incl. a raw
`config_model_overrides[...]` read).

*User docs that teach the key and would otherwise contradict the scan:*
`docs/tool-calling.md` · `docs/vllm-notes.md` ·
`docs/vllm-tool-calling-guide.md` · `docs/dgx-spark-setup.md`.

⚠️ **The break is NOT drop-and-scan — the key must be TRANSLATED.**
Measured across the example config and a real user config (90 configured
models): several providers carry `capabilities.native_tool_calling: true`
and **no `tool_calling` block at all** — `openrouter` and `ollama` in the
shipped example config are exactly this shape (verified: `tool_calling`
absent, capabilities key `true`). For them that key is the *only* thing
holding native tool calling on.

So Q0c's migration must map `capabilities.native_tool_calling: true` →
`tool_mode: native` (and `false` → `prompt_based`), in `/doctor`'s rewrite
and in the example config, in the same change. A pure drop — even with a
scan that *reports* the stale key — silently demotes every `openai_compat`
deployment in the field that copied the example config. **The migration
cost of this ADR lives in field configs, not in code tables.**

### 3. `api_path` is finally *consumed* — as `ModelFacts.wire_protocol`

The declared-but-inert field is carried into the unified record (renamed to
say what it means) rather than a parallel mechanism being invented beside it.
`_is_responses_api_model` and `RESPONSES_API_PREFIXES` become *seed data* for
`openai_native`'s per-model table and then stop being a router. The three
measured drifts are resolved as an explicit, reviewed table — each row a
decision, not a coincidence of prefix matching.

Naming: `api_path` described an OpenAI endpoint suffix; the field now selects
a protocol handler across four wires, one of which (`generate_content`) is not
an HTTP path at all. Renaming is part of the config clean break in Q0c, not a
separate migration.

### 4. Registration time is the wiring point

Handlers are attached where providers are registered
([`providers/__init__.py:59`](../../ppxai/engine/providers/__init__.py#L59)) —
the harness-startup seam. A provider declares the set it can speak; the model
picks one per request. This is also the seam at which an operator-declared
protocol could later be added without a code change, though this ADR does
**not** propose opening that surface yet (see *Future*).

### 5. Perplexity's Agent fleet is then table data

I4b reduces to rows: `anthropic/claude-sonnet-5 → protocol="responses"`, plus
`requires_max_output_tokens` (measured at I2: `anthropic/*` 400s without it).
No second provider entry, no translation layer, no new protocol code — which is
what the plan wanted, now actually true rather than assumed.

**This settles the question I4b reserved for the owner** ("new models on the
existing `perplexity` provider, or a second provider entry?"). Under this ADR
the question dissolves *for this case*: the Agent-API fleet is reached with the
**same Perplexity key, billed on the same Perplexity account, under the same
price table** — one identity, two wires — so one `perplexity` entry speaking two
protocols is the natural expression. A second entry here would exist only to
work around a provider being unable to speak two protocols, which is the
limitation this removes.

That reasoning is **scoped to a shared identity**, and does not generalize to
every two-wire case. Where the second route is a different account with its own
credential and rates, the entries stay separate no matter how the protocol is
resolved — see §7, which decides exactly that for Anthropic-direct.

### 6. Messages is designed for, not built

The `messages` handler is **specified here and implemented by whoever picks up
`feat/anthropic-provider`** — this ADR does not schedule it, and no migration
step below builds it. What this ADR commits to is narrower and load-bearing:
the contract above must not have to change when it arrives.

Concretely, that means three things hold today:

- `ctx` is client-agnostic (§1), so the `anthropic` SDK is not a special case.
- `convert_messages` is a handler method with a protocol-owned return type, so
  system-hoisting and `tool_result` batching are ordinary handler work rather
  than a base-class exception.
- The wire validator travels with the converter, so a fourth protocol is
  covered by ADR 0006 on day one instead of joining the two that currently
  bypass it.

The consequences of Messages *not* being OpenAI-shaped therefore land entirely
inside its own handler. That is the test of whether this design is right, and
it is the reason for specifying it before the handler set exists rather than
after.

### 7. The same model over two wires stays two catalog entries — DECIDED

**Owner decision, 2026-08-30:** `anthropic/claude-sonnet-5` (via Perplexity)
and `claude-sonnet-5` (native Messages) are **separate catalog entries on
separate providers** — *"different provider, different billing, accounting and
API access token."*

This was raised in §6 as an open product question about the model picker. It
is not: all three reasons are **structural**, and each is keyed on provider
identity in shipped code.

| Axis | Where it is keyed | Consequence of merging |
|---|---|---|
| **API token** | `api_key_env` is a **provider-level** config key, read by `get_api_key(provider)` ([`config/providers.py:103-106`](../../ppxai/config/providers.py#L103-L106)) | One catalog entry cannot resolve two credentials — the second route has no key to send |
| **Billing** | `pricing` is a **provider-level** config block, read by `get_provider_config(provider).get("pricing")` ([`config/providers.py:83`](../../ppxai/config/providers.py#L83)) | Two routes at different rates would share one price table; every cost figure for one of them is wrong |
| **Accounting** | Usage aggregates by splitting the `"provider/model"` key on `/` ([`usage.py:243`](../../ppxai/usage.py#L243)) — the **provider name is literally the accounting key** | The two routes collapse into one bucket in `/cost` and `by_provider`, unattributable |

So merging them would not be a nicer model picker with a hidden route — it
would be one entry that cannot authenticate its second route, prices it wrong,
and cannot report it separately. **The catalog entry is the billing boundary**,
and that is a stronger invariant than the display convenience §6 weighed.

**This does not weaken the ADR — it sharpens what the ADR is for.** Protocol
stays a per-model capability: it decides *how a request is encoded and sent*.
Identity, credentials, price and accounting stay per-provider: they decide
*whose account pays and under what terms*. Those are different questions, and
this ADR only unifies the first. `PerplexityProvider` speaking two protocols is
still right (one key, one price table, one bucket, two wires); Anthropic-direct
is a separate provider because it is a separate account — not because it speaks
a different protocol.

**Consequences for the Anthropic work:** `feat/anthropic-provider` registers a
new provider with its own `api_key_env`, `pricing` block and catalog entries,
and declares the `messages` handler from §6. Users see Claude models twice, and
that is correct — the two entries bill differently and draw on different
credentials. Worth a doc note so it does not read as a duplication bug.

---

## Why this and not the alternatives

**Not "add a second provider entry for the Agent API."** It answers the
symptom. Two entries would still each hardcode their protocol, `api_path` would
still be inert, and the three measured `openai_native` drifts would remain
untouched. It also doubles the config/pricing/install surface (example config,
`install.sh`, `scripts/install.ps1`, `vscode-extension/src/config.ts`, four
pricing tables — the same list I3 had to touch) for what is one API's routing
detail.

**Not "make `PerplexityProvider` inherit from `OpenAINativeProvider`."** It
would reach the helpers with the least typing and is the worst option: it
inverts an unrelated is-a relationship purely to share a wire format, and drags
`enable_web_search`, reasoning-model handling and OpenAI's pricing assumptions
along with it.

**Not "duplicate the Responses block into `perplexity.py`."** Cheapest now, and
it guarantees the two copies diverge — the Responses shape is external and
changes on OpenAI's schedule, not ours.

**Not "fix the drift only."** Correcting `RESPONSES_API_PREFIXES` to match the
profile table would clear today's three disagreements in about ten minutes and
leave the mechanism that produced them — two sources of truth, the declared one
inert — fully intact. It would also leave the operator override still silently
doing nothing.

**Accepted cost.** This touches all four providers and the `chat.py` dispatch,
and it refactors working wire code. That is why it is an ADR and why the
migration below is staged with a no-behaviour-change first step: the risk is
concentrated in the move, so the move is made provable before anything else
depends on it.

---

## Migration

Ordered so each step is verifiable before the next depends on it. Every step is
gated on the owner's explicit go, per the arc's standing rule.

0. **Unify the fact systems (§2).** `ModelFacts` + one resolver replaces
   `ProviderCapabilities` and `ModelProfile`'s parallel ladders; both old
   accessors and merge sites are deleted; config keys merge under Q0c with
   the `/doctor` scan in the same commit. Behaviour byte-identical — this
   step moves *where* facts resolve, not *what they say*. Fences: every
   existing capability and profile test passes against the unified accessor;
   I2's real-config cross-pair test extended to profile fields; a
   mode-vs-capability seam test (the I3 regression); the accessor-override
   ban.

1. **Extract, no behaviour change.** Lift the Responses block into a handler;
   `openai_native` consumes it via the handler while keeping
   `_is_responses_api_model` as its resolver. Fence: existing suite green, plus
   a request-kwargs spy proving the outgoing request is byte-identical
   before/after for one `responses` model and one `chat` model.
2. **Make the protocol field load-bearing.** Routing reads
   `get_facts_for_model(model).wire_protocol`; the prefix tuple becomes
   table seed data. Fence:
   a test asserting declared-vs-routed agreement **for every built-in profile**
   — the check that would have caught all three drifts — plus a test that an
   operator `api_path` override actually changes the outgoing request (the
   inert-config regression).
3. **Perplexity speaks both.** Register the Responses handler on `perplexity`;
   add the fleet rows. Fence: live trial of `anthropic/claude-sonnet-5` through
   `/task --tools read_file`, canary-verified end to end, per the arc's
   trial-after rule.
4. **`chat_completions` and `generate_content` become handlers.** Completes the
   model; `openai_compat` and `gemini` stop being special cases. This is the
   step that moves `convert_messages` into the handlers and retires Gemini's
   incompatible override — and where `assert_wire_blocks_clean` starts covering
   all protocols. Fence: the ADR 0006 validator runs on every protocol's
   output, asserted per handler.

Steps 1–2 stand on their own merit — they fix measured drift and an inert
config override — and are worth doing even if step 3 were abandoned.

**Messages (`/v1/messages`) is not a step here.** It is specified in §6 and
built with `feat/anthropic-provider`, on that work's own schedule. If it lands
*before* step 4, it should be written as a handler against this contract from
the start rather than as a fifth bespoke provider — that is cheaper than
retrofitting it, and it is the case this ADR is designed to absorb without
change.

---

## Future / proper solution

- **Operator-declared protocols.** §4's registration seam could accept a
  handler from config, letting a deployment add a wire format without a code
  change. Deliberately not proposed now: it is a plugin surface, and it should
  follow a real second consumer, not precede one.
- **Fold in `PROMPT_BASED_MODEL_PREFIXES`.** The arc's I5 already plans to fold
  that prefix tuple into the per-model table. It is the *same* anti-pattern as
  `RESPONSES_API_PREFIXES` — a hardcoded prefix list shadowing declared
  per-model data — and both should end up in one shape.
- **`api_path="auto"`.** Documented (try chat, fall back to responses on 404)
  and, like the rest of the field, unimplemented. Under this ADR it becomes a
  handler-selection strategy rather than a fourth branch. No consumer needs it
  yet; it should stay unimplemented until one does, rather than shipping a
  second untested routing mode.

## Triggers to revisit

- `streaming` stops being a pure endpoint fact. It holds today (no model
  anywhere sets `streaming=False`), but reasoning models with streaming
  restrictions are the obvious future exception — and the field would then
  have to move from `ProviderFacts` to `ModelFacts`.
- A provider needs a protocol whose transport is not an SDK client at all (a
  raw-HTTP or gRPC wire): `ctx` carrying *a* client stops being the right
  abstraction. Note this trigger originally read "not OpenAI-SDK-shaped" and
  was **already live when written** — Messages is exactly that case, which is
  why §1 now specifies `ctx` client-agnostically and §6 designs for it. A
  pre-armed trigger is worth less than a contract that does not need it.
- A fifth provider or a fourth protocol arrives before step 4 lands — the
  handler set is still small enough to reshape cheaply, and would not stay so.
- Perplexity exposes a real `/models` endpoint. Capability and protocol could
  then be partly enumerated rather than declared, changing what the table is
  for (see `scripts/probe-perplexity-capabilities.py`, which exists precisely
  because no such endpoint does).
- The Responses shape diverges between OpenAI and Perplexity. One shared
  handler is correct only while the two remain the same wire; if they fork,
  this becomes two handlers, and the composition model absorbs that without a
  provider change.

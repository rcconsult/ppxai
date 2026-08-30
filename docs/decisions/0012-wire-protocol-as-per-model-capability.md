# ADR 0012 — Wire protocol as a per-model capability, not a provider property

**Date:** 2026-08-30
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
    name: str          # "chat_completions" | "responses" | "generate_content"

    def chat(self, ctx, messages, model, stream, tools) -> AsyncIterator[Event]: ...
    def oneshot(self, ctx, messages, model, max_tokens) -> str: ...
```

`ctx` carries what the handler needs from its host — the client, and the
provider-specific request inputs (`enable_web_search`, tool-hint builder) that
the coupling audit identified. The handler never reaches back into a concrete
provider class; that is what makes one handler usable by several providers.

### 2. `BaseProvider` composes handlers; the model selects one

`BaseProvider` gains a handler map and a resolver that mirrors
`get_capabilities_for_model()` exactly — same shape, same ladder, same
`shipped_*` / final-accessor split that I2 established:

```python
protocols: dict[str, ProtocolHandler]         # what this provider CAN speak
def shipped_protocol_for_model(model) -> str  # subclass-overridable
def get_protocol_for_model(model) -> str      # final; applies config
```

Precedence is I2's, unchanged — **specificity before authorship**:

1. config `models.<m>.…api_path` (per model)
2. code per-model table (per model)
3. config `providers.<p>.…api_path` (per provider)
4. code provider default

I2's guard applies unchanged too: a test must ban subclasses from overriding
the public accessor, since a subclass that did would silently drop the config
layers — the same shape that broke I1.

### 3. `api_path` becomes the live input to that resolution

The existing field is kept and finally *consumed*, rather than a parallel
mechanism being invented next to it. `_is_responses_api_model` and
`RESPONSES_API_PREFIXES` become the *seed data* for `openai_native`'s per-model
table and then stop being a router. The three measured drifts are resolved as
an explicit, reviewed table — each row a decision, not a coincidence of prefix
matching.

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
the question dissolves: a provider is a composition of protocol handlers, so one
`perplexity` entry speaking two protocols is the natural expression. A second
entry would exist only to work around a provider being unable to speak two
protocols — the very limitation this removes.

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

1. **Extract, no behaviour change.** Lift the Responses block into a handler;
   `openai_native` consumes it via the handler while keeping
   `_is_responses_api_model` as its resolver. Fence: existing suite green, plus
   a request-kwargs spy proving the outgoing request is byte-identical
   before/after for one `responses` model and one `chat` model.
2. **Make `api_path` load-bearing.** Resolution moves to
   `get_protocol_for_model()`; the prefix tuple becomes table seed data. Fence:
   a test asserting declared-vs-routed agreement **for every built-in profile**
   — the check that would have caught all three drifts — plus a test that an
   operator `api_path` override actually changes the outgoing request (the
   inert-config regression).
3. **Perplexity speaks both.** Register the Responses handler on `perplexity`;
   add the fleet rows. Fence: live trial of `anthropic/claude-sonnet-5` through
   `/task --tools read_file`, canary-verified end to end, per the arc's
   trial-after rule.
4. **`chat_completions` and `generate_content` become handlers.** Completes the
   model; `openai_compat` and `gemini` stop being special cases.

Steps 1–2 stand on their own merit — they fix measured drift and an inert
config override — and are worth doing even if step 3 were abandoned.

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

- A provider needs a protocol that is **not** OpenAI-SDK-shaped (a raw-HTTP or
  gRPC wire): `ctx` carrying an SDK client stops being the right abstraction.
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

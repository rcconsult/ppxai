# Plan — per-model capabilities as a shared framework

**Status:** proposed, not started. Written 2026-08-15 on `bugfix/v1.19.1`.
Every claim below was verified against the tree at `fbb23225`; the
verification command is given so a reader can re-check rather than trust.

## Why this is not a Perplexity patch

Item 43 looks like one line on one provider. It is not. Three findings, in
increasing order of severity:

### F1 — `get_capabilities_for_model()` exists but the send paths ignore it

`BaseProvider.get_capabilities_for_model(model)` is the per-model hook.
Exactly ONE non-provider caller consults it:

    ppxai/engine/chat.py:686   provider_caps = ctx.provider.get_capabilities_for_model(ctx.model)

Every *provider send path* instead reads the static `self.capabilities`:

| Site | Method | `model` in scope? |
|---|---|---|
| `openai_native.py:434` | `_chat_completions_api` | yes |
| `openai_native.py:650` | `_chat_responses_api` | yes |
| `openai_compat.py:264` | `chat` | yes |
| `gemini.py:864` | `_build_config` | **no** — needs threading |

Verify: `grep -rn "self\.capabilities\.native_tool_calling" ppxai/`

**This is a live shipped bug, independent of Item 43.** `OpenAINativeProvider`
declares `o4-mini` and `gpt-4.1-mini` prompt-based
(`PROMPT_BASED_MODEL_PREFIXES`, benchmark-backed: o4-mini 10.9% native to
62.5% prompt-based). The override returns False; the send path reads True
and sends native tools anyway. Measured 2026-08-15:

    o4-mini: get_capabilities_for_model() = False
             self.capabilities            = True   <- what line 434 uses

So the existing per-model mechanism is **half-wired**. Adding Perplexity to
it without fixing the send paths would produce a correct-looking override
that changes nothing on 3 of 4 providers.

### F2 — capability is a provider-level constant in 3 of 4 providers

Only `openai_native` overrides the hook. `perplexity`, `gemini` and
`openai_compat` declare one static `native_tool_calling` for every model
they serve.
Verify: `grep -ln "def get_capabilities_for_model" ppxai/engine/providers/*.py`

That is wrong wherever a provider serves a mixed fleet — which is now all of
them (Perplexity proven below; `openai_compat` fronts arbitrary vLLM/NIM
fleets by design).

### F3 — the per-model config precedent already exists

`get_tool_calling_config(provider, model)` (`ppxai/config/providers.py:377`)
already implements provider-level defaults plus model-level override, read
from `ppxai-config.json`, consumed by `chat.py:187` and `execution.py:341`.
**The framework should extend this shape, not invent a second one.**

## Measured facts (Perplexity)

Live against `api.perplexity.ai` through our own provider client:

| Model | Native `tool_calls` |
|---|---|
| `sonar` | 400 `Tool calling is not supported for this model` |
| `sonar-pro` | emits `tool_calls` (full round-trip, canary-verified) |
| `sonar-reasoning-pro` | emits `tool_calls` |
| `sonar-deep-research` | 400 `Tool parameters must be a JSON object` |

Two constraints this imposes:

- **No `/models` endpoint.** `client.models.list()` returns 404 (verified
  2026-08-15). Capability cannot be discovered by enumeration; it must be
  declared (config/table) or probed.
- **`sonar` and `sonar-deep-research` HARD FAIL** (HTTP 400) rather than
  degrading. So "not tool-capable" must mean *reject before sending*, not
  *fall back to prompt-based* — the prompt-based fallback is exactly what
  Item 43 is about, and it produces refusal/confabulation.

## The new models and the Agent API — MEASURED 2026-08-15

The owner asked whether the new models (Claude Sonnet, etc.) ride the
OpenAI-compatible surface or require the Agent API. Answered by probing
the live API with a real key, not from docs.

### The new models are NOT on chat completions

All eight Agent-API model IDs tested return **HTTP 400 `invalid_model`**
on `/chat/completions` — the endpoint every ppxai provider uses today:

    anthropic/claude-sonnet-5, anthropic/claude-opus-5,
    openai/gpt-5.6-terra, google/gemini-3.1-pro-preview,
    xai/grok-4.6, perplexity/kimi-k3, perplexity/glm-5.2,
    perplexity/sonar                       -> all 400 invalid_model

The error names the documented model list. So chat completions serves the
four bare Sonar IDs ONLY (`sonar`, `sonar-pro`, `sonar-reasoning-pro`,
`sonar-deep-research`). **The new fleet is unreachable from our current
code path.**

### The Agent API is the OpenAI RESPONSES API

Two live endpoints found by probing: **`POST /v1/agent`** and
**`POST /v1/responses`** — both accept the new model IDs and return the
same body. The response shape is the OpenAI Responses envelope:

    {"object": "response", "status": "completed",
     "output": [{"type": "message", "content": [{"type": "output_text", ...}]}],
     "previous_response_id": null, "store": true, "parallel_tool_calls": true}

Verified working:

- `anthropic/claude-sonnet-5` answered a prompt through Perplexity.
- Native tool calling works — a `tools=[...]` request produced
  `{"type": "function_call", "name": "read_file",
      "arguments": "{\"path\": ...}", "call_id": "toolu_..."}`.
- **The stock OpenAI SDK drives it unchanged**:
  `OpenAI(base_url="https://api.perplexity.ai/v1").responses.create(...)`
  returned `status=completed`, `output_text="SDK-OK"`.

### What this changes

The earlier assessment in this plan — *"not OpenAI-compatible for tools,
needs a translation layer"* — was based on the docs and is **wrong**. It is
OpenAI-compatible; it is simply the *Responses* API rather than *Chat
Completions*. And ppxai **already implements the Responses API**:
`OpenAINativeProvider._chat_responses_api` (`openai_native.py:610`) exists
for Codex/Pro models and already handles `function_call` items.

So serving the new fleet is a **routing** problem, not a protocol problem:
per model, choose the Responses path or the Chat Completions path — which
is exactly the per-model capability table this plan already builds. One
provider-level `api_path`/`native_tool_calling` constant cannot express
"these four models use chat completions, those forty use responses".

`ToolCallingProfile` already carries an `api_path` field
(`get_tool_calling_config` supports it), so the table has somewhere to put
this.

An Anthropic-model note for ppxai-sre: the Agent API **requires
`max_output_tokens`** for `anthropic/*` (400 otherwise). That is a
per-model request-shaping rule — more table data, not a code branch.

### Relevance to agentic workloads (ppxai-sre)

This is the surface to build on if ppxai is to serve agentic workloads:
it is the only way to reach Claude/GPT/Gemini/Grok through one Perplexity
key, it does native tool calling, and it carries server-side conversation
state (`previous_response_id`, `store`) that the chat-completions path
lacks. Whether ppxai-sre should go through Perplexity or direct to
Anthropic remains a separate call — going direct avoids a middleman for
`anthropic/*`, and intersects the reserved `feat/anthropic-provider` work.

### There is still no SDK to migrate

No `perplexityai` import exists in `ppxai/` or `pyproject.toml` — we use the
OpenAI SDK, and the measurement above shows that stays true for the Agent
API too. The official `perplexityai` package (0.43.3) is not needed.

## Design

One declarative source of truth, consulted through one accessor.

    ModelCapabilityResolver:
        capabilities_for(provider, model) -> ProviderCapabilities

Resolution order (narrowest wins), mirroring `get_tool_calling_config`:

    1. ppxai-config.json  providers.<p>.models.<m>.capabilities   (per model)
    2. provider code      per-model table / prefix rules          (per model)
    3. ppxai-config.json  providers.<p>.capabilities              (per provider)
    4. provider code      default_capabilities                    (per provider)

CORRECTED during I2. The original ordering put both config layers above
both code layers; that is wrong. A provider-WIDE operator statement must
not outrank a shipped per-MODEL table — specificity wins before
authorship. Caught by running against the developer real config, which
carries `providers.openai.capabilities.native_tool_calling: true` (a
restatement of the default, predating per-model tables). Under the flat
ordering it silently cancelled the o4-mini benchmark table. Every I2 unit
test passed while this was broken.

Notes on the shape:

- Differences between models are **data** (a table keyed by model or
  prefix), never a second code path. Same rule the `TIERS` table follows.
- The table is compiled, but the config layers above it are operator-
  editable — capability is a *statement about the endpoint*, not a privilege
  grant, so a JSON typo degrades a feature rather than widening a security
  boundary. (Contrast `TIERS`, deliberately not JSON-describable.)
- `get_capabilities_for_model` stays the provider-facing method; providers
  gain a declarative table instead of hand-rolled overrides.

## Iterations

Each is independently committable, testable, and live-trialable. Do not
start N+1 before N is green and trialed.

### I1 — close F1: make the send paths honour the existing hook

No new mechanism. Change 3 sites to `self.get_capabilities_for_model(model)`;
thread `model` into `gemini._build_config` for the 4th.

- **Fixes a real shipped bug today** (o4-mini / gpt-4.1-mini).
- Trial: `o4-mini` with tools; confirm prompt-based routing is actually used.
- Fence: a test asserting no send path reads
  `self.capabilities.native_tool_calling`.

### I2 — the resolver plus config layers

Add `ModelCapabilityResolver` with the 4-layer precedence. No provider
behaviour changes yet — `default_capabilities` remains layer 4, so I2 is a
pure refactor with identical outputs.

- **Loader trap:** any NEW config key must be plumbed through
  `load_config()`'s whitelist or it is silently invisible. This has bitten 4
  times (`file_tree`, `execution`, `providers.<n>.web_search`, `network`).
  Test through the REAL loader, not a stubbed block reader.
- Fence: precedence matrix test; mutation-test each layer.

### I3 — Perplexity per-model table (closes Item 43) — ✅ DONE 2026-08-24

Took FOUR layers, not one. Each looked correct in isolation, and each was
inert until the one below it was fixed — the F1 shape, three more times:

1. **Capability table** (`PERPLEXITY_NATIVE_TOOL_MODELS`) — the obvious part.
2. **Model profile** — `sonar-pro*`/`sonar-reasoning-pro*` were pinned
   `mode="prompt_based"`, and `chat.py:693` checks the mode FIRST and
   short-circuits without reading capabilities. Measured:
   `profile.mode=prompt_based, caps.native=True -> use_native=False`. Both
   are now `"auto"`.
3. **`perplexity.chat()` ignored `tools` outright** — it carried
   `# Note: tools parameter is ignored` and had no native path at all, so
   the table, the profile and I1's send-path wiring were ALL inert here.
   Live-verified before the fix: sonar-pro produced 0 tool calls and refused
   in prose while every upstream layer resolved native=True. Added the
   tools/tool_choice kwargs plus `TOOL_CALL` event emission matching the
   `openai_compat` contract.
4. **Admission guard** — `sonar`/`sonar-deep-research` HTTP-400 on a tools
   array rather than degrading, and the fallback for a non-capable model is
   the prompt-based path that produced Item 43's confabulations. A
   tool-carrying run on those is refused before it is minted; fails OPEN on
   any unresolved lookup.

**Live trial (the actual proof):** `sonar-pro` and `sonar-reasoning-pro`
both emit a real `TOOL_CALL` event — `tool=read_file`, correct path
argument, `native=True`. `sonar` sends no tools array.

`sonar-deep-research` dropped from the shipped catalog (example config,
`install.sh`, `scripts/install.ps1`, `vscode-extension/src/config.ts`, and
their pricing tables). Its 400 is **not** a schema quirk after all: the
example config's own comment records it "uses Jobs API with
reasoning_effort … not chat completions", so it was never reachable on the
endpoint ppxai calls. Its `model_profiles.py` entry stays as a fallback for
anyone configuring it by hand.

Tests: 35, five mutations killed. The lesson worth carrying into I4b/I5 is
that a capability decision passes through FOUR independent layers, and a
green unit test at any one of them proves nothing about the wire. Trial
live, or check the request kwargs.

#### Original I3 scope (for reference)

`sonar-pro`, `sonar-reasoning-pro` to native. `sonar` not tool-capable. Drop
`sonar-deep-research` from the configured model list per owner decision (its
400 is a schema-shape complaint, unresolved and not worth carrying).

- Trial: `/task --tools read_file` on sonar-pro end to end, using the Item 43
  canary method (unguessable content) so a pass proves a real tool call.
- Also: a tool-capable `/task` on `sonar` must be REJECTED up front, not
  routed to the prompt-based path.

### I4 — refresh the Perplexity model roster — ✅ DONE 2026-08-24

Reconcile configured models against what the API actually serves. No
`/models` endpoint, so this is a capability PROBE per model (one request
carrying a `tools=[...]` array), not an enumeration. Feeds debt Item 38.

**Shipped:** `scripts/probe-perplexity-capabilities.py` + 23 offline tests
in `tests/test_perplexity_capability_probe.py`.

**Live result — no drift.** All three shipped models match the table:

| Model | Measured | Table |
|---|---|---|
| `sonar` | REJECTS (400 "Tool calling is not supported") | REJECTS |
| `sonar-pro` | NATIVE — *emitted a real tool call* | NATIVE |
| `sonar-reasoning-pro` | NATIVE | NATIVE |

`/models` re-verified **404**. `sonar-deep-research` (dropped at I3) still
returns its distinct parameter-SHAPE 400.

**Design points worth keeping:**

- **The roster is read from `ppxai-config.example.json`, not hardcoded** —
  a model added to config but never measured starts being probed with no
  edit to the script. The one thing a stale-table guard must not do is go
  stale itself.
- **Four verdicts, not two.** `REJECTS` (capability absent) and `SHAPE`
  (parameter-shape complaint) are different findings; `ABSENT`
  (`invalid_model`) is not a capability statement at all. Collapsing them
  would assert measurements we have not made.
- **`ERROR` is never a capability verdict.** A 401/5xx exits 2 and judges
  nothing — a failed probe must not read as "the model lost tool calling".
  Mutation-verified with a deliberately bad key: the run reported ERROR on
  a model the table calls NATIVE, rather than a false drift.
- **Drift is checked in both directions.** The underclaim direction (table
  says not-capable, API accepts) is the Item 43 shape — silent, and it cost
  about a month.

All four properties were mutation-tested by breaking the script and
confirming the suite goes red; the baseline was then restored and verified
byte-identical to the version that produced the live result above.

Also corrected here: **debt Item 38's "NOT OpenAI-compatible for tools …
needs a translation layer" paragraph**, which was doc-derived and wrong —
it survived unamended when this plan was corrected at I2, and would have
misdirected I4b.

### I4b — reach the new Perplexity fleet (Responses routing) — ⏰ DEADLINE-DRIVEN

> **2026-08-30:** the Sonar chat-completions endpoint **retires
> 2026-09-27** (web-verified; see debt Item 38 watch 2). I4b is executed
> as W0–W3 of [plan-adr-0012-implementation.md](plan-adr-0012-implementation.md),
> target 2026-09-20.

> **Superseded in shape by [ADR 0012](decisions/0012-wire-protocol-as-per-model-capability.md)
> (2026-08-30).** This section assumed `api_path` merely needed filling in and
> that the owner had to choose "new models on `perplexity`" vs "a second
> provider entry". Investigating found (a) `api_path` is declared, config-
> overridable and `/provider`-displayed but **never read** — routing is a
> hardcoded prefix tuple, and the two disagree on three models today; (b) the
> Responses helpers are private to `OpenAINativeProvider`, so "no new protocol
> code" was true of the behaviour but not the reachability. ADR 0012 makes
> protocol a per-model capability resolved through the I2 ladder, which
> dissolves the provider-entry question. I4b becomes step 3 of that ADR's
> migration.

Only after I1-I3 are green. Route `anthropic/*`, `openai/*`, `google/*`,
`xai/*`, `perplexity/*` model IDs to `POST /v1/responses` instead of
`/chat/completions`, driven by the table's `api_path` — no new protocol
code, because `_chat_responses_api` already speaks this shape and the stock
OpenAI SDK `.responses` client works against Perplexity unchanged
(measured).

- Table data, not branches: `api_path=responses`, plus
  `requires_max_output_tokens` for `anthropic/*`.
- Trial: `anthropic/claude-sonnet-5` through `/task --tools read_file`,
  canary-verified end to end.
- Open question for the owner: whether these appear as new models on the
  existing `perplexity` provider or as a second provider entry. The former
  is less config churn; the latter keeps two base URLs and two model
  namespaces visibly separate. Recommend deciding at I4b, not now.

### I5 — extend the table to the remaining providers

`gemini`, `openai_compat`, and fold `openai_native`'s
`PROMPT_BASED_MODEL_PREFIXES` into the same table so there is one shape, not
two.

**Deferred, explicitly not in this plan:** Agent API adoption (wire
translation layer, Item 38); `sonar-deep-research` schema investigation.

## Risks

- **I1 changes live routing for o4-mini / gpt-4.1-mini.** It is a fix, but it
  is a behaviour change on models in the user config — trial before moving on.
- **A capability table goes stale silently.** Perplexity gained tool calling
  and nothing told us for roughly a month. Mitigate with the I4 probe as a
  repeatable check, and record in Item 38 that a `/models`-style liveness
  sweep cannot see a capability change.
- **Config layers could disable a working capability.** Acceptable: degrades
  a feature, does not widen a boundary. `/doctor` should report the effective
  resolved capability and the layer it came from.

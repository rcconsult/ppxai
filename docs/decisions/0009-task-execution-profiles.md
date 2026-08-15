# ADR 0009 — Task execution profiles (config-driven grants + web_search as first-class enrichment)

**Date:** 2026-07-23
**Revised:** 2026-08-01 — field evidence from the Windows `/task` trials; Q2/Q4 settled; new Q5 (`preferred` pin-vs-ordering) and Q6 (one-shot preflight query origin).
**Revised:** 2026-08-01 (review pass) — Q1/Q3/Q5/Q6 written in; added §5 (grant resolution order — where `enrichment` derives), the `preferred`/`strict` scoped tuple, `oneshot_enrichment` as a key distinct from `oneshot_grounding`, and the static-vs-call-time scope of grant-time validation.
**Revised:** 2026-08-01 (design pass) — §4 oneshot enrichment changed from server-side preflight to **model-triggered search reusing the task-tier tool loop** (`chat_with_tools` + `ScopedToolManager`, `{web_search}`-only grant, bounded iterations); Q6's query-origin cluster dissolved by it. §6 added: target config shape (operator-review outcome — config must stop growing as per-code-path patchwork).
**Accepted:** 2026-08-01 — all six sign-off questions settled (see §"Sign-off"); implementation may proceed.
**Status:** Accepted — steps ① + ② + ③ **implemented v1.19.1** (2026-08-02: ① oneshot search loop as the F1–F5 facade over the run tier, live-verified full config matrix; ② per-tool `tools.<tool>.egress` baselines + https-only `get_weather` scheme-poison removal, Item 52 retired, live-verified. 2026-08-03: ③ `execution.profiles` + `--profile`/`--enrichment` on `/task` web+VSCode, `enrichment` in `_SPEC_FIELDS` (tri-state), Q1 replace-not-union merge with the skills-union exception, §5 derivation + both contradiction 400s, `execution.egress_ceiling` intersection at every allowlist-assembly site with the Q3 half-enriched fail-fast). 2026-08-03: ④ shared backend resolver — `engine/tools/search_backends.py` leaf, top-imported by both `web_premium` (chain = resolver candidates, ordering semantics, strict-only pin) and `network_policy` (egress = resolver hosts; provider context threaded via `NetworkPolicy(provider_name)` → `tool_targets`); Q5 scoped tuple + keyless fail-safe + dead-key warning; `/doctor` tuple report + 3 checks; Q3 refined to all-of over the effective set; the `web_premium.py` function-local import retired. **ALL FOUR STEPS COMPLETE.**
**Related:**
- [`0003-agent-platform-architecture.md`](0003-agent-platform-architecture.md) — the `/v1/agent/task` tier + per-run `ScopedToolManager` grant enforcement this builds on
- [`0004-llm-gateway-features.md`](0004-llm-gateway-features.md) — the stateless `/v1/oneshot` tier that shares the "context-blind local LLM" problem
- `ppxai/engine/agent_spec.py::AgentSpec` — the existing per-run profile primitive (`{task, system, tools, provider, model, budget, network, read_paths}`), loaded from `sandbox.specs_dir`, merged `request > spec > default`
- `ppxai/server/routes/agent_v1.py::_with_task_default_allow` (L758-768) — the ONLY config-driven egress-baseline mechanism today; wired for `web_search` only
- `ppxai/engine/tools/network_policy.py` — the AC-2 egress superset; `get_weather` targets are a hardcoded literal (Item 52)
- `ppxai/engine/tools/builtin/web_premium.py::get_premium_search_provider` (L34) — the **provider-aware** backend resolver used at call time
- `ppxai/engine/tools/network_policy.py::pinned_web_search_backend` (L213) — the **global-only** resolver the egress set is narrowed by; the disagreement between the two is Problem 4
- Debt inventory: **Item 52** (get_weather config-parity gap — subsumed by this ADR) and **Item 53** (this ADR's tracking entry)
- `../ppxai-sre/docs/PPXAI-INTEGRATION-V1.19.md` — primary Stage-2 consumer; §"Consumer alignment" below verifies this ADR respects its ownership boundaries (SRE owns dynamic tier policy A2; ppxai owns the primitives)

---

## Context

A `/task` (and `/v1/oneshot`) run is only as capable as the tools it is granted
**and** the egress those tools are allowed. Today that grant is assembled
per-run from three sources — the request flags, an optional `--spec` file, and
the `default_subagent` — and enforced by the per-run `ScopedToolManager`. Two
problems make this painful in practice:

### Problem 1 — the config-driven surface exists for `web_search` only

Commit `27ea00d9` established the intended pattern: **operator config knobs,
read by the engine, honored by the `/task` tier across the board.** `web_search`
received the full set — `tools.web_search.{preferred, enabled, task_default_allow}`
— where `task_default_allow` is a config-driven baseline egress allowlist merged
into every run by `_with_task_default_allow`. **No other tool got this.**
`get_weather` was left on a hardcoded egress literal with a known-broken
`http://wttr.in` entry that makes it *unallowlistable* on sealed local `/task`
(Item 52). So expanding the coder JSON schema fixed `web_search` everywhere but
covered nothing else. The mechanism is right; its reach is one tool wide.

### Problem 2 — no reusable, named grant

`AgentSpec` is a genuine "task profile" primitive, but it is a **file** passed
per run (`--spec <name>` under `sandbox.specs_dir`). There is no
`ppxai-config.json`-native, **named**, reusable profile a run selects by name —
so operators hand-wire the same `{tools, network}` for every research task, every
coding task, etc. The primitive is built; the ergonomic, config-first surface is
missing.

### Problem 3 — `web_search` is not "just a tool"; it is context enrichment

This is the load-bearing observation. A **local / self-hosted LLM** (vLLM Qwen,
DGX) has no built-in web grounding and a fixed training cutoff. For it, `/task`
and `/v1/oneshot` are **closed-book** unless `web_search` is granted AND its
egress allowed. Absent that, every local-LLM task silently degrades to reasoning
over only the prompt — no fact-checking, no current information, no source
enrichment. Contrast hosted providers (Perplexity Sonar, Gemini grounding) whose
search is **native** and for whom `web_search` is redundant. So `web_search` is
the **enrichment capability** for the local-LLM case, which is exactly why it
earned the config surface `get_weather` never got — and why a profile system
should treat "enable enrichment" as a first-class, opt-in profile property, not
a tool an operator must remember to hand-grant every time.

### Problem 4 — `preferred` is a hard pin, not an ordering, and two resolvers disagree about it

`tools.web_search.preferred` reads like "try this backend first, then fall back."
It is implemented as **use only this backend, never fall back**: when a pin is
active, `web_search_premium` forbids cross-backend fallback and returns an error
instead (`web_premium.py` L270-278, L304-309). So setting `preferred` to any
concrete backend kills the perplexity→gemini→DDG chain **in the live interactive
session too**, not merely under a sandbox. The session-parity baseline this ADR
treats as the reference behavior therefore holds only while `preferred` is
`"auto"` — the default. That name/behavior mismatch is the user-facing half of
the problem.

The mechanical half: the two resolvers do not agree on what the pin is.
`get_premium_search_provider(provider_name)` (`web_premium.py` L34) resolves
**provider-aware** — per-provider override, then global, then auto-detect.
`pinned_web_search_backend()` (`network_policy.py` L213) takes **no provider
argument** and reads only the global key. A per-provider override therefore
selects one backend while the egress set is narrowed to a different one
(`network_policy.py` L322-325).

That divergence is security-relevant, not merely cosmetic, because
`NetworkPolicy.authorize` pre-checks the **static** target set from
`tool_targets()` and never inspects the URL actually requested
(`network_policy.py` L430-435). Under a divergent pin, both directions are live
depending on the run's `allow_outbound`:

- the run allowlists the **pinned** host, `authorize` passes, and the request
  goes to the **other** backend's host — the run's egress allowlist is bypassed,
  which is precisely the confused-deputy case the superset rule exists to
  prevent; or
- the run allowlists the host actually needed but not the pinned one, and a
  legitimate call takes a false `network_policy_denied`.

Neither fires today: global `preferred` is `"auto"` → no pin → full superset.
A per-provider override is already present in real configs
(`providers.openai.web_search.preferred`), so a single global-config change arms
it. There is a fail-safe precedent to build on: a backend pinned *without its
API key* is already treated as no pin at all — "never narrow egress on a config
that can't take effect" (`network_policy.py` L179-187). A pin contradicted by a
per-provider override is the same class of dead config.

**Sign-off Q5 settles the pin's semantics, and the divergence fix follows from
it:** `preferred` becomes an **ordering**, with narrowing available only via an
explicit `strict: true`. The alternative — making `pinned_web_search_backend()
provider-aware while *preserving* hard-pin semantics — would have made the two
resolvers agree, but by ratifying the "only, never fall back" reading that is the
opposite of the session parity Problems 1-3 ask for. Under the settled ordering
semantics the divergence largely dissolves by construction: with no `strict`
flag there is no narrowing to disagree about, and the shared resolver (see
"Requires", below) is what keeps the two call sites in agreement when there is.

---

## Decision

Introduce **task execution profiles**: named, config-driven, reusable grants
that reuse the `AgentSpec` shape, with per-tool egress baselines and a
first-class `web_search` enrichment property.

### 1. Named profiles in config, reusing `AgentSpec`

Key locations below are the **ADR 0010 final names** (`execution.*`,
`tools.<tool>.egress`) — both ADRs were accepted 2026-08-01, so new keys land
in their final home on day one; legacy names (`tools.agent.*`,
`task_default_allow`) appear only when describing today's code or the dual-read
migration.

```jsonc
"execution": { "profiles": {
  "research": {
    "tools": ["web_search", "fetch_url", "read_file"],
    "enrichment": true,            // auto-grant web_search + the SEARCH egress
                                   // baseline (backend superset) — derived per
                                   // §5, NOT listed in "network" below
    "network": { "allow_outbound": ["api.open-meteo.com", "wttr.in"] },
                                   // ADDITIONAL egress beyond enrichment's:
                                   // here, hosts for get_weather-style calls
    "budget": { "iterations": 20 }
  },
  "coding": {
    "tools": ["read_file", "search_files", "apply_patch", "write_file"],
    "enrichment": false            // closed-book by intent; no egress widening
  }
}}
```

A run selects one by name — `--profile research` (client) / `"profile": "..."`
(wire) — resolved through the **same `spec_from_mapping` normalizer** the
`--spec` path already uses. Precedence extends the existing chain:
**request > spec > profile > `default_subagent` > built-in default**. Zero new
schema shape — a profile *is* an `AgentSpec` mapping in a config location.

### 2. Per-tool egress baselines (generalize `task_default_allow` → `tools.<tool>.egress`)

The egress baseline becomes per-tool, not `web_search`-only, under the ADR 0010
final name **`tools.<tool>.egress`** (today's `tools.web_search.
task_default_allow` is the legacy spelling, honored during the dual-read
window). `_with_task_default_allow` reads the union across the run's granted
tools. This **subsumes Item 52**: `get_weather`'s key-free hosts (Open-Meteo,
https wttr.in) become `tools.get_weather.egress` (or a profile's `network`),
read by the engine — one config-driven mechanism, working across local `/task`,
coder, and future tiers, exactly as `web_search` already does. (The contained
`http://wttr.in` scheme-poison removal still lands as part of the fix — an
always-denied scheme must never gate a tool.)

### 3. `enrichment: true` — opt-in, explicit, never a silent default

A profile with `enrichment: true` auto-grants `web_search` **and** merges its
egress baseline, so the context-blind-local-LLM case is solved *by construction*
for that profile. Crucially it is **per-profile and opt-in**: a locked-down
tenant profile sets `enrichment: false` and gets no egress widening. This keeps
the AC-2 confused-deputy protection intact — enrichment is a deliberate
declaration, not a global on-switch. Opt-in is at the **profile** level, so a
config-designated default profile still spares the operator from re-declaring it
per run; that is the ergonomic ask, and it does not require a global switch.

**Scope is `web_search` only — explicitly NOT `fetch_url`.** `web_search`'s
egress is a fixed, known host set (Perplexity / Gemini / DuckDuckGo); the model
chooses the *query*, never the *target*. `fetch_url` takes an
attacker-influencable arbitrary host and would forfeit that property, along with
the safety argument for §4 below. Enrichment also carries **no provider
routing**: it does not steer a run toward a search-native provider. Provider and
model are already independently selectable per run (`--provider` / `--model`) and
by config (`execution.default_subagent.{provider,model}`), and conflating the
two would make an egress grant silently change which model answers.

**The enrichment egress baseline is the full backend superset, not one backend
— unless `strict: true`.** Session parity *is* the fallback chain, so the honest
egress set for an enriched run is every host the chain can reach — the same
superset `tool_targets()` returns in `"auto"` mode. Narrowing it to a single
backend does not harden the run; it disables the chain (Problem 4).

The one sanctioned narrowing is Q5's `strict: true`, and it composes rather than
conflicts: **`strict: true` narrows the enrichment baseline to the pinned
backend's hosts, and enrichment remains satisfied so long as that backend is
usable.** An operator setting `strict` has already accepted "this backend or
nothing"; enrichment does not override that choice, it inherits it. Two
consequences must be documented rather than discovered: the run loses the
fallback chain, so a single backend outage returns it to closed-book; and the
existing "a backend pinned without its API key is no pin at all" fail-safe
(`network_policy.py` L179-187) is what keeps a dead `strict` pin from silently
starving enrichment. `/doctor` should warn on `strict: true` + `enrichment:
true` for exactly that reason. `strict` is therefore **compatible** with
enrichment — it is not a grant-time error.

### 4. `/v1/oneshot` enrichment — model-triggered search via a scoped slice of the task-tier loop

Oneshot is where the closed-book problem bites hardest: a custom or local model
with a fixed cutoff, no tools and no grounding produces confidently wrong
answers, which makes the tier near-useless as a sub-agent for fact-dependent
work.

**One-shot enrichment is model-triggered search: `web_search` — and ONLY
`web_search` — is exposed to the model through the SAME bounded tool loop the
`/task` tier already runs, with a low iteration cap.** The model decides, per
prompt and mid-inference, whether it lacks the information to answer — exactly
the semantics of Perplexity Sonar and Gemini grounding, where the provider's
LLM triggers search when the request needs it. A prompt that doesn't need facts
takes a single round-trip with zero tool calls, indistinguishable from today; a
prompt that semantically asks for more than the model knows triggers a
model-formulated search, then the answer.

An earlier draft of this section specified a **server-side preflight** (search
before the model call, inject results into the prompt). Rejected on review: the
server cannot know whether a given prompt needs search — only the model can —
so a preflight is structurally either always-search (paying latency, cost and
disclosure on prompts that never needed it) or a server-side heuristic guessing
at the model's knowledge gaps. It also spawned its own question cluster (query
origin, verbatim-prompt disclosure guards, always-vs-conditional) that the
model-triggered design dissolves: **the model writes its own search query**, so
no caller `query` field, no verbatim-prompt fallback, no disclosure of anything
but the model-chosen query, and no search-trigger heuristic. The request schema
needs nothing added; the response gains one optional field (see "Wire
contract" below).

**Structural reuse, not new machinery.** The `/task` tier already executes runs
via `chat_with_tools` through a per-run `ScopedToolManager` (`agent_v1.py`
L787) — a bounded tool loop with grant enforcement (AC-1), egress enforcement
(AC-2, `NetworkPolicy`), and budgets, running server-side outside any
interactive session (`agent_runs.py` is the construction precedent). Enriched
oneshot is that same loop with a grant of exactly `{web_search}`, egress = the
§3 enrichment baseline, and a small iteration cap — a scoped slice of existing
gears, not a second tool-execution path. When the first oneshot implementation
shipped (ADR 0004), this machinery did not exist; now that it does, reusing it
is the structural choice, and the search calls run under the same
`NetworkPolicy.authorize` and emit the same audit events as every other tool
call.

This does mean ADR 0004's "no tool loop in oneshot" purity is **explicitly
revised** rather than preserved. What is preserved is the property that
mattered underneath it: **the perimeter.** Only `web_search` is callable — a
tool whose egress is a fixed, known host set where the model chooses the
*query*, never the *target* (§3) — no filesystem, no shell, no
attacker-influencable destination. The tier stays stateless (no run registry
entry, no durable state); "oneshot" means one request/one response, not
one model call.

**Its config key is `execution.oneshot.enrichment`, default off — a new key,
deliberately NOT a reuse of the grounding switch.** (ADR 0010 final name; the
native-search switch shipped as `tools.web_search.oneshot_grounding`,
`oneshot.py` L130-146, and migrates to `execution.oneshot.grounding` in the
same window.) The grounding key turns on the **provider's own** native search;
this one exposes the **`web_search` fallback chain to the model**. Different
mechanism, cost, and egress profile — an operator reading one key name must not
have to guess which they enabled, which is why both live side by side under
`execution.oneshot.*` rather than on the tool block.

> **Amendment (2026-08-02, owner-approved — ADR 0011):** two details of this
> section are superseded by the command-taxonomy streamline
> ([0011](0011-command-taxonomy-streamline.md)), decided before any of it was
> implemented (no migration):
> 1. **Key location:** the pair lives under **`execution.run.*`**
>    (`execution.run.web_search`, `execution.run.grounding`) — the surface is
>    now the `/run` command family, and the key literally enables/disables
>    `web_search` for `kind=oneshot` runs (UX `/run` + API `/v1/oneshot`
>    facade share one brain). The side-by-side principle above is unchanged.
> 2. **"No run registry entry":** enriched oneshot executes as a real
>    registry run (`kind=oneshot`) — the facade over unmodified task gears
>    ([plan](../archive/plan-adr0009-step1-oneshot-enrichment.md)). "Stateless" keeps
>    its ADR 0004 meaning (no *session* side-effects); the run record is the
>    audit + debug surface, and the sync HTTP response is unchanged.

**Gating — decided per request on EFFECTIVE native grounding, not provider
capability alone.** A provider "takes the native path" only when native
grounding is actually on (`oneshot_grounding: true` AND the provider is
search-capable) — capability with the switch off is not grounding, and today's
code deliberately disables Gemini chat-grounding in that case (`oneshot.py`
L261-268, the default-OFF guarantee). The full truth table:

| `oneshot_grounding` | `oneshot_enrichment` | native-capable | tool-calling | Result |
|---|---|---|---|---|
| on | any | yes | any | **native grounding** (loop never runs — never both) |
| on | off | no | any | closed-book (grounding key can't help a non-native provider) |
| off | on | any | yes | **search loop** — including a native-capable provider whose operator left native off: enrichment is an explicit opt-in and does not silently re-enable the path the operator declined |
| off | on | any | no | closed-book, **reported** (see below) |
| off | off | any | any | closed-book — today's behavior, byte-identical |

- **Tool-calling capable** means the model can emit tool calls (local vLLM with
  hermes/harmony parsers qualifies — the primary closed-book case this exists
  for). A model that qualifies for no row's search path stays closed-book
  *honestly* — that is a model limitation, not a harness gap, and silently
  degrading to a server-guessed preflight would reintroduce everything this
  design rejected. `/doctor` reports the effective grounding path per
  configured model, since "which grounding am I getting" must not require
  reading code.

**Wire contract — request unchanged; response gains ONE optional field.**
`OneshotResponse` today is `{content, finish_reason, model, provider, usage}`
(`oneshot.py` L117-122) — there is no metadata channel, no event stream, and no
run-registry entry on this tier, so "surface it in events" is not implementable
here and a log-only sink would make grounded and ungrounded answers
indistinguishable to the caller. The contract is therefore an **optional
`grounding` response field**, additive and semver-minor, absent whenever
enrichment is off (existing consumers see byte-identical responses):

```jsonc
"grounding": {                    // present only on enriched requests
  "searched": true,               // false = model chose not to search
  "queries": ["..."],             // model-formulated queries actually sent
  "backend": "perplexity",        // chain backend that answered
  "search_cost": 0.005            // premium-search cost, USD (0 for DDG)
}
```

**Accounting.** The loop's extra model round-trips are real prompt/completion
tokens and land in the existing `usage` field — no schema change there.
Premium-search cost is computed by the existing `calculate_tool_cost`, but it
must be **returned with the individual search invocation (or attached to the
request context), NOT read via `get_last_tool_usage()`** — that accessor is a
process-global with reset-on-read semantics (`web_premium.py` L22, L384-396:
`_last_tool_usage = None` after extraction), which under two concurrent
enriched requests silently attributes one request's search cost to the other.
Fine for the single-session interactive path it was built for; disqualifying as
a per-request accounting contract. The per-invocation usage feeds
`grounding.search_cost` and the cross-tier accounting ADR 0008 defines, so
enriched-oneshot spend is not invisible to `/cost`. Search-backend errors do
not fail the request: the loop surfaces the tool error to the model, which
answers with what it has — `searched: true` with the failure noted in the
audit sink.

**Audit sink — decided, because this tier has no run registry and no event
stream to inherit.** The enriched-oneshot loop runs in an **ephemeral,
in-memory context** (built per request, discarded after — the tier stays
stateless; no `~/.ppxai/runs/` entry, no SSE channel). Its audit trail is
therefore two-channel: **caller-facing**, the `grounding` response field (the
authoritative record of what was searched); **operator-facing**, the tool-call
and `NETWORK_POLICY_ALLOWED/DENIED` decisions written to the standard server
log (debug-log honoring `tui.debug_log` semantics), tagged with the request's
correlation id. No new event type, no registry coupling — an operator who
needs durable per-run audit uses the `/task` tier, which exists for exactly
that.

**Other observable changes warranting a consumer heads-up:** latency and search
cost when (and only when) the model searches; **prompt contents** (retrieved
text enters the context the model answers from); **disclosure** limited to the
model-formulated query leaving to the search backend.

**What "safe" means here, precisely.** Host- and filesystem-safe, **not**
injection-proof. A prompt injection cannot modify the host, touch a file, or
steer egress to an attacker-chosen destination — the only callable capability
has a fixed target set. It can still (a) influence the answer text, since
retrieved content enters the context, and (b) influence what the model puts in
its search query. Both are inherent to grounding of any kind, including the
native path already shipped, and both argue for default-off rather than against
the capability.

### 5. Grant resolution order — where `enrichment` derives

`enrichment` is a **derived** grant: it adds `web_search` and its egress rather
than being written out by the operator. The draft never said *when* in
resolution that derivation happens, and two settled answers contradict each
other until it does — Q1 guarantees a narrower layer can remove a tool, while §3
auto-grants one. The resolution order is therefore normative:

1. **Resolve every declared field through the precedence chain** (request > spec
   > profile > `default_subagent` > built-in default), with list-valued fields
   replacing per Q1. `enrichment` resolves here too, as an ordinary **scalar**
   field — exactly like `provider` and `model`.
2. **Then derive, once, from the resolved values.** If effective `enrichment` is
   true, add `web_search` and its egress baseline (superset, or the pinned
   backend's hosts under `strict`) to the effective grant.
3. **Then apply the Q3 ceiling intersection**, and fail fast per Q3 if it leaves
   an enriched run without a usable backend.

**When "grant time" is, precisely — two validation stages, matching the task
lifecycle as built.** The route today starts the run and validates the grant
inside the background execution (`agent_v1.py` L1094 — deliberately, per
Item 50: tool *existence* is only checkable once a live engine has registered
its tools). So "fail fast" splits:

- **Pre-start (HTTP 4xx, no run created):** everything resolvable from config
  and the request alone — unknown profile name, the §5 contradiction cases, the
  Q3 ceiling-vs-enrichment check. These need no tool registry, so deferring
  them to an async run failure would be gratuitous.
- **Pre-execution (run created, fails before any model call):** checks that
  need the live registry — tool existence (Item 50) stays where it is. This is
  "fail before execution", not an HTTP error, and the run's failure event names
  the cause.

Derivation after resolution, never per layer. Two rules follow, and they are the
answer to "does a narrower `tools` list re-add `web_search`?":

- **To narrow enrichment, set `enrichment: false`** — that is the field designed
  for it. A spec composing over an enriched profile disables the derived grant
  by saying so, which keeps Q1's "a narrower layer can remove a tool" property
  intact *through the field that expresses it*, not by omission.
- **Omission is not denial, but contradiction is an error.** If a layer at or
  more specific than the one declaring `enrichment: true` states an explicit
  `tools` list that omits `web_search`, the two fields disagree about the same
  run. **Fail fast at grant time**, naming both layers — do not silently pick a
  winner. This is the Q3 rule applied to a second unsatisfiable configuration:
  an operator who wrote both meant one of them, and guessing reproduces the
  silent-closed-book failure in a new place.

### 6. Config placement — this ADR's keys must not extend the patchwork

The config has grown organically, key-by-key, tracking code execution paths:
each new tier taught `tools.web_search` a new switch (`task_default_allow`,
`oneshot_grounding` — and this ADR's enrichment switch would have been the
third, had ADR 0010 not landed first), and the whole execution tier
lives under `tools.agent.*` because it historically grew out of the
`spawn_subagent` tool. Operator-visible result: three keys on one tool block
that answer three different questions ("which backend?", "what egress on
/task?", "may oneshot ground?"), and an "agent" that is not a tool configured
as one. The full reorganization is **ADR 0010** (config-shape review) —
**accepted the same day as this ADR**, so this ADR's new keys land directly in
their 0010-final homes on day one, with no second migration:

- **Tool-intrinsic keys on the tool block:** `tools.web_search.preferred` +
  `strict` (the Q5 scoped tuple — how the tool picks backends, regardless of
  tier), backend model choices, and per-tool **`tools.<tool>.egress`** (§2 —
  the hosts a *tool* needs are a property of the tool; today's
  `task_default_allow` is the legacy spelling, honored only through 0010's
  one-release dual-read window).
- **Execution-tier keys under `execution.*`, not on tools:**
  `execution.profiles` (§1), `execution.egress_ceiling` (Q3),
  `execution.default_subagent`, and the oneshot switches
  `execution.oneshot.{grounding, enrichment}` (§4) — tier behaviors ("may this
  tier expose search to the model"), not search-tool properties. The shipped
  `tools.web_search.oneshot_grounding` migrates alongside via dual-read.
- **Override axes follow the Q5 rule everywhere:** where a key is overridable
  per provider/model, the override is a **scoped tuple** (scope chosen once,
  related fields read together), never independent per-field fallback.

### Options considered

- **Option A — profiles reusing `AgentSpec` + per-tool egress + `enrichment`
  (recommended).** One normalizer, one precedence chain, subsumes Item 52. Con:
  new config surface + a precedence rule to document/test.
- **Option B — fix `get_weather` only (Item 52 spot-fix), no profiles.**
  Cheapest; leaves Problem 2/3 unsolved and the config surface one-tool-wide.
- **Option C — profiles WITHOUT `enrichment`; operators hand-list `web_search`
  + egress per profile.** Simpler schema; but re-buries the enrichment decision
  in boilerplate every operator must get right, which is the ergonomic problem
  we set out to fix.

---

## Why not just keep `--spec` files

`--spec` is per-run and path-based; it answers "shape THIS run," not "define a
REUSABLE research grant once." Profiles are the named, config-native layer over
the same primitive — specs stay for one-off/authored runs, profiles for the
standing set an operator curates. They compose (request > spec > profile), not
compete.

---

## Triggers to revisit / decide

- A local-LLM `/task` or `/v1/oneshot` returns a stale/closed-book answer because
  `web_search` wasn't granted (the enrichment gap made concrete).
- Item 52: weather unusable on sealed local `/task` (the config-parity gap).
- Operators hand-wiring the same `{tools, network}` across many runs (the
  reusable-grant gap).
- A tenant needs a locked-down, no-egress task profile (the opt-in-enrichment
  requirement).
- **FIRED (Windows `/task` trials, 2026-07):** a local-LLM `/task` run, denied
  search, **produced a `execute_shell_command` + `curl` request for network
  access**. It failed closed as designed (`SHELL_TOOL_NAMES` is refused at grant
  time and again whenever an egress policy is active). The behavior is the
  finding: an under-granted local model does not degrade quietly, it reaches for
  the boundary under prompt pressure. **This is evidence of capability starvation,
  NOT an argument for granting shell.** The correct response is legitimate
  `web_search` enrichment plus continued, unambiguous denial of shell — widening
  the grant to shell would trade a correctness problem for a containment
  failure. (Recorded from the operator's report; whether the model emitted a
  refused tool call or only proposed `curl` in text is not established from the
  trial transcript, and the evidence does not depend on which.)

---

## Consequences

**Implementation requirements (Option A, accepted):**
- Enables: named reusable grants; one config-driven egress mechanism for ALL
  tools (retires Item 52's weather-specific path); enrichment solved by
  construction for local LLMs; per-profile security posture.
- Requires: the `execution.profiles` config block + `--profile` selector;
  per-tool `tools.<tool>.egress` (legacy `task_default_allow` via dual-read)
  read in `_with_task_default_allow`; precedence rules
  (request > spec > profile > default) documented + sentinel-tested; the
  `http://wttr.in` scheme-poison removal.
- Requires (from Problem 4 / Q5): a single shared backend resolver (leaf module,
  imported at top level by both `web_premium` and `network_policy`) returning a
  **structured result**: the **scope the answer came from** (which provider
  block, or global — the field that makes the Q5 tuple auditable), the **ordered
  backend candidates**, the **effective strictness**, and the **effective egress
  host set**. Both consumers read one answer instead of each inspecting global
  config and environment independently — which is what lets a reviewer or a
  `/doctor` check see *why* a backend was chosen, and is the structural reason
  the global-vs-provider divergence cannot quietly return. This also retires the
  undocumented function-local import at `web_premium.py` L277.
- Requires: provider/tier context threaded into egress resolution —
  `tool_targets()`, `NetworkPolicy.authorize()` and `ScopedToolManager.__init__`
  all gain it (verified: the manager has no provider today,
  `agent_scoped_tools.py` L69-77; the constructing route does, `agent_v1.py`
  L349-374 / L1088-1092).
- Requires: tests for the currently-missing case that exposes the bug — **global
  preference plus a conflicting per-provider override**, asserting the enumerated
  egress set and the host actually contacted agree. Extends
  `tests/test_web_search_task_config.py`.
- Requires (from Q1): **replace-not-union** semantics for `tools` and
  `network.allow_outbound` in `spec_from_mapping`'s layer merge, with a sentinel
  test asserting a narrower layer can actually *remove* a tool and a host —
  the property that silently inverts if anyone "fixes" the merge to union later.
- Requires (**blocker**, from §3/§5): **`enrichment` must be added to the
  `AgentSpec` shape.** It is not there today — `_SPEC_FIELDS` is a frozenset of
  exactly `{task, system, tools, provider, model, budget, network, read_paths}`
  (`agent_spec.py` L38-39), and `spec_from_mapping` **drops unknown keys with a
  warning** (`agent_spec.py` L110-112). So a profile written per §1 today
  resolves to a grant with no `web_search` and an `ignored unknown spec keys:
  ['enrichment']` line buried in `spec.warnings` — the silent closed-book failure
  of Problem 3, arriving through the very feature meant to fix it. The field must
  land in `_SPEC_FIELDS`, in normalization (scalar, tri-state:
  true / false / absent-means-inherit), and in the §5 resolution order.
- Requires (from §5): the derivation step implemented **after** precedence
  resolution, not per layer, plus grant-time errors for the two contradiction
  cases — an explicit `tools` list omitting `web_search` under effective
  `enrichment: true`, and Q3's ceiling leaving an enriched run backend-less.
- Requires (from Q3): a `execution.egress_ceiling` config key; intersection
  applied where the run's effective allowlist is assembled; unset = no cap; and a
  **grant-time hard failure** when the intersection leaves an `enrichment: true`
  profile without the backend superset, with an error naming the stripped hosts.
- Requires (from Q5): a `tools.web_search.strict` key resolved as a **scoped
  tuple with `preferred`** (scope selected once, both fields read from it;
  defaults `"auto"` / `false`), never by independent per-field fallback; a
  precedence-matrix test over provider / global / mixed / neither; `/doctor`
  checks for (a) a concrete `preferred` without `strict` — the upgrade behavior
  change, (b) a per-provider `strict` with no per-provider `preferred` — a dead
  key, and (c) `strict: true` together with `enrichment: true` — legal, but it
  costs the fallback chain; and a release-note callout for the
  egress-widens-on-upgrade change.
- Requires (from §4/Q6): the enriched-oneshot execution path — reuse
  `chat_with_tools` + a `ScopedToolManager` granting exactly `{web_search}`
  (construction pattern per `agent_runs.py`), small iteration cap, egress = the
  §3 enrichment baseline, enforced by the same `NetworkPolicy`; **request
  unchanged, response gains the optional `grounding` field** (§4 "Wire
  contract") carrying searched/queries/backend/search_cost; loop tokens land in
  the existing `usage`; search cost feeds ADR 0008 accounting. Gated per the §4
  truth table on **effective** native grounding (not capability) AND per-model
  tool-calling; a single request never takes both grounding paths. A `/doctor`
  line reports the effective grounding path per configured model; sentinel
  tests cover every truth-table row.

**Current pre-implementation state (what ships today, until the above lands):**
- `web_search` is the only tool with config-driven egress; `get_weather` is
  unallowlistable on sealed local `/task` (Item 52 held pending this design).
- No named reusable profiles; grants are hand-assembled per run.
- Local-LLM tasks are silently closed-book unless the operator remembers to
  grant + allow `web_search`.

---

## Consumer alignment — ppxai-sre (verified 2026-07-23)

Checked against `../ppxai-sre/docs/PPXAI-INTEGRATION-V1.19.md` (§"What stays in
this repo", caveats C1–C5, asks A1–A3). ppxai-sre is the primary Stage-2
consumer, so this ADR must not contradict its ownership boundaries.

**Aligned — profiles are a config convenience OVER the primitive, and SRE
doesn't consume them.** ppxai-sre drives runs through the **wire** (`POST
/v1/agent/run` + tools, C4) with an explicit per-run grant it computes itself;
it does not select ppxai config profiles. A profile is resolved to the same
`AgentSpec`/`tools`/`network` a request already carries, so the wire surface SRE
depends on is **unchanged** — profiles add a naming/default layer local operators
opt into, and the `request > spec > profile > default` precedence keeps an
explicit wire grant authoritative (request wins). Nothing here alters
`/v1/agent/run`, its `tools` field, or the run namespace.

**The one tension — do NOT let profiles become a policy/tier engine.** SRE's
philosophy is explicit and load-bearing: the **3-tier classification
(Autonomous / Notify-and-Act / Require-Approval) is SRE-shaped, "not
generalizable"** (§5.2), and A2 asks for a **registered policy callable** that
decides tiering *dynamically at call time* — "ppxai's dialog only fires when the
callable returns 'ask user.'" ppxai provides the **primitives** (per-tool consent
contract, Phase-5 network-policy, egress allowlist); SRE owns the **policy**.

Therefore this ADR's scope is deliberately bounded:
- Profiles are **static grant + egress composition** (which tools, which egress
  baseline), NOT dynamic per-call authorization. `enrichment: true` is a
  *grant-time* default (adds `web_search` + its egress to the run's allowlist),
  not a *call-time* decision — it never pre-empts or replaces the consent
  contract / A2 policy callable.
- The `enrichment` opt-in and the deployment egress ceiling
  (`execution.egress_ceiling`, Q3) must compose UNDER a deployment policy hook,
  not above it: a profile may not widen egress beyond what an SRE-registered
  policy (A2) or the ceiling permits. Profiles propose a grant; policy disposes.
  The ceiling is config-only and intersective, so it cannot be raised by a run —
  which is what makes "propose, don't dispose" mechanical rather than a
  convention.
- **The Q3/§5 grant-time fail-fast is scoped to STATIC configuration, and does
  not claim call-time authority.** It validates the resolved grant against
  config the server can see before the run starts — the ceiling, the profile,
  the spec. It cannot pre-validate an A2 policy callable, which decides *per
  call* and may legitimately deny a backend the grant allowed. So the guarantee
  is precisely: **a run never starts half-enriched because of static
  configuration.** A run may still lose enrichment mid-flight to a policy denial,
  and that is correct — policy retains final say, and a grant-time check that
  tried to pre-empt it would be the call-time policy engine this ADR promises not
  to become. The two mechanisms are ordered, not competing: static validation
  first, dynamic policy always after. A mid-run policy denial of an enriched
  run's only backend should surface as the existing
  `NETWORK_POLICY_DENIED` event (C1) — no new contract — so the operator can tell
  a policy denial from a misconfiguration.
- Per-tool `tools.<tool>.egress` emits the SAME `NETWORK_POLICY_ALLOWED/DENIED`
  events (C1) already committed — profiles change what's in the allowlist, not
  how enforcement or audit is surfaced. No new event type, no internal tap.

**Net:** ADR 0009 is a local-operator ergonomics + config-parity layer on the
grant side. It stays clear of the run wire shape (C3/C4), the audit event
contract (C1/A1), and the dynamic tier-classification hook (A2) that ppxai-sre
owns. If any future revision moves profiles toward *call-time* policy, that is a
conflict with A2 and must be re-litigated with the SRE boundary in view.

## Sign-off

### Settled (2026-08-01)

1. **Precedence** — **the draft order stands: `request > spec > profile >
   default_subagent > built-in default`.** A `--spec` file is authored for one
   run; a profile is a standing, curated grant — so the spec is the more specific
   layer and correctly outranks the profile.

   **Merge semantics for list-valued fields (the part the draft left unstated):
   `tools` and `network.allow_outbound` REPLACE, they do not union.** A more
   specific layer that supplies the field supplies all of it. If lists unioned, a
   grant could only ever grow and **narrowing would be inexpressible** — a spec
   could never take a tool or a host away from the profile it composes over. That
   is the wrong default for a security surface. (Layers that omit a field inherit
   it unchanged; replacement applies only where a layer states the field.)
2. **`enrichment` scope** — `web_search` **only**; not `fetch_url` (arbitrary
   host forfeits the fixed-target property §3/§4 rest on), and **no** implied
   provider preference: provider/model are already selectable per run and by
   config, and coupling them to an egress grant would let a tool grant silently
   change which model answers.
3. **Egress trust / ceiling** — **`execution.egress_ceiling`, config-only,
   intersective.**
   - **Config-only, never per-run** — a run that could state its own ceiling
     could raise it, which is not a ceiling.
   - **Effective allowlist = intersection** of the resolved profile/spec/request
     egress union with the ceiling.
   - **Unset = no cap**, for back-compat with every deployment that has no
     ceiling today.

   **The sharp edge — what happens when the intersection strips a host an
   `enrichment: true` profile needs: fail fast at grant time with an explicit
   error** — pre-start, HTTP 4xx, no run created; this check is
   config-resolvable, unlike the registry-dependent checks §5's two-stage
   validation keeps pre-execution. Do not start the run half-enriched. A degraded-but-running enriched
   profile reproduces precisely the closed-book failure this ADR exists to fix
   (Problem 3), except now silent and harder to diagnose — the operator declared
   enrichment, the run reports success, and the answer is unknowingly
   ungrounded. An unsatisfiable enrichment grant is a **configuration error**,
   and it should read as one. This also discharges the §3 floor-vs-ceiling note:
   the floor is not quietly lowered to fit the ceiling; the conflict surfaces.
4. **`/v1/oneshot`** — **yes**, enrichment extends to oneshot: `web_search` only,
   model-triggered through a scoped slice of the task-tier tool loop (revised
   from the earlier preflight draft — see §4), its own config key, default off.
   See §4 for the perimeter argument and the observable-behavior cost.
5. **`preferred` — pin or ordering?** — **(b): ordering, plus explicit
   strictness.** `preferred` becomes first-choice-then-fall-back;
   `tools.web_search.strict: true` preserves today's narrowing for operators who
   want it. Chosen over a separate `backend_lock` key because a second key naming
   a second backend can contradict `preferred` and would need a third precedence
   rule; a boolean modifier cannot.

   **`preferred` and `strict` resolve together, as one scoped tuple — never as
   two independently-inherited fields.** Resolution selects a *scope* first, then
   reads both fields from it:

   - if the provider block states `preferred`, the scope is **that provider
     block** — `strict` is read from it too, defaulting to `false` when absent;
   - otherwise the scope is the **global** `tools.web_search` block, and both
     fields are read from there;
   - defaults when neither states them: `preferred: "auto"`, `strict: false`.

   The failure this forecloses: a per-provider `preferred` inheriting a global
   `strict: true` it was never meant to be locked by — Problem 4 reproduced one
   layer up, with the same divergence between what the resolver picks and what
   egress is narrowed to. Independent per-field fallback is what creates it, so
   the tuple is the fix, not a convention. **A per-provider `strict` without a
   per-provider `preferred` is a dead key** — it is out of scope by construction,
   and `/doctor` should flag it rather than let it look effective.

   Requires a **precedence-matrix test** over provider-level / global-level /
   mixed / neither, asserting the selected backend, the strictness actually
   applied, and the enumerated egress set all come from the same scope.

   Rejected: **(a) ordering with no strictness at all** — same divergence fix,
   but operators lose the ability to narrow `web_search` egress to one backend
   entirely. **(c) keep the hard pin, make it provider-aware** — minimal change
   and it does fix the AC-2 divergence, but it ratifies `preferred` meaning
   "only", leaving the session-parity semantics broken, which is the complaint
   that prompted this revision.

   **Migration note:** a deployment that today sets `preferred` to a concrete
   backend gets hard-pin narrowing as a side effect. Under (b) that behavior now
   requires adding `strict: true`; without it, **egress widens to the superset on
   upgrade**. This is a behavior change for existing configs and needs a
   release-note callout and a `/doctor` check.
6. **One-shot enrichment — who decides to search, and where does the query come
   from?** — **the model, in both cases** (§4, revised from the preflight
   design).

   The question as originally posed — caller `query` field vs. verbatim prompt
   vs. extraction call — belonged to the rejected preflight, where the server
   had to guess. Under model-triggered search the model decides *whether* to
   search per prompt (native-grounding parity: search-free prompts stay a
   single round-trip) and *formulates its own query* — the same as every
   interactive-session search today. That dissolves the sub-questions rather
   than answering them: no wire addition, no verbatim-prompt disclosure (only
   the model-chosen query leaves the host), no length-cap/redaction machinery,
   no always-vs-conditional heuristic to own.

   What replaces them is one implementation-owned obligation:
   - **Observability:** the optional `grounding` response field (§4 "Wire
     contract") — searched-or-not, the model's queries, backend, and search
     cost — so a caller can tell a grounded answer from an ungrounded one.
     Additive/semver-minor; absent when enrichment is off. Documented in
     `docs/api-gateway.md`.
   - The **iteration cap** for the search loop is an implementation constant
     (small; it bounds cost, not capability — one or two searches answer a
     fact-dependent prompt).

### Open

None — all six settled 2026-08-01. Implementation may proceed.

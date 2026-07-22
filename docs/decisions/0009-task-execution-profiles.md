# ADR 0009 — Task execution profiles (config-driven grants + web_search as first-class enrichment)

**Date:** 2026-07-23
**Status:** Proposed (living draft — may be revised in place until Accepted)
**Related:**
- [`0003-agent-platform-architecture.md`](0003-agent-platform-architecture.md) — the `/v1/agent/task` tier + per-run `ScopedToolManager` grant enforcement this builds on
- [`0004-llm-gateway-features.md`](0004-llm-gateway-features.md) — the stateless `/v1/oneshot` tier that shares the "context-blind local LLM" problem
- `ppxai/engine/agent_spec.py::AgentSpec` — the existing per-run profile primitive (`{task, system, tools, provider, model, budget, network, read_paths}`), loaded from `sandbox.specs_dir`, merged `request > spec > default`
- `ppxai/server/routes/agent_v1.py::_with_task_default_allow` (L758-768) — the ONLY config-driven egress-baseline mechanism today; wired for `web_search` only
- `ppxai/engine/tools/network_policy.py` — the AC-2 egress superset; `get_weather` targets are a hardcoded literal (Item 52)
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

---

## Decision (PROPOSED)

Introduce **task execution profiles**: named, config-driven, reusable grants
that reuse the `AgentSpec` shape, with per-tool egress baselines and a
first-class `web_search` enrichment property.

### 1. Named profiles in config, reusing `AgentSpec`

```jsonc
"tools": { "agent": { "profiles": {
  "research": {
    "tools": ["web_search", "fetch_url", "read_file"],
    "enrichment": true,            // auto-grant web_search + its egress baseline
    "network": { "allow_outbound": ["api.open-meteo.com", "wttr.in"] },
    "budget": { "iterations": 20 }
  },
  "coding": {
    "tools": ["read_file", "search_files", "apply_patch", "write_file"],
    "enrichment": false            // closed-book by intent; no egress widening
  }
}}}
```

A run selects one by name — `--profile research` (client) / `"profile": "..."`
(wire) — resolved through the **same `spec_from_mapping` normalizer** the
`--spec` path already uses. Precedence extends the existing chain:
**request > spec > profile > `default_subagent` > built-in default**. Zero new
schema shape — a profile *is* an `AgentSpec` mapping in a config location.

### 2. Per-tool egress baselines (generalize `task_default_allow`)

`task_default_allow` becomes per-tool, not `web_search`-only:
`tools.<tool>.task_default_allow`. `_with_task_default_allow` reads the union
across the run's granted tools. This **subsumes Item 52**: `get_weather`'s
key-free hosts (Open-Meteo, https wttr.in) become
`tools.get_weather.task_default_allow` (or a profile's `network`), read by the
engine — one config-driven mechanism, working across local `/task`, coder, and
future tiers, exactly as `web_search` already does. (The contained
`http://wttr.in` scheme-poison removal still lands as part of the fix — an
always-denied scheme must never gate a tool.)

### 3. `enrichment: true` — opt-in, explicit, never a silent default

A profile with `enrichment: true` auto-grants `web_search` **and** merges its
egress baseline, so the context-blind-local-LLM case is solved *by construction*
for that profile. Crucially it is **per-profile and opt-in**: a locked-down
tenant profile sets `enrichment: false` and gets no egress widening. This keeps
the AC-2 confused-deputy protection intact — enrichment is a deliberate
declaration, not a global on-switch.

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

---

## Consequences

**If Option A is chosen:**
- Enables: named reusable grants; one config-driven egress mechanism for ALL
  tools (retires Item 52's weather-specific path); enrichment solved by
  construction for local LLMs; per-profile security posture.
- Requires: a `profiles` config block + `--profile` selector; per-tool
  `task_default_allow` read in `_with_task_default_allow`; precedence rules
  (request > spec > profile > default) documented + sentinel-tested; the
  `http://wttr.in` scheme-poison removal.

**Until decided (current state):**
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
- The `enrichment` opt-in and per-profile egress ceiling (open question 3) must
  compose UNDER a deployment policy hook, not above it: a profile may not widen
  egress beyond what an SRE-registered policy (A2) or a deployment ceiling
  permits. Profiles propose a grant; policy disposes.
- Per-tool `task_default_allow` emits the SAME `NETWORK_POLICY_ALLOWED/DENIED`
  events (C1) already committed — profiles change what's in the allowlist, not
  how enforcement or audit is surfaced. No new event type, no internal tap.

**Net:** ADR 0009 is a local-operator ergonomics + config-parity layer on the
grant side. It stays clear of the run wire shape (C3/C4), the audit event
contract (C1/A1), and the dynamic tier-classification hook (A2) that ppxai-sre
owns. If any future revision moves profiles toward *call-time* policy, that is a
conflict with A2 and must be re-litigated with the SRE boundary in view.

## Open questions for sign-off

1. **Precedence** — is `request > spec > profile > default_subagent` the right
   order? (Should an explicit `--profile` override a `--spec`, or compose under
   it?)
2. **`enrichment` scope** — does it grant only `web_search`, or also
   `fetch_url`/citations? Does it imply a provider preference (route to a
   search-native provider when available)?
3. **Egress trust / ceiling** — `task_default_allow` is operator-trusted config.
   A profile's `network` MUST be capped by a deployment-level ceiling (and,
   where present, an SRE-registered policy per A2) so a profile can't widen
   egress beyond what the deployment globally permits — profiles propose, policy
   disposes (see §"Consumer alignment"). What is the ceiling's shape — a
   `tools.agent.egress_ceiling` allowlist the profile union is intersected with?
4. **`/v1/oneshot`** — oneshot is stateless (no tools today). Does the
   enrichment idea extend to it (provider-native grounding toggle), or is this
   `/task`-only?

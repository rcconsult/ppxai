# ppxai-as-SDK: what's still needed to enable mutation tools in ppxai-sre long-running agents

**Date:** 2026-06-24
**Branch context:** `feature/v1.19.0` @ `690d8db4` (not yet released)
**Related:**
- [2026-06-24-ppxai-sre-integration-reconciliation.md](2026-06-24-ppxai-sre-integration-reconciliation.md) — the C/A gap reconciliation this builds on
- [docs/debt-inventory.md](../debt-inventory.md) Item 37 (agent-platform watchlist), 37p (C5 + `agent_n`), 37q (`state.json`)
- ppxai-sre `docs/PPXAI-INTEGRATION-V1.19.md` (asks **A1**, **A2**), `docs/DESIGN-outlook-agent.md` (the fit-test agent)
- [docs/decisions/0003-agent-platform-architecture.md](../decisions/0003-agent-platform-architecture.md)

## The architecture being designed for (the reframe)

**ppxai is the SDK/library for building ppxai-sre agents** — that was always the
intent. The shape:

- A ppxai-sre **long-running agent** (the `serve()` daemon — scheduler, mailbox
  poller, `AGENT.md` loader, `PolicyEngine`, `AuditLogger`) is the **outer loop**
  and lives in the **ppxai-sre pod**. The survey/poll loop is ppxai-sre's
  (`SREHeartbeat` / APScheduler — the integration doc deliberately keeps cron
  scheduling in ppxai-sre, not ppxai).
- When the outer loop decides an inbound event needs action, it **spawns a ppxai
  sub-agent run** — a bounded, sandboxed, tool-capable execution unit — and *that*
  run is where **mutation tools** (`reply`, `move`, `forward`, `delete`) execute,
  steered by the rendered `AGENT.md` and governed by ppxai's sandbox.
- The mutation tools are **ppxai-sre's own code**, registered into the ppxai run
  as `FunctionTool`s (via `ppxai_sre_core.tools_adapter`).

This is **embedded sub-agent runtime**, NOT remote `/task` HTTP hosting. The
current outlook-monitor MCP server is a **POC** to exercise the mailbox plumbing
(auth, sync, store, read tools) against real services — it is not the target
architecture for mutations.

**Why this framing matters:** it removes the heavy items from the critical path.
ppxai hosting outlook-monitor as a remote `/task` run would require MCP-client
tool integration, C5 services routing, a remote tool-callback protocol, and
tier-d OS isolation. The SDK/embedded model needs **none of those** — the run
executes in ppxai-sre's pod with ppxai-sre's creds and ppxai-sre's tool code.

## Verified: what already exists (build on these today)

Confirmed by reading the v1.19.0 tree, not docstrings:

| Capability | Status | Evidence |
|---|---|---|
| Custom tool registration (the mutation tools) | ✅ `FunctionTool(name, description, parameters, handler)` wraps arbitrary sync/async Python; `tools_adapter` already uses it | [`engine/tools/base.py:76-123`](../../ppxai/engine/tools/base.py) |
| AC-1 capability sandbox | ✅ `ScopedToolManager` — model sees only granted tools; off-grant `execute_tool` hard-denied | [`engine/agent_scoped_tools.py:46`](../../ppxai/engine/agent_scoped_tools.py) |
| AC-2 egress firewall | ✅ `NetworkPolicy` — deny-by-default, typed `NETWORK_POLICY_*` events | [`engine/tools/network_policy.py:266`](../../ppxai/engine/tools/network_policy.py) |
| Durable run registry + lifecycle | ✅ `AgentRunRegistry.start_run` / events.jsonl / cancel / budget | [`engine/agent_runs.py:349,451`](../../ppxai/engine/agent_runs.py) |
| AGENT.md steering into the run | ✅ `compose_agent_system_prompt(caller_system)` composes caller's rendered AGENT.md on top of the bounded-agent framing | [`server/routes/agent_v1.py:123`](../../ppxai/server/routes/agent_v1.py) |
| Spawn one sandboxed child from a run | ✅ `spawn_subagent` — child grant ⊆ parent, egress ⊆ parent, depth=1, consent-gated | [`engine/tools/agent_spawn.py`](../../ppxai/engine/tools/agent_spawn.py) |

**Conclusion: the sandbox is real and trial-verified, and the mutation tools can
already be registered.** The blockers are NOT "build the sandbox" — they are
"make the sandbox embeddable" and "make mutation-gating deterministic."

## The gap list (ranked)

### Gap 1 — `build_task_runner` is welded to the HTTP route, not the engine **[BLOCKING — structural]**

The function that *assembles* a sandboxed run (wires `ScopedToolManager` +
`NetworkPolicy` + budget/cancel + spawn + AGENT.md framing onto an `EngineClient`
and drives `chat()`) lives at [`server/routes/agent_v1.py:530`](../../ppxai/server/routes/agent_v1.py),
importing from `.oneshot` and `..state` (FastAPI route state). The *primitives*
(`ScopedToolManager`, `NetworkPolicy`) are engine-level and importable; the
*assembly* is not.

An SDK consumer embedding ppxai would have to import a server-route module
(dragging FastAPI/route state) or **re-implement the security wiring** — exactly
the thing ppxai should own and test once.

**What ppxai must provide:** lift the runner-assembly into the engine as a stable,
FastAPI-free API, e.g.

```python
# ppxai/engine/agent_runtime.py  (proposed)
def build_sandboxed_run(
    registry: AgentRunRegistry,
    *,
    provider: str, model: str,
    task: str,
    tools: list[BaseTool],              # incl. consumer FunctionTools (mutations)
    allow_outbound: list[str],
    system: str | None = None,          # rendered AGENT.md
    budget: dict | None = None,         # {iterations, time_s, tokens}
    allow_spawn: bool = False,
    policy_hook: PolicyHook | None = None,   # Gap 2
) -> Runner: ...
```

The HTTP route (`/v1/agent/task`) becomes a thin caller of this; ppxai-sre becomes
another caller. **Without this, "ppxai is the SDK for the sandboxed run" is not
true — only "ppxai is the SDK for the HTTP server" is.** Single most important
deliverable.

### Gap 2 — Deterministic pre-mutation policy hook (integration ask **A2**) **[BLOCKING — the actual write-tool unblocker]**

The outlook design's load-bearing safety property is *classification (LLM,
fallible) separated from action-gating (PolicyEngine, deterministic,
un-bypassable)*. For a mutation tool to be safe, ppxai-sre's `PolicyEngine` must
run **before** each mutating call and be able to allow / deny / escalate, keyed on
`tool + args` per the 3-tier model.

Today ppxai's per-tool gate is coarse: the AC-1 allowlist decides *whether a tool
exists in the grant*, not *whether this specific call is permitted*. Per-tool
consent is interactive-or-refuse (`spawn_consent` deny/auto). There is **no seam
for a registered, args-aware policy callable**. So today every granted mutation
tool is callable by the model once in the grant.

**What ppxai must provide:** A2 option (b) — a pre-tool-call policy callable on the
run / tool-manager:

```python
PolicyHook = Callable[[str, dict], Awaitable[PolicyVerdict]]
# PolicyVerdict ∈ {ALLOW, DENY(reason), ESCALATE(reason)}
```

ppxai-sre registers its `PolicyEngine` here. This is what makes `forward`
Tier-3-gated, `forward_external` denied without approval, `delete` blocked —
deterministically, with the LLM having no influence. **Promote A2 from v1.20.x to
the write-tools milestone.**

### Gap 3 — Policy/consent decision audit events (integration ask **A1**) **[needed for the acceptance-corpus gate]**

The outlook design gates write-tool *shipping* on a red-team corpus proving "no
unapproved Tier-2/3 verb ever fired," asserted via the JSONL audit trail. That
needs a stable event per policy decision.

**What ppxai must provide:** A1 — `EventType.CONSENT_DECISION` (or
`POLICY_DECISION`) `{tool, args_hash, decision, reason, source, run_id}`, emitted
from the same chokepoint as Gap 2's hook. Co-lands with A2. Without it,
`AuditLogger` taps internals and the corpus gate isn't cleanly testable.

### Gap 4 — Long-run ↔ bounded-run lifecycle boundary **[design, light code]**

"Survey the mailbox forever" is NOT one ppxai run. The survey loop stays in
ppxai-sre (`SREHeartbeat`/APScheduler); it spawns **one bounded ppxai sub-agent
run per message/decision**. So ppxai needs no new "infinite run" concept. Pin two
things:

- **Continuity/idempotency boundary:** the outer loop owns dedup (sqlite, outlook
  Phase 5); each sub-agent run is stateless-per-message. Context the run needs
  (thread history, prior decisions) is injected by the outer loop into
  `task`/`system` — it is the outer loop's job, not ppxai's. Document this seam.
- **`state.json` (debt 37q):** if ppxai-sre's heartbeat wants to reconstruct an
  interrupted run from disk, the Inspection Triplet must be complete. Close 37q.

### Gap 5 — `agent_n` nesting — only if a ppxai run *itself* fans out **[deferred, correctly]**

In this model the **outer loop** does any fan-out (it spawns N bounded ppxai
runs), so each is a top-level run and **flat siblings + `parent_run_id` suffice**.
Nested `agent_n` slots become load-bearing only if you want *a single ppxai run*
to fan out internally (N>1 inside one run) or to host C5 bound-service inspection
assets under a child slot. **Not on this critical path. Keep `agent_n`; do not
build nesting yet.** (See debt 37p for the C5/nesting entanglement when it does
return.)

## The premise, corrected

The stated blocker — *"ppxai does not offer a full secure sandbox"* (read as OS
isolation / tier-d) — is **not the binding constraint for this model.** The run
executes ppxai-sre's *own* mutation code in ppxai-sre's *own* pod. The threat is
**"trusted operator code + untrusted email prompt,"** which the **in-process**
AC-1/AC-2 sandbox + a deterministic A2 policy gate is precisely designed for.
tier-d OS-isolation matters when ppxai executes *untrusted* code — it does **not**
here.

So the real write-tool blocker resolves to:

> **an embeddable runner (Gap 1) + the deterministic policy hook (A2) + policy
> audit events (A1).** Not OS isolation. Not MCP integration. Not C5. Not nesting.

## Critical path (the answer)

**To enable ppxai-sre long-running agents to provide mutation tools via ppxai
sub-agents, ppxai needs three things on the critical path:**

1. **Lift `build_task_runner` into the engine as a FastAPI-free, embeddable SDK
   API** (Gap 1). *Structural blocker.*
2. **Ship the pre-mutation policy hook (A2)** (Gap 2). *The real write-tool
   unblocker.* Promote from v1.20.x.
3. **Ship policy-decision audit events (A1)** (Gap 3). Co-lands with #2.

**Supporting (not blocking the first write tool):** close `state.json` (debt
37q); document the long-loop-in-sre / bounded-run-in-ppxai boundary (Gap 4).

**Explicitly NOT needed for this model:** MCP-client integration, C5
agent-served-services routing, tier-d OS isolation, nested `agent_n`.

## Recommended next artifacts

- A concrete deliverable spec: the `build_sandboxed_run` engine API signature, the
  A2 `pre_execute` hook protocol, and the A1 event shape — as a `docs/decisions/`
  ADR amendment (extends ADR 0003) or a dedicated design doc.
- Update the integration doc's **A1 / A2** rows from "v1.20.x deferred (no
  consumer-side blocker)" to **"required for ppxai-sre mutation tools"** — the
  reframe makes them critical-path, not hygiene.
- File Gap 1 (embeddable runner) as a new debt item — it is the structural
  precondition the integration doc never named because the doc predates the
  SDK-embedding framing.

# Agents Framework — Design Discussion

**Status:** Not a decision yet. Captured for later review.
**Date:** 2026-04-24
**Branch at time of discussion:** `feature/v1.18.0`
**Related repos:** [ppxai](https://github.com/rcconsult/ppxai), [ppxai-sre](https://github.com/rcconsult/ppxai-sre)

---

## Origin of the idea

The conversation started from two separate observations:

1. **"I want sub-agents in ppxai or ppxai-sre — tool-like, spawned from a
   prompt, driven by an `AGENT.md`/`SOUL.md` file, solve a scoped task
   with input from the caller."**

2. **"Also, `ppxai-sre` should provide a framework for autonomous agents
   that run as daemons / k8s jobs / cron jobs — e.g. a Prometheus metric
   watcher that detects anomalies, fires Alertmanager alerts, and
   publishes an audit log."**

These are two distinct systems with shared DNA (agent definition format,
tool registry, result publishing) but fundamentally different runtimes.
Conflating them produces a chat-loop shape forced onto a cron job.

---

## Two systems, not one

### System 1 — Sub-agents (synchronous, interactive)
- Spawned by a parent agent or a user prompt
- One task → returns a result → dies
- Runs *inside* ppxai/ppxai-sre as a built-in tool
- Operator is in the loop

### System 2 — Autonomous agents (asynchronous, unattended)
- Spawned by a scheduler (daemon / cron / k8s CronJob)
- Lifecycle per tick: wake → observe → decide → act → publish → sleep
- Runs *outside* ppxai as its own process/pod
- No operator in the loop — side effects are the product

**Rule:** share the **definition format** (`AGENT.md`) and the **tool
registry**, keep the **runtime** separate. Don't unify prematurely.

---

## Worked example: Prometheus anomaly watcher

```
prometheus-anomaly-watcher/
├── AGENT.md                 # role, scope, schedule, tools, success criteria
├── runtime: k8s CronJob every 5min
└── lifecycle per tick:
    1. Pull:    query prometheus (PromQL queries from AGENT.md)
    2. Decide:  LLM call — "anomalous vs the last 7d baseline?"
    3. Act:     if anomaly → POST to Alertmanager, write audit log
    4. Publish: append to audit stream (Loki / Kafka / postgres)
    5. Exit:    0 on success, non-zero on infra error → k8s retries
```

The LLM is *only* the decision step. Everything else is plumbing.

---

## Survey of existing `ppxai-sre` (as of 2026-04-24)

Confirmed via gh API — `rcconsult/ppxai-sre`, default branch `master`.

### What's already there

| Piece | Status |
|---|---|
| `AGENT.md` definition format | ✅ Used in `agents/*/AGENT.md` — Identity, Role, Capabilities, Boundaries, Escalation Rules |
| Agent loader | ✅ `libs/core/src/ppxai_sre_core/bootstrap_loader.py` (`load_agent_bootstrap`, `find_agent_md`) |
| Entry-point discovery | ✅ `[project.entry-points."ppxai_sre.agents"]` + `discovery.py` |
| Tool registry bridge | ✅ `tools_adapter.py` with `register_mcp_server` (MCP-based) |
| Scheduler | ✅ `heartbeat.py` on APScheduler |
| Manager/Executor split | ✅ `manager.py` + `executor.py` |
| Policy / consent model | ✅ `PolicyEngine` + `ActionTier` (AUTONOMOUS / NOTIFY_AND_ACT / REQUIRE_APPROVAL) |
| Audit log | ✅ `AuditLogger` → JSONL |
| Event bus integration | ✅ `SREEventType`, `sre_event` hook into ppxai's bus |
| Packaging per agent | ✅ Dockerfile + PyInstaller spec per agent |
| SRE tool pack | ⚠️ K8s + Prometheus implemented; Grafana / Slack / PagerDuty / Vault / Pure stubs |

### Gaps vs. the autonomous-agent vision

1. **No k8s manifests / Helm chart** — Dockerfiles exist, nothing to deploy them
2. **No Alertmanager integration** — the motivating metric-watcher example isn't wired
3. **No `/metrics` endpoint on agents** — audit logs yes, Prometheus scrape target no
4. **No webhook/server runtime mode** — scheduler exists, no "listen for alertmanager → respond" shape
5. **Stalled since 2026-04-05** (19 days) — ppxai has moved to v1.18.0 while `ppxai-sre` still pins `ppxai>=1.17.3`

### Repo metadata

- 6 commits total, last push 2026-04-05
- 0 open issues / PRs
- uv workspace monorepo; Python >=3.11
- Core lib MIT; root repo no license declared
- Tests exist in `libs/core`, `agents/incident-responder`, `agents/cert-monitor`, `mcp-servers/kubernetes`, `mcp-servers/prometheus` — coverage unknown

---

## The real blocker — ppxai's API surface

The gap isn't in `ppxai-sre`. It's that **ppxai has no documented public
API**. `ppxai-sre` depends on `ppxai>=1.17.3` but every v1.17.x→v1.18.0
refactor risks breaking it. Three structural issues:

1. **No public API contract** — `ppxai-sre` reaches into `ppxai.engine`
   internals. Every engine refactor is a potential break.
2. **No tool registration entry point** — `tools_adapter` bridges MCP
   servers via import tricks, not a stable extension point.
3. **No `spawn_agent` primitive** — the interactive sub-agent pattern
   (System 1) doesn't exist in ppxai yet, so there's no way to validate
   the `AGENT.md` format in the human-in-the-loop case before running
   it unattended.

---

## Proposed ordering (not committed)

### ppxai-side work (in this repo, on feature/v1.18.0 or later)

| # | Item | Effort | Unblocks |
|---|---|:---:|---|
| A | Bump ppxai-sre's ppxai pin to 1.18.0; fix breakage | ~1d | Repo buildable again |
| B | Define and document ppxai's public API (`EngineClient`, tool registration, event bus). Mark everything else internal | ~3d | ppxai-sre stops depending on private internals |
| C | Add `ppxai.tools` entry-point group to the tool loader so external packages register without import tricks | ~2d | Clean ppxai-sre integration; enables third-party tool packs |
| D | Build `spawn_agent` built-in tool — loads `AGENT.md`, instantiates scoped `EngineClient`, returns structured result | ~5d | Interactive sub-agents; foundation for ppxai-sre Manager agent |

### ppxai-sre-side work (separate repo)

| # | Item | Effort |
|---|---|:---:|
| E | Alertmanager tool + Prometheus anomaly-watcher example agent | ~1 week |
| F | Helm chart + k8s CronJob manifests | ~3d |
| G | `/metrics` endpoint per agent (Prom scrape target) | ~2d |

### Rationale for this ordering

- **A** gets ppxai-sre unstuck immediately.
- **B** is load-bearing: without a documented public API, every ppxai
  release is a ppxai-sre breakage risk.
- **C** turns the ad-hoc tool bridge into a real extension point.
- **D** validates the `AGENT.md` format and sub-agent execution model in
  the interactive case, where bugs are cheap. No autonomous agents fire
  real alerts before the format has been proven in chat.
- **E/F/G** become a thin layer on top, not a parallel framework.

A + B + C together are what I earlier called "extract
`ppxai-agent-core`" — but you don't actually need a separate package.
You just need a stable API surface within `ppxai` itself.

---

## Design decisions still open

1. **`AGENT.md` vs `SOUL.md`** — ppxai-sre uses `AGENT.md`. Should
   ppxai's `spawn_agent` tool accept either, or only one? (Leaning:
   only `AGENT.md`, match ppxai-sre.)

2. **Frontmatter schema** — ppxai-sre's `AGENT.md` is free-form prose
   (Identity, Role, Capabilities, Boundaries, Escalation). Do we
   formalize YAML frontmatter for machine-readable fields (name,
   tools, model, schedule)? (Leaning: yes — prose for LLM context,
   frontmatter for loader/runtime.)

3. **Sub-agent discovery locations** — `./AGENTS/*.md`,
   `~/.ppxai/agents/*.md`, pyproject entry points. All three or just
   one? (Leaning: all three, layered; package entry points are how
   ppxai-sre exposes its agents to ppxai chat.)

4. **Tool allowlist per sub-agent** — explicit `tools:` list in
   frontmatter, unknown tools rejected at load. Inherit from parent
   or always explicit? (Leaning: always explicit, for auditability.)

5. **Model/provider per sub-agent** — per-agent `model:` in
   frontmatter, or resolve via the in-progress routing work
   (`RoutingRole`)? (Leaning: routing once it lands; per-agent model
   pin as escape hatch.)

6. **Consent flow for nested edits** — sub-agent file edits: inherit
   parent consent, or prompt fresh? (Leaning: inherit, with
   observable trail in UI.)

7. **Result contract** — `SubAgentResult(summary, artifacts, success,
   error)` or looser? (Leaning: strict; parent agents need to reason
   about success/failure.)

8. **Autonomous-agent safety primitives** — dry-run mode, rate
   limits, circuit breakers, RBAC scope. All in ppxai-sre, or some
   primitives (circuit breaker) in ppxai itself since interactive
   agents benefit too? (Leaning: circuit breaker in ppxai-sre's
   `PolicyEngine` — already partially there.)

9. **Observability contract** — what every agent must emit.
   Structured audit log ✅ (already in ppxai-sre). `/metrics`
   endpoint? OpenTelemetry traces? (Leaning: audit log + `/metrics`
   mandatory; OTel optional.)

10. **Should ppxai grow an autonomous-agent runtime, or stay
    interactive-only?** — Currently ppxai has no daemon/CronJob
    concept. Autonomous agents live entirely in ppxai-sre. Keep that
    split? (Leaning: yes — ppxai is an interactive app, ppxai-sre is
    the unattended-agent platform.)

---

## Things explicitly NOT decided yet

- Timeline — nothing is scheduled against v1.18.0 or any other release
- Whether to do this at all — user said "I need to think about it"
- Whether to extract `ppxai-agent-core` as a separate Python package or
  keep everything in `ppxai` with a documented public API
- MCP vs ppxai-native tool registration as the canonical extension
  mechanism (ppxai-sre uses MCP; ppxai uses native tools)

---

## Next step if pursued

Pick one of:

- **Minimum unblock:** just do item **A** (bump pin, fix breakage). ~1
  day, no new design.
- **Stabilize:** do **A + B**. Establishes public API contract before
  1.18.0 ships. ~4 days.
- **Full path:** do **A + B + C + D**, then hand off to ppxai-sre for
  E. ~2 weeks on ppxai side, then ppxai-sre work begins. Ships
  end-to-end in a v1.19 or v1.20 timeframe.

No commitment until this gets reviewed.

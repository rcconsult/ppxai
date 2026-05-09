# Research note: What ppxai-sre needs from ppxai (gap analysis for v1.19.x)

**Date:** 2026-05-10
**Status:** Research / exploratory — not a decision
**Triggered by:** question during the v1.18.4 release-prep session
about what ppxai needs to build to support [ppxai-sre](https://github.com/rcconsult/ppxai-sre)
(autonomous SRE agent platform — see [RELATED-PROJECTS.md](../../RELATED-PROJECTS.md))
**Author:** Captured from a research conversation; not vetted against
ppxai-sre's current branch.
**Not blocking:** ppxai-sre's outlook-monitor agent runs against
ppxai today via `POST /v1/oneshot`. The capabilities below are what
the **planned** ppxai-sre features (heartbeat scheduler,
manager-executor, multi-agent routing, policy engine) will need from
ppxai when they land.

This is a research note, not an architecture decision record. If/when
the v1.19.x agent-platform work commits to specific scope, the
ROADMAP entry referencing this note is the load-bearing artifact;
this note is the rationale.

## TL;DR

| Layer | Status | Where the work goes |
|---|---|---|
| **Stateless one-shot calls** (outlook-monitor's only need today) | ✅ Shipped (v1.18.3 `/v1/oneshot`) | Done |
| **Agent-platform primitives** (run identity, persistence, registry, sub-agents, budgets, run-id cancellation) | ❌ Missing | v1.19.x must-have — ADR 0003 Stage 2 |
| **`/v1/agent/run` endpoint** (promote agent platform to stable surface) | ❌ Missing | v1.19.x must-have — ADR 0004 trigger row "Tool calls requested for `/v1/oneshot`" |
| **Network policy enforcement** (per-run egress allowlist) | ❌ Missing | v1.19.x must-have (Section 6.5.1) — load-bearing for ppxai-sre's policy engine |
| **k8s session-manager security tests** (DEBT-INVENTORY Item 3) | ⚠️ Trigger-deferred today | v1.19.x must-have (Section 6.5.3) — promote from deferred since ppxai-sre IS the k8s context |
| **`/v1/tokens` per-agent identity** | ❌ Missing | v1.19.x should-have (urgent on agent #2) |
| **Credential broker** (k8s secrets / Vault / AWS Secrets Manager pluggable resolver) | ❌ Missing | v1.20.x defer (Section 6.5.2) — operational maturity, not Stage 2 blocker |
| **Native-provider `oneshot()` parity** (Gemini, Perplexity, OpenAI) | ❌ Partial | v1.20.x defer — only matters when SRE agent picks non-NIM reasoning |
| **Heartbeat scheduler** (planned ppxai-sre feature) | ⚠️ ppxai exposes `AGENT_BEAT`; scheduler belongs in ppxai-sre | Owned by ppxai-sre |
| **Policy engine** (planned ppxai-sre feature) | ⚠️ ppxai's per-tool consent is the right primitive; tiered SRE policy is a layer above | Owned by ppxai-sre, but **needs ppxai's network-policy primitive** to be load-bearing |
| **MCP servers for k8s/Prom/Grafana/PagerDuty** (planned ppxai-sre feature) | ⚠️ ppxai's MCP support is there; SRE-flavored servers belong in ppxai-sre | Owned by ppxai-sre |

**Net:** ppxai-sre needs ~70% of what it requires from ppxai to come
out of **ADR 0003 Stage 2** (the agent-platform plan), plus three
specific v1 gateway extensions (`/v1/agent/run`, `/v1/tokens`,
native-provider oneshot parity). Re-evaluation through the
ppxai-sre threat model (Section 6.5 below) adds three more items:
**network policy enforcement** (must-have v1.19.x — load-bearing for
ppxai-sre's planned policy engine), **promote DEBT-INVENTORY Item 3
to v1.19.x** (k8s session-manager IS ppxai-sre's deployment
substrate), and **credential broker** (defer to v1.20.x — operational
maturity, not Stage 2 blocker). Everything else stays in ppxai-sre's
repo, which is correct per RELATED-PROJECTS.md's separation rationale.

## 1. What ppxai-sre IS (per RELATED-PROJECTS.md and ADR 0004)

> **ppxai-sre extends ppxai with OpenClaw-inspired autonomous agent
> patterns specialized for Site Reliability Engineering. It enables
> proactive monitoring, incident response, and infrastructure
> management through AI agents with hard security boundaries.**

Key contrasts (from RELATED-PROJECTS.md):

| Aspect | ppxai | ppxai-sre |
|--------|-------|-----------|
| Purpose | Developer chat tool | Autonomous SRE operations |
| User | Interactive (developers) | Autonomous + interactive (SREs) |
| Execution | On-demand commands | Background heartbeat + on-demand |
| Scope | General purpose | Infrastructure operations |
| Security | User consent for tools | Tiered autonomous permissions |

Today ppxai-sre uses ppxai for **one** thing: the outlook-monitor
agent calls `POST /v1/oneshot` for stateless email classification
(referenced explicitly in ADR 0004). That's working; it's the
canonical proof that the v1 gateway tier is load-bearing.

The **planned** features (heartbeat scheduler, multi-agent routing,
manager-executor pattern, policy engine, MCP server bindings) need
ppxai-side work that hasn't shipped yet.

## 2. What's already shipped in ppxai

These are the capabilities ppxai-sre can already build against
without further ppxai work:

- **`POST /v1/oneshot`** (v1.18.3) — stateless single-turn LLM call.
  No session, no streaming, no history. Used by outlook-monitor.
- **Bearer-token auth** (`PPXAI_API_TOKEN`, v1.18.3) — opt-in,
  default off; preserves localhost UX while enabling cluster auth.
- **Provider abstraction** — `OpenAICompatibleProvider` covers
  `local`, `custom`, NIM, vLLM, Ollama, OpenRouter. The cases external
  agents target today (outlook-monitor's NIM deployment specifically).
- **Per-model `extra_body` config** — vendor knobs like NIM
  `chat_template_kwargs.enable_thinking` carry through `/v1/oneshot`
  transparently.
- **Throttle telemetry + cross-provider gap-fill** (v1.18.3) —
  persistent `provider_errors` counter, `_classify_throttle`
  classification across Perplexity / OpenAI-native / Gemini-native.
- **AGENT_BEAT / AGENT_RUN_START / AGENT_RUN_COMPLETE / AGENT_RUN_ERROR /
  AGENT_ZOMBIE event types** (v1.18.0) — the substrate ppxai-sre's
  heartbeat scheduler can subscribe to.
- **Tool execution framework** — `ToolEngineProtocol`, builtin tools.
  ppxai-sre inherits these if it imports ppxai as a library, which
  RELATED-PROJECTS.md says it does ("imports ppxai as dependency").
- **MCP integration** — the SRE-flavored servers (k8s, Prom, etc.)
  belong in ppxai-sre, but the consumption side is in ppxai already.

## 3. Documented near-term gaps (ADR 0004's "Triggers to revisit")

These are rows in ADR 0004's trigger table that will fire as
ppxai-sre grows. Each has a named likely change:

| Gap | When it bites ppxai-sre | Effort estimate |
|---|---|---|
| **Multiple agents need per-call attribution** (`/v1/tokens` registry) | Second SRE agent comes online + audit asks "which agent ran this prompt?" | ~500 LoC + storage migration policy + new stability commitment per ADR 0004 |
| **Streaming `/v1/oneshot`** | First SRE agent that wants partial-response feedback (e.g., live incident-triage commentary) | Either `?stream=1` mode or `/v1/oneshot/stream` SSE endpoint |
| **Tool calls on `/v1/oneshot`** | First SRE agent that wants the LLM to call tools (kubectl, prom queries) | Per ADR 0004: belongs at `/v1/agent/run` instead — Stage 2 of ADR 0003 |
| **Native Gemini / Perplexity / OpenAI in `/v1/oneshot`** | SRE agent that wants Claude / Gemini for reasoning instead of NIM | Each provider gets its own `oneshot()`; the 400 carve-out goes away |
| **Rate limiting** | Multi-tenant deployment; one runaway agent eats the quota | Per-token (after multi-token) OR per-IP middleware; separate ADR |
| **OIDC/JWT** | First enterprise deployment that needs SSO/audit-trail integration | New `/v1/auth/...` namespace; separate ADR |

These don't need to ship together. The **ordering** is roughly:
`/v1/agent/run` first (unblocks tool-calling SRE agents), then
`/v1/tokens` (unblocks multi-agent attribution), then native-provider
oneshot parity (unblocks non-NIM reasoning), then rate limiting and
OIDC (unblock specific deployment shapes).

## 4. The gap that matters most: ADR 0003 Stage 2 primitives

ADR 0003 ("Agent platform architecture") names seven things missing
from ppxai's current agent execution. **Every planned ppxai-sre
feature depends on at least one of these landing**:

| Primitive | Why ppxai-sre needs it | Where it'd land |
|---|---|---|
| **Run identity** (`run_id`) | Heartbeat scheduler needs to address "this specific agent run" — pause it, inspect it, kill it. Without `run_id`, every monitoring action is "interrupt the current request stream" which doesn't map to long-running background runs | `POST /v1/agent/run → {run_id}` |
| **Run persistence** (survive engine restart) | SRE agents are long-lived (cert-monitor: hourly; incident-responder: on-call). Engine restart shouldn't abort an in-flight run. The `runs/<run_id>/` artifact namespace from the OpenShell research note solves this | `~/.ppxai/runs/<run_id>/state.json` per the OpenShell research note |
| **Run registry** (`GET /v1/agent/runs`) | "Show me all active SRE agent runs" — basic operational visibility. Today there's no list endpoint | New v1 endpoint |
| **Parent/child relationship** (sub-agents) | The manager-executor pattern from RELATED-PROJECTS.md is literally "manager spawns executor sub-agents." No sub-agent primitive in ppxai today | `spawn_subagent` per the OpenShell research note |
| **Resource budgets** (token/time/network caps) | Autonomous agents without budgets are how cloud bills explode. SRE agents especially — they run unattended | `meta.json` per run carrying `{budget, started_at, status}` |
| **Cancellation by run-id** | Today `POST /interrupt` cancels the current request stream, not "this specific agent run." For heartbeat-driven agents this is the wrong shape | `POST /v1/agent/runs/<id>/cancel` |
| **Sub-agent tool** (`spawn_subagent`) | Manager-executor pattern needs it. No precedent in ppxai today | New tool, gated by consent contract |

The OpenShell research note ([2026-05-10-openshell-coordination-patterns.md](2026-05-10-openshell-coordination-patterns.md))
already maps four of these (run_id, persistence, parent/child, budgets)
onto a single artifact-namespace shape:

```
~/.ppxai/runs/<run_id>/
  meta.json              # {parent_run, status, started_at, budget, model}
  agent-1/
    output.md
    log.jsonl
    state.json
  agent-2/
    output.md
    log.jsonl
    state.json
  synthesis.md
```

This is the **load-bearing design** for ppxai-sre support. If ADR
0003 Stage 2 ships with this shape, ppxai-sre's heartbeat scheduler
can `ls runs/` to discover active runs, the manager-executor pattern
gets parent/child via slot ownership, and persistence comes free
because each slot is a checkpoint boundary.

## 5. What ppxai should NOT build for ppxai-sre

Per RELATED-PROJECTS.md's "Why Separate Repository?" rationale,
several SRE-specific features belong in ppxai-sre, not in ppxai:

### 5.1 Heartbeat scheduler

**Why not ppxai:** ppxai is a developer chat tool — interactive
on-demand commands. A heartbeat scheduler is a daemon-shaped feature
that adds operational complexity (cron-like scheduling, health checks,
restart handling) for zero benefit to ppxai's chat use case. Feature
creep.

**What ppxai DOES provide:** the substrate. `AGENT_BEAT` events
emit per tool iteration; `AGENT_ZOMBIE` fires when a run goes silent.
ppxai-sre subscribes via SSE or polls `GET /v1/agent/runs/<id>` and
makes scheduling decisions. Clean separation.

### 5.2 Policy engine (tiered autonomous permissions)

**Why not ppxai:** ppxai's per-tool consent is the right primitive
for the developer-chat use case — every dangerous action prompts.
The "tiered autonomous permissions" model from RELATED-PROJECTS.md
(agent X can run kubectl in namespace Y but not delete pods) is a
**different threat model**: the agent runs unattended, so the
human-in-the-loop assumption breaks. That needs durable policy,
not per-call consent.

**What ppxai DOES provide:** the consent contract
([CONSENT-CONTRACT.md](../CONSENT-CONTRACT.md)) is the security
boundary. ppxai-sre's policy engine wraps it: "for tool X, auto-grant
consent if (agent role + namespace + verb) match the policy; deny
loudly otherwise; log everything." The hook is at the consent-grant
moment.

### 5.3 SRE-flavored MCP servers (k8s, Prometheus, Grafana, PagerDuty)

**Why not ppxai:** these are domain-specific tools for SRE workflows.
Bundling them in ppxai bloats the install for every developer-chat
user who never touches k8s.

**What ppxai DOES provide:** MCP support already, generic. ppxai-sre
ships the SRE-flavored servers as a separate package; ppxai consumes
them via the same MCP protocol everyone else uses.

### 5.4 Per-agent containers (sandbox-per-agent isolation)

Already covered in the OpenShell research note (Section 4.1):
ppxai's single-user shape doesn't justify per-agent containers.
ppxai-sre's k8s deployment shape gets isolation from k8s itself
(via the session-manager from DEBT-INVENTORY.md Item 3, when those
tests land).

## 6. Recommendation: bundle for v1.19.x

A single v1.19.x deliverable, named explicitly to make clear it's
about agent-platform stabilization for external consumers (ppxai-sre
being the first):

> **v1.19.x — Agent platform Stage 2 + v1 gateway extensions for
> external agents (ppxai-sre)**

### Must-have for v1.19.x (blocks ppxai-sre planned features)

1. **ADR 0003 Stage 2 implementation** —
   `runs/<run_id>/agent-<n>/` namespace +
   `POST /v1/agent/run` +
   `GET /v1/agent/runs` +
   `GET /v1/agent/runs/<id>` +
   `POST /v1/agent/runs/<id>/cancel` +
   sub-agent primitive (`spawn_subagent` tool).
2. **Run persistence** — checkpoint to `state.json` per agent slot;
   recover on engine restart.
3. **Resource budgets** — `meta.json` carrying token / time /
   iteration caps; runtime enforcement at `chat_with_tools` boundary.
4. **Network policy enforcement primitive** (Section 6.5.1) —
   per-run egress allowlist + fail-closed default. Load-bearing for
   ppxai-sre's policy engine planned feature.
5. **k8s session-manager security tests promoted from
   DEBT-INVENTORY Item 3** (Section 6.5.3) — multi-tenant deployment
   isolation. Quick pass (~half day) is the minimum gate.

### Should-have for v1.19.x (operationally important)

6. **`/v1/tokens` multi-agent registry** — per-agent identity for
   workload attribution. Becomes urgent the moment ppxai-sre ships
   agent #2; safe to ship in v1.19.x even if agent #2 is still
   downstream.

### Deferred to v1.20.x (operational maturity, not blockers)

7. **Credential broker pattern** (Section 6.5.2) — pluggable
   resolver protocol so production keys live in k8s secrets / Vault /
   AWS Secrets Manager, not in `~/.ppxai/.env`. Important production
   hygiene for unattended SRE agents, but ppxai-sre v1 can ship with
   today's env-var model and the same threat surface as outlook-monitor.
8. **Native-provider `oneshot()` parity** — only matters when an SRE
   agent actively wants Claude / Gemini for reasoning. Today
   outlook-monitor uses NIM (covered by `OpenAICompatibleProvider`).
9. **Rate limiting** — only matters in multi-tenant deployments
   where one runaway agent could starve others. Tied to `/v1/tokens`
   landing first.
10. **OIDC/JWT** — only matters with SSO/audit integration request.
11. **Streaming `/v1/oneshot`** — only matters with live-feedback
    SRE agent that doesn't yet exist.

## 6.5. Re-evaluation through the ppxai-sre threat model: three more items from OpenShell

The earlier OpenShell research note ([2026-05-10-openshell-coordination-patterns.md](2026-05-10-openshell-coordination-patterns.md))
evaluated OpenShell's patterns against **ppxai's single-user shape**
and rejected most of them. Re-evaluating against **ppxai-sre's
multi-tenant cluster shape with autonomous unattended agents**, three
patterns I dismissed actually become load-bearing.

### 6.5.1 Network policy enforcement on agent runs

**OpenShell pattern:** `policy.template.yaml` per sandbox declares
allowed hosts/paths/methods. Network gateway enforces.

**Why ppxai-sre needs it (that I missed earlier):** an
incident-responder agent shouldn't be able to call
`random-host.example.com`; a cert-monitor shouldn't be able to reach
the API server; an outlook-monitor shouldn't be able to make
arbitrary outbound calls. RELATED-PROJECTS.md's "policy engine —
hard security boundaries (not prompt-based)" planned feature is
exactly this. **Per-tool consent (today's primitive) is the wrong
shape for unattended agents** — there's no human to approve.

**What ppxai needs to add:**

```yaml
# Per-run network policy carried in meta.json
network:
  allow:
    - host: api.openai.com
    - host: prometheus.monitoring.svc.cluster.local
    - host: github.com
      paths: [/repos/our-org/our-app/*]
  deny_default: true
```

New middleware in `ppxai/engine/tools/network_policy.py` that hooks
the outbound-HTTP path of network-touching tools. `network_policy`
field in `meta.json` (per the artifact-namespace shape from the
OpenShell research note).

**Effort:** nontrivial — needs k8s service-discovery shape, glob
matching on paths, fail-closed default behavior, audit logging on
deny. ~3-5 days. **Belongs in v1.19.x** because the policy engine is
listed as a planned ppxai-sre feature and this is the load-bearing
ppxai-side primitive.

### 6.5.2 Credential resolution at the gateway boundary

**OpenShell pattern:** sandboxes start with placeholder credentials;
real ones injected at the network gateway based on policy. The
agent process never sees the raw key.

**Why ppxai-sre needs it (that I missed earlier):** SRE agents run
unattended in clusters. If they're compromised (prompt injection,
supply chain attack), an exfil of their environment shouldn't yield
production API keys. The credential broker pattern is the standard
production answer.

**What ppxai needs to add:**

- ppxai-server reads provider API keys from a credential broker
  (k8s secrets, HashiCorp Vault, AWS Secrets Manager) **per-request**,
  not from `~/.ppxai/.env` at startup.
- Pluggable resolver protocol in `ppxai/server/credentials.py`:
  - `EnvVarResolver` (today's behavior — keep for ppxai single-user)
  - `KubernetesSecretResolver` (read from mounted secret at request time)
  - `VaultResolver` (HashiCorp Vault HTTP API)
  - `AwsSecretsManagerResolver`
- The agent sees a request-scoped placeholder; gateway substitutes
  the real key when forwarding to the LLM provider.

**Effort:** sizeable — pluggable resolver + per-request resolution
adds latency + new test surface for each resolver. ~5-7 days.

**Timing:** this is **operational maturity, not a Stage 2 blocker**.
ppxai-sre can ship its v1 with env-var credentials and the same
threat model as today's outlook-monitor. Defer to **v1.20.x** unless
the first ppxai-sre cluster deployment surfaces a security review
that demands it sooner.

### 6.5.3 Promote DEBT-INVENTORY Item 3 (k8s session-manager) from deferred to v1.19.x

**Item 3 today:** k8s session-manager security tests are
trigger-deferred ("when k8s context environment so tests can be
exercised end-to-end"). The session-manager IS the multi-tenant
isolation boundary for the deploy shape.

**Why ppxai-sre changes the calculus:** ppxai-sre IS the k8s
context. Its planned features (heartbeat scheduler running
unattended; multi-agent routing across SRE specializations) imply
multi-tenant deployment. The session-manager stops being "nice to
have when someone deploys" and becomes "load-bearing for ppxai-sre's
deployment shape."

**What changes:** Item 3 promotes from "trigger-deferred" to "v1.19.x
parallel deliverable." The implementation work itself doesn't change
— `feat/k8s-session-manager-tests` branch + 30-50 tests around the 8
named functions in `deploy/images/session-manager/main.py` per the
DEBT-INVENTORY-v1.18.2.md original entry. What changes is its
**priority** and the **release-readiness gate**: v1.19.x can't claim
"ready for ppxai-sre" without these tests passing.

**Effort:** half-day quick pass (10 tests around `_hash_password`,
`authenticate`, naming validation), full-day full pass (30-50 tests
with mocked `kubernetes.client`). Per DEBT-INVENTORY Item 3's
existing estimate. Add half-day for end-to-end k8s integration test
in CI.

### 6.5.4 What I correctly rejected (still rejected)

- **Bash + external CLI agent orchestration** — ppxai-sre also runs
  in-process per RELATED-PROJECTS.md ("imports ppxai as dependency"),
  not shell-spawned. The bash + Codex pattern doesn't apply.
- **`gh + jq` host orchestration** — ppxai-server is the orchestrator;
  GitHub-as-substrate is OpenShell's choice for cross-tenant durable
  storage, but ppxai's local filesystem + SessionManager (or per-run
  k8s PVC for the cluster shape) is faster and avoids the GitHub
  dependency.
- **Per-agent containers in ppxai itself** — k8s already provides
  per-tenant container isolation via the session-manager. Adding
  ppxai-internal containers would double-wrap the isolation for zero
  benefit.

## 7. Open questions

These are not blocking the recommendation, but worth flagging for
when v1.19.x planning starts:

- **Should `/v1/agent/run` accept tools?** ADR 0004's trigger row says
  "Tool calls requested for `/v1/oneshot` → probably belongs at
  `/v1/agent/run` instead." Confirming "yes, tools are a v1 concept
  on `/v1/agent/run`" is a real commitment because it pins the wire
  shape. Worth pinning in the Stage 2 ADR.
- **Where does `spawn_subagent` enforce policy?** If ppxai owns the
  primitive but ppxai-sre owns the policy engine, there's a
  consent-grant hook to design. The OpenShell research note's
  artifact-namespace pattern doesn't address this.
- **Multi-tenant deployment boundary.** RELATED-PROJECTS.md says
  ppxai-sre has its own release cadence and imports ppxai as a
  dependency. If ppxai-sre runs in k8s and ppxai-server is the
  gateway, the deploy/session-manager from Item 3 in
  [DEBT-INVENTORY.md](../DEBT-INVENTORY.md) is on the critical
  path. Worth confirming whose roadmap that work is on.
- **Manager-executor wire shape.** Manager spawns executor; how does
  the executor stream results back? Polling vs. SSE vs. push to
  parent's slot. Worth pinning in Stage 2.

## What's NOT in scope for this note

- Detailed wire shape for `/v1/agent/run` (that's the Stage 2 ADR's job)
- ppxai-sre's internal architecture (that's ppxai-sre's repo)
- Cross-machine / distributed agent coordination (one-machine first;
  cluster shape is downstream of multi-tenant work in DEBT-INVENTORY Item 3)
- ppxai-sre release tooling (separate concern)

If those become real requirements, write follow-up notes; don't
retrofit them into this one.

## Related documents

- [RELATED-PROJECTS.md](../../RELATED-PROJECTS.md) — ppxai-sre overview and separation rationale
- [docs/decisions/0003-agent-platform-architecture.md](../decisions/0003-agent-platform-architecture.md) — agent platform ADR (the load-bearing one for v1.19.x)
- [docs/decisions/0004-llm-gateway-features.md](../decisions/0004-llm-gateway-features.md) — v1 gateway tier; "Triggers to revisit" table is the future-work checklist
- [docs/API-GATEWAY.md](../API-GATEWAY.md) — v1 gateway public spec
- [docs/CONSENT-CONTRACT.md](../CONSENT-CONTRACT.md) — current security boundary (per-tool, the hook ppxai-sre's policy engine wraps)
- [docs/research/2026-04-29-python-vs-go-for-agents.md](2026-04-29-python-vs-go-for-agents.md) — language-choice research note for autonomous agents (sibling)
- [docs/research/2026-05-10-openshell-coordination-patterns.md](2026-05-10-openshell-coordination-patterns.md) — coordination-pattern research note (the load-bearing design for ADR 0003 Stage 2)
- [DEBT-INVENTORY.md](../DEBT-INVENTORY.md) Item 3 — k8s session-manager (multi-tenant deploy shape)
- [ROADMAP.md](../../ROADMAP.md) — v1.19.x agent-platform entry references this note
- ppxai-sre repository: https://github.com/rcconsult/ppxai-sre (private)

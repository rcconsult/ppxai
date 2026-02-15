# ppxai + OpenClaw Approach: Autonomous SRE Agents

## Analysis Date: February 15, 2026

## Executive Summary

This document analyzes how ppxai can adopt OpenClaw's autonomous agent patterns to build specialized SRE (Site Reliability Engineering) agents. ppxai already has ~80% of the required foundation. SRE is arguably a better domain fit than OpenClaw's general-purpose personal assistant model because actions are more bounded, telemetry is structured, and enterprise environments enforce natural guardrails.

---

## OpenClaw Overview

OpenClaw (formerly Clawdbot/Moltbot) is an open-source autonomous AI agent framework by Peter Steinberger. Core pattern:

- **SOUL.md** — agent identity and persona definition
- **Skills** — modular SKILL.md capability packs
- **Heartbeat loop** — proactive background execution without human input
- **Tool orchestration** — shell, browser, file, API access
- **Chat interface** — Telegram, Slack, WhatsApp, Discord as primary UI
- **Persistent memory** — local-first Markdown/JSONL storage
- **Model-agnostic** — Claude, GPT, Gemini, Ollama

### Key Stats (Feb 2026)
- 175,000+ GitHub stars in under two weeks
- MIT licensed, fully self-hosted
- Gartner recognized AI SRE tooling as emerging category (Jan 2026)
- Gartner predicts 85% enterprise AI SRE adoption by 2029 (from <5% in 2025)

### OpenClaw Architecture Components
1. **Channel Adapter** — standardizes inputs from different platforms
2. **Gateway Server** — session coordinator and message routing
3. **Lane Queue** — serial execution by default (prevents race conditions)
4. **Agent Runner** — model selection, API key rotation, prompt assembly
5. **Agentic Loop** — tool call → execute → backfill → repeat until resolution

### OpenClaw Security Lessons (What Went Wrong)
- Security model was prompt instructions, not architectural boundaries
- Prompt injection overrides "guardrails" that are just system prompt text
- Top-downloaded community skill was malware (Cisco found 26% of skills had vulnerabilities)
- 230+ malicious skills uploaded to ClawHub in first week of February 2026
- OpenClaw maintainer warned: "if you can't understand how to run a command line, this is far too dangerous"

---

## ppxai Current State — Existing Foundation

ppxai already has the majority of building blocks needed:

| OpenClaw Concept | ppxai Equivalent | Status |
|---|---|---|
| SOUL.md (agent persona) | AGENTS.md context injection | ✅ Implemented |
| Skills (SKILL.md) | Tool system + MCP servers | ✅ Implemented |
| Agent mode | Agent mode with shell execution + consent | ✅ Implemented |
| Chat interface | TUI, VSCode Extension, Web App | ✅ Multi-client (better than OpenClaw) |
| Shell execution | `execute_shell_command` tool | ✅ Implemented |
| Context injection | @file, @git, @tree injection | ✅ Implemented |
| Per-provider config | Per-provider system prompts + prompt modes | ✅ Implemented |
| Session management | Session isolation across clients | ✅ Implemented |
| LLM backbone | Multi-provider (OpenAI-compatible, vLLM) | ✅ Model-agnostic |
| FastAPI server | Persistent backend with idle management | ✅ Running |
| Heartbeat loop | ❌ Missing | 🔴 Core gap |
| Multi-agent routing | ❌ Single AGENTS.md | 🔴 Needs work |
| Action tier enforcement | Consent system (interactive only) | 🟡 Needs autonomous mode |
| Outbound notifications | ❌ Server waits for clients | 🔴 Missing |

### ppxai Advantages Over OpenClaw
1. **Multi-client architecture** — TUI + VSCode + Web App already built (OpenClaw relies on chat apps only)
2. **Own GPU infrastructure** — vLLM on H100s means near-zero cost for routine heartbeat checks
3. **Enterprise context** — existing Kubernetes, Prometheus, Grafana, HashiCorp Vault integrations
4. **Consent system** — already has safety controls for shell execution
5. **Python ecosystem** — FastAPI + APScheduler = natural heartbeat implementation

---

## SRE Domain Fit — Why This Works Better Than General-Purpose

| Factor | General Assistant (OpenClaw) | SRE Agent (ppxai) |
|---|---|---|
| Action scope | Unlimited (email, calendar, files, web) | Bounded (infrastructure operations) |
| Signal type | Unstructured (email, chat) | Structured telemetry (metrics, logs, traces) |
| Safety model | Broad permissions needed | Least-privilege natural (read-only by default) |
| Guardrails | Hard to define (what's "safe" for personal tasks?) | Well-defined (prod vs non-prod, RBAC) |
| Audit requirements | Optional | Mandatory (enterprise compliance) |
| Skill supply chain | Community marketplace (malware risk) | Internal only (controlled) |
| Model costs | Every action uses frontier API | Routine checks on local models, frontier for reasoning |

---

## Proposed Architecture: ppxai-sre

### 1. Agent Definitions — Multi-Agent AGENTS.md

Extend current single AGENTS.md to support multiple specialized agents:

```
~/.ppxai/agents/
├── incident-responder/
│   ├── AGENT.md          # Identity, capabilities, boundaries
│   ├── TOOLS.md          # Available tools + notes
│   ├── RUNBOOKS.md       # Embedded runbook knowledge
│   └── sessions/
├── capacity-planner/
│   ├── AGENT.md
│   └── ...
├── deployment-validator/
│   ├── AGENT.md
│   └── ...
├── log-analyst/
│   ├── AGENT.md
│   └── ...
├── cert-monitor/
│   ├── AGENT.md
│   └── ...
└── cost-optimizer/
    ├── AGENT.md
    └── ...
```

#### Example: Incident Responder AGENT.md

```markdown
# Incident Responder Agent

## Role
You are an SRE incident response agent for Tradition Technology.
You monitor alerts, perform initial triage, and escalate when needed.

## Tools Available
- kubectl (read-only in prod, read-write in dev/staging)
- promql queries via Prometheus API
- Grafana dashboard snapshots
- PagerDuty API for escalation
- Slack webhook for notifications

## Action Tiers
### Tier 1 - Autonomous (no approval needed)
- Query metrics and logs
- Correlate alerts with recent deployments
- Generate incident summary
- Post status to #incidents Slack channel

### Tier 2 - Notify and act (inform human, proceed)
- Restart crashed pods in staging
- Scale replicas within approved bounds (min: 2, max: 10)
- Trigger pre-approved runbook actions

### Tier 3 - Require approval (ask before acting)
- Any production mutation
- DNS/network changes
- Rollback deployments
- Scaling beyond approved bounds

## Escalation
- Page on-call if severity > P2
- Require human approval for any production mutation
```

### 2. Heartbeat Scheduler — The Key Missing Piece

Background scheduler integrated into ppxai's FastAPI server:

```python
# ppxai/sre/heartbeat.py
class SREHeartbeat:
    """
    OpenClaw-style heartbeat loop adapted for SRE.
    Runs agents proactively on schedules.
    """
    schedules = {
        "cluster-health": {
            "agent": "incident-responder",
            "cron": "*/5 * * * *",        # every 5 min
            "prompt": "Check cluster health: pod restarts, node conditions, resource pressure",
            "model": "local/qwen-2.5-7b",  # cheap model for routine checks
            "on_finding": "slack:#platform-ops",
        },
        "cert-expiry": {
            "agent": "cert-monitor",
            "cron": "0 8 * * *",           # daily 8am
            "prompt": "Check all TLS certificates expiring within 30 days",
            "model": "local/qwen-2.5-7b",
            "on_finding": "slack:#security",
        },
        "capacity-forecast": {
            "agent": "capacity-planner",
            "cron": "0 0 * * 1",           # weekly Monday
            "prompt": "Run weekly capacity forecast for GPU and storage clusters",
            "model": "anthropic/claude-sonnet",  # needs reasoning power
            "on_finding": "slack:#infrastructure",
        },
        "log-anomalies": {
            "agent": "log-analyst",
            "cron": "*/15 * * * *",        # every 15 min
            "prompt": "Scan for anomalous patterns in last 15min of logs",
            "model": "local/qwen-2.5-7b",
            "on_finding": "slack:#incidents",
        },
        "cost-anomaly": {
            "agent": "cost-optimizer",
            "cron": "0 9 * * *",           # daily 9am
            "prompt": "Check for unusual resource consumption vs 7-day baseline",
            "model": "local/qwen-2.5-7b",
            "on_finding": "slack:#finops",
        },
    }
```

#### Model Routing Strategy

Leverages existing vLLM/H100 infrastructure:

| Task Type | Model | Cost | Reasoning |
|---|---|---|---|
| Routine health checks | Local Qwen 2.5 7B via vLLM | ~$0 | High-volume, simple pattern matching |
| Log anomaly detection | Local Qwen 2.5 7B via vLLM | ~$0 | Fast, structured output |
| Root cause analysis | Claude Sonnet or local 70B | $$ | Needs multi-step reasoning |
| Capacity forecasting | Claude Sonnet | $$ | Complex trend analysis |
| Incident postmortem | Claude Opus | $$$ | Deep reasoning, report writing |

### 3. Manager-Executor Pattern with Hard Boundaries

**Critical lesson from OpenClaw**: security must be architectural, not prompt-based.

```
┌──────────────────────────────────────────┐
│            ppxai SRE Gateway             │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  Manager Agent (reasoning only)    │  │
│  │  - Analyzes alerts/metrics         │  │
│  │  - Plans remediation               │  │
│  │  - CANNOT execute commands         │  │
│  └──────────────┬─────────────────────┘  │
│                 │ (structured task)       │
│  ┌──────────────▼─────────────────────┐  │
│  │  Policy Engine (code, not prompts) │  │
│  │  - Action tier enforcement         │  │
│  │  - kubectl verb allowlists         │  │
│  │  - Namespace restrictions          │  │
│  │  - Rate limiting                   │  │
│  │  - Audit logging                   │  │
│  └──────────────┬─────────────────────┘  │
│                 │ (approved action)       │
│  ┌──────────────▼─────────────────────┐  │
│  │  Executor (sandboxed)              │  │
│  │  - Runs in restricted container    │  │
│  │  - Only approved tools available   │  │
│  │  - Network access scoped           │  │
│  │  - All actions logged to JSONL     │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

Policy engine is **Python/OPA code** — not prompt instructions. If the manager says "delete the production database," the policy engine blocks it structurally. No prompt injection can bypass compiled code.

### 4. MCP Servers as SRE Skill Packs

Leverages existing ppxai MCP support:

```json
{
  "mcp_servers": {
    "kubernetes": {
      "command": "ppxai-mcp-k8s",
      "args": ["--kubeconfig", "/etc/k8s/config", "--namespace-allow", "dev,staging"],
      "description": "Kubernetes cluster operations (scoped)"
    },
    "prometheus": {
      "command": "ppxai-mcp-prometheus",
      "args": ["--url", "http://prometheus:9090"],
      "description": "PromQL queries and alert status"
    },
    "grafana": {
      "command": "ppxai-mcp-grafana",
      "description": "Dashboard snapshots and annotations"
    },
    "pagerduty": {
      "command": "ppxai-mcp-pagerduty",
      "description": "Incident creation and escalation"
    },
    "vault": {
      "command": "ppxai-mcp-vault",
      "args": ["--read-only"],
      "description": "Secret rotation status checks"
    },
    "pure-storage": {
      "command": "ppxai-mcp-pure",
      "description": "Storage array health and capacity"
    }
  }
}
```

### 5. Multi-Client SRE Reporting

ppxai's existing multi-client architecture maps naturally to SRE workflows:

| Client | SRE Use Case |
|---|---|
| **TUI** | Real-time incident investigation, interactive kubectl through agent, on-call primary interface |
| **VSCode Extension** | Side-by-side with code during post-incident reviews, deployment validation while writing Helm charts |
| **Web App** | SRE control plane dashboard: agent activity, incident timelines, heartbeat status |
| **Slack/Telegram** (new) | OpenClaw-style push notifications from heartbeat findings |

---

## Practical SRE Workflow Examples

### Proactive (heartbeat-driven)

```
[08:01] 🔍 cert-monitor: TLS certificate for api.tradition.com expires in 12 days.
        Tier 2 action: Created renewal request in HashiCorp Vault.
        Notify: #platform-ops

[08:15] 📊 capacity-planner: GPU cluster utilization trending 87% over 7 days.
        At current growth rate, will exceed 95% by March 3.
        Recommendation: Provision 2 additional H100 nodes.
        [Approve] [Dismiss] [Details]

[08:30] ⚠️ cost-optimizer: vLLM inference costs 340% above 7-day baseline.
        Root cause: Model "llama-3.3-70b" loaded on 4 MIG partitions instead of 2.
        Tier 1 action: Logged anomaly report.
        Recommendation: Rebalance MIG allocation.
```

### Reactive (incident response)

```
[03:22] 🚨 Alert: Pod CrashLoopBackOff in prod/inference-api (5 restarts in 10min)

[03:22] 🤖 incident-responder analyzing...
        - Recent deployment: inference-api v2.4.1 deployed 47 min ago
        - Memory OOM detected in container logs
        - Previous version v2.4.0 was stable for 14 days
        - Correlation: New model loading code increased memory footprint

        Recommended action (Tier 3 - needs approval):
        Rollback inference-api to v2.4.0
        [Approve Rollback] [Investigate More] [Escalate to On-Call]
```

### Interactive (human-initiated via TUI)

```
you> why is the vllm service slow today?

agent> Investigating vLLM performance...

        Queried Prometheus: vllm_request_latency_p99 = 4.2s (normal: 1.1s)
        Checked GPU utilization: 2/4 MIG partitions at 98%
        Found: Batch job "quarterly-eval" consuming 2 MIG slices since 06:00
        
        The quarterly model evaluation job is competing for GPU resources.
        Options:
        1. Reduce eval job priority (I can do this - Tier 2)
        2. Reschedule eval to off-hours (needs your approval)
        3. Temporarily allocate additional MIG partitions
```

---

## Gap Analysis — What Needs Building

### 🔴 Critical Gaps (4 features)

#### 1. Heartbeat Scheduler
- **What**: Background task loop that runs agents on cron schedules
- **Approach**: APScheduler or asyncio tasks in FastAPI server
- **Effort**: ~1 week
- **Impact**: Unlocks entire "proactive agent" pattern

#### 2. Multi-Agent Routing
- **What**: Multiple AGENT.md files with isolated contexts, tool sets, and sessions
- **Approach**: Agent registry in server, heartbeat invokes specific agents
- **Effort**: ~1-2 weeks (extend existing session isolation)
- **Impact**: Specialized agents with scoped permissions

#### 3. Autonomous Action Tier Enforcement
- **What**: Policy engine that pre-classifies actions without human-in-the-loop
- **Approach**: Python policy engine (or OPA integration) that sits between manager and executor
- **Effort**: ~1-2 weeks
- **Impact**: Safe 3 AM autonomous operation

#### 4. Outbound Notifications
- **What**: Push heartbeat findings to Slack/Telegram/PagerDuty
- **Approach**: Webhook handlers in FastAPI, configurable per-agent notification targets
- **Effort**: ~3-5 days
- **Impact**: Agent reaches humans where they are

### 🟡 Enhancements

- **JSONL audit trail** for all autonomous agent actions
- **Runbook ingestion** — convert existing markdown runbooks to agent knowledge
- **Multi-model routing** — auto-select cheap local vs expensive frontier per task
- **Agent activity dashboard** in web app
- **Feedback loop** — human corrections improve agent behavior over time

---

## Implementation Roadmap

### Phase 1 — Foundation (2-3 weeks)
- [ ] Add heartbeat scheduler to FastAPI backend (APScheduler)
- [ ] Create multi-agent AGENT.md format and agent loader
- [ ] Build 2-3 SRE MCP servers (Kubernetes read-only, Prometheus, Slack notifications)
- [ ] Simple policy engine with action tier enforcement
- [ ] JSONL audit logging for all agent actions

### Phase 2 — Intelligence (3-4 weeks)
- [ ] Manager-executor split with sandboxed execution
- [ ] Runbook ingestion (markdown → agent knowledge)
- [ ] Multi-model routing (local cheap for heartbeats, frontier for reasoning)
- [ ] Outbound notifications (Slack, PagerDuty webhooks)
- [ ] Agent activity dashboard in web app

### Phase 3 — Collaboration (4-6 weeks)
- [ ] Multi-agent coordination (incident-responder triggers capacity-planner)
- [ ] Team features in web app (shared incident timelines)
- [ ] Integration with existing ITSM/ticketing
- [ ] Feedback loop: human corrections improve agent behavior
- [ ] Incident postmortem generation

---

## Key Design Decisions — Divergence from OpenClaw

| Decision | OpenClaw Approach | ppxai-sre Approach | Rationale |
|---|---|---|---|
| Security model | Prompt-based guardrails | Hard architectural boundaries (OPA/code) | OpenClaw got compromised; prompt injection bypasses prompt-only security |
| Agent scope | General-purpose "do everything" | Focused SRE domain | Narrower scope = safer + more reliable |
| Model hosting | External API (Claude, GPT) | Local vLLM for routine + frontier API for reasoning | Cost optimization with existing H100 infrastructure |
| Audit trail | JSONL transcripts (optional) | JSONL + SIEM integration (mandatory) | Enterprise compliance requirement |
| Skill supply chain | Community marketplace (ClawHub) | Internal skills only | Avoids malware risk (26% of ClawHub skills had vulnerabilities) |
| Deployment | Local developer machine | Enterprise server/k8s deployment | Production SRE workload, not personal assistant |
| Notification | Chat apps (Telegram, WhatsApp) | Slack + PagerDuty + multi-client UI | Enterprise communication patterns |

---

## Industry Context (Feb 2026)

### Agentic SRE Landscape
- **Azure SRE Agent** — Microsoft's managed AI SRE service (announced Build 2025)
- **Komodor Klaudia** — Named in Gartner's Jan 2026 Market Guide for AI SRE
- **PagerDuty Agentic SRE** — Autonomous incident triage and diagnostics
- **Rootly** — AI-native incident lifecycle platform
- **Ciroos** — AI SRE as abstraction layer for enterprise operations

### Key Predictions
- Gartner: 85% enterprises will use AI SRE tooling by 2029
- AI SRE becoming "abstraction layer" across observability, ticketing, CI/CD, infrastructure
- Shift from "AI as tool" to "AI as team member" in SRE
- New roles emerging: reliability architects supervising AI output

### ppxai Competitive Advantage
Building on open-source ppxai with internal model hosting gives Tradition Technology:
1. **No vendor lock-in** — own the platform, choose the models
2. **Data sovereignty** — telemetry and agent actions stay internal
3. **Cost control** — routine checks on local H100s, pay API only for complex reasoning
4. **Customization** — agents tuned to specific infrastructure and runbooks
5. **Integration depth** — direct access to internal systems (no SaaS intermediary)

---

## References

- OpenClaw GitHub: https://github.com/openclaw/openclaw
- OpenClaw Architecture: https://docs.openclaw.ai/concepts/agent
- Gartner Market Guide for AI SRE (Jan 2026)
- Cisco AI Security Research on OpenClaw skill vulnerabilities
- Azure SRE Agent: https://azure.microsoft.com/en-us/products/sre-agent/
- "Agentic SRE: Self-Healing Infrastructure" — Unite.AI (Feb 2026)
- ppxai GitHub: https://github.com/rcconsult/ppxai

---

*Document created: February 15, 2026*
*Context: Analysis of OpenClaw autonomous agent patterns applied to ppxai for SRE specialization*
*Key conclusion: ppxai has ~80% of the foundation; 4 critical features needed to reach autonomous SRE agent capability*

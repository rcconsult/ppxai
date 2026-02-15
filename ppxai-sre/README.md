# ppxai-sre

Autonomous SRE agent platform built on ppxai foundation.

**Status:** 📋 Research/Planning Phase (post-v1.16.0)

## Overview

ppxai-sre extends ppxai with OpenClaw-inspired autonomous agent patterns specialized for Site Reliability Engineering. It enables proactive monitoring, incident response, and infrastructure management through AI agents with hard security boundaries.

## Key Features (Planned)

- 🤖 **Autonomous Agents** - Background heartbeat loop for proactive monitoring
- 🔒 **Hard Security Boundaries** - Policy engine enforcement (not prompt-based)
- 📊 **Multi-Agent Routing** - Specialized agents with scoped permissions
- 🔔 **Outbound Notifications** - Slack, PagerDuty, webhook integrations
- 🏗️ **Manager-Executor Pattern** - Separation of reasoning and execution
- 🔧 **MCP Integration** - Kubernetes, Prometheus, Grafana, Vault, and more

## Architecture

```
┌─────────────────────────────────────────────┐
│            ppxai SRE Gateway                │
│  ┌───────────────────────────────────────┐  │
│  │  Manager Agent (reasoning only)       │  │
│  │  - Analyzes alerts/metrics            │  │
│  │  - Plans remediation                  │  │
│  │  - CANNOT execute commands            │  │
│  └──────────────┬────────────────────────┘  │
│                 │ (structured task)          │
│  ┌──────────────▼────────────────────────┐  │
│  │  Policy Engine (code, not prompts)    │  │
│  │  - Action tier enforcement            │  │
│  │  - kubectl verb allowlists            │  │
│  │  - Namespace restrictions             │  │
│  │  - Rate limiting, audit logging       │  │
│  └──────────────┬────────────────────────┘  │
│                 │ (approved action)          │
│  ┌──────────────▼────────────────────────┐  │
│  │  Executor (sandboxed)                 │  │
│  │  - Runs in restricted container       │  │
│  │  - Only approved tools available      │  │
│  │  - All actions logged to JSONL        │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

## Agents (Planned)

- **incident-responder** - Alert triage and correlation
- **cert-monitor** - TLS certificate expiry tracking
- **capacity-planner** - Resource forecasting
- **log-analyst** - Anomaly detection in logs
- **cost-optimizer** - Resource consumption monitoring
- **deployment-validator** - Pre/post-deployment checks

## Foundation

ppxai-sre leverages ~80% of ppxai's existing foundation:

| ppxai Component | SRE Usage |
|-----------------|-----------|
| AGENTS.md | Agent persona definitions |
| MCP servers | SRE skill packs (k8s, prometheus, etc.) |
| Agent mode | Autonomous execution framework |
| Multi-client UI | TUI, VSCode, Web for SRE workflows |
| FastAPI server | Heartbeat scheduler backend |
| vLLM/H100s | Cost-optimized local model hosting |

## Implementation Roadmap

### Phase 1 - Foundation (2-3 weeks)
- [ ] Heartbeat scheduler (APScheduler in FastAPI)
- [ ] Multi-agent AGENT.md format
- [ ] First MCP servers (Prometheus, Slack)
- [ ] Policy engine with action tier enforcement
- [ ] JSONL audit logging

### Phase 2 - Intelligence (3-4 weeks)
- [ ] Manager-executor split with sandboxing
- [ ] Runbook ingestion (markdown → agent knowledge)
- [ ] Multi-model routing (local vs frontier)
- [ ] Outbound notifications (Slack, PagerDuty)
- [ ] Agent activity dashboard

### Phase 3 - Collaboration (4-6 weeks)
- [ ] Multi-agent coordination
- [ ] Team features in web app
- [ ] ITSM/ticketing integration
- [ ] Feedback loop for agent improvement
- [ ] Incident postmortem generation

## Documentation

- [RESEARCH.md](docs/RESEARCH.md) - Full OpenClaw analysis and strategic rationale
- ARCHITECTURE.md (coming soon)
- SECURITY.md (coming soon)

## Security Model

**Critical Design Principle:** Security through architectural boundaries, NOT prompt instructions.

- ✅ Hard policy enforcement via code/OPA
- ✅ Manager cannot execute (only plans)
- ✅ Executor cannot reason (only runs approved actions)
- ✅ Action tiers: Autonomous → Notify → Require approval
- ✅ Audit logging (mandatory, SIEM-ready)
- ❌ NO prompt-based guardrails
- ❌ NO community skill marketplace

## Timeline

**Start Date:** After ppxai v1.16.0 ships (March 2026)

**Current Focus:** Complete ppxai v1.15.5 → v1.16.0 first

## References

- ppxai: https://github.com/rcconsult/ppxai
- OpenClaw: https://github.com/openclaw/openclaw
- Gartner Market Guide for AI SRE (Jan 2026)

---

*Created: February 15, 2026*
*Status: Research phase - implementation begins post-v1.16.0*

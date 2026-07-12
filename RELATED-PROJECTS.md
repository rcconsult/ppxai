# Related Projects

## ppxai-sre

**Autonomous SRE agent platform built on ppxai foundation**

**Repository:** https://github.com/rcconsult/ppxai-sre (private)

**Status:** Active integration

### Overview

ppxai-sre extends ppxai with OpenClaw-inspired autonomous agent patterns specialized for Site Reliability Engineering. It enables proactive monitoring, incident response, and infrastructure management through AI agents with hard security boundaries.

Its outlook-monitor agent consumes ppxai's released, versioned `POST /v1/oneshot` gateway endpoint (bearer auth) — a stable, semver-guaranteed public surface, not an internal import. v1.19.x adds the `/v1/agent/*` background agent platform (durable runs, tool-capable sandboxed tier, capability grants, budgets, egress allowlists) that ppxai-sre is building its next integration layer on via an SDK-style path.

### Key Differences from ppxai

| Aspect | ppxai | ppxai-sre |
|--------|-------|-----------|
| **Purpose** | Developer chat tool | Autonomous SRE operations |
| **User** | Interactive (developers) | Autonomous + interactive (SREs) |
| **Execution** | On-demand commands | Background heartbeat + on-demand |
| **Scope** | General purpose | Infrastructure operations |
| **Security** | User consent for tools | Tiered autonomous permissions |

### Architecture

ppxai-sre is a separate codebase that talks to ppxai over the network rather than embedding it:
- Consumes ppxai's `/v1` API gateway (oneshot completions today; `/v1/agent/*` for background runs)
- Brings its own agent runtime, tool execution, and policy engine on the SRE side
- MCP integration (Kubernetes, Prometheus, Grafana, PagerDuty, etc.) lives in ppxai-sre, not ppxai

### Planned Features

- **Heartbeat scheduler** - Proactive monitoring loop
- **Multi-agent routing** - Specialized agents (incident-responder, cert-monitor, etc.)
- **Manager-executor pattern** - Separation of reasoning and execution
- **Policy engine** - Hard security boundaries (not prompt-based)
- **MCP servers** - Kubernetes, Prometheus, Grafana, PagerDuty, etc.

### Integration Surface

ppxai-sre does not vendor or import ppxai's internal modules — it integrates purely over the network via the versioned `/v1` API gateway (`POST /v1/oneshot` today; `/v1/agent/*` for the emerging SDK path). This keeps ppxai's internal endpoints (`/chat`, `/command/*`, etc.) free to evolve without breaking the SRE integration. See [docs/api-gateway.md](docs/api-gateway.md) for the gateway contract.

### Why Separate Repository?

- **Privacy** - Strategic research kept private
- **Different scope** - Enterprise SRE vs developer tools
- **Different cadence** - Independent release schedule
- **Shared foundation** - Integrates against ppxai's stable `/v1` gateway rather than importing it as a dependency

---

*For access to ppxai-sre repository, contact repository owner.*

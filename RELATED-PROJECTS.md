# Related Projects

## ppxai-sre

**Autonomous SRE agent platform built on ppxai foundation**

**Repository:** https://github.com/rcconsult/ppxai-sre (private)

**Status:** Research/Planning phase (post-v1.16.0)

### Overview

ppxai-sre extends ppxai with OpenClaw-inspired autonomous agent patterns specialized for Site Reliability Engineering. It enables proactive monitoring, incident response, and infrastructure management through AI agents with hard security boundaries.

### Key Differences from ppxai

| Aspect | ppxai | ppxai-sre |
|--------|-------|-----------|
| **Purpose** | Developer chat tool | Autonomous SRE operations |
| **User** | Interactive (developers) | Autonomous + interactive (SREs) |
| **Execution** | On-demand commands | Background heartbeat + on-demand |
| **Scope** | General purpose | Infrastructure operations |
| **Security** | User consent for tools | Tiered autonomous permissions |

### Architecture

ppxai-sre uses ~80% of ppxai's foundation:
- Engine and provider system
- Tool execution framework
- Multi-client architecture (TUI, VSCode, Web)
- FastAPI server backend
- MCP integration

### Planned Features

- **Heartbeat scheduler** - Proactive monitoring loop
- **Multi-agent routing** - Specialized agents (incident-responder, cert-monitor, etc.)
- **Manager-executor pattern** - Separation of reasoning and execution
- **Policy engine** - Hard security boundaries (not prompt-based)
- **MCP servers** - Kubernetes, Prometheus, Grafana, PagerDuty, etc.

### Timeline

Implementation begins after ppxai v1.16.0 ships (March 2026).

### Why Separate Repository?

- **Privacy** - Strategic research kept private
- **Different scope** - Enterprise SRE vs developer tools
- **Different cadence** - Independent release schedule
- **Shared foundation** - Imports ppxai as dependency

---

*For access to ppxai-sre repository, contact repository owner.*

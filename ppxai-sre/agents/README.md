# SRE Agents

This directory contains agent definitions in AGENT.md format.

## Planned Agents

### incident-responder
Alert triage, correlation with deployments, initial remediation

### cert-monitor
TLS certificate expiry tracking and renewal automation

### capacity-planner
Resource forecasting and scaling recommendations

### log-analyst
Anomaly detection in application and infrastructure logs

### cost-optimizer
Resource consumption monitoring and cost anomaly detection

### deployment-validator
Pre-deployment validation and post-deployment health checks

## Agent Structure

Each agent directory contains:

```
agent-name/
├── AGENT.md          # Identity, role, capabilities, boundaries
├── TOOLS.md          # Available tools and usage notes
├── RUNBOOKS.md       # Embedded runbook knowledge
└── sessions/         # Historical execution logs
```

## Action Tiers

- **Tier 1 (Autonomous)** - Read-only queries, status reporting
- **Tier 2 (Notify and Act)** - Non-prod mutations, approved runbooks
- **Tier 3 (Require Approval)** - Production mutations, risky operations

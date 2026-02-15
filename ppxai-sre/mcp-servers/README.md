# SRE MCP Servers

Model Context Protocol servers for SRE operations.

## Planned Servers

### kubernetes
- Namespaced kubectl operations (scoped by environment)
- Read-only in prod, read-write in dev/staging
- Pod logs, describe, events, resource quotas

### prometheus
- PromQL query execution
- Alert status and history
- Metric time-series data

### grafana
- Dashboard snapshots
- Annotation creation
- Panel data extraction

### slack
- Webhook notifications to channels
- Status updates for incidents
- Escalation notifications

### pagerduty
- Incident creation and escalation
- On-call schedule queries
- Incident timeline updates

### vault
- Secret rotation status (read-only)
- Certificate expiry checks
- Lease information

### pure-storage
- Storage array health metrics
- Capacity forecasting data
- Performance statistics

## Security Model

Each MCP server enforces:
- Scoped permissions (namespace, environment)
- Action tier classification
- Audit logging
- Rate limiting
- Network access restrictions

## Development

MCP servers are Python packages implementing the Model Context Protocol:

```python
from mcp import Server, Resource, Tool

class KubernetesMCP(Server):
    def __init__(self, namespace_allow: list[str]):
        self.namespace_allow = namespace_allow

    @tool
    def get_pods(self, namespace: str) -> list[dict]:
        if namespace not in self.namespace_allow:
            raise PermissionError(f"Namespace {namespace} not allowed")
        # Implementation...
```

## References

- MCP Specification: https://modelcontextprotocol.io/
- ppxai MCP Integration: See ppxai/mcp/

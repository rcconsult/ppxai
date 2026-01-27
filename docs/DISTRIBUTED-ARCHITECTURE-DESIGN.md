# Distributed Architecture: Multi-Tenant ppxai with Remote Agents

**Date:** 2026-01-27
**Use Case:** Enterprise deployment with centralized control and distributed execution
**Status:** Design proposal

---

## Architecture Overview

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER LAYER                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ Web App  │  │ VSCode   │  │ ppxaide  │  │ Mobile   │      │
│  │ (Browser)│  │Extension │  │   TUI    │  │   App    │      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘      │
│       │             │              │             │             │
│       └─────────────┴──────────────┴─────────────┘             │
│                          │                                      │
│                          │ HTTPS + SSE                          │
│                          ▼                                      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    CONTROL PLANE (K8S)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐      │
│  │           API Gateway (Kong / Nginx)                 │      │
│  │  - Authentication (OAuth2, OIDC, API Keys)          │      │
│  │  - Authorization (RBAC, tenant isolation)           │      │
│  │  - Rate limiting, SSL termination                   │      │
│  └────────────────────┬─────────────────────────────────┘      │
│                       │                                         │
│  ┌────────────────────▼─────────────────────────────────┐      │
│  │         ppxai-server (FastAPI)                       │      │
│  │  Pods: [server-1] [server-2] [server-3] ...        │      │
│  │  - SSE streaming to clients                         │      │
│  │  - LLM provider access                              │      │
│  │  - Session management (Redis)                       │      │
│  │  - Tool orchestration                               │      │
│  └────────────────────┬─────────────────────────────────┘      │
│                       │                                         │
│  ┌────────────────────▼─────────────────────────────────┐      │
│  │        Message Bus (NATS / RabbitMQ / Kafka)        │      │
│  │  Topics:                                            │      │
│  │    - tool.execute.{tenant_id}.{agent_id}           │      │
│  │    - tool.result.{tenant_id}.{session_id}          │      │
│  │    - agent.heartbeat                               │      │
│  │    - agent.register                                │      │
│  └────────────────────┬─────────────────────────────────┘      │
│                       │                                         │
│  ┌────────────────────┴─────────────────────────────────┐      │
│  │              Shared Services                         │      │
│  │  - Redis (sessions, cache)                          │      │
│  │  - PostgreSQL (users, agents, audit)                │      │
│  │  - S3 (file storage)                                │      │
│  │  - Prometheus/Grafana (metrics)                     │      │
│  └──────────────────────────────────────────────────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                          │
                          │ Message Bus
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DATA PLANE (Agents)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │   Agent 1    │  │   Agent 2    │  │   Agent N    │         │
│  │ (Dev Server) │  │(Prod Server) │  │ (Edge Device)│         │
│  ├──────────────┤  ├──────────────┤  ├──────────────┤         │
│  │ • File ops   │  │ • Shell exec │  │ • Docker ops │         │
│  │ • Git ops    │  │ • File ops   │  │ • File ops   │         │
│  │ • Docker ops │  │ • K8S ops    │  │ • Shell exec │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│                                                                 │
│  Features:                                                      │
│  - Subscribe to message bus                                     │
│  - Execute tools locally with isolation                         │
│  - Report results back                                          │
│  - Health checks / heartbeat                                    │
│  - TLS client certificates (mTLS)                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Architecture Options

### Option 1: Message Bus Architecture (RECOMMENDED) ⭐

**Pattern:** Pub/Sub via NATS/RabbitMQ/Kafka

**Flow:**
```
User → Client → API Gateway → ppxai-server
                                   ↓
                          [Publish to bus]
                    topic: tool.execute.{tenant}.{agent}
                                   ↓
                          [Message Bus]
                                   ↓
                          [Agent subscribes]
                                   ↓
                          [Execute locally]
                                   ↓
                         [Publish result]
                    topic: tool.result.{tenant}.{session}
                                   ↓
                          [Server receives]
                                   ↓
                          [Stream to client]
```

**Pros:**
- ✅ **Decoupled** - Server and agents don't need direct connections
- ✅ **Scalable** - Add agents without server changes
- ✅ **Reliable** - Message persistence, replay, dead letter queues
- ✅ **Multi-tenant** - Topic-based isolation
- ✅ **Fault tolerant** - Agents can go offline, messages queued
- ✅ **Observable** - Easy to monitor message flow
- ✅ **Load balancing** - Multiple agents can handle same topics

**Cons:**
- ⚠️ Requires message bus infrastructure
- ⚠️ Eventual consistency (not real-time)
- ⚠️ More complex than direct HTTP

**Message Bus Choice:**

| Feature | NATS | RabbitMQ | Kafka |
|---------|------|----------|-------|
| **Latency** | Ultra-low (<1ms) | Low (5-10ms) | Medium (10-50ms) |
| **Throughput** | Very high | High | Very high |
| **Complexity** | Simple | Medium | High |
| **Persistence** | Optional (JetStream) | Yes | Yes (durable) |
| **Multi-tenancy** | Excellent (subjects) | Good (exchanges) | Good (topics) |
| **Operations** | Easy | Medium | Complex |
| **Best for** | Real-time, lightweight | Task queues | Event logs, analytics |

**Recommendation: NATS** for this use case:
- Lightweight, easy to deploy in K8S
- Low latency (important for interactive AI)
- Excellent multi-tenancy via hierarchical subjects
- Simple client libraries
- Built-in request/reply pattern

---

### Option 2: gRPC Bidirectional Streaming

**Pattern:** Agents connect to server via gRPC, maintain persistent connections

**Flow:**
```
Agent → [gRPC connect] → Server
            ↓
    [Bidirectional stream]
            ↓
Server streams commands → Agent executes → Streams results back
```

**Pros:**
- ✅ **Low latency** - Persistent connections
- ✅ **Type safety** - Protobuf schemas
- ✅ **Efficient** - Binary protocol
- ✅ **Built-in auth** - mTLS, interceptors
- ✅ **Load balancing** - gRPC LB support

**Cons:**
- ⚠️ Agents must maintain connections (harder with NAT/firewalls)
- ⚠️ Server must track agent connections
- ⚠️ Less flexible than message bus
- ⚠️ Connection failures require retry logic

**Best for:** Agents in controlled network (same datacenter)

---

### Option 3: WebSocket with API Gateway

**Pattern:** Agents connect via WebSocket, server pushes commands

**Flow:**
```
Agent → [WebSocket upgrade] → API Gateway → Server
                 ↓
         [Persistent connection]
                 ↓
    Server pushes JSON messages → Agent executes → Pushes results
```

**Pros:**
- ✅ **Simple** - Standard WebSocket protocol
- ✅ **NAT friendly** - Outbound connections from agents
- ✅ **Real-time** - Bidirectional messaging
- ✅ **Wide support** - Libraries in all languages

**Cons:**
- ⚠️ Server must manage connections (state)
- ⚠️ Scaling harder (sticky sessions or Redis pub/sub)
- ⚠️ Reconnection logic needed

**Best for:** Small number of agents (<100)

---

### Option 4: Agent Pull Model (HTTP Long Polling)

**Pattern:** Agents poll server for work, server queues commands

**Flow:**
```
Agent → [GET /work/poll?timeout=30s] → Server
                 ↓
         [Long poll, waits for work]
                 ↓
         [Work available, returns immediately]
                 ↓
Agent executes → [POST /work/result] → Server
```

**Pros:**
- ✅ **Simple** - Standard HTTP, no persistent connections
- ✅ **Firewall friendly** - Agents initiate all connections
- ✅ **Stateless server** - Easy to scale
- ✅ **No message bus** - Simpler infrastructure

**Cons:**
- ⚠️ Higher latency (polling delay)
- ⚠️ Inefficient (many empty polls)
- ⚠️ Work queue needed in server

**Best for:** Agents behind strict firewalls, simple deployments

---

## Recommended Architecture: NATS Message Bus

### System Design

```
┌─────────────────────────────────────────────────────────────┐
│                      Control Plane                          │
└─────────────────────────────────────────────────────────────┘

API Gateway (Kong)
  ├─ HTTPS → Client facing
  ├─ OAuth2/OIDC → Authentication
  ├─ JWT validation → Authorization
  └─ Rate limiting → DDoS protection

ppxai-server (FastAPI pods)
  ├─ SSE to clients (authenticated)
  ├─ Tool execution orchestration
  ├─ Session management (Redis)
  └─ NATS publisher/subscriber

NATS JetStream
  ├─ Subjects:
  │   ├─ tool.execute.{tenant_id}.{agent_id}.{tool_name}
  │   ├─ tool.result.{tenant_id}.{session_id}
  │   ├─ agent.heartbeat.{tenant_id}.{agent_id}
  │   └─ agent.register.{tenant_id}
  ├─ Persistence: 7 days
  └─ Replay: Yes

PostgreSQL
  ├─ Users, tenants, RBAC
  ├─ Agent registry (ID, tenant, capabilities, status)
  ├─ Audit logs (who did what, when)
  └─ Session metadata

Redis
  ├─ Session state (active conversations)
  ├─ Result cache
  └─ Rate limiting counters

┌─────────────────────────────────────────────────────────────┐
│                       Data Plane                            │
└─────────────────────────────────────────────────────────────┘

ppxai-agent (Python/Go binary)
  ├─ NATS subscriber (reconnect logic)
  ├─ Tool executor (sandboxed)
  ├─ Heartbeat sender (every 30s)
  ├─ mTLS client certificate
  ├─ Capabilities declaration
  └─ Result publisher
```

---

## Implementation Details

### 1. NATS Subject Hierarchy

**Pattern:** `{domain}.{action}.{tenant}.{target}.{detail}`

```
tool.execute.acme_corp.agent_dev_001.shell
tool.execute.acme_corp.agent_dev_001.file_write
tool.execute.acme_corp.agent_prod_*.docker    # Wildcard
tool.result.acme_corp.session_abc123
agent.heartbeat.acme_corp.agent_dev_001
agent.register.acme_corp
```

**Benefits:**
- Tenant isolation (agents only see their tenant's messages)
- Selective subscriptions (agent subscribes to specific tools)
- Wildcard targeting (broadcast to all prod agents)

---

### 2. Message Schemas

**Tool Execution Request:**
```json
{
  "message_id": "msg_20260127_001",
  "tenant_id": "acme_corp",
  "session_id": "session_abc123",
  "agent_id": "agent_dev_001",  // or "*" for any
  "tool": "shell",
  "arguments": {
    "command": "ls -la /tmp",
    "working_dir": "/home/user",
    "timeout": 30
  },
  "consent": {
    "approved": true,
    "user_id": "user@example.com",
    "timestamp": "2026-01-27T10:30:00Z"
  },
  "timestamp": "2026-01-27T10:30:00Z",
  "timeout": 300,  // Max execution time
  "priority": "normal"  // normal, high, critical
}
```

**Tool Execution Result:**
```json
{
  "message_id": "msg_20260127_001",  // Same as request
  "tenant_id": "acme_corp",
  "session_id": "session_abc123",
  "agent_id": "agent_dev_001",
  "tool": "shell",
  "status": "success",  // success, error, timeout
  "result": {
    "stdout": "total 8...",
    "stderr": "",
    "exit_code": 0,
    "execution_time_ms": 245
  },
  "error": null,
  "timestamp": "2026-01-27T10:30:05Z",
  "agent_metadata": {
    "hostname": "dev-server-01",
    "os": "linux",
    "version": "1.15.0"
  }
}
```

**Agent Heartbeat:**
```json
{
  "agent_id": "agent_dev_001",
  "tenant_id": "acme_corp",
  "status": "healthy",  // healthy, degraded, offline
  "capabilities": ["shell", "file_read", "file_write", "git", "docker"],
  "load": {
    "cpu_percent": 15.2,
    "memory_mb": 256,
    "active_tasks": 2
  },
  "timestamp": "2026-01-27T10:30:00Z",
  "version": "1.15.0"
}
```

**Agent Registration:**
```json
{
  "agent_id": "agent_dev_001",
  "tenant_id": "acme_corp",
  "hostname": "dev-server-01",
  "ip_address": "10.0.1.50",
  "os": "linux",
  "capabilities": ["shell", "file_read", "file_write", "git", "docker"],
  "certificate_fingerprint": "sha256:abc123...",
  "version": "1.15.0",
  "timestamp": "2026-01-27T10:00:00Z"
}
```

---

### 3. Authentication & Authorization

**Control Plane (Client → Server):**

```
User → Client → API Gateway
         ↓
   OAuth2/OIDC login
         ↓
   JWT token issued
         ↓
   Client includes: Authorization: Bearer {jwt}
         ↓
   API Gateway validates JWT
         ↓
   Extracts tenant_id, user_id, roles
         ↓
   Forwards to ppxai-server
```

**JWT Claims:**
```json
{
  "sub": "user@example.com",
  "tenant_id": "acme_corp",
  "roles": ["developer", "tools.shell.execute", "tools.file.read"],
  "exp": 1706356800,
  "iat": 1706270400
}
```

**RBAC Permissions:**
- `tools.*.execute` - Execute any tool
- `tools.shell.execute` - Execute shell commands
- `tools.file.read` - Read files
- `tools.file.write` - Write files
- `tools.docker.admin` - Docker operations
- `agents.register` - Register new agents
- `agents.view` - View agent status

**Data Plane (Agent → NATS):**

```
Agent → NATS (mTLS)
   ↓
Client certificate validation
   ↓
Certificate CN = agent_id
   ↓
Certificate OU = tenant_id
   ↓
NATS authorization:
  - Can subscribe: tool.execute.{tenant_id}.{agent_id}.*
  - Can publish: tool.result.{tenant_id}.*
  - Can publish: agent.heartbeat.{tenant_id}.{agent_id}
```

**mTLS Certificate Example:**
```
Subject: CN=agent_dev_001, OU=acme_corp, O=ppxai
Issuer: CN=ppxai-ca
Validity: 90 days
```

---

### 4. Multi-Tenancy

**Tenant Isolation:**

1. **Network level:**
   - Each tenant gets isolated NATS subject space
   - Agents can only subscribe to their tenant's subjects
   - API Gateway enforces JWT tenant_id

2. **Database level:**
   - All tables have `tenant_id` column
   - Row-level security (RLS) in PostgreSQL
   - Agent registry filtered by tenant

3. **Message level:**
   - Every message includes `tenant_id`
   - Server validates tenant_id matches JWT
   - Agents validate tenant_id matches certificate

4. **Storage level:**
   - S3 bucket prefix: `{tenant_id}/`
   - Redis keyspace: `{tenant_id}:{key}`

---

### 5. Tool Execution Flow

**Complete flow with all components:**

```
1. User sends message with file edit request
   ↓
2. Client → API Gateway (HTTPS + JWT)
   ↓
3. API Gateway validates JWT → ppxai-server
   ↓
4. ppxai-server calls LLM (OpenAI/Perplexity)
   ↓
5. LLM returns tool call: edit_file(path, content)
   ↓
6. ppxai-server checks RBAC: user has tools.file.write?
   ↓
7. ppxai-server publishes to NATS:
   Subject: tool.execute.acme_corp.agent_dev_001.file_write
   ↓
8. NATS delivers to subscribed agent
   ↓
9. Agent validates:
   - tenant_id matches certificate
   - tool capability enabled
   - path within allowed directories
   ↓
10. Agent executes file write (sandboxed)
   ↓
11. Agent publishes result to NATS:
   Subject: tool.result.acme_corp.session_abc123
   ↓
12. ppxai-server receives result
   ↓
13. ppxai-server stores in Redis (session state)
   ↓
14. ppxai-server streams result to client via SSE
   ↓
15. Client displays result to user
```

---

### 6. Error Handling & Retry

**Scenarios:**

**Agent offline:**
```
1. Tool request published to NATS
2. No agent responds within timeout (30s)
3. Server receives timeout from NATS
4. Server streams error to client: "Agent unavailable"
5. Message stored in dead letter queue (optional retry)
```

**Agent crashes mid-execution:**
```
1. Agent receives tool request
2. Agent starts execution
3. Agent crashes (no result published)
4. Server timeout (5 minutes)
5. Server checks agent heartbeat (missing)
6. Server marks agent as offline
7. Server streams error to client: "Agent failed"
```

**Network partition:**
```
1. Agent executes successfully
2. Network partition (agent can't reach NATS)
3. Agent buffers result locally
4. Network restored
5. Agent reconnects to NATS
6. Agent publishes buffered result
7. Server receives delayed result
8. Server checks if session still active
9. If yes: stream result to client
10. If no: store in audit log
```

---

### 7. Observability

**Metrics (Prometheus):**

```
# Control plane
ppxai_server_requests_total{tenant, endpoint, status}
ppxai_server_sse_connections{tenant}
ppxai_server_tool_executions_total{tenant, tool, status}
ppxai_server_tool_execution_duration_seconds{tenant, tool}

# Message bus
nats_messages_published_total{subject}
nats_messages_delivered_total{subject}
nats_message_latency_seconds{subject}

# Data plane
ppxai_agent_heartbeat_timestamp{tenant, agent}
ppxai_agent_tool_executions_total{tenant, agent, tool, status}
ppxai_agent_tool_duration_seconds{tenant, agent, tool}
ppxai_agent_load_cpu_percent{tenant, agent}
ppxai_agent_load_memory_mb{tenant, agent}
```

**Logging (Structured JSON):**

```json
{
  "timestamp": "2026-01-27T10:30:00Z",
  "level": "info",
  "service": "ppxai-server",
  "tenant_id": "acme_corp",
  "session_id": "session_abc123",
  "user_id": "user@example.com",
  "message": "Tool execution requested",
  "tool": "shell",
  "agent_id": "agent_dev_001",
  "message_id": "msg_20260127_001",
  "trace_id": "trace_abc123"
}
```

**Tracing (OpenTelemetry):**

```
Client request → API Gateway → ppxai-server → NATS → Agent
     ↓              ↓               ↓            ↓       ↓
  span_1        span_2          span_3       span_4  span_5

Trace attributes:
- tenant_id
- session_id
- user_id
- tool
- agent_id
```

---

## Security Considerations

### 1. Authentication

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| **Client → Server** | OAuth2/OIDC + JWT | User authentication |
| **Server → NATS** | TLS + credentials | Service authentication |
| **Agent → NATS** | mTLS (client cert) | Agent authentication |

### 2. Authorization

| Layer | Mechanism | Enforcement |
|-------|-----------|-------------|
| **Client** | JWT roles | API Gateway validates |
| **Server** | RBAC policies | Check before tool execution |
| **Agent** | Capability list | Agent checks before execution |
| **NATS** | Subject ACLs | NATS enforces pub/sub permissions |

### 3. Encryption

- **Transit:** TLS 1.3 everywhere (client-server, server-NATS, agent-NATS)
- **At rest:** Database encryption, S3 encryption
- **Secrets:** Vault/Sealed Secrets for API keys

### 4. Isolation

- **Network:** NATS subject namespaces per tenant
- **Compute:** Agent sandboxing (containers, seccomp, AppArmor)
- **Data:** PostgreSQL RLS, Redis keyspace prefixes

### 5. Audit

- **All tool executions logged** (who, what, when, where, result)
- **Agent registrations logged**
- **Failed auth attempts logged**
- **Retention:** 90 days (configurable)

---

## Deployment Architecture

### Kubernetes Resources

**Control Plane:**

```yaml
# ppxai-server deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ppxai-server
spec:
  replicas: 3
  selector:
    matchLabels:
      app: ppxai-server
  template:
    metadata:
      labels:
        app: ppxai-server
    spec:
      containers:
      - name: server
        image: ppxai/server:1.16.0
        env:
        - name: NATS_URL
          value: "nats://nats:4222"
        - name: REDIS_URL
          value: "redis://redis:6379"
        - name: POSTGRES_URL
          valueFrom:
            secretKeyRef:
              name: postgres-creds
              key: url
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 2000m
            memory: 4Gi
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000

---
# NATS JetStream
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: nats
spec:
  serviceName: nats
  replicas: 3
  selector:
    matchLabels:
      app: nats
  template:
    metadata:
      labels:
        app: nats
    spec:
      containers:
      - name: nats
        image: nats:2.10
        args:
        - "--jetstream"
        - "--cluster_name=ppxai"
        volumeMounts:
        - name: data
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 100Gi

---
# API Gateway (Kong)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kong
spec:
  replicas: 2
  selector:
    matchLabels:
      app: kong
  template:
    metadata:
      labels:
        app: kong
    spec:
      containers:
      - name: kong
        image: kong:3.5
        env:
        - name: KONG_DATABASE
          value: postgres
        - name: KONG_PG_HOST
          value: postgres
        - name: KONG_PROXY_ACCESS_LOG
          value: /dev/stdout
        - name: KONG_ADMIN_ACCESS_LOG
          value: /dev/stdout
        - name: KONG_PROXY_ERROR_LOG
          value: /dev/stderr
        - name: KONG_ADMIN_ERROR_LOG
          value: /dev/stderr
```

**Data Plane:**

```yaml
# Agent DaemonSet (runs on every node)
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: ppxai-agent
spec:
  selector:
    matchLabels:
      app: ppxai-agent
  template:
    metadata:
      labels:
        app: ppxai-agent
    spec:
      containers:
      - name: agent
        image: ppxai/agent:1.16.0
        env:
        - name: NATS_URL
          value: "nats://nats:4222"
        - name: TENANT_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.labels['tenant']
        - name: AGENT_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        volumeMounts:
        - name: agent-cert
          mountPath: /etc/ppxai/certs
          readOnly: true
        - name: docker-sock
          mountPath: /var/run/docker.sock  # For docker tools
        securityContext:
          capabilities:
            drop: ["ALL"]
            add: ["NET_BIND_SERVICE"]
          readOnlyRootFilesystem: true
      volumes:
      - name: agent-cert
        secret:
          secretName: agent-cert
      - name: docker-sock
        hostPath:
          path: /var/run/docker.sock
```

---

## Agent Implementation

### Agent Core (Python)

```python
# ppxai/agent/main.py
import asyncio
import json
from nats.aio.client import Client as NATS
from nats.js.api import StreamConfig

class PpxaiAgent:
    """Remote agent for tool execution."""

    def __init__(
        self,
        tenant_id: str,
        agent_id: str,
        nats_url: str,
        cert_file: str,
        key_file: str,
        ca_file: str,
    ):
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.nats_url = nats_url
        self.cert_file = cert_file
        self.key_file = key_file
        self.ca_file = ca_file

        self.nc: Optional[NATS] = None
        self.capabilities = ["shell", "file_read", "file_write", "git"]

    async def connect(self):
        """Connect to NATS with mTLS."""
        self.nc = NATS()
        await self.nc.connect(
            servers=[self.nats_url],
            tls=nats.aio.client.TLSOptions(
                cert_file=self.cert_file,
                key_file=self.key_file,
                ca_file=self.ca_file,
            ),
            name=f"{self.tenant_id}:{self.agent_id}",
        )
        logger.info(f"Connected to NATS: {self.nats_url}")

        # Get JetStream context
        self.js = self.nc.jetstream()

        # Register agent
        await self.register()

        # Subscribe to tool execution requests
        for tool in self.capabilities:
            subject = f"tool.execute.{self.tenant_id}.{self.agent_id}.{tool}"
            await self.nc.subscribe(subject, cb=self.handle_tool_request)
            logger.info(f"Subscribed to: {subject}")

        # Start heartbeat
        asyncio.create_task(self.send_heartbeat())

    async def register(self):
        """Register agent with control plane."""
        message = {
            "agent_id": self.agent_id,
            "tenant_id": self.tenant_id,
            "hostname": socket.gethostname(),
            "capabilities": self.capabilities,
            "version": __version__,
            "timestamp": datetime.utcnow().isoformat(),
        }
        subject = f"agent.register.{self.tenant_id}"
        await self.nc.publish(subject, json.dumps(message).encode())
        logger.info("Agent registered")

    async def send_heartbeat(self):
        """Send periodic heartbeat."""
        while True:
            message = {
                "agent_id": self.agent_id,
                "tenant_id": self.tenant_id,
                "status": "healthy",
                "capabilities": self.capabilities,
                "timestamp": datetime.utcnow().isoformat(),
            }
            subject = f"agent.heartbeat.{self.tenant_id}.{self.agent_id}"
            await self.nc.publish(subject, json.dumps(message).encode())
            await asyncio.sleep(30)

    async def handle_tool_request(self, msg):
        """Handle tool execution request."""
        try:
            request = json.loads(msg.data.decode())
            logger.info(f"Tool request: {request['tool']}")

            # Validate
            if request["tenant_id"] != self.tenant_id:
                raise ValueError("Tenant ID mismatch")

            # Execute
            result = await self.execute_tool(
                tool=request["tool"],
                arguments=request["arguments"],
            )

            # Publish result
            response = {
                "message_id": request["message_id"],
                "tenant_id": self.tenant_id,
                "session_id": request["session_id"],
                "agent_id": self.agent_id,
                "tool": request["tool"],
                "status": "success",
                "result": result,
                "timestamp": datetime.utcnow().isoformat(),
            }

            subject = f"tool.result.{self.tenant_id}.{request['session_id']}"
            await self.nc.publish(subject, json.dumps(response).encode())

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            # Publish error result
            ...

    async def execute_tool(self, tool: str, arguments: dict) -> dict:
        """Execute tool in sandboxed environment."""
        # Import tool executor
        from ppxai.engine.tools import get_tool

        tool_impl = get_tool(tool)
        result = await tool_impl.execute(**arguments)
        return result
```

---

## Scaling Considerations

### Horizontal Scaling

| Component | Scaling Strategy |
|-----------|-----------------|
| **ppxai-server** | Stateless pods, scale based on CPU/requests |
| **API Gateway** | Multiple replicas behind load balancer |
| **NATS** | Cluster with 3+ nodes for HA |
| **Redis** | Redis Cluster or Sentinel for HA |
| **PostgreSQL** | Primary + read replicas |
| **Agents** | Add more agents, no limit |

### Capacity Planning

**Example: 1000 concurrent users**

- **ppxai-server:** 10 pods (100 users/pod)
- **API Gateway:** 3 replicas
- **NATS:** 3 nodes (cluster)
- **Redis:** 3 nodes (cluster)
- **PostgreSQL:** 1 primary + 2 replicas
- **Agents:** Variable (based on workload)

**Resource estimates:**
- CPU: ~50 cores total
- Memory: ~200GB total
- Storage: 1TB (PostgreSQL) + 500GB (NATS)

---

## Cost Estimation (AWS)

**Monthly costs for 1000 concurrent users:**

| Component | Service | Size | Cost/month |
|-----------|---------|------|------------|
| Control plane | EKS cluster | t3.xlarge × 5 | $600 |
| ppxai-server | EC2 (pods) | t3.medium × 10 | $400 |
| NATS | EC2 (stateful) | t3.large × 3 | $300 |
| Redis | ElastiCache | cache.r6g.large | $150 |
| PostgreSQL | RDS | db.r6g.xlarge | $400 |
| API Gateway | ALB | - | $25 |
| Storage | EBS + S3 | 2TB | $200 |
| **Total** | | | **~$2,075/month** |

**Per-user cost:** ~$2/user/month

---

## Migration Path

### Phase 1: Add Message Bus Support (v1.16.0)

- Add NATS client to ppxai-server
- Publish tool requests to NATS (optional)
- Keep direct execution as fallback
- **Effort:** 3 days

### Phase 2: Build Agent Prototype (v1.17.0)

- Create ppxai-agent binary
- Implement NATS subscriber
- Implement tool execution
- Test with single agent
- **Effort:** 5 days

### Phase 3: Add Authentication Layer (v1.17.0)

- Integrate API Gateway (Kong)
- Add OAuth2/OIDC support
- Implement JWT validation
- Add RBAC policies
- **Effort:** 5 days

### Phase 4: Multi-Tenancy (v1.18.0)

- Add tenant_id to all tables
- Implement tenant isolation
- Add agent registry
- Test with multiple tenants
- **Effort:** 7 days

### Phase 5: Production Hardening (v1.19.0)

- Add observability (metrics, logs, traces)
- Implement retry/error handling
- Add audit logging
- Load testing
- Documentation
- **Effort:** 10 days

**Total:** ~30 days across 4 releases

---

## Summary

**Recommended Architecture:** NATS Message Bus

**Key Benefits:**
- ✅ Scalable (add agents/servers independently)
- ✅ Reliable (message persistence, replay)
- ✅ Secure (mTLS, multi-tenancy, RBAC)
- ✅ Observable (metrics, logs, traces)
- ✅ Cost-effective (~$2/user/month)

**Best for:**
- Enterprise deployments
- Multi-tenant SaaS
- Distributed teams
- Remote execution needs

**Next Steps:**
1. Validate requirements with stakeholders
2. Design API Gateway + auth strategy
3. POC with NATS + single agent
4. Iterate based on feedback

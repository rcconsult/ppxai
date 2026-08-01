# ADR 0005 — Inspection Triplet pattern for runtime observability

**Date:** 2026-05-10
**Status:** Accepted (status reconciled 2026-08-01 — the pattern shipped and is load-bearing) — implemented: agent runs (`engine/agent_runs.py`: `meta.json` + `state.json` atomic temp-then-rename + `events.jsonl`, producers T5/T6/T7) and preview backend (`engine/preview_backend.py`)
**Related:**
- [ADR 0003](0003-agent-platform-architecture.md) — Agent platform architecture; Stage 2's `runs/<run_id>/agent-<n>/` namespace IS this pattern, scoped to agent runs only
- [`docs/research/2026-05-10-openshell-coordination-patterns.md`](../research/2026-05-10-openshell-coordination-patterns.md) — prior art (NVIDIA OpenShell `runs/<run_id>/` namespace)
- [`../../../ppxai-sre-repo/docs/PPXAI-INTEGRATION-V1.19.md`](../../../ppxai-sre-repo/docs/PPXAI-INTEGRATION-V1.19.md) — caveat C5 (agent-served services routing) builds on this pattern
- `ppxai/server/routes/preview.py` — v1.18.5 preview-backend log file is an `events.jsonl`-shaped artifact today
- `ppxai/engine/session.py` — session JSON files are `state.json`-shaped artifacts today

## Context

ppxai already has multiple runtime artifacts that expose internal
state for inspection:

- `~/.ppxai/sessions/<id>.json` — atomic-write conversation snapshots
- `~/.ppxai/logs/<component>-debug.log` — per-component debug streams
- `~/.ppxai/logs/preview-backend-<pid>.log` (v1.18.5) — captured
  subprocess output from `/preview --serve`
- `~/.ppxai/usage/usage.json` — provider call counters and costs
- `~/.ppxai/checkpoints/<id>/` — git checkpoints for `/agent` rollback

The ADR 0003 Stage 2 plan adds another:

- `~/.ppxai/runs/<run_id>/agent-<n>/{meta.json, state.json,
  events.jsonl, transcript.md}` — agent run namespace

Each artifact was designed independently. They share an underlying
shape — atomic-write snapshot + append-only event log + sometimes
a control surface — but no document names that shape, so:

1. **New components reinvent.** Every time someone needs runtime
   inspection of a new piece (preview backend, MCP server, an
   autonomous SRE agent's dashboard), the artifact layout gets
   negotiated from scratch. preview backends ended up with plain text
   log files; agent runs ended up with structured JSON. Same
   conceptual layer, different shape.
2. **Cross-context inspection is awkward.** ppxai's Textual TUI uses
   an event bus for live UI updates. ppxai-sre's autonomous agents
   run in k8s pods with no shared bus. Today there's no single
   pattern that works in both contexts — the bus-equipped clients
   subscribe to in-process events; the bus-free clients have to
   tail log files; cross-pod readers have to invent yet a third
   protocol.
3. **The agent-platform Stage 2 work is about to commit a shape**
   (`runs/<run_id>/agent-<n>/`) that, under the surface, is the
   right shape for everything. Calling it "the agent thing" instead
   of "the inspection thing" hides the generality and makes the next
   inspectable component an awkward retrofit.

The question raised 2026-05-10: what's the architectural pattern that
allows any background component / service / activity to be inspected
for **debugging, monitoring, or control**, in both event-bus-equipped
contexts (Textual TUI, web app, VSCode ext) and bus-free contexts
(Rich TUI direct read, ppxai-sre autonomous agents in k8s pods,
external operators using `kubectl exec`)?

## Decision

**Adopt the Inspection Triplet as a project-wide pattern** for any
component whose runtime state is worth observing. Three artifacts at
a known per-component filesystem path:

```
<component_root>/
    state.json       atomic-write current snapshot
    events.jsonl     append-only time-ordered log
    admin/           optional bidirectional control surface
        (Unix socket, HTTP port, or absent)
```

### State layer (`state.json`)

Atomic-write snapshot of the component's current state. Updated on
every state change via the standard "write-temp-then-rename" pattern
(POSIX rename is atomic on the same filesystem; readers always see
either the old or the new file, never a half-write). Schema is
component-specific.

Reader contract: `cat state.json | jq` always returns valid JSON.
Concurrent readers don't need locks; concurrent writers serialize
through the atomic-rename invariant.

### Event layer (`events.jsonl`)

Append-only log; one JSON object per line. Each event minimally
carries `{ts, type, ...payload}`. Old entries are NEVER mutated.
Truncation/rotation is a separate operational concern (cron / logrotate)
not part of the contract.

Reader contracts (multiple, equally first-class):
- `tail -f events.jsonl | jq 'select(.type=="ERROR")'` — live filtering
- `cat events.jsonl | jq -s '.[-100:]'` — last N for replay
- HTTP `GET /events?since=<offset>` — event-bus adapter on top of
  the file (`offset` is byte-position or sequence number)

Crucially: **events flow ONE WAY into the file**. Anything that wants
to consume them is a reader, regardless of transport. The Textual TUI's
in-process event bus becomes a CACHE/FANOUT layer that tails
`events.jsonl` and rebroadcasts; an `kubectl exec cat` is equally a
valid consumer.

### Control layer (`admin/`, optional)

Where bidirectional interaction is needed (start/stop a service,
trigger a reload, query a derived value, mutate config), expose a
control surface at a known relative path:

- `admin.sock` — Unix domain socket (in-host components)
- `admin/` HTTP endpoints — when reachable across hosts (k8s pods,
  remote ops); routes are component-specific but conventionally
  include `GET admin/state` (return current `state.json`),
  `POST admin/reload`, `POST admin/stop`, etc.

Components that don't need a control plane omit this layer entirely.
Read-only inspectables (logs, metrics, snapshots) often don't need it.

## Consequences

### What this enables

- **One pattern, all contexts.** Bus-equipped clients (Textual /
  Web / VSCode SSE) layer their bus ON TOP of the file artifacts as
  a cache. Bus-free clients (Rich TUI, ppxai-sre k8s agents,
  CLI inspection tools, k8s `kubectl exec`) read the same files
  directly. No transport gating who can inspect.
- **Cross-pod inspection is free.** PVC-mounted `runs/<id>/` on a
  shared volume + `kubectl exec <other-pod> cat` works without any
  custom protocol. Sibling agents in ppxai-sre's manager-executor
  pattern read peers' `state.json` as their own input.
- **Replay and audit are first-class.** `events.jsonl` is the audit
  log. ppxai-sre's `AuditLogger` (per gap-analysis §5.2) consumes
  the file directly; the same file feeds a real-time dashboard via
  WebSocket; the same file backs CLI debugging via `tail -f`. One
  source of truth.
- **New components inherit the pattern.** When the next inspectable
  appears (an MCP server, a long-running benchmark run, a
  ppxai-sre `cert-monitor` heartbeat) the layout is decided up
  front — same three files at a known root.

### What this requires

- **Atomic-write discipline on `state.json`.** A non-atomic write
  during a reader's `cat` produces a parse failure. The
  ConfigStore module already uses the temp-then-rename pattern;
  formalize it as a shared helper (`ppxai/common/atomic_write.py`).
- **Schema discipline on `events.jsonl`.** Each event type's payload
  shape needs documenting somewhere — likely a per-component
  `EVENTS.md` next to the file, or a JSON schema in
  `ppxai/engine/events_schema.json`. Without this, downstream
  consumers parse defensively and break on shape changes.
- **Decision discipline on the admin layer.** Opt-in per component;
  not every artifact needs control. Avoid making `admin/` mandatory
  — read-only artifacts stay simpler without it.

### Migration plan

The pattern is retroactive. The migration is a series of "rename and
formalize" passes, not rewrites:

| Existing artifact | Triplet shape today | Migration |
|---|---|---|
| `~/.ppxai/sessions/<id>.json` | `state.json`-equivalent | Rename to `~/.ppxai/runs/session-<id>/state.json` over time; add `events.jsonl` for the chat-event-stream |
| `~/.ppxai/logs/preview-backend-<pid>.log` (v1.18.5) | `events.jsonl`-equivalent (text, not JSON) | Promote to JSONL: each subprocess output line becomes `{ts, type: "stdout", line: "..."}`. Add companion `state.json` (pid, port, command, started_at) |
| `~/.ppxai/usage/usage.json` | `state.json`-equivalent | Already correct shape; add `usage-events.jsonl` for per-call event log if/when needed |
| ADR 0003 Stage 2 `runs/<run_id>/agent-<n>/` | **Already the full Triplet** | Rename "agent run namespace" to "the canonical Triplet for an agent run" in docs; reuse the pattern outside agents |
| Future: ppxai-sre `cert-monitor`, `incident-responder` | Per ppxai-sre integration plan | Each agent's pod writes its own Triplet to a PVC-mounted path; ppxai-server (or a sibling agent) reads via `kubectl exec` or admin HTTP |

No code change in v1.18.5; the migration lands incrementally with
each new component or refactor that touches an existing artifact.

### Open decisions

1. **Common path root.** Today `~/.ppxai/` is split into `sessions/`,
   `logs/`, `usage/`, `checkpoints/`. The Stage 2 plan introduces
   `runs/`. Should existing artifacts migrate under `runs/` over
   time (one root, many subdirectories) or stay split? Recommend
   keeping the split to avoid v1.20.x churn, but commit to `runs/`
   for new artifacts.

2. **Event schema versioning.** `events.jsonl` entries should carry
   a `schema_version` field per record so a consumer reading a
   long-lived file across ppxai upgrades knows what to expect.
   Recommend `{"v": 1, "ts": ..., "type": ..., ...}`.

3. **Truncation policy.** `events.jsonl` grows unboundedly. Cron-style
   rotation (preserving last N MB / last N events) belongs at the
   per-component level, not the pattern level. Components that need
   rotation document their policy in their own README.

4. **Control-plane authentication.** When the `admin/` layer is HTTP,
   reuse the `PPXAI_API_TOKEN` mechanism from ADR 0004 (bearer
   middleware); when Unix socket, file permissions are sufficient.
   Cross-pod authentication is a v1.20.x credential-broker concern.

## Why now

Three motivating items in flight:

1. **v1.18.5 `read_preview_log` follow-up tool** would benefit from
   a structured event stream; designing it as Triplet-shaped now
   avoids the v1.20.x retrofit.
2. **v1.19.x ADR 0003 Stage 2 implementation** is about to commit
   the `runs/<run_id>/agent-<n>/` shape; naming it as the Triplet
   pattern (not "the agent thing") means the next inspectable
   doesn't reinvent.
3. **ppxai-sre integration caveat C5** (agent-served services
   routing — see `PPXAI-INTEGRATION-V1.19.md`) needs an inspection
   surface for the agent's dashboard / REST API. The Triplet is
   the substrate that supports it without coupling to the agent's
   internal event bus.

Capturing the pattern as an ADR now means Stage 2 implementation
ships with the right vocabulary, and follow-on work (read_preview_log,
C5 service-binding, sibling-agent reads) doesn't relitigate the
shape each time.

## What this is NOT

- **Not a replacement for the Textual TUI / Web / VSCode event bus.**
  Those buses keep their value as caching/fanout/UI-update layers.
  The Triplet says: the bus reads from the filesystem, not the other
  way around. Components write events ONCE to the file; the bus is
  one consumer.
- **Not a logging framework.** ppxai's per-component
  `~/.ppxai/logs/<component>-debug.log` files are a separate concern
  (debug-level human-readable text). `events.jsonl` is structured,
  schema-documented, intended for programmatic consumption.
- **Not a metrics system.** Numerical time-series belongs in
  Prometheus / OpenTelemetry. The Triplet tracks state and discrete
  events; metrics are a different consumer of those events at most.

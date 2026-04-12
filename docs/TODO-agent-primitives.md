# TODO: Agent Engine Primitives

**Status:** Planning
**Target:** v1.18.x series
**Priority:** High — unblocks ppxai-sre-repo and any higher-level agentic workload built on ppxai
**Created:** 2026-04-12

---

## Overview

ppxai is the platform; ppxai-sre-repo (and future agentic projects) are consumers.
Currently ppxai-sre-core has to build its own beat tracking, event types, zombie
detection, policy engine, and audit logging because ppxai's engine doesn't expose
these primitives. This TODO covers pre-building them into ppxai so consumers get
them for free via `ppxai>=1.18.0`.

**Dependency direction:** `ppxai-sre-core` → depends on → `ppxai>=1.18.0`.
Nothing in ppxai depends on ppxai-sre-core.

**Reference implementation:** `/Users/rado/git/utils/ppxai-sre-repo/libs/core/`
contains the patterns we're upstreaming. Each item below cites the ppxai-sre-core
file that would be simplified or dropped once the engine primitive lands.

---

## P0 — Agent Heartbeat (v1.18.0)

The core primitive: structured lifecycle events + beat tracking + zombie detection
in the engine's tool-calling loop (`ppxai/engine/chat.py`). Ships as one commit.

### P0.1 — Agent lifecycle events in EventType

**File:** `ppxai/engine/types.py`

Add to the `EventType` enum:
```python
AGENT_BEAT = "agent_beat"
AGENT_RUN_START = "agent_run_start"
AGENT_RUN_COMPLETE = "agent_run_complete"
AGENT_RUN_ERROR = "agent_run_error"
AGENT_ZOMBIE = "agent_zombie"
```

**Why:** ppxai-sre-core currently wraps these as `SREEventType` → `EventType.INFO`
with `metadata["sre_type"]` (see `ppxai-sre-repo/libs/core/.../events.py`). Making
them native EventType values means:
- All 4 ppxai clients (Rich, Textual, Web, VSCode) can render them without SRE-specific code
- ppxai-sre-core drops its `SREEventType` wrapper and `sre_event()` helper entirely
- SSE `state_sync` + event streaming handle them like any other engine event

**Effort:** ~10 lines (enum additions + SSE event mapping).

### P0.2 — AgentBeatState dataclass

**File:** `ppxai/engine/types.py`

```python
@dataclass
class AgentBeatState:
    iteration: int = 0
    beat_sequence: int = 0
    last_beat_time: float = 0.0
    last_tool: str = ""
    last_run_ok: bool = True
    consecutive_failures: int = 0
    start_time: float = 0.0

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.start_time if self.start_time else 0.0
```

**Why:** ppxai-sre-core has its own `AgentBeatState` at `heartbeat.py:30-36`.
Moving it to the engine means both ppxai's agent mode and ppxai-sre's scheduled
agents share the same state shape — clients render one widget for both.

**Effort:** ~15 lines.

### P0.3 — Beat emission in chat_with_tools()

**File:** `ppxai/engine/chat.py`

On every tool-loop iteration, emit `AGENT_BEAT` with the current state:

```python
beat = AgentBeatState(start_time=time.monotonic())

while iteration < max_iterations:
    beat.iteration = iteration
    beat.beat_sequence += 1
    beat.last_beat_time = time.monotonic()

    # ... existing tool call logic ...

    beat.last_tool = tool_name
    if tool_succeeded:
        beat.last_run_ok = True
        beat.consecutive_failures = 0
    else:
        beat.last_run_ok = False
        beat.consecutive_failures += 1

    yield Event(EventType.AGENT_BEAT, {
        "iteration": beat.iteration,
        "beat": beat.beat_sequence,
        "tool": beat.last_tool,
        "ok": beat.last_run_ok,
        "failures": beat.consecutive_failures,
        "elapsed_s": round(beat.elapsed_s, 1),
    })
```

**Why:** Today the agent loop emits `EventType.INFO` messages ("Processing...
(iteration N)") which are text-only and unparseable by clients. Structured
beat events let clients render progress bars, elapsed timers, and tool-call
counts without string parsing.

**Effort:** ~30 lines in chat.py.

### P0.4 — Zombie detection / circuit breaker

**File:** `ppxai/engine/chat.py`

After beat emission, check for zombie state:

```python
zombie_threshold = ctx.agent_config.get("zombie_threshold", 3)
if beat.consecutive_failures >= zombie_threshold:
    yield Event(EventType.AGENT_ZOMBIE, {
        "reason": f"{beat.consecutive_failures} consecutive tool failures",
        "last_tool": beat.last_tool,
    })
    break  # bail out of the tool loop
```

**Config:** `tools.agent.zombie_threshold` in ppxai-config.json (default: 3).

**Why:** Today if `apply_patch` fails 10 times in a row, the agent retries with
hallucinated variations until `max_iterations` is exhausted. A zombie threshold
catches this early and breaks the loop. ppxai-sre-core's zombie detection
(`heartbeat.py:137-149`) becomes unnecessary — it just reads the engine event.

**Effort:** ~15 lines in chat.py + config field.

### P0.5 — AppState field for client visibility

**File:** `ppxai/engine/app_state_schema.json`

Add to the canonical schema:
```json
"agent_beat": {
    "client": "agentBeat",
    "type": "object",
    "default": {},
    "group": "streaming",
    "doc": "Latest agent beat state — iteration, tool, ok, failures, elapsed_s. Empty when no agent is running."
}
```

**Why:** Flows through the schema DTO automatically — web gets it via
`window.APP_STATE_SCHEMA`, VSCode via bundled copy, TUIs via Python AppState.
All 4 clients render agent heartbeat without per-client work beyond the widget.

**Effort:** 1 line in schema JSON + bump sentinel test count.

### P0 total effort: ~80 lines engine code + schema field
### P0 ppxai-sre-core simplification: drops `SREEventType`, `sre_event()`, `AgentBeatState` (from heartbeat.py), zombie detection logic. SREHeartbeat becomes: APScheduler cron + call `engine.chat()` + read engine events.

---

## P1 — Enterprise Readiness (v1.18.1)

### P1.1 — Action tier policy system

**Files:** new `ppxai/engine/policy.py`, refactor `ppxai/engine/consent_ops.py`

Generalize the current binary consent system (ask yes/no for file edits and shell
commands) into a configurable tiered policy:

| Tier | Behavior | Current ppxai equivalent |
|------|----------|--------------------------|
| 1 — Autonomous | Auto-approve, log only | `_classify_shell_command() → "allowed"` |
| 2 — Notify & Act | Log + notify human + proceed | (not supported) |
| 3 — Require Approval | Block until human approves | Current consent dialog |

**Config surface:**
```json
"tools": {
    "policy": {
        "default_tier": 1,
        "rules": [
            {"pattern": "apply_patch:*", "tier": 1},
            {"pattern": "run_command:rm *", "tier": 3},
            {"pattern": "run_command:kubectl delete *", "tier": 3},
            {"pattern": "run_command:*", "tier": 2}
        ]
    }
}
```

**ppxai-sre-core simplification:** drops `PolicyEngine`, `PolicyRule`,
`PolicyDecision`. Uses ppxai's built-in policy with SRE-specific rules in
the config YAML.

**Effort:** Medium (~200 lines). Refactors consent_ops + _classify_shell_command
into a policy.py module.

### P1.2 — Structured audit logging (JSONL)

**File:** new `ppxai/engine/audit.py`

Log every tool execution as a JSONL entry:

```json
{"ts": "2026-04-12T14:23:01Z", "tool": "apply_patch", "args_hash": "a1b2c3", "tier": 1, "approved": true, "result": "ok", "tokens": {"prompt": 1200, "completion": 450}, "session_id": "abc"}
```

**Config:** `tools.audit.enabled` (default: false), `tools.audit.path`
(default: `~/.ppxai/audit/actions.jsonl`).

**ppxai-sre-core simplification:** drops `AuditEntry` dataclass and the
JSONL logging logic. Uses ppxai's audit with SRE-specific metadata fields
added via the engine's audit hook.

**Effort:** Small-medium (~100 lines).

---

## P2 — Background Scheduling (v1.18.2 or v1.19.x)

### P2.1 — Optional scheduler primitive

**File:** new `ppxai/engine/scheduler.py`

Expose `engine.schedule(callback, cron_expr)` for background tasks:

```python
engine.schedule(check_certs, "0 */6 * * *")    # every 6 hours
engine.schedule(refresh_context, "*/30 * * * *") # every 30 minutes
```

Uses APScheduler (already a transitive dep via ppxai-sre-core). Made optional
via `pip install ppxai[scheduler]`.

**ppxai-sre-core simplification:** `SREHeartbeat` drops its own APScheduler
setup and uses `engine.schedule()` + engine beat events. The heartbeat class
becomes a thin config reader + agent registry.

**Enables in ppxai standalone:**
- `/monitor` command (watch file/service on interval)
- Periodic AGENTS.md refresh (detect project changes)
- Scheduled context injection (re-read config on timer)

**Effort:** Medium (~150 lines + optional dependency).

---

## Dependency impact on ppxai-sre-core

After all P0-P2 items land:

| ppxai-sre-core module | Status |
|---|---|
| `events.py` (SREEventType + sre_event) | **Dropped** — use ppxai EventType directly |
| `heartbeat.py` (AgentBeatState) | **Simplified** — cron scheduling only; beat tracking + zombie detection are engine-native |
| `models.py` (ActionTier) | **Dropped** — use ppxai policy tiers |
| `policy.py` (PolicyEngine) | **Dropped** — use ppxai engine policy.py |
| `audit.py` (AuditEntry) | **Dropped** — use ppxai engine audit.py with SRE metadata extensions |
| `agent.py` (SREAgent, AgentRegistry) | **Kept** — SRE-specific agent base class; ppxai provides primitives, not the agent abstraction |
| `config.py` (SRE config loader) | **Kept** — SRE-specific config (namespaces, agent schedules); uses ppxai config system as base |

**Net result:** ppxai-sre-core shrinks from ~6 modules to ~3, and the 3 that
remain are thin SRE-specific layers on top of engine primitives.

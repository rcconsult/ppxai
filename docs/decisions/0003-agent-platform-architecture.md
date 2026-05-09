# ADR 0003 — Agent platform architecture

**Date:** 2026-05-03
**Status:** Proposed (decision pending — see "Open decisions" below)
**Related:**
- [`docs/archive/TODO-v1.18.2-agent-loop-unification.md`](../archive/TODO-v1.18.2-agent-loop-unification.md) — the immediate refactor blocked on this ADR
- `ppxai/commands/agent.py` — TUI-side outer continuation loop (`handle_agent`)
- `ppxai/engine/chat.py` — `chat_with_tools` inner tool loop, AGENT_BEAT emission (lines 559, 875, 1066, 1138)
- `ppxai/engine/types.py` — `EventType.AGENT_BEAT` / `AGENT_RUN_START` / `AGENT_RUN_COMPLETE` / `AGENT_RUN_ERROR` / `AGENT_ZOMBIE` (v1.18.0)
- `vscode-extension/src/chatPanel.ts::handleAgentCommand` — VSCode-side replica of the outer loop (~150 LoC)

## Context

ppxai has agent execution today, but the design predates the
"agents-platform" use cases that are now driving the roadmap:
**sub-agents** (a parent agent spawning scoped child agents in
parallel) and **autonomous agents** (long-running, self-driving
runs that outlive any client connection).

The current shape can't support either without significant work:

### Current state (verified 2026-05-03)

```
                         ┌── chat_with_tools (engine/chat.py) ───────────┐
                         │  Inner tool loop. One chat() call.            │
                         │  Model calls tools until it stops.            │
                         │  Emits AGENT_BEAT per tool iteration.         │
                         └───────────────────────────────────────────────┘
                                              ▲
                                              │ called per iteration
              ┌────────────── handle_agent (commands/agent.py) ─────────────┐
              │  Outer continuation loop, in-process via asyncio.run.       │
              │  Builds continuation prompt; matches "TASK_COMPLETE:" in    │
              │  model output to decide whether to keep iterating.          │
              │  NOT HTTP-aware. Blocks the request handler.                │
              └─────────────────────────────────────────────────────────────┘
                          ▲                  ▲                    ▲
                          │ in-process       │ NOT used           │ replicated
                  ┌─── Rich TUI ────┐ ┌─── web (web/...) ────┐ ┌── VSCode ────┐
                  │ factory dispatch │ │ streamChat('/agent') │ │ handleAgent  │
                  │   handle_agent   │ │ → /chat (no outer    │ │ Command —    │
                  │                  │ │   loop, just gate)   │ │ ~150 LoC of  │
                  │                  │ │                      │ │ duplicated   │
                  │                  │ │                      │ │ outer loop   │
                  └──────────────────┘ └──────────────────────┘ └──────────────┘
```

What's already in place:
- AGENT_BEAT / AGENT_RUN_START / AGENT_RUN_COMPLETE / AGENT_RUN_ERROR /
  AGENT_ZOMBIE event types (v1.18.0).
- AppState has `agent_beat` field; web + VSCode + ppxaide all render it.
- `validate_agent_task` shared validator (v1.18.1) — `/chat` route
  applies it before web requests reach the engine.
- `prompt_text` SideEffectKind (v1.18.3) — auto-resume when the
  validator rejects a vague task.

What's missing:
- **Run identity.** No `run_id`. Can't address a running agent later.
- **Run persistence.** Engine restart loses everything mid-run.
- **Run registry.** No `GET /agent/runs`, can't list/inspect/replay.
- **Parent/child relationship.** No model for sub-agents.
- **Resource budgets.** Implicit `max_iterations`; no token/time caps.
- **Cancellation by run-id.** `POST /interrupt` cancels the current
  request stream, not "this specific agent run."
- **Sub-agent tool.** No `spawn_subagent` primitive.

### What sub-agents and autonomous agents actually need

The two roadmap use cases share the same architectural primitives:

| Primitive | Sub-agents need it for | Autonomous agents need it for |
|---|---|---|
| **Run identity** (`run_id`) | Parent observes children by ID | Address the run after the user's session ends |
| **Run lifecycle state** | Know when child completed | Know whether yesterday's run finished, failed, or zombied |
| **Run persistence** | In-flight children survive engine restart | Survive any restart; the whole point |
| **Run registry / index** | "list my children" | "list my runs," "list runs since X" |
| **Parent/child link** | Native | Optional but useful |
| **Resource budget** | Stop runaway children | Stop runaway autonomous runs |
| **Cancel by `run_id`** | Cancel one child without killing parent | Cancel a specific autonomous run |

Both use cases are unblocked by the same infrastructure. **Either
both work or neither does** — the agent-loop unification question
is downstream of this architectural decision, not separate.

## Decision space

### Question A — what does the outer continuation loop actually buy us?

The outer loop in `handle_agent` and VSCode's `handleAgentCommand`
sends a continuation prompt if the model's text response doesn't
contain `TASK_COMPLETE:`. It's distinct from `chat_with_tools`'s
inner tool loop:

- **Inner loop** stops when the model stops calling tools.
- **Outer loop** stops when the model either says `TASK_COMPLETE:`
  or runs out of `max_iterations`.

The outer loop was added in the GPT-3.5 era when models stopped
mid-task. Frontier models (gpt-5-mini, gpt-5.5, qwen3.5-122b)
typically tool-use through complex tasks in one chat turn. **We
don't have data on how often the outer loop actually fires usefully
on modern models.**

Three possible answers:
- **(A1)** It rarely fires usefully → eliminate it. Modern models
  finish in one turn or they don't.
- **(A2)** It sometimes fires usefully → keep it but server-side
  only.
- **(A3)** It's load-bearing → keep it AND make it
  HTTP-streaming-compatible (the original v1.18.2 plan).

**Decision input needed:** instrument `chat_with_tools` to log
how often the outer loop's `TASK_COMPLETE:` check returns false
across a week of real usage. Without that data, picking is opinion.

### Question B — where does run state live?

| Location | Pros | Cons |
|---|---|---|
| **In-memory dict** on `EngineClient` | Trivial; today's status quo | Dies on restart; no observability across sessions |
| **Filesystem** under `~/.ppxai/agent-runs/<run_id>/` | Plays well with existing convention (`sessions/`, `checkpoints/`, `usage/`); inspectable with `ls`/`cat`; append-only `events.jsonl` is robust | List/filter operations need a directory scan |
| **SQLite** under `~/.ppxai/agent-runs.db` | Indexed queries (by status, by parent, by date); atomicity; concurrent writers | New dependency surface; schema migrations |

The migration filesystem → SQLite is mechanical if we put the
write/read API behind a single class (`AgentRunRegistry`). Start
filesystem; migrate later if `list runs` becomes a bottleneck.

### Question C — sub-agent execution model

| Model | Pros | Cons |
|---|---|---|
| **Same-process asyncio.Task** | Simple; shares event loop; trivial parent/child observability | One sub-agent that hangs blocks the loop; no GIL parallelism |
| **Same-process subprocess** | Process isolation; OOM in child doesn't kill parent | Heavier; IPC overhead; child needs full ppxai environment |
| **Worker pool / queue** | Scales beyond one machine; survives engine restart of parent | Significant infra; overkill for desktop-app use case |

Same-process asyncio.Task is the right starting point for a
desktop tool. The `AgentRunRegistry` abstraction makes the
worker-pool migration trivial later.

### Question D — engine lifecycle per sub-agent

A sub-agent has its own message history, its own provider/model
choice, its own tool budget. Two ways to model this:

- **(D1)** New `EngineClient` per sub-agent run. Most flexible;
  parent and child are fully independent. But `EngineClient`
  construction needs to be cheap (verify before committing).
- **(D2)** Reuse parent's `EngineClient`, push/pop a "scope" for
  each sub-agent. Simpler concurrency story but the scope mechanism
  is new code with edge cases (mid-run scope leaks, tool calls
  attributed to wrong run).

D1 wins on isolation; pre-condition is verifying construction cost.

## Proposed architecture (v1.19.x agent platform)

```
                ┌──── AgentRunRegistry ────────────────────────────┐
                │  ~/.ppxai/agent-runs/<run_id>/                   │
                │     ├── meta.json   (task, parent, status, ...)  │
                │     ├── events.jsonl (append-only)               │
                │     ├── state.json  (iteration, budget, tools)   │
                │     └── transcript.md                            │
                │                                                  │
                │  start_run(task, parent_run_id?, budget) → run_id│
                │  list_runs(filter?) → [meta]                     │
                │  get_run(run_id) → meta + state                  │
                │  events(run_id, since?) → AsyncIterator[Event]   │
                │  cancel_run(run_id) → bool                       │
                └──────────────────────────────────────────────────┘
                                     ▲
                                     │
       ┌─── POST /command/agent ─────┴──────────── spawn_subagent tool ────┐
       │  Returns immediately:                       Engine-side built-in  │
       │   {ok, result, side_effects:                tool. Calls           │
       │    [{kind: "agent_run_started",             registry.start_run    │
       │      run_id, task}], events:[]}             with parent_run_id    │
       │  Background asyncio.create_task             = current run_id.     │
       │  drives the loop.                                                 │
       └────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
       ┌──── live SSE stream OR replay-from-events.jsonl ────────────────┐
       │  Clients (Rich, ppxaide, web, VSCode) consume the same stream.  │
       │  GET /agent/runs/<id>/events?since=<offset> for replay.         │
       │  GET /agent/runs/<id>/events?live=1         for live tail.      │
       └─────────────────────────────────────────────────────────────────┘
```

**Wire shape for runs (proposed):**

```http
POST /command/agent          → {ok, result, side_effects: [agent_run_started], events: []}
GET  /agent/runs             → {runs: [{run_id, task, status, started_at, parent_run_id?, ...}]}
GET  /agent/runs/<id>        → {meta, state}
GET  /agent/runs/<id>/events → SSE stream (live + replay; ?since=N for resume)
POST /agent/runs/<id>/cancel → {ok, status: "cancelling"}
```

**SideEffectKind additions (proposed):**

- `AGENT_RUN_STARTED` payload: `{run_id, task, parent_run_id?}` —
  the immediate reply to `POST /command/agent`. Clients render
  "🤖 run started" and subscribe to the live event stream by id.
- `AGENT_RUN_REFERENCE` payload: `{run_id}` — emitted from the
  `spawn_subagent` tool so the parent's own UI can show the child
  with a clickable link/button.

## Decision

**Recommended path forward (3 stages):**

### Stage 1 (v1.18.x or early v1.19.0) — Instrument + decide A

- Add a counter in `chat_with_tools` / `handle_agent` for "outer
  loop fired more than once" vs "completed in one inner loop."
- Surface as a usage stat in `~/.ppxai/usage/usage.json` under a
  new `agent_run_stats` key.
- Run for one week of real usage, then commit to A1, A2, or A3.

### Stage 2 (v1.19.0) — Build the run registry + background tasks

- `ppxai/engine/agent_runs.py` — `AgentRunRegistry` with the
  filesystem layout above.
- Refactor `handle_agent` so the HTTP path returns
  `agent_run_started` immediately and runs the loop as a
  background `asyncio.create_task` reading from / writing to the
  registry.
- The TUI factory path keeps its in-process `asyncio.run` for
  backward compatibility, but it ALSO writes to the registry so
  TUI users can list past runs.
- Delete VSCode's `handleAgentCommand`; route `/agent <task>`
  through `POST /command/agent` like every other command.

### Stage 3 (v1.19.x) — Sub-agent tool

- New built-in tool `spawn_subagent(task, scope_files?, budget?,
  return_mode: "summary" | "run_id")`.
- Engine-side: creates a child `EngineClient` (Decision D1) and a
  child run in the registry with `parent_run_id = current_run_id`.
- `return_mode="summary"` (default) blocks the parent tool call
  until the child completes, returns the child's final text.
- `return_mode="run_id"` returns immediately for parallel
  spawning; parent uses a separate `wait_for_subagent(run_id)`
  tool to collect.

### Out of scope for now (defer)

- Cron-driven autonomous runs (needs scheduler integration).
- Cross-machine run distribution (needs worker pool).
- Run-level RBAC / multi-user (single-user tool today).

## Open decisions

These are gaps this ADR cannot close without input or measurement:

1. **Question A** — outer-loop value. Needs instrumentation data.
2. **Question B** — filesystem vs SQLite for the registry. Recommend
   filesystem; revisit if listing runs becomes slow.
3. **Question D** — `EngineClient` construction cost. Needs a
   benchmark (`time` to spin up an EngineClient with default
   provider). If under ~50ms, D1 (per-sub-agent instance) is fine.
4. **Cancellation semantics for sub-agents** — does cancelling a
   parent cancel all children automatically, or only the parent?
   Default proposal: cascading cancel (parent cancel → mark all
   children for cancellation), with `?cascade=false` query param to
   disable.
5. **Budget enforcement** — token cap and time cap need to interrupt
   mid-tool-call cleanly. Today's `_active_subprocesses` cleanup
   (commit `a746a7c6`) is the foundation; needs extending to a
   per-run budget tracker.

## Consequences

If accepted (post-Stage-1 instrumentation):

- Agent-loop unification (`docs/archive/TODO-v1.18.2-agent-loop-unification.md`)
  is closed by Stage 2 — it's no longer a standalone refactor.
- Sub-agent tool (currently a roadmap wishlist item) becomes a
  concrete v1.19.x deliverable.
- Autonomous agent runs (long-running, client-disconnect-survivable)
  become possible in Stage 2 already; only scheduling integration
  is left for later.
- VSCode loses ~150 LoC of duplicated client-side iteration code.
- Web's `_dispatchAgent` stays as-is (already aligned).
- New persistent state on disk requires a migration policy:
  `~/.ppxai/agent-runs/` directory created on first use; old runs
  garbage-collected after N days (config knob, default 30d).

If rejected: the agent-loop-unification TODO can still proceed via
Stage 2 alone (in-memory background task without persistence), but
sub-agents and autonomous agents stay out of reach until the
registry is built.

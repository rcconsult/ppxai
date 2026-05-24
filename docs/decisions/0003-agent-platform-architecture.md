# ADR 0003 — Agent platform architecture

**Date:** 2026-05-03
**Status:** Proposed (decision pending — see "Open decisions" below)
**Related:**
- [`docs/archive/TODO-v1.18.2-agent-loop-unification.md`](../archive/TODO-v1.18.2-agent-loop-unification.md) — the immediate refactor blocked on this ADR
- `ppxai/commands/agent.py` — TUI-side outer continuation loop (`handle_agent`)
- `ppxai/engine/chat.py` — `chat_with_tools` inner tool loop, AGENT_BEAT emission (lines 559, 875, 1066, 1138)
- `ppxai/engine/types.py` — `EventType.AGENT_BEAT` / `AGENT_RUN_START` / `AGENT_RUN_COMPLETE` / `AGENT_RUN_ERROR` / `AGENT_ZOMBIE` (v1.18.0); planned v1.19.x additions: `AGENT_SERVICE_DOWN` (per §13 / caveat C5)
- `vscode-extension/src/chatPanel.ts::handleAgentCommand` — VSCode-side replica of the outer loop (~150 LoC)
- [`../../../ppxai-sre-repo/docs/PPXAI-INTEGRATION-V1.19.md`](../../../ppxai-sre-repo/docs/PPXAI-INTEGRATION-V1.19.md) — consumer-side integration plan with caveats (C1-C5) and asks (A1-A3) folded into "Open decisions" §6-§13 below
- [`../research/2026-05-10-ppxai-sre-requirements.md`](../research/2026-05-10-ppxai-sre-requirements.md) — gap analysis driving Stage 2 scope

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

These are gaps this ADR cannot close without input or measurement.
Items 1-5 are ppxai-internal; items 6-13 are consumer-driven, surfaced
2026-05-10 in [`../../../ppxai-sre-repo/docs/PPXAI-INTEGRATION-V1.19.md`](../../../ppxai-sre-repo/docs/PPXAI-INTEGRATION-V1.19.md)
(caveats C1-C5 and asks A1-A3) and need answers before Stage 2 implementation
lands. Items 6-12 (C1-C4, A1-A3) were folded in commit `42ed8f00` (2026-05-10).
Item 13 (C5 — agent-served services routing) was filed by the consumer in
peer commits `a604b0c` + `b3ba0f6` (2026-05-10) **after** `42ed8f00`, with the
C5.1-C5.5 open-shape questions surfaced via the outlook-monitor Phase-4
fit-test; folded here as a follow-on. Each carries a recommended position;
items marked LOAD-BEARING block ppxai-sre's planned features in their current
shape.

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
6. **C4 — Tools first-class on `POST /v1/agent/run`** [LOAD-BEARING].
   Without a `tools` field on the run-spawn request, ppxai-sre's
   manager-executor pattern would have to reimplement the runtime
   itself. **Recommended position:** mandatory in v1.19.x Phase 1.
   Same `tools` shape `/v1/oneshot` would accept once it grows tool
   support, so the wire surfaces stay consistent. ROADMAP Phase 1
   row to be amended.
7. **C3 — SSE on `GET /v1/agent/runs/<id>/events`**. Polling gates
   the manager-executor pattern on round-trip latency
   (`incident-responder` needs live triage commentary while the
   executor runs `kubectl describe`, Prom queries, etc.). The ADR's
   own "Wire shape for runs" section already proposes
   `GET /agent/runs/<id>/events` as SSE; this elevates that proposal
   from notional to committed. **Recommended position:** SSE channel
   in v1.19.x Phase 1; polling `GET /v1/agent/runs/<id>` stays as
   the status-snapshot path. ROADMAP Phase 1 row to be amended.
8. **C1 — Typed `EventType.NETWORK_POLICY_DENIED` /
   `NETWORK_POLICY_ALLOWED`** [LOAD-BEARING for ppxai-sre audit].
   Phase 5's network-policy primitive must emit stable typed events
   (analogous to `EventType.PROVIDER_THROTTLED`) so ppxai-sre's
   `AuditLogger` consumes them as data, not by tapping internal
   code paths. Payload shape:
   `{tool, target_host, target_path, reason, allowlist_rule_id, run_id}`.
   **Recommended position:** add to v1.19.x Phase 5 scope. ROADMAP
   Phase 5 row to be amended.
9. **C2 — `/v1/tokens` pluggable resolver from day one**
   [LOAD-BEARING for v1.20.x migration cost]. ROADMAP today says
   "`~/.ppxai/tokens.json` (single-machine) OR k8s secret (cluster)" —
   left unspecified. SRE agents deploy to k8s; the k8s-secret path
   is load-bearing. If we ship v1.19.x with a single hardcoded
   storage shape, the v1.20.x credential broker becomes a wire
   re-shape. **Recommended position:** define the resolver protocol
   in v1.19.x Phase 7 even though the credential broker proper is
   v1.20.x. Same code path supports `~/.ppxai/.env` / k8s secret /
   Vault. ROADMAP Phase 7 row to be amended.
10. **A3 — `run_id` and `parent_run_id` on `EventType.AGENT_RUN_START`**.
    Phase 1 introduces a `run_id` per run; ppxai-sre's audit JSONL
    keys by `run_id`. The native v1.18.0 `AGENT_RUN_START` payload
    predates the run namespace and doesn't carry one. **Recommended
    position:** additive fields on the existing event type, no new
    event needed. The namespace is the only new state. Fold into
    Phase 1 implementation note (no separate ROADMAP row).
11. **A1 — `EventType.CONSENT_DECISION` event stream**.
    Symmetric with C1 for non-network consent decisions. ppxai-sre's
    `AuditLogger` records every consent decision (allow/deny/
    approval_required) keyed by tool + args hash. Today the consent
    contract is per-call dialog; without an event stream they tap
    internals. Payload:
    `{tool, args_hash, decision, reason, source: user|policy, run_id}`.
    **Recommended position:** v1.19.x should-have. Cheap to add
    once the consent flow is event-emitting; cheap to defer to
    v1.20.x if Phase 5 (C1) is enough for the threat model
    ppxai-sre is shipping in v1.19.x.
12. **A2 — Pre-tool-call hook for tier classification**.
    ppxai-sre's 3-tier classification (Autonomous / Notify-and-Act /
    Require-Approval) must fire **before** ppxai's consent dialog —
    otherwise the user sees a dialog for tier-1 read-only verbs that
    should auto-approve. Two options proposed by the consumer: (a)
    `ToolEngineProtocol.pre_execute(tool_name, args) → AllowReason
    | DenyReason | DefaultConsent`, or (b) consent contract documents
    a "headless mode" where decisions come from a registered policy
    callable. **Recommended position:** option (b), defer to
    v1.20.x. Keeps the consent contract as the single boundary and
    avoids adding a parallel hook surface. Doesn't block v1.19.x;
    ppxai-sre's policy engine works without it (just renders dialogs
    that the autonomous agent auto-approves via test harness).
13. **C5 — Agent-served services routing** [LOAD-BEARING for ppxai-sre
    long-lived service agents]. Several planned ppxai-sre agents are
    not "compute and exit" — they run as long-lived services that
    ALSO bind their own HTTP endpoints for human and machine
    consumers (`incident-responder` on-call dashboard,
    `cost-optimizer` FinOps approval queue, `cert-monitor` health
    endpoint, `log-analyst` `POST /query` interface). Each agent
    must declare "I bind a UI on port X and a REST API on port Y"
    as part of its run spec; ppxai's runtime (or k8s session-manager
    in production) reverse-proxies external traffic to those
    bindings.

    **Recommended position:** v1.19.x Phase 1 extends
    `POST /v1/agent/run`'s request body with an optional `services`
    object mapping name → `{port, path, auth}`; the response carries
    a `services` map of name → externally-reachable URL of the form
    `…/v1/agent/runs/<id>/services/<name>/`. ROADMAP Phase 1 row
    amended. When `services` is omitted or empty, ppxai's runtime
    skips reverse-proxy registration (the CronJob case, where the
    agent doesn't stay up to receive inbound traffic). The bound
    service's logs / state are exposed via the **Inspection
    Triplet pattern** (per [ADR 0005](0005-inspection-triplet.md))
    at `runs/<run_id>/agent-<n>/services/<name>/{state.json, events.jsonl}`
    — the C5 ask doesn't need to invent an inspection surface.

    Five sub-question resolutions pinned by peer outlook-monitor
    Phase-4 fit-test (sharpened in peer commit `b3ba0f6`):

    - **C5.1 — Auth surface scope.** Narrow v1.19.x to
      `bearer | none`. The proposed `session` auth (cookie domain,
      CSRF, SameSite, Secure all unspecified) is deferred to v1.20.x
      alongside the OIDC work that's already deferred. One protocol
      fully specified beats three half-specified.
    - **C5.2 — Bearer auth source.** `auth: "bearer"` does NOT
      mandate the `/v1/tokens` source. Per-service field
      `token_source: "v1-tokens"` (default) or
      `token_source: "header:X-Custom-Token"` for per-deployment
      static-secret models. outlook-monitor uses the latter
      (`OUTLOOK_ADMIN_TOKEN` env var rotated via secret update); the
      Phase 7 `/v1/tokens` registry is the default but not the
      only validator.
    - **C5.3 — Inbound network policy shape.** Symmetric primitive
      on the same allowlist as Phase 5's outbound. In `meta.json`:

      ```yaml
      network:
        allow_outbound: [...]   # C1, Phase 5
        allow_inbound:          # C5
          services/dashboard: {sources: [token-role:oncall], paths: [/]}
          services/api: {sources: [token-role:slackbot], paths: [/v1/]}
      ```

      Committed in v1.19.x to avoid a v1.20.x retrofit.
    - **C5.4 — Lifecycle: restart policy + drain.** Adopt k8s
      vocabulary: `restart_policy: "Always" | "OnFailure" | "Never"`
      per service. Clean-exit drain via explicit
      `POST /v1/agent/runs/<id>/terminate` that marks the run as
      terminating before the next `AGENT_SERVICE_DOWN` fires (so
      ppxai's restart loop doesn't re-spawn an agent that intends to
      exit, e.g. outlook-monitor's `/admin/drain`). Pinned: explicit
      terminate API, not exit-code conventions.
    - **C5.5 — Reverse-proxy path semantics.** ppxai injects
      `X-Forwarded-Prefix` and the agent renders relative URLs
      assuming that prefix. Standard ASGI/WSGI middleware handles it
      on the agent side without code changes; avoids the
      double-prefix / broken-relative-URL trap.

    Plus two clarifications folded directly into the wire shape:

    - **Multi-name-same-port.** Routing key is `(port, path)`, not
      `port` alone. Outlook-monitor binds `/metrics` and `/healthz`
      on port 9090; the `services` map allows multiple name entries
      on the same port.
    - **CronJob compatibility.** `services` is optional and
      explicitly empty for CronJob runs; ppxai's runtime skips
      reverse-proxy registration when omitted.

    **Companion event type — `EventType.AGENT_SERVICE_DOWN`.**
    Symmetric with the existing `EventType.AGENT_ZOMBIE` (v1.18.0).
    Emitted by ppxai's runtime when a bound service exits or stops
    responding to liveness probes; consumers' restart policy
    (managed by ppxai per `C5.4` vs. agent-internal supervision)
    decides what happens next. Payload shape:
    `{run_id, service_name, port, reason: "exited" | "unresponsive", exit_code?}`.
    Doc-only addition to ADR 0003 until Phase 1 implementation ships;
    extends the v1.18.0 event-type list at line 9 (kept in sync there).

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

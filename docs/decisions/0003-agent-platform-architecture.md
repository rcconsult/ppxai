# ADR 0003 — Agent platform architecture

**Date:** 2026-05-03 (revised 2026-06-15 — MVP design resolved)
**Status:** Proposed. Question A (outer loop) still pending instrumentation;
**MVP design resolved 2026-06-15** — see "Resolved MVP design — read-only
research sub-agents" below. The MVP sidesteps Question A by defining a run as
a single `chat_with_tools` invocation, so Stage 2 can proceed for the
read-only research slice without waiting on the week-of-usage data.
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
| **Filesystem** under `~/.ppxai/runs/<run_id>/agent-<n>/` (the ADR 0005 Inspection Triplet path — canonical) | Plays well with existing convention (`sessions/`, `checkpoints/`, `usage/`); inspectable with `ls`/`cat`; append-only `events.jsonl` is robust | List/filter operations need a directory scan |
| **SQLite** under `~/.ppxai/agent-runs.db` | Indexed queries (by status, by parent, by date); atomicity; concurrent writers | New dependency surface; schema migrations |

The migration filesystem → SQLite is mechanical if we put the
write/read API behind a single class (`AgentRunRegistry`). Start
filesystem; migrate later if `list runs` becomes a bottleneck.

> **Forward note (2026-06-15):** this "API behind one class" instinct is
> the seed of a broader capability — a **pluggable memory/log/knowledge
> persistence channel** (JSONL / markdown / SQLite / mem0 / vector
> stores) shared across agent runs, sessions, and checkpoints, with the
> backend chosen by config. Tracked as **debt-inventory Item 35**; likely
> its own ADR once `AgentRunRegistry` ships as its first consumer.

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
                │  ~/.ppxai/runs/<run_id>/agent-<n>/  (ADR 0005)  │
                │     ├── meta.json   (task, parent, status, ...)  │
                │     ├── events.jsonl (append-only)               │
                │     ├── state.json  (iteration, budget, tools)   │
                │     ├── transcript.md                            │
                │     └── artifacts/  (run-owned, §5)              │
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

## Resolved MVP design — read-only research sub-agents (2026-06-15)

A design conversation on 2026-06-14/15 resolved the MVP scope and the
cross-cutting concerns (security, consent, results, lifecycle) that the
original "Decision space" deliberately left open. **This section is the
design of record for the first slice.** It resolves Question C
(execution model), the direction of Question D (engine lifecycle), and
open-decision item 4 (cascade cancel), and adds five dimensions the
original ADR did not cover (capability sandbox, run secret, results,
two-phase termination, config inheritance). Question A (outer loop)
stays open but is **sidestepped** by the run-unit definition below.

Guiding principle, inherited from the v1.18.8 `/files/*` parity charter:
**for any reader that may be remote or pod-sandboxed, the registry API is
the contract** — because such a reader has no shared FS with the main app,
so nothing observable about a run may be reachable *only* by reading the
filesystem.

This does **not** demote ADR 0005. Co-located / PVC-shared readers (Rich
TUI, `kubectl exec cat`, sibling ppxai-sre agents on a shared volume)
**may read the Inspection Triplet files directly** — `events.jsonl` /
`state.json` remain a first-class inspection contract per
[ADR 0005](0005-inspection-triplet.md). The rule is one of *supersetting*,
not replacement: **the registry API never exposes less than the Triplet
files do.** The API is the contract for readers that *can't* touch the FS;
the Triplet is the contract for readers that can. Same bytes, two
access paths, neither second-class — exactly ADR 0005's "the bus reads
from the filesystem, not the other way around," extended to the HTTP
adapter.

### 1. Scope — one sub-agent, full multi-ID plumbing

- The MVP spawns **at most one** sub-agent. The registry, `run_id`,
  `parent_run_id`, and every wire shape are built for **N** from day one.
- Concurrency is a single config knob `tools.agent.max_concurrent_subagents`
  (default `1`). Raising it to N is the multi-agent system; no wire change.
- **Rationale:** the ID/registry/lifecycle plumbing is the expensive,
  hard-to-retrofit part; the cap is one integer. Build the platform, ship
  it gated.

### 2. Run unit — one `chat_with_tools` invocation (this is what sidesteps Question A)

- An MVP research run = a **single inner-loop (`chat_with_tools`)
  invocation**. No outer continuation loop, no `TASK_COMPLETE:` polling.
- This **defers Question A**: a read-only research agent does not need
  outer-loop continuation semantics. Whether the *general* agent keeps the
  outer loop remains gated on Stage-1 instrumentation; the MVP does not
  block on it. When the data lands, the outer loop (if kept) wraps the
  same run unit additively.

### 3. Capability model — read-only, but fully sandboxed (read-only ≠ injection-safe)

Read-only removes write/corruption blast radius. It does **not** remove
the two threats that dominate research agents, both of which the MVP must
handle from day one:

- **Prompt injection via fetched content is the *defining* risk.** The
  agent curls a page, feeds it to the model; that page can steer the
  model to exfiltrate via the *next* network call. The network tool is
  the exfil channel — so the egress allowlist is a **ship-gate, not a
  nice-to-have: the read-only research MVP does not ship if egress
  control slips**, because prompt-injection exfiltration is the central
  threat the whole sandbox exists to contain.
- **Read scope must exclude secrets-at-rest.** A read-only agent that can
  `grep ~/.ppxai/.env` has already lost. Path-jail bounds *what it can
  read*, independent of writes.

Capability tiers, enforced at the **tool-execution boundary** (not the
agent loop), carried in `meta.json` as the run's grant:

| Tier | Mechanism | MVP |
|---|---|---|
| a. **Tool allowlist** | dispatcher denies any tool not in the run's grant (research = `web_search`, `read_file`, `grep`/`find`, read-only `curl`; no shell-write, no `write_file`) | ✅ required |
| b. **Read-path jail** | file/grep ops confined to a subtree, `~/.ppxai/` excluded; extends existing `_within_tree` + cwd-grounding | ✅ required |
| c. **Egress allowlist** | outbound network via an allowlist proxy; emits `NETWORK_POLICY_DENIED`/`_ALLOWED` (open-decision item 8 / Phase 5) | ✅ required |
| d. **OS isolation** | tool execution in a separate process (seccomp/namespaces) or **k8s pod** | deferred to untrusted/write agents |

### 4. Tool-execution boundary — subprocess/pod, not the agent runtime

The agent loop stays an in-process `asyncio.Task` (resolves **Question C
→ same-process asyncio.Task**; I/O-bound work needs no GIL escape). What
gets sandboxed is the **tool call**, not the loop:

> **Non-negotiable invariant:** *every* tool in a run's grant executes
> through the sandbox-executing adapter; **no allowed tool may keep an
> in-process fast-path.** This is the load-bearing implementation risk —
> `read_file`, `grep`/`find`, and `curl`/web all run **in-process today**,
> so the MVP must route them through the adapter or the sandbox is
> theater. The capability grant (§3) is enforced *inside* that adapter, so
> a bypass is simultaneously a sandbox escape and a grant escape.
>
> **Acceptance criterion AC-1 (named ship-gate):** an automated test
> asserts that for every tool in a run's grant, resolution goes through
> the sandbox-executing adapter and **no granted tool resolves to a
> direct in-process call**. The MVP does not ship while AC-1 fails — it
> is the test that proves the sandbox is real rather than theater. Pair
> with **AC-2:** egress for a granted network tool is denied-by-default
> and every allow/deny emits a typed `NETWORK_POLICY_*` event (§3 tier-c
> / open-decision 8).


- MVP: tools run in a **subprocess** with a restricted environment — no
  secrets in env, cwd-jailed, network via the tier-c allowlist proxy.
- Hardened/headless: reuse the existing multi-tenant **k8s session-manager
  pod** (`deploy/images/session-manager/`) — don't invent new isolation.
- The subprocess/pod is the *one* legitimate place a separate process
  earns its keep; it is invisible to the registry and the wire surface,
  which only ever see the agent run.

### 5. Results — reuse the ADR 0006 artifact contract (don't invent result types)

A run result = a **primary body** (markdown/html) + a list of
**`MarshallableArtifact` refs** (`TextAttachmentRef` / `ImageAttachmentRef`
/ `OfficeAttachmentRef` / `PdfAttachmentRef` per
[ADR 0006](0006-content-block-schema-separation.md)). The main app
resolves each ref through the **same `/files/preview` + artifact-projector
pipeline** chat attachments use (the v1.18.8 files-parity contract), so
csv/xlsx/pptx/png/code all render with zero new transport. A genuinely new
output kind = one new `ArtifactRef` subclass, never a new result channel.
Mirrors the message content-block model.

> **Artifact addressing — authority is the run, not the session
> (corrects a draft inconsistency).** Run artifacts are addressed by
> **`(run_id, artifact_id)`** and **owned by the `AgentRunRegistry`**,
> stored under the run workspace (`~/.ppxai/runs/<run_id>/agent-<n>/artifacts/`,
> the ADR 0005 Triplet path) and resolved
> *only* via `GET /v1/agent/runs/<id>/artifacts/<artifact_id>`. We **reuse
> the `SessionFileStore` content-addressing *mechanism*** (blob hashing,
> dedup) but **not its authority** — the current-session file store must
> never be the source of truth for a run artifact. This is the direct
> lesson of the v1.18.8 stale-`file_id` bugs: a session-scoped store
> cannot own something whose lifetime is a *run* (which may outlive,
> precede, or belong to a different session than the one that reads it).
> A run `artifact_id` is meaningless outside its `run_id` namespace.


### 6. Run workspace — Triplet files for co-located readers, registry API for remote

`~/.ppxai/runs/<run_id>/agent-<n>/{meta.json, state.json, events.jsonl,
transcript.md, artifacts/}` — the **ADR 0005 Inspection Triplet path**
(canonical; `agent-<n>` scopes the per-agent slot, `<n>=0` for a top-level
run, incrementing for sub-agents) — is **both** the storage layout **and**
a first-class inspection contract for co-located / PVC-shared readers (per
ADR 0005). The **registry API** (`GET /v1/agent/runs/<id>/...`) is the
contract for readers that have **no shared FS** — a pod-sandboxed tool, a
remote client. The API is a superset adapter over the same Triplet bytes
(§"Guiding principle" above): it never exposes less than the files do, and
it is the *only* path a no-shared-FS reader can use. So the main app reads
the registry API (uniform across local and pod runs); local inspection
tools may read the directory directly.

### 7. Ownership & the run secret — reuse C1 signed-bearer, don't roll crypto

At spawn the registry mints a **256-bit random run token** = the run's
ephemeral capability credential, lifetime = run lifetime, **auto-revoked
at any terminal state**. This is open-decision item 9 (`/v1/tokens`) in
minimal form: one token per run.

- **Do not invent a bespoke SHA256 handshake.** A SHA256 *hash* is not a
  key, and rolling channel crypto is a footgun. Extend the existing
  per-resource auth gate — the **v1.18.7 C1 fix** (signed token +
  `/authz` gate, fail-closed on missing/short signing key, 403 on
  ownership mismatch). A run is just another protected resource scoped by
  `run_id`.
- **Mutual auth:** the main app proves ownership (it minted the run); the
  sub-agent proves authenticity (presents the run token). The token is
  injected into the sub-agent process via **stdin/env at creation, never
  argv** (argv leaks in `ps`).
- "Prove possession before revealing data" = an **HMAC challenge–response**
  over the run token, so the secret itself is never shipped on the wire
  after the initial handout. "One-time use" applies to the *initial
  handout*, not the monitor stream (which tails repeatedly within the run).
- Same-process MVP collapses this to an ownership check; the full
  handshake matters only once the sub-agent crosses the process/pod
  boundary. The token model is additive now; the handshake lands with
  tier-d isolation.
- **`run_token` classification — it is a bearer capability, and it stays
  out of the MVP response.** Decide what it is before returning it: in the
  MVP the run_token is the **sub-agent's** credential to prove
  authenticity to the registry, handed to the sub-agent process directly
  (stdin/env). The **monitoring client never needs it** — web/VSCode
  authenticate with their existing session/bearer, and the registry
  checks **ownership** (`session owns run_id`). So `POST /v1/agent/run`
  returns **`{run_id, status}` only**; the token is internal. It surfaces
  on the wire *only* once a client orchestrates separate-process
  sub-agents, and even then the server should hand it to the sub-agent
  rather than echo it to the UI. **Never log or persist it raw** (treat
  like the C1 signing key); redact in any event/audit payload.
- **Monitor-channel authz:** the `/events`, `/result`, and `/artifacts`
  endpoints for a `run_id` are sensitive (transcript, tool output). Only
  the owning session/token may read them — the per-run version of the C1
  cross-user fix. Don't let any bearer holder read any run.

### 8. Lifecycle — TTL-gated cascade, two-phase termination, one `WAITING` state machine

**Cascade cleanup is TTL-gated, never instant-on-disconnect** —
instant-kill-on-disconnect would contradict the entire "semi-autonomous,
UI non-blocking" premise (it would make a foreground agent). Distinguish
disconnect from death:

- **Clean close** (UI exits gracefully) → explicit `cancel` → cascade
  teardown of children + tool sandboxes now.
- **Crash / vanish** → **heartbeat reaper with a grace TTL**, reusing the
  v1.18.0 heartbeat primitives + the session-manager TTL teardown (k8s
  owner-reference GC for the pod case). Within the grace window the run
  **keeps going** (autonomous, within budget). This resolves
  open-decision item 4 with a TTL gate.

**Two-phase termination — separate compute teardown from artifact
retention:**

- At self-declared done, the agent writes results, emits
  `AGENT_RESULT_READY` with artifact refs, and **the agent process dies**
  (stops consuming tokens/CPU; tool sandbox torn down). The run enters
  `COMPLETED_PENDING_ACK` — **record + artifacts persist**.
- The main app fetches/validates results, then `POST …/ack` → run →
  `FINALIZED` → GC-eligible. This gives **at-least-once result delivery**:
  if the UI was disconnected when the agent finished, results are not
  GC'd before collection. A retention TTL is the backstop (acked OR
  expired → reaped).
- The agent **does not block** waiting for ack — fire results, die, the
  *registry* holds the pending state. Blocking a live process on
  confirmation re-couples what we decoupled.

**`WAITING` is for mid-run gates only — terminal-ack is NOT a `WAITING`
variant.** A mid-run decision ("found 3 approaches, which to deep-dive?")
and a consent gate share one mechanism: the run enters `WAITING`, emits a
request tagged with `run_id`, parks with a resume token + TTL, and resumes
via `POST …/respond`. **End-of-run acknowledgement is a distinct,
canonical model** — `COMPLETED_PENDING_ACK → FINALIZED` via `POST …/ack`
(two-phase termination below). These are deliberately separate: `WAITING`
is a *live process parked mid-run* awaiting input to continue; ack is a
*dead process* whose registry record persists until the result is
collected. Conflating them (an earlier draft modeled terminal-ack as
`WAITING{terminal_ack}`) would couple result-retention to the live-process
resume path, which two-phase termination exists to avoid. One model each.

```
SPAWNING → RUNNING ⇄ WAITING{consent | input}              (mid-run, resumed via /respond)
RUNNING  → COMPLETED_PENDING_ACK → FINALIZED               (end-of-run, /ack | retention-TTL)
RUNNING  → FAILED (provider) | ZOMBIE (tool-loop) | BUDGET_EXCEEDED | CANCELLED (explicit | cascade-TTL)
any terminal → tool sandbox torn down; artifacts retained until FINALIZED/GC
```

**Consent for unattended runs (resolves the "semi-autonomous" tension):**

- **Pre-authorized scope (default).** At spawn the user grants the
  capability envelope (§3 tiers); the run executes within it with **no
  per-tool prompts**, and anything outside the envelope is a **hard deny,
  not a prompt**. The grant *is* the consent — this is what makes the run
  non-blocking.
- **Deferred consent (escape hatch).** An out-of-envelope request →
  `WAITING{consent}` → surfaced to the parent UI as a pending badge →
  resumed on async approval. Keeps human-in-loop for sensitive ops
  without making the whole run interactive.
- Headless policy (`CONSENT_DECISION` stream, pre-tool hook) stays
  v1.20.x (open-decision items 11/12).

### 9. Config inheritance — inherit infra, inject intent, default-deny capability

| Inherit (parent defaults) | Inject (explicit per spawn) | Never inherit |
|---|---|---|
| provider/model + API keys, timeouts, model-profile registry, shell-wrapper config | task definition, persona/spec, **tool allowlist**, read-path scope, budgets, system prompt, egress allowlist | parent's conversation history (fresh context), parent's **interactive consent grants** (no transitive privilege), debug/UI-only state |

- **Agent-spec is a first-class artifact** (new): persona + default tool
  grant + budget + system-prompt fragment, in one schema reused by
  interactive spawn *and* ppxai-sre.
- **API keys:** same-process child just has them (MVP-fine). When tier-d
  isolation lands, the spec carries a **token *reference*, not a raw
  key**, so the swap to per-agent identity (item 9) is non-breaking.

### 10. AppState — one running-agents summary field

Add a `background_agents` summary field to
`engine/app_state_schema.json` (auto-mirrors to web + VSCode + the
schema via the existing 4-mirror DTO; bump the sentinel counts in
`tests/test_app_state.py`). The UI shows a background-agents badge that
survives reconnects through the existing `state_sync` mechanism.

### 11. Additive wire & event surface (v1 contract stays byte-identical)

All additions are **purely additive** — `POST /v1/oneshot` and the
existing `AGENT_RUN_*` payloads are untouched (ppxai-sre constraint).

```http
POST /v1/agent/run                  → {run_id, status}   (run_token is internal — §7, never in this response for the MVP)
     body: {task, persona?, provider?, model?, tools[], read_scope?,
            budget{tokens,time_s,iterations}, network{allow_outbound[]},
            idempotency_key?}
GET  /v1/agent/runs                  → {runs:[...]}
GET  /v1/agent/runs/<id>             → {meta, state}   (status snapshot)
GET  /v1/agent/runs/<id>/events      → SSE (live + ?since=N replay)
GET  /v1/agent/runs/<id>/result      → {body, artifact_refs:[...]}
GET  /v1/agent/runs/<id>/artifacts/<artifact_id>  → resolves via /files/preview
POST /v1/agent/runs/<id>/respond     → {resume_token, response}   (answer a WAITING)
POST /v1/agent/runs/<id>/ack         → {ok, status:"finalized"}   (two-phase termination)
POST /v1/agent/runs/<id>/cancel      → {ok, status:"cancelling"}
```

- **Spawn idempotency:** client-supplied `idempotency_key` → registry
  dedup, so a retried POST never double-spawns.
- **Fan-out backpressure:** `max_concurrent_subagents` caps spawn (cf.
  the Workflow engine's `min(16, cores-2)` cap) — unbounded spawn =
  resource exhaustion + provider rate-limit storms.
- **Per-run cost attribution:** surface the existing per-`EngineClient`
  usage counter keyed by `run_id`; budget enforcement reads the same
  counter.

**New `EventType` members (additive):**

- `AGENT_RESULT_READY` — `{run_id, status, body_ref, artifact_refs[]}` —
  emitted on `COMPLETED_PENDING_ACK`.
- `AGENT_WAITING` — `{run_id, wait_kind: "consent"|"input", prompt,
  resume_token, ttl_s}`. Mid-run gates only — end-of-run uses
  `AGENT_RESULT_READY` + `/ack`, never a `WAITING` variant (§8).
- `NETWORK_POLICY_DENIED` / `NETWORK_POLICY_ALLOWED` — **MVP ship-gate,
  not Phase 5.** The read-only research MVP's egress allowlist (§3 tier-c,
  build-order step 2) is the central prompt-injection-exfiltration
  defense, so these typed events ship with the first slice. (Item 8 /
  Phase 5 is the *ppxai-sre-consumer* commitment for the same events; the
  MVP requires them earlier, not later.) `AGENT_SERVICE_DOWN` in §13.)

**New `SideEffectKind`:** `AGENT_RUN_STARTED` (already proposed above).

### MVP build order (the first slice)

1. `engine/agent_runs.py` — `AgentRunRegistry` + the state machine (§8),
   filesystem backend, in-memory live index. **Keystone.** Put
   read/write behind a narrow interface (not raw FS calls inline) so the
   pluggable-persistence-channel extraction (debt Item 35) is cheap later
   — shape the seam now, defer the abstraction.
2. Capability grant + tool-allowlist enforcement at the dispatcher (§3a/b);
   egress allowlist proxy (§3c) with `NETWORK_POLICY_*` events.
3. Background driver: `POST /v1/agent/run` mints run + (internal) token,
   starts the `asyncio.Task`, returns `{run_id, status}` immediately
   (token stays server-side — §7); `run_id`/`parent_run_id` added to the
   existing `AGENT_RUN_START` payload.
4. Monitor: `GET …/events` (live + replay), `GET …/result`,
   `GET …/artifacts/<id>` (via files-parity); per-run authz (§7).
5. Two-phase termination + `WAITING`/`respond`/`ack`; TTL reaper + cascade.
6. `spawn_subagent` tool (Stage 3) gated to `max_concurrent_subagents`;
   result returns as artifact refs.
7. AppState `background_agents` field + 4-mirror sync (§10).

Subprocess tool-execution (§4) is required for step 2's sandbox even at
N=1 — that is the deliberate "build the sandbox infra now" choice. Pod
isolation (tier d) and restart-durable persistence stay additive upgrades.

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

> **Resolved by the MVP design (2026-06-15)** — item numbers below are
> unchanged; resolutions are annotated inline. Additionally **Question C**
> (not previously a numbered item) is resolved: same-process
> `asyncio.Task` for the agent loop (I/O-bound work needs no GIL escape),
> with isolation moved to the **tool-execution** boundary
> (subprocess/pod), not the loop — see Resolved MVP design §4.

1. **Question A** — outer-loop value. Needs instrumentation data.
   **MVP-sidestepped (2026-06-15):** the read-only research run is one
   `chat_with_tools` invocation (Resolved MVP design §2), so the MVP
   ships without this data. Still open for the *general* agent.
2. **Question B** — filesystem vs SQLite for the registry. Recommend
   filesystem; revisit if listing runs becomes slow. (MVP: filesystem.)
3. **Question D** — `EngineClient` construction cost. Direction set to
   **D1** (new `EngineClient` per sub-agent run) per Resolved MVP design
   §9; still needs the benchmark (`time` to spin up an EngineClient with
   default provider). If under ~50ms, D1 is confirmed.
4. **Cancellation semantics for sub-agents — RESOLVED (2026-06-15):**
   cascading cancel, but **TTL-gated, not instant-on-disconnect** (else
   it defeats semi-autonomy). Clean close → explicit cancel now; crash →
   heartbeat reaper past a grace TTL. See Resolved MVP design §8.
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
   `NETWORK_POLICY_ALLOWED`** [LOAD-BEARING — MVP ship-gate AND ppxai-sre audit].
   **RESOLVED (2026-06-15): these ship with the read-only research MVP,
   not Phase 5.** The egress allowlist is the MVP's central
   prompt-injection-exfiltration defense (Resolved MVP design §3 tier-c,
   build-order step 2), so the typed events that audit it are part of the
   first ship gate — the registry/background-agent slice does not ship
   without them. The events emit stable payloads (analogous to
   `EventType.PROVIDER_THROTTLED`) so ppxai-sre's `AuditLogger` consumes
   them as data, not by tapping internal code paths. Payload shape:
   `{tool, target_host, target_path, reason, allowlist_rule_id, run_id}`.
   The "Phase 5" framing was the ppxai-sre-consumer commitment; the MVP
   pulls it forward. ROADMAP Phase 1 (MVP) and Phase 5 rows to be amended
   so the requirement appears in the first slice.
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
        allow_outbound: [...]   # egress allowlist — MVP ship-gate (§3 tier-c / open-decision 8)
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
  `~/.ppxai/runs/` directory created on first use; old runs
  garbage-collected after N days (config knob, default 30d).

If rejected: the agent-loop-unification TODO can still proceed via
Stage 2 alone (in-memory background task without persistence), but
sub-agents and autonomous agents stay out of reach until the
registry is built.

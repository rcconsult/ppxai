# v1.19.0 iteration — sequencing plan

**Branch:** `feature/v1.19.0` (off `master` @ a1a8cc35, post-v1.18.8)
**Created:** 2026-06-15
**Status:** Active — iteration tracker. This is the source of truth for
*what order* v1.19.x work happens in. ROADMAP.md describes the full
v1.19.x scope; this doc says what THIS iteration does first and what it
explicitly defers.

## Theme

Land **agent-platform Stage 2** (ADR 0003) — the ppxai-sre-blocking
substrate. Everything else v1.19.x-tagged is sequenced *after* it.

## Operating rules (the build contract)

Set by the user 2026-06-15. These govern HOW every increment below is
built and merged:

1. **Small, testable, always-runnable increments.** Every increment
   leaves the code runnable and **hands-on trialable right now** via the
   HTTP API (start `ppxai-server`, `curl` the endpoint) — even when the
   feature is incomplete. No increment that only "works once the next
   piece lands." Each carries tests + an explicit "How to trial" recipe.
2. **Gated progression.** Do NOT start increment N+1 until the user has
   manually trialed N **and explicitly approved**. Stop and hand off
   after each increment.
3. **Sequenced as a vertical-slice MVP.** Order is chosen so each
   increment adds *visible working capability* end-to-end (wire → engine
   → disk), not horizontal layers integrated at the end. ADR 0003's
   build order is layered; the increments below re-slice it vertically so
   increment 1 is already curl-able.
4. **Shape the seams early, grow interfaces additively.** A vertical
   slice may need a structural piece earlier than its "own" increment
   (e.g. the `AgentRunStore` Protocol seam in Inc 1, though SQLite/Item 35
   is deferred) — bring it, so the MVP is correctly shaped and we never
   retrofit a contract under existing callers. But keep each interface
   **minimal**: ship only the methods the current increment uses; later
   increments **add** methods to the same Protocol/contract. Additive
   growth is fine and expected; a breaking reshape is the thing to avoid.
   (User-confirmed 2026-06-15: "if the interfaces can be additive over
   the course of implementation I see no issue with it.")

**Trial surface:** HTTP API. Canonical loop for every increment:
`uv run ppxai-server` → `curl` the new/changed `/v1/agent/*` endpoint →
observe response + on-disk `~/.ppxai/runs/<run_id>/`.

**Per-increment deliverables (every increment ships all of these):**
1. Code + tests.
2. "How to trial" recipe (in the hand-off).
3. **Call-graph update** — add/amend the increment's section in
   [agent-platform-call-graphs.md](agent-platform-call-graphs.md) in the
   same commit. Reference map for future debugging/refactoring.

## Active this iteration — vertical-slice increments (in order)

Re-slices ROADMAP "Agent platform Stage 2" / ADR 0003 build order into
runnable steps. Each is one PR-sized increment on
`feat/agent-platform-stage-2`, gated per rule 2.

> **INCREMENT STATUS** (update as we go):
> - [x] Inc 1 — minimal run lifecycle (start/list/get, synchronous, filesystem) — merged `0f54f55d`
> - [~] Inc 2 — background execution + live status — built, awaiting trial
> - [ ] Inc 3 — events.jsonl + GET …/events (replay, then SSE)
> - [ ] Inc 4 — capability grant + tool allowlist (AC-1 sandbox seam)
> - [ ] Inc 5 — egress allowlist + NETWORK_POLICY_* (AC-2 ship-gate)
> - [ ] Inc 6 — budgets + cancel + conditional-resume checkpoint
> - [ ] Inc 7 — spawn_subagent (the N=1 sub-agent)
> - [ ] Inc 8 — /v1/tokens + per-run authz
> - [ ] Inc 9 — AppState background_agents mirror

### Inc 1 — minimal run lifecycle (synchronous, filesystem)
**Capability:** create a run, see it on disk, list it, fetch it.
**Build:** `engine/agent_runs.py::AgentRunRegistry` (start_run / get_run /
list_runs writing `~/.ppxai/runs/<run_id>/agent-0/{meta.json}`);
`server/routes/agent_v1.py` with `POST /v1/agent/run` (runs the task
**synchronously** for now, writes meta, returns `{run_id, status}`),
`GET /v1/agent/runs`, `GET /v1/agent/runs/<id>`. Mirror `oneshot.py`.
**Trial:** `curl -XPOST …/v1/agent/run -d '{"task":"say hi","tools":[]}'`
→ `{run_id}`; `curl …/v1/agent/runs` lists it; `cat
~/.ppxai/runs/<id>/agent-0/meta.json`.
**Tests:** registry round-trip; route 200 + run appears in list.
**Deliberately NOT yet:** background exec, events, sandbox, budgets.
(Synchronous means the POST blocks till done — fine for trial; Inc 2
makes it async.)

### Inc 2 — background execution + live status — DONE
**Capability:** POST returns immediately; run executes in the background;
status transitions running → completed/failed visible via GET.
**Built (as shipped):** `AgentRunRegistry.run_in_background` =
`asyncio.create_task` driver with strong-ref tracking; `started_at`
persisted on `RunMeta` (in `meta.json`) — a **separate `state.json` was
NOT introduced** (deferred to Inc 3/6 when there's iteration/checkpoint
state to hold). Status subset: pending→running→completed/failed. The
immediate reply returns `{run_id, status:"running"}`.
**Note (corrected 2026-06-15):** an earlier draft of this entry said
"`state.json` + `AGENT_RUN_STARTED` side-effect." Neither shipped in Inc 2
as written: started_at lives on `RunMeta`, and the whole-run engine event
is the existing native `AGENT_RUN_START` (no -ED; `AGENT_RUN_STARTED` is a
*SideEffectKind* in ADR 0003 §11, a separate concept reserved for the
immediate POST reply, not yet emitted). Inc 3 added the real `events.jsonl`
emission (`agent_run_start`/`_complete`/`_error` run-event types).
**Trial:** POST returns instantly with `status:"running"`; poll
`GET …/runs/<id>` → watch it flip to `completed`. ✅ verified in-browser.

### Inc 3 — events + monitor channel
**Capability:** see what the run did, live, with verbosity/severity filtering.
**Build:** append-only `events.jsonl` with the **level + category** record
schema (ADR 0003 §11a — both axes from the first persisted event);
`AgentRunStore.append_event`/`read_events` (additive Protocol growth);
`GET …/runs/<id>/events?since=N` (replay) then `?live=1` (SSE, mirror
existing streaming); `?min_level=` + `?category=` filters applied on both
replay and live tail. **Always persist all events; filter on read.**
**Trial:** `curl -N …/runs/<id>/events?live=1` while a run executes;
`?min_level=warning` to confirm filtering. Web client upgrades from
polling to the SSE tail (verbosity slider + category toggles).

### Inc 4 — capability grant + tool allowlist (sandbox seam, AC-1)
**Capability:** a run can only call tools in its grant; others hard-deny.
**Build:** grant in `meta.json`; enforcement at the tool dispatcher; the
named **AC-1** test (no granted tool resolves to a direct in-process
call — route through the adapter seam). Subprocess execution may start as
a thin shim here.
**Trial:** POST a run granting only `read_file`; confirm a `write_file`
attempt is denied in events.

### Inc 5 — egress allowlist + NETWORK_POLICY_* (ship-gate, AC-2)
**Capability:** outbound network is deny-by-default; allow/deny audited.
**Build:** `engine/tools/network_policy.py`; `NETWORK_POLICY_DENIED/_ALLOWED`
events; `network.allow_outbound` in the run spec.
**Trial:** run with an empty allowlist + a network tool → see DENIED event.

### Inc 6 — budgets + cancel + conditional-resume checkpoint
**Capability:** runs stop at caps / on cancel; interrupted runs checkpoint.
**Build:** `meta.json` budgets enforced at `chat_with_tools`;
`POST …/cancel`; `INTERRUPTED` + the resumability flag in `state.json`
(conditional-resume per ADR #5 — resume logic itself can be the additive
follow-up, but the checkpoint + flag land here).
**Trial:** set a 1-iteration budget → run halts; cancel a running run.

### Inc 7 — spawn_subagent (N=1)
**Capability:** a run spawns one child run; parent collects its result.
**Build:** `spawn_subagent` tool (consent-gated), `parent_run_id`,
`max_concurrent_subagents=1`; child writes artifacts; parent reads result.
**Trial:** a task that spawns one research sub-agent; inspect both runs.

### Inc 8 — /v1/tokens + per-run authz
**Capability:** only the owning session/token may read a run's monitor
channels.
**Build:** `/v1/tokens` CRUD (pluggable resolver), per-run authz on
`/events` `/result` `/artifacts` (the C1 cross-user fix, per-run scoped).
**Trial:** a foreign token gets 403 on someone else's run.

### Inc 9 — AppState background_agents mirror
**Capability:** UIs show a background-agents badge that survives reconnect.
**Build:** `background_agents` field in `app_state_schema.json` + 4-mirror
sync + sentinel test bumps.
**Trial:** start a run, see the badge in web/VSCode; reconnect, still there.

---

Original layered phase list (ADR 0003 build order) kept below for
traceability; the increments above are the runnable re-slicing of it.

1. **Phase 1 — ADR 0003 Stage 2 primitives** (`feat/agent-platform-stage-2`)
   `engine/agent_runs.py` `AgentRunRegistry` (keystone) + the
   `~/.ppxai/runs/<run_id>/agent-<n>/` namespace; `POST /v1/agent/run`,
   `GET /v1/agent/runs[/<id>]`, `/events` SSE, `/cancel`, `/terminate`;
   `run_id`/`parent_run_id` on `AGENT_RUN_START`; `AGENT_SERVICE_DOWN`.
   ~7-9 d.
2. **Phase 2 — sub-agent primitive** (`spawn_subagent`, consent-gated).
   ~3-4 d.
3. **Phase 3 — run persistence + recovery** (`state.json` checkpoint;
   *conditional* resume on restart). Pairs with ADR 0003 open-decision #5
   (RESOLVED 2026-06-15: checkpoint unconditionally, resume conditionally
   — only if the checkpoint is conclusive AND artifacts don't already
   capture the work; else stays `INTERRUPTED`). Needs a
   resumability/conclusiveness flag in `state.json`. ~2-3 d.
4. **Phase 4 — resource budgets** (`meta.json` token/time/iter caps
   enforced at `chat_with_tools`). ~2 d.
5. **Phase 5 — network policy enforcement** (per-run egress allowlist,
   fail-closed, typed `NETWORK_POLICY_*` events). MVP ship-gate per ADR
   0003 §3 tier-c. ~4-6 d. (`feat/network-policy-enforcement`)
6. **Phase 7 — `/v1/tokens` registry** (should-have; pluggable resolver
   from day one). ~4-6 d. (`feat/v1-tokens-registry`)

### Design decisions (all RESOLVED 2026-06-15 — no open blockers)

- **Q-A (ADR #1, outer loop): A1 — eliminate it.** A run is one
  `chat_with_tools` invocation; no outer continuation loop, no
  `TASK_COMPLETE:` marker. Accepted the small risk (a weak model stopping
  mid-task) for one-loop simplicity. Deletes the ~150 LoC VSCode replica.
  Revisit A2 (server-side re-prompt) only if a specific model regresses —
  not speculatively.
- **Q-D (ADR #3, EngineClient lifecycle): D1 — new EngineClient per
  sub-agent.** Isolation first; optimize later only if profiling shows
  construction is a real bottleneck under fan-out. No benchmark gate.
- **ADR #5 (budget interrupt): conditional resume.** Checkpoint
  unconditionally; resume only if conclusive + work not already in
  artifacts (see Phase 3).

## Deferred — AFTER Stage 2 lands (NOT this iteration's active set)

User decision 2026-06-15:

- **debt Item 3 (k8s session-manager FULL test suite)** — quick-pass DONE
  + merged. Full suite waits until the sub-agent pod sandbox (Phase 1-2)
  exists, so the tests validate the actual sub-agent-in-a-pod security
  boundary end-to-end, not the session-manager in isolation. = ROADMAP
  Phase 6.
- **debt Item 21 (`chat_with_tools` decomposition)** — postponed. Stage 2
  adds run/budget/sub-agent code into this exact function; decompose after
  the shape settles, not before.
- **ROADMAP track B — Anthropic Provider** — deferred; do after Stage 2.
  `feat/anthropic-provider` stays reserved.
- **ROADMAP track C — Prompt Analyzer + Adaptive Routing** — deferred;
  already "(Future)". After Stage 2.

## Deferred to v1.20.x (unchanged from ROADMAP)

Credential broker, `CONSENT_DECISION` event (A1), pre-tool-call hook
(A2), native-provider `oneshot()` parity, rate limiting, OIDC/JWT,
streaming `/v1/oneshot`.

## Also v1.19.x-tagged but independent of Stage 2 (schedule opportunistically)

- **debt Item 29** — `engine.completion` layer inversion (ADR 0007).
  ~1-1.5 d, seam already seeded.
- **debt Item 33** — command-layer `console.print` sweep.
- **debt Item 34** — add `python-docx` to `[data]` extra (small).
- **debt Item 35** — pluggable persistence channel (likely ADR 0008);
  `AgentRunRegistry` from Phase 1 is its first consumer, so it naturally
  follows Phase 1.

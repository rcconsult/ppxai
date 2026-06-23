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
> - [x] Inc 2 — background execution + live status — trialed + committed
> - [x] Inc 3 — events.jsonl + GET …/events (replay + SSE) — trialed + committed
> - [x] Inc 4 — capability grant + tool allowlist (AC-1 sandbox seam) — trialed + committed (`acee4821`)
> - [x] Inc 5 — egress allowlist + NETWORK_POLICY_* (AC-2 ship-gate) — **trial-verified** (`3519e919`): live deny/allow/fail-closed + shell-reject on nvidia Nemotron
> - [x] Inc 6 — budgets + cancel + conditional-resume checkpoint — **trial-verified** (`cc0d75a1`): iteration→interrupted, cancel→cancelled, 409 on terminal (token-budget by test only)
> - [x] Inc 7 — spawn_subagent (the N=1 sub-agent) — **trial-verified** (`cc0d75a1`+fixes): live spawn, parent/child link via `parent_run_id`, result collection, subset rules. Requires `tools.agent.spawn_consent="auto"` for API-driven spawns.
> - [x] Inc 8 — /v1/tokens + per-run authz (pluggable secret sources; reads scoped to the run's owner) — committed + live-trial-verified
> - [x] Inc 9 — AppState background_agents mirror — committed + live-trial-verified
>
> All nine increments are committed and live-trial-verified, plus post-Inc-9 hardening §A–§K (see [agent-platform-call-graphs.md](agent-platform-call-graphs.md)). Next: interactive sub-agent UX design.
>
> **Trial-found fixes (2026-06-16), all committed:** `18373e31` v1 tier 400 lists eligible OpenAI-compatible providers (native openai/gemini/perplexity rejected); `227ea6f8` spawn consent policy + visible `spawn_denied` events (was silent auto-deny); `b4923bd3` surface `spawn_consent` through `get_agent_config` whitelist; `0a336645` ship `spawn_consent:"deny"` default. Plus Inc 5 ×4 + Inc 6/7 ×3 codex/copilot review rounds, all resolved.

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
**Capability:** a tool-capable run can only call tools in its grant;
others hard-deny.

**Tier separation (design 2026-06-15):** tool-calling is a *categorically
different* safety tier from the tool-free `/v1/oneshot`/`/v1/agent/run`
path (which is safe *because* it has no tools — no sandbox needed). So
Inc 4 adds a **separate endpoint** rather than bolting tools onto the safe
path:
- `POST /v1/agent/run` — UNCHANGED. Tool-free tier (oneshot), no sandbox.
- `POST /v1/agent/task` — NEW. Tool-capable, sandboxed tier: requires a
  capability grant, executes via `chat_with_tools`, enforces the
  allowlist. Locks the two tiers at the URL level so they can't be
  conflated. Shares the same run registry / events / monitor infra
  (`/agentruns`, `/events`, status all work identically).

**Build:** `ScopedToolManager(base, grant)` — a per-run filtered view:
the model is offered ONLY granted tools (filtered `get_tools_openai_format`
/ `get_tools_prompt`), and `execute_tool` hard-denies any off-grant name
(+ emits a `tool_denied` warning/tool event) as the backstop — the model
can't call what it can't see, and the chokepoint catches the rest. `task`
route runs `chat_with_tools` with the scoped manager. The named **AC-1**
test: a granted tool resolves only via the scoped view, never a direct
ToolManager fast-path. (OS-level subprocess isolation is tier-d, a later
increment; Inc 4 is the in-process allowlist seam.)

**Trial:** `POST /v1/agent/task` granting only `read_file`; confirm a
`write_file` attempt is denied and surfaces as a `tool_denied` event on
the run's `/events` stream.

### Inc 5 — egress allowlist + NETWORK_POLICY_* (ship-gate, AC-2)
**Capability:** outbound network is deny-by-default; allow/deny audited.
**Build:** `engine/tools/network_policy.py` (`NetworkPolicy.check(url)`
per-URL primitive + `authorize(name, kwargs)` whole-call decision, both
fail-closed); `NETWORK_POLICY_ALLOWED/_DENIED` events on the `network`
category; `network.allow_outbound` in the `/v1/agent/task` spec, persisted on
`RunMeta.network`. Enforced at the **same `ScopedToolManager.execute_tool`
chokepoint as AC-1** — grant check first, then (for a network-capable tool:
`fetch_url`/`web_search`/`get_weather`) `authorize` before the request fires.

**Policy spec (resolved 2026-06-15):**
- `allow_outbound` entries: a bare host string (exact, any path) OR
  `{host, paths?}`. Host may be `*.suffix` (single-label, suffix-anchored
  glob — `*.wikipedia.org` matches `en.wikipedia.org`, NOT
  `wikipedia.org.evil.com` and NOT `a.b.wikipedia.org`). `paths` is a list
  of prefixes; absent = any path.
- **Fail-closed:** empty/absent allowlist denies all outbound; an
  unresolvable target denies; https-only (http denied) for the MVP.
- **No shell tool (resolved 2026-06-16, security review High):** a shell tool
  (`execute_shell_command`) runs arbitrary commands (`curl`, `pip`,
  `Invoke-WebRequest`, …) whose egress the host/path allowlist cannot inspect,
  so it would bypass the chokepoint entirely. Only the deferred OS-isolation
  tier (ADR 0003 §3 tier-d) can contain it. A `/v1/agent/task` grant
  containing a shell tool is therefore **rejected with a 400** up front, and
  `ScopedToolManager` refuses to run it whenever an egress policy is active
  (defense-in-depth). This matches ADR §3a (research grant = "no shell").
- **Superset rule (resolved 2026-06-16, fixes a security review High/Medium):**
  a tool's real egress host is often chosen at CALL time and unpredictable
  before the call. `web_search` dispatches to a premium backend with a
  Perplexity→Gemini→DuckDuckGo fallback, so its egress set is
  `{duckduckgo.com, html.duckduckgo.com, api.perplexity.ai,
  generativelanguage.googleapis.com}`; `get_weather` falls back https→http.
  `authorize` therefore allows a tool only if **EVERY** URL it could reach
  passes `check()`. Consequence: allowlisting only DuckDuckGo does NOT permit
  `web_search` (it could reach Perplexity) — it's denied before the call; and
  `get_weather` is un-allowlistable under the MVP (its http-fallback branch
  fails https-only) until that fallback is removed. This closes the
  confused-deputy gap where a run could exfiltrate through an unallowlisted
  backend and the audit event would name the wrong host.
- Event payload (stable for ppxai-sre AuditLogger):
  `{tool, target_host, target_path, reason, allowlist_rule_id, run_id}`;
  `allowlist_rule_id` = matched rule index (allow) or `null` (deny).

**Trial:** `POST /v1/agent/task` with `tools:["fetch_url"]` and
`network.allow_outbound:["api.github.com"]`, task = fetch an off-allowlist
URL → `network_policy_denied` on `…/events?category=network`, the fetch never
fires; a fetch of api.github.com → `network_policy_allowed`. Empty
`allow_outbound` denies even the granted tool.

### Inc 6 — budgets + cancel + conditional-resume checkpoint
**Capability:** runs stop at caps / on cancel; the stop is recorded as a
non-failure terminal state that a future resume could pick up.
**Build (as implemented 2026-06-16):**
- `RunControl` (engine/agent_runs.py): per-run cooperative control the
  registry owns while a run is in flight. The runner calls `check(now=…)`
  at each tool-loop boundary; it raises `RunCancelled` / `RunBudgetExceeded`.
- `BudgetSpec` on `AgentTaskRequest` — `{iterations?, time_s?, tokens?}`,
  any subset; absent axis = uncapped. Persisted to `RunMeta.budget`.
  **Cooperative, not `task.cancel()`** — a stop lands at a clean checkpoint,
  never mid-tool-call (which could leave a half-written artifact). All three
  axes are LIVE-enforced: `iterations` counted at each tool-loop boundary,
  `time_s` from a monotonic clock, `tokens` refreshed from the run's
  `engine.session.usage.total_tokens` (the EngineClient is run-local per D1,
  so its cumulative total IS this run's) before each `check()`.
- `POST /v1/agent/runs/<id>/cancel` → flips the control flag, moves the run
  to `cancelling`; the runner observes it next boundary and stops. 404
  unknown / 409 already-terminal.
- New terminal statuses: `cancelled` (owner cancel, resumable) and
  `interrupted` (budget hit, resumable), distinct from `failed`. `RunMeta.
  resumable` flag set accordingly (the conditional-resume seam per ADR #5;
  resume *logic* is the additive follow-up — the flag + checkpoint land here).
- Budget check is "allow N, stop at N+1": `check()` runs BEFORE counting the
  iteration, so a budget of N permits exactly N iterations.
- Run-lifecycle events: `agent_run_cancelling` / `agent_run_cancelled` /
  `agent_run_interrupted` on the `lifecycle` channel (free-form RunEvent
  strings — not engine `EventType` enum, so no stream-handler change).
**Trial:** (a) `budget:{iterations:2}` on a task that would loop more → run
ends `interrupted`, `resumable:true`, exactly 2 `tool_call` events; (b) start
a longer run, `POST …/cancel` → run ends `cancelled`, `resumable:true`;
(c) cancel a finished run → 409.

### Inc 7 — spawn_subagent (N=1)
**Capability:** a run spawns one child run; parent collects its result.
**Build (as implemented 2026-06-16):**
- `engine/tools/agent_spawn.py::SpawnSubagentTool` (a `BaseTool`), registered
  on a run's EngineClient ONLY when (a) `spawn_subagent` is in the grant AND
  (b) the run is top-level (`allow_spawn=True`). Bound to the parent's
  run_id + grant + allowlist + provider/model.
- The `/task` runner was extracted to a shared `build_task_runner(...)` used
  by both top-level runs and child runs, so a child goes through the
  IDENTICAL sandbox (ScopedToolManager AC-1 + NetworkPolicy AC-2 + Inc 6
  budget/cancel).
- **Security (keeps AC-1/AC-2 transitive):**
  - *child grant ⊆ parent grant* — off-parent tool → spawn refused (no
    escalation); a child may never carry a shell tool either.
  - *child egress ⊆ parent allowlist* — each child host must resolve ALLOW
    under the parent's own `NetworkPolicy`; off-parent host → refused.
  - *depth = 1, structural* — the child runner is built `allow_spawn=False`,
    so it never receives the tool; a grandchild is impossible (not a runtime
    flag the model can probe).
  - *N = 1 concurrent* — the parent's tool call awaits the child to terminal
    before returning, so one parent drives at most one child.
  - *consent-gated* — spawning is gated by `tools.agent.spawn_consent`:
    **"deny" (default, safe)** refuses a spawn that needs consent (over
    /v1/agent/task there is NO interactive channel, so deny = no spawn);
    **"auto"** lets API-driven spawns proceed with the subset rules as the
    boundary. (Trial-found 2026-06-16: a per-run EngineClient has no consent
    callback, so the old unconditional gate auto-denied every server spawn
    SILENTLY and the model fell back — now refusals emit a `spawn_denied`
    event and "auto" makes spawn usable. Proper AGENT_WAITING/respond flow,
    ADR §8, supersedes this later.)
- Every refusal (grant/egress/consent) emits a **`spawn_denied`** event —
  no silent refusal (the observability gap that made the trial bug hard to
  see).
- Child is a **first-class run** with its own run_id + `parent_run_id`
  linkage (NOT nested under the parent's dir via agent_n — that ADR 0005
  refinement is later; nesting here caused a get_run slot mismatch, fixed).
- Parent stream gets `subagent_spawned` (lifecycle) + `subagent_finished`
  (result) events.
**Trial (thorough, after 6+7):** FIRST set `tools.agent.spawn_consent="auto"`
in ppxai-config.json (else server spawns are denied — by design). Grant a
parent `["spawn_subagent"]` (omit read_file so the model MUST delegate);
its task spawns a child with `tools:["read_file"]` → both runs appear in
`/v1/agent/runs` (child has `parent_run_id`), parent result embeds child
result, parent stream shows `subagent_spawned`/`subagent_finished`. Negatives
(each emits `spawn_denied`, mints no child): child requesting `["write_file"]`
(off-parent) → refused; off-parent egress host → refused; with
spawn_consent="deny" → refused. Confirm a child can't itself spawn (no
`spawn_subagent` offered to it).

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

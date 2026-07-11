# Agent platform — endpoint call graphs (per increment)

**Purpose:** a reference map of what each `/v1/agent/*` endpoint actually
calls, traced from code, maintained **per increment**. Use it for
debugging (where does this path go?), refactoring (what depends on this
seam?), and onboarding (the shape of the agent platform at a glance).

**Maintenance rule:** every increment that adds or changes an endpoint
updates this doc in the same commit. Graphs are append-/amend-only per
increment section so the historical shape stays traceable (mirrors the
ADR-governance "factual-reality corrections" discipline). Source of truth
is the code; if a graph and the code disagree, the code wins — fix the
graph.

- **Plan / increments:** [plan-v1.19.0-sequencing.md](plan-v1.19.0-sequencing.md)
- **Design:** [decisions/0003-agent-platform-architecture.md](decisions/0003-agent-platform-architecture.md)
- **Triplet path:** [decisions/0005-inspection-triplet.md](decisions/0005-inspection-triplet.md)

## The shared two-layer seam (stable across all increments)

Every endpoint funnels through the same layering. Increments thicken the
leaves; this spine does not change.

```
   route handler (server/routes/agent_v1.py)   ← HTTP, Pydantic wire models
        │  get_agent_run_registry()            (server/state.py, lazy singleton)
        ▼
   AgentRunRegistry (engine/agent_runs.py)     ← service: identity, lifecycle, queries
        │  self._store.<method>
        ▼
   AgentRunStore  (Protocol)                   ← swappable seam (debt Item 35)
        │  implemented by
        ▼
   FilesystemAgentRunStore                     ← ALL disk I/O lives here
        ▼
   ~/.ppxai/runs/<run_id>/agent-<n>/...        ← ADR 0005 Inspection Triplet path
```

Invariants this seam enforces (check these when refactoring):
- **No route handler ever touches `Path` / `open()` directly** — all
  persistence goes through `AgentRunStore`. The Item 35 backend swap
  replaces exactly `FilesystemAgentRunStore` and nothing above it.
- **The registry depends on the Protocol, not the concrete store.**

---

## Increment 1 — minimal run lifecycle (synchronous)

Added: `engine/agent_runs.py`, `server/routes/agent_v1.py`,
`get_agent_run_registry()` in `server/state.py`.
Execution model: **synchronous** — `POST /v1/agent/run` blocks on the LLM
call before returning.

### `POST /v1/agent/run` — create + execute synchronously

```
create_agent_run(req)                                  [routes/agent_v1.py]
├─ get_agent_run_registry()                            [server/state.py]
│   └─ (first call) AgentRunRegistry(FilesystemAgentRunStore(PPXAI_HOME/"runs"))
├─ req.provider or get_default_provider()              [config/providers.py]  → 400 if none
├─ req.model    or get_default_model(provider)         [config/providers.py]  → 400 if none
├─ registry.start_run(task, tools, provider, model)   [engine/agent_runs.py]
│   ├─ _new_run_id()                          → secrets.token_hex → "run_<hex>"
│   ├─ RunMeta(status="pending", created_at=time.time())
│   └─ store.persist_meta(meta)               [FilesystemAgentRunStore]
│       └─ mkdir runs/<id>/agent-0/ ; write meta.json atomically (tmp + os.replace)
├─ _build_provider(provider_name)                      [routes/oneshot.py]  ← reused
│   └─ create_provider(...) → OpenAICompatibleProvider [engine/providers/]
├─ if not OpenAICompatibleProvider:
│   └─ registry.finish_run(meta, status="failed", error=...) → HTTPException 400
└─ try:
    ├─ provider.oneshot(prompt=task, model, system)   [providers/openai_compat.py]
    │   └─ ← THE LLM CALL (blocking — the reason Inc 1 is synchronous)
    ├─ registry.finish_run(meta, "completed", result=content)  → store.persist_meta
    └─ except: registry.finish_run(meta, "failed", error=str(e)) → store.persist_meta
   → AgentRunResponse(run_id, status)
```

The **only leaf that leaves the process** is `provider.oneshot()`.
Everything else is registry → store → disk. (Inc 2 wraps the
start_run → oneshot → finish_run segment in `asyncio.create_task` so the
POST returns immediately; the registry/store contract is untouched.)

### `GET /v1/agent/runs` — list

```
list_agent_runs()                                      [routes/agent_v1.py]
├─ get_agent_run_registry()
├─ registry.list_runs()                                [engine/agent_runs.py]
│   └─ store.list_meta()                       [FilesystemAgentRunStore]
│       ├─ iterdir() over ~/.ppxai/runs/
│       ├─ load_meta(name, agent_n=0) per dir → RunMeta.from_dict(json)
│       │     (corrupt/missing → logged + skipped, not fatal)
│       └─ sort by created_at desc
└─ [RunMetaResponse.from_meta(m) ...]          → RunListResponse
```

### `GET /v1/agent/runs/{run_id}` — fetch one

```
get_agent_run(run_id)                                  [routes/agent_v1.py]
├─ get_agent_run_registry()
├─ registry.get_run(run_id)                            [engine/agent_runs.py]
│   └─ store.load_meta(run_id)                 [FilesystemAgentRunStore]
│       └─ read runs/<id>/agent-0/meta.json → RunMeta.from_dict  (None if absent)
└─ if None → HTTPException 404 ; else RunMetaResponse.from_meta(meta)
```

### Inc-1 store surface (the `AgentRunStore` Protocol so far)

```
persist_meta(meta)            create/overwrite meta.json (atomic)
load_meta(run_id, agent_n=0)  read one slot's meta, or None
list_meta()                   all top-level (agent-0) metas, newest-first
```

Later increments ADD to this Protocol (no reshape):
`append_event` / `read_events` (Inc 3), `save_state` / `load_state`
(Inc 2-3), sub-agent slot enumeration (Inc 7).

---

## Increment 2 — background execution + live status

Changed: `engine/agent_runs.py` (added `run_in_background` + `_tasks` set +
`RunMeta.started_at`), `server/routes/agent_v1.py` (POST no longer awaits
the LLM call). **Execution model change: synchronous → background.** GET
endpoints unchanged (they already read from the store; now they observe
`running` mid-flight). Store Protocol unchanged this increment.

### `POST /v1/agent/run` — create + execute in background

```
create_agent_run(req)                                  [routes/agent_v1.py]
├─ get_agent_run_registry()
├─ provider/model resolution (PER-RUN INTENT, ADR 0003 §9):
│   req.provider/model  →  tools.agent.default_subagent (config)  →  400
│   (the interactive session's chat provider is NOT consulted — a
│    sub-agent's model is chosen for its task. Per-session sub-agent
│    config is a middle layer, debt Item 36.)   [config/tools.py]
├─ _build_provider(provider_name)                      [routes/oneshot.py]
│   └─ → 400 (no run created) if unknown / not OpenAICompatibleProvider
│       ↑ carve-out now runs BEFORE minting (Inc 1 minted-then-failed)
├─ registry.start_run(...)                  → RunMeta(status="pending"), persist
├─ registry.run_in_background(meta, _runner)           [engine/agent_runs.py]
│   ├─ meta.status="running"; meta.started_at=now; store.persist_meta
│   ├─ task = asyncio.create_task(_drive())   ; self._tasks.add(task)
│   │   └─ _drive(): await _runner(meta)
│   │        ├─ ok  → finish_run("completed", result=body) → persist
│   │        └─ exc → finish_run("failed", error=str) → persist
│   └─ task.add_done_callback(self._tasks.discard)
│       (_runner = asyncio.to_thread(provider.oneshot, ...) — blocking
│        call runs off the event loop so GET polls aren't starved)
└─ return AgentRunResponse(run_id, status="running")   ← INSTANT, no await
```

The POST returns while `_drive` runs concurrently. The run's terminal
state is observed by polling `GET /v1/agent/runs/<id>` (below, unchanged).
`self._tasks` holds a strong ref so the loop doesn't GC the in-flight
task; the done-callback removes it. Cancel-by-id + shutdown drain = Inc 6.

### `GET /v1/agent/runs` / `GET /v1/agent/runs/{run_id}`

Unchanged from Inc 1 (registry → store → disk). They now return
`status:"running"` for an in-flight run and the terminal status once
`_drive` has called `finish_run`. `started_at` is populated once
background execution begins.

### Web client surface (consumer of the above — no new endpoints)

Added alongside Inc 2 so the live `running → completed` status is
trialable in-app, not just via curl.

```
chat input "/agentrun <task>"            [web/app.js sendMessage]
└─ handleSlashCommand → commandDispatcher.dispatch()  [command-dispatcher.js]
   └─ cmd === "/agentrun" → _dispatchAgentRun(task)
      ├─ apiClient.post("/v1/agent/run", {task, tools:[]})   → {run_id, status:"running"}
      ├─ showSystemMessage("🤖 <run_id> — running…")
      └─ poll loop (600ms, ≤2min):
           apiClient.get("/v1/agent/runs/<id>")
             completed → showSystemMessage("✅ …") + addMessage("assistant", result)
             failed    → showSystemMessage("❌ … <error>")
             (else keep polling; run continues server-side regardless)

chat input "/agentruns"
└─ _dispatchAgentRunsList()
   └─ apiClient.get("/v1/agent/runs") → render newest-20 as a system line
```

Served from `~/.ppxai/web/` (NOT the repo) by default — see static.py
`WEB_UI_DIR`. **Since v1.19.0** you no longer have to copy files there to trial
edits: set `PPXAI_WEB_DIR=$PWD/ppxai/web` and any launcher (`uv run
ppxai-server`, desktop) serves the checkout live (`_resolve_web_ui_dir`).

---

## Increment 3 — events + monitor channel

Added: `RunEvent` dataclass + `LEVELS`/`CATEGORIES` + `emit_event` /
`read_events` / `subscribe` / `unsubscribe` on the registry;
`append_event` / `read_events` on the store Protocol + Filesystem impl;
`GET /v1/agent/runs/<id>/events` route. Background driver now emits
lifecycle/result events. Store Protocol grew (additive).

### emit path (during a run)

```
registry.emit_event(run_id, type, level=, category=, data=)  [agent_runs.py]
├─ seed self._seq[run_id] from persisted max on first emit (restart-safe)
├─ seq = ++self._seq[run_id]
├─ RunEvent(seq, ts, type, level, category, data)
├─ store.append_event(run_id, event)        [FilesystemAgentRunStore]
│   └─ append one JSON line to runs/<id>/agent-0/events.jsonl
└─ fan out: for q in self._subscribers[run_id]: q.put_nowait(event)
            on QueueFull (slow consumer): set q._ppxai_overflowed = True
            — NEVER block the emitter, NEVER silently drop. The event is
            on disk; the SSE generator self-heals (see below). Disk is the
            source of truth; the queue is a fast-path notifier.

emitters (Inc 3): run_in_background._drive →
  agent_run_start (info/lifecycle), agent_run_complete (info/result),
  agent_run_error (error/lifecycle)
```

### `GET /v1/agent/runs/{run_id}/events` — replay + live tail

```
get_agent_run_events(run_id, since, live, min_level, category)  [routes/agent_v1.py]
├─ registry.get_run(run_id)  → 404 if unknown
├─ cats = parse ?category=    (comma-separated set)
├─ if not live:  read_events(since, min_level, cats) → {"events": [...]}  ← JSON replay
│   (non-live reads the backlog directly — no queue, no race)
└─ if live:  StreamingResponse(_sse(), text/event-stream)
     _sse():
       q = registry.subscribe(run_id)       ← SUBSCRIBE FIRST (lost-event fix):
       backlog = read_events(since, ...)     ← THEN snapshot, so an event in the
                                               window lands in q, not lost
       yield each backlog event as "data: {json}\n\n"  (advances last_seq)
       loop:
         if request.is_disconnected(): break
         if q._ppxai_overflowed:             ← slow-consumer self-heal
           clear flag; replay read_events(since=last_seq) from disk; continue
           (no silent gap — durable log fills what the queue dropped)
         ev = await q.get() (15s timeout → ": keepalive")
         skip if ev.seq <= last_seq or not ev.passes(min_level, cats)
         advance last_seq; yield "data: {json}\n\n"
       finally: registry.unsubscribe(run_id, q)   (runs on disconnect)
```

Filters (`min_level` + `category`, ADR 0003 §11a) apply on BOTH the
replay backlog and the live tail. Always-persist / filter-on-read: the
file has everything; the endpoint subsets it.

### Web client (Inc 3 upgrade)

`/agentrun` switches from poll-loop to the SSE tail: after POST, open
`GET …/events?live=1` and render frames as they arrive; close on the
terminal `agent_run_complete`/`agent_run_error` event. (Verbosity slider +
category toggles are a follow-up UI refinement.)

---

## Increment 4 — capability grant + tool allowlist (sandbox seam, AC-1)

Added: `engine/agent_scoped_tools.py` (`ScopedToolManager`); new
`POST /v1/agent/task` route (tool-capable tier). `/v1/agent/run` unchanged
(tool-free tier). **Tier separation at the URL** — tool-calling is a
distinct safety tier from the safe tool-free path; the two never mix.

### `POST /v1/agent/task` — tool-capable, allowlist-enforced run

```
create_agent_task(req)                                 [routes/agent_v1.py]
├─ grant required + non-empty (pydantic min_length=1 → 422 otherwise)
├─ provider/model: request → tools.agent.default_subagent → 400
├─ _v1_provider_or_400 = _build_provider only (400 on unknown/no-key).
│    v1.19.x: provider-AGNOSTIC — no OpenAI-compat class guard; any
│    BaseProvider works (engine.chat is abstract on all). [post-Inc-9 §A]
├─ registry.start_run(task, tools=grant, owner=caller, ...) → RunMeta(running)
└─ registry.run_in_background(meta, _runner):
     _runner(m):
       engine = EngineClient(); set_provider/model; enable_tools()  [ADR §9 D1]
       engine.system_prompt_override = compose_agent_system_prompt(req.system)
                                ← v1.19.x bounded-agent framing + caller's
                                  AGENT.md; replaces provider chat prompt
                                  so the model uses GRANTED tools, not native
                                  fallback. [post-Inc-9 §B]
       engine.tool_manager = ScopedToolManager(engine.tool_manager,
                                grant, on_deny=emit tool_denied)
       async for ev in engine.chat(task):    ← chat_with_tools loop
         (provider's non-streaming SDK call runs via asyncio.to_thread so
          this run never starves the event loop — [post-Inc-9 §C])
         TOOL_CALL  → control.check() [budget/cancel] → emit_event(tool_call)
         STREAM_END → capture final text → run result
```

### AC-1 enforcement (ScopedToolManager)  [engine/agent_scoped_tools.py]

```
Two layers, both required:

1. OFFERED set filtered to the grant (model never SEES off-grant tools):
   get_tools_openai_format / get_available_tools / list_tools / get_tool /
   get_tools_prompt → only names in grant. (get_tools_prompt is the
   prompt-based / native-fallback path — it re-renders the base prompt BOUND
   to the scoped manager so it enumerates only granted tools. v1.19.x: the
   shell-wrapper context is gated AT THE SOURCE via
   get_tools_prompt(include_wrapper_context=has_shell_grant) — never emitted
   for a no-shell grant — instead of emitted-then-substring-stripped. Part
   of AC-1. [post-Inc-9 §D])

2. execute_tool CHOKEPOINT (the AC-1 + AC-2 invariants — backstop):
   execute_tool(name, **kw):
     name not in grant → on_deny(name)  [emit tool_denied warning/tool]
                        → return model-readable "not permitted" (NO raise,
                          loop continues; tool did NOT run)
     name in SHELL_TOOL_NAMES AND network_policy set:   ← AC-2 shell backstop
        → on_network(False, …) [emit network_policy_denied]
        → return "not permitted" (shell escapes egress; route 400s it up front,
          this is defense-in-depth; NEVER runs)
     name in grant AND is_network_tool(name) AND network_policy set:   ← AC-2
        network_policy.authorize(name, kw):   ← SUPERSET rule over ALL targets
            targets = tool_targets(name, kw)  [fetch_url→[url kwarg];
              web_search→[ddg, html.ddg, api.perplexity.ai,
                          generativelanguage.googleapis.com] (call-time
                          backend + fallback chain — ALL possible);
              get_weather→[https://wttr.in, http://wttr.in] (https+fallback)]
            allowed IFF every target passes check()  (else first failing
              target is the deny reason — e.g. web_search with only ddg
              allowlisted → DENY on api.perplexity.ai)
          deny → on_network(False, payload) [emit network_policy_denied]
               → return model-readable "network access denied" (request
                 NEVER fired; fail-closed)
          allow→ on_network(True, payload)  [emit network_policy_allowed]
     name in grant (passed both) → base.execute_tool(name)  ← only path to real tool

   AC-1 test: an off-grant call never reaches base.execute_tool
   (test_ac1_off_grant_tool_never_reaches_base +
    test_task_enforces_grant_end_to_end).
   AC-2 test: an off-allowlist network target never reaches base.execute_tool
   (test_ac2_denied_target_never_runs_and_emits_denied +
    test_task_enforces_egress_end_to_end).

All other attributes delegate to the base manager (__getattr__) so
chat_with_tools treats it as a normal manager with a smaller toolset.
```

`/v1/agent/run` stays the tool-free tier: its `tools` field is recorded
for provenance but never executed (oneshot has no tool loop). Tools are
only *enforced and executed* via `/task`.

---

## Increment 5 — egress allowlist + NETWORK_POLICY_* (AC-2 ship-gate)

Added: `engine/tools/network_policy.py`. Changed: `agent_scoped_tools.py`
(egress chokepoint), `routes/agent_v1.py` (`network` field + on_network),
`agent_runs.py` (`RunMeta.network`), `types.py` (two EventTypes).

Execution model: no new endpoint. A tool-capable run ALWAYS gets a
`NetworkPolicy` installed (even with no `network` spec → empty → fail-closed),
so a granted network tool is deny-by-default.

### POST /v1/agent/task — egress wiring (delta over Inc 4)

```
create_agent_task(req: AgentTaskRequest{..., network?{allow_outbound[]}})
  grant_has_shell(req.tools)?  → 400  (shell escapes egress; tier-d only — AC-2)
  registry.start_run(..., network=req.network.allow_outbound)  → RunMeta.network persisted
  _runner(m):
    net_policy = NetworkPolicy(req.network.allow_outbound or [])   ← empty = fail-closed
    on_network(allowed, payload):
        emit network_policy_allowed|denied  (category=network,
            info|warning, data={...payload, run_id})
    engine.tool_manager = ScopedToolManager(base, grant,
        on_deny=…, network_policy=net_policy, on_network=on_network)
    async for ev in engine.chat(task):   ← egress enforced inside execute_tool
```

### NetworkPolicy  [engine/tools/network_policy.py]

```
NetworkPolicy(allow_outbound[]) → normalized [_Rule(host, paths, rule_id)]

check(url) -> Allow(rule_id) | Deny(reason):   ← per-URL primitive
   no url                        → Deny  (unresolvable target; fail-closed)
   scheme != "https"             → Deny  (https-only; bare/empty scheme also
                                          rejected — v1.19.x [post-Inc-9 §F])
   for rule in rules:
     rule.matches_host(host):           exact, or "*.suffix" single-label,
                                        suffix-anchored (blocks lookalikes)
        rule.matches_path(path) is False → Deny(path not in prefixes)
        _host_resolves_to_blocked_ip(host) → Deny  ← SSRF guard: an allowlisted
           name that resolves to loopback/private/link-local/reserved is
           blocked (incl. 169.254.169.254). DNS lookup runs ONLY after the
           host+path match; resolution failure does NOT block. Does NOT cover
           DNS-rebinding TOCTOU (→ tier-d). [post-Inc-9 §F]
        else → Allow(rule_id)
   no rule matched               → Deny(host not in allowlist)
empty rules                      → Deny everything (fail-closed)

authorize(name, kwargs) -> ToolDecision:      ← the chokepoint decision
   targets = tool_targets(name, kwargs)        every URL the call COULD reach
   no targets                    → Deny  (unresolvable; fail-closed)
   ALL targets pass check()      → Allow (superset rule — see below)
   any target fails check()      → Deny  (reports the first failing target)
   ToolDecision.approved_targets = ALL allowlisted hosts (the full superset,
     not just targets[0]) → surfaced in the network_policy_allowed audit
     event so a multi-backend tool's log shows every approved host. [§G]

Superset rule (AC-2): web_search's backend is chosen at call time with a
Perplexity→Gemini→DDG fallback, so its egress set is the UNION of all of
them; the run must allowlist EVERY one or web_search is denied — it can't
reach an unallowlisted backend by taking a branch we didn't predict. Same
for get_weather's https→http fallback (the http branch is denied under the
MVP https-only rule, so wttr.in alone can't authorize get_weather).
```

## Increment 6 — budgets + cancel + conditional-resume checkpoint

Added/changed: `engine/agent_runs.py` (RunControl + RunStopped hierarchy +
cancel_run/get_control + status mapping), `routes/agent_v1.py` (BudgetSpec,
budget wiring, POST …/cancel). Execution model: cooperative stop — the run
is NOT task.cancel()'d; it stops at the next tool-loop checkpoint.

### control lifecycle (registry)  [engine/agent_runs.py]

```
run_in_background(meta, runner):
  meta.status = running
  control = RunControl(run_id, budget=meta.budget, started_at=monotonic())
  self._controls[run_id] = control      ← findable by cancel_run
  self._run_tasks[run_id] = task
  _drive():
    try: body = await runner(meta) → finish_run(completed)
    except RunStopped as s:               ← RunCancelled | RunBudgetExceeded
        finish_run(status=s.status, error=s.reason, resumable=s.resumable)
        emit agent_run_<status> (lifecycle, warning)
    except Exception: finish_run(failed)
    finally: pop control + task

cancel_run(run_id):  → _cancel_run_cascade(run_id, seen=set())
  control = self._controls.get(run_id)    ← None if not in flight → False
  control.cancel_requested = True
  meta.status = cancelling; emit agent_run_cancelling; _notify_change()
  CASCADE: for each in-flight run with parent_run_id == run_id →
     _cancel_run_cascade(child)   ← cancelling a parent never orphans a
     sub-agent (recursion-safe via `seen`, cycle-guarded). [post-Inc-9 §E]
```

### POST /v1/agent/task — budget/cancel polling (delta over Inc 5)

```
start_run(..., budget=_budget_dict(req.budget))  → RunMeta.budget persisted
_runner(m):
  control = registry.get_control(m.run_id)
  async for ev in engine.chat(task):
    ev == TOOL_CALL:
       control.check(now=monotonic())   ← raises RunCancelled/RunBudgetExceeded
          cancel_requested              → RunCancelled  (status cancelled)
          iterations >= budget.iterations → RunBudgetExceeded (interrupted)
          elapsed   >= budget.time_s    → RunBudgetExceeded
          tokens    >= budget.tokens    → RunBudgetExceeded
       control.iterations += 1          ← count AFTER check (allow N, stop N+1)
```

### POST /v1/agent/runs/<id>/cancel

```
cancel_agent_run(run_id):
  meta = get_run(run_id)               none → 404
  registry.cancel_run(run_id)          in-flight → flip flag, 200 cancelling
                                       terminal  → 409 not cancellable
```

## Increment 7 — spawn_subagent (N=1 sub-agent)

Added: `engine/tools/agent_spawn.py`. Changed: `routes/agent_v1.py`
(extracted `build_task_runner`, shared by /task + child runs; registers the
spawn tool for top-level granted runs). Execution model: a parent run's tool
call mints + runs ONE child run (own run_id, linked by parent_run_id) and
blocks on it.

### tool registration (depth gate)  [routes/agent_v1.py build_task_runner]

```
build_task_runner(registry, ..., tools, allow_outbound, allow_spawn):
  _runner(m):
    engine.enable_tools()
    if allow_spawn AND "spawn_subagent" in tools:      ← only top-level + granted
        engine.tool_manager.register_tool(SpawnSubagentTool(
            registry, parent_run_id=m.run_id,
            parent_owner=m.owner,                       ← child inherits owner (8b)
            parent_tools=tools, parent_allow_outbound=allow_outbound,
            parent_provider, parent_model, request_consent, consent_policy))
    engine.tool_manager = ScopedToolManager(...)        ← AC-1/AC-2 wrap as usual
  # child runs are built allow_spawn=False -> tool NEVER registered -> depth=1
```

### SpawnSubagentTool.execute  [engine/tools/agent_spawn.py]

```
execute(task, tools=[], allow_outbound=[]):
  1. _check_grant_subset(child_tools):
       shell in child            → _deny(grant)   (AC-2)
       child_tools ⊄ parent_tools→ _deny(grant)   (no escalation)
  2. _check_egress_subset(child_allow):
       any child (host,path) not Allow under parent_policy → _deny(egress)
  3. consent gate (policy = tools.agent.spawn_consent):
       "auto"            → skip prompt (subset rules ARE the boundary)
       "deny" + no chan  → _deny(consent)   ← server context, no human to ask
       "deny" + channel  → request_consent(summary) False → _deny(consent)
  4. child = registry.start_run(task, tools=child_tools,
              network=child_allow, parent_run_id=parent_run_id,
              owner=parent_owner)              ← own run_id; inherits owner (8b)
     emit subagent_spawned (parent stream, lifecycle)
  5. runner = build_task_runner(..., allow_spawn=False)   ← child can't spawn
     registry.run_in_background(child, runner)
  6. status,body,err = await _await_child(child.run_id, child.budget)
        awaits registry.get_run_task(child) directly (no disk-poll);  ← N=1
        ALSO polls parent_control.cancel_requested on a ~100ms tick → if the
        PARENT is cancelled while awaiting, cancels the child promptly
        (not after wait_cap). [post-Inc-9 §E]
        wait cap = child time_s + margin, else 300s; on timeout CANCELS
        the child (never orphaned)
     emit subagent_finished (parent stream, result)
     return "[sub-agent <id> completed]\n<body>"  (or ended:<status>)

_deny(reason, kind): emits spawn_denied event (consent kind → category
  consent, else lifecycle) AND returns the model-readable Error. NO refusal
  is silent — every refusal both mints NO child AND leaves a stream trace.
Consent policy default "deny": over /v1/agent/task there is no interactive
  consent channel, so spawn is refused unless tools.agent.spawn_consent="auto"
  (subset rules still gate). Proper AGENT_WAITING/respond flow (ADR §8)
  supersedes this later.
```

## Increment 8a — pluggable secret-source framework (`/v1/tokens`)

Added: `server/secrets/{base,env,file,chain,__init__}.py`,
`routes/tokens_v1.py`, `state.get_secret_provider()`. Changed:
`server/auth.py` now resolves via the provider chain (was a single
env-var compare). No execution-model change to agent runs; this is the
credential layer that Inc 8b's per-run authz will consume.

The seam (ADR 0003 §C2): one `SecretProvider` Protocol, many backends,
consumers blind to which.

```
auth_middleware (http.py)
  -> auth.check_request(request)                  # exemptions checked IN ORDER:
       1. not is_auth_enabled()      -> proceed   # no provider enforces a token
            -> is_auth_enabled(): a MINT-capable (file) provider enforces by
               mere presence (empty store => still 401, not open); env enforces
               only when its var is set. [post-Inc-9 §H]
       2. method == OPTIONS          -> proceed   # CORS preflight (no auth hdr)
       3. loopback POST /v1/tokens w/ mutable store -> proceed  # bootstrap mint
            (NOT gated on the store being empty — repeat local mints deliberate)
       4. loopback UI/static/chat    -> proceed   # local browser carries no
            bearer; EXEMPT iff path NOT under (/v1/agent, /v1/tokens) — the
            sensitive API stays protected even from loopback. Remote NEVER
            exempt. [post-Inc-9 §H]
       5. chain.resolve(bearer)                   # first provider to match wins
            -> EnvSecretProvider.resolve()        #   PPXAI_API_TOKEN compare (read-only)
            -> FileSecretProvider.resolve()       #   salted-SHA256 verify vs tokens.json
          None  -> 401 JSONResponse
          match -> request.state.principal = TokenRecord  # owner stashed (8b) -> proceed
```

### `GET /v1/tokens` — list token metadata (never material)

```
list_tokens()
  -> get_secret_provider().list()               # concatenate list-capable providers
       (CapabilityError => 405)                  # read-only-only chain (env/k8s)
  -> [TokenMeta(...)]                            # token_id/owner/roles/expires_at/revoked/source
```

### `POST /v1/tokens` — mint (material returned ONCE)

```
mint_token(MintTokenRequest{owner, roles, ttl_s})
  -> get_secret_provider().mint(owner, roles, ttl_s)
       -> _first_with(CAP_MINT)                  # routes to file; env/k8s lack it
            -> FileSecretProvider.mint()         # 256-bit material; store salted hash
       (CapabilityError => 405 | ValueError => 422)
  -> MintTokenResponse{token=material, meta}     # material echoed once, never logged/persisted raw
```

### `DELETE /v1/tokens/{token_id}` — revoke

```
revoke_token(token_id)
  -> get_secret_provider().revoke(token_id)      # every revoke-capable provider
       (CapabilityError => 405)
       (False => 404)
  -> {ok, token_id, revoked}
```

Config: `server.secrets.providers` (omit => single env provider =
legacy behavior). Backward-compat: `test_auth_middleware.py` unchanged
and green; no `server.secrets` block behaves exactly as v1.18.3.

## Increment 8b — per-run authorization (owner-scoped)

Added: `RunMeta.owner` (additive field), `start_run(owner=)`,
`agent_v1._caller_owner()` / `_authorize_run_access()`. Changed: the four
per-run routes enforce ownership. No execution-model change.

Rule: auth disabled => no scoping (runs unowned, all reads allowed,
loopback UX). Auth enabled => run stamped with creator's owner; a read is
allowed iff `caller.owner == run.owner`; an unowned run (pre-8b /
sub-agent) is readable by any authenticated caller.

```
# create — stamp owner from the middleware-set principal
POST /v1/agent/run  | /v1/agent/task
  -> _caller_owner(request)               # request.state.principal.owner (or None)
  -> registry.start_run(..., owner=<owner>)   # RunMeta.owner persisted

# read/cancel — enforce owner
GET  /v1/agent/runs/<id>                   \
GET  /v1/agent/runs/<id>/events             >  -> registry.get_run(id) (404 if none)
POST /v1/agent/runs/<id>/cancel            /      -> _authorize_run_access(request, meta)
                                                       caller=None            -> allow (auth off)
                                                       meta.owner=None        -> allow (unowned)
                                                       meta.owner==caller     -> allow
                                                       else                   -> 403

# list — filter to caller
GET  /v1/agent/runs
  -> registry.list_runs()
  -> if caller: keep m where m.owner in (None, caller)   # no cross-owner enumeration
```

Tests: `test_agent_run_authz.py` (owner stamping, 403 on foreign token for
meta/events/cancel, 401 missing, 404 unknown, unowned-readable, list
scoping, auth-disabled no-scoping).

## Increment 9 — AppState `background_agents` mirror

Added: schema field `background_agents` (array), `SSE_SYNC_FIELDS` entry,
`AgentRunRegistry.active_summary()` / `on_change()` / `_notify_change()`,
`SessionManager.broadcast_background_agents()`. Changed: registry fires the
hook on run start / terminal / cancelling; `state.get_agent_run_registry()`
registers the AppState-mirror hook; `GET /state` recomputes the field live.
No execution-model change. The server-global registry is per-session
AppState's source for the badge.

```
# push on change (run start / finish / cancelling)
registry._notify_change()
  -> mirror hook (registered in get_agent_run_registry)
       -> SessionManager.broadcast_background_agents(registry.active_summary())
            -> for each engine (default + sessions):
                 engine.state.set("background_agents", summary)   # AppState
                   -> existing state_sync SSE -> connected clients

# reconnect (authoritative, survives a missed push)
GET /state
  -> snapshot of SSE_SYNC_FIELDS
  -> payload["background_agents"] = registry.active_summary()  # live recompute

active_summary(): list_runs() (newest-first) minus terminal statuses,
projected to {run_id, status, task, owner} — never result/error/events.
```

Clients are schema-driven (web via window.APP_STATE_SCHEMA, VSCode via the
bundled copy synced by scripts/sync-schema.js), so they pick up the field
with no hand-edits; a badge widget is a thin client-side follow-up.

Tests: test_background_agents_mirror.py (active_summary filtering/projection/
ordering, on_change fire + bad-listener isolation, schema+SSE membership).
Sentinels bumped: AppState fields 21→22, schema fields 21→22, SSE_SYNC
12→13.

## Post-Inc-9 hardening (review + benchmark fixes, 2026-06-16)

Fixes that landed AFTER Inc 9, from review rounds + the agent-behavior
benchmark. The inline `[post-Inc-9 §X]` tags above point here. These change
call flow without adding endpoints; debt Item 37 a–j tracks the residue.

**§A — v1 tier is provider-agnostic.** `_v1_provider_or_400` is now just
`_build_provider` (400 only on unknown/no-key). The old
`isinstance(provider, OpenAICompatibleProvider)` guard on `/run` + `/task` +
`/v1/oneshot` is gone. `oneshot()` is now `@abstractmethod` on `BaseProvider`,
implemented on all 4 providers (native ones compose their existing
`chat_sync_simple` + per-vendor usage parser). `/task` uses `engine.chat`
(abstract on all); `/run` + `/v1/oneshot` use `oneshot`. Any configured
provider works. (commits 18373e31←removed, cbb8c536)

**§B — agent system-prompt framing.** `EngineClient.system_prompt_override`
(per-engine, D1-isolated) is read by chat.py's prompt-based AND native
assembly paths, REPLACING the provider's chat `system_prompt` when set.
`/task` sets it to `compose_agent_system_prompt(req.system)` =
`DEFAULT_AGENT_SYSTEM_PROMPT` ("use ONLY granted tools; no native fallback")
+ caller's `system` (e.g. ppxai-sre's rendered AGENT.md). Also: the
"you have native web search, you do NOT need a tool" block in
`_build_prompt_based_messages` is SUPPRESSED when the override is active (it
caused the Perplexity substitution). Persona/AGENT.md ownership stays with
the consumer; ppxai provides the seam + default. Live-verified across all 4
providers (benchmarks/agent-behavior). (commit b7ddd424)

**§C — non-streaming provider call off-loaded.** Every provider's `chat`
non-streaming branch (+ openai responses API) wrapped its SYNCHRONOUS SDK
call in `await asyncio.to_thread(...)`. `/task` uses `stream=False`, so
before this one agent run starved the asyncio event loop (server
unresponsive to ALL requests until the LLM call returned). LLM calls are
I/O-bound → to_thread releases the GIL during the socket wait → concurrent
runs interleave. Proven: independent request returns 0.46s mid-run (was:
timeout). Streaming `/chat` path NOT changed (small-burst starvation,
deferred). `oneshot` is already offloaded at its `/run` call site.
(commit baacfef0)

**§D — shell-wrapper prompt gated at source.** `ToolManager.get_tools_prompt`
takes `include_wrapper_context`; `ScopedToolManager` passes `has_shell_grant`,
so the "## Shell wrapper context" block is never EMITTED for a no-shell
grant — replacing the old `_strip_section` substring-parse (which coupled the
AC-1 filter to markdown formatting). `_strip_section` deleted. (commit a8e7247d)

**§E — cancel cascades + prompt parent-cancel.** `cancel_run` →
`_cancel_run_cascade`: cancelling a run also cancels any in-flight run with
`parent_run_id == it` (recursion-safe, cycle-guarded) — a parent cancel
never orphans a sub-agent. Plus `_await_child` polls the parent's
`cancel_requested` on a ~100ms tick so a parent cancel propagates to the
awaited child promptly (not after the 300s wait cap). Deferred: cancel
DURING a provider HTTP call still waits for it to return (→ tier-d).
(commits 4b1459bb, e0f725c2)

**§F — egress SSRF guard + scheme tightening.** `check()` rejects bare/empty
scheme (https-only) and denies an allowlisted host that resolves to a
loopback/private/link-local/reserved IP (`_host_resolves_to_blocked_ip`,
incl. the 169.254.169.254 metadata endpoint). DNS lookup runs only after the
host+path match; resolution failure does not block. Does NOT cover
DNS-rebinding TOCTOU — that needs network-layer enforcement (tier-d).
(commit a8e7247d)

**§G — full egress audit targets.** `ToolDecision.approved_targets` carries
ALL allowlisted hosts (the superset), surfaced in `network_policy_allowed`,
so a multi-backend tool's audit shows every approved host, not just the
first. `target_host`/`target_path` keep the first for back-compat (additive
key). (commit e0f725c2)

**Sub-agent owner inheritance (Inc 8b completion).** `SpawnSubagentTool`
takes `parent_owner` and passes `owner=parent_owner` to `start_run`, so a
child run inherits the parent's owner (not `owner=None` = world-readable).
This also fixed a latent crash: `build_task_runner` was already passing
`parent_owner=` to a constructor that didn't accept it. (commit 71022ad5)

**§H — loopback UI auth exemption (surfaced live, web app 401'd).** With a
file token store configured, auth is enforced — but the browser web/desktop
client carries NO bearer, so opening `127.0.0.1:54320` returned 401 and the
UI couldn't even load. `check_request` now exempts loopback requests to the
UI/static/chat surface (allowlist-by-exclusion: loopback AND path NOT under
`/v1/agent` or `/v1/tokens`). Same trust basis as the loopback mint
exemption — a local browser is physically on the host. The sensitive v1
surface (agent run monitor channels — owner-scoped; token mgmt) stays
protected EVEN from loopback; remote requests are never exempt. Also
clarifies the empty-store policy: a mint-capable provider enforces auth by
its mere presence (an empty store is 401, not open). Verified on the
installed binary: `/` + `/state` → 200, `/v1/agent/runs` + `/v1/tokens`
GET → 401, remote UI → 401. (commit aa989cef)

**§I — oneshot native web search (Option A, opt-in).** `_build_provider`
(the shared construction site for `/v1/oneshot` AND `/v1/agent/run`) now reads
`tools.web_search.oneshot_grounding` (default OFF) and, when on, switches a
SEARCH-CAPABLE provider into the PROVIDER'S OWN web search before return
(`_apply_oneshot_grounding`). Option A, not B: retrieval stays INSIDE the
provider API call — no `web_search`/`fetch_url` tool is exposed to the model,
so the egress perimeter is unchanged and `NetworkPolicy` (the `/task`-only
firewall) is NOT involved. Capability-gated: no-op for OpenAI/NVIDIA
(`web_search:false`). Both tool-free tiers pick it up from one site
(`agent_v1._v1_provider_or_400` delegates to `_build_provider`).

```
POST /v1/oneshot | POST /v1/agent/run
  -> _build_provider(name)                         [routes/oneshot.py]
       -> create_provider(...)                     # unchanged
       -> if _oneshot_grounding_enabled():         # tools.web_search.oneshot_grounding
            _apply_oneshot_grounding(provider, name)
              -> get_provider_config(name).capabilities.web_search ? continue : return  # gate
              -> if hasattr(provider,"enable_grounding"): provider.enable_grounding=True # Gemini
                 # Perplexity: sonar* searches intrinsically — nothing to flip
  -> provider.oneshot(...)                          # grounded call, citations in content
```

Tests: `test_oneshot_grounding.py` (flag plumbing, capability gate, build
wiring, + an AST perimeter-lock test that fails if a web-tool symbol is ever
referenced in oneshot CODE — drift fence against Option B). Docs:
`docs/api-gateway.md` Notes, `docs/plan-oneshot-grounding.md`.

**§J — `/v1/agent/run` loopback carve-out (refines §H).** §H protected the
WHOLE `/v1/agent` prefix on loopback, which broke the web `/agentrun` command
(its only agent verb POSTs `/v1/agent/run` — the tool-free oneshot tier — and
the browser carries no bearer). Fix: two scoped, fail-closed loopback
exemptions UNDER the protected prefix, so the safe tier works while the
dangerous/observability surface stays bearer-gated even locally:

```
check_request (auth enforced, loopback)
  -> _is_loopback_ui_request:
       path == "/v1/agent/run"                          -> EXEMPT  (tool-free oneshot tier)
       GET /v1/agent/runs/<id>[/events] AND run UNOWNED -> EXEMPT  (_is_loopback_unowned_run_read)
                                                                    # owner==None ⇒ a run the
                                                                    # token-less browser created
       else under /v1/agent or /v1/tokens               -> PROTECTED (401 without bearer)
```

Why scoped reads: the web `/agentrun` tails `…/events` and reads `…/<id>`.
Those are exempt ONLY for an UNOWNED run (the kind a token-less local client
creates via the exempt POST). An OWNED run — every `/task` run, every run
created WITH a bearer — stays protected, so a local process can never read
another owner's (or a tool-capable) run's transcript+tool-output. `/task`,
list, cancel, and unknown-run reads all still 401. Remote never exempt.
Verified live (rebuilt server): web launch→tail→read all succeed token-less;
`/task`+`/runs`+`/cancel`+ghost-read all 401. Tests: 14 new in
`test_tokens_v1_route.py::TestLoopbackUIExemption`.

**§K — web `/agentrun` fire-and-forget (web client only).** `/agentrun`
previously AWAITED its own SSE tail inline, blocking the chat prompt until the
run completed — defeating the background run registry. `_dispatchAgentRun` now
launches, prints `🤖 run_xxx — running… (chat stays usable…)`, and RETURNS
immediately; the tail+result-post runs detached in `_watchAgentRunDetached`
(not awaited). Result appends out-of-band when the run finishes; the
background_agents badge (§Inc 9) shows it running meanwhile.

```
chat input "/agentrun <task>"               [web/shared/command-dispatcher.js]
  -> _dispatchAgentRun(task)
       -> apiClient.post("/v1/agent/run",{task,tools:[]})  -> {run_id}
       -> showSystemMessage("🤖 … running…")
       -> this._watchAgentRunDetached(runId)   # FIRE-AND-FORGET (no await) → prompt freed
  (detached) _watchAgentRunDetached(runId)
       -> for await ev of _tailRunEvents(runId): break on agent_run_(complete|error)
       -> get /v1/agent/runs/<id> → append result as assistant message
```

NO server change (server already backgrounds runs). DEPLOYMENT NOTE: web JS is
bundled into the `ppxai-desktop` binary (`ppxai-desktop.spec` datas
`('ppxai/web','ppxai/web')`) and the launcher RESTORES it to `~/.ppxai/web/` on
every start — so a web-asset change requires rebuilding `ppxai-desktop`, not
just copying into `~/.ppxai/web/` (that gets reverted on next launch). Tests:
`test_web_command_dispatcher_v18_1.py::TestAgentRunFireAndForget` (drift fences:
no inline `for await`; watcher started un-awaited) + size fence 300→340 with
documented reason. Verified live: prompt usable mid-run (`ls`/`/pwd` ran while
a run was active; `✅ completed` posted out-of-band).

**§L — Gemini review fixes (2026-06-17).** Four issues from an external review,
all verified against the code first (one proposed fix was empirically worse and
replaced):

- **#4 loopback exemption ignored a provided bearer (regression from §J).**
  `check_request` returned early on a loopback exemption WITHOUT resolving an
  Authorization header if present — so a local script that authenticated had its
  token dropped and its run stamped `owner=None` (lost isolation/traceability).
  Fix: compute `has_bearer` up front; apply the bootstrap-mint + loopback-UI
  exemptions ONLY when no bearer was presented. A present-but-invalid bearer
  falls through to 401 (never silently exempted). Tests:
  `TestLoopbackHonorsProvidedBearer`.
- **#1 sync DNS on the event loop (SSRF guard).** `_host_resolves_to_blocked_ip`
  calls `socket.getaddrinfo`; it ran inline in `ScopedToolManager._check_network`
  on every network tool call. The obvious fix (offload via `asyncio.to_thread` /
  `loop.getaddrinfo`) was MEASURED to be ~4× slower here (2.4s vs ~ms) and wedged
  the egress test past its poll timeout — so instead the lookup is MEMOIZED with
  a 30s TTL (`_resolve_cache` in network_policy): repeated checks for the same
  host do zero DNS, amortizing the loop-block concern to near-nothing while
  staying fast. Failures aren't cached (retry next call). Tests:
  `TestSsrfGuard::test_resolution_memoized_within_ttl` + failure/literal cases.
- **#2 `active_summary()` O(N) disk scan per lifecycle event.** It called
  `list_runs()` (read+parse meta.json for EVERY historical run) on every run
  start/finish/cancel — growing unboundedly. Fix: an in-memory `_active` index
  `{run_id: summary}` maintained at each state transition (pending/running/
  cancelling → upsert; terminal → remove); `active_summary()` reads it,
  O(active), zero disk. Tests: `test_no_disk_read`, `test_cancelling_stays_active`.
- **#3 `_await_child` time drift.** The timeout loop summed `waited += tick`,
  which under-counts real elapsed when the loop is busy (each `wait_for(tick)`
  can take >tick), so a wedged child could be cancelled far past `wait_cap`. Fix:
  `time.monotonic()` measures actual elapsed. (covered by existing
  `test_wait_timeout_cancels_child_not_orphan`.)

Second review round (2026-06-17, two more):

- **cancel cascade did a per-child disk read.** `_cancel_run_cascade` called
  `store.load_meta(child_id)` for every in-flight control to read its
  `parent_run_id` — O(C·D) disk reads on the event loop during a cancel. Now
  `parent_run_id` is carried in the in-memory `_active` index (added for #2) and
  the cascade reads it from there — zero disk. `active_summary()` still projects
  to badge fields only (parent_run_id not surfaced). Test:
  `test_cancel_cascade_does_no_disk_read_for_children`.
- **fixed-name temp file on persist (defense-in-depth).** `persist_meta`
  (`meta.json.tmp`) and the token store `_save` (`tokens.json.tmp`) wrote to a
  HARDCODED temp name. Not a live bug in our single-process async model (per-run
  slot dirs make meta tmps distinct; no `await` between write and replace), but
  two writers WOULD race under `uvicorn --workers N`. Switched both to
  `tempfile.mkstemp` (unique name) + `os.replace`, with temp-cleanup on failure.
  Tests: `test_persist_meta_leaves_no_tmp_and_is_valid`,
  `test_persist_meta_cleans_tmp_on_failure`.

## Build plan T1 — `/task` command family (web client surface)

Added: `web/shared/task-controller.js` (`TaskController extends AgentRunController`),
`web/components/views/task-run-view.js` (`TaskRunView extends AgentRunView`).
Changed: `command-dispatcher.js` (route `/task`), `commands.js` + `app.js` (catalog),
`index.html` (script includes), `styles/right-panel-frame.css`. **No new endpoints** —
the tool-capable tier's client, entirely over the Inc-4→9 `/v1/agent/*` routes.
(build plan: `plan-task-command-sequencing.md`.)

```
chat input "/task <verb> …"                     [command-dispatcher.js dispatch]
└─ cmd === "/task" → tasks.handle(args)          [TaskController]
   ├─ run "<desc>" --tools … --allow … --budget … --provider … --model … --system …
   │   └─ run(argline)
   │      ├─ parseTaskArgs(argline) → {task, tools[], provider, model, system,
   │      │                            network.allow_outbound[], budget{}, errors[]}
   │      ├─ guards: errors → abort; no task → usage; no tools → "needs a grant"
   │      ├─ provider/model fall back to app.state.current{Provider,Model}
   │      ├─ apiClient.post("/v1/agent/task", body)          → {run_id, status}
   │      │     403 tier-off / 400 shell|no-provider → showSystemMessage(e.message)  [verbatim]
   │      ├─ _openPane(run_id, task, {tools,network,budget,provider,model,status})
   │      │     → new TaskRunView(...)   [chips: model · grant · ↗egress · ⏲budget]
   │      ├─ _breadcrumb(run_id, …)      [clickable "open ▸" in chat]
   │      └─ _watchDetached(run_id) ── inherited ───────────────────────┐
   ├─ ls | list          → list()   → GET /v1/agent/runs → clickable rows → focus()
   ├─ show | open | watch <id> → show(id) → focus(id)  [GET /runs/{id}, setMeta, re-tail]
   ├─ cancel <id>        → cancel(id) → POST /v1/agent/runs/<id>/cancel → pane.setStatus("cancelling")
   └─ "" | help          → help()
                                                                        │
   inherited watcher (AgentRunController, reused unchanged): ◄──────────┘
   _watchDetached → _runWatch:
     for await ev of _tailEvents(<id>?live=1):               [SSE `data:` lines]
        live = getViewByPath("agent://run/<id>")
        live.appendEvent(ev)   ── TaskRunView live log: tool_call / tool_denied /
                                  network_policy_allowed|denied / spawn_denied /
                                  subagent_spawned|finished  (else raw type string)
        break on agent_run_{complete,error,cancelled,interrupted}
     _pollUntilTerminal(<id>)  [degraded fallback if the SSE drops; no run-duration ceiling]
     _renderTerminal → pane.setResult(result) | setError(error)   [mirror to chat if no pane]
```

**Reuse seam** (why `TaskController` is ~200 lines, not ~400): the base controller
was made view-class-agnostic (`_viewClass`) and grew duck-typed hooks the oneshot
pane ignores — `setMeta` (hydrate chips from `GET /runs/{id}`), `appendEvent` (live
log), `setOnCancel` (Cancel button) — plus a shared `cancel()`. `/agentrun` behavior
is unchanged (its Node behavioral test still passes). Emitted event types the log
maps come from `build_task_runner` (`tool_call`, `tool_denied`,
`network_policy_*`) and `agent_spawn` (`spawn_denied`, `subagent_*`).

**Trialing from source (`uv run`):** the web UI is served from `~/.ppxai/web` by
default, so a plain `uv run ppxai-server` shows the INSTALLED bundle, not your
edits. Prefix `PPXAI_WEB_DIR=$PWD/ppxai/web` to serve the checkout live; enable the
tier (`tools.agent.task_tier_enabled=true`); and avoid CWD config/`.env` shadowing
(`PPXAI_CONFIG_FILE=~/.ppxai/ppxai-config.json`, `set -a; . ~/.ppxai/.env; set +a`).
Live-verified: launch → tool loop → `completed`; `cancel` → `cancelling`.

---

## Build plan T2 — filesystem seal (`tools.agent.sandbox`, in-process jail)

Added: `engine/tools/filesystem_policy.py` (`FilesystemPolicy`, mirror of
`NetworkPolicy`). Changed: `config/tools.py` (parse `sandbox`),
`agent_scoped_tools.py` (path chokepoint), `agent_v1.build_task_runner`
(per-run workdir + policy wiring), `task-run-view.js` (`path_denied` in the log).
**Off by default** — the jail engages only on `enforcement:"in_process"`, so an
unconfigured tool-capable run reads/writes as before (non-breaking).

```
build_task_runner._runner(m):                         [routes/agent_v1.py]
  sandbox = get_agent_config()["sandbox"]
  if sandbox.enforcement == "in_process":
     workdir = <sandbox.workdir.root>/<run_id>/work    (mkdir)
     engine.set_working_dir(workdir)                   ← relative tool paths resolve here
     fs_policy = build_filesystem_policy(sandbox, workdir)
                   read_roots = read_paths.allow + skills_dir + specs_dir + workdir
                   workdir     = the ONLY write root
     _on_path(allowed, payload): if not allowed → emit_event("path_denied", category="filesystem")
  engine.tool_manager = ScopedToolManager(..., filesystem_policy=fs_policy, on_path=_on_path)

ScopedToolManager.execute_tool(name, **kwargs):        [engine/agent_scoped_tools.py]
  grant check → shell check → network check →
  if filesystem_policy and is_path_tool(name):         [filesystem_policy._PATH_TOOLS]
     d = filesystem_policy.authorize(name, kwargs)
         mode, kwarg = _PATH_TOOLS[name]   # read_file→filepath(read), write_file→file_path(write), …
         target = resolve(raw)             # expanduser; relative→workdir; realpath unless follow_symlinks
         check(mode, target):
            deny-glob match → Deny (deny wins)
            write → within(workdir) ? Allow : Deny
            read  → any within(read_root) ? Allow : Deny   [boundary-anchored via commonpath]
     if not d.allowed:
        _on_path(False, {tool, mode, target_path, reason})   → path_denied event
        return "Error: filesystem access denied …"           # tool NEVER runs
  → base.execute_tool(name, **kwargs)
```

Best-effort under threat model A (a path-prefix jail, not an OS boundary).
`enforcement:"container"` (tier-d, T9) realizes the SAME `sandbox` fields as
real mounts: read-only rootfs, workdir `emptyDir`, skills/specs read-only
ConfigMap mounts, egress a k8s NetworkPolicy. Trial: set
`read_paths.allow`, then a `/task` read outside it returns the sandbox denial.

---

## Build plan T5 — interactive consent: `waiting` park + `POST /respond`

Added: `POST /v1/agent/runs/<id>/respond` (route), `AgentRunRegistry.park_run` /
`respond_run`, `AgentRunStore.persist_state`/`load_state` → **`state.json`**
(the Inspection Triplet's third file — debt (r) first write), consent card in
`TaskRunView`, `/task respond` verb. Changed: `build_task_runner`'s spawn-consent
adapter (was: engine shell-consent, auto-denied over HTTP → now: registry park),
`config/tools.py` (`consent_ttl_s`, default 300 s). New run status: **`waiting`**
(non-terminal — stays in the AppState `background_agents` mirror).

```
spawn_subagent.execute (consent_policy="deny")        [engine/tools/agent_spawn.py]
└─ await request_consent(summary) ──► _spawn_consent(summary)   [build_task_runner]
   └─ await registry.park_run(m, kind="consent", prompt=summary,
                              ttl_s=config.consent_ttl_s)       [agent_runs.py]
      ├─ (cancel already pending? → return {approved:False, via:"cancelled"}, no park)
      ├─ token = secrets.token_hex(8)
      ├─ meta.status="waiting"; meta.waiting={kind,prompt,token,since,expires_at,ttl_s}
      │    persist_meta · _index_active · _notify_change    [badge shows ✋ waiting]
      ├─ persist_state(run_id, {schema:1, status:"waiting", waiting{…}})   ← state.json
      ├─ emit_event("agent_waiting", category="consent", data={…,token})   ← SSE tail
      ├─ await wait_for(future, ttl_s)
      │    ├─ respond_run resolves        → {approved, text, via:"respond"}
      │    ├─ TTL expires                 → {approved:False, via:"timeout"}   [fail-closed]
      │    └─ cancel_run resolves waiter  → {approved:False, via:"cancelled"} [no TTL idle]
      └─ meta.status="running"; waiting=None; persist_meta + persist_state(last_response)
           emit_event("agent_resumed", category="consent", {kind,approved,via})

POST /v1/agent/runs/{id}/respond {token, approved?|text?}   [routes/agent_v1.py]
├─ 404 unknown · 403 not owner (Inc 8b) · 422 answer-less body
├─ registry.respond_run(id, token, approved, text)
│    not parked/restarted → (False,…) → 409 · token mismatch → 409 · done → 409
│    ok → future.set_result({approved, text, via:"respond"})
└─ {ok:true, run_id, status:"running"}

client (web):
  agent_waiting on the SSE tail → TaskRunView consent card (prompt + note field
    + Approve/Deny; token from event data) → setOnRespond → controller.respond()
  /task respond <id> approve|deny|"<text>" → GET /runs/{id} → waiting.token →
    POST …/respond   (text-only answer to a consent park = deny-with-note)
  agent_resumed | setStatus(≠waiting) → card cleared
```

Restart semantics (deliberate, T5 scope): the park's future is in-memory — a
parked run does NOT survive a restart *in flight*; its `state.json` checkpoint
does (respond after restart → 409 "server restarted"; T7 `/resume` is the
consumer). `spawn_consent:"auto"` still skips the park entirely.

---

## Build plan T6 — two-phase termination: `completed_pending_ack` + `POST /ack`

Added: `POST /v1/agent/runs/<id>/ack` (route), `AgentRunRegistry.ack_run` /
`_finalize` / `maybe_reap_hold`, `RunMeta.hold_result`/`acked_at`, Collect
button + `/task ack` (client). Changed: `run_in_background._drive` success
branch (hold split), GET read paths (lazy reap), `config/tools.py`
(`result_retention_s`, default 3600 s). New statuses: **`completed_pending_ack`**
(run exited, result HELD) and **`finalized`** (collected / GC-eligible) — both
out of the AppState badge set (the run consumes nothing).

```
run_in_background._drive success:                     [engine/agent_runs.py]
  body = await runner(meta)
  ├─ meta.hold_result (top-level /task run — the route sets it)
  │    finish_run(status="completed_pending_ack", result=body)   ← record persists
  │    persist_state({status, result_ready_at, result_chars})    ← state.json
  │    emit_event("agent_result_ready", category="result")       ← INSTEAD of agent_run_complete
  └─ else (tool-free /run tier · spawn children — collected inline)
       finish_run(status="completed") + emit "agent_run_complete"   (unchanged)

POST /v1/agent/runs/{id}/ack                          [routes/agent_v1.py]
├─ 404 unknown · 403 not owner (Inc 8b)
├─ registry.ack_run(id)
│    finalized already → (True, "already")  → 200 (idempotent, no dup event)
│    not completed_pending_ack → (False, …) → 409 (nothing held)
│    else _finalize(via="ack"): status="finalized"; acked_at; persist_meta;
│         persist_state({status:"finalized", via, acked_at});
│         emit "agent_run_finalized" {via}
└─ {ok:true, run_id, status:"finalized"}

GET /runs · GET /runs/{id}  (lazy retention backstop — no timer task)
└─ registry.maybe_reap_hold(meta, config.result_retention_s)
     held AND finished_at + retention elapsed → _finalize(via="retention")
     (0/None disables; finalize marks GC-eligible, deletes NOTHING)

client (web):
  agent_result_ready on the tail → watcher breaks → pane renders the held
    result, status chip 📬 result ready, Collect button visible
  Collect button | /task ack <id> → POST …/ack → chip ✅ collected
  reopen via /task ls (📬 icon) → focus() GET → result re-rendered from meta
```

Design choice: **explicit collect** (button + verb), not silent auto-ack-on-view
— the user issues the receipt, which is what makes the disconnect-then-collect
trial observable. Children never hold (`hold_result` unset): the awaiting
parent IS their collector, so `spawn_subagent._await_child` still sees a
`completed` child (its terminal tuple includes the new statuses defensively).

---

## Build plan T7 — interrupted resume: `POST /resume` + restart-orphan sweep

Added: `POST /v1/agent/runs/<id>/resume` (route), `resume_refusal()` (the
conditional-resume decision matrix, ADR #5), `AgentRunRegistry.sweep_orphans` /
`resume_run`, `RunMeta.system`/`read_roots` (the remaining runner inputs,
persisted by the /task route so the rebuild is faithful), Resume button +
`/task resume` (client). Changed: `server/state.py` (sweep at registry
construction), `_drive`'s RunStopped path (writes a `state.json` stop
checkpoint). Debt (r) is **retired**: the Triplet's `state.json` now has
producers (T5 park, T6 hold/finalize, T7 stop/sweep/resume) AND its consumer.

```
server start → get_agent_run_registry() → registry.sweep_orphans()   [state.py]
  for meta in list_meta() where status ∈ {pending,running,waiting,cancelling}
                            and run_id not in _run_tasks:
     status="interrupted"; error="server restarted…"; waiting=None
     resumable = hold_result AND task/tools/provider/model AND no result
     persist_meta · persist_state({via:"restart_sweep"}) · emit agent_run_interrupted

POST /v1/agent/runs/{id}/resume                       [routes/agent_v1.py]
├─ 403 tier off (resume re-enters the tool tier) · 404 unknown · 403 not owner
├─ resume_refusal(meta, in_flight=get_run_task(id) is not None) → 409 {reason}:
│    in flight · status ∉ {interrupted,cancelled} · not resumable ·
│    not hold_result (tool-free /run tier + spawn children refused) ·
│    result already recorded · missing task/tools/provider/model
├─ _validate_provider_or_400(meta.provider)      [fail fast, run unchanged]
├─ runner = build_task_runner(provider/model/task/tools/network from meta,
│             system=meta.system, extra_read_paths=meta.read_roots,
│             allow_spawn=True)                  [IDENTICAL AC-1/AC-2 sandbox]
└─ registry.resume_run(meta, runner)
     clear error/finished_at/resumable/waiting
     persist_state({status:"running", resumed_from}) · emit "agent_run_resume"
     run_in_background(meta, runner)   → fresh budget window, SAME run_id,
                                         events APPEND to the same log (seq
                                         continues); a T6 hold applies to the
                                         resumed leg (hold_result persisted)

client (web):
  Resume button visible only when meta.resumable AND status interrupted|cancelled
  /task resume <id> | button → POST …/resume
     409 → refusal reason verbatim; 200 → chip running, pane re-pinned,
     detached watcher restarted (the old one broke at the interrupt)
```

Resume semantics (deliberate): a resume **re-executes the bounded task from its
start** under the same run identity — the dead leg's conversation state is not
replayed (the run record, not the chat transcript, is the durable unit). The
stop checkpoint (`state.json`) is what makes the decision and the audit trail
inspectable, not a mid-conversation snapshot.

---

## Build plan T8a — VSCode port of the `/task` family

Added: `vscode-extension/src/taskController.ts` (IoC controller, VSCode-free),
`/v1/agent/*` typed slice in `httpClient.ts`, `/task` route + UI adapter in
`chatPanel.ts`, `/task` in the completion catalog. **No server changes** — the
whole increment is a second client over the T1–T7 surface. T8b (TUI) is split
out pending the transport decision (in-process registry = debt (t) vs HTTP
client in the TUIs) — see the plan doc §T8.

```
webview input "/task <verb> …"                    [chatPanel.handleSlashCommand]
└─ command === 'task' → getTaskController().handle(argsText)   [BEFORE factory
   │                                                    dispatch — factory has no /task]
   ├─ run    → parseTaskArgs (same grammar as web) → backend.agentTask(body)
   │            403/400 detail verbatim · session provider/model fallback
   │            → systemMessage launch line → watchDetached(run_id)
   ├─ ls     → agentRuns() → icon rows into the transcript
   ├─ show|watch <id> → agentRun(id) → renderRun (+ re-watch if live)
   ├─ respond <id> … → agentRun(id).waiting.token → agentRunRespond
   ├─ ack <id> / resume <id> / cancel <id> → POST; 409 reasons verbatim
   └─ help

watchDetached(id)  [poll; web degraded-path contract: backoff 1.5s→30s,
                    no run-duration ceiling, give up only on consecutive fails]
└─ loop agentRun(id):
   ├─ status waiting + unseen token → vscode QuickPick (✋ Approve/Deny —
   │     same idiom as shell/file consent) → agentRunRespond({token, approved})
   │     dismissed → hint line; the T5 TTL is the fail-closed backstop
   └─ terminal → renderRun:
        completed_pending_ack → fullResponse(result) + "/task ack" hint (T6)
        interrupted|cancelled + resumable → "/task resume" hint (T7)
```

Parity is TESTED, not assumed (`tests/test_vscode_task_controller.py`): the
verb set, the `/v1/agent/*` endpoint set, and the terminal/success status sets
are regex-extracted from BOTH clients and compared — a verb/endpoint/status
added to one client fails the sentinel until the other grows it too.

---

<!-- Inc 10+ sections appended here as they land. Template:
## Increment N — <title>
Added/changed: <files>. Execution model change: <if any>.
### <METHOD /path> — <what>
``` ...graph... ```
-->

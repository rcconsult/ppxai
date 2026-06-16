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

Served from `~/.ppxai/web/` (NOT the repo) — see static.py `WEB_UI_DIR`.
Trialing edits requires copying the changed web files there (build-install
step 5b, or a targeted copy of command-dispatcher.js + app.js).

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
       3. loopback POST /v1/tokens into EMPTY store -> proceed  # bootstrap mint
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

<!-- Inc 10+ sections appended here as they land. Template:
## Increment N — <title>
Added/changed: <files>. Execution model change: <if any>.
### <METHOD /path> — <what>
``` ...graph... ```
-->

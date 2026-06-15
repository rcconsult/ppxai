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
├─ _build_provider + OpenAI-compat carve-out (400 if not)
├─ registry.start_run(task, tools=grant, ...)          → RunMeta(running)
└─ registry.run_in_background(meta, _runner):
     _runner(m):
       engine = EngineClient(); set_provider/model; enable_tools()  [ADR §9 D1]
       engine.tool_manager = ScopedToolManager(engine.tool_manager,
                                grant, on_deny=emit tool_denied)
       async for ev in engine.chat(task):    ← chat_with_tools loop
         TOOL_CALL  → registry.emit_event(tool_call, debug/tool)
         STREAM_END → capture final text → run result
```

### AC-1 enforcement (ScopedToolManager)  [engine/agent_scoped_tools.py]

```
Two layers, both required:

1. OFFERED set filtered to the grant (model never SEES off-grant tools):
   get_tools_openai_format / get_available_tools / list_tools / get_tool /
   get_tools_prompt → only names in grant. (get_tools_prompt is the
   prompt-based / native-fallback path — it re-renders the base prompt BOUND
   to the scoped manager so it enumerates only granted tools, and strips the
   shell-wrapper context unless a shell tool is granted. Part of AC-1.)

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
   scheme not https/""           → Deny  (https-only MVP)
   for rule in rules:
     rule.matches_host(host):           exact, or "*.suffix" single-label,
                                        suffix-anchored (blocks lookalikes)
        rule.matches_path(path):        no paths = any; else prefix match
           → Allow(rule_id)
        else → Deny(path not in prefixes)
   no rule matched               → Deny(host not in allowlist)
empty rules                      → Deny everything (fail-closed)

authorize(name, kwargs) -> ToolDecision:      ← the chokepoint decision
   targets = tool_targets(name, kwargs)        every URL the call COULD reach
   no targets                    → Deny  (unresolvable; fail-closed)
   ALL targets pass check()      → Allow (superset rule — see below)
   any target fails check()      → Deny  (reports the first failing target)

Superset rule (AC-2): web_search's backend is chosen at call time with a
Perplexity→Gemini→DDG fallback, so its egress set is the UNION of all of
them; the run must allowlist EVERY one or web_search is denied — it can't
reach an unallowlisted backend by taking a branch we didn't predict. Same
for get_weather's https→http fallback (the http branch is denied under the
MVP https-only rule, so wttr.in alone can't authorize get_weather).
```

<!-- Inc 6+ sections appended here as they land. Template:
## Increment N — <title>
Added/changed: <files>. Execution model change: <if any>.
### <METHOD /path> — <what>
``` ...graph... ```
-->

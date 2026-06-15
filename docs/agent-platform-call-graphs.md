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

<!-- Inc 3+ sections appended here as they land. Template:
## Increment N — <title>
Added/changed: <files>. Execution model change: <if any>.
### <METHOD /path> — <what>
``` ...graph... ```
-->

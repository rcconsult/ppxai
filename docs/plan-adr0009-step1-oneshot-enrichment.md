# ADR 0009 Step ① — Enriched `/v1/oneshot` (oneshot facade over the run tier)

**Status:** Planned, not started. Implements ADR 0009 §4 + Sign-off Q4/Q6.
**Build order:** step ① of ④ (① oneshot facade → ② per-tool `tools.<tool>.egress`
→ ③ `execution.profiles` + `enrichment` → ④ shared backend resolver).

**Decisions locked (owner):**
- **Oneshot is a FACADE over the real run machinery — not a parallel mode**
  (2026-08-02, owner-corrected twice; supersedes both the loop-extraction idea
  and the ephemeral/null-registry idea). The oneshot endpoint starts a real
  agent run through the real `AgentRunRegistry` — same registry, same events,
  same runs dir, same budget control, same sandbox — and the ONLY difference
  is oneshot semantics: the HTTP request awaits the run's terminal state and
  returns its result in the response body. Engine mechanics stay identical to
  `/task` execution, so over time we **remove more code than we change**.
- **Debuggability is a requirement.** Enriched oneshots are debuggable exactly
  like task runs: a run id, `~/.ppxai/runs/<id>/` meta + event log,
  `/task show <id>`. No log-only side channel.
- **Egress for step ① = the existing `_WEB_SEARCH_ALL_HOSTS` superset**
  `web_search` already declares in `network_policy.py`. Step ② swaps the
  source to `tools.web_search.egress` with no behavior change.

---

## Architecture (verified from code — every seam already exists)

The facade is the **spawn_subagent parent pattern with HTTP as the parent**.
`SpawnSubagentTool._await_child` already awaits a child run's completion via
`registry.get_run_task()` — the docstring at `agent_runs.py:642` names exactly
this use ("lets a waiter await the child's completion directly instead of
polling"). Oneshot does the same from the route handler:

```python
registry = get_agent_run_registry()
meta = registry.start_run(
    task=req.prompt,
    tools=["web_search"],            # the ONLY grant — the whole point
    provider=provider_name, model=model,
    network=list(_WEB_SEARCH_ALL_HOSTS),   # step ① egress (step ② swaps source)
    budget={"iterations": SEARCH_CAP},     # small impl constant (1–2)
    hold_result=False,               # → terminal `completed`, no ack/T6 hold
    owner=...,                       # same authz stamping as any run
)
runner = build_task_runner(
    task=req.prompt, tools=["web_search"],
    provider=provider_name, model=model,
    network=list(_WEB_SEARCH_ALL_HOSTS),
    budget={"iterations": SEARCH_CAP},
    allow_spawn=False,               # no spawn_subagent → consent/park path dead
)
registry.run_in_background(meta, runner)
await registry.get_run_task(meta.run_id)   # ← oneshot semantics: block here
final = registry.get_run(meta.run_id)
# final.status ∈ {completed, failed, cancelled, interrupted} → map to response
```

Why this needs **zero** changes to `agent_v1.py` / `agent_runs.py`:

- `build_task_runner`'s `_runner` emits events / reads its control through the
  **module-global registry** (`get_agent_run_registry()`) — the same singleton
  the facade uses. No injection needed; events land on the real run's log.
- `hold_result=False` is the existing sub-agent-child termination path:
  `_drive()` finishes the run `completed` with the result on meta — no
  `completed_pending_ack`, no ack, no retention hold (`agent_runs.py:1066`).
- `allow_spawn=False` makes the T5 park/consent path unreachable.
- Cancel/budget/orphan-sweep semantics come along for free: a server restart
  mid-oneshot lands the run `interrupted` via the T7 sweep like any run.

**"Stateless" means what ADR 0004 actually cared about** — no user-session
side-effects. The per-run throwaway `EngineClient` (D1) preserves that: no
session store touched, no state_sync, no `usage.json` mutation. The run
*record* is not session state — it is the audit + debug surface the owner
requires, GC'd like any sub-agent run record.

## The unification endgame ("remove more code than change")

Step ① adds the facade for the **enrichment-on** branch only; the plain path
still calls `provider.oneshot()` directly. Once the facade is proven (gateway
smoke + parity), the follow-up is to route **all** oneshot flavors through the
run tier and delete the direct-provider path from `oneshot.py`:

- plain (no tools) → run with `tools=[]`
- native grounding (Gemini `oneshot_grounding`) → **prerequisite:** thread the
  provider-side grounding flag through the run-tier engine (today it only
  exists on `provider.oneshot()`); until then the native branch stays direct.
- Net effect: one execution path, oneshot = a verb, and ADR 0008's tier count
  drops (oneshot spend lands wherever task spend lands — one sink to fix,
  not two).

This removal is a follow-up commit gated on parity (gateway-smoke must stay
byte-identical for the ppxai-sre consumer), not part of step ①.

---

## TODO

### A. Config (new keys, default off; ADR 0011 Q5 final locations + dual-read)
- [ ] `execution.run.web_search` reader (mirror `_oneshot_grounding_enabled`,
      `oneshot.py:130`), dual-read fallback, default `False`.
      (Supersedes ADR 0009's planned `execution.oneshot.enrichment` name —
      owner-approved via ADR 0011 Q5; amendment note in ADR 0009.)
- [ ] Migrate grounding key: `execution.run.grounding` ←
      `tools.web_search.oneshot_grounding` (`oneshot.py:146`), dual-read.

### B. Gating truth table (`oneshot.py` handler, ~L278)
- [ ] `native_grounding_effective = grounding_on AND capabilities.web_search`.
- [ ] `tool_calling_capable(provider, model)`.
- [ ] Branch per §4 table; **enrichment XOR native** (never both); both-off ⇒
      byte-identical to today.

### C. The facade (core of step ① — all inside `oneshot.py`)
- [ ] `start_run(..., tools=["web_search"], hold_result=False)` +
      `build_task_runner(...)` + `run_in_background` +
      `await get_run_task(run_id)`; map terminal status → response
      (completed → 200; failed/cancelled/interrupted → structured error with
      the run id so it stays debuggable).
- [ ] Request timeout: bound the await (config or impl constant); on timeout
      `registry.cancel_run(run_id)` and return 504 **with the run id** (the
      run record keeps whatever happened — debuggable after the fact).
- [ ] Client disconnect: cancel the run (don't leave a headless spender).

### D. Per-request accounting (§4's named concurrency bug)
- [ ] **Do NOT use `get_last_tool_usage()`** (`web_premium.py:384`,
      process-global reset-on-read → cross-request misattribution). Capture
      premium-search cost **per invocation**.
- [ ] Model round-trip tokens → existing `usage`. Search cost →
      `grounding.search_cost`.

### E. Wire contract (one optional response field)
- [ ] `OneshotResponse.grounding: Optional[OneshotGrounding]` (`oneshot.py:117`):
      `{searched, queries, backend, search_cost, run_id}`. `run_id` is the
      debug handle (owner requirement — `/task show <id>` works on it).
      **Absent when off** (byte-identical for existing consumers).

### F. Audit + observability (reuses the run tier wholesale)
- [ ] Nothing to build: events land on the run's real event log
      (`~/.ppxai/runs/<id>/`), visible via `/task show` / events SSE like any
      run. Verify in the trial that a oneshot run is listed + inspectable.
- [ ] Search-backend error does NOT fail the request — surfaced to the model,
      which answers with what it has; `searched: true` + failure on the event
      log.
- [ ] Decide display tagging: oneshot runs appear in `/task ls` — acceptable
      (they're real runs) but consider an `origin`/task-prefix marker so
      operators can tell them apart. (Open sub-choice; smallest viable:
      nothing in step ①.)

### G. `/doctor` + docs
- [ ] `/doctor` reports effective grounding path per configured model
      (native / search-loop / closed-book).
- [ ] Document `grounding` (incl. `run_id`) in `docs/api-gateway.md`;
      release-note the ADR-0004 "no tool loop in oneshot" purity revision.

### H. Tests
- [ ] Truth-table matrix (5 rows).
- [ ] Concurrent-request accounting (no cross-attribution — §4's named bug).
- [ ] Perimeter: only `web_search` callable; no file/shell tool reachable.
- [ ] `grounding` absent when off; present + shaped when on.
- [ ] Facade lifecycle: run record exists + terminal `completed`; timeout →
      cancel + 504 + run id; failed run → structured error + run id.
- [ ] `/task` regression green (trivially — step ① changes no agent code).

---

## Perimeter guarantee (ADR 0009 §4 "what safe means")
Host/filesystem-safe, NOT injection-proof. Only `web_search` callable (fixed
target set; model chooses query, never target). Injection can influence the
answer text + the search query — inherent to grounding, incl. the native path
already shipped — which argues for default-off, not against the capability.

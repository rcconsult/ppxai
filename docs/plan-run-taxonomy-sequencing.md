# Sequencing plan — enriched oneshot facade + command taxonomy

Implements [ADR 0009](decisions/0009-task-execution-profiles.md) step ① via
the facade plan
([plan-adr0009-step1-oneshot-enrichment.md](plan-adr0009-step1-oneshot-enrichment.md))
and [ADR 0011](decisions/0011-command-taxonomy-streamline.md) (Accepted).

**Build contract** (same rules as the T1–T8a `/task` plan): one stage = one
commit; **live-trial after each stage before starting the next**; commit on
owner instruction; every stage leaves the tree runnable, all tests green,
and the new surface debuggable. Stages are ordered so nothing ever depends
on an unbuilt later stage.

Two phases: **F** (facade — API-side, zero UX break) lands and proves the
mechanics first; **U** (UX taxonomy — the ADR 0011 breaking sweep) reshapes
the command surface on top of the proven facade. The follow-up unification
(FU) stays gated behind parity.

---

## Phase F — enriched `/v1/oneshot` facade (ADR 0009 step ①)

> **STATUS (2026-08-02): Phase F COMPLETE.** F1 `abf83868` · F2 `8bcd8109`
> · F3 `26c26a19` · F4 `16b6091d` · F5 `01554919` + docs. Live-verified:
> full 2×2 config matrix (search-loop / native / closed-book / XOR
> native-wins), grounded answer with real per-request accounting
> (`queries`, `backend=perplexity`, `search_cost`, token usage) derived
> from the run's own audit trail; gateway-smoke 6/6 byte-identical at
> defaults. Two live-trial catches fixed en route: the loader's top-level
> whitelist dropped the `execution` block, and URL-vs-bare-host allowlist
> entries made the facade's egress deny everything. Next: Phase U (or
> ADR 0009 steps ②/③ — see "Dependencies" below).

### F1 — `RunMeta.kind` discriminator (additive, inert)

The taxonomy's data seam lands FIRST so the facade never pollutes the task
list, and so `kind` exists before any consumer.

- `RunMeta.kind ∈ {"oneshot","task"}`; persisted; **absent/legacy reads as
  `"task"`**. All current producers stamp `task` explicitly.
- Additive `?kind=` filter on `GET /v1/agent/runs`; no UI change.
- **Trial:** `/task run` a trivial task → `meta.json` shows `"kind": "task"`;
  `/task ls` output unchanged; `GET /v1/agent/runs?kind=oneshot` → empty.
- **Tests:** meta round-trip with/without the field; filter; legacy meta file
  (hand-written, no `kind`) loads as `task`.
- **Invariant:** zero behavior change; `/task` regression green.

### F2 — `execution.run.*` config readers + gating truth table (inert)

- Readers for `execution.run.web_search` (default off) and
  `execution.run.grounding` (dual-read fallback from
  `tools.web_search.oneshot_grounding`, `oneshot.py:130-146`).
- The §4 gating truth table computed in the oneshot handler
  (`native_grounding_effective`, `tool_calling_capable`, enrichment XOR
  native) — but the enrichment branch only **logs** the chosen path
  (debug log, honors `tui.debug_log`); execution stays today's.
- **Trial:** flip the keys; debug log shows the effective path per request;
  `scripts/gateway-smoke.py` green and **byte-identical** in every config
  combination (both-off is the shipped default).
- **Tests:** truth-table matrix (5 rows) against the reader, dual-read
  fallback, default-off.
- **Invariant:** wire behavior byte-identical; the gate exists before the
  thing it gates.

### F3 — the facade (enrichment-on path goes live)

The core: enrichment-on drives a real `kind=oneshot` registry run —
`start_run(kind="oneshot", tools=["web_search"], hold_result=False)` +
`build_task_runner` + `run_in_background` + `await get_run_task(run_id)`.
**Zero changes to `agent_v1.py` / `agent_runs.py`.**

- Terminal-status map: `completed` → 200; `failed/cancelled/interrupted` →
  structured error **with the run id**.
- Request timeout → `cancel_run` + 504 with run id; client disconnect →
  cancel (no headless spender).
- Minimal `grounding` field: `{searched, run_id}` (full shape in F4).
- Egress = `_WEB_SEARCH_ALL_HOSTS` (step ② later swaps the source).
- **Trial (live):** enrichment on, oneshot a current-events question against
  a local model → grounded answer; then **debug the run like any run**:
  `~/.ppxai/runs/<id>/` has meta + events; `/task show <id>` works (old verb
  — U2 renames it). Enrichment off → byte-identical (smoke).
- **Tests:** facade lifecycle (completed/failed/timeout paths), perimeter
  (only `web_search` callable; no file/shell tool reachable), `/task ls`
  unpolluted (kind filter from F1), `/task` regression green.
- **Invariant:** default-off feature; existing consumers unaffected.

### F4 — per-request accounting + full `grounding` shape

- Per-invocation premium-search cost capture — **NOT**
  `get_last_tool_usage()` (`web_premium.py:384` process-global
  reset-on-read → cross-request misattribution, §4's named bug).
- `grounding: {searched, queries, backend, search_cost, run_id}`; model
  tokens → existing `usage`. Absent when off.
- Search-backend failure does NOT fail the request — surfaced to the model;
  `searched: true` + failure on the run's event log.
- **Trial:** two **concurrent** enriched oneshots → each response's
  `search_cost`/`queries` attribute to its own run (check both event logs).
- **Tests:** concurrent-attribution, grounding present+shaped when on /
  absent when off, backend-failure path.

### F5 — observability + docs polish

- `/doctor` reports the effective grounding path per configured model
  (native / search-loop / closed-book).
- `docs/api-gateway.md`: `grounding` field incl. `run_id` as the debug
  handle; release-note draft for the ADR-0004 "no tool loop in oneshot"
  purity revision.
- **Trial:** `/doctor` output against a mixed provider config.

**Phase F exit:** facade live-trialed through an installed binary
(gateway-smoke + a real grounded answer), `/task` untouched, ppxai-sre
contract byte-identical with enrichment off.

---

## Phase U — taxonomy sweep (ADR 0011; breaking, release-noted, NO aliases)

Each stage is a hard rename scoped small enough to trial in one sitting;
T8a **parity sentinels** + completion data + help text move in the same
commit as the verbs they name. A running release-note entry
(`docs/release-notes-v1.19.x` draft) accumulates the breaks per stage.

### U1 — `/auto` (commands layer, all clients at once)

- `/agent` → `/auto` (usage, help, category, completion), `tools agent` →
  `tools auto`. Old names **gone** (Q4: no aliases).
- Consent semantics per ADR 0011: ask per consent by default; each prompt
  offers "always allow" scoped to this auto run. (If today's loop already
  asks, this is a rename; any consent-gap is closed here.)
- **Trial:** Rich TUI `/auto on|off` + one small checkpointed task + `/undo`;
  `/agent` → unknown command with a helpful pointer.
- **Tests:** registry, completion, help; checkpoint/undo regression.

### U2 — `/task` reshape (web + VSCode)

- **Direct-launch grammar**: `/task "<prompt>" --tools …` launches; verb rule
  = first token ∈ verb set AND remainder id-shaped (`run_`+12hex) or empty.
  The `run` subcommand is gone.
- Verb renames: `show` → `get`, `ack` → `collect` (collect keeps ack
  semantics for now — finalize + display; **merge lands in U4**).
- **Trial:** launch via direct grammar; `get`/`collect`/`watch`/`cancel`/
  `respond`/`resume` round-trip in web AND VSCode; prompt-starting-with-verb
  edge (`/task get the weather...` → launches, because "the" isn't
  id-shaped).
- **Tests:** grammar table (verb+id / verb+empty / verb+prose / bare
  prompt), parity sentinels, T5–T7 lifecycle regression.

### U3 — `/run` family (web + VSCode)

- `/run <prompt>` → `kind=oneshot` run; grant `{}` or `{web_search}` per
  `execution.run.web_search` — no flag can widen it. Small default budget.
- Verbs `ls · get · watch · cancel · collect` (shared dispatch with /task,
  kind-filtered lists); side-panel / split-view rendering.
- **Retire `/agentrun` + `/agentruns`** (breaking); drop the
  `task-controller.js:218` tool-free guard — tool-free one-offs are `/run`,
  `/task` accepts any grant.
- **Trial:** `/run "what happened today in X"` → progress in side panel,
  non-blocking chat; `/run ls` shows only oneshots, `/task ls` only tasks;
  `/agentrun` → unknown command.
- **Tests:** kind-filtered ls, grant clamp (config off → `{}`; no widening
  flag), retirement, parity sentinels.

### U4 — collect semantics + `execution.collect`

- Collect = finalize + **plain merge** of the result text into the active
  session (Q3). GUI: Collect button on `/run` + `/task` views.
- `execution.collect`: `auto` = always auto-merge on completion; `yes` =
  held + collectable; `no` = collect impossible — button greyed/disabled,
  TUI warns with the enable hint. Mechanics ride T6 `hold_result`
  (auto→merge+finalize; yes→hold; no→auto-finalize, no merge path).
- TUI legs apply where the commands exist — full TUI `/run`+`/task` ride
  T8b (parked); until then the config drives web/VSCode + any TUI warning
  surface that exists.
- **Trial matrix:** 3 config values × {`/run`, `/task`} in web; merged text
  visible to the model in the next chat turn (ask it about the result).
- **Tests:** hold_result mapping per value, merge payload plain, greyed/
  disabled state, no-merge invariant under `no`.

**Phase U exit:** release-note "Breaking changes" section complete
(`/agent`, `/agentrun(s)`, `task show`, `task ack`, `tools agent` removed;
new: `/auto`, `/run`, direct-launch `/task`, `get`, `collect`,
`execution.run.*`, `execution.collect`).

---

## FU — follow-up unification (gated, not scheduled)

Route **plain** oneshot through the run tier too and **delete** the direct
`provider.oneshot()` path ("remove more code than change").

- **Prerequisite:** provider-native grounding flag threaded into the
  run-tier engine (today it exists only on `provider.oneshot()`).
- **Gate:** gateway-smoke byte-parity for the ppxai-sre consumer, proven
  before the deletion commit.

## Dependencies on the ADR 0009 build order

Steps ② (`tools.<tool>.egress`) and ③ (`execution.profiles`) are unchanged
and slot in after Phase F (② swaps F3's egress source with no behavior
change). Neither blocks Phase U.

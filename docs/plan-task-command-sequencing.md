# `/task` command — incremental build plan

Sequencing plan for the interactive **`/task`** command family (design:
[agent-task-command-design.html](agent-task-command-design.html); lifecycle:
[agent-task-lifecycle.html](agent-task-lifecycle.html); architecture:
[decisions/0003-agent-platform-architecture.md](decisions/0003-agent-platform-architecture.md)
§8–§9). Same contract as the Stage-2 increment plan
([plan-v1.19.0-sequencing.md](archive/plan-v1.19.0-sequencing.md)):

> **Build contract.** Each increment is a **vertical slice** that brings
> exactly the server + client bits needed to **live-trial it end-to-end**,
> nothing speculative. Bring a seam early only when it's the right shape
> (e.g. the read-path enforcement point). **Web first** — TUI + VSCode are a
> late port. Every increment ships with tests and a concrete trial before the
> next one starts.

**Where we start.** The tool-capable tier already exists server-side:
`POST /v1/agent/task`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/events`
(SSE), `POST /runs/{id}/cancel`, owner-scoped authz, `execution.task.enabled`
default-off gate, no-shell rejection. There is **no `/task` client command in
any client** — `/agentrun` (tool-free) is the only agent slash command shipped.
So T1 is mostly client work over existing endpoints; new server machinery
arrives only where the lifecycle needs it (T5–T7) and where the filesystem
seal needs it (T2).

**Trial prerequisites (every increment).**
- Enable the tier: `execution.task.enabled: true` in `~/.ppxai/ppxai-config.json`.
- Run the web client against **live source**: `PPXAI_WEB_DIR=$PWD/ppxai/web uv run ppxai-server` (edits to `ppxai/web/` don't reach `~/.ppxai/web` otherwise — see `docs/lessons/web-assets-served-from-ppxai-home.md`).
- Trial with **auth disabled** (default — no `server.secrets` file store, `PPXAI_API_TOKEN` unset): `/task` is loopback-reachable without a bearer (`auth.py::check_request` → `if not is_auth_enabled(): return None`). A token-carrying web client for the auth-enabled case is a follow-up, not a blocker.
- Set a default subagent so a bare `--tools` launch has a provider/model: `execution.default_subagent: {provider, model}`.

---

## T1 — launch + observe: `run · ls · show · watch · cancel` — ✅ DONE

**Shipped:** `0ff4370b` (+ `42543961` log-noise fix, `22d7757f` call graph),
live-trial-verified in-browser (run/ls/cancel; pane with chips + live log +
result). `TaskController extends AgentRunController`, `TaskRunView extends
AgentRunView`; `/agentrun` unchanged.

**Capability:** `/task run "<desc>" --tools …` mints a tool-capable run and
renders it in a right-panel pane; `/task ls` lists runs; `show`/`watch` focus +
live-tail a pane; `cancel` stops one. All over **existing** endpoints.

**Build (client only):**
- `web/shared/task-controller.js` — `TaskController`, mirror of
  `AgentRunController`; register `/task` in `command-dispatcher.js` next to
  `/agentrun` and route sub-verbs (`run|ls|show|open|watch|cancel|help`).
- Launch-line flag parser: `--tools a,b,c`, `--allow host[/path],…`,
  `--provider`, `--model`, `--budget iters=,time=,tokens=`, `--system "…"`,
  `--work-dir <path>` (per-run working directory intent, 2026-07-12,
  post-T8a: clients thread the session working dir by default; the server
  honors it only when the T2 seal is OFF — sealed runs keep their jail and
  the launch response flags `workdir_ignored`)
  → `AgentTaskRequest` body.
- `web/components/views/task-run-view.js` — `TaskRunView`, extends the
  `AgentRunView` pane: grant chips, egress chips, budget meter, live events
  log (`tool_call`/`tool_result`/`tool_denied`/`network_*`/`spawn_*`), a
  **Cancel** button while non-terminal.
- Surface the tier errors verbatim: 403 (tier disabled + enable hint), 400
  (shell grant), 400 (missing provider/model).

**Trial:** enable the tier; `/task run "list the files under docs and count the
markdown ones" --tools read_file,grep,list_directory`; watch the tool loop in
the pane; `/task ls`; `/task cancel <id>` mid-run and confirm it stops.

**Tests:** flag-parser unit tests (grant/allow/budget parsing, bad input);
dispatcher routing test (`/task run|ls|cancel` → controller); a Node
behavioral test mirroring `test_agent_run_controller_behavior.py`.

**Deliberately NOT yet:** spec/skill files, read-scope, `respond`/`ack`/`resume`.

---

## T2 — the seal: `read_paths` enforcement + `execution.task.sandbox` (in_process) — ✅ DONE

**Shipped:** `89b18ac0` (+ `9bd8c790` call graph). `engine/tools/filesystem_policy.py`
(`FilesystemPolicy`), `config/tools.py` sandbox parsing (as built; now
`config/execution.py`, default `enforcement:"off"` → non-breaking), the
`ScopedToolManager` path chokepoint (`path_denied`), and the
per-run workdir in `build_task_runner`. Live-trialed: allowed read → ok, `/etc/hosts`
→ denied; 24 unit tests. `container` sub-block schema defined but inert (T9).

**Capability:** a run can read/write **only** inside configured locations; an
attempt to read outside the allowlist is denied with a `path_denied` event.
Brought early so every later increment is trialed confined.

**Build (server):**
- Parse `tools.agent.sandbox` in `config/tools.py` (`get_agent_config`) as
  built (v1.19.1, ADR 0010: moved to `execution.task.sandbox`, read via
  `config/execution.py::get_execution_task_config`):
  `workdir{root,writable,cleanup}`, `read_paths{allow,deny,follow_symlinks}`,
  `skills_dir`, `specs_dir`, `allow_skill_scripts`, `enforcement:"in_process"`.
  (Ship the `container` sub-block **schema** but leave it inert.)
- **New primitive** — read-path jail in `ScopedToolManager`: resolve every
  path arg of `read_file`/`grep`/`list_directory`/`write_file`/`apply_patch`
  and check it against `read_paths` (deny wins; symlinks resolved then
  re-checked) and the per-run `workdir` (the only writable root). Off-scope →
  denied + `path_denied` event, same shape as `tool_denied`.
- Per-run `workdir` = `sandbox.workdir.root/{run_id}/work`, created at
  `start_run`, cleaned per `cleanup`.
- **`--work-dir <path>` flag (2026-07-12, post-T8a):** clients thread the
  session working dir by default; the server only honors it when this T2
  seal is OFF — sealed runs keep their jail regardless, and the launch
  response flags `workdir_ignored` so the client can surface it.

**Trial:** set `read_paths.allow: ["~/.ppxai/skills"]`; `/task run "read
/etc/hosts" --tools read_file` → denied; `/task run "read the file
~/.ppxai/skills/x.md" --tools read_file` → ok; a `write_file` outside
`workdir` → denied.

**Tests:** path-jail unit suite (allow/deny/symlink-escape/`..`-escape/absolute
vs relative/workdir write); config-parse defaults; a run-level test asserting
`path_denied` fires and the tool never executes.

**Deliberately NOT yet:** container enforcement (T9); skill mounting (T4).

---

## T3 — spec files: `--spec` · `--system-file` · `--batch` — ✅ DONE (`--spec`); `--system-file`/`--batch` deferred to T3.b

**Shipped:** `engine/agent_spec.py` (loader: md front-matter / json / yaml /
jsonl-batch → `AgentSpec`, size-bounded, clear errors); `/v1/agent/task` gains a
`spec` NAME field resolved under `execution.task.sandbox.specs_dir` (name-only,
path-escape + containment guarded, 400 on any problem) with **precedence
request > spec > default_subagent** (`execution.default_subagent`) and the
ceiling clamp run on the MERGED grant (shell-in-spec
→ 400; empty merged grant → 400; no-spec-no-tools still → 422 via a
`model_validator`, preserving the invariant). Web client `--spec <name>`
(task-controller flag + pane reflects the server-merged meta). Tests:
`test_agent_spec.py` (22 loader), `test_agent_runs.py::TestTaskSpecFiles` (9
route), `test_task_controller_behavior.py` scenario 3b.

**Deferred to T3.b (client-only conveniences, browser File-API reads):**
`--system-file` (prose file → `system`) and `--batch <file.jsonl>` (one run per
line). The loader already parses jsonl (`load_batch_lines`) and prose-as-system
(a `.md` with no front-matter), so T3.b is client glue: read the local file in
the browser and either inline `system` or fan out N `/task` POSTs. Not
headless-testable, hence split from the load-bearing server slice.

**Capability:** configure a run from a file — `.md` (YAML front-matter +
body), `.json`/`.yaml`, or `.jsonl` (batch fan-out).

**Build:**
- Spec loader (`engine/agent_spec.py`): normalize `.md`/`.json`/`.yaml` → the
  agent-spec schema (task, system, tools, provider, model, budget, network,
  read_paths). Reuse `bootstrap.py::_parse_yaml_front_matter` for front-matter;
  body → `system`.
- Client: `--spec <path>` (local: server reads under
  `execution.task.sandbox.specs_dir` by **name**; remote/web: client reads +
  **inlines** into the request), `--system-file` (prose → `system`),
  `--batch <file.jsonl>` (one run per line).
- Precedence: CLI flags > `--spec` > server `default_subagent`
  (`execution.default_subagent`); clamped by the operator ceiling (allowed
  grant · no-shell · `execution.task.enabled`).

**Trial:** author `specs/triage.md` (front-matter grant+budget, body =
instructions); `/task run --spec triage "the CI job is red"`; confirm the
pane shows the grant/budget from the file. `--batch three.jsonl` mints 3 runs.

**Trial-verified 2026-07-12 (macOS, auth-ON):** API trial against the installed
server with a `server.secrets` file token store. Bootstrap-minted a bearer
(`POST /v1/tokens`), launched `--spec triage`; the run meta carried the
spec's `tools:[read_file,grep,list_directory]` + `budget:{iters8,time120}`,
while a request `provider/model` override beat the spec (precedence). Lifecycle
`completed_pending_ack → ack → finalized`; the `rejected-shell` spec 400'd on
the shell-grant ceiling clamp. Runnable recipe (auth-off and auth-on variants):
`examples/task-specs/README.md`.

**Tests:** loader unit tests (md front-matter, json, jsonl, missing/oversized,
bad yaml); precedence-merge tests; ceiling-clamp test (spec asking for a tool
outside the operator's allowance is refused).

**Deliberately NOT yet:** skill directories (T4).

---

## T4 — skills: `--skill <name>` (references mounted into read-scope) — ✅ DONE

**Capability:** `--skill ci-triage` loads `SKILL.md` as the spec **and** mounts
the skill's `references/` into the run's read-scope; `scripts/` stay inert.

**Build (landed):** `engine/agent_skill.py` (`load_skill` — reads `SKILL.md`
through the T3 loader, detects `references/`/`scripts/`); route
`_resolve_named_skill` resolves `--skill <name>` under `sandbox.skills_dir`
(name-only, symlink-contained — shares `_reject_unsafe_name`/`_within_root`
with the T3 spec resolver); `_load_skills` refuses a `scripts/`-bearing skill
unless `allow_skill_scripts` is on. `_merge_task_fields` unions every skill's
grant into the effective grant and returns `read_roots`; the route threads
those through `build_task_runner(extra_read_paths=…)` →
`build_filesystem_policy(extra_read_paths=…)` (T2 enforcement). Multiple
`--skill` compose (grants union + read-roots union, still ⊆ ceiling — the
shell-reject/non-empty/provider guards run on the MERGED grant). Web client:
`--skill` flag (repeatable + comma-split, de-duped) in `task-controller.js`.

**Trial:** point `sandbox.skills_dir` at `examples/task-skills/` (with
`enforcement:"in_process"`); `/task run --skill ci-triage`; confirm the agent
reads `references/checklist.md` but a read of a sibling outside the skill dir is
denied. `--skill needs-scripts` → 400 (scripts gate). Examples ship in
[examples/task-skills/](../examples/task-skills/) (ci-triage, secrets-scan,
needs-scripts + README recipe), loader-verified.

**Trial-verified 2026-07-12 (macOS, auth-ON, `enforcement:in_process`):** API
trial against the installed server (isolated `PPXAI_CONFIG_FILE` with the seal
on). `skills:["ci-triage"]` → run meta carried the SKILL.md grant
`[read_file,grep,list_directory]` + budget `{iterations:8}`; the agent read the
mounted `references/checklist.md` in-scope (no denial), while a forced read of
an out-of-scope path (repo `README.md`) emitted a `path_denied`
(`"path is outside the run read scope"`) — the seal held. Compose
`skills:["ci-triage","secrets-scan"]` → grant union `[grep,list_directory,read_file]`.
`skills:["needs-scripts"]` → 400 (`scripts/ … cannot run in the in-process
tier`, `allow_skill_scripts` off). Auth-aware recipe:
`examples/task-skills/README.md`.

**Tests (landed):** `test_agent_skill.py` (8 — loader: manifest→spec,
read_root, references present/absent, missing/malformed manifest, scripts
detection); `test_agent_runs.py::TestTaskSkills` (11 — resolution-by-name +
path-escape, not-found, no-manifest, scripts refuse/allow, shell-in-skill
clamp, no-source-422, grant supply, multi-skill union, request∪skill);
`test_filesystem_policy.py` (2 — `extra_read_paths` mounts skill scope /
siblings denied, None is no-op); `test_task_controller_behavior.py` (scenarios
3c/3d — `--skill` parse + body).

**Deliberately NOT yet:** runnable skill scripts (needs T9 container tier).

---

## T5 — interactive consent: `waiting` + `POST /respond` — ✅ DONE

**Capability:** a run that needs a human **parks** instead of hard-denying; the
pane shows a consent card; `/task respond <id> approve|deny|"<text>"` (or the
button) resumes it.

**Build (landed, server):** `waiting` status (non-terminal — stays in the
AppState badge mirror) + `agent_waiting`/`agent_resumed` events
(category=`consent`, token rides the event data); `AgentRunRegistry.park_run`
(resume token + TTL; timeout → denial, fail-closed; a cancel resolves the
waiter promptly instead of idling out the TTL) + `respond_run` (token-checked);
`POST /runs/{id}/respond` (`waiting → running`, owner-scoped 403, 409 on
not-parked / token mismatch / already answered / parked-before-restart);
`RunMeta.waiting` + the meta projection carry {kind, prompt, token, since,
expires_at, ttl_s}. The **existing** spawn-consent seam (previously auto-denied
over HTTP) now parks in `waiting{consent}` under `spawn_consent:"deny"`;
`"auto"` still skips the park. TTL: `execution.task.consent.consent_ttl_s`
(default 300 s).
**Client (landed):** consent card (prompt + Approve/Deny + optional note field,
built with safe DOM methods — the prompt embeds model-derived text) in
`TaskRunView`, raised by the SSE `agent_waiting` / meta `waiting`, cleared on
resume; `/task respond` verb (approve/deny words → `approved`, else free text);
✋ waiting status in pane + `ls` rows.

**Persistence (landed — debt (r), `state.json`, Inspection Triplet 3rd file):**
`AgentRunStore.persist_state/load_state` + the `FilesystemAgentRunStore`
implementation (atomic write, shared with `meta.json`); written when a run
enters `waiting` and updated on resume (`last_response`). Flat `agent-0/` slot
only. The park's *future* is in-memory — a parked run does not survive a
restart in flight; its checkpoint does (T7 `/resume` is the consumer). This
retires debt (r) as a standalone item.

**Trial (concrete recipe):**

1. Config (`~/.ppxai/ppxai-config.json` → `execution.task`): `enabled:
   true`, a working `execution.default_subagent` {provider, model}, and
   `consent.spawn_consent` left at its default `"deny"` (that IS the park
   mode now). Optionally `consent.consent_ttl_s` (default 300) — set it low
   (e.g. 30) to trial the timeout.
2. Serve the checkout (an installed `~/.ppxai/web` bundle won't have the
   consent card): `PPXAI_WEB_DIR=$PWD/ppxai/web uv run ppxai-server`, then
   open the web UI. (Config/env shadowing gotchas: see the T1 "trialing from
   source" note in [agent-platform-call-graphs.md](agent-platform-call-graphs.md).)
3. **Park:** `/task run "spawn a child to summarize docs/README.md" --tools
   read_file,spawn_subagent` → pane status flips to ✋ waiting and the consent
   card appears (prompt = the spawn summary); `/task ls` shows ✋.
4. **Approve:** click Approve (or `/task respond <id> approve`) →
   `agent_resumed` in the live log, the child spawns (`subagent_spawned`),
   the parent completes with the child's result embedded.
5. **Deny:** rerun step 3, click Deny (or `/task respond <id> deny`) →
   visible `spawn_denied` in the log; the run completes with the refusal
   text; no child appears in `/task ls`.
6. **Timeout:** rerun step 3 with a low `consent_ttl_s`, answer nothing →
   after the TTL the run resumes on its own with a denial
   (`agent_resumed {via:"timeout", approved:false}`).
7. **API-level checks (curl/PowerShell):** `GET /v1/agent/runs/<id>` while
   parked shows the `waiting` block incl. `token`; `POST .../respond` with a
   wrong token → 409; with `{token, approved:true}` → 200 `{status:running}`;
   `~/.ppxai/runs/<id>/agent-0/state.json` holds the waiting checkpoint and,
   after resume, the `last_response`.

**Trial-verified 2026-07-12 (macOS, auth-ON):** API trial via
`scripts/trial-task-lifecycle.py` against the installed server. A
`spawn_subagent` grant under `spawn_consent:"deny"` parked the run in
`waiting{consent}` (token present); `POST /runs/{id}/respond` with a wrong
token → 409, with `{token, approved:true}` → 200, and the approved run ran to
a terminal state.

**Tests (landed):** `test_agent_runs.py::TestStateJson` (5 — roundtrip/replace,
missing/corrupt/non-dict → None, atomic no-tmp); `TestParkRespond` (7 —
approve roundtrip incl. state.json + consent-category events, token
mismatch survives park, TTL denial + late respond, never-parked, cancel
unblocks park, park refused when cancel already pending);
`TestRespondRoute` (4 — 404, 409 not-waiting, 422 answer-less, meta carries
waiting); `TestConsentParkE2E` (3 — park→approve→child spawns,
park→deny→`spawn_denied` + no child, unanswered park times out to denial;
context-managed TestClient so the parked task survives across requests);
`TestAgentConfig` (2 — `consent_ttl_s` whitelist); `test_task_controller_behavior.py`
scenarios 9/9b (respond mapping, token fetch, not-waiting guard, routing).

**Deliberately NOT yet:** two-phase termination (T6); ask-user
`waiting{input}` parks (the wire + registry already carry `text`/`kind`).

---

## T6 — two-phase termination: `completed_pending_ack` + `POST /ack` — ✅ DONE

**Capability:** a finished run **holds its result** until collected, so a
disconnected UI never loses it; `/task ack <id>` (or the pane's Collect
button) finalizes.

**Build (landed, server):** `hold_result` on `RunMeta`/`start_run` — set by
the `/task` route for **top-level** runs only (sub-agent children and the
tool-free `/run` tier still land `completed`: their parent/caller collects
inline). On success a held run lands **`completed_pending_ack`** and emits
`agent_result_ready` (category=`result`) *instead of* `agent_run_complete`;
the run has exited (control/sandbox torn down, out of the AppState badge set)
but the record + result persist. `POST /runs/{id}/ack` (owner-scoped 403,
404/409) → `AgentRunRegistry.ack_run` → **`finalized`** + `agent_run_finalized`
(idempotent: re-acking a finalized run is 200, no duplicate event). Retention
backstop: `execution.task.budgets.result_retention_s` (default 3600 s, 0 disables) via
`maybe_reap_hold` — a **lazy reaper on the GET read paths** (no timer task; an
expired hold finalizes with `via:"retention"` the next time anyone looks).
Finalizing never deletes data — it marks the run GC-eligible; `acked_at` on
the meta projection records collection. **Explicit collect, not silent
auto-ack** — the user issues the receipt (matches the trial below).
**Client (landed):** Collect button in `TaskRunView` (visible only while
`completed_pending_ack`); `/task ack <id>` verb; 📬 result-ready / ✅ collected
status labels + `ls` icons; watcher/poll terminal sets grew
(`completed_pending_ack`/`finalized` statuses; `agent_result_ready`/
`agent_run_finalized` stream markers); held/finalized runs render their result
like `completed`.

**Persistence (landed — debt (r), cont.):** `persist_state()` snapshots the
hold (`{status: completed_pending_ack, result_ready_at, result_chars}`) and
the finalization (`{status: finalized, via, acked_at}`) — with `meta.json`
(which carries the result body) a held run survives a restart and reopens
intact. Still flat `agent-0/`. Remaining under (r): **T7** consumes the
checkpoint (resume = reload `state.json`).

**Trial (concrete recipe):** config as in the T5 trial (tier on,
`default_subagent` set); serve the checkout (`PPXAI_WEB_DIR=$PWD/ppxai/web
uv run ppxai-server`).

1. `/task run "summarize docs/README.md" --tools read_file` → on finish the
   pane shows 📬 result ready + the held result + a Collect button;
   `/task ls` shows 📬.
2. **Close the pane, reopen via `/task ls`** — the result is still there
   (served from `meta.json`; nothing was lost by disconnecting).
3. `/task ack <id>` (or Collect) → `✅ collected`; `GET /runs/<id>` shows
   `status:"finalized"`, `acked_at` set, result still present; a second ack
   is a no-op 200.
4. Retention: set `execution.task.budgets.result_retention_s` low (e.g. 30), run
   another task, wait past the TTL, then `/task ls` — the run shows
   finalized (reaped on read, `agent_run_finalized {via:"retention"}` on its
   event log).
5. API-level: `~/.ppxai/runs/<id>/agent-0/state.json` shows the
   `completed_pending_ack` snapshot, then `finalized` after ack.

**Trial-verified 2026-07-12 (macOS, auth-ON):** via
`scripts/trial-task-lifecycle.py`. A top-level `/task` run held its result
(`completed_pending_ack`, result body present); `POST /runs/{id}/ack` → 200 →
`finalized` with `acked_at` set and the result still present; a second ack was
an idempotent 200.

**Tests (landed):** `test_agent_runs.py::TestHoldAndAck` (7 — hold lands
pending_ack + state.json snapshot + result_ready-instead-of-complete + badge
exit, no-hold still completes, ack transition + idempotency (single finalize
event), non-held/unknown ack rejected, reaper expires only stale holds,
reaper disabled at 0/None); `TestAckRoute` (4 — 404, 409 not-held,
ack→finalized + result retained + idempotent 200, GET reaps expired holds on
single + list reads); `TestDisconnectThenCollectE2E` (1 — run finishes with
no client attached, held result collected later, then finalized; ctx_client);
`TestAgentConfig` (2 — `result_retention_s` whitelist);
`test_task_controller_behavior.py` scenario 10 (ack POST + verb routing).
Existing /task success assertions updated `completed` →
`completed_pending_ack` (the T6 semantic change).

**Deliberately NOT yet:** interrupted-resume (T7); artifact GC (finalized =
GC-eligible marker only); auto-ack-on-view (explicit collect keeps the
receipt in the user's hands — revisit if the friction annoys).

---

## T7 — interrupted resume: `POST /resume` — ✅ DONE

**Capability:** an `interrupted` run (engine restart / kill / budget cap) can be
**conditionally** resumed; `/task resume <id>` (or the button) continues it, or
refuses with a reason if the checkpoint is inconclusive (open-decision #5).

**Build (landed, server):** `POST /runs/{id}/resume` (owner-scoped 403; same
`execution.task.enabled` 403 gate as POST /task — resume re-enters the tool tier;
404/409). The decision matrix is `resume_refusal()` (pure meta rules): only
`interrupted`/`cancelled` + `resumable` + **top-level /task** (`hold_result`)
runs with no recorded `result` and complete rebuild inputs; everything else is
refused with the stated reason and the run is unchanged. Resume REBUILDS the
scoped runner via `build_task_runner` from the **persisted inputs** — task/
grant/egress/budget were already on the meta; T7 adds `system` + `read_roots`
(the T4 skill mounts) to `RunMeta` so the rebuild is faithful — and
`resume_run()` clears the stale stop fields, snapshots `state.json`
(`resumed_from`), emits `agent_run_resume`, and drives it like a fresh run
under the SAME run_id (identical AC-1/AC-2 sandbox, fresh budget window,
events append to the same log — seq continues; a T6 hold applies to the
resumed leg too). **Restart-orphan sweep:** `sweep_orphans()` runs once at
registry construction — any run stranded `pending/running/waiting/cancelling`
on disk (its task/control/consent future died with the process) lands
`interrupted` ("server restarted…", `resumable` iff the checkpoint is
conclusive), with a `state.json` `via:"restart_sweep"` snapshot + event. A
resumable stop (cancel/budget) now also writes its own `state.json` checkpoint
at stop time. **Client (landed):** Resume button in `TaskRunView` (visible only
when `resumable` AND `interrupted`/`cancelled`); `/task resume <id>` verb;
resume restarts the detached watcher; the 409 refusal reason is surfaced
verbatim; `agent_run_resume` gets a transcript line.

**Persistence (debt (r) — RETIRED):** T5 wrote the park checkpoint, T6 the
hold/finalize snapshots, T7 adds the stop + restart-sweep + resume snapshots
AND is the consumer. The Inspection Triplet is complete on the flat `agent-0/`
slot (the multi-slot/service Triplet remains (q)/`agent_n` nesting).

**Trial (concrete recipe):** config as in T5/T6 (tier on, `default_subagent`).

1. **Restart-interrupt:** start a run that stays busy (e.g. `/task run
   "spawn a child to summarize docs/README.md" --tools
   read_file,spawn_subagent` and leave the consent card unanswered, or any
   long run), then kill the server mid-flight. Restart it → `/task ls` shows
   the run **⏸️ interrupted** ("server restarted…"), with a Resume button on
   its pane (the sweep judged it resumable).
2. **Resume:** `/task resume <id>` (or the button) → `▶️ resumed (running)`;
   the run re-executes with the same grant/egress/budget/system and lands
   📬 result ready (T6 hold) — same run_id, same event log (`agent_run_resume`
   visible in it).
3. **Budget-interrupt path:** `/task run "…" --tools read_file --budget
   iters=1` → lands ⏸️ interrupted (resumable); `/task resume <id>` gives it a
   fresh budget window and it completes.
4. **Refusals:** `/task resume` a completed/held run → 409 "not resumable";
   resume an `/agentrun`-tier cancelled run → 409 "only a top-level /task
   run…"; after a successful resume completes and you re-resume → 409 "work
   already captured".
5. API-level: `state.json` shows the stop checkpoint, then
   `{status: running, resumed_from: interrupted}` after resume.

**Trial-verified 2026-07-12 (macOS, auth-ON):** via
`scripts/trial-task-lifecycle.py`, restart-interrupt path. A consent-parked
run had the server killed under it and restarted; the registry's
construction-time `sweep_orphans()` landed it `interrupted` + `resumable:true`;
`POST /runs/{id}/resume` → 200 re-entered the tool tier under the same run_id
and the run reached a terminal state; the refusal arm (`resume` a `finalized`
run) → 409. **Investigation note:** an earlier trial appeared to show a
`waiting` run NOT being swept — that was a **test-harness bug, not a product
one**: the installed `ppxai-server` is a PyInstaller onefile (bootloader
parent + real-server child), so `Popen.terminate()` on the parent left the
child holding the port; the "restarted" server couldn't bind and the GET hit
the stale old process where the sweep never ran (`resumable:false` was the
tell). Fixed by killing the whole process group (`start_new_session` +
`os.killpg`); the sweep itself works exactly as documented. See
[docs/lessons/stale-server-invalidates-acceptance.md](../docs/lessons/stale-server-invalidates-acceptance.md).

**Client observation 2026-07-12 (VSCode, auth-ON):** a `/task resume` of an
interrupted run refused with *"not marked resumable (the stop did not land at a
clean checkpoint)"* — **correct behavior, not a bug.** The target run was
created **2026-07-02, before T6 landed (2026-07-07)**, so its meta has
`hold_result=False` and the sweep can never mark it resumable; a same-day run
created by the current binary had `hold_result=True` and resumed fine. Only
runs stranded from a pre-T6 binary hit this. Minor UX polish (not scheduled):
the refusal reason could distinguish "created before resume support" from
"stopped uncleanly."

**Tests (landed):** `test_agent_runs.py::TestResumeRefusal` (9 — the full
decision matrix incl. every non-candidate status, in-flight, non-task,
result-present, missing inputs); `TestSweepOrphans` (4 — all orphanable
statuses swept with state.json/event + terminal untouched, resumable
judgement, in-flight-not-swept, idempotent); `TestResumeRoute` (5 — tier-gate
403, 404, 409 leaves run unchanged, /run-tier refused, e2e rebuild-from-
persisted-inputs → resumed leg holds + same-log seq monotonic; ctx_client);
`test_task_controller_behavior.py` scenario 11 (resume POST + watcher restart
+ routing + verbatim refusal).

**Deliberately NOT yet:** cross-client port (T8); transcript-level
continuation (a resume re-executes the bounded task from its start — the
conversation state of the dead leg is not replayed; the run record, not the
chat transcript, is the durable unit).

---

## T8 — cross-client port: TUI + VSCode — SPLIT into T8a / T8b

The two clients have opposite transport realities, so T8 lands in two
independently-trialable halves:

- **T8a — VSCode (✅ DONE):** the extension already speaks
  HTTP to ppxai-server (`httpClient.ts`), so the port is a faithful mirror
  of the web client over the identical `/v1/agent/*` surface.
- **T8b — Rich/Textual TUI (✅ DONE — unparked 2026-08-08, option (1) chosen; see §T8b below):** the TUIs
  are **in-process** — they have NO channel to a ppxai-server. Porting `/task`
  there forces the transport decision that is debt Item 37(t)'s SDK question:
  **(1)** embed the registry + an embeddable `build_task_runner` in-process
  (runs live in the TUI's event loop; retires (t) as a by-product — the
  recommended direction, since it also unblocks the ppxai-sre SDK model), or
  **(2)** grow an HTTP client in the TUIs pointed at a running server
  (matches the plan's original "identical surface" wording but adds a
  server dependency to standalone terminal use). Decide before building;
  do NOT guess this one silently. **Resume checklist:** pick the transport →
  if (1), first extract `build_task_runner` from `server/routes/agent_v1.py`
  into an engine-level module (that IS the debt-(t) work; keep the route a
  thin caller so the T1–T7 tests stay green) → then Rich + Textual `/task`
  handlers + per-TUI run view + consent affordance → extend the T8a parity
  sentinels (`tests/test_vscode_task_controller.py` pattern) to the TUI
  dispatch surface.

### T8a — VSCode port — ✅ DONE

**Build (landed):** `vscode-extension/src/taskController.ts` — a
dependency-injected (IoC, same pattern as `handlers/consent.ts`), VSCode-free
controller with **verb-for-verb parity** with the web client
(run/ls/list/show/open/watch/cancel/respond/ack/resume/help; the same
`parseTaskArgs` grammar incl. `--spec`/`--skill`/`--budget`/`--work-dir`
suffixes).
`httpClient.ts` grows the typed `/v1/agent/*` slice (agentTask/agentRuns/
agentRun/agentRunCancel/agentRunRespond/agentRunAck/agentRunResume) with the
tier's guardrail 4xx `detail` bodies surfaced **verbatim** (403 tier-off
hint, 400 shell-grant, 409 respond/ack/resume refusal reasons).
`chatPanel.ts` routes `/task` client-side BEFORE factory dispatch (the
CommandFactory has no /task) and wires the UI adapter: transcript output via
`systemMessage`/`fullResponse`, and — per VSCode idiom — the **T5 consent
park pops a native QuickPick** (Approve/Deny; same dialog pattern as
shell/file consent), raised automatically by the poll watcher once per
resume token; a dismissed dialog leaves the TTL as the fail-closed backstop
(`/task respond` still works). The watcher is poll-based with the web
degraded-path contract (backoff, no run-duration ceiling, give-up only on
consecutive GET failures); terminal renders include the 📬 `/task ack` and
▶️ `/task resume` hints. `/task` added to the completion catalog
(`engine/completion.py`) for all clients.

**Trial (concrete recipe):** server as in T5–T7 trials (tier on,
`default_subagent`); `code --install-extension` a fresh VSIX or F5 the
extension; point `ppxai.serverUrl` at the server.

1. In the VSCode chat panel: `/task run "summarize docs/README.md" --tools
   read_file` → launch line, then (poll) 📬 result ready + the result +
   the `/task ack` hint; `/task ack <id>` → ✅ collected.
2. `/task run "spawn a child to summarize docs/README.md" --tools
   read_file,spawn_subagent` → when the run parks, a **QuickPick pops**
   (✋ Agent run … needs consent) → Approve → child spawns, parent holds;
   Deny → refusal text; Escape → hint line + TTL backstop
   (`/task respond <id> approve` still answers it).
3. `/task ls` shows the same runs (and icons) as the web pane; kill/restart
   the server → ⏸️ interrupted → `/task resume <id>` → continues.
4. 403/400/409 guardrails (tier off, shell grant, wrong-token respond,
   re-resume after success) all show the server's own reason text.

**Tests (landed):** `tests/test_vscode_task_controller.py` (11 structural —
the repo's TS-testing idiom, see test_vscode_visibility_reanchor.py):
**verb-parity sentinel** (VSCode routes exactly the web verb set),
**endpoint-parity sentinel** (both clients drive the same `/v1/agent/*`
paths; TaskBackend methods exist on httpClient), **status-parity**
(terminal/success sets match the web sets), chatPanel wiring
(task-before-factory, controller construction, QuickPick → `{approved}`),
consent-token discipline (park token rides every respond; one QuickPick per
park). Plus `npm run compile` (tsc + esbuild) green.

### T8b — TUI port — ✅ DONE (unparked 2026-08-08, closed 2026-08-11)

**Transport decided: EMBED** (option 1). `build_task_runner` was extracted to
`ppxai/engine/task_runner.py` (`eeb82076`), retiring debt (t) and giving
ppxai-sre the embeddable runner as the plan predicted.

| Piece | State |
|---|---|
| Embeddable runner | ✅ `eeb82076` — seam verified 9/9 byte-identical |
| In-process backend | ✅ `d2886958` — `engine/task_backend.py`, full lifecycle with no server |
| U2 grammar, shared with the web client | ✅ `1615b9d1` — `engine/task_grammar.py` + parity sentinels |
| `/task` + `/run` command handlers | ✅ `f3b42a63` — registered in `CommandFactory` |
| Run view per TUI idiom | ✅ `6ddc1dc0` — `TableResult` already routed to the side panel; what it needed was a focus opt-out so a run list does not steal the cursor |
| Consent affordance (T5 park) | ✅ `2e32b02a` — `RunConsentScreen` + a single watcher, one prompt per park token, Escape defers rather than denies |
| T8a-style parity sentinels vs the web verb set | ✅ `defc13cc` — every grammar verb is handled; chain is web JS ↔ engine grammar ↔ TUI handler |
| Third-client defect sweep (RED→GREEN) | ✅ `f3cf3d53` (one failing sentinel per defect) → `394bdf1f` (U4 merge, lifecycle wiring, discoverability) — the last T8b gaps |

**Availability is gated per VERB on a capability, not per client.** Launch and
resume need a live event loop; `ls`/`get`/`cancel`/`collect`/`respond` are
synchronous registry operations. So Textual has the full set today, and Rich
has everything except launch/resume — with a message naming the reason rather
than the command being absent. Rich's remaining half is its blocking prompt
(`main.py:477`) plus five `asyncio.run()` call sites; that is a main-loop
decision, not a `/task` decision, and it is still open.

Two things found while unparking, both fixed: the engine-level egress-ceiling
gap (`82ae0bcb` — the ceiling was route-only, so an embedded run escaped it),
and the completion gating that hid `/task` from the TUIs, which was correct
before the embed and wrong after.

---

## T9 — (future, tier-d) container enforcement

Deferred with the OS-isolation tier. Flip `sandbox.enforcement:"container"`:
the T2 scoping fields become real OS boundaries — read-only root fs, `workdir`
= pod `emptyDir`, **skills/specs = read-only ConfigMap mounts**, egress = a k8s
NetworkPolicy, and `allow_skill_scripts` becomes runnable. The config schema
(T2) already anticipates this; no new config surface, only the enforcer. This
is the tier that lets `/task` accept **untrusted** input and become sealable.

---

## Dependency summary

```
T1 launch/observe ─┬─► T2 read_paths seal ─┬─► T3 spec files ─► T4 skills
                   │                        │
                   ├─► T5 waiting/respond   │   (T4 needs T2 + T3)
                   ├─► T6 pending_ack/ack    │
                   └─► T7 interrupted/resume ┘
                                  │
                                  ▼
                     T8 TUI + VSCode port
                                  │
                                  ▼
                     T9 container enforcement (tier-d, future)
```

T2–T7 each depend only on T1 (a `/task` run to drive) except T4 (needs T2 + T3).
Order is value + safety first: launch, then the seal, then config (spec/skill),
then the lifecycle transitions, then ports. Every increment is independently
live-trial-verified before the next begins.

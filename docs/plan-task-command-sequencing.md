# `/task` command — incremental build plan

Sequencing plan for the interactive **`/task`** command family (design:
[agent-task-command-design.html](agent-task-command-design.html); lifecycle:
[agent-task-lifecycle.html](agent-task-lifecycle.html); architecture:
[decisions/0003-agent-platform-architecture.md](decisions/0003-agent-platform-architecture.md)
§8–§9). Same contract as the Stage-2 increment plan
([plan-v1.19.0-sequencing.md](plan-v1.19.0-sequencing.md)):

> **Build contract.** Each increment is a **vertical slice** that brings
> exactly the server + client bits needed to **live-trial it end-to-end**,
> nothing speculative. Bring a seam early only when it's the right shape
> (e.g. the read-path enforcement point). **Web first** — TUI + VSCode are a
> late port. Every increment ships with tests and a concrete trial before the
> next one starts.

**Where we start.** The tool-capable tier already exists server-side:
`POST /v1/agent/task`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/events`
(SSE), `POST /runs/{id}/cancel`, owner-scoped authz, `task_tier_enabled`
default-off gate, no-shell rejection. There is **no `/task` client command in
any client** — `/agentrun` (tool-free) is the only agent slash command shipped.
So T1 is mostly client work over existing endpoints; new server machinery
arrives only where the lifecycle needs it (T5–T7) and where the filesystem
seal needs it (T2).

**Trial prerequisites (every increment).**
- Enable the tier: `tools.agent.task_tier_enabled: true` in `~/.ppxai/ppxai-config.json`.
- Run the web client against **live source**: `PPXAI_WEB_DIR=$PWD/ppxai/web uv run ppxai-server` (edits to `ppxai/web/` don't reach `~/.ppxai/web` otherwise — see `docs/lessons/web-assets-served-from-ppxai-home.md`).
- Trial with **auth disabled** (default — no `server.secrets` file store, `PPXAI_API_TOKEN` unset): `/task` is loopback-reachable without a bearer (`auth.py::check_request` → `if not is_auth_enabled(): return None`). A token-carrying web client for the auth-enabled case is a follow-up, not a blocker.
- Set a default subagent so a bare `--tools` launch has a provider/model: `tools.agent.default_subagent: {provider, model}`.

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
  `--provider`, `--model`, `--budget iters=,time=,tokens=`, `--system "…"`
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

## T2 — the seal: `read_paths` enforcement + `tools.agent.sandbox` (in_process) — ✅ DONE

**Shipped:** `89b18ac0` (+ `9bd8c790` call graph). `engine/tools/filesystem_policy.py`
(`FilesystemPolicy`), `config/tools.py` sandbox parsing (default `enforcement:"off"`
→ non-breaking), the `ScopedToolManager` path chokepoint (`path_denied`), and the
per-run workdir in `build_task_runner`. Live-trialed: allowed read → ok, `/etc/hosts`
→ denied; 24 unit tests. `container` sub-block schema defined but inert (T9).

**Capability:** a run can read/write **only** inside configured locations; an
attempt to read outside the allowlist is denied with a `path_denied` event.
Brought early so every later increment is trialed confined.

**Build (server):**
- Parse `tools.agent.sandbox` in `config/tools.py` (`get_agent_config`):
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
`spec` NAME field resolved under `sandbox.specs_dir` (name-only, path-escape +
containment guarded, 400 on any problem) with **precedence request > spec >
default_subagent** and the ceiling clamp run on the MERGED grant (shell-in-spec
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
- Client: `--spec <path>` (local: server reads under `specs_dir` by **name**;
  remote/web: client reads + **inlines** into the request), `--system-file`
  (prose → `system`), `--batch <file.jsonl>` (one run per line).
- Precedence: CLI flags > `--spec` > server `default_subagent`; clamped by the
  operator ceiling (allowed grant · no-shell · `task_tier_enabled`).

**Trial:** author `specs/triage.md` (front-matter grant+budget, body =
instructions); `/task run --spec triage "the CI job is red"`; confirm the
pane shows the grant/budget from the file. `--batch three.jsonl` mints 3 runs.

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

## T5 — interactive consent: `waiting` + `POST /respond`

**Capability:** a run that needs a human **parks** instead of hard-denying; the
pane shows a consent card; `/task respond <id> approve|deny|"<text>"` (or the
button) resumes it.

**Build (server):** `waiting` status + `AGENT_WAITING` event (tagged run_id) +
a resume token + TTL park/resume in the registry; `POST /runs/{id}/respond`
(`waiting → running`, token-checked, owner-scoped). Redirect the **existing**
spawn-consent seam (`agent_spawn.py::request_consent`, today auto-denied over
HTTP) to park in `waiting{consent}` and await `/respond`. **Client:** consent
card (Approve/Deny) + input field in `TaskRunView`; `/task respond`.

**Persistence (absorbs debt (r) — `state.json`, Inspection Triplet 3rd file).**
A parked run IS a checkpoint that must survive a restart, so this increment
lands the first `state.json` write: add `AgentRunStore.persist_state(run_id,
state)` (the slot dir + `_slot_dir()` already exist; `meta.json`/`events.jsonl`
are the other two Triplet files) and write it when a run enters `waiting`. Flat
`agent-0/` slot only — the multi-slot/service-state Triplet stays deferred to
(q)/`agent_n` nesting; this is the run's own lifecycle state, nothing more. This
retires debt (r) as a standalone item and fulfils the `FilesystemAgentRunStore`
docstring's "state.json arrives in Inc 2-3" — correct that comment when you land it.

**Trial:** with `spawn_consent` requiring approval, `/task run "spawn a child to
summarize docs/README.md" --tools read_file,spawn_subagent`; the run parks
(pane shows Approve/Deny); `/task respond <id> approve` → the child spawns and
the parent continues; `deny` → visible `spawn_denied`.

**Tests:** park/resume unit (token match/mismatch/expiry; owner scope); event
`AGENT_WAITING` emitted; `/respond` transition + 404 on unknown/foreign run;
consent-card behavioral test.

**Deliberately NOT yet:** two-phase termination (T6).

---

## T6 — two-phase termination: `completed_pending_ack` + `POST /ack`

**Capability:** a finished run **holds its result** until collected, so a
disconnected UI never loses it; `/task ack <id>` (or auto-ack on view) finalizes.

**Build (server):** `completed_pending_ack` status + `AGENT_RESULT_READY`
event; the run exits (frees tokens/CPU, sandbox torn down) but the record +
artifacts persist; `POST /runs/{id}/ack` (`→ finalized`, GC-eligible) with a
**retention TTL** backstop. **Client:** result view + "Collect result"
affordance / auto-ack on pane view; `/task ack`.

**Persistence (debt (r), cont.).** The "record + artifacts persist after the run
exits" promise is the same `state.json` write introduced in T5 — reuse
`persist_state()` to snapshot the held result/terminal state so a
`completed_pending_ack` run survives a restart and reopens intact (the trial
below closes the pane and reopens via `/task ls`). Still flat `agent-0/`.

**Trial:** `/task run "summarize docs/README.md" --tools read_file`; on finish
the pane shows the held result; **close the pane, reopen via `/task ls`** — the
result is still there; `/task ack <id>` → finalized; confirm a later `ls` shows
it GC-eligible / gone after TTL.

**Tests:** terminal-hold unit (result persists post-exit); `/ack` transition +
idempotency; retention-TTL reaper; disconnect-then-collect behavioral test.

**Deliberately NOT yet:** interrupted-resume (T7).

---

## T7 — interrupted resume: `POST /resume`

**Capability:** an `interrupted` run (engine restart / kill / budget cap) can be
**conditionally** resumed; `/task resume <id>` (or the button) continues it, or
refuses with a reason if the checkpoint is inconclusive (open-decision #5).

**Depends on the `state.json` write from T5/T6 (debt (r)).** T7 is the *consumer*
of the checkpoint — "reload the run's checkpoint" IS reading the `state.json`
`persist_state()` wrote. T7 cannot land before that write exists, which is why
(r) is injected into T5/T6 (the producers) rather than filed standalone.

**Build (server):** `POST /runs/{id}/resume` — reload the run's checkpoint
(`state.json`), rebuild the scoped runner, continue; refuse (stay `interrupted`)
when the checkpoint isn't conclusive or artifacts already capture the work.
**Client:** Resume button shown only when `resumable`; `/task resume`.

**Trial:** start a long run, kill/restart the server to land it `interrupted`;
`/task resume <id>` → continues; force an inconclusive case → refused with the
stated reason.

**Tests:** conditional-resume decision matrix; runner rebuild from checkpoint;
`/resume` transition + refusal path.

**Deliberately NOT yet:** cross-client port (T8).

---

## T8 — cross-client port: TUI + VSCode

**Capability:** the full `/task` family in Rich/Textual TUI and the VSCode
extension, reusing the same endpoints and envelopes.

**Build:** TUI command handlers + a task-run view; VSCode `TaskController`
mirror + webview panel controls; both drive the identical `/v1/agent/*`
surface. Consent/ack/resume affordances per client idiom.

**Trial:** run T1–T7 trials from TUI and VSCode.

**Tests:** per-client dispatch + envelope tests; parity sentinel across clients.

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

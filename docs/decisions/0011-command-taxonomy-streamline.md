# ADR 0011 — Command taxonomy streamline (`/auto` · `/run` · `/task`)

**Date:** 2026-08-02
**Status:** **Accepted** (2026-08-02 — semantics converged and all five
sign-off questions answered by the owner in the same design session; the
"no cutting until crystal clear" gate is now open. Amends ADR 0009's config
key location — amendment note added there.) **Implemented 2026-08-02/03** —
Phase F (oneshot facade): F1 `abf83868`, F2 `8bcd8109`, F3 `26c26a19`, F4
`16b6091d`. Phase U (command surface rename): U1 `3fa55f3b`, U2 `e2690636`,
U3 `89d5c95c`, U4 `8867bc5c`. Phase FU (follow-up): `0c997df8`. All landed
on `bugfix/v1.19.1`.
**Related:**
- [`0003-agent-platform-architecture.md`](0003-agent-platform-architecture.md) — the run registry + `start_run` contract verb this taxonomy surfaces
- [`0009-task-execution-profiles.md`](0009-task-execution-profiles.md) §4 — enriched oneshot; step ① makes oneshot a facade over the run tier, which is what makes this streamline possible
- [`0010-config-shape-review.md`](0010-config-shape-review.md) — the `execution.*` axis where the collect config lives
- [`docs/plan-adr0009-step1-oneshot-enrichment.md`](../plan-adr0009-step1-oneshot-enrichment.md) — the facade plan (oneshot = a registry run awaited server-side)

---

## Context — the organically grown surface

Five names cover three-and-a-half concepts, and the word **"agent"** is
spread across three different things:

| Today | What it really is | Clients |
|---|---|---|
| `/agent <task>` / `on\|off` | **in-session** sync autonomous loop, checkpoint/undo, blocks chat (`commands/agent.py:767`) | Rich/Textual |
| `/tools …` (incl. `tools agent` subcmd) | chat-turn tool enablement + loop config | all |
| `/agentrun`, `/agentruns` | fire-and-forget **tool-free** background run (→ `/v1/agent/run`) | web |
| `/task run·ls·show·watch·cancel·respond·ack·resume` | **tool-capable sandboxed** lifecycle runs (→ `/v1/agent/task`) | web + VSCode |
| `POST /v1/oneshot` | stateless gateway call (becoming a run-tier facade, ADR 0009 step ①) | API |

Evidence of drift: `task-controller.js:218` literally tells users *"A
tool-free run belongs on /agentrun"* — a guard that exists only because two
surfaces grew side by side. `/run X` vs `/task run X` would have been a fresh
verb collision; `/agent` collides with the sub-agent tier, which is "more true
agent than the sync session tools loop steered by the model" (owner).

**The unlock:** once ADR 0009 step ① lands, *everything that executes outside
a chat turn is a registry run*, differing on two axes only — **grant** (none …
sandboxed tool set) and **ceremony** (one-off prompt vs managed lifecycle).
Oneshot, `/agentrun`, and `/task` are cells of one grid, not three mechanisms.
Name the mechanism once; distinguish by intent.

## Semantic ladder (vocabulary this ADR fixes)

- **run** — one execution instance in the registry (already the domain noun:
  `run_id`, `~/.ppxai/runs/`, `RunMeta`).
- **task** — a delegated work item (prompt + grant + spec/skill); its
  execution is a run.
- **agent** — the executor construct; "sub-agent" for spawned children.
  **Never a command name.** Survives only as the API/platform namespace
  (`/v1/agent/*`, "agent platform" in docs).

## Decision — the command taxonomy

| Command | Context | Mechanics | Semantics |
|---|---|---|---|
| `/auto <task>` | in-session, **sync** | today's `/agent` loop (checkpoint/undo), renamed | autonomy *in your context*; result lands in-session — **collect is implicit** |
| `/run <prompt>` | registry, **async** | full task gears, `kind=oneshot` | one-off: prompt-only ceremony, default grant, collect-back |
| `/task <prompt> [flags]` | registry, **async** | full task gears, `kind=task` | managed: specs/skills/grants, full lifecycle |
| `/tools …` | chat turns | unchanged (subcmd `agent` → `auto`) | tool enablement |

`/run` vs `/task` is **not a mechanics split** — same registry, same
`build_task_runner`, same events, same sandbox. It is a ceremony + intent
split carried by a discriminator (below). Retired: `/agentrun` → `/run`,
`/agentruns` → `/run ls` (deprecation aliases, one minor version).

### `kind` discriminator on `RunMeta`

- `RunMeta.kind ∈ {"oneshot", "task"}` — additive field; legacy metas without
  it read as `"task"`. Spawned children stay distinguished by
  `parent_run_id` (display unchanged).
- `/run ls` and `/task ls` are the same listing filtered by kind; additive
  query param `?kind=` on `GET /v1/agent/runs`.
- API-facade oneshots (ADR 0009 step ①) are `kind=oneshot` too — debuggable
  via `/run get <id>`, hidden from `/task ls` by construction.

### Launch grammar (direct launch — no `start`/`run` subcommand)

`/task "migrate the docs" --tools shell,editor` launches; `/task ls` manages.
Disambiguation rule: the first token is a **lifecycle verb** AND the remainder
is **id-shaped** (`run_` + 12 hex) **or empty** → lifecycle op; anything else
is a launch prompt. Run-id shape makes this collision-proof in practice;
quoting the prompt stays recommended, never required. Same rule for `/run`.

### Lifecycle verbs (shared implementation, per-family surface)

`ls · get · watch · cancel · collect · respond · resume · help`

- **`get` replaces `show`** (owner; also shrinks the verb-vs-prompt collision
  surface — prompts rarely start with "get run_…"). `show` stays as alias.
- **`collect` replaces `ack`** (T6): collect = finalize the held result
  **and merge it into the active session context**. `ack` stays as alias.
- `respond` (T5) and `resume` (T7) are shared dispatch; for `kind=oneshot`
  runs `respond` is unreachable by construction (`allow_spawn=False`, no
  consent path) and simply reports "not parked".

### Grants per surface (owner-decided, 2026-08-02)

| Surface | Grant | Consent |
|---|---|---|
| `/auto` | **tools on** (session tool set) | **ask per consent by default**; each prompt offers "always allow" scoped to *this* auto run |
| `/run` | **no tools by design**; `web_search` is the only tool that can appear in the allowed list, **enabled/disabled by JSON config** | n/a (no consentable tools; `allow_spawn=False`) |
| `/task` | **as working now** — explicit `--tools` / spec / skill grant | T5 respond/consent unchanged |

`/run`'s grant is therefore `{}` or `{web_search}` — never anything else, no
flag can widen it. This makes UX `/run` and the API oneshot facade
(ADR 0009 step ①) literally one brain: same kind, same grant rule, same
config gate.

### Collect semantics per surface (owner-decided, 2026-08-02)

| Surface | GUI (web / VSCode) | TUI (Rich / Textual) |
|---|---|---|
| `/run` | rendered in **side panel / split view**; **Collect button** merges into active session | JSON-config-driven: `auto` / `yes` / `no` |
| `/task` | **Collect button** merges into active session | same config as `/run` |
| `/auto` | n/a (in-session) | **implicit** — result is already in context |

Config key (ADR 0010 `execution.*` axis): **`execution.collect`** — one
global key covering `/run` + `/task`. Value semantics (decided):

- **`auto`** — the run **always auto-merges** into the active session on
  completion; no user step.
- **`yes`** — collect is **enabled**: the run holds its result and the user
  collects it explicitly (button / `collect` verb), which merges it.
- **`no`** — **no collect possible at all**: GUI renders the Collect button
  **greyed out/disabled**; TUI issues a warning that collect is disabled and
  tells the user the action to enable it (`execution.collect`) if desired.
  The result stays on the run record only.

Mechanically this rides the existing T6 machinery — no new lifecycle states:
`auto` → complete + merge + finalize in one motion; `yes` →
`hold_result=True`, collect = ack + merge; `no` → `hold_result=False`,
auto-finalize, merge path never offered.

**Merge payload (owner-decided): plain merge.** The run's result text enters
the active session as plain content — no provenance tagging, no special block
type. What the run answered is what the conversation sees.

### API mapping (wire stays put)

| UX intent | API |
|---|---|
| `/run <prompt>` | `POST /v1/agent/run` (or `/task` tier when a grant applies) with `kind=oneshot` |
| `/task <prompt> …` | `POST /v1/agent/task`, `kind=task` |
| external sync oneshot | `POST /v1/oneshot` — **frozen contract** (ppxai-sre byte-identical); the HTTP response *is* the collect; internally a `kind=oneshot` run (step ① facade) |

Principle: **UX commands name user intent; API paths name the subsystem**
(same reason `git branch` doesn't say `refs/heads`). The skew is principled
and documented, not accidental. No `/v1/*` path renames.

## Migration (owner-decided: clean break, NO deprecation aliases)

Hard rename in one coordinated sweep; **breaking changes are published in the
release notes** of the version that ships them. No alias layer, no
deprecation window — the old names simply stop existing:

- `/agent` → `/auto` · `/agentrun` → `/run` · `/agentruns` → `/run ls` ·
  `task show` → `task get` · `task ack` → `task collect` ·
  `tools agent` → `tools auto`.
- **Scope of the break is UX-only.** The API is untouched (`/v1/oneshot`
  frozen, `/v1/agent/*` paths unchanged) — ppxai-sre and any gateway consumer
  are unaffected. Only slash-command muscle memory breaks, and the release
  notes say so explicitly.
- Cheap by construction: CommandFactory registry + command envelope
  (`POST /command/<name>`) + single CompletionProvider mean the rename is a
  registry-level sweep. Moves in lockstep, same commit: T8a **parity
  sentinels** (VSCode↔web), completion data, `/task help` texts, docs.
- **Sequencing / T8b:** `/auto` (rename of `/agent`) lands everywhere at once
  — it's a commands/-layer rename shared by all clients. `/run` + the new
  `/task` verbs reach the TUIs only with T8b (transport decision, parked);
  until then the TUIs have `/auto` but no registry commands, which is a
  feature gap, not a dialect mismatch.

## Consequences

- One mechanism, one vocabulary: every out-of-turn execution is a run;
  "agent" stops being three things.
- `/task ls` stops being polluted by one-offs; `/run ls` gives oneshots their
  own list (`kind` filter).
- The `task-controller.js:218` guard ("tool-free belongs on /agentrun")
  disappears — `/run` takes tool-free one-offs; `/task` accepts any grant.
- Collect gets a definition (finalize + merge-to-context) instead of the
  protocol word `ack`; TUI behavior becomes a config, not a hardcode.
- Cost: muscle-memory retraining in web/VSCode; alias layer + parity
  sentinels + completion data all need one coordinated sweep.

## Sign-off record (all questions answered by owner, 2026-08-02)

1. **`/run` launch defaults** — no tools by design; `web_search` the only
   config-enableable tool (see "Grants per surface"). `/auto` = tools on with
   per-consent ask + "always allow for this run"; `/task` = as working now.
2. **`execution.collect`** — global key; `auto` = always auto-merge, `yes` =
   collectable, `no` = collect impossible (greyed button / TUI warning +
   enable hint). See "Collect semantics".
3. **Merge payload** — **plain merge**: result text enters the session as
   plain content, no provenance tagging.
4. **Deprecation** — **none**: hard rename, breaking changes published in the
   release notes. See "Migration".
5. **Config key location** — **`execution.run.*`**: the enrichment gate is
   `execution.run.web_search` (and the native-grounding switch migrates to
   `execution.run.grounding`), superseding ADR 0009's planned
   `execution.oneshot.*` names before anything was implemented (no
   migration). Amendment note added to ADR 0009. `/run`'s default budget
   (small iteration cap) is an implementation constant per ADR 0009 §4.

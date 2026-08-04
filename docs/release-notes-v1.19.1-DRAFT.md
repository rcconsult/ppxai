# ppxai v1.19.1 — release notes (DRAFT — accumulating until release)

> Working draft per the F/U sequencing plan: each U-stage lands its breaking
> changes here as it commits. Finalized (and renamed to
> `release-notes-v1.19.1.md`) by the `/release` flow.

## ⚠ Breaking changes (ADR 0011 — command taxonomy, hard rename, NO aliases)

The command surface is streamlined per
[ADR 0011](decisions/0011-command-taxonomy-streamline.md). Old names are
**removed**, not aliased. The **API is untouched** — `/v1/oneshot` and
`/v1/agent/*` keep their exact paths and shapes; only slash-command muscle
memory changes.

| Removed | Use instead | Since stage |
|---|---|---|
| `/agent <task>`, `/agent on\|off` | **`/auto`** — same in-session autonomous loop, checkpoint/undo intact | U1 |
| `/tools agent` | **`/tools auto`** | U1 |
| `/task run "<desc>" …` | **`/task "<desc>" …`** — direct launch; a first token counts as a verb only when followed by a run id (`run_` + 12 hex) or nothing | U2 |
| `task show` (canonical) | **`task get`** (`show`/`open` still accepted as aliases) | U2 |
| `task ack` (canonical) | **`task collect`** (`ack` still accepted as alias; merge semantics land with `execution.collect`) | U2 |
| `/agentrun <task>` | **`/run <prompt>`** — same async one-off, now `kind=oneshot` on the full run gears with the U2 grammar; **no flags** (the grant is config-decided: `execution.run.web_search` on → `{web_search}`, off → closed-book) | U3 |
| `/agentruns` | **`/run ls`** — kind-filtered (`/task ls` now shows only task runs too) | U3 |

## New: `execution.collect` — run results into your session (U4)

One global key for the `/run` + `/task` families (default **`yes`** — the
shipped T6 behavior):

- **`auto`** — a finished run merges its result into the active session
  automatically (runs auto-finalize; the watching client merges once, on
  completion — reopening an old run never re-merges).
- **`yes`** — the run holds its result (📬) until you collect it; **collect
  now = finalize + merge**: the Collect button / `collect` verb appends the
  result to the active session, so the model sees it on your next turn.
- **`no`** — collect impossible: the GUI renders the Collect button
  **disabled** with the enable hint, the `collect` verb warns, and no merge
  path exists. The result stays on the run record only.

Merge is **plain** (owner decision Q3): the run enters the conversation
as an ordinary user(task) → assistant(result) exchange — exactly the
texts the run ran on and answered with, no provenance tagging. (The pair
shape is deliberate: session alternation-fixing silently drops a lone
leading assistant message and collapses same-role neighbors, so a
single-message merge could vanish from the next provider request —
caught in the live trial.) New wiring: `GET /config/execution` (clients
read the mode) and `POST /sessions/merge-run-result` (owner-guarded for
remote callers; loopback keeps the UI exemption's on-the-host trust
basis).

U3 behavior changes on `POST /v1/agent/run` (in-development `/v1/agent/*`
surface — not the frozen `/v1/oneshot`): runs are stamped `kind=oneshot`;
a successful run now **holds** its result (`completed_pending_ack`) until
collected, like `/task`; and the loopback auth exemption applies **only
while `execution.run.web_search` is off** — once the config grants
web_search, the endpoint is a capability and requires a bearer even from
localhost.

U2 safety net: after a lifecycle verb, a `run_…`-ish token that is not a
full run id (truncated paste, typo) errors instead of silently launching a
task whose prompt is the mangled command.

Why: "agent" meant three different things (in-session loop, tool-free
background run, sandboxed task tier). After ADR 0011, **`/auto`** is
autonomy *in your session*, **`/task`** and **`/run`** are registry runs,
and "agent" names only the `/v1/agent/*` platform.

## New: enriched `/v1/oneshot` (ADR 0009 step ①, default off)

Two independent switches under `execution.run.*` (both default **off** —
off/off is byte-identical to v1.19.0 and air-gap-safe with a local
provider):

- `execution.run.grounding` — provider-native search (Gemini grounding,
  Perplexity Sonar). Supersedes `tools.web_search.oneshot_grounding`
  (still honored via dual-read).
- `execution.run.web_search` — the model gets exactly one tool,
  `web_search`, and the request executes as an auditable `kind=oneshot`
  registry run; the response gains an additive `grounding` field
  (`searched`, `queries`, `backend`, `search_cost`, `run_id` — the debug
  handle). Exists so local models get context enrichment.

Native wins when both are on (never double retrieval). Per-combination
behavior table in [api-gateway.md](api-gateway.md); `/doctor` reports the
effective path per configured model. Revises ADR 0004's "no tool loop in
oneshot" (opt-in, perimeter preserved).

## New: execution profiles + `enrichment` (ADR 0009 step ③)

Named, reusable task grants in config — `execution.profiles.<name>` is an
AgentSpec-shaped mapping (same fields and normalizer as a `--spec` file), and
a run selects one with `--profile <name>` (web + VSCode `/task`) or
`"profile"` on `POST /v1/agent/task`:

```jsonc
"execution": { "profiles": {
  "research": { "tools": ["web_search", "read_file"], "enrichment": true,
                "network": ["api.open-meteo.com"] },
  "coding":   { "tools": ["read_file", "apply_patch"], "enrichment": false }
}}
```

- **Precedence** `request > spec > skills > profile > default_subagent`;
  list fields (`tools`, `network`) **replace, never union** — a more
  specific layer can actually narrow a grant (skills still union theirs in;
  mounting capability is their purpose).
- **`enrichment: true|false`** — first-class, tri-state (absent = inherit).
  Effective true derives `web_search` + the full backend-superset egress
  baseline once, after resolution. A more specific explicit `tools` list
  omitting `web_search` under effective enrichment is a pre-start **400
  naming both layers** — never a silent closed-book "enriched" run.
  `--enrichment on|off` is also a per-run flag on `/task`.
- **`execution.egress_ceiling`** — deployment-wide egress cap, config-only,
  intersective, unset = no cap. Applied where every run's allowlist is
  assembled (`/task`, `/run`, the `/v1/oneshot` facade). An enriched run
  whose ceiling strips **every** search backend fails pre-start (400 naming
  the stripped hosts, per Q3); a malformed ceiling is a loud 400, never a
  silent no-cap.

## Changed: every `/v1/oneshot` is now a registry run (FU — one-off tier unification)

The plain (non-enriched) `/v1/oneshot` path now executes as a real
`kind=oneshot` registry run, exactly like the enriched facade and
`/v1/agent/run` — the direct non-registry code path is **deleted**, so the
whole one-off tier has one execution path. **The wire contract is
unchanged** (same request, same response envelope byte-for-byte, same 502
error contract on provider failure — gateway-smoke 6/6 against the live
server). What's new around it:

- Every oneshot call leaves an auditable record in `~/.ppxai/runs/<id>/`
  and appears in `/run ls` (status `completed` — a plain oneshot never
  holds; the HTTP response *is* the collect). Records are subject to the
  standard retention reaper.
- A client disconnect now cancels the run cooperatively instead of
  abandoning the provider call.
- Native grounding rides along by construction: the run's provider is
  built through the same construction site that applies
  `execution.run.grounding`, so grounded and closed-book calls share the
  gears.
- `scripts/gateway-smoke.py` updated to the U4 collect contract it had
  missed: under `execution.collect: "yes"` (default) a `/v1/agent/run`
  result is held (`completed_pending_ack`) — the smoke now acks it to
  `finalized` (and accepts straight-`completed` under `auto`/`no`).

## Changed: `tools.web_search.preferred` is now an ORDERING (ADR 0009 step ④, Q5)

⚠ **Behavior change for existing configs.** A concrete `preferred`
(`"perplexity"` / `"gemini"` / `"duckduckgo"`) used to be a hard pin: no
cross-backend fallback, egress narrowed to that backend. It now means
**first-choice-then-fall-back** — the chain stays live and the egress set
is the full backend superset, i.e. **egress widens on upgrade**. To keep
the old pin, add **`strict: true`** in the *same scope* as `preferred`:

```jsonc
"tools": { "web_search": { "preferred": "perplexity", "strict": true } }
```

- `preferred` + `strict` resolve **together, as one scoped tuple**: the
  provider block (`providers.<name>.web_search`) owns both fields iff it
  states `preferred`; otherwise the global block does. A per-provider
  `strict` without a per-provider `preferred` is a dead key. `/doctor` now
  reports the resolved tuple per scope and flags: a concrete `preferred`
  without `strict` (the upgrade change), a dead per-provider `strict`, and
  `strict` combined with enrichment (legal, but one backend outage returns
  the run to closed-book).
- One shared resolver now feeds **both** the call-time search chain and the
  AC-2 egress enumeration (they previously read config differently — a
  per-provider override could select one backend while egress narrowed to
  another). Provider context is threaded through `NetworkPolicy` into
  `tool_targets`, so per-provider tuples resolve identically at both sites.
- Fallback ordering is honest now: a failed `preferred=gemini` tries
  perplexity before DuckDuckGo (previously it skipped straight to DDG).
- Q3 ceiling check refined: enrichment survival is **all-of** over the
  effective egress set (the egress chokepoint enforces all-of, so a
  partially-surviving allowlist made the tool un-callable at run time while
  passing grant time). A narrow ceiling composes with a `strict` pin — the
  pinned backend's hosts are the whole effective set.
- **Fixed en route:** the config loader's per-provider whitelist silently
  dropped the `providers.<name>.web_search` block, so the per-provider
  `preferred` override (documented since v1.13.4) was **dead config** for
  every file-loaded provider. It now survives the load — if your config
  carries such a block, it takes effect from this release (as an ordering;
  add `strict: true` for a pin). `/doctor` reports the resolved tuple.

## New: per-tool egress baselines (ADR 0009 step ②)

`tools.<tool>.egress` — operator-declared hosts merged into any run that
*grants* that tool (task tier + oneshot facade). Generalizes the old
web_search-only `task_default_allow` (dual-read). `get_weather` is now
https-only (the plain-http wttr.in fallback that made it un-allowlistable
is removed — debt Item 52 retired).

## Fixed

- `/clear` left the status-bar `Ctx:` badge stale (Item 48) — fixed in
  **all four clients**. `context_percentage` is refreshed by the engine's
  messages-changed fan-out, so `/clear`, `/compact`, session load and
  rollback all update it (engine + Rich). **ppxaide** gains the live `Ctx`
  badge (same thresholds as Rich: `~` at ≥80%, `!` at ≥100%, hidden on an
  empty session). **Web + VSCode** now receive the value as a push: the
  terminal `stream_end` SSE event carries `context_percentage` in its
  metadata (additive — alongside the existing `usage`), and out-of-band
  changes (`/clear`, `/compact`, load) emit one discrete `state_sync`
  through the command envelope. The field is deliberately NOT in the
  `state_sync` whitelist — no per-message push traffic.
- **New: live web-app E2E suite** (`tests/e2e/live-app.spec.ts`). Every other
  spec in that directory drives a static `file://` harness; this one runs the
  REAL web UI against a REAL `ppxai-server`, covering the wiring harnesses
  can't see — command-envelope round-trips, SSE, and the AppState-driven
  badges. Opt-in via `npm run test:live` (starts the working-tree server, not
  the installed binary); `PPXAI_E2E_PROVIDER=<name>` enables the LLM-dependent
  steps, which otherwise skip. Includes a regression fence for the Clear
  bypass below: it asserts the button hits `POST /command/clear` and never the
  bespoke `POST /sessions/clear`.
- **Clear buttons bypassed the command envelope.** The web Clear button, the
  VSCode Clear button, and the `ppxai.clearHistory` palette command called
  `POST /sessions/clear` directly, while a typed `/clear` went through
  `POST /command/clear`. The bespoke call discards the response body — which
  is where the envelope's `events[]` live — so server-pushed AppState had to
  be re-fetched by hand at each call site, and a missed one meant a stale
  badge (this is what kept Item 48's staleness alive in the buttons after
  the typed command was fixed). All three now dispatch `/clear` through the
  envelope, so pushed state updates itself. VSCode gained a single
  `clearConversation()` path shared by both of its entry points.
- **Config-error fail-safe was incomplete for `execution.run.grounding`.**
  When the config source itself could not be read, `get_execution_run_config()`
  still consulted the *legacy* `tools.web_search.oneshot_grounding` key —
  a second, still-readable source — so a box whose config failed to load
  could keep provider-native search ON while every other `execution.*`
  knob correctly fell back to off. Both keys now resolve to `false` when
  the config is unreadable (an absent `execution` block is still normal
  and resolves defaults as before). A capability must not survive the
  failure of the config that governs it.
- Concurrent-run web_search cost misattribution: the process-global
  reset-on-read usage channel replaced by a per-call ContextVar holder
  (affected interactive chat too).
- `load_config()` now passes the top-level `execution` block through (the
  whitelist silently dropped it).
- Run audit: `tool_call` events carry a truncated args snapshot; a
  `run_usage` event records per-run tokens + tool cost + backend.

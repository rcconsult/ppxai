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

## New: per-tool egress baselines (ADR 0009 step ②)

`tools.<tool>.egress` — operator-declared hosts merged into any run that
*grants* that tool (task tier + oneshot facade). Generalizes the old
web_search-only `task_default_allow` (dual-read). `get_weather` is now
https-only (the plain-http wttr.in fallback that made it un-allowlistable
is removed — debt Item 52 retired).

## Fixed

- Concurrent-run web_search cost misattribution: the process-global
  reset-on-read usage channel replaced by a per-call ContextVar holder
  (affected interactive chat too).
- `load_config()` now passes the top-level `execution` block through (the
  whitelist silently dropped it).
- Run audit: `tool_call` events carry a truncated args snapshot; a
  `run_usage` event records per-run tokens + tool cost + backend.

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

*(U3–U4 entries land here as those stages commit: `/run` family +
`/agentrun` retirement, `execution.collect`.)*

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

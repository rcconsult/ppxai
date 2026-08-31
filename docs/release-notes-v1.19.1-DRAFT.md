# ppxai v1.19.1 — release notes (DRAFT — accumulating until release)

> Working draft per the F/U sequencing plan: each U-stage lands its breaking
> changes here as it commits. Finalized (and renamed to
> `release-notes-v1.19.1.md`) by the `/release` flow.
>
> **Maintainer note:** this file is what ships. Backfilled through
> `b7c6b527` (2026-08-15); if commits land after that, extend it before
> running `/release` — `CHANGELOG.md` `[1.19.1]` is the authoritative
> source to backfill from.

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

## ⚠ Breaking changes (ADR 0010 — config shape, hard move, NO dual-read)

The execution-tier keys move off `tools.agent.*` onto the `execution.*` axis
per [ADR 0010](decisions/0010-config-shape-review.md). **There is no dual-read
window.** A config left at the old paths is not warned about at load time — it
is simply **ignored**, and those settings silently revert to their defaults.

**Migrate with `/doctor`.** It gained a `Config shape (ADR 0010)` section that
reads your config *file* and prints the exact old→new mapping for anything
still stale:

```
Config shape (ADR 0010, v1.19.1):
   ⚠ 3 key(s) at their OLD location — BREAKING change in v1.19.1, no
     dual-read. These are being IGNORED and have reverted to their defaults.
     Move them:
      tools.agent.task_tier_enabled  ->  execution.task.enabled
      tools.agent.sandbox            ->  execution.task.sandbox
      tools.agent.spawn_consent      ->  execution.task.consent.spawn_consent
```

| Legacy (ignored) | Use instead |
|---|---|
| `tools.agent.task_tier_enabled` | **`execution.task.enabled`** |
| `tools.agent.sandbox.*` | **`execution.task.sandbox.*`** (sub-fields unchanged) |
| `tools.agent.spawn_consent` | **`execution.task.consent.spawn_consent`** |
| `tools.agent.consent_ttl_s` | **`execution.task.consent.consent_ttl_s`** |
| `tools.agent.result_retention_s` | **`execution.task.budgets.result_retention_s`** |
| `tools.agent.default_subagent` | **`execution.default_subagent`** |

Before / after:

```jsonc
// BEFORE (v1.19.0)                    // AFTER (v1.19.1)
"tools": {                             "execution": {
  "agent": {                             "task": {
    "task_tier_enabled": true,             "enabled": true,
    "sandbox": { "enforcement":            "sandbox": { "enforcement":
                 "in_process" },                        "in_process" },
    "spawn_consent": "auto",               "consent": { "spawn_consent": "auto",
    "consent_ttl_s": 900,                               "consent_ttl_s": 900 },
    "result_retention_s": 86400,           "budgets": {
    "default_subagent": {                    "result_retention_s": 86400 }
      "provider": "gemini" },              },
    "max_iterations": 50                   "default_subagent": {
  }                                          "provider": "gemini" }
}                                        },
                                         "tools": { "agent": {
                                           "max_iterations": 50 } }
```

Note `max_iterations` **stays** on `tools.agent` — along with
`max_tool_iterations`, `max_same_tool_calls`, `context_char_limit`,
`min_task_words`, `auto_retry_empty` and `zombie_threshold`. Those describe
how the agent *tool* loops, which is tier-independent; only keys describing
*where work runs* moved.

**Why the axis exists:** `providers.*` say WHO answers, `tools.*` say WHAT
each tool is, `execution.*` says WHERE work runs. A tier switch was a sub-key
of a sub-key of `tools`; the security surface (tier enablement, sandbox,
consent, egress ceiling) now reads top-to-bottom in one block.

**`GET /agent/config` changed shape** with it — the six tier keys are no
longer in its response. It is an internal endpoint (not part of the `/v1/*`
stability contract) and its only consumer is the bundled VSCode extension,
versioned with the server. **`/v1/oneshot` and `/v1/agent/*` are unchanged**:
they consume config, they are not shaped by it, so no request or response
field moves.

**Deployment note:** if you pin any of the six moved keys in a k8s
ConfigMap or a checked-in `ppxai-config.json`, rename them in the same
window — there is **no grace period** and a stale key is silently ignored.
Run `/doctor`, which prints the old→new mapping for anything still stale.
(An earlier draft named ppxai-sre specifically; that was checked and it
carries no ppxai config keys, so it is unaffected.)

Also removed as dead config in this pass: the root-level **`visualization.*`**
block (documented as configuring `/show`, but nothing ever read it).

## ⚠ Breaking changes (ADR 0012 — per-model facts, hard move, NO dual-read)

**`capabilities.*` and `tool_calling.*` merge into one `facts` block.** As
with ADR 0010, this is a clean break: a config left at the old keys is
**silently ignored** and those settings revert to defaults. Run **`/doctor`**,
which scans the config *file* (not the loaded values — a moved key is
invisible to every accessor) and prints the old→new mapping, flags fields in
the wrong block, and offers a complete record to paste.

Two record types replace what used to be one overlapping set:

| Record | Answers | Lives on |
|---|---|---|
| `ProviderCapabilities` | what the **endpoint** does — `web_search`, `web_fetch`, `weather`, `citations`, `streaming` | the provider block |
| `ModelFacts` | what a **model** does — `wire_protocol`, `tool_mode`, limits, fallbacks, vision, tier | each model block |

**No field appears on both**, so there is nothing to arbitrate. A
`tool_mode` written in a provider block does not reach any model — `/doctor`
reports it as misplaced rather than letting it silently half-work.

**`native_tool_calling` is deleted, not aliased.** Use `tool_mode`, which
says what the boolean could not: `native`, `prompt_based`, or `auto` (native
with a prompt-based fallback). If you copied the example config, the
migration is `native_tool_calling: true` → `tool_mode: "native"`, `false` →
`tool_mode: "prompt_based"`.

## New: one model, two wires — Perplexity's Agent fleet

A Perplexity key now reaches **Anthropic, OpenAI, Google and xAI models**.
Perplexity serves Sonar over Chat Completions and its Agent fleet over the
OpenAI *Responses* API; ppxai picks the wire per model from
`facts.wire_protocol`, so both live on the one `perplexity` provider — same
key, same bill, same price table.

```json
"anthropic/claude-sonnet-5": {
  "facts": { "wire_protocol": "responses", "tool_mode": "auto", "max_tokens": 4096 }
}
```

`max_tokens` is **required** for `anthropic/*` here — the API rejects a
request without it.

**This matters before 2026-09-27.** Perplexity retires the Sonar
chat-completions endpoint on that date. The Responses wire is the survivor,
and both the provider and the `web_search` tool now follow
`facts.wire_protocol` onto it — the tool used to run its own separate client
that would have broken independently.

### The shipped default moved — and one model has no successor

`default_model` and `coding_model` are now **`perplexity/sonar`** in the
example config, `install.sh`, `scripts/install.ps1` and the VSCode bootstrap.
A fresh install lands entirely on the surviving wire.

Measured 2026-08-31, twice: the Responses wire serves **only**
`perplexity/sonar`. Both `sonar-pro` (the previous default) and
`sonar-reasoning-pro` answer `400 validation failed: model "..." is not
supported` there, in bare **and** namespaced form. They keep working on the
chat wire until 2026-09-27 and then have nowhere to go.

`/doctor` carries deprecation rows for all three bare ids, all pointing at
`perplexity/sonar` — the lighter model, and the only honest target. Naming a
replacement that 400s would send you to a second failure. **Re-check before
the date:** if Perplexity ships the pro line on the Responses wire, those
rows change.

`base_url` stays `https://api.perplexity.ai`. Do **not** append `/v1` — the
provider derives the Responses root per wire, and pinning `/v1` would break
the chat wire that `sonar-pro` still needs.

## New: `tools.web_search.order` — the whole search chain, not just its head

`preferred` chose only the first backend; the rest of the fallback chain was
fixed. Now:

```json
"tools": { "web_search": { "order": ["gemini", "duckduckgo", "perplexity"] } }
```

Backends you leave out are appended in the default order, so a short list
means *"try these first"*, not *"only these"* — pinning to one backend is
still `strict`'s job. Unknown ids are reported by `/doctor` and skipped
rather than taking search offline. The egress allowlist is derived from the
same resolved list, so the chain and the hosts a run may reach cannot drift
apart.

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

## New: `/task` and `/run` in the TUIs (T8b — the port is done)

`/task` and `/run` previously existed only in the web and VSCode clients.
They now ship in **all four client families**. The transport question
parked since 2026-07-07 resolved in favour of **embed**: `build_task_runner`
moved to `ppxai/engine/task_runner.py`, `ppxai/engine/task_backend.py`
drives the same registry and the same sandbox in-process, and the TUIs
became peers of the HTTP clients rather than a second implementation of
them. No TUI grew an HTTP client, and no server is required.

**Availability is gated per verb on a capability, not per client on a
name.** `launch` and `resume` schedule an `asyncio.Task` and need a live
event loop; `ls` / `get` / `watch` / `cancel` / `collect` / `respond` are
synchronous registry operations that do not.

| Client | `/task` + `/run` |
|---|---|
| Web, VSCode | full set |
| **Textual** (`ppxaide`) | full set |
| **Rich** (`ppxai`) | every verb **except `launch` and `resume`**, which return an error naming the reason and pointing at `ppxaide` |

Rich's gap is its blocking prompt, not a `/task` decision — it starts
working the moment that main-loop question is settled, with no change to
this command family. Textual also gained a parked-run consent screen (one
prompt per park token; Escape defers rather than denies) and a focus
opt-out, so `/task ls` no longer steals the cursor.

## New: `network.ssl.*` — TLS settings in config, not just env

TLS verification could previously be configured only through the
`SSL_VERIFY` / `SSL_CERT_FILE` environment variables. It is now also
settable in `ppxai-config.json`:

```json
{ "network": { "ssl": { "verify": true, "cert_file": "/path/to/ca.pem" } } }
```

Precedence: `SSL_VERIFY` → `SSL_CERT_FILE` → `network.ssl.verify` →
`network.ssl.cert_file` → system trust store. **Environment wins**, so
existing `.env` setups are unchanged.

**A custom CA now ADDS to the system trust store rather than replacing
it.** This is the behavior most corporate-proxy users expect and the one
that survives a laptop moving between networks: your internal hosts and
the public internet both verify. Previously — and still, if you set
`SSL_CERT_FILE` in the environment on an older build — OpenSSL narrowed
the context to the bundle alone (measured: 1 trusted root vs 124).

Three drifted outbound clients were unified onto one resolver
(`ppxai/config/tls.py`) along the way: `web_premium.py` honoured
`SSL_VERIFY` but ignored `SSL_CERT_FILE` entirely, so a custom-CA install
silently verified against the system store on the premium search paths;
and only `web.py` checked that the bundle path *exists*, so elsewhere a
stale path became an opaque connection error instead of a fallback. A test
now fails if any module reads those env vars directly again.

**Disabled verification is no longer silent** — startup logs a warning and
`/doctor` reports it, including on an otherwise-clean config where nothing
else would print.

## Security: one admission boundary for every tier

Two paths into the run registry had drifted apart, and T8b's in-process
route reached the runner without the HTTP route's admission checks.
Concretely, before this release: `ppxaide` could start a tool-capable run
while **`execution.task.enabled` was false**; a grant containing
**`execute_shell_command`** evaded the server's explicit rejection; and
**`--skill` values were passed straight through as filesystem read roots**,
so `--skill /etc` mounted that directory into the run's read scope. The
suite was green throughout — no test drove one request through both paths.

Admission now lives in one engine-level boundary,
`ppxai/engine/task_authorizer.py::authorize_task()`, which every client
passes through; the HTTP route is a thin adapter over it. The differences
between the tool-capable and one-off tiers are expressed as **data**
(`TierPolicy` rows) rather than as a second code path, and `AuthorizedTask`
has exactly one construction site in the production tree — a hand-built
literal is how the bypass existed in the first place.

Three defects fell out of that merge, none of them in the original review:
`tools.web_search.enabled=false` did not cover `/run`; the in-process
`/run` borrowed the chat pane's provider/model instead of resolving it per
run; and the oneshot iteration count lived in the route layer although it
is part of the grant that config decides.

**Operator-visible:** none of this changes a request or response shape.
`/v1/oneshot` stays byte-identical.

## Fixed

- **Structured output silently disabled Gemini grounding.** A caller
  combining `response_format` with `execution.run.grounding` kept its JSON
  and quietly lost its search. Verified against the live API on
  `gemini-3.1-pro-preview`: `google_search` coexists with both
  `response_mime_type` and `response_schema` — only *function
  declarations* conflict with grounding. Affected web, VSCode and
  `/v1/oneshot` consumers alike, since it sat in the provider.
- **`response_format` was silently dropped on Gemini** — the fix the item
  above corrects a regression in. `/v1/oneshot` now *delivers*
  `response_format` to the provider; note it delivers rather than
  enforces, which the gateway doc now states explicitly.
- **`/task` with no grant guided instead of firing a doomed HTTP 422**
  (Item 57). A bare `/task "<desc>"` is correctly rejected — a tool-capable
  run must carry an explicit grant — but clients echoed a raw
  *"❌ Task rejected: HTTP 422"*, which read as an outage. Both clients now
  short-circuit client-side with actionable guidance, and the server's 422
  names the flags a user actually types.
- **`/task web_search` no longer loses live data under a narrowed task
  egress** (Item 59). With a soft `preferred: perplexity` and an allowlist
  permitting only `api.perplexity.ai`, the resolver still enumerated the
  DuckDuckGo fallback, the all-of egress rule denied the whole call over
  the unreachable host, and the model fabricated an answer with a
  disclaimer. Selection and egress can no longer diverge.
- **rtk (and any shell wrapper) no longer goes permanently silent** when
  its binary isn't on PATH at first check (Item 56). A negative
  `shutil.which` result was memoized for the process lifetime, so a
  startup-ordering window left the wrapper inactive with no rewrite and no
  log line — observed in a long-running coder pod. Only positive hits are
  cached now.
- **A user-configurable default `/task` grant** (`execution.task.default_grant`,
  Item 58) so a bare `/task "<desc>"` works in an environment that declares
  the tools it normally wants. It is a new precedence *layer*, not a new
  power: it sits below any explicit request/spec/skill/profile and above
  the empty built-in default, and still passes every unchanged clamp.
  `execution.task.allow_user_default` (default true) disables it for a
  locked-down deployment.
- **The browser terminal had no interactive shell** — no history, no line
  editing, no completion. `get_shell_config()` dropped `shell_bin` and
  `login_shell`, so an operator setting `tools.shell.shell_bin` was
  ignored; and the fallback landed on `/bin/sh`, which is dash on
  Debian/Ubuntu. Config now steers it, the unset case prefers bash, and the
  PTY child launches interactive and login with a seeded writable
  `HISTFILE`.
- **Office preview 500'd when LibreOffice was present but could not
  render** — the Ubuntu snap is confined to `$HOME` and fails on `/tmp`
  sources *with exit code 0*. That now degrades to extracted text like the
  LibreOffice-missing path, honouring the route's documented "never 500 for
  a preview we can't rasterize" contract.
- **A transient lifecycle-wiring failure was permanent.** One flag was set
  before two operations were attempted inside a single `try`, so a single
  failure meant orphaned runs stayed `running` forever and the active-run
  badge could never light — silently, since it logs at debug level.
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

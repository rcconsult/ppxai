# Release Notes — v1.19.3

> **Scope:** Started as a two-fix observability release and grew to
> **ten fixes, one transcript change, and ADR 0007's one-command-registry
> work** on the same branch ahead of tagging. Two of the fixes make an
> **existing silent degradation visible**; neither
> changes what the send path does, and neither changes a resolved fact
> value. Two close out the 2026-09-27 Perplexity Sonar chat-completions
> retirement on the web_search tool's own code path (the provider side
> was already fixed under ADR 0012 W3) — one of them **does** change a
> code default. Two correct `/doctor`, which probed outside the TLS
> resolver and whose facts scan could describe a different config file
> than the one its own header named. Two are resolution and display: the
> shipped Qwen 27B-FP8 row now covers the in-place 3.8 upgrade — **this
> release does change the model catalog**, one glob, one family — and
> the context-window badge stops multiplying its baseline by the
> tool-loop iteration count. One rebuilds tool-loop detection: a guard
> that only ever saw a trailing streak of byte-identical arguments is
> replaced by a per-turn occurrence count plus an argument-independent
> per-tool budget, after a live incident where 15 paraphrased
> `web_search` calls tripped nothing. The last lands with the turn-level
> tool strip in the web and VSCode transcripts, which also fixes a
> chevron that could expand to nothing.
>
> Two more, found by the 2026-09-26 VSCode smoke run, make the
> Responses wire usable on `perplexity/sonar`, the only Sonar id left
> after 09-27: attachments were sent with chat-completions part types,
> and three tool names (`search_files`, `web_search`, `fetch_url`) are
> reserved by Perplexity. Both failed every affected turn.
>
> **⚠️ Perplexity is removed as a chat provider; Gemini is the new
> default** (owner decision 2026-09-27, ADR 0015). Perplexity stays a
> web search and grounding backend. A config that still names it
> for chat is **ignored, with a warning**, and the engine falls back to
> the next configured provider; see "Removed" and the upgrade steps
> below. **Grounding now searches first, for every provider** (ADR 0014),
> and `/v1/oneshot` gained an optional `grounding` request field.
>
> **Command-surface changes, landed and Accepted 2026-09-21 (ADR 0007).**
> `CommandSpec` is now the single declaration for every command;
> completion, `/help` and both JS clients' menus derive from it. **This
> release DOES remove a command from web and VSCode**: `/quit` is gone
> from both — web's header button is now "Leave", VSCode uses its
> existing connect/disconnect commands; `/quit`/`/exit` are unaffected
> in the Rich and Textual TUIs. Both JS clients now fail CLOSED on slash
> commands when the roster can't be fetched (e.g. newer web assets
> against an older server). **`/checkpoint clear` now asks first in
> ALL four clients** (web, Rich, Textual, VSCode) instead of clearing
> immediately — Cancel is the default-highlighted first choice, `--yes`
> is there for scripted use — and both TUIs gained their first
> interactive prompt UI along the way, which also fixes `/show @x`
> multi-match and `/edit <missing>` dead-ending in Rich/Textual. See
> "One command registry" below for the rest — subcommand display in
> `/help`, `/tools help` reaching Rich and Textual, VSCode's
> `/tools`/`/context`/`/ls`/`/tree`/`/checkpoint` now server-rendered
> and VSCode's legacy intercept mechanism deleted entirely. **Later the
> same day, ADR 0007's last open decision closed:** VSCode's AppState
> TypeScript types are now generated from the schema (a hand-written
> copy had silently lost two fields), and VSCode now checks the
> connected server's AppState shape on every (re)connect — **new,
> user-visible: one warning when a compiled-against field is missing or
> retyped on the server**; a newer server's extra fields are adopted
> silently, an older server changes nothing.
>

> Config shape: a `providers.perplexity` block is now ignored, and
> `execution.run.grounding: true` now means search-first retrieval (see
> the upgrade steps). The shipped microk8s coder template changes shape,
> but it is an example: nothing in an existing install reads it. The v1
> API gateway (`POST /v1/oneshot`, bearer auth) keeps its response shape;
> its request gains one optional field, `grounding`, and a request naming
> `provider: "perplexity"` now answers 400 instead of calling the retired
> endpoint.

## Branch

`bugfix/v1.19.3` (from master @ v1.19.2), **42 commits ahead of master**
at the time of writing — re-derive with `git rev-list --count
master..HEAD`; uncommitted work in the tree lands as further commits
before tagging, so this count is a floor, not a final tally. Nine fixes
and a web/VSCode transcript feature carried the branch through
2026-09-16 (see Verification below for that tree's test state); ADR
0007's one-command-registry work (steps 1–5 plus the same-day follow-ups
in "One command registry" below) landed 2026-09-21. A tenth fix — the
tool-loop guard rework below — landed 2026-09-23.

**Upgrade steps.** Run `/doctor` after upgrading; it reports each of
these.

1. **Perplexity for chat (ADR 0015).** If `default_provider` or
   `MODEL_PROVIDER` is `perplexity`, or your `ppxai-config.json` has a
   `providers.perplexity` block, the block is now ignored and ppxai
   starts on the next configured provider. Set `default_provider` to
   another provider (e.g. `gemini`) and delete the block. Models you
   reached through a Perplexity key move to the vendor's own provider:
   `openai/*` → `openai`, `google/*` → `gemini`, `anthropic/*` →
   `anthropic` (opt-in, untested against the live API), `xai/*` →
   `openrouter`. Keep `PERPLEXITY_API_KEY`: it still powers web search
   and grounding.
2. **The web search model.** If `tools.web_search.perplexity_model` is a
   bare Sonar id (`sonar`, `sonar-pro`, ...), set it to
   `"perplexity/sonar"`. The bare ids were served only on the
   chat-completions endpoint that retired 2026-09-27, so every
   Perplexity search fails with them. **The shipped `ppxai-config.json`
   carried `sonar` until this release.**
3. **Grounding.** If you set `execution.run.grounding: true` and serve
   Gemini, search moves from Gemini's in-call Google Search to a
   separate search before the model call, through the resolved backend
   chain (Gemini's Google Search first when `GEMINI_API_KEY` is set). Set
   `"native"` to keep the old behaviour.

Otherwise: if you run tool loops against models whose facts rows you
have not checked, the first fix is the reason to take this release; if
you serve the 27B-FP8 Qwen line, the catalog fix is; if you script
against web or VSCode's `/quit`, switch to the "Leave" button /
connect-disconnect commands.

## One command registry (ADR 0007)

Landed and Accepted 2026-09-21. `CommandSpec` is the only place a
command is declared — completion, `/help`, and both JS clients' command
menus are all derived from it, served over `GET /commands?client=<id>`.
See [docs/decisions/0007-completion-first-class-service.md](decisions/0007-completion-first-class-service.md).

- Both JS clients fetch the roster at startup; the hand-written
  `ppxai/web/shared/commands.js` and `vscode-extension/src/shared/commands.ts`
  are deleted, along with five more hand-written command lists
  (including a Rich welcome-screen catalog that had drifted 18 commands
  out of date).
- **⚠️ User-visible: `/quit` no longer exists as a command in web or
  VSCode.** Ending a client session is a UI workflow now, not a slash
  command — web's button reads "Leave"; VSCode uses connect/disconnect.
  Unaffected in Rich/Textual, where `/quit`, `/exit`, and now `/q`
  (newly registered as an alias) all still work.
- Both JS clients fail CLOSED on slash commands when the roster can't
  be fetched, rather than silently doing nothing or guessing at a name.
- `/token set <value>` is `client_handled`, so a typed-inline
  `/token set <bearer>` is masked and intercepted client-side before it
  can reach the server dispatch path.
- Same-day follow-ups: `/help <cmd>` now lists a command's
  subcommands; `/tools help` / `/tools help editing` now work in Rich,
  Textual and web (previously VSCode-only); VSCode's `/tools`,
  `/context`, `/ls`, `/tree` and (as of the follow-up below)
  `/checkpoint` are now server-rendered via `POST /command/<name>`;
  `/context clear` no longer leaves a stale Ctx% badge; three stale
  `/tools agent` hint strings (retired by ADR 0011) are fixed.
- **`/checkpoint clear` asks first, in all four clients, and both TUIs
  gained their first interactive prompt UI.** `/checkpoint clear`
  irreversibly deletes every file-backend snapshot; VSCode's modal used
  to be the only confirmation any client had — web, Rich and Textual
  cleared immediately. With no flag, `/checkpoint clear` now returns a
  quick-pick list with **Cancel first** and the destructive row second,
  so a bare Enter on the default-highlighted item can never destroy
  anything; picking Cancel re-dispatches `clear --no` (deletes nothing),
  picking the second row re-dispatches `clear --yes` (clears). Scripted
  use needs `--yes` directly. Rich shows a numbered list (Enter, `0`, a
  non-numeric reply, or Ctrl-C all cancel); Textual shows a
  `QuickPickDialog` modal (Escape dismisses). Neither TUI previously
  read `CommandResult.side_effects` at all, so this also fixes two
  unrelated dead ends: `/show @<term>` with several matches used to
  print a count and stop — it now shows the numbered/dialog pick and
  opens the chosen file; `/edit <missing-file>` used to print "not
  found" with no way to create it — it now offers to create the file.
  VSCode's legacy intercept mechanism — the last row of
  `LEGACY_INTERCEPTS`, plus `LEGACY_HANDLERS`, the router's legacy
  branch, `handlers/commands.ts` and `handlers/types.ts` — is deleted
  outright, not just emptied. See
  [docs/decisions/0007-completion-first-class-service.md](decisions/0007-completion-first-class-service.md)
  open owner decision 7. VSIX size: 136 KB.
- **VSCode's AppState TypeScript types are now generated, closing open
  owner decision 5** (2026-09-21, later the same day). The hand-written
  `interface AppStateFields` had silently drifted from the canonical
  schema — 22 fields declared, 20 typed — missing `lastMessageRole`
  (v1.18.0) and `modelSupportsVision` (v1.18.6); no test compared the
  two. `vscode-extension/scripts/sync-schema.js` now also emits
  `src/appState.generated.ts`, tracked and pinned byte-identical to a
  fresh regeneration.
- **New, user-visible: VSCode checks the connected server's AppState
  shape on every (re)connect.** `vscode-extension/src/schemaGuard.ts`
  fetches `GET /schema/app-state` and compares it with the extension's
  bundled schema. A matched pair is silent. A newer server's extra
  fields are adopted for the connection silently — logged once, no
  toast, because that state is stored but nothing renders it (rendering
  code ships compiled in). **A field the extension was compiled against
  going missing, or changing type, on the server produces exactly one
  visible warning**, naming the fields and both versions. An older
  server with no `/schema/app-state` endpoint (pre-v1.17.4) changes
  nothing — one log line, chat keeps working; state deliberately does
  NOT fail closed the way the command roster does, because `AppState`
  is constructed before any server exists. VSIX 138 KB.
- **VSCode's vision badge now updates on a command-palette provider or
  model switch, and the attach-time image warning's wording is
  corrected** (2026-09-21, later the same day, closing open owner
  decision 8 — whose own premise turned out wrong too: VSCode's webview
  already had an untyped mirror of `modelSupportsVision` since v1.18.6,
  so it never lost the badge, only the type). `ppxai.switchProvider` /
  `ppxai.switchModel` now trigger a full AppState re-anchor
  (`chatPanel.ts::reanchorState()`) that also forwards to the webview —
  previously only `/status` refreshed, which doesn't carry
  `model_supports_vision`, so the badge lagged a full chat turn behind
  a switch. The attach-time warning no longer promises the image "will
  be sent as a text placeholder" (web retracted that claim in v1.19.0);
  it now matches web's wording — a vision sidecar or the shell tool may
  handle it, or the send is blocked, never silently dropped. The gate
  decision itself moved to a new pure module,
  `vscode-extension/media/webview/visionGate.js`.
- **Web now re-verifies the AppState schema on reconnect** (closing
  open owner decision 9). `_reanchorFromServer()` takes an opt-in
  schema check, run only at a reconnect boundary — heartbeat recovery
  and a tab regaining visibility, never first load or a same-connection
  provider/model switch. It fetches `GET /schema/app-state` and
  classifies it with a new pure module,
  `ppxai/web/shared/app-state-schema-diff.js` — a JS re-implementation
  of `schemaGuard.ts`'s classifier, held to identical verdicts by a
  cross-language parity test over 10 shared fixtures. A match is
  silent; a newer server's extra fields adopt quietly; **a field this
  tab expected going missing or changing shape produces one chat
  notice** telling the user the page was refreshed and to reload for a
  matching UI; an unreachable endpoint logs once and blocks nothing.
- **SchemaGuard's log now reaches the extension's Output panel**
  (the dedicated `"ppxai"` channel as of 2026-09-22; it first landed on
  the `"ppxai HTTP"` channel a day earlier), not only the Extension Host
  console
  (closing open owner decision 10).
- **The AppState schema's `"version"` field is maintained from `"1.1"`
  on** (closing open owner decision 11). `"1.0"` sat unchanged across
  five earlier field-adding commits, so it's an unmeasured historical
  marker, not a real signal. MAJOR for a field removed/renamed/retyped,
  MINOR for a field added or its default changed — enforced against a
  new append-only `ppxai/engine/app_state_schema_history.json`. Neither
  run-time schema check (VSCode's or web's) treats `version` as the
  verdict; both still decide on the actual fields.

## Fixed

- **Gemini grounded searches were logged at 1/1000 of their cost.**
  `tools.web_search.pricing.gemini_grounding.per_query` is a per-query
  price ($0.035, "$35/1000 queries" in the shipped configs), but the cost
  function divided it by 1000. Since v1.13.0 each Gemini grounded search
  was logged at $0.000035, so `/cost` under-reported Gemini web search
  and grounding. If you had written a per-thousand value into
  `per_query` to compensate, divide it by 1000.

- **`/cost` now counts plain `/v1/oneshot` calls and tool-free
  `/v1/agent/run` runs.** The cross-tier usage log behind `/cost` (ADR
  0008) was written by the chat path, `/task` runs and the oneshot
  search-loop path only. A plain oneshot call recorded nothing, so it was
  missing from `/cost`. The model call's tokens are now logged under the
  oneshot tier, priced by the requested model id. The response is
  unchanged, and an accounting failure never fails the request.

- **A discarded parallel tool call now says so in the log.** When a
  model's facts row says `parallel_tool_calls=False`, `chat_with_tools`
  keeps only the first native call:

  ```python
  if not facts.parallel_tool_calls:
      parsed_calls = parsed_calls[:1]
  ```

  That is the one branch in the function that throws away output the
  model already produced, and it was the only one with no logging —
  sitting directly beside the `fallback_on_empty` branch that does log.
  The cost was measured in v1.19.2: fifteen shipped rows were pinned at
  the conservative floor while their models emit several calls per turn.
  Every one of those turns lost calls here and left **nothing** in
  `~/.ppxai/logs`; the operator's only symptom was a tool loop taking
  twice the round trips it needed, which is why the defect was found from
  the outside — comparing one model id across two providers — rather than
  from the logs kept for exactly this.

  It now logs a warning naming the model, the call kept, the calls
  dropped, and the `parallel_tool_calls` row to change (the row is what
  the reader has to edit; naming only the symptom leaves them nowhere to
  go). Single-call turns stay silent behind an `if dropped:` guard — a
  warning present on every turn of every serial model is one nobody
  reads. Behaviour is otherwise unchanged: same call kept, same calls
  dropped. (`30459847`)

- **`/model info` no longer reports a floor value as built-in
  knowledge.** The label came from `is_unmeasured(model_id,
  provider_table)`, which answers *"did a row match"* — so any matched
  provider row made all twelve fields print `(built-in)`.
  `PerplexityProvider` seeds its gateway rows from
  `shipped_facts_for_model("openai/")` (and `anthropic/`, `google/`,
  `xai/`, `perplexity/`), and **none of those globs match anything**, so
  the seed *is* `UNMEASURED`: three fields (`wire_protocol`, `tool_mode`,
  `max_tokens`) are then set deliberately and the remaining **nine print
  as `(built-in)` for every model those five globs serve, across four
  vendors**. ADR 0012 Q0e requires the floor to be visible — *"an
  operator should be told which of their models those are rather than
  discovering it when a tool call silently degrades"* — which is
  precisely the route this took: a model reached through two providers
  answered `parallel_tool_calls` differently, and the gateway's answer, a
  guess, wore the label of a measurement. A live probe then showed the
  guess was wrong (both ids emit two calls per turn, 3/3 trials).

  **Reporting only.** The vendor-agnostic floor is correct as
  *resolution* — one wire, four vendors, a roster that changes without
  notice — and was only ever wrong as a *label*, so `is_unmeasured`, the
  resolver and the send path are untouched. The `Tier` row moves with it:
  tier is one of the nine, and it used to say `(no tier)` ("we have a
  row, it just has no tier") when the truth is "no measurement".
  (`6d29451b`)

- **The web_search tool's `perplexity_model` default now survives the
  2026-09-27 Sonar retirement.** `web_search_perplexity` already resolves
  its wire per-model from `ModelFacts.wire_protocol` — the same table
  `PerplexityProvider` reads — but the code default handed to that lookup
  was still the chat-wire id `sonar`. Anyone who never set
  `tools.web_search.perplexity_model` (the common case) would have lost
  web_search the moment Perplexity retires that endpoint, without having
  touched their own config. The default is now `perplexity/sonar`, which
  resolves to the `responses` wire and was verified live end-to-end
  (2026-09-16: a real search query returns an answer plus citations).
  `ppxai-config.example.json` updated to match, and a new test asserts
  the default resolves to the `responses` wire rather than just "is not
  (yet) in the deprecation table" — so a future regression to a
  chat-wire id fails immediately instead of waiting for the next
  retirement date.

- **A stray Pydantic serialization warning on Responses-wire web_search
  calls is gone.** A live call against `perplexity/sonar` that actually
  triggers a search printed
  `PydanticSerializationUnexpectedValue(Expected \`ResponseCustomToolCall\`
  ...)` to stderr on every call. Root cause: Perplexity's `search_results`
  output item is a type the openai SDK's `Response.output` union doesn't
  know, and `_responses_answer_and_citations` used to call
  `response.model_dump()` to read the response as a plain dict — which
  makes pydantic re-validate that mismatch and warn. The function now
  reads `response.output` directly via attribute access (duck-typed
  against both real SDK objects and dict-shaped test doubles) and never
  serializes the typed union. Verified live before/after: the warning
  fired on the unpatched code against a real search query and is silent
  on the same query after the fix, with identical answer text and
  citations.

- **`/doctor`'s endpoint probe now goes through the outbound TLS
  resolver.** Every other outbound client in ppxai — provider SDK clients,
  the built-in web tools — obtains its verification setting from
  `config.tls.tls_verify()`, the v1.19.1 additive-CA resolver that honours
  `SSL_VERIFY` / `SSL_CERT_FILE` / `network.ssl.*` and adds a configured
  corporate CA to the system trust store rather than replacing it.
  `_probe_provider_endpoint`'s `httpx.Client` was the one client that
  never got the memo: it passed no `verify=` at all, so it fell back to
  httpx's own certifi-only default. Measured 2026-09-16: `/doctor probe`
  answered `CERTIFICATE_VERIFY_FAILED` for a corporate-CA endpoint the
  same provider's own chat client reached without incident, because the
  chat client's `httpx.Client(verify=tls_verify())` picked up the OS
  trust store and the probe's did not. The probe now passes
  `verify=tls_verify()`, the same call every other client makes.

- **`/doctor`'s ADR 0012 facts scan can no longer report on the wrong
  config file.** `_format_facts_section` and the `facts_config` functions
  it calls (`migration_plan`, `misplaced_fields_in_config`,
  `wrong_typed_fields_in_config`, `incomplete_blocks_in_config`) took no
  argument, so each one independently re-resolved and re-read whatever
  config `facts_config.find_config_file()` currently points at — which
  is not necessarily the file `audit_user_config()` audited, when a
  caller passes it an explicit `config_path` (the headless
  `audit_user_config(Path(...))` entry point exists for exactly this).
  Observed 2026-09-16: the facts section listed providers from one
  config while the audit header, two paragraphs above it in the same
  report, named a different one. Every affected function now accepts an
  optional `config_data: dict | None = None`; `/doctor` threads through
  the same raw config dict its ADR 0010 migration scan already reads
  from the audited path (`_format_config_migration_section` established
  this pattern first), so both sections describe the one file the report
  names. The default `None` keeps every other caller's behaviour
  unchanged — this is unrelated to, and does not close, the Item 69
  runtime debt below (`find_config_file()`'s own cwd-based search order).

- **The shipped facts row for the 27B-FP8 Qwen line now covers
  Qwen3.8.** The codeai and in-cluster deployments were upgraded **in
  place** to `Qwen/Qwen3.8-27B-FP8` and `-agent`, keeping the 3.6 ids
  served as aliases and the `qwen36` ingress path for backward
  compatibility. The shipped glob was `Qwen/Qwen3.[56]-27B-FP8*`, so the
  two ids now behaved differently against the same served weights: a
  config naming the **real** 3.8 id matched nothing and landed on the
  UNMEASURED floor — `tool_mode` prompt-based, no vision — while a config
  naming the alias kept native tools. An in-place upgrade is exactly the
  case a glob is supposed to absorb, and this one did not.

  The glob is now `Qwen/Qwen3.[568]-27B-FP8*`. The row is **inherited,
  not measured**: same family, same parser, same endpoint as 3.5/3.6,
  pending a 3.8 benchmark run of its own — the source comment says so,
  so the next reader does not mistake inheritance for a measurement. The
  existing vision/native test pins both 3.8 ids. (`f5d2c078`)

- **The context-window badge no longer overshoots 100% in tool loops.**
  Measured on a live coder session (2026-09-16): a 13-request tool-loop
  turn displayed roughly 350% while the model was actually at roughly
  26%, and a separate 10-request turn displayed roughly 410% against an
  actual roughly 41%. `chat_with_tools` accumulates usage across every
  iteration of a tool loop into `accumulated_usage` — correct for
  billing, since each iteration is a real, separately-billed provider
  call — then calls `session.update_usage(accumulated_usage, ...)` once
  at the end of the run. `_sync_usage_to_state` (the AppState listener
  behind the badge) had no way to tell that delta apart from a
  single-request turn's delta, so it treated the iteration-summed total
  as "tokens currently in `session.messages`" — over-claiming by
  roughly a factor of N for an N-iteration loop, since every iteration
  resends the whole history rather than adding to it.

  `SessionManager.update_usage()` gains an optional `context_tokens`
  keyword: the token count of `session.messages` *after* the turn, as
  opposed to `usage`'s cumulative-for-billing total. `chat_with_tools`
  now tracks `last_request_tokens` — the most recent iteration's own
  `prompt_tokens + completion_tokens` — alongside `accumulated_usage`,
  and passes it as `context_tokens` at both `update_usage()` call sites
  (normal completion and the max-iterations exit). `_sync_usage_to_state`
  uses `context_tokens` as the context baseline whenever it is a
  positive int, falling back to the pre-existing delta-based behaviour
  otherwise. Session/cost totals (the usage badge, billing, per-model
  tracking) are untouched — only the context-percentage baseline
  changes. The plain single-request chat path never passes
  `context_tokens`, so its behaviour (v1.18.4 Item A) is unchanged.

- **Tool-loop detection now catches paraphrased repeats, not just
  byte-identical streaks.** Measured live (2026-09-22, web client,
  `gemini-3.5-flash`): one turn ran `web_search` 15 times in 113 seconds
  hunting a single IMDb image id, every call succeeding, until the user
  interrupted it. `"Loop detected"` appeared **zero** times in the log.
  Four of the fifteen queries were byte-identical, but interleaved with
  ten paraphrases (calls 2, 7, 10 and 14) — and the existing guard,
  `is_tool_loop_detected`, walked the turn's history *backward from the
  most recent call* and reset to zero at the first non-matching one, so
  a trailing streak of 3 never formed. Plumbing was ruled out first: 17
  `SSE: tool_call` and 17 `SSE: tool_result` lines in the window, so
  every result reached the model — it was looping, not being made to
  repeat.

  Two changes, not one:

  1. **Guard A now counts occurrences of `(tool, args)` anywhere in the
     current turn**, among successful calls only, instead of a trailing
     streak. The old streak rule is deleted outright rather than kept
     alongside the new one — a trailing streak of N is also N
     occurrences in the turn, so it could never fire before the new rule
     does; keeping both would have left dead code.
  2. **A new argument-independent per-turn call budget** (guard B) on
     `web_search` and `fetch_url` only — 10 calls each by default,
     configured at `tools.agent.tool_call_budgets` and merged over the
     shipped default (raising one tool's cap doesn't uncap the others;
     absent or 0 means unlimited). This is the guard exact-argument
     matching structurally cannot replace: it catches the ten
     *paraphrased* calls the incident actually ran, not just the four
     byte-identical ones. The number comes from tau-bench's published
     historical trajectories (`sierra-research/tau-bench`, MIT license;
     1,960 real GPT-4o/Sonnet runs scanned locally): a tool is called
     once in 83.6% of turns, five times or fewer in 99.3%, but **32 of
     the 76 turns that called one tool six-plus times succeeded** (reward
     1.0) — so a low cap would have cut real, working turns. Ten calls
     costs an estimated ~0.03% of legitimate turns and still stops the
     2026-09-22 incident at call 11. Nothing else is capped — reading
     files, listing directories and running shell commands legitimately
     repeat many times in a turn.

  **Failed calls count toward neither guard.** A retry after a transient
  failure is recovery, not a loop, and "synthesize from the results you
  already have" is the wrong thing to tell a model when there are no
  results yet; a tool that keeps failing remains the zombie circuit
  breaker's job (`tools.agent.zombie_threshold`). `record_tool_call` now
  runs *after* the tool executes, with the real outcome, so this
  distinction is possible at all.

  **Each guard's refusal carries its own message.** The old text —
  "called the tool with the same arguments N times" — is simply false
  for a budget trip, and would teach the model to rephrase its
  arguments, which is exactly the behaviour that caused the incident.
  **The budget refusal is also terminal**: a second attempt at an
  already-exhausted tool withdraws tools for the rest of the turn and
  forces a synthesis pass, so the model can't spend its remaining
  iterations negotiating with a tool that will never run again this
  turn.

  A gap is accepted, not hidden: an alternating two-tool cycle where
  every call uses fresh arguments (`A, B, A, B, …`, never repeating) is
  caught by neither guard — fuzzy/semantic argument matching was
  considered and declined, since it needs a tuned per-tool similarity
  threshold and would block two deliberately different queries as
  readily as one rephrased one. That gap is bounded only by the
  iteration cap and the zombie breaker (the cap now ends in an answer
  pass and logs the call pattern; see the Item 80 entry below), and is recorded in
  `tests/fixtures/tool_loops/call-graph-cycle-alternating-distinct-args.json`
  rather than left undocumented.

  Config lands on the existing `tools.agent.*` axis, not a new one.
  `GET /tools/status` and `GET /agent/config` both gain a
  `tool_call_budgets` key in their response body, additively; `POST
  /v1/oneshot` is untouched. (`2514ba55`)

- **A `/task` run's `events.jsonl` now records degraded turns.** A
  `turn_degraded` record is written for each tool-guard degradation
  (budget exhausted, tools withdrawn, repeat loop) and a `turn_end`
  record per turn carrying `degraded`/`degradation_reasons`. Previously
  the runner persisted only tool calls, so a degraded turn looked
  complete in the audit file. Additive; existing records and the run's
  own `agent_run_complete`/`agent_run_error` are unchanged. A missing
  `turn_end` means the turn's outcome is unknown. (`59702221`, closes
  debt Item 82)

- **Every tool-loop exit now ends with a run terminal.** Three
  `chat_with_tools` exits (the prompt-based fallback's provider error,
  the retry-synthesis provider error, and a tool interrupt) returned
  without `AGENT_RUN_ERROR`, breaking the heartbeat contract and leaving
  those turns with no `turn_end`. They now emit it, and the `/task`
  runner waits for it before failing the run: the run still ends FAILED
  with the same message, and no tool runs after an error. `path_denied`
  audit records' `filesystem` category is now declared, so a
  `?category=filesystem` filter documented from the list finds them.
  The web and VSCode task views render `turn_degraded` and `turn_end`;
  a turn that did not report `degraded` shows as "outcome unknown",
  never as clean.

- **A tool loop that hits its iteration cap now answers instead of
  giving up** (debt Item 80). The cap used to end the turn on a canned
  *"[Tool iterations limit reached …]"* line and throw away everything
  the loop gathered. That was the only outcome for the loop neither
  guard sees: two tools alternating with fresh arguments on every call.
  After the last tool iteration, one extra pass now runs with tools
  withdrawn, and its answer ends the turn. The cap is a new
  degradation reason, `ToolGuardReason.ITERATION_CAP`
  (`"iteration_cap"`, additive). `AGENT_RUN_COMPLETE` still sets
  `max_iterations_reached: true` alongside it, so
  `task_runner.turn_end_level` grades the turn `warning` as before. At
  ~70% of the cap the model gets one "converge" notice
  (`metadata.notice = "iteration_warning"`). It refuses nothing, so it
  is not a degradation reason. The cap, the notice, both guards and the
  zombie breaker log the turn's call pattern: shape, the repeating tool
  cycle if any, per-tool calls and distinct arguments, and the last 12
  tool names. The pattern also rides in the cap and notice metadata as
  `call_pattern`. A detector that *refuses* the alternating shape is
  still declined, because legitimate exploration looks the same. The
  logged pattern is the evidence a future one would be designed from.
  **For consumers:** a turn capped with a positive `max_iterations`
  no longer reaches the fall-through exit, so its final text is the
  model's answer, not the canned line. The fall-through now runs only
  when `max_iterations <= 0`.
- **No module reads config at import any more.** The one that did,
  `engine/context.py`'s module-level `MAX_FILE_SIZE`, is removed. `@tree`
  now uses the live configured limit, which previously ignored config
  reloads. A new test fails on any future import-time config read. The
  module attribute `ppxai.engine.context.MAX_FILE_SIZE` is gone; use
  `ContextInjector().MAX_FILE_SIZE`.
- **Five more defects from the 2026-09-26 VSCode smoke run.**
  `/context clear` now actually removes injected content (defect 5,
  broken since v1.13.9). Six VSCode webview elements that the CSP left
  visible now start hidden (defect 1). Raw HTML in message text is
  escaped in both VSCode and web, so `<task>` stays visible and
  `<img onerror=...>` from a model is inert (defect 2). VSCode's `/auto`
  stops when a tool-using turn reports `TASK_COMPLETE:`, and says "Max
  iterations reached" only when it did (defect 6). VSCode re-checks the
  AppState schema on window focus, so a server restarted under a live
  connection is verified (defect 7).
- **The first process on a fresh HOME had no providers.** Importing
  `ppxai` reads config at module level, which loaded the store before
  `initialize()` seeded `~/.ppxai/ppxai-config.json`. The store kept that
  empty result for the whole first process, and only the second run
  worked. Any container that starts with an empty HOME hit this.
  `initialize()` now reloads the store on the call that seeds the file and
  loads `.env`.
- **An `EngineClient()` built before `ppxai.config.initialize()` had no
  providers.** An embedder that skipped `initialize()` got an empty
  provider table, and every `set_provider()` returned False silently.
  `EngineClient.__init__` now calls the new
  `ppxai.config.ensure_initialized()`, which runs `initialize()` once if
  nothing has yet and never re-runs a completed one. The first call has
  `initialize()`'s usual effects: it loads `.env`, seeds a missing
  `~/.ppxai/ppxai-config.json`, and creates the `~/.ppxai` subdirectories.
- **The server ignored `default_provider`.** `SessionManager` started
  every engine on the first provider block in the config file, so neither
  `default_provider` nor `MODEL_PROVIDER` reached web, VSCode or
  `/v1/oneshot`. Found on 2026-09-27: with `default_provider: "gemini"`
  the server still started on Perplexity, which is listed first. It now
  starts on `get_default_provider()`. If that provider has no API key, it
  tries the configured providers in file order.
- **Attachments work on Responses-wire models.** `perplexity/sonar`,
  gpt-5.6-terra, gpt-5.3-codex and gpt-5-pro rejected every attachment
  turn with `invalid type "text"`. The Responses handler passed
  chat-completions content parts through unchanged. It now sends `text`
  as `input_text` (`output_text` for assistant turns), `image_url` as
  `input_image` and `file` as `input_file`.
- **Tools on with `perplexity/sonar` no longer fails every turn.**
  Perplexity's `/v1/responses` reserves `search_files`, `web_search` and
  `fetch_url` as custom function names (measured 2026-09-26), so a
  tools-on turn, and any `/task` grant naming one of them, failed before
  the model answered. A provider now declares `reserved_function_names`;
  the Responses handler sends those tools as `ppxai_<name>` and maps the
  name back when the model calls one. Registry, grants, consent and logs
  keep the real names. Only `PerplexityProvider` declares any.
  Live-verified: a tools-on turn called `search_files`, then
  `read_file`, and answered.

### The guard against over-reach

Comparing a value to `UNMEASURED` cannot by itself tell a guess from a
measurement that happens to agree with the guess. So the `/model info`
fix above is gated on `has_global_row`: a model with its own row in
`SHIPPED_MODEL_FACTS` keeps `(built-in)` on **every** field, and only a
model resolved *solely* through a provider row is compared field by
field. `o3*`'s measured-serial `parallel_tool_calls=False` and
`gemini-3.1-pro*`'s are findings, not floors, and are never relabelled as
guesses. Tests pin both.

- **A session that never checkpoints no longer leaves an empty
  directory behind.** `FileCheckpointBackend.__init__` used to
  `mkdir(parents=True, exist_ok=True)` at construction — and a
  `FileCheckpointBackend` is built for every session whose working
  directory has no `.git`, which is ordinary session creation, not a
  checkpoint operation. Found while auditing the checkpoint-clear
  confirmation work above: on one developer host this had accumulated
  roughly 14,900 `sessions/checkpoints/session_<timestamp>/`
  directories, all but two of them empty. The directory now appears on
  the first real snapshot instead; `list_checkpoints()` and
  `cleanup_old_checkpoints()` both tolerate its absence. Nothing a user
  can see changes.

- **(Developer-facing) The test suite can no longer write into the
  real `~/.ppxai`.** The empty-checkpoint-directory leak above turned
  out to be one symptom of a broader gap: a full suite run was also
  appending to the `/cost` usage-events sink, interleaving into real
  debug logs, writing real PNGs into the preview cache, and — despite
  an existing autouse guard meant to prevent exactly this — a spawned
  `ppxai-server` smoke-test subprocess kept rewriting the real TUI
  session-restore pointer, because that guard patches an attribute
  inside the pytest process and cannot reach a child interpreter with
  its own real `HOME`. `tests/conftest.py` now points `HOME` at a
  throwaway directory in `pytest_configure`, before any `ppxai` module
  is imported — the one point at which redirecting `HOME` actually
  works, since every module-level `Path.home()` constant (and every
  subprocess the suite spawns) resolves into the throwaway home from
  then on. `PPXAI_TEST_KEEP_HOME=1` keeps it after the run for
  inspection. No change for anyone who only runs `ppxai` normally.

## Removed

- **Perplexity as a chat provider (ADR 0015).** Its chat-completions API
  retired on 2026-09-27; the one Sonar id left needed two wire fixes the
  day before (see Fixed). Perplexity stays a web search and grounding
  backend, second in the default order after Gemini. The phase-1 deprecation (warn on select) never
  shipped: it is replaced by the removal in the same release.
  - `PerplexityProvider` and the models it served through a Perplexity
    key (`openai/*`, `anthropic/*`, `google/*`, `xai/*`,
    `perplexity/*` as chat) are gone.
  - A `providers.perplexity` block is ignored, never rewritten, and
    logged once at start-up. `set_provider("perplexity")` returns False
    and never raises (start-up code that selects the configured default
    keeps working), and it never falls back to a generic
    OpenAI-compatible client, which would have called the retired
    endpoint and failed every turn. The engine starts on the next
    configured provider.
  - `/provider perplexity`, `/v1/oneshot` and the task tier answer with a
    message naming the fix. `/doctor` reports the leftover default or
    block, with a replacement per model it lists
    (`metadata.removed_chat_providers`).
  - A session recorded on Perplexity keeps its history, continues on the
    current provider, and says so once: in the restore result
    (`notice`) and as an INFO event (`metadata.notice =
    "provider_removed"`) leading the next chat turn.
  - Defaults: `default_provider` is `gemini` in both shipped configs, the
    installers' generated configs, and VSCode's built-in config and
    `ppxai.defaultProvider` setting. The fallback when nothing valid is
    configured is `gemini`, then the first configured provider.
    `get_provider_config("<unknown>")` returns `{}` instead of
    Perplexity's block, which silently swapped providers under the
    caller.
  - Removed with it: the Perplexity chat system prompt, its `AGENTS.md`
    hints, its model-deprecation and recommended-model rows,
    `ProviderName.PERPLEXITY`, and
    `scripts/probe-perplexity-capabilities.py` (it measured chat tool
    calling). `perplexity_facts.py` keeps only the search backend's
    Responses-wire row. `CODING_MODEL` now names `gemini-3.8-flash`.

## Changed

### Grounding searches first, for every provider (ADR 0014)

Web search is now its own layer, `ppxai/engine/search/`: the Perplexity,
Gemini and DuckDuckGo backends and the resolver that orders them. It
imports nothing from the chat providers, which a test pins. The
`web_search` tool is an adapter over it, and its output is unchanged.

**`execution.run.grounding: true` now means `"retrieve"`.** On
`/v1/oneshot` and the tool-free `/v1/agent/run`, ppxai searches once, with
the prompt as the query (capped at 2,000 characters), through the same
backend chain as `web_search` — by default Gemini, then Perplexity, then
DuckDuckGo, each when usable — and then calls the model with the result framed ahead of the
prompt. Any provider can be grounded.

- The response's existing optional `grounding` record is set: `searched`,
  `run_id`, `queries`, `backend`, `search_cost`. `searched: false` means no
  backend was usable or every one failed, and the model answered without a
  search.
- The search cost is logged under the oneshot tier, so `/cost` counts it.
- Only the prompt text is sent: not the system message, history or
  attachments. The backend's hosts must pass `execution.egress_ceiling`;
  a malformed ceiling is a 400 before the run starts.
- The injected result is capped by `context.max_injection_size`. The
  model is asked to cite `[n]`; ppxai does not append sources to the
  answer, since that would break a JSON `response_format`.
- `"native"` keeps the provider's in-call search (Gemini), the meaning
  `true` had before. An unrecognised value is treated as off.
- `/doctor` shows the mode, the `retrieve` path per model, the backend and
  host a prompt would reach, and a warning about untrusted input.

**New optional request field, `/v1/oneshot`: `grounding`.**

| Value | Effect |
|---|---|
| absent / `null` | The server setting decides. |
| `false` | No web search of any kind for this request: no retrieval, no native search, no search loop. |
| `true` | Grounding required: 400 when the server cannot ground this request. |

The response shape is unchanged. **Callers with untrusted or confidential
prompts should send `false`**: retrieval sends the prompt text to a
third-party search host, and the results reach the model. A server older
than v1.19.3 ignores the field; a caller that depends on it checks the
version from `GET /health`.

**Default search order.** The `web_search` chain, which grounding also
uses, is now Gemini → Perplexity → DuckDuckGo (was Perplexity first;
owner decision 2026-09-27). Only usable backends are tried, so without
`GEMINI_API_KEY` it stays Perplexity → DuckDuckGo. To keep the old order,
set `tools.web_search.order: ["perplexity", "gemini", "duckduckgo"]`.

**Upgrade.** If you set `execution.run.grounding: true` (or the legacy
`tools.web_search.oneshot_grounding: true`) and serve Gemini, search moves
from Gemini's in-call Google Search to the resolved backend. Set
`"native"` to keep the old behaviour.


- **Gemini's default model is now `gemini-3.8-flash`** (owner decision,
  2026-09-27): the newest generally available Gemini Flash model, at half
  the price of `gemini-3.5-flash` through 2026-12-31 ($0.75 / $3.75 per 1M
  tokens, then $1.50 / $7.50 from 2027-01-01). Capabilities were measured
  2026-09-13; its tier is inherited from the 3.5 line, not benchmarked. It
  changes in all six places the default is written: both shipped configs,
  both install scripts, VSCode's built-in config and `/doctor`'s recommended
  default. Existing configs keep their own default. Two shipped prices were
  wrong and are corrected: `gemini-3.5-flash` is $1.50 / $9.00 (was
  $0.50 / $3.00) and `gemini-3.1-flash-lite` is $0.25 / $1.50 (was
  $0.10 / $0.40), so earlier cost estimates on those models were low.

- **web_search's Gemini backend in the shipped config moves off
  `gemini-2.5-flash`**, which Google shuts down on 2026-10-16. Debt Item 54
  fixed the code default, but `ppxai-config.json` overrode it. It is now
  `gemini-3.6-flash`, matching the code and the example config.
- **Tool calls collapse into one strip per assistant turn** (web and
  VSCode). The transcript already grouped tool calls, but the engine
  emits one `TOOL_GROUP_START` per tool-loop **iteration**, and an
  agentic run is usually one or two tools per iteration. Measured in a
  live session (2026-09-19): 221 group events, runs reaching iteration 7,
  **every one with `count=1`** — so seven separate collapsed strips for a
  single answer, each inserted *above* the assistant message and pushing
  the answer further down the page. The grouping was never wrong; it sat
  one level too low.

  `.tool-turn` is that level: one strip per assistant turn holding every
  iteration group, labelled from running counts (`14 tools · 8 steps ✓`)
  with a status mark when it closes. Collapsed by default — expanding
  the turn shows its steps, expanding a step shows its tool bubbles. It
  is created lazily on the first group of a turn, closed in the
  streaming `finally` so an aborted or errored turn cannot leak into the
  next one, and dropped in `clearConversation`, which otherwise leaves
  the following turn appending into detached DOM. `/auto`'s
  per-iteration `━━━ Iteration n/m ━━━` system message folds into the
  same strip instead of competing with it, and still prints on its own
  when a run uses no tools.

  Ported to the VSCode webview in the same change rather than left for
  later — the two transcripts are line-for-line twins, which is the
  subject of `docs/lessons/parity-harness-must-know-every-client.md`.
  (`1c1beac4`)

- **Also fixed in that change: a tool bubble's chevron could expand to
  nothing.** The ▶ chevron rendered on **every** tool bubble, but
  `.tool-details` was only built when verbose tool output was on — so
  with verbose off, clicking a bubble toggled a class and revealed an
  empty box. The VSCode webview never had this: it always renders the
  details and treats verbose as "start expanded". The web side now
  matches it, and a bubble with genuinely no payload renders no chevron
  and takes no focus.

- **Tool bubbles are keyboard-operable and announce their state.** These
  disclosures were mouse-only, and there was no `aria-expanded` anywhere
  in the web app. Headers are now `role="button"`, tab-reachable,
  operable with Enter or Space, and carry `aria-expanded` plus
  `aria-controls`. Bubbles are built with `createElement` /
  `textContent` instead of `innerHTML` template strings — the old form
  interpolated `escapeHtml()` correctly, but it put the safety on every
  future editor rather than on the construction.

- **The shipped microk8s coder template is v1.19.3-shaped**
  (`deploy/examples/microk8s/server-config.yaml`). It predated ADR 0010
  and ADR 0012: no `execution` block, no `network.ssl`, and tool
  capability still declared per provider
  (`capabilities.native_tool_calling` / `tool_calling.mode`) — keys
  v1.19.1 **silently ignores**. Every model now carries a complete facts
  block; `execution.{run,collect,task,default_subagent}` and
  `network.ssl` are shown explicitly; Perplexity moves to the
  Responses-wire ids (`perplexity/sonar` and the two gateway models)
  ahead of the 09-27 retirement, `tools.web_search.perplexity_model`
  included. Because the template enables the task tier with a default
  `web_search` grant, it now also shows the matching posture instead of
  the open default: `execution.task.sandbox.enforcement=in_process` with
  `/workspace` as the readable root and the standard deny list, and
  `execution.egress_ceiling=[api.perplexity.ai]` — the only host that
  grant needs. Both are deployment decisions an operator should make
  deliberately, and a template that leaves them at the default teaches
  the default. `vllm-qwen36` is renamed `vllm-qwen38` with the 3.8 model
  id, matching the deployed ConfigMap. **Example only** — nothing in an
  existing install reads this file. (`9afc18fe`, `aa69e126`)

## Debt

- **Item 69 wording sharpened — recorded, not reopened, at the owner's
  direction.** Item 69 closed the *test* half of the config-resolution
  asymmetry; the *runtime* half is still open, and it makes `/doctor`
  lie. `find_config_file()` prefers `./ppxai-config.json`, so `/doctor`
  run from the ppxai repo root audits **ppxai's own project config** and
  gives a clean bill of health on a file it never opened. Measured both
  directions on the same tree, same code, only `cwd` differing:
  `cwd=<repo root>` → `ppxai-config.json`, `incomplete_blocks_in_config()
  = {}`; `cwd=/tmp` with `PPXAI_CONFIG_FILE` pointed at the home config →
  one partial record, eleven fields named. The ADR 0012 Q0d enforcement
  path therefore returns a **false negative** for anyone running
  `/doctor` from a checkout. The next person to touch `/doctor`'s file
  resolution should know the test-side pin did not cover them.
  (`8c95d999`)

- **Item 73 — the `rendering.textual_renderer` ↔ `tui.app` import cycle
  is now fenced, not fixed.** `TestEveryPackageImportsStandalone`
  checked six *package* roots, which is exactly how this cycle got in:
  `ppxai/rendering/__init__.py` does not pull `textual_renderer`, so the
  package imported clean while the module did not. A new sweep imports
  **every module** under `ppxai/` in one subprocess, purging every
  `ppxai*` entry from `sys.modules` between imports so each internal
  graph is rebuilt while third-party imports stay cached — roughly 30s
  for ~180 modules, against ~5s × 180 for an interpreter apiece.
  `ppxai.tui.*` is excluded because importing it sets up the terminal
  and can hang; the Item 73 cycle is still caught, because the module
  that starts it lives in `rendering`. The cycle is the single
  `KNOWN_IMPORT_CYCLES` row, and a second test asserts that row **still
  fails** — so fixing the cycle turns the exemption into a failure
  telling you to delete it. The cycle itself stays open; the inventory
  now records what a fix costs (both ends lead to
  `ppxai/tui/__init__.py:22` importing `tui.app` eagerly, and nothing
  outside that file does `from ppxai.tui import PPXAIDEApp`).
  (`99ca13f7`)

- **Item 34 — closed as obsolete, not implemented.** It asked for
  `python-docx` in the `[data]` extra "so the Word text fallback can
  extract without LibreOffice". That fallback never used python-docx:
  `docx_tools.py` extracts with stdlib `zipfile` + `xml.etree` (its own
  docstring says so) and `files.py:868` calls it for the `.docx`
  fallback; `grep -rn "import docx"` over `ppxai/` and `tests/` returns
  nothing. Adding the dependency would have grown every binary by a
  package nothing imports. Its heading already carried a ✅ while the
  body was half open — the same heading-versus-body drift the item's own
  text complains about. (`99ca13f7`)

- **Item 54 — re-probed early rather than waiting for its due date.** 58
  Gemini models (was 52 on 09-01), still **no GA 3.x Pro**: only the two
  `gemini-3.1-pro-preview` ids. The one new GA-looking id,
  `gemini-3-pro-image`, is an image model and no target for a chat Pro.
  The entry's own instruction is "still preview-only? move this date
  past the sunset", so the due date moves 2026-10-10 → 2026-11-14 with
  the probe recorded. (`99ca13f7`)

- **Item 74 filed — `/preview --serve` cannot start ANY Node project on
  Windows.** Found live on a project whose `package.json` declares
  `"start": "node server.js"`. `detect_command()` returns the string
  `"npm start"` (`preview_backend.py:128`) and the launcher splits it and
  starts it directly **with no shell** (`preview_backend.py:363`). On
  Windows `npm` is not an executable — it is `npm.cmd`, or a PowerShell
  script under a version manager — so the OS call fails with
  `Failed to start backend: Command not found: [WinError 2]`.
  Reproduced outside ppxai on the same host to rule out our own
  resolution. Every non-`.exe` name the detector can emit is affected:
  `npm`, `npx`, `yarn`, `pnpm`, and the `make run` branch; the Python
  branch survives by accident because it resolves an absolute
  `python.exe`. It went unnoticed because POSIX has no equivalent
  failure, the detector never runs on Windows in CI, and
  `detect_command` has **no test at all on any platform**. The entry
  records the verified workaround and two candidate fixes — the better
  one being to stop throwing away the value we already read: we consult
  `scripts.start` to decide `npm start` is available, and
  `"node server.js"` is directly startable on every platform.
  (`b067ce9c`)

- **Item 78 — closed, and it was bigger than filed.** Filed as "the
  test suite leaks empty checkpoint directories into the real
  `~/.ppxai`"; measured before the fix (one clean-tree run, marker-file
  method): 214 entries created or modified in the developer's real
  `~/.ppxai` — 111 empty `sessions/checkpoints/session_*` directories
  (the filed leak), 8 real session files, 34 interleaved debug logs, 29
  entries under `runs/`, 5 preview-cache PNGs, a staged upload, both
  `/cost` sink files appended to, and the TUI session-restore pointer
  rewritten by a spawned `ppxai-server` subprocess despite an existing
  in-process guard against exactly that. After: 0. Both halves fixed —
  `tests/conftest.py` points `HOME` at a throwaway directory before the
  first `ppxai` import, and `FileCheckpointBackend` no longer creates
  its directory at construction. Fenced by `tests/test_home_hermeticity.py`
  and `tests/test_checkpoint.py::TestTheDirectoryIsCreatedLazily`. See
  `docs/debt-inventory.md`'s closed-items note for the full account.
  Existing empty directories on developer hosts were **not** deleted —
  the cleanup command is recorded there, run at the owner's discretion.
- **Item 79 filed — a `checkpoint_dir` fallback that always falls
  back.** `EngineClient`'s Agent Mode notification
  (`ppxai/engine/client.py` ~line 807) reads
  `getattr(self._checkpoint_manager, "checkpoint_dir", None)`, but
  `CheckpointManager` has no `checkpoint_dir` attribute — only its
  `.backend` does — so the `getattr` always returns `None` and the
  literal fallback path is always shown. Harmless today because the
  literal is correct, but silently wrong if the two ever diverge.
  Found, not fixed, while auditing Item 78.

**Open items: 20** (re-derived from the "Open at a glance" table before
this session's closes/filings — Items 73 and 74 filed, Item 34 closed;
Item 78 closes and Item 79 files in this same session, net unchanged).

## Known limitations

- **Not every fix here was confirmed live; the split is deliberate.**
  Four were measured against a real endpoint on 2026-09-16 — the
  `perplexity/sonar` default (a real search returning answer plus
  citations), the Pydantic warning (fired before the change, silent
  after, identical answer and citations), `/doctor`'s TLS probe (a
  corporate-CA endpoint the same provider's chat client reached without
  incident), and `/doctor`'s facts scan (the section listing providers
  from a different config than the header named). The rest rely on
  unit tests and mutation checks, **not** on a live tool loop against the
  installed binaries. Their acceptance checks, if you want to close that
  gap yourself: for the dropped-call warning, a multi-call turn against a
  model whose row is still `False` — `~/.ppxai/logs` should now carry it;
  for `/model info`, any `openai/*`-style id served through the
  Perplexity gateway, where nine fields should now read `(unmeasured)`;
  for the context badge, any multi-iteration tool loop, where the
  percentage should stay under 100.
- **The Qwen3.8 row is inherited, not benchmarked.** It is the 3.5/3.6
  row — same family, same parser, same endpoint — and it is a far better
  answer than the UNMEASURED floor the real 3.8 id was getting, but it
  is not a measurement of 3.8. If 3.8 changed its tool-calling or vision
  behaviour in the in-place upgrade, this row now states that change
  confidently and wrongly. A 3.8 benchmark run is the close-out.
- **The turn-level tool strip is covered by two partial suites, neither
  of which alone claims tool rendering works.** The turn logic lives on
  a class in a 3,700-line file that cannot be instantiated standalone,
  so `tests/e2e/tool-turn.spec.ts` (9 tests) drives the real
  `styles.css` for the CSS collapse contract while
  `tests/test_web_shared_modules.py` (10 tests) covers the source
  wiring — when a turn opens, nests and closes. The split is documented
  in both files. Mutation-verified, each mutation failing exactly one
  test.
- Everything Item 46 covered in v1.19.1 still stands: `execution.task.*`
  has no dual-read from `tools.agent.*`, and `/doctor` prints what each
  stale key costs. Unchanged by this release.
- The Anthropic provider remains **opt-in and untested against the live
  API**, as recorded in v1.19.1 (debt Item 71, an accepted limitation).

## Verification

Full suite at `1953c29c` (branch HEAD, 2026-09-21, later the same day —
supersedes the `beffa197` figure below, taken before the VSCode AppState
codegen + connect-time schema-guard work landed) on macOS with
`uv sync --all-extras`: **6,696 passed, 1 skipped, 0 failed** in 596s.
The `beffa197` measurement — **6,667 passed, 1 skipped, 0 failed** in
531s — predates that work; kept for the record, not current. The
`b067ce9c` measurement — **5,909 passed, 1 skipped, 0 failed** in
535s — predates ADR 0007 entirely; kept for the record, not current.
Windows at an earlier point in the branch, measured on the other host:
**5,878 passed, 32 skipped, 0 failed** @ `1c1beac4`; the extra skips
are the usual platform gates (PTY, symlink cases, POSIX signal
semantics) — not re-run since ADR 0007 landed. The Playwright specs
under `tests/e2e/` are not in any of these counts — **209 passed**
there at `beffa197`, including the 9 `tool-turn.spec.ts` tests; not
re-run at `1953c29c` (the AppState work touched no web/VSCode webview
UI a Playwright spec would exercise). The new VSCode AppState tests
leave the real `~/.ppxai` untouched (entry count equal before and
after, per the commit message). **NOT verified in a real VSCode
extension host** — see the manual smoke checklist in
[docs/plan-adr-0007-completion-service.md](plan-adr-0007-completion-service.md).

The first two fixes were mutation-tested — the dropped-call warning
fails 2 guards without its change, `/model info` fails 6. The tool-strip
change was mutation-tested too, each mutation failing exactly one test:
groups re-appended to the container, `endToolTurn` dropped from the
`finally`, the `clearConversation` reset removed, details re-gated on
verbose, the VSCode wrapper renamed, and the collapse rule deleted from
the stylesheet.

`tests/test_parallel_tool_call_drop_logging.py` fences both halves of the
first fix. Its logger double is `create_autospec`, **not**
`MagicMock(spec=Logger)`: measured against the exact call shape that
broke — `common.logger.Logger.warning` is `(msg, exc_info=False)` and
takes no format arguments, so a lazy `%`-args call raises `TypeError`
inside the tool loop — `MagicMock()` and `spec=` both *accept* it and
hide the bug, while autospec and the real `Logger` both raise. `spec=`
constrains which attributes exist; it says nothing about how they may be
called. The first version of those tests used a bare `MagicMock` and
passed against the broken call. (`bd687a15`)

Local install verified on macOS Intel (x86_64, 12.7.6) after the version
bump: all four binaries plus `/Applications/ppxai.app` report **1.19.3**,
`~/.ppxai/web` diffs clean against the source tree, gateway-smoke **7/7**
(including `/v1/agent/run` and `/v1/agent/task` to finalized), and
`/files/preview` returns a real 1500×1125 PNG — the check that catches a
build missing the `[data]` extras.

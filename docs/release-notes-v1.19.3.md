# Release Notes — v1.19.3

> **Scope:** Started as a two-fix observability release and grew to
> **nine fixes, one transcript change, and ADR 0007's one-command-registry
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
> tool-loop iteration count. The last lands with the turn-level tool
> strip in the web and VSCode transcripts, which also fixes a chevron
> that could expand to nothing.
>
> **Command-surface changes, landed and Accepted 2026-09-21 (ADR 0007).**
> `CommandSpec` is now the single declaration for every command;
> completion, `/help` and both JS clients' menus derive from it. **This
> release DOES remove a command from web and VSCode**: `/quit` is gone
> from both — web's header button is now "Leave", VSCode uses its
> existing connect/disconnect commands; `/quit`/`/exit` are unaffected
> in the Rich and Textual TUIs. Both JS clients now fail CLOSED on slash
> commands when the roster can't be fetched (e.g. newer web assets
> against an older server). See "One command registry" below for the
> rest — subcommand display in `/help`, `/tools help` reaching Rich and
> Textual, VSCode's `/tools`/`/context`/`/ls`/`/tree` now server-rendered.
>
> No config-shape changes. The shipped microk8s
> coder template changes shape, but it is an example: nothing in an
> existing install reads it. The v1 API gateway (`POST /v1/oneshot`,
> bearer auth) and the `/v1/agent/*` surface are **byte-identical to
> v1.19.2** — ppxai-sre and any other v1 consumer is unaffected.

## Branch

`bugfix/v1.19.3` (from master @ v1.19.2), **42 commits ahead of master**
at the time of writing — re-derive with `git rev-list --count
master..HEAD`; uncommitted work in the tree lands as further commits
before tagging, so this count is a floor, not a final tally. Nine fixes
and a web/VSCode transcript feature carried the branch through
2026-09-16 (see Verification below for that tree's test state); ADR
0007's one-command-registry work (steps 1–5 plus the same-day follow-ups
in "One command registry" below) landed 2026-09-21.

Nothing in this release requires an upgrade step. If you run tool loops
against models whose facts rows you have not checked, the first fix is
the reason to take it; if you serve the 27B-FP8 Qwen line, the catalog
fix is; if you script against web or VSCode's `/quit`, switch to the
"Leave" button / connect-disconnect commands.

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
  `/context`, `/ls` and `/tree` are now server-rendered via
  `POST /command/<name>` (`/checkpoint` is the one VSCode command that
  stays client-side for now: `/checkpoint clear`'s irreversible delete
  needs a confirmation, and the owner decided 2026-09-21 to build one
  that works in all four clients, including both TUIs, before
  `/checkpoint` migrates — implementation in progress);
  `/context clear` no longer leaves a stale Ctx% badge; three stale
  `/tools agent` hint strings (retired by ADR 0011) are fixed.

## Fixed

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
  existing vision/native test pins both 3.8 ids. This is the one
  model-catalog change in the release. (`f5d2c078`)

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

### The guard against over-reach

Comparing a value to `UNMEASURED` cannot by itself tell a guess from a
measurement that happens to agree with the guess. So the `/model info`
fix above is gated on `has_global_row`: a model with its own row in
`SHIPPED_MODEL_FACTS` keeps `(built-in)` on **every** field, and only a
model resolved *solely* through a provider row is compared field by
field. `o3*`'s measured-serial `parallel_tool_calls=False` and
`gemini-3.1-pro*`'s are findings, not floors, and are never relabelled as
guesses. Tests pin both.

## Changed

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

**Open items: 20** (re-derived from the "Open at a glance" table, not
carried over — Items 73 and 74 filed, Item 34 closed).

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

Full suite at `b067ce9c` (branch HEAD) on macOS with
`uv sync --all-extras`: **5,909 passed, 1 skipped, 0 failed** in 535s.
Windows at the same point in the branch, measured on the other host:
**5,878 passed, 32 skipped, 0 failed** @ `1c1beac4`; the extra skips are
the usual platform gates (PTY, symlink cases, POSIX signal semantics).
The Playwright specs under `tests/e2e/` are not in either count —
**209 passed** there, including the 9 new `tool-turn.spec.ts` tests.

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

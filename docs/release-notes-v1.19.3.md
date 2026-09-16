# Release Notes — v1.19.3

> **Scope:** Started as a two-fix observability release; two more landed
> on the same branch ahead of tagging. The first two entries make an
> **existing silent degradation visible**; neither changes what the send
> path does, and neither changes a resolved fact value. The other two
> close out the 2026-09-27 Perplexity Sonar chat-completions retirement on
> the web_search tool's own code path (the provider side was already
> fixed under ADR 0012 W3) — one of them **does** change a code default.
> No config-shape changes, no command renames, no model-catalog changes.
> The v1 API gateway (`POST /v1/oneshot`, bearer auth) and the
> `/v1/agent/*` surface are **byte-identical to v1.19.2** — ppxai-sre and
> any other v1 consumer is unaffected.

## Branch

`bugfix/v1.19.3` (from master @ v1.19.2). Five commits: two fixes, two
docs, one version bump.

Nothing in this release requires an upgrade step. If you run tool loops
against models whose facts rows you have not checked, the first fix is
the reason to take it.

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

### The guard against over-reach

Comparing a value to `UNMEASURED` cannot by itself tell a guess from a
measurement that happens to agree with the guess. So the second fix is
gated on `has_global_row`: a model with its own row in
`SHIPPED_MODEL_FACTS` keeps `(built-in)` on **every** field, and only a
model resolved *solely* through a provider row is compared field by
field. `o3*`'s measured-serial `parallel_tool_calls=False` and
`gemini-3.1-pro*`'s are findings, not floors, and are never relabelled as
guesses. Tests pin both.

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

## Known limitations

- Both fixes are proven by unit tests and mutation checks, not by a live
  tool loop on the installed binaries. The acceptance check for the first
  is a multi-call turn against a model whose row is still `False` —
  `~/.ppxai/logs` should now carry the warning; for the second, `/model
  info` on any `openai/*`-style id served through the Perplexity gateway,
  where nine fields should now read `(unmeasured)`.
- Everything Item 46 covered in v1.19.1 still stands: `execution.task.*`
  has no dual-read from `tools.agent.*`, and `/doctor` prints what each
  stale key costs. Unchanged by this release.
- The Anthropic provider remains **opt-in and untested against the live
  API**, as recorded in v1.19.1 (debt Item 71, an accepted limitation).

## Verification

Full suite at `bd687a15` on macOS with `uv sync --all-extras`: **5,882
passed, 1 skipped, 0 failed**. Both fixes were mutation-tested — the
first fails 2 guards without its change, the second fails 6.

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

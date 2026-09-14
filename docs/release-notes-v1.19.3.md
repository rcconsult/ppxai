# Release Notes — v1.19.3

> **Scope:** A two-fix observability release. Both entries make an
> **existing silent degradation visible**; neither changes what the send
> path does, and neither changes a resolved fact value. No new features,
> no config-shape changes, no command renames, no model-catalog changes.
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

### The guard against over-reach

Comparing a value to `UNMEASURED` cannot by itself tell a guess from a
measurement that happens to agree with the guess. So the second fix is
gated on `has_global_row`: a model with its own row in
`SHIPPED_MODEL_FACTS` keeps `(built-in)` on **every** field, and only a
model resolved *solely* through a provider row is compared field by
field. `o3*`'s measured-serial `parallel_tool_calls=False` and
`gemini-3.1-pro*`'s are findings, not floors, and are never relabelled as
guesses. Tests pin both.

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

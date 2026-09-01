# Shared lessons

Cross-host engineering hazards and verified architectural facts that
any agent (AI or human) working on this codebase should know **before**
they start re-deriving them.

This directory exists because per-host AI memory
(`~/.claude/projects/<repo>/memory/` on each developer's machine) does
NOT sync. A lesson written on macOS isn't visible to a session on
Windows. Authoritative cross-host knowledge belongs in the repo, where
`git pull` is the sync mechanism.

## What belongs here

A lesson belongs in `docs/lessons/` when it meets **all three**
criteria:

1. **Cross-host relevance.** The lesson is true on any machine running
   this repo — not specific to one host's path quirks, shell, or
   installed-tool versions.

2. **Verifiable from code.** A reader can `grep`, open a file, or run
   a one-line check to confirm it. The lesson is grounded in
   observable repo state, not in "Claude on Windows once hit X."

3. **Changes what a reader DOES.** The lesson names a different action,
   check, or default — not merely a thing to be aware of. "Keep an eye
   out for X" fails this test; "assert the precondition that selects
   the mutated path before believing a pass" passes it.

   The third criterion is the one that rejects a *true, verified,
   cross-host* observation. On 2026-09-01 a fifth instance of
   pipeline-exit-code laundering was found while verifying something
   else — real, reproducible, and already documented in
   [mutation-tests-that-never-ran.md](mutation-tests-that-never-ran.md)
   §2. A sixth file saying "this keeps happening" would have added a
   frequency claim and no new action. A repeat sighting of a documented
   shape is evidence the existing lesson is right; it earns a sentence
   there at most, never a file of its own.

Examples of cross-host + grep-verifiable lessons:

- "ppxai imports `mcp` nowhere — the `[mcp]` optional extra is intent,
  not implementation" (verifiable: `Grep "import mcp" ppxai/`)
- "`tool_manager.py:193` hardcodes `source: engine`, blocking
  extension by external tool sources" (verifiable: open the file)
- "ADR 0006 producer-side keys MUST stay off the wire — the
  `__debug__`-gated `assert_wire_blocks_clean` validator enforces it"
  (verifiable: read `engine/uploaded_file.py`)

## What does NOT belong here

Stays in per-host memory (`~/.claude/projects/<repo>/memory/`):

- **User-preference notes** — "this user prefers terse responses",
  "don't expand scope without permission"
- **Host-specific paths** — Windows `code.cmd` shim, macOS `hdiutil`
  invocations, rtk hook is bash-only on Windows
- **Session scratchpads** — "branch X in flight, commit Y next",
  "just verified Z this turn"
- **Agent self-discipline reminders** — "verify both directions",
  "read files don't infer"

These stay private because they're either personal preference or
ephemeral context. Promoting them here would mix signal (engineering
hazards) with noise (per-developer prefs) and hurt both.

## Format

Each lesson is a short markdown file with this shape:

```markdown
# <Short title — the lesson, not the symptom>

**TL;DR:** One sentence stating the fact.

**Verify with:** `<grep command | file path | one-line check>`

## Why this trips people up

What looks like evidence-of-X that actually isn't, or the surprising
behavior that doesn't match the obvious mental model. The trap.

## What's actually true

The fact, grounded in repo state. Include file path + line numbers
where they help the reader confirm.

## Related

Links to ADRs, ROADMAP entries, or other lessons.
```

Keep each lesson under 100 lines. If the topic needs more space,
it's probably an ADR or design doc, not a lesson.

## Promotion workflow (for AI agents)

When you discover a hazard during a session:

1. **Triage:** does it meet all three criteria above (cross-host +
   grep-verifiable + changes what a reader does)?
2. **If yes:** propose adding a `docs/lessons/<topic>.md` file in
   the user-facing summary of your turn. Don't auto-commit;
   the user decides whether the lesson is worth the repo's
   permanent attention.
3. **If no:** save to your per-host memory only.

Same gesture as filing an ADR — deliberate, human-in-the-loop,
discoverable later.

## Index

- [mcp-not-yet-integrated.md](mcp-not-yet-integrated.md) — ppxai
  has filename-level MCP breadcrumbs but zero integration; v1.20.x
  plan at `docs/MCP-INTEGRATION-PLAN.md`
- [config-source-resolution.md](config-source-resolution.md) —
  `PPXAI_CONFIG_FILE` (often set via repo-root `.env`) overrides
  `./ppxai-config.json`; editing the obvious project config can
  silently have no effect on the server
- [loopback-ui-auth-exemption.md](loopback-ui-auth-exemption.md) —
  with auth on, loopback `/chat` + `/files/read` are bearer-EXEMPT by
  source-IP alone (any local process, not just the operator's browser);
  deliberate desktop-UX choice, not a bug — don't drive-by "fix" it
- [testclient-per-request-event-loop.md](testclient-per-request-event-loop.md) —
  non-context `TestClient(app)` gives every request its own event loop;
  a background task that must live ACROSS requests (T5 consent park)
  silently dies — use `with TestClient(app) as c:` (`ctx_client` fixture)
- [stale-server-invalidates-acceptance.md](stale-server-invalidates-acceptance.md) —
  ppxai-server binds a FIXED port (54320); a stale server makes a freshly
  spawned binary die silently, so acceptance tests the OLD process — free
  the port first (`gateway-smoke.py` now guards this)
- [perplexity-alternation-retired-orphan-toolcalls-is-real.md](perplexity-alternation-retired-orphan-toolcalls-is-real.md) —
  Perplexity Sonar relaxed the old "messages must alternate" rule (verified
  live); the recurring tools-chat 400 is the provider-agnostic orphan
  `assistant.tool_calls` case — check the actual wire error before adding
  another alternation patch
- [stale-tests-outlive-deleted-behavior.md](stale-tests-outlive-deleted-behavior.md) —
  removing a behavior leaves its tests behind; they fail as assumed-
  environmental noise or keep passing against a renamed surface while
  guarding nothing. Invert, retarget, or delete — and mutation-test the fence
- [qwen-27b-vl-empirically-supported.md](qwen-27b-vl-empirically-supported.md) —
  Qwen3.5/3.6-27B-FP8 empirically accept `image_url` content via vLLM;
  ppxai's `model_profiles.py` lacked `supports_vision=True` entries for them
  (fixed 2026-06-08, `model_profiles.py:481-505`)
- [web-assets-served-from-ppxai-home.md](web-assets-served-from-ppxai-home.md) —
  clients serve the web UI from `~/.ppxai/web`, not the repo source tree;
  editing `web/` in-repo has no effect on a running server without
  `PPXAI_WEB_DIR` pointed at the checkout
- [absence-is-invisible-in-listings.md](absence-is-invisible-in-listings.md) —
  a `/models` sweep cannot detect your own dead ids: a retired model vanishes
  from the listing, so it looks like an id you never noticed. Call each
  configured id; a 410 carries the EOL date. Four models shipped broken for
  six weeks this way. Also: a `replacement` is a liveness claim, so re-verify
  replacements whenever a provider is swept.
- [resolver-vs-direct-path-checks.md](resolver-vs-direct-path-checks.md) —
  calling a parser with a path you chose proves the file parses, not that it
  is the file the app loads. `find_bootstrap_file()` picks `AGENTS.md` here,
  not `CLAUDE.md`. When the question is "which one?", call the picker.
- [tests-whose-premise-expires.md](tests-whose-premise-expires.md) — a test
  asserting something is *absent* silently stops testing when the roadmap
  makes it present. Assert absence with a name nothing will ever claim.
- [clean-break-config-moves-need-a-file-scan.md](clean-break-config-moves-need-a-file-scan.md) —
  a config key moved with NO dual-read is invisible to every accessor, so a
  stale key silently reverts to its default; only a check that reads the
  config FILE can detect it (`/doctor`'s ADR 0010 section) — ship that scan
  with the move, not as cleanup

- [parity-harness-must-know-every-client.md](parity-harness-must-know-every-client.md)
  — a multi-client parity harness that knows N-1 clients is a blind spot. Adding
  a client is a change to the harness FIRST. Cost: three shipped-missing
  capabilities that no test caught (2026-08-09).
- [module-level-home-paths-leak-into-user-state.md](module-level-home-paths-leak-into-user-state.md)
  — `Path.home()` constants resolve at IMPORT time, so isolating a directory
  through a constructor does not stop a test writing the user's real state.
  Cost: the suite silently clobbered the developer's session pointer.

- [sdk-validation-is-not-api-acceptance.md](sdk-validation-is-not-api-acceptance.md)
  — a provider SDK's request model and the provider's REST API are two
  different validators. Constructing a request the SDK accepts proves the
  shape is well-formed locally, not that the endpoint will take it.
- [a-check-that-never-ran-reports-success.md](a-check-that-never-ran-reports-success.md)
  — verification tooling fails SILENT far more often than loud, and every
  silent failure is shaped like success. `pytest | grep` returns exit 0 with
  six tests failing (reproduced: direct 1, piped 0); a zero-output helper
  exits non-zero and kills an `&&` chain before the real work; `ruff --select
  <RULE>` reports a different count than a full run; a sweep missing one
  patching idiom declared a batch safe that then shipped 15 failures. Read
  the COUNTS, never the exit code — "5,684 passed" cannot be forged by a
  pipe. A false "fine" ships; a false "broken" only costs time (2026-09-01).
- [mutation-tests-that-never-ran.md](mutation-tests-that-never-ran.md) — a
  mutation test's failure modes all resolve to "all green", which is what a
  covered guard also looks like. An anchor that matches twice patches the
  wrong function; a runner that cannot start prints nothing; a trailing
  `| tail` launders the exit code; and a correct mutation on an unreachable
  line (no `.git` -> the fallback branch runs) passes every one of those
  checks and still proves nothing. Prove the mutation applied, that the
  mutated line RUNS here, and that the suite ran — then check WHICH test
  failed. Cost: two sessions read the same false "not covered", this file's
  own snippets were wrong until someone ran them (2026-08-31), and two
  sessions hit the reachability shape on one fence (2026-09-01).
- [ruff-safe-fixes-are-not-semantically-safe.md](ruff-safe-fixes-are-not-semantically-safe.md)
  — ruff's safe/unsafe split is confidence about SYNTAX, not meaning. A
  *safe* `UP045` fix rewrote `Optional[callable]` to `callable | None`,
  which raises `TypeError` at import and would have stopped the product
  starting; an *unsafe* `F841` fix leaves the right-hand side as a bare
  statement — dead code that still executes. A 384-file bulk `--fix` also
  regressed `F811` and `E402` from zero, caught by the CI ratchet rather
  than by a green suite (2026-09-01).

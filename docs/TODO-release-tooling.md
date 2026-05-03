# TODO: Release tooling hardening (v1.18.1+)

**Status:** Closed 2026-05-03. All three confirmed defects have landed
fixes; acceptance criteria met. See "Closed" section at the bottom.

The v1.18.0 release shipped successfully but the path was bumpy. This
document tracks the specific fixes so they don't get lost.

## Confirmed defects

### 1. `release.py` watches the wrong CI workflow

**Bug.** `wait_for_ci(version)` calls `gh run list` and treats the
first matching run for the tag as authoritative. When two workflows
trigger from a tag push (`Build Executables` and `Deploy Documentation`),
the script can pick up the docs workflow's success and declare the
release complete while `Build Executables` is still running — or
already failed. v1.18.0 hit exactly this: docs deploy went green in
~25s, build executables failed in tests at ~70s; script announced
success at the 70s mark while the build job was already in `failure`
state.

**Effect.** If trusted, the script publishes "release complete" with
no binaries on the GitHub Release. The user has to notice manually.

**Fix.** **Landed 2026-05-03.** `wait_for_ci` now passes
`--workflow="Build Executables"` to `gh run list`, so docs deploys
and any other concurrent workflows on the tag are excluded from the
gate. The existing `seen_in_progress` guard remains as a second
defense against stale completed runs.

**Files.** `scripts/release.py::wait_for_ci` (~line 619).

**Status.** Done.

### 2. `release.py --dry-run` performs the master merge

**Bug.** The "merge to master if on a feature branch" step ignored
`args.dry_run`, so a dry-run preview unconditionally executed
`git checkout master && git merge feature/X --no-edit` before
printing the dry-run summary.

**Effect.** User runs a "harmless preview," ends up on master with
a real merge commit, and now has to either continue from there or
manually reset.

**Fix.** Landed on master at commit `7d5b1700`:
`merge_to_master_if_needed` now accepts `dry_run=True` and prints the
four git commands without executing them.

**Status.** Done. **Regression test landed 2026-05-03** in
`tests/test_release_dry_run.py`: three tests pin the contract that
`merge_to_master_if_needed(..., dry_run=True)` invokes zero
subprocess calls, plus a sanity test that `dry_run=False` still
calls the real git commands (catches a "always skip side effects"
rewrite regression).

### 3. Cross-language test passes locally, fails in CI

**Bug.** `tests/test_usage_format.py::_extract_ts_function` extracted
TypeScript code and ran it under node *as-is*. Local node 24 was
permissive enough to accept some TS syntax (`name: type` parameter
annotations) silently. CI runs node 20, which correctly rejects this
with `SyntaxError: Unexpected token ':'`. 13 cross-language parity
tests failed only in CI.

**Effect.** v1.18.0 first release attempt CI failed; tag was already
pushed; release object never got created; script reported "complete"
anyway (see defect #1).

**Fix.** **Landed on master** (commit `6e7e0741`): new
`_strip_ts_syntax` helper removes TS-only syntax (parameter type
annotations, return type annotations, `export` keyword) before
handing the function body to node. Verified passing locally.

**Status.** Done.

**Generalisation worth tracking.** Local test runs use whatever node
version is on PATH (node 24 on this dev machine). CI uses node 20.
Any test that shells out to `node` is at risk of the same drift.
Two options:

- (a) **Pin node version in dev shell** — add a `.nvmrc` or a `tools.
  node = "20.x"` config so `npm`/`npx`/`node` invocations match CI.
- (b) **Run cross-language tests under multiple node versions in CI**
  — extends the test matrix slightly, catches drift in either
  direction.

Recommend (a) — single source of truth for the version.

**Generalisation status.** **Landed 2026-05-03.** `.nvmrc` at repo
root pins `20`. nvm/fnm/asdf and most CI setup-node actions read
this file when no explicit version is specified, so local node
invocations from tests will match CI by default.

## Procedural lessons

### 4. No working dry-run path

**Symptom.** I ran `--dry-run` to verify before the destructive
operation, hit defect #2, and chose to continue from the partially-
mutated state ("the merge happened, master is where the real run
wants us anyway"). That was the wrong call: a dry-run with side
effects shouldn't be normalised by working around it. **Fix #2 is the
actual fix.** This entry exists to flag that decision-making policy.

**Rule.** If a dry-run produces unexpected mutations, *abort and
fix the dry-run first*, even if continuing seems faster. The
asymmetry is: a broken dry-run that "works once you know its quirks"
makes future releases riskier; fixing it costs an hour.

### 5. The broken `release_preflight_check.py` should have been
fixed-or-deleted on first contact

**Symptom.** During Phase 5 I noticed the pre-flight script was
hardcoded for v1.15.0, half-fixed the UTF-8 issue, and reverted the
half-fix. Should have just deleted it then (which I did later in
Phase 5h). Leaving a stale-but-attractive script in `scripts/` cost
me time during the v1.18.0 release attempt.

**Rule.** When discovering broken tooling: fix it, replace it, or
delete it on first contact. Leaving "this exists but doesn't work"
is the worst of three options.

## Out-of-scope but related

These came up during the release but belong elsewhere:

- **GitHub Actions Node.js 20 → 24 migration.** Already addressed
  with `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` in
  `.github/workflows/build.yml` and `docs.yml` (commit `67b0774a`).
  Verified safe in the post-release docs deploy. Drop the env var
  once every action has shipped a v5+ release.

- **`release.py` `--allow-dirty` plumbing.** Already addressed
  (commit `ec20d48d`). `validate-release.py` now accepts the flag;
  `release.py` passes it. Standalone validator usage unchanged.

## Acceptance criteria for closing this TODO

1. `release.py --dry-run` performs **zero** git mutations. Verify
   by running on a feature branch and confirming `git status` is
   unchanged after the dry-run completes.
2. `release.py` waits specifically for the `Build Executables`
   workflow's outcome, not "any workflow on the tag."
3. Cross-language tests run under the same node version locally
   and in CI (option (a) above, or comparable).
4. Each fix has a corresponding test or runbook entry that would
   have caught the original bug. No regressions on `validate-release.py`.

## Suggested order

1. **#3 generalisation** (node version pinning) — smallest, prevents
   the same class of bug for free. Add `.nvmrc` with `20`.
2. **#1** (workflow filter) — most impactful for trustworthiness of
   release script.
3. **#2 verification** — confirm the dry-run fix landed and write a
   regression test that runs `--dry-run` and checks `git status`.

Estimated total: half a day of focused work. Worth scheduling for
v1.18.1 alongside the routing/codegen workstreams.

# A check that never ran is indistinguishable from a check that passed

**TL;DR:** Verification tooling fails silent far more often than it fails
loud. A pipe swallows an exit code, a helper that prints nothing exits
non-zero and kills an `&&` chain, a rule selector changes which files are
examined. In every case the signal you get back is the same one a healthy
run produces. Read the **counts**, not the status.

**Verify with:**
```bash
pytest tests/ -q | grep -E "passed|failed"   # exit code is grep's, not pytest's
echo $?                                       # 0 even with failures
```

## Four measured instances, all 2026-08-31/09-01

### 1. `pytest | grep` reported exit 0 with six failures

```bash
pytest tests/ -q -k "..." | grep -E "^FAILED|passed"
# PYTEST_EXIT=0 — and the harness's own task notification said
# "completed (exit code 0)"
```

Six tests had failed. `$?` belongs to the last command in a pipeline, so it
was grep's status, not pytest's. The laundering was invisible at two levels:
the shell reported success and so did the task runner. Caught only by
reading the output file, which said `6 failed`.

The fix is to write the log to a file, read `$?` straight from pytest, and
grep the file separately:

```bash
pytest tests/ -q > run.log 2>&1; echo "EXIT=$?"
grep -E "^FAILED|passed|failed" run.log
```

### 2. A zero-output helper killed an `&&` chain

`git status --porcelain` on a clean tree prints nothing. Under a wrapper
that made it exit non-zero, this died at the first link:

```bash
cd <dir> && git status --porcelain && git log -1 && pytest tests/
```

The output file held only the *previous* run's `git log` line — 88 bytes,
unchanged for 13 minutes. `tail -4` on it returns that line, which is exactly
what a healthy run looks like before pytest flushes. The tell that was
available the whole time and went unread: **no new bytes since launch**.

Never put a status- or grep-shaped command in an `&&` chain ahead of the
thing you actually want to run.

### 3. `ruff --select <RULE>` reports a different count than a full run

Selecting a rule changes which files are examined, because per-file ignores
stop applying. `F841` reads 112 in a full run and 116 under `--select F841`.
Quoting either without saying which denominator produced it misleads. Use
`--statistics` for per-rule figures.

### 4. A sweep that misses an idiom says "safe" as confidently as anything

A sweep for tests that patch a name searched `patch` and `patch.object`, found
18 hazards, and declared a batch safe. The batch shipped **15 failures**, all
`monkeypatch.setattr(module, "name", ...)` — an idiom the sweep had never
looked for. Widened, the count was 24.

The inverse also happened: a search for `patch("ppxai.engine.task_authorizer.X")`
returned zero hits and was read as "this annotation is unfounded". But a patch
does not have to name the importing module — `monkeypatch.setattr(provmod,
"get_provider_class", boom)` patches the **source** module, and the lazy import
is what routes the call through it. Hoisting those imports broke seven tests.
The zero-hit count was measuring the wrong shape.

## Why this species is worth its own lesson

These are not carelessness; each one produces a result that is
*well-formed*. Exit 0 is a real exit code. An empty grep is a real empty
grep. A rule count is a real count. Nothing raises, nothing warns, and the
output is shaped exactly like success — so the more disciplined you are about
"check before claiming", the more of these you walk into, because the check
itself is what lied.

The asymmetry that matters: a false "broken" costs an investigation, a false
"fine" ships. Bias the reading accordingly.

## The rule

1. **Counts are the receipt, not the exit code.** `5,684 passed, 32 skipped`
   cannot be forged by a pipe; `exit 0` demonstrably can.
2. **A zero-length or unchanged output file is a failure signal**, not a
   pending one. Compare bytes against launch, not against nothing.
3. **Never chain a status/grep-shaped command ahead of the real work.**
4. **A zero-hit search is a hypothesis about your query**, not a fact about
   the code — especially when acting on it is destructive.
5. **Say which denominator a count came from**, since selecting a rule or a
   path changes it.

## Related

- [`mutation-tests-that-never-ran.md`](mutation-tests-that-never-ran.md) —
  the same species inside a mutation test: the mutation not applying looks
  exactly like the fence not catching it.
- [`ruff-safe-fixes-are-not-semantically-safe.md`](ruff-safe-fixes-are-not-semantically-safe.md)
  — a tool's own confidence signal describing something narrower than you
  assume.
- [`absence-is-invisible-in-listings.md`](absence-is-invisible-in-listings.md)
  — a quiet answer indistinguishable from a good one.

# A mutation test proves nothing until you prove it ran

**TL;DR:** Mutation testing answers "would anything catch this regression?"
and its failure modes all resolve to **all green**, which is the same thing a
covered guard looks like. Before believing a mutation result, prove two
things: **the mutation applied to the line you meant**, and **the suite
actually executed**.

**Verify with:**
```bash
grep -c 'not probe.get' ppxai/commands/doctor.py     # 2 — one anchor, two sites
```
Two byte-identical guards, 68 lines apart, in different functions. A
`replace(..., 1)` or an unanchored `sed` hits the first one every time.

## Three ways a mutation result lied, all on 2026-08-31

All three were produced by people deliberately being careful. None raised an
error.

### 1. The anchor matched twice

`if not probe or not probe.get("reachable"):` appears at
`ppxai/commands/doctor.py:429` (`detect_context_limit_drift`) and `:497`
(`detect_uncatalogued_models`). Mutating "the guard" patched line 429 while
the tests exercised the function at 497, so the suite passed — and that reads
exactly like *this guard has no fence under it*.

Two sessions ran the same mutation independently and both got the same wrong
reading. It surfaced only when one of them could not explain **why** the
mutated input still returned `[]`, and instrumented the call directly.

Mutate by index, or assert the anchor is unique first:

```python
assert src.count(ANCHOR) == 1, f"anchor matches {src.count(ANCHOR)} sites"
```

### 2. The suite never started

A mutation run in a detached worktree under `/c/tmp`: the worktree has no
venv, so every `uv run pytest` failed to spawn. The output was piped through
`| grep -E "passed|failed"`, which matched nothing and printed nothing.
Blank output was read as a clean run.

Reproduce the shape:
```bash
cd /c/tmp && uv run pytest -q 2>&1 | grep -E "passed|failed"; echo "exit=$?"
# prints nothing; grep exits 1; the pipeline's own status is 0
```

**Silence is not success.** A grep filter over a command that never ran looks
identical to a grep filter over a command that passed. Take a **baseline
first** and require it to be non-zero:

```bash
BASE=$(pytest -q 2>&1 | grep -cE "^[0-9]+ passed")
[ "$BASE" -gt 0 ] || { echo "suite did not run"; exit 1; }
```

### 3. The verification grep didn't look

Checking whether the duplicate anchor was still present, a `grep` whose
pattern carried unescaped `(` and `"` returned **0 matches** on a file that
contains two. That "confirmed" the opposite of the truth, in one line, while
double-checking a lesson about checks that do not check.

## Why this species is worth its own lesson

The three failures are the same shape: **a check that cannot fail reports the
same thing as a check that passed.** That is also the shape of
[`clean-break-config-moves-need-a-file-scan.md`](clean-break-config-moves-need-a-file-scan.md)
(a moved key is invisible to every accessor) and of
[`absence-is-invisible-in-listings.md`](absence-is-invisible-in-listings.md)
(a retired model just vanishes). In each case the tooling's *quiet* answer is
indistinguishable from its *good* answer.

Mutation testing is the highest-leverage place to get this wrong, because its
whole purpose is to be the check on the checks. A false "not covered" wastes
an afternoon; a false "covered" ships a fence with nothing behind it and
retires the suspicion that would have found it.

## The rule

1. **Prove the mutation applied.** Assert the anchor is unique, or address the
   line by index and read it back.
2. **Prove the suite ran.** Baseline count first; a non-zero test count is
   the receipt. Never let a filter be the only thing you read.
3. **Prove the right test failed.** "1 failed" is not enough — check it is the
   test that *names* the guard. A mutation caught by an unrelated test means
   the fence you were checking still has nothing under it.
4. **Restore and re-run.** Confirm green again before drawing any conclusion,
   and confirm the restore by content, not by having run a `cp`.

## Related

- `tests/test_doctor_uncatalogued.py` — `test_unreachable_beats_a_stale_non_empty_catalog`
  is the fence that closed the gap found here; it is the only test that fails
  when line 497 is weakened.
- Lesson promotion criteria: [README.md](README.md).

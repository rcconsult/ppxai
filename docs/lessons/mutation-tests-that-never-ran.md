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

Reproduce the shape — and note which line actually hides the failure:

```bash
# grep alone REPORTS the problem: $? is grep's own status.
cd /c/tmp && uv run pytest -q 2>&1 | grep -E "passed|failed"; echo "exit=$?"
# prints nothing, exit=1   <- visible, if you look at it

# One more stage and the signal is gone. `tail` succeeds on empty input,
# so the pipeline's status becomes tail's 0 and grep's 1 is discarded.
cd /c/tmp && uv run pytest -q 2>&1 | grep -E "passed|failed" | tail -1; echo "exit=$?"
# prints nothing, exit=0   <- indistinguishable from a clean run
```

The lesson is not "grep hides failures" — grep reported it correctly. It is
that **any trailing stage that tolerates empty input launders the exit
code**, and `| tail -1`, `| head -1`, `| sort` are exactly the stages people
append to tidy up output.

**Silence is not success.** A grep filter over a command that never ran looks
identical to a grep filter over a command that passed. Take a **baseline
first** and require it to be non-zero:

```bash
BASE=$(pytest -q 2>&1 | grep -cE "^[0-9]+ passed")
[ "$BASE" -gt 0 ] || { echo "suite did not run"; exit 1; }
```

### 3. The verification grep didn't look

Checking whether the duplicate anchor was still present, a grep returned
**0 matches** on a file that contains two — "confirming" the opposite of the
truth while double-checking a lesson about checks that do not check.

The cause is the regex dialect, and the contrast is the whole teaching:

```bash
grep -c  'if not probe or not probe.get("reachable"):' ppxai/commands/doctor.py   # 2
grep -cE 'if not probe or not probe.get("reachable"):' ppxai/commands/doctor.py   # 0
```

Plain `grep` is BRE, where `(` is a literal character and the pattern matches
fine. `-E` switches to ERE, where `(` opens a group — the pattern is still
*valid*, so there is no error, it simply stops matching. A habit of reaching
for `-E` "because it is the better regex" silently turns a search for
parenthesised code into a search for nothing.

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

## Both of the corrections above were found the same way

The first version of this file got §2 and §3 wrong — it printed an exit code
the pipeline does not produce, and blamed "unescaped parens" for what is
actually a BRE/ERE difference. A reader reproducing either one would have got
a result contradicting the text and concluded the lesson was wrong.

They were caught by a reviewer **running the snippets** rather than reading
them. That is the fourth instance of this file's own species, inside the file
warning about it: a plausible illustration that nobody had executed. If a
document tells you to verify, its own examples are the first thing to verify.

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

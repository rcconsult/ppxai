# ruff's safe/unsafe split is syntactic confidence, not semantic safety

**TL;DR:** `ruff check --fix` classifies a fix as *safe* when it is
confident about the **syntax** of the rewrite — not when it is confident
the program still means the same thing. A **safe** fix broke `import
ppxai` outright, and an **unsafe** fix produced code worse than the
finding it removed. Read the diff of a bulk `--fix` before committing
it, especially for `UP045` and `F841`.

**Verify with:**
```bash
python -c "callable | None"        # TypeError
python -c "from typing import Optional; Optional[callable]"   # legal
```

## 1. A SAFE fix that kills the package (`UP045`)

`UP045` rewrites `Optional[X]` to `X | None`. In `engine/client.py` the
annotation was `Optional[callable]` — `callable` being the **builtin
function**, not a type. Measured:

```
Optional[callable]   -> legal. Subscripting a builtin is meaningless but harmless.
callable | None      -> TypeError: unsupported operand type(s) for |:
                        'builtin_function_or_method' and 'NoneType'
```

The annotation is evaluated while the class body executes, so the
rewrite turns a latent, harmless wrongness into a **hard failure at
import**. `import ppxai` raises; the product does not start.

This is not behind `--unsafe-fixes`. ruff considers it safe, and by its
own definition it is: the rewrite is syntactically faithful. The
annotation was already wrong; `Optional[...]` was hiding it. The correct
fix is `Callable`, not the mechanical one.

## 2. An UNSAFE fix worse than the finding (`F841`)

`F841` flags an assignment never read. The obvious fix is to delete the
line. ruff does not do that — it keeps the right-hand side as a **bare
expression statement**:

```python
# before
source_name = Path(hints_info["source"]).name
# after `ruff check --select F841 --unsafe-fixes --fix`
Path(hints_info["source"]).name
```

Dead code that still executes, replacing a dead binding that did not.
Reproduced standalone on a three-line file. Roughly 8 of 109 findings
had this shape.

ruff is right to call it unsafe — deleting an assignment whose RHS has
side effects would change behaviour, so it declines to guess. But the
alternative it chose is not a safe middle ground, and running
`--unsafe-fixes` across a bulk count without reading the diff ships it.

**The same rule needs three different dispositions**, which no flag can
choose between:

| shape | disposition |
|---|---|
| pure dead assignment | delete the line |
| `asyncio.get_running_loop()` | keep the CALL, drop the binding — it raises `RuntimeError` and the `except` below is the control flow |
| `except ... as e`, `e` unused | drop the binding only |

## 3. The corollary: a bulk `--fix` regresses rules already at zero

A 384-file mechanical pass (`UP006,UP045,I001,F401,UP035,F541`) drove
ruff 3,701 → 408 and introduced **21 new findings in rules that were at
zero**:

- **18 × `F811`** — hand-restoring re-exports appended an import block
  instead of merging, so seven files imported the same names from the
  same module twice. Harmless at runtime, so the suite stayed green; the
  `# noqa: F401` added alongside silenced the rule that would have
  pointed at it.
- **3 × `E402`** — `I001` reordering split a `# noqa: E402` block in two,
  and the second half lost the marker. All three placements were
  deliberate (after `register_provider`, after `importorskip`).

Both were verified as regressions by running ruff on the parent commit,
not by memory.

Neither a green full suite (5,684 passed, 32 skipped, both before and
after) nor per-batch scoped runs caught any of it. **A CI ratchet did**,
once widened: the workflow gates only rules standing at zero
(`F821,F822,F823,F632,F811,E402` in
`.github/workflows/build.yml`), so a class that regresses fails the
build even when every test passes.

## The rule

1. **Read the diff of any bulk `--fix`.** "N fixable" is a count, not a
   warrant.
2. **Select rules explicitly** (`--select A,B,C`), never a blanket
   `--fix`, so rules left open on purpose stay untouched.
3. **Re-measure every rule already at zero afterwards.** A fix for one
   rule regresses another; that is how both defects above arrived.
4. **Widen the ratchet as classes reach zero.** Two rules added here
   found four regressions that a green suite missed.
5. A finding whose fix needs a *judgement per instance* (`F841`,
   `E402`) is not mechanical work. Read it, or leave it and state why.

## Related

- [`clean-break-config-moves-need-a-file-scan.md`](clean-break-config-moves-need-a-file-scan.md)
  — same species: a change invisible to every accessor, needing a check
  that reads the artifact rather than the code path.
- [`absence-is-invisible-in-listings.md`](absence-is-invisible-in-listings.md)
  — a quiet answer indistinguishable from a good one.

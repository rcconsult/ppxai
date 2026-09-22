# A measurement on a dirty tree is not a measurement of the commit you cite

**TL;DR:** A measurement taken against a tree with uncommitted changes
describes the code that is actually on disk, not the code any commit
contains. Stamp a sha next to that number anyway and it becomes a
confident wrong number about that sha.

**Verify with:**
```bash
git status --short
```
Run this before trusting any "measured on this tree" claim that also cites
a commit hash. Any output at all — staged, unstaged, or untracked — means
the tree you measured and the commit you're about to name are two
different things. `git diff --stat` producing any lines is the same
signal: a non-empty diff already means tree ≠ HEAD.

## Why this trips people up

Mid-session, HEAD hasn't moved — you haven't committed, so the sha in
`git log -1` looks like it's still describing "the code I'm looking at."
It feels like the number is tied to HEAD because nothing *reset* it. But a
working tree with edits, a stray new file, or a half-applied patch is not
HEAD's content; it's HEAD's content plus whatever's uncommitted. A lint
count, a test-pass count, a LoC count, a god-class edge count — all of
them silently include the uncommitted delta, and nothing about running the
tool warns you it did.

## What's actually true

To pin a number to a specific commit, export that commit clean first and
measure the export, not the working tree:

```bash
git archive <sha> | tar -x -C <tmp-dir>
# or: a throwaway worktree
git worktree add <tmp-dir> <sha>
```

Then run the measurement inside `<tmp-dir>`. Whatever the tool reports now
is actually about `<sha>` — nothing else could have leaked in, because
nothing else is on disk there.

This also gives a diagnostic move for a specific kind of disagreement:
when your number contradicts a peer's account of their own code, check the
instrument — *which tree did I actually measure?* — before concluding
their account is wrong. A dirty-tree measurement that disagrees with a
clean report about the same sha is evidence about your working tree, not
evidence against their claim.

## Related

- [mutation-tests-that-never-ran.md](mutation-tests-that-never-ran.md) —
  the same `git archive <sha> | tar -x` extract, used there to prove a
  mutated line is unreachable rather than to pin a measurement to a commit;
  same underlying tool, different question it answers.
- Lesson promotion criteria: [README.md](README.md).

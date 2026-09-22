# A doc comment promising a mechanism is not the mechanism

**TL;DR:** `vscode-extension/src/appState.ts`'s header claimed the interface
was "checked at runtime by a constructor assertion" and promised "the
v1.18.x schema generator will auto-generate `AppStateFields`". Neither
existed — the constructor only did an `as AppStateFields` cast — and no
test compared the interface to the schema, so the hand-written interface
sat **two fields behind** the schema for four minor versions: the schema
had 22 fields, the interface 20. `lastMessageRole` (added v1.18.0) and
`modelSupportsVision` (added v1.18.6) were missing from the interface the
whole time, while web had gated its attach badge on `modelSupportsVision`
since v1.18.6.

**Verify with:** the file is gone now (deleted in the fix below), so point
at history:
```bash
git log -S "will auto-generate" --oneline -- vscode-extension/src/appState.ts
# -> 1953c29c, f351f43f

git show 1953c29c^:vscode-extension/src/appState.ts | sed -n '1,40p'
# header: "checked at runtime by a constructor assertion" /
# "will auto-generate AppStateFields"

git show 1953c29c^:vscode-extension/src/appState.ts | grep -n "as AppStateFields"
# -> line 243: this._data = { ...defaults, ...initial } as AppStateFields;
# a cast, not an assertion — nothing runs at runtime to check the claim
```
The fix commit's own message states the drift plainly:
```bash
git log -1 --format=%B 1953c29c
```

## Why this trips people up

A comment describing a safeguard reads like evidence the safeguard exists
— especially in confident future tense ("the schema generator *will*
auto-generate..."). It sits right next to the code it describes, formatted
like documentation, so it inherits the authority of the code around it.
Nothing runs it, though: a doc comment is not compiled, tested, or linted
against the claim it makes. Nothing in the suite ever compared
`AppStateFields`'s field list to `ppxai/engine/app_state_schema.json`'s, so
the drift had no way to surface — the interface could fall behind
silently and stay green forever.

## What's actually true / what to do

Treat a comment asserting a cross-file invariant ("X is checked against
Y", "Z is generated from W") as a claim to verify, not a fact to repeat.
Find the actual check or the actual generator — or its absence — before
citing the claim anywhere else, including in your own turn summary.

The closure here: `vscode-extension/scripts/sync-schema.js` now really
does generate `src/appState.generated.ts` from the JSON schema (commit
`1953c29c`), and `tests/test_app_state_generated_types.py` fences it — the
hand-written interface and its stale comment are deleted outright, not
patched.

## Related

- `docs/decisions/0007-completion-first-class-service.md` §"CORRECTION OF
  THE CORRECTION" — a separate instance of the same trap: a design record
  overstated what a hand-written AppState mirror costs to maintain, was
  corrected once, and the correction itself needed a second, later
  correction the same day.
- Lesson promotion criteria: [README.md](README.md).

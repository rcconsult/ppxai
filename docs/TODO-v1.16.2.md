# TODO: v1.16.2 Bugfix Branch

**Branch:** bugfix/1.16.2
**Base:** v1.16.1

---

## Bug 1 — Web App: Side Panel Saves File to Wrong Path

### Symptom

When the AI opens a file (e.g. `outlook_agent/main.py`) in the web app's side panel editor
via `display_file`, and the user edits and saves it, the file is written to the **working
directory root** as `main.py` instead of `outlook_agent/main.py`.

Observed in server log:
```
01:41:34  display_file → filepath: /ppxai-sre-repo/outlook_agent/main.py   (correct)
01:42:03  POST /files/read  path: outlook_agent/main.py                     (correct)
01:42:56  POST /files/write path: main.py → /ppxai-sre-repo/main.py        (WRONG)
```

### Root Cause

**Two-part bug:**

1. **`ppxai/server/http.py` — `/files/read` returns `path.name` (basename only):**
   ```python
   # Lines 2133, 2148 — both text and binary responses:
   "filename": path.name,   # ← "main.py" not "outlook_agent/main.py"
   ```
   The server should return the **relative path from the working directory**, not just the
   filename basename.

2. **`~/.ppxai/web/app.js` — editor uses `data.filename` for save path:**
   ```javascript
   // Line 2802 — handleEditCommand():
   this.showEditorPanel(data.filename || filepath, data.content, line, col);
   //                   ↑ picks up "main.py" stripping the directory

   // Line 3052 — saveEditor():
   body: JSON.stringify({ path: this.editorFilename, content })
   //                           ↑ sends "main.py" → writes to root
   ```
   The web app prefers `data.filename` over the original `filepath` that was requested.
   Since `data.filename` is just the basename, the directory is lost.

### Fix

**`ppxai/server/http.py`** — return relative path instead of basename:

```python
# In /files/read endpoint, compute relative path from working_dir:
working_dir = Path(engine.get_working_dir())
try:
    rel_path = str(path.relative_to(working_dir))
except ValueError:
    rel_path = path.name  # fallback if outside working dir

return {
    "filename": rel_path,   # "outlook_agent/main.py" not "main.py"
    "path": str(path),
    ...
}
```

Apply to both text (line ~2148) and binary (line ~2133) response branches.

**`~/.ppxai/web/app.js`** — prefer `filepath` (the requested path) over `data.filename`
for the editor, or use `data.path` (the absolute path) to derive the save path. The
simplest fix is to not override with `data.filename` when opening for editing:

```javascript
// Line 2802 — prefer the requested filepath, fall back to data.filename:
this.showEditorPanel(filepath || data.filename, data.content, line, col);
```

This ensures the directory prefix from the original `/edit` or `display_file` request
is preserved in `editorFilename`.

### Tests to Add

- `tests/test_files_endpoint.py` — `/files/read` on `subdir/file.py` returns
  `filename: "subdir/file.py"`, not `"file.py"`
- Web app integration check: save after display_file writes to correct relative path

---

## Bug 2 — Validator False Positive: `claim_without_action` on Acknowledgement

### Symptom

The validator fires a `claim_without_action` warning when the model acknowledges a mistake
rather than claiming it completed a file modification:

```
SSE: warning - claim_without_action ... "Model claims to have modified 'o..."
```

Triggered by the model saying:
> "You are absolutely right. My apologies. I missed the `uv.lock` file... Let's correct that."

The phrase "Let's correct that" (or similar) matched the success-claim heuristic even
though no file was actually claimed to have been modified.

### Root Cause

`_claims_success()` in `ppxai/engine/tools/validator.py` uses a keyword-set + proximity
window approach. The word "correct" is likely matching a SUCCESS_VERB or CLAIM_SIGNAL
in proximity to a filename-like token.

Inspect: does `"correct"` appear in `SUCCESS_VERBS` or `CLAIM_SIGNALS`? Also check
whether the 60-char proximity window is too wide, catching adjacent sentences.

### Fix

- Remove `"correct"` / `"corrected"` from SUCCESS_VERBS if present (it's ambiguous —
  "I corrected the issue" vs "Let's correct that")
- Add negation/apology prefix guard: if response contains "apologies", "my bad",
  "you are right", "I missed" within N chars of the claim signal, suppress the warning
- Tighten proximity window or add sentence-boundary detection so cross-sentence matches
  don't fire

### Tests to Add

- `tests/test_validator.py` — acknowledgement/apology sentences should NOT trigger
  `claim_without_action`:
  - `"You are right, I missed the uv.lock file. Let's correct that."`
  - `"My apologies, I should have noticed the pyproject.toml. Let me fix the approach."`
  - `"I was wrong about the path. Let's start over."`

---

## Status

| # | Bug | Status |
|---|-----|--------|
| 1 | Web app saves to wrong path (`path.name` vs relative path) | ✅ Fixed |
| 2 | Validator false positive on apology/acknowledgement | ✅ Fixed |

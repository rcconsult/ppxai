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

---

## Feature 3 — Web App: Collapsible File Tree Sidebar

### Summary

VSCode-style collapsible sidebar for the web app that lets users browse the working directory
without leaving the chat. Click a file to preview/edit it in the side panel; right-click to
inject `@file:path` into the chat input.

### Implementation

**New files:**
- `ppxai/web/components/file-tree.js` — `FileTreeComponent` class
  - Lazy-loads directory contents via `GET /files/list`
  - Expand/collapse directories; persists state to `localStorage`
  - Left-click file → `displayFileFromEvent(relPath)` (preview panel)
  - Right-click file → `_injectFileRef(relPath)` (injects `@file:path` at cursor)
  - Refresh button reloads current tree
- `ppxai/web/styles/file-tree.css` — sidebar layout and tree node styles

**Modified files:**
- `ppxai/web/index.html` — sidebar toggle button `🗂` in header-left; `<div id="fileSidebar">`
  and `<div id="sidebarResizeHandle">` in main-content; `<link>` + `<script>` tags
- `ppxai/web/app.js` — `toggleFileSidebar()`, `_injectFileRef()`, `initSidebarResizeHandle()`;
  sidebar elements in `this.elements`; auto-refresh on `working_dir_changed` event

### Usage

- Click `🗂` in the header to open/close the file tree
- Resize by dragging the right edge of the sidebar
- Left-click a file: opens in the side preview/edit panel
- Right-click a file: injects `@file:path` at the cursor in the chat input

---

---

## Bug 4 — TUI: Redundant `set_model` Calls on `/provider` Switch

### Symptom

Observed in TUI debug log: switching provider via `/provider gemini` logs model hint matching
**4 times in a row** for the same model:

```
02:00:29.560  Model switch to 'gemini-2.5-flash': 14 model hints (matched: ['gemini-2.5-flash*'])
02:00:29.561  Provider switch to 'gemini': 21 provider hints, 14 model hints
02:00:29.584  Model switch to 'gemini-2.5-flash': 14 model hints (matched: ['gemini-2.5-flash*'])
02:00:29.585  Provider switch to 'gemini': 21 provider hints, 14 model hints
02:00:29.585  Model switch to 'gemini-2.5-flash': 14 model hints (matched: ['gemini-2.5-flash*'])
02:00:29.585  Model switch to 'gemini-2.5-flash': 14 model hints (matched: ['gemini-2.5-flash*'])
```

Reproduced across two separate sessions at 02:00 and 02:09.

### Root Cause (suspected)

The provider-switch call path invokes `set_model` from multiple places simultaneously:
1. Command handler (`handle_provider`) calls `set_model` directly
2. `restore_session()` / `reload_config()` triggers a secondary model resolution
3. Badge update / event callback in the TUI triggers another `set_model`

This means the same model hint matching runs 3–4× per single `/provider` switch.

### Impact

- Wasteful CPU: hint matching runs multiple times unnecessarily
- Potential badge flicker in the TUI if intermediate states are visible
- Risk of race condition if one of the redundant calls resolves to a different model

### Fix

- Trace the full call stack for a `/provider` switch and identify all `set_model` call sites
- Add deduplication: if provider+model haven't changed, skip `set_model`
- Or: gate `set_model` with a `_setting_model` lock so re-entrant calls are no-ops

### Tests Added

- `tests/test_commands.py` — `TestHandleProviderCallCount`:
  - `/provider X` results in exactly one `context.set_model` call
  - `engine_client.set_model` is NOT called directly from the handler (prevents regression)
  - Same-provider switch is a no-op (no `set_provider`/`set_model` calls)

---

---

## Web App Refactor (Items 5–10)

`app.js` is a 4,264-line god class with ~50 methods, ~25 instance vars, and no separation of
concerns. Items 5–7 will cut it roughly in half and fix the most fragile parts. Items 8–10
are lower-urgency polish. All changes are internal refactors — no user-visible behaviour
changes unless noted.

### Item 5 — Route All Fetches Through `api-client.js`

`app.js` calls `fetch()` directly ~20 times, each hand-rolling the same pattern:

```javascript
const resp = await fetch(`${this.serverUrl}/endpoint`, { headers: this.getSessionHeaders() });
const data = await resp.json();
```

`shared/api-client.js` already defines most endpoints but is bypassed. This means no timeouts
on direct calls, duplicated error handling at every call site, and `escapeHtml()` defined in
three separate files (formatters.js, app.js, table-viewer.js).

**Fix:**
1. Audit every `fetch(` in `app.js` — add missing methods to `ApiClient`
2. Add a `_fetch(endpoint, options)` base method with `AbortSignal.timeout(10000)` default
   and a standard error shape `{ ok, data, error, status }`
3. Replace inline fetches with `this.apiClient.methodName(args)` throughout app.js
4. Consolidate `escapeHtml()` to `formatters.js` only

- **Files:** `shared/api-client.js`, `app.js`
- **Risk:** low — mechanical substitution, no logic change
- **Lines saved:** ~180

### Item 6 — Extract `CommandDispatcher`

The slash command handler is a ~1,700-line switch (lines 1080–2777), each case duplicating
fetch, error handling, and response rendering.

**Fix:** Create `shared/command-dispatcher.js` with a `register(name, handler)` / `dispatch(command, args)` pattern. Split handlers into command-group modules under `shared/commands/`:

```
shared/commands/
  file-commands.js     (/show, /edit, /ls, /tree, /cd, /pwd, /preview)
  session-commands.js  (/save, /load, /sessions, /clear, /export)
  model-commands.js    (/provider, /model, /tools, /agent)
  context-commands.js  (/context, /inject, /config)
  help-commands.js     (/help, /status, /usage, /debug)
  ai-commands.js       (/generate, /explain, /test, /docs, /implement)
```

- **Files:** new `shared/command-dispatcher.js` + `shared/commands/*.js`; modified `app.js`
- **Risk:** medium — logic moved, each command needs manual verification
- **Lines saved:** ~1,400–1,600

### Item 7 — Extract `StreamHandler`

The SSE streaming logic (lines 807–1062) mixes HTTP fetch, manual line-buffer management,
24-event dispatch, render throttle, and DOM mutations in one function.

The buffer split is fragile:
```javascript
buffer += decoder.decode(value, { stream: true });
const lines = buffer.split('\n');
buffer = lines.pop() || '';
```
Silently corrupts events if a JSON payload spans two TCP chunks. The render throttle
(`fullContent.length % 50 === 0`) re-runs the full `marked.js` parse each time with no
`requestAnimationFrame`.

**Fix:** Create `shared/stream-handler.js` extending `EventTarget`. Proper buffer flush,
abort/timeout support, and `requestAnimationFrame`-gated rendering. `app.js` subscribes
to typed events (`stream_chunk`, `tool_call`, etc.) instead of a switch.

- **Files:** new `shared/stream-handler.js`; modified `app.js`
- **Risk:** medium-high — core path, all 24 event types must be verified
- **Lines saved:** ~250

### Item 8 — Extract `EditorController`

CodeMirror 6 lifecycle (~350 lines, 2835–3200) is self-contained: init, language detection,
save prompt, Ctrl+S, destroy. No dependencies on chat logic.

**Fix:** Create `components/editor-controller.js` with `open(filename, content)`,
`getContent()`, `hasUnsavedChanges()`, `destroy()`. Wire save/close via constructor callbacks.

- **Files:** new `components/editor-controller.js`; modified `app.js`, `index.html`
- **Risk:** low — well-isolated
- **Lines saved:** ~300–350

### Item 9 — Centralize State (`AppState`)

~25 instance vars mutated directly across 50+ methods with no traceability. No way to know
what triggered a state change or protect against stale reads.

**Fix:** Thin `AppState` class in `shared/app-state.js`:

```javascript
class AppState {
    get(key) { return this._state[key]; }
    set(key, value) {
        if (this._state[key] === value) return;  // no-op if unchanged → fixes Bug 4
        this._state[key] = value;
        this._listeners[key]?.forEach(fn => fn(value));
    }
    on(key, fn) { (this._listeners[key] ??= []).push(fn); }
}
```

The `set()` no-op on unchanged values directly fixes the redundant `set_model` calls (Bug 4).

- **Files:** new `shared/app-state.js`; modified `app.js`
- **Risk:** medium — touches many locations, each change trivial

### Item 10 — Virtual Scroll for Messages

All messages stay in the DOM indefinitely. Degradation begins around 150–200 messages.

**Fix:** Buffer-based virtual scroller — keep last 60 messages rendered, prepend height
sentinel for older ones. Alternatively, add `/clear keep:20` as a lighter option.

- **Risk:** high — scroll position management is tricky
- **Priority:** low — only if long sessions become a common complaint

---

### Sequencing

| Order | Item | Risk | Lines saved |
|-------|------|------|------------:|
| 1st | Route fetches through api-client (#5) | Low | ~180 |
| 2nd | Extract EditorController (#8) | Low | ~340 |
| 3rd | Extract StreamHandler (#7) | Medium-high | ~250 |
| 4th | Extract CommandDispatcher (#6) | Medium | ~1,500 |
| 5th | Centralize AppState (#9) | Medium | — |
| 6th | Virtual scroll (#10) | High | — |

After items 5–8: `app.js` drops from ~4,264 to ~1,800 lines.

---

## Status

| # | Item | Status |
|---|------|--------|
| 1 | Web app saves to wrong path (`path.name` vs relative path) | ✅ Fixed |
| 2 | Validator false positive on apology/acknowledgement | ✅ Fixed |
| 3 | Web app file tree sidebar | ✅ Done |
| 4 | Redundant `set_model` calls on `/provider` switch | ✅ Fixed |
| 5 | Route fetches through `api-client.js` | ✅ Done |
| 6 | Extract `CommandDispatcher` | ✅ Done |
| 7 | Extract `StreamHandler` | ✅ Done |
| 8 | Extract `EditorController` | ✅ Done |
| 9 | Centralize state (`AppState`) | 🔲 Open |
| 10 | Virtual scroll for messages | 🔲 Open |

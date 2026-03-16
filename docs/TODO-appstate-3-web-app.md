# TODO: AppState Phase 3 — Desktop Web App

**Status:** Open
**Priority:** HIGH — proves cross-language schema parity (Python → JS)
**Depends on:** Phase 2 (Textual TUI — thread-safety proven)
**Target:** v1.17.2

---

## Why Third

The desktop web app proves the schema generates correct JS code with field parity
to the Python implementation. It already has a hand-written `AppState` class
(`ppxai/web/shared/app-state.js`) — this phase replaces it with the generated version.

Key advantages for testing:
- **200 Playwright e2e tests** — comprehensive regression safety net
- **Existing `AppState` pattern** — the web app already uses `state.on()` observers,
  so this is a drop-in replacement, not a pattern change
- **Same app as k8s** — proving it here means Phase 4 (k8s) is just config injection

## Current State

| File | Lines | Role |
|------|------:|------|
| `ppxai/web/shared/app-state.js` | 79 | Hand-written AppState (Proxy-based, observers) |
| `ppxai/web/app.js` | 2,363 | Main app — `this.state = new AppState({...})` with 30+ fields |

### Current AppState Fields (app.js lines 66–123)

```javascript
// Already using AppState — fields declared in constructor:
currentProvider, currentModel, toolsEnabled, agentMode, theme,
isStreaming, isSending, isHandlingCommand, currentAbortController,
currentAssistantMessage, commandHistory, historyIndex, debugLogEnabled,
verbose, lastCheckpoint, checkpointCount, usage, previewViewMode,
previewContent, previewFilename, previewDataFormat, autocompleteVisible,
autocompleteItems, autocompleteIndex, autocompleteType, htmlPreviewActive,
htmlPreviewFilepath, rpfStackSize, rpfDedup, rpfPersist, rpfStackDepth,
rpfActiveTitle, rpfActiveDirty
```

### Which Fields Move to Schema vs Stay Widget-Local

**Schema fields** (app-level state, shared with Python):
`currentProvider`, `currentModel`, `toolsEnabled`, `agentMode`, `isStreaming`,
`cancelRequested`, `autoInject`, `bootstrapLoaded`, `lastCheckpoint`,
`checkpointCount`, `usagePromptTokens`, `usageCompletionTokens`, `usageCost`,
`debugLogEnabled`, `workingDir`, `sessionName`, `messageCount`, `toolsVerbose`

**Widget-local fields** (stay on the web app, not in schema):
`theme`, `isSending`, `isHandlingCommand`, `currentAbortController`,
`currentAssistantMessage`, `commandHistory`, `historyIndex`, `verbose`,
`previewViewMode`, `previewContent`, `previewFilename`, `previewDataFormat`,
`autocompleteVisible`, `autocompleteItems`, `autocompleteIndex`, `autocompleteType`,
`htmlPreviewActive`, `htmlPreviewFilepath`, `rpfStackSize`, `rpfDedup`, `rpfPersist`,
`rpfStackDepth`, `rpfActiveTitle`, `rpfActiveDirty`

**Decision:** The web app keeps its `AppState` instance with ALL fields (schema + local).
The generated `AppState` class provides the core implementation. Widget-local fields
are added at construction time by the web app — they're just extra keys in the same
store. The schema doesn't need to know about them.

## Implementation Steps

### Step 1: Replace hand-written AppState with generated version

**Files:** `ppxai/web/shared/app-state.js`

- Run `scripts/generate-state.py` to produce new `app-state.js`
- Generated version must preserve the existing public interface:
  `state.get()`, `state.set()`, `state.on()`, `state.snapshot()`, plus
  Proxy shorthand `state.currentProvider`
- Verify the Proxy traps, no-op dedup, and observer dispatch work identically

### Step 2: Update web app constructor

**Files:** `ppxai/web/app.js`

- Schema fields come from the generated `AppState` defaults
- Widget-local fields are added in the constructor:
  ```javascript
  this.state = new AppState();  // Core schema fields with defaults
  // Add widget-local fields
  this.state.set('theme', localStorage.getItem('ppxai-theme') || 'dark');
  this.state.set('commandHistory', JSON.parse(localStorage.getItem('ppxai-history') || '[]'));
  // ... etc
  ```
- Or: pass additional fields to constructor:
  ```javascript
  this.state = new AppState({
      theme: localStorage.getItem('ppxai-theme') || 'dark',
      commandHistory: JSON.parse(localStorage.getItem('ppxai-history') || '[]'),
      // ... widget-local fields
  });
  ```

### Step 3: Enforce public interface

- Grep for direct `state._data` access — replace with `state.get()`/`state.set()`
- Grep for `this.state.someField =` — verify it goes through Proxy set trap
  (it should already, but confirm)

### Step 4: Run Playwright e2e tests

```bash
cd tests/e2e && npx playwright test
```

All 200 tests must pass. These cover:
- Provider/model switching
- Chat streaming
- Tool calling + consent dialogs
- Session save/load/restore
- File tree, preview, editor
- Checkpoints
- Status bar updates

### Step 5: Verify runtime schema loading (prep for Phase 4)

- Test `state.loadRuntime('ppxai-runtime-k8s')` with mock k8s settings
- Verify fields are accessible via `state.get("sessionIsolation")`
- Verify unknown runtime name fails gracefully

## Acceptance Criteria

- [ ] Generated `app-state.js` replaces hand-written version
- [ ] All 200 Playwright e2e tests pass
- [ ] No direct `_data` access anywhere in `app.js` or component files
- [ ] Widget-local fields work alongside schema fields in the same store
- [ ] `loadRuntime()` works for k8s settings injection
- [ ] `SCHEMA_VERSION` matches Python version

## What NOT to Do

- Don't change web app behavior — this is a drop-in replacement
- Don't restructure `app.js` further — v1.16.2 refactoring already extracted components
- Don't move widget-local fields to the schema — they're UI-specific, not app state

## Estimated Effort

~3 hours (generator already done in Phase 0, mostly verification)

## Lessons Learned

*(To be filled during/after implementation)*

### From Phase 1 (Rich TUI)
*(Copy relevant lessons)*

### From Phase 2 (Textual TUI)
*(Copy relevant lessons)*

### Cross-Language Parity Issues
- ...

### Proxy/Property Shorthand Differences
- ...

### What to Do Differently Next Time
- ...

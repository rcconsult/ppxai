# TODO: AppState Phase 2 — Textual TUI (ppxaide)

**Status:** Open
**Priority:** HIGH — proves thread-safety and async listener dispatch
**Depends on:** Phase 1 (Rich TUI — AppState on EngineClient proven)
**Target:** v1.17.1

---

## Why Second

The Textual TUI (`ppxaide` command) adds the concurrency complexity that Rich didn't:
- **Worker threads** — engine chat runs in async workers, UI updates on main thread
- **EventBus** — blinker-based pub/sub (`ppxai/tui/event_bus.py`)
- **`call_from_thread()`** — Textual's cross-thread UI update mechanism
- **15+ shadow state fields** — `self._provider`, `self._model`, etc. on the app class
- **Manual badge sync** — ~30 scattered `update_badge()` calls

This is where AppState observers prove their value: replacing manual sync with
automatic reactive updates.

## Current State

| File | Lines | State fields |
|------|------:|--------------|
| `ppxai/tui/app.py` | 2,303 | `_provider`, `_model`, `_tools_enabled`, `_is_streaming`, `_cancel_requested`, `_reasoning_started`, `_reasoning_content`, `_tool_group_active`, `_tool_group_tools`, `_tools_verbose`, `_current_message_content`, + 5 more |
| `ppxai/tui/event_bus.py` | 226 | `EventBus` + `Events` constants |
| `ppxai/commands/context.py` | `TextualCommandContext` | 12+ properties delegating to app + engine |

### Shadow State Problem

Every state change requires manual multi-step sync:
```python
# Current: session restore (ppxai/tui/app.py ~line 689)
self._provider = result["provider"]
status_bar.update_badge("provider", self._provider)
self._model = result["model"]
status_bar.update_badge("model", self._model)
self._tools_enabled = result["tools_enabled"]
status_bar.update_badge("tools", "ON" if self._tools_enabled else "OFF")
if self._provider and self._model:
    self.sub_title = f"{self._provider}/{self._model}"
```

With AppState observers (target):
```python
# engine.restore_session() internally calls:
#   state.update(current_provider="openai", current_model="gpt-4", tools_enabled=True)
# Observers fire automatically — no manual sync needed
```

## Implementation Steps

### Step 1: Replace shadow state with AppState observers

**Files:** `ppxai/tui/app.py`

- Remove `self._provider`, `self._model`, `self._tools_enabled`, etc.
- Read from `self._engine_client.state` instead
- Register observers in `on_mount()`:
  ```python
  def _on_state_change(key, update_fn):
      """Thread-safe observer that posts update to Textual event loop."""
      def listener(value):
          self.call_from_thread(update_fn, value)
      self._engine_client.state.on(key, listener)

  _on_state_change("current_provider", lambda v: status_bar.update_badge("provider", v))
  _on_state_change("current_model", lambda v: status_bar.update_badge("model", v))
  _on_state_change("tools_enabled", lambda v: status_bar.update_badge("tools", "ON" if v else "OFF"))
  _on_state_change("current_provider", lambda _: self._update_subtitle())
  _on_state_change("current_model", lambda _: self._update_subtitle())
  _on_state_change("is_streaming", lambda v: self._update_streaming_ui(v))
  ```
- Remove all manual `update_badge()` calls that are now handled by observers

### Step 2: Simplify TextualCommandContext

**Files:** `ppxai/commands/context.py`

- `TextualCommandContext` properties delegate to `engine.state.get()` instead of
  reading app shadow state
- Remove reference to `app._provider`, `app._model` etc.

### Step 3: Add thread-safety tests

**Files:** `tests/test_app_state.py` (extend from Phase 1)

- `test_concurrent_read_write` — multiple threads writing, main thread reading
- `test_no_torn_reads` — reader never sees partial state from a batch `update()`
- `test_async_listener_dispatch` — async listener scheduled via `create_task()`
- `test_listener_called_outside_lock` — verify no deadlock when listener triggers
  another `set()` call
- `test_off_prevents_stale_calls` — unsubscribed listener not called after `off()`

### Step 4: Verify EventBus + AppState coexistence

The EventBus handles **engine events** (stream chunks, tool calls, consent requests).
AppState handles **state observation** (provider changed, tools toggled).
These are complementary:

- EventBus: `bus.emit(Events.ENGINE_STREAM_CHUNK, data=...)` → handler accumulates text
- AppState: `state.on("is_streaming", fn)` → UI toggles send button

Verify no conflicts, no duplicate handling, clean separation.

### Step 5: Verify Textual TUI behavior

**Tests:**
- Run full test suite
- Run TUI-specific tests (if blinker available)
- Manual smoke test: `uv run ppxaide` → chat, switch provider, load session,
  toggle tools, toggle agent, Ctrl+C cancel, theme switching, file tree, side panel
- Verify all badges update correctly after every state transition
- Verify `call_from_thread()` doesn't race with widget unmounting

## Acceptance Criteria

- [ ] All 15+ `self._*` shadow state fields removed from `PPXAIDEApp`
- [ ] All state reads go through `engine.state.get()` or shorthand
- [ ] All badge updates happen via AppState observers (zero manual `update_badge()`)
- [ ] Thread-safety tests pass (concurrent R/W, no deadlocks)
- [ ] EventBus and AppState coexist cleanly
- [ ] `TextualCommandContext` uses `engine.state` not `app._*`
- [ ] All existing tests pass
- [ ] Manual smoke test passes

## What NOT to Do

- Don't refactor EventBus — it handles a different concern (engine events vs state observation)
- Don't extract theme_manager/key_router yet — that's item 6, depends on this working first
- Don't touch web app or VSCode — those are later phases

## Estimated Effort

~4 hours (builds on Phase 1 patterns)

## Lessons Learned

*(To be filled during/after implementation)*

### From Phase 1 (Rich TUI)
*(Copy relevant lessons from Phase 1 here before starting)*

### Architecture Decisions
- ...

### Threading Pitfalls
- ...

### Patterns That Worked Well
- ...

### What to Do Differently Next Time
- ...

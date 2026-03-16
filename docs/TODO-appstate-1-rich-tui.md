# TODO: AppState Phase 1 — Rich TUI

**Status:** Open
**Priority:** HIGH — simplest client, proves AppState core works
**Depends on:** Phase 0 (schema + generator)
**Target:** v1.17.1

---

## Why First

The Rich TUI (`ppxai` command) is the simplest client:
- Single thread — no `call_from_thread()`, no worker threads
- Sync event handler — no async listener dispatch needed
- No event bus — events flow through `EventHandler` callbacks directly
- Minimal client state — most state lives on `EngineClient`
- Well-tested — `CommandHandler` and `EventHandler` have good test coverage

This makes it the safest place to prove the AppState pattern works before
adding threading and async complexity in Phase 2.

## Current State

| File | Lines | State fields |
|------|------:|--------------|
| `ppxai/rich/main.py` | 803 | Reads from `EngineClient` directly |
| `ppxai/rich/event_handler.py` | ~350 | `_full_response`, `_reasoning_response`, `_should_break` (internal accumulators, NOT app state) |
| `ppxai/rich/ui_components.py` | 871 | Stateless rendering |
| `ppxai/commands/handler.py` | ~500 | Reads/writes via `EngineClient` + `RichCommandContext` adapter |
| `ppxai/commands/context.py` | `RichCommandContext` | 12+ properties delegating to `EngineClient` |

Key observation: Rich TUI has almost no shadow state. It reads directly from
`EngineClient`. The main work is:
1. Wire `EngineClient` to use `AppState` internally
2. Simplify `RichCommandContext` to read from `state`
3. Verify all existing behavior is preserved

## Implementation Steps

### Step 1: Wire EngineClient to AppState

**Files:** `ppxai/engine/client.py`

- Add `self.state = AppState({...})` in `__init__` with all schema fields
- Keep existing properties (`provider_name`, `model`, `tools_enabled`, etc.) as
  thin wrappers that read/write `state`:
  ```python
  @property
  def provider_name(self) -> str:
      return self.state.get("current_provider")

  @property
  def model(self) -> str:
      return self.state.get("current_model")
  ```
- Update `set_provider()`, `set_model()`, `restore_session()` to write via
  `state.set()` / `state.update()`
- All existing tests must pass unchanged — wrappers preserve the public interface

### Step 2: Simplify RichCommandContext

**Files:** `ppxai/commands/context.py`

- `RichCommandContext` properties delegate to `engine.state.get()` instead of
  reading `engine.provider_name` etc. directly
- This is a minor change since the engine wrappers exist, but establishes the
  pattern of reading state through the public interface

### Step 3: Verify Rich TUI behavior

**Tests:**
- Run full test suite (1,318 tests)
- Manual smoke test: `uv run ppxai` → chat, switch provider/model, save/load session,
  enable/disable tools, agent mode, checkpoint undo
- Verify status line shows correct provider/model/tools after every operation

### Step 4: Add AppState unit tests

**Files:** `tests/test_app_state.py` (new)

- `test_get_set_basic` — set a value, read it back
- `test_dedup` — set same value twice, observer fires only once
- `test_observer_on_off` — subscribe, verify callback, unsubscribe, verify no callback
- `test_update_batch` — update multiple fields, each observer fires
- `test_snapshot` — snapshot returns correct dict copy
- `test_property_shorthand` — `state.current_provider` works like `state.get("current_provider")`
- `test_load_runtime` — runtime fields accessible after `loadRuntime()`

Thread-safety and async tests are NOT needed in this phase (Rich TUI is single-threaded).
They will be added in Phase 2 (Textual TUI).

## Acceptance Criteria

- [ ] `EngineClient` uses `AppState` internally for all state fields
- [ ] Existing properties (`provider_name`, `model`, etc.) work unchanged
- [ ] `RichCommandContext` reads from `engine.state`
- [ ] All 1,318 existing tests pass
- [ ] New `test_app_state.py` tests pass
- [ ] Manual smoke test: Rich TUI behaves identically to before
- [ ] No lazy imports, no circular dependencies

## What NOT to Do

- Don't add threading/async complexity — save for Phase 2
- Don't change the EventHandler — its internal accumulators are NOT app state
- Don't touch Textual TUI, web app, or VSCode — those are later phases
- Don't remove EngineClient wrapper properties yet — backward compat for other clients

## Estimated Effort

~4 hours

## Lessons Learned

*(To be filled during/after implementation — these carry forward to Phase 2)*

### Architecture Decisions
- ...

### Pitfalls Encountered
- ...

### Patterns That Worked Well
- ...

### What to Do Differently Next Time
- ...

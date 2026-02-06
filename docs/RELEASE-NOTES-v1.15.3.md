# Release Notes: v1.15.3

**Release Date:** 2026-02-07
**Branch:** bugfix/v1.15.3
**Focus:** TUI EventBus Stability, Error Handling Improvements

---

## Overview

v1.15.3 is a stability-focused release that completes the v1.15.2 response validation system integration with the TUI, adds resilience guards to EventBus handlers, and reduces debug log noise. This release fixes several edge-case crashes and improves the overall robustness of the ppxaide TUI.

---

## Critical Fixes

### 1. WARNING Event Handler for Hallucination Detection

**Problem:**
- v1.15.2 introduced `EventType.WARNING` for hallucination detection but TUI had no handler
- Led to "Unhandled event type: EventType.WARNING" debug messages
- Validation warnings from ResponseValidator were logged but not displayed to users

**Solution:**
- Added `ENGINE_WARNING` constant to `Events` class (`ppxai/tui/event_bus.py`)
- Added `WARNING` mapping to event_map in `ppxai/tui/app.py`
- Implemented `_on_engine_warning()` handler that displays warnings with yellow ⚠ indicator
- Subscribed to ENGINE_WARNING event in on_mount

**Implementation:**
```python
async def _on_engine_warning(self, sender, data, **kwargs) -> None:
    """Handle ENGINE_WARNING event (hallucination detection, v1.15.3)."""
    try:
        chat_view = self.query_one("#chat-view", ChatView)
    except NoMatches:
        self._log.warning(f"[Event] Engine warning (chat view not mounted): {data}")
        return

    if data and isinstance(data, str):
        self._log.warning(f"[Event] Engine warning: {data}")
        chat_view.add_system_message(f"[yellow]⚠ Warning:[/yellow] {data}")
```

**Files Updated:**
- `ppxai/tui/event_bus.py` - Added ENGINE_WARNING constant
- `ppxai/tui/app.py` - Added event mapping, subscription, and handler

**Impact:**
- Completes v1.15.2 response validation system
- Users now see hallucination warnings in real-time
- Critical for debugging model behavior issues

---

### 2. EventBus Handler Resilience (NoMatches Guards)

**Problem:**
- EventBus handlers crashed when firing before chat_view was mounted
- "No nodes match '#chat-view' on Screen(id='_default')" errors during:
  - App startup
  - Session restoration
  - Rapid tool execution
- Unhandled exceptions in event handlers broke the event system

**Solution:**
- Imported `NoMatches` from `textual.css.query`
- Added try/except guards to all critical EventBus handlers:
  - `_on_tool_call`
  - `_on_tool_result`
  - `_on_tool_error`
  - `_on_engine_error`
  - `_on_engine_warning`
  - `_on_engine_info`

**Pattern:**
```python
async def _on_tool_result(self, sender, data, **kwargs) -> None:
    """Handle TOOL_RESULT event."""
    try:
        chat_view = self.query_one("#chat-view", ChatView)
    except NoMatches:
        self._log.warning("[Event] Chat view not mounted, skipping tool result display")
        return
    # ... rest of handler
```

**Files Updated:**
- `ppxai/tui/app.py` - Added NoMatches import and guards to 6 handlers

**Impact:**
- Prevents crashes during app lifecycle transitions
- Graceful degradation when UI not ready
- Follows Pattern #6 from MEMORY.md (Textual Widget Query Errors)

---

### 3. Shell Consent Dialog Threading Verification

**Background:**
- Logs showed "push_screen must be run from a worker when wait_for_dismiss is True" error

**Investigation:**
- Audited shell consent dialog implementation
- Verified correct use of `call_from_thread()` + callback pattern
- Confirmed NO usage of `wait_for_dismiss` parameter

**Current Implementation (CORRECT):**
```python
def show_dialog_in_main_thread():
    dialog = ConsentDialog(title=title, message=message, question=question)
    self.push_screen(dialog, on_dialog_dismiss)  # ✅ callback, not wait_for_dismiss

self.call_from_thread(show_dialog_in_main_thread)  # ✅ thread-safe
consent_event.wait()  # ✅ blocks worker thread, not main thread
```

**Conclusion:**
- Error was from older code version (already fixed)
- Current implementation follows Textual best practices
- No action required

**Files Audited:**
- `ppxai/tui/app.py` - `_shell_consent_handler()`, `_show_consent_dialog()`

---

## Performance & Usability Improvements

### 4. Reduced Model Hints Debug Noise

**Problem:**
- "no model hints matched (available patterns: [...])" logged repeatedly during:
  - Session restoration
  - Model switching
  - Provider initialization
- Cluttered logs with non-actionable information

**Solution:**
- Removed verbose logging when no hints matched
- Only log when hints ARE matched (informative case)
- Users can still see available patterns via `/context show` command

**Files Updated:**
- `ppxai/engine/client.py` - Simplified model hint logging logic

**Impact:**
- Cleaner debug logs
- Easier to spot actual issues
- Reduced log file size

---

### 5. Working Directory Change Deduplication

**Problem:**
- Two `WORKING_DIR_CHANGED` events per tool call:
  - Event #1: Tool changes to temp directory
  - Event #2: Tool restores original directory
- Caused unnecessary UI updates and bootstrap context reloads

**Solution:**
- Compare resolved paths before emitting event
- Only emit when directory actually changes from user's perspective
- Skip temporary directory switches

**Implementation:**
```python
def set_working_dir(self, path: str):
    # Check if directory actually changed (v1.15.3)
    current_dir = self.get_working_dir()
    if current_dir and Path(current_dir).resolve() == Path(path).resolve():
        logger.debug(f"Working directory unchanged: {path}")
        return
    # ... emit event and update state
```

**Files Updated:**
- `ppxai/engine/client.py` - Added deduplication logic to `set_working_dir()`

**Impact:**
- Fewer UI updates during tool execution
- Reduced bootstrap context reloads
- Smoother user experience

---

## Documentation Updates

### MEMORY.md

Added v1.15.3 critical patterns:

**Pattern #8: TUI EventBus Handler Resilience**
- All EventBus handlers MUST guard against widget queries before mount
- Use `try/except NoMatches:` for all `query_one()` calls
- Prevents "No nodes match" crashes during app lifecycle

**Pattern #9: WARNING Event Handling**
- Subscribe to ENGINE_WARNING for hallucination detection
- Handler displays validation warnings with yellow ⚠ indicator
- Completes v1.15.2 response validation system

**Pattern #10: Working Directory Change Deduplication**
- Only emit WORKING_DIR_CHANGED when directory actually changes
- Compare resolved paths to handle absolute/relative paths
- Prevents duplicate events from temporary cwd switches

---

## Files Modified

### ppxai/tui/
- `event_bus.py` - Added ENGINE_WARNING constant
- `app.py` - Added WARNING handler, NoMatches guards to 6 event handlers

### ppxai/engine/
- `client.py` - Added cwd change deduplication, reduced model hints logging

### Documentation
- `CHANGELOG.md` - v1.15.3 entry
- `docs/RELEASE-NOTES-v1.15.3.md` - This file
- `~/.claude/projects/.../memory/MEMORY.md` - Added patterns #8-10

---

## Testing & Validation

**Manual Testing:**
1. ✅ WARNING events display in TUI with yellow indicator
2. ✅ No NoMatches crashes during startup/shutdown
3. ✅ Shell consent dialog works correctly
4. ✅ Model hints only log on match
5. ✅ No duplicate WORKING_DIR_CHANGED events

**Automated Testing:**
- All existing tests pass
- No new test failures introduced

---

## Upgrade Notes

**From v1.15.2 → v1.15.3:**
- No breaking changes
- No configuration changes required
- Drop-in replacement for v1.15.2

**Benefits:**
- More stable TUI (no EventBus crashes)
- Cleaner debug logs
- Hallucination warnings now visible in TUI

---

## Known Issues

None specific to v1.15.3.

---

## Next Steps (v1.16.x)

Future improvements identified during v1.15.3 development:

1. **Apply Patch Tool Call Format** - Handle nested argument structures
2. **Transactional State Management** - Apply checkpoint/commit/rollback pattern to provider/model switching
3. **Enhanced Test Coverage** - Integration tests for EventBus handlers

See `ROADMAP.md` for full feature planning.

---

## Credits

- **TUI Stability** - EventBus handler guards, WARNING event handler
- **Performance** - Model hints logging, cwd change deduplication
- **Documentation** - MEMORY.md patterns, release notes

---

**Release Tag:** v1.15.3
**Commit:** [Will be set during release]
**Download:** https://github.com/rcconsult/ppxai/releases/tag/v1.15.3

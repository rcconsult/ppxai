# TODO: v1.15.1 Bug Fixes

**Created:** 2026-01-28
**Branch:** feature/1-15-1
**Status:** In Progress
**Previous Release:** v1.15.0

---

## Issues to Address

### 1. ppxaide TUI - Blocked Event Loop During Streaming

**Source:** User testing
**Severity:** High - UI freezes during long provider responses
**Status:** ✅ **FIXED** (v1.15.1)

**Problem:**
The `async for` loop in `_stream_response()` blocks Textual's event loop while waiting for HTTP responses from AI providers (30+ second waits). During this time:
- Screen appears frozen
- Scroll events not processed
- Status bar updates don't render

**Root Cause:**
Engine client's HTTP streaming doesn't properly yield to event loop during network waits, even though marked as async.

**Attempted Fixes:**
- ❌ `asyncio.create_task()` - still blocks in same event loop
- ❌ `loop.run_in_executor()` - can't update Textual widgets from thread
- ❌ Explicit `asyncio.sleep(0)` - HTTP client doesn't yield between calls
- ❌ Custom `queue.Queue` + `set_interval()` consumer - over-engineered

**Final Solution (v1.15.1):**
✅ **Textual's `call_from_thread()`** - Native framework pattern for thread-safe UI updates
- Worker thread runs HTTP streaming without blocking main event loop
- Uses `self.call_from_thread()` to schedule UI updates in main thread
- UI stays responsive: scrolling, history navigation, etc. all work during streaming
- Input box disabled during streaming to prevent concurrent request race conditions

**Implementation:**
- Thread: `_stream_response_thread()` creates event loop, runs `_stream_response()`
- Events: `self.call_from_thread(self._handle_stream_event, type, data)`
- Completion: `self.call_from_thread(self._handle_stream_end)`
- Errors: `self.call_from_thread(self._handle_stream_error, msg)`

**Concurrency Protection:**
- Submission blocked during streaming (notification shown if attempted)
- Input box remains enabled - users can type, navigate history, prepare next prompt
- Prevents overlapping requests that would confuse the AI provider

---

### 2. VSCode Extension - Unused Imports

**Source:** CI build warnings
**Severity:** Low - No functional impact, just code cleanup
**Status:** ✅ **FIXED** (v1.15.1)

**File:** `vscode-extension/src/chatPanel.ts`

**Removed Imports:**
- `SLASH_COMMANDS` - only imported, never used
- `isAIForwardedCommand` - only imported, never used
- `parseCommand` - only imported, never used
- `formatToolsStatus` - only imported, never used
- `formatToolsList` - only imported, never used
- `formatToolConfig` - only imported, never used
- `formatToolHelp` - only imported, never used
- `formatAgentStatus` - only imported, never used
- `formatCheckpointStatus` - only imported, never used
- `formatCheckpointList` - only imported, never used

**Verification:**
- ✅ Removed unused imports from chatPanel.ts
- ✅ TypeScript compilation successful with no warnings
- ✅ All remaining imports are actively used in the code

---

### 2. CI Workflow - Already Fixed in v1.15.0

**Status:** ✅ Fixed in v1.15.0 release

The following fixes were applied during v1.15.0 release:

1. **CI test dependency fix** (commit 874c4fb)
   - Changed `uv sync --frozen --dev` to `uv sync --frozen --all-extras`
   - Ensures blinker and TUI dependencies are installed for tests

2. **PyInstaller spec file update** (commit a607df8)
   - Removed non-existent modules (ppxai.main, ppxai.commands.ui, etc.)
   - Added new v1.15.0 modules (commands.factory, rendering.base, etc.)

---

## Testing Checklist

Before releasing v1.15.1:

- [x] All 1105 tests pass (66.74s)
- [x] TypeScript lint shows 0 warnings
- [x] display_file tool implemented and integrated
- [ ] VSCode extension works correctly (requires manual testing)
- [ ] All v1.15.0 features still work (requires manual testing)
- [ ] Test display_file tool with AI (manual testing)

---

## Release Checklist

- [x] Update CHANGELOG.md with v1.15.1 entry
- [x] Update version numbers across all files
- [x] Create docs/RELEASE-NOTES-v1.15.1.md
- [x] Implement /show command as AI tool (`display_file` tool)
- [x] All 1105 tests passing
- [x] TypeScript compilation: 0 warnings
- [ ] Merge to master
- [ ] Run `/release v1.15.1`

---

## References

- v1.15.0 release: https://github.com/rcconsult/ppxai/releases/tag/v1.15.0
- CI fix commit: 874c4fb
- PyInstaller fix commit: a607df8

# Work In Progress: v1.15.0 Feature Parity

**Branch:** `feature/new-tui-command`
**Last Updated:** 2026-01-28
**Status:** Ready for Release

## Completed This Session

**Phase 1 - Type-based rendering:**
- [x] Type-based file display migration for /show command
- [x] TreeResult uses DataViewer with Ctrl+V toggle (tree ↔ source)
- [x] TableResult uses TableViewer with Ctrl+V toggle (table ↔ source)
- [x] MarkdownResult renders in side panel
- [x] ImageResult uses ImageViewer
- [x] FileViewResult uses CodeEditor
- [x] python-magic dependency for file type detection
- [x] All 1105 tests passing
- [x] FEATURE-PARITY-ANALYSIS.md created

**Phase 2 - Consistency fixes:**
- [x] Auto-save interval (commit 00b0348)
- [x] Crash recovery with dirty flag (commit 00b0348)
- [x] Debug log display fix (commit 4e876f0)
- [x] Session restore config fix (commit a059c42)
- [x] Session restoration permissive mode (commit f1547bd)
- [x] Bootstrap sequence fix (commit 8620dd6)
- [x] Async event loop error handling (commit b09169e)
- [x] Async session restoration (commit 5785506)
- [x] Debug and trace CLI flags (commit 30fc1d9, 89d5be9)
- [x] Coding commands async compatibility (commit pending)
- [x] Logger enhancement with exc_info (commit pending)
- [x] Textual logger override (commit pending)
- [x] Session restoration worker fix (commit pending)
- [x] Autocomplete disabled and deferred (commit 87785e9)

**Phase 3 - Blinker Event Bus Integration (2026-01-28):**
- [x] Blinker event bus for decoupled components (commit 6eb83e2)
- [x] 8 event handlers subscribed (STREAM_START, STREAM_CHUNK, STREAM_END, TOOL_CALL, TOOL_RESULT, TOOL_ERROR, ERROR, INFO)
- [x] STREAM_END.data handling fixed (extracts content when no chunks)
- [x] Tool consent callbacks wired to EngineClient
- [x] All 1105 tests passing
- [x] Documentation updated (FEATURE-PARITY-ANALYSIS.md)

---

## Phase 1 - Critical Missing Features (User-Visible)

### 1.1 Tab Autocomplete ⚠️ DEFERRED TO PHASE 4/5
- [x] Command completion (slash commands) - All 30+ commands from CommandFactory
- [x] @file/@clipboard/@url context providers - With descriptions
- [x] File path completion with ignore patterns (.git, node_modules, __pycache__, .venv)
- [x] Model/provider name completion - Dynamic from config
- [x] Subcommand completion (tools, usage, checkpoint, status, theme)
- [ ] **DISABLED:** Inadequate implementation, needs complete refactoring

**Implementation:**
- `ppxai/tui/completer.py` - TextualCompleter with 440 lines of completion logic
- `ppxai/tui/widgets/completion_popup.py` - Visual popup widget with arrow key navigation
- Press Tab to show completions, arrow keys to navigate, Enter/Tab to select
- File cache with 5-second TTL for performance
- **Commit:** 4400480 (initial), disabled in 87785e9 - see Phase 4/5 for refactoring requirements

### 1.2 Status Bar Toggles ✅
- [x] `/status version` - toggle version display (v1.15.0)
- [x] `/status cwd` - toggle working directory display (ppxai/utils)
- [x] `/status datetime` - toggle date/time display (2026-01-26 20:30)

**Implementation:**
- Config stored in `ppxai-config.json` under `tui.show_version`, `show_cwd`, `show_datetime`
- Badges added on app startup from config
- Toggle commands update config and show/hide badges dynamically
- DateTime badge updates every minute when enabled

### 1.3 Agent Mode Badges ✅
- [x] Agent mode indicator badge - Shows "Agent: ACTIVE" in green
- [x] Checkpoint status badge (↶ valid, ↶! stale) - Unicode arrows

**Implementation:**
- Agent badge shows when `/agent on` is executed
- Checkpoint badge shows ↶ for valid checkpoint (undo available)
- Checkpoint badge shows ↶! for stale checkpoint (undo may not work)
- Badges update dynamically when agent mode changes

### 1.4 Reasoning Token Display
- [ ] DeepSeek R1 reasoning tokens - DEFERRED (not in Rich TUI yet)
- [ ] GPT-OSS thinking display - DEFERRED (requires special handling)
- [ ] Collapsible reasoning sections - DEFERRED

**Note:** Reasoning token display is not yet implemented in Rich TUI either, so this is not a parity gap. Will be added in future version when provider support is more mature.

---

## Phase 2 - Consistency Fixes ✅ COMPLETED

### 2.1 Auto-save Interval ✅
- [x] Implement configurable auto-save interval
- [x] Match Rich TUI behavior
- [x] Auto-save after each message pair

**Implementation:**
- Auto-save in `_handle_event()` after STREAM_END
- Uses `session.save_dirty()` to mark session as dirty
- Configurable via `session.auto_save_interval` (default: 1)
- **Commit:** 00b0348

### 2.2 Crash Recovery ✅
- [x] Dirty session detection
- [x] Crash recovery prompt on startup
- [x] Mark session clean on graceful exit

**Implementation:**
- Check `dirty` flag in `_check_session_restoration()`
- Show "⚠ Session Recovery" modal (higher priority than auto_restore)
- Clear dirty flag if user declines
- Call `session.mark_clean()` in `action_quit()`
- **Commit:** 00b0348

### 2.3 Debug Log Display ✅
- [x] Show debug log output in TUI (side panel)
- [x] `/debug-log [on|off|show|clear]` command integration
- [x] Use FileViewResult for proper display

**Implementation:**
- Fixed `/debug-log show` to return FileViewResult instead of TextResult
- Displays last 50 lines in CodeEditor side panel
- Read-only view with syntax highlighting
- **Commit:** (pending)

### 2.4 Tools Config ✅
- [x] `/tools config` works correctly in Textual TUI
- [x] Uses KeyValueResult renderer (already implemented)

**Implementation:**
- Command already existed and worked
- KeyValueResult renderer displays tool configuration
- No changes needed

### 2.5 Session Restoration Fix ✅
- [x] Match Rich TUI's permissive restoration behavior
- [x] Don't fail restoration when API key missing
- [x] Always render messages regardless of provider/model status
- [x] Use strict=True for model validation
- [x] Fall back to default model if stored model unavailable

**Implementation:**
- Don't check return value of `set_provider()` - just call it (Rich TUI line 579)
- Use `strict=True` for `set_model()` validation (Rich TUI line 586)
- Fall back to provider's default model if unavailable (Rich TUI lines 589-594)
- Always continue restoration even if provider/model can't be activated
- **Commit:** f1547bd

**Bug Fixed:**
- Session with 70 messages + provider=gemini showed empty chat with provider=perplexity
- Root cause: Textual TUI was too strict - checked `set_provider()` return value
- When GEMINI_API_KEY missing, restoration failed and stopped
- Now matches Rich TUI: permissive restoration, always shows messages

**Additional Fix (commit 5785506):**
- Made `_restore_session()` async to properly integrate with Textual's event loop
- All callers now use `await` when calling the method
- Fixes asyncio.run() errors during session restoration

### 2.6 Bootstrap Sequence Fix ✅
- [x] Initialize config before event loop starts
- [x] Match Rich TUI's bootstrap sequence exactly
- [x] Prevent asyncio.run() conflicts
- [x] Ensure .env files loaded before event loop

**Implementation:**
- Move `initialize()` call from `_initialize_engine()` to `main()` in `tui/__init__.py`
- Call `initialize()` BEFORE `app.run()` starts Textual's event loop
- Remove duplicate `initialize()` call from `_initialize_engine()`
- **Commit:** 8620dd6

**Bug Fixed:**
- "asyncio.run() cannot be called from a running event loop" error on startup
- Root cause: Textual TUI called initialize() inside on_mount() (after event loop started)
- Rich TUI calls initialize() in main() (before event loop starts)
- Now matches Rich TUI: initialize → load .env → start event loop

**Bootstrap Sequence:**
```
Rich TUI:  main() → initialize() → load .env → create objects → start loop
Textual TUI (old): main() → app.run() → [loop] → initialize() ❌
Textual TUI (new): main() → initialize() → app.run() → [loop] ✅
```

### 2.7 Async Event Loop Error Handling ✅
- [x] Support async command handlers
- [x] Catch asyncio.run() errors with helpful messages
- [x] Add async_compat module for event loop detection

**Implementation:**
- Check if command handler returns coroutine and await it
- Catch RuntimeError from asyncio.run() attempts
- Show clear error message suggesting Rich TUI for incompatible commands
- Add `ppxai/common/async_compat.py` with event loop helpers
- **Commit:** b09169e

**Error Message:**
```
Command failed: <command>
This command is not compatible with the Textual TUI yet.
It tries to create a new event loop while one is already running.
Try using the Rich TUI instead: uv run ppxai
```

### 2.8 Debug and Trace CLI Flags ✅
- [x] Add --debug flag for stderr logging
- [x] Add --trace flag for full exception tracebacks
- [x] Update Logger.error() to support exc_info parameter
- [x] Enhanced exception handling with traceback display

**Implementation:**
- `--debug`: Enables logging to both stderr and file (~/.ppxai/logs/tui-debug.log)
- `--trace`: Shows full stack traces in chat view (implies --debug)
- Sets PPXAIDE_TRACE env var for exception handlers
- All exceptions logged with full traceback when --trace enabled
- **Commit:** 30fc1d9

**Usage:**
```bash
uv run ppxaide --debug           # Debug logging to stderr + file
uv run ppxaide --trace           # Full tracebacks in chat + debug logging
```

**Benefits:**
- Systematic debugging instead of random code changes
- Immediate visibility of errors during development
- Full stack traces show exact location of issues
- Works with async event loop errors

---

## Phase 3 - Rich-Only Features (Consider Adding) ✅ COMPLETED

**Status:** Phase 3 feature parity achieved. All critical gaps addressed.

**Feature Parity Summary:**
- ✅ Status Bar: 100% parity (version/cwd/datetime toggles working)
- ✅ Session Management: 100% parity (restoration, auto-save, crash recovery)
- ✅ Agent/Checkpoint Badges: 100% parity (agent mode + checkpoint status)
- ⚠️ Tab Autocomplete: Deferred to Phase 4/5 (see below)
- ⏸️ Reasoning Tokens: Deferred (not in Rich TUI yet, not a parity gap)

**Textual TUI Advantages:**
- More themes (17+ vs 6+)
- Better keyboard shortcuts (Ctrl+T, Ctrl+P, Ctrl+W, etc.)
- Advanced file viewers (tree/table toggle, image support)
- Transactional state management (badge transactions)
- Side panel editing with syntax highlighting

### 3.1 Emoji Mode (Optional) - Rich TUI-only
- [ ] Text symbol fallback for terminal alignment
- [ ] `/theme emoji on|off` command

**Note:** Emoji mode is a Rich TUI-specific feature for terminal alignment. Not critical for parity.

---

## TODO: Phase 4/5 - Deferred Features (Needs Refactoring)

### 4.1 Autocomplete Enhancement ❌ DISABLED
**Status:** Disabled in commit 87785e9 - inadequate implementation

**Current Issues:**
- Fixed offset positioning (`offset-y: 90%`) instead of cursor-based
- Single column layout instead of multi-column like Rich TUI
- No alphabetical sorting of file list
- No lazy loading/virtual scrolling for large file lists
- Fixed 100 file limit with no dynamic pagination
- Files shown in random order, priority files hack

**What Rich TUI Has:**
- Cursor-based positioning (popup appears exactly at '@' character)
- Multi-column scrollable layout
- Alphabetical sorting of all files
- Dynamic lazy loading as user scrolls
- No file limit - entire project tree available

**Implementation Requirements:**
1. **Cursor positioning**: Get actual cursor coordinates in terminal, position popup relative to cursor
2. **Multi-column layout**: Use Textual Grid or Horizontal containers for columns
3. **Alphabetical sorting**: Sort files before display
4. **Virtual scrolling**: Implement lazy loading with scroll events
5. **Integration**: Study prompt_toolkit approach in Rich TUI (`ppxai/rich/completer.py`)

**Files to modify:**
- `ppxai/tui/widgets/input_box.py` - Re-enable tab handler (line 94-96)
- `ppxai/tui/widgets/completion_popup.py` - Complete refactoring needed
- `ppxai/tui/completer.py` - Sorting and pagination logic

**User feedback:** "showing fixed list... is not presentable to any user, it is a bug"

**Decision:** Focus on Phase 3 feature parity first, tackle this properly in Phase 4/5.

---

## TODO: Release Prep

- [ ] Run full test suite
- [ ] Update CHANGELOG.md for v1.15.0
- [ ] Create release notes: `docs/RELEASE-NOTES-v1.15.0.md`
- [ ] Version bump in all files
- [ ] Merge to master

---

## Files Modified in This Work

| File | Changes |
|------|---------|
| `ppxai/common/file_type.py` | NEW - File type detection |
| `ppxai/common/__init__.py` | Export file_type module |
| `ppxai/commands/display.py` | /show returns typed results |
| `ppxai/commands/results.py` | Add MarkdownResult |
| `ppxai/rendering/textual_renderer.py` | Use DataViewer/TableViewer |
| `ppxai/rendering/rich_renderer.py` | Add MarkdownResult renderer |
| `ppxai/tui/themes/layout.tcss` | Markdown styles for SidePanel |
| `pyproject.toml` | Add python-magic dependency |
| `tests/test_tui.py` | Update test assertions |
| `docs/FEATURE-PARITY-ANALYSIS.md` | Full comparison document |

---

## Quick Start for Next Session

```bash
# Checkout the branch
git checkout feature/new-tui-command
git pull

# Sync dependencies
uv sync --all-extras

# Run tests to verify state
uv run pytest tests/test_commands.py tests/test_tui.py -v

# Build and test TUI
uv run ppxaide
```

---

## Reference Documents

- [FEATURE-PARITY-ANALYSIS.md](FEATURE-PARITY-ANALYSIS.md) - Full comparison
- [TUI-COMMAND-REFACTORING-PLAN.md](TUI-COMMAND-REFACTORING-PLAN.md) - Architecture plan
- [architecture.md](architecture.md) - Transactional state pattern

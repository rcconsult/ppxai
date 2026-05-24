# Release Notes: v1.15.3

**Release Date:** 2026-02-07
**Branch:** bugfix/v1.15.3
**Focus:** Config Hot-Reload, DAG Init, Platform Alignment, TUI Stability

---

## Overview

v1.15.3 is a comprehensive stability and technical debt release that addresses critical configuration management issues, platform compatibility problems, and TUI reliability. This release includes 5 major workstreams with deep architectural improvements that eliminate long-standing bugs and workarounds.

**Key Improvements:**
- ✅ Config changes now reflected without restart
- ✅ All platforms (Windows/macOS/Linux) have consistent signal handling
- ✅ Eliminated stale config cache issues
- ✅ Removed 4 configuration workarounds
- ✅ 100% test pass rate (1157/1157 tests)

---

## Major Features

### 1. Config Hot-Reload Fix

**Problem:**
- `/model` and `/provider` commands showed stale provider lists after external config edits
- Session restore used outdated config when file was edited while app was running
- Root cause: `EngineClient._load_config()` captured snapshot of PROVIDERS dict that never refreshed

**Solution:**
- New `EngineClient.reload_config()` method refreshes all cached config data
- `/model` and `/provider` commands auto-reload config from disk
- All 3 clients (TUI, Rich, HTTP) reload config before restoring sessions
- HTTP + JSON-RPC endpoints reload before listing/switching providers/models

**Implementation Details:**
- `EngineClient.reload_config()` - Single entry point to refresh ConfigStore + cached configs
- Module-level `reload_config()` updates PROVIDERS/MODELS in-place
- Session restore calls `engine.reload_config()` before loading saved state

**Files Changed:**
- `ppxai/engine/client.py` - Added `reload_config()` method
- `ppxai/commands/provider.py` - Auto-reload on `/provider` command
- `ppxai/tui/app.py` - Reload on session restore
- `ppxai/rich/main.py` - Reload on session restore
- `ppxai/server/http.py` - Reload on provider/model endpoints

**Impact:**
- Config changes reflected immediately without restart
- No more stale provider/model lists
- Session restore works with updated configs

---

### 2. DAG-Based Config Initialization

**Problem:**
- `__getattr__` lazy loading caused no caching (PROVIDERS recomputed on every access)
- Snapshot staleness: `self._providers_config = PROVIDERS` went stale after reload
- Fragile workarounds: Commands had to re-import PROVIDERS after reload

**Solution:**
- Replaced `__getattr__` with explicit `initialize()` function
- Module-level PROVIDERS/MODELS dicts populated at startup
- In-place mutation (`.clear()` + `.update()`) keeps all references fresh
- EngineClient uses `@property providers_config` instead of snapshot
- Added `reset_config_after_test` fixture for test isolation

**Implementation Details:**

**ppxai/config/__init__.py:**
```python
# Module-level attributes - populated by initialize()
PROVIDERS: Dict[str, Any] = {}
MODELS: Dict[str, Any] = {}

def initialize():
    """Load config and populate module-level PROVIDERS/MODELS."""
    global PROVIDERS, MODELS
    config = ConfigStore.get_instance().config
    PROVIDERS.clear()
    PROVIDERS.update(config.get("providers", {}))
    MODELS.clear()
    MODELS.update(PROVIDERS.get("perplexity", {}).get("models", {}))
```

**ppxai/engine/client.py:**
```python
@property
def providers_config(self) -> dict:
    """Always returns current providers from config module."""
    from ..config import PROVIDERS
    return PROVIDERS
```

**Entry Points:**
- Rich TUI: `ppxai/rich/main.py` (already had it)
- Textual TUI: `ppxai/tui/app.py` in `on_mount()`
- HTTP Server: `ppxai/server/http.py` in startup
- Tests: `tests/conftest.py` in `pytest_configure()`

**Dead Code Removed:**
- `_lazy_attrs` dict
- `__getattr__` function
- `self._providers_config` snapshot
- `self._default_provider` (unused)
- `self._get_default_model` (unused)

**Workarounds Removed:**
- `ppxai/commands/provider.py` - Removed deferred re-import after reload
- `ppxai/tui/app.py` - Removed local import for freshness
- `ppxai/server/http.py` - Improved comment (latent bug prevented)

**Test Isolation Fix:**
```python
@pytest.fixture(autouse=True)
def reset_config_after_test():
    """Reset PROVIDERS/MODELS after each test for isolation."""
    yield  # Run the test
    from ppxai.config import initialize
    initialize()
```

**Files Changed:**
- `ppxai/config/__init__.py` - Replace `__getattr__` with `initialize()`
- `ppxai/config/store.py` - Call `initialize()` after reload
- `ppxai/engine/client.py` - Remove snapshot, add property
- `ppxai/commands/provider.py` - Clean imports
- `ppxai/tui/app.py` - Add `initialize()` call, clean imports
- `ppxai/server/http.py` - Improved comments
- `tests/conftest.py` - Add reset fixture
- `tests/test_commands.py` - Fix 3 patch decorators

**Test Results:**
- **Before:** 1147/1157 pass (10 test isolation failures)
- **After:** 1157/1157 pass (100% pass rate) ✅

**Impact:**
- No stale snapshots - all engines see fresh config via property
- No workarounds - clean top-level imports everywhere
- Predictable behavior - PROVIDERS/MODELS updated in-place on reload
- Easier debugging - no magic `__getattr__`, explicit initialization

---

### 3. Platform Alignment (Windows/macOS/Linux)

**Problems Fixed:**

**A. Signal Handling Inconsistencies**
- SIGINT handler skipped on Windows ("Windows signal handling has quirks")
- SIGTERM not handled in TUI (only server had it)
- Ctrl+C didn't work on Windows

**B. Binary Search Path Inefficiency**
- All paths checked regardless of platform
- Windows checked `/usr/local/bin`, `/usr/bin` (Unix-only)
- Unix/macOS/Linux checked `AppData/Local/ppxai` (Windows-only)

**C. Path Expansion Inconsistency**
- Mixed use of `Path.home()` and `os.path.expanduser("~")`
- Inconsistent path handling across modules

**Solutions:**

**A. Signal Handling - All Platforms**

**ppxai/tui/__init__.py:**
```python
def signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM gracefully."""
    try:
        app.call_from_thread(app.action_quit)
    except Exception:
        sys.exit(0)

# Install handlers on all platforms (Windows, macOS, Linux)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

**B. Platform-Aware Binary Search Paths**

**ppxai/config/__init__.py:**
```python
def get_bin_search_paths() -> List[str]:
    """Get platform-aware binary search paths."""
    all_paths = get_paths_config().get("bin_search_paths", [])

    if sys.platform == 'win32':
        # Windows: Skip Unix system paths
        return [p for p in all_paths if not p.startswith('/usr')]
    else:
        # Unix/macOS/Linux: Skip Windows AppData
        return [p for p in all_paths if 'AppData' not in p]
```

**C. Path Expansion Standardization**

**Pattern:**
```python
# Prefer: Path.home() / ".ppxai" / "file.json"
# Over:   os.path.expanduser("~/.ppxai/file.json")

# Exception: Keep os.path.expanduser() in tool handlers
# (supports ~username syntax, not just ~)
```

**Files Changed:**
- `ppxai/tui/__init__.py` - Signal handling for all platforms
- `ppxai/config/__init__.py` - Platform-aware binary search
- `ppxai-desktop.py` - Use filtered paths, add comments
- `docs/installation.md` - Platform-specific documentation

**Documentation Added:**
- Clipboard support per platform (Windows/macOS/Linux/headless)
- Signal handling (SIGINT/SIGTERM) on all platforms
- Linux headless requirements (`xclip`/`xsel`)

**Impact:**
- Windows users get Ctrl+C and SIGTERM support
- Faster binary search (fewer unnecessary path checks)
- Consistent behavior across all platforms

---

### 4. TUI EventBus Stability

**Problem:**
- EventBus handlers crashed when firing before chat_view was mounted
- "No nodes match '#chat-view'" errors during startup/shutdown
- v1.15.2 WARNING events had no TUI handler

**Solution:**
- Added NoMatches guards to all event handlers
- Added ENGINE_WARNING handler for hallucination detection
- Verified shell consent dialog threading (correct implementation)

**Implementation:**
```python
async def _on_engine_warning(self, sender, data, **kwargs) -> None:
    """Handle ENGINE_WARNING event (hallucination detection)."""
    try:
        chat_view = self.query_one("#chat-view", ChatView)
    except NoMatches:
        return  # Silently ignore if chat_view not mounted

    chat_view.add_system_message(f"[yellow]⚠ Warning:[/yellow] {data}")
```

**Protected Handlers:**
- `_on_tool_call`
- `_on_tool_result`
- `_on_tool_error`
- `_on_engine_error`
- `_on_engine_warning` (new)
- `_on_engine_info`

**Files Changed:**
- `ppxai/tui/event_bus.py` - Added ENGINE_WARNING constant
- `ppxai/tui/app.py` - Added guards and WARNING handler

**Impact:**
- No crashes during app lifecycle transitions
- Hallucination warnings now visible in TUI
- Completes v1.15.2 response validation system

---

### 5. Benchmarks & Performance

**Added:**
- DGX Spark benchmark results for GPT-OSS-120B, Qwen3-30B-A3B, Qwen2.5-Coder-32B
- Results tracked in `benchmarks/llm-eval/results/`
- Hallucination resistance gate tests

**Improvements:**
- Reduced model hints debug noise (only log on match, not on miss)
- Working directory change deduplication (compare resolved paths)

**Files Changed:**
- `ppxai/engine/client.py` - Simplified logging, added cwd deduplication
- `benchmarks/llm-eval/results/` - New benchmark data

**Impact:**
- Cleaner debug logs
- Fewer UI updates during tool execution
- Benchmark data for model comparison

---

## Files Modified Summary

**Total:** 15 files changed (~350 lines)

**Core:**
- `ppxai/config/__init__.py` - DAG init, binary search filtering
- `ppxai/config/store.py` - Call `initialize()` after reload
- `ppxai/engine/client.py` - Property pattern, simplified logging
- `ppxai/commands/provider.py` - Clean imports
- `ppxai/tui/app.py` - Config init, clean imports, event guards
- `ppxai/tui/__init__.py` - Signal handling all platforms
- `ppxai/tui/event_bus.py` - ENGINE_WARNING constant
- `ppxai-desktop.py` - Platform filtering

**Tests:**
- `tests/conftest.py` - Reset fixture, initialize()
- `tests/test_commands.py` - Fix patch decorators

**Docs:**
- `docs/installation.md` - Platform-specific notes
- `docs/RELEASE-NOTES-v1.15.3.md` - This file
- `CHANGELOG.md` - v1.15.3 entry
- `TODO-v1.15.3.md` - Status updates
- `~/.claude/.../MEMORY.md` - Patterns #8-10

---

## Testing & Validation

**Test Results:**
- **1157/1157 tests pass** (100% pass rate) ✅
- No regressions introduced
- Test isolation fixed with reset fixture

**Manual Testing Checklist:**
- [x] Config hot-reload works (edit config, run `/provider list`)
- [x] Ctrl+C works on Windows
- [x] SIGTERM works on all platforms
- [x] Binary search paths filtered correctly
- [x] WARNING events display in TUI
- [x] No NoMatches crashes

---

## Upgrade Notes

**From v1.15.2 → v1.15.3:**
- No breaking changes
- No configuration changes required
- Drop-in replacement for v1.15.2

**Benefits:**
- Config changes reflected without restart
- Windows users get Ctrl+C support
- More stable TUI (no EventBus crashes)
- Cleaner debug logs
- Faster binary search

**Automatic Migrations:**
- None required

---

## Architecture Patterns Added

From MEMORY.md:

**Pattern #8: TUI EventBus Handler Resilience**
- All EventBus handlers MUST guard against NoMatches exceptions
- Use try/except around `query_one()` calls
- Prevents crashes when handlers fire before UI is ready

**Pattern #9: WARNING Event Handling**
- WARNING events from response validator must be displayed
- TUI: Yellow ⚠ indicator in chat
- Web: Styled warning boxes with severity

**Pattern #10: Working Directory Change Deduplication**
- Only emit WORKING_DIR_CHANGED when path actually changes
- Compare resolved paths to prevent duplicate events

---

## Known Issues

None specific to v1.15.3.

---

## Next Steps (v1.16.0)

**Planned:**
- File navigation commands (`/ls`, `/tree`)
- Interactive file tree sidebar (ppxaide)
- Apply Pattern #8-10 to remaining code
- Enhanced test coverage for EventBus handlers

See `TODO-v1.16.0.md` for detailed planning.

---

## Performance Metrics

**Test Suite:**
- Total tests: 1157
- Pass rate: 100%
- Total time: ~44.6s
- Average: 0.0385s per test

**Slowest Tests:**
1. `test_web_premium_fallback_on_error` (4.99s)
2. `test_many_messages_performance` (2.58s)
3. `test_page_up_down_in_chat_view` (2.35s)

**Fastest Test:**
- `test_is_table_block_with_leading_text` (0.0001s)

---

**Release Tag:** v1.15.3
**Commit:** [Will be set during release]
**Download:** https://github.com/rcconsult/ppxai/releases/tag/v1.15.3

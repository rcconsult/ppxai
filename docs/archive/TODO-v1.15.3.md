# TODO: v1.15.3 - Config Hot-Reload, DAG Init & Platform Alignment

**Created:** 2026-02-07
**Branch:** feature/v1.15.5 (completed)
**Status:** ✅ Complete (6/6 workstreams)
**Previous Release:** v1.15.2
**Last Updated:** 2026-02-14

---

## Executive Summary

### ✅ Completed (6/6 workstreams)

| # | Workstream | Status | Impact | Completed |
|---|------------|--------|--------|-----------|
| 1 | **Config Hot-Reload Fix** | ✅ Done | Config changes reflected without restart | 2026-02-08 |
| 2 | **TUI EventBus Stability** | ✅ Done | No NoMatches crashes, warnings displayed | 2026-02-08 |
| 3 | **DGX Spark Benchmarks** | ✅ Done | Results tracked for GPT-OSS, Qwen3, Qwen2.5-Coder | 2026-02-08 |
| 4 | **DAG-Based Config Init** | ✅ Done | No stale cache, 100% test pass rate | 2026-02-08 |
| 5 | **Platform Alignment** | ✅ Done | Signal handling all platforms, platform-aware binary search | 2026-02-08 |
| 7 | **Tool Calling Clarification** | ✅ Done | Metadata distinguishes native vs prompt-based | 2026-02-14 |

### ⏳ Deferred Items (1/7 workstreams)

| # | Workstream | Priority | Effort | Status |
|---|------------|----------|--------|--------|
| 6 | **File Navigation** | Medium | 7 days | Deferred to v1.16.0 |

### Release Recommendation

**v1.15.3 is COMPLETE with:**
- ✅ Config Hot-Reload Fix (Done)
- ✅ TUI EventBus Stability (Done)
- ✅ Benchmarks (Done)
- ✅ Platform Alignment (Done)
- ✅ DAG-Based Config Init (Done)
- ✅ Tool Calling Clarification (Done)

**Deferred to v1.16.0:**
- 🔲 File Navigation (7 days - feature work)

**Status:** ✅ All v1.15.3 work complete (6/6 workstreams). Ready for v1.15.5 release.

---

## Detailed Workstreams

---

## 1. Config Hot-Reload Fix ✅

**Status:** Done
**Effort:** Completed

| Feature | Description | Status |
|---------|-------------|--------|
| **Config auto-reload** | `/model` and `/provider` commands reload config from disk | ✅ Done |
| **`EngineClient.reload_config()`** | Single entry point to refresh all cached config data | ✅ Done |
| **Session restore reload** | All 3 clients reload config before restoring sessions | ✅ Done |
| **Server endpoint reload** | HTTP + JSON-RPC endpoints reload before listing/switching | ✅ Done |
| **Root cause** | ConfigStore singleton + EngineClient snapshot = stale config (since v1.8.0) | ✅ Identified |

**Root Cause:** `EngineClient._load_config()` captures `self._providers_config = PROVIDERS` at init time. When config file is edited externally (e.g., adding new models), the cached dict goes stale. `reload_config()` now refreshes ConfigStore + all cached config snapshots.

---

## 2. DAG-Based Config Initialization ✅

**Priority:** High (tech debt)
**Status:** Done (10 test isolation issues remain)
**Effort:** 0.5 days (Completed)

### Completed Changes

All planned implementation steps completed:

1. ✅ **Replaced `__getattr__` with `initialize()`** - `ppxai/config/__init__.py`
   - Module-level `PROVIDERS` and `MODELS` dicts
   - `initialize()` function populates dicts in-place using `.clear()` + `.update()`
   - `reload_config()` calls `initialize()` after store reload

2. ✅ **Simplified EngineClient** - `ppxai/engine/client.py`
   - Removed `self._providers_config` snapshot (line 137)
   - Removed `self._default_provider` dead code (line 141)
   - Added `@property providers_config` - always returns current PROVIDERS
   - Updated 3 consumers to use property (lines 424, 432, 501)

3. ✅ **Removed workarounds** - 4 files cleaned up
   - `ppxai/commands/provider.py` - Top-level import, removed deferred re-import
   - `ppxai/tui/app.py` - Top-level import, removed local import
   - Fixed latent bug in `ppxai/server/http.py` - improved comment clarity

4. ✅ **Added `initialize()` calls** - 3 entry points
   - Rich TUI: `ppxai/rich/main.py` (already had it)
   - Textual TUI: `ppxai/tui/app.py` in `on_mount()`
   - Tests: `tests/conftest.py` in `pytest_configure()`

5. ✅ **Cleaned up dead code**
   - Removed `self._get_default_model` from EngineClient
   - Removed `_lazy_attrs` dict from config/__init__.py
   - Removed `__getattr__` function from config/__init__.py

### Test Results

- **1157/1157 tests pass** (100% pass rate) ✅
- **Test isolation fix:** Added `reset_config_after_test` fixture in `conftest.py`
  - Auto-runs after each test to reset PROVIDERS/MODELS
  - Ensures clean config state for every test
  - Fixed all 10 test isolation issues

### Known Issues

### Problem

`ppxai/config/__init__.py` uses module-level `__getattr__` to lazily compute `PROVIDERS` and `MODELS`. This creates:

1. **No caching** - `PROVIDERS` is recomputed from ConfigStore on every access
2. **Snapshot staleness** - `EngineClient._providers_config = PROVIDERS` captures a dict at init that goes stale on reload
3. **Fragile workarounds** - Commands must re-import PROVIDERS after reload, call `_get_providers()` directly, or use dynamic imports

---

### Codebase Audit (2026-02-07)

#### A. Lazy Loading Mechanism (`ppxai/config/__init__.py`)

| Component | Lines | Description |
|-----------|-------|-------------|
| `_get_config()` | 56-62 | Reads `ConfigStore.get_instance().config` (fresh every call) |
| `_get_providers()` | 65-67 | Returns `_get_config().get("providers", {})` |
| `_get_models()` | 70-72 | Returns perplexity models only (legacy) |
| `_lazy_attrs` dict | 88-91 | Maps `"PROVIDERS"` → `_get_providers`, `"MODELS"` → `_get_models` |
| `__getattr__()` | 94-98 | Module hook: calls factory fn on every attribute access |

**Key behavior:** `__getattr__` is called on **every** access to `PROVIDERS` or `MODELS` — it returns a fresh dict each time (no module-level caching). This means `from ppxai.config import PROVIDERS` binds to whatever `_get_providers()` returns *at import time*, and that binding goes stale after `ConfigStore.reload()`.

#### B. EngineClient Snapshot Pattern (`ppxai/engine/client.py`)

**`_load_config()` (lines 134-145) — 7 cached attributes:**

| Attribute | Line | Type | Refreshed by `reload_config()`? |
|-----------|------|------|--------------------------------|
| `self._providers_config` | 137 | Dict snapshot | Yes (line 158) |
| `self._get_api_key` | 138 | Function ref | No (but calls fresh config internally) |
| `self._get_base_url` | 139 | Function ref | No (but calls fresh config internally) |
| `self._get_default_model` | 140 | Function ref | No (but calls fresh config internally) |
| `self._default_provider` | 141 | String value | **No** (stale after reload) |
| `self._shell_config` | 144 | Dict snapshot | Yes (line 159) |
| `self._agent_config` | 145 | Dict snapshot | Yes (line 160) |

**`reload_config()` (lines 147-160):**
```python
from ..config import reload_config as _reload_config
_reload_config()                              # L154: reload ConfigStore
from ..config import _get_providers
self._providers_config = _get_providers()     # L158: fresh providers
self._shell_config = get_shell_config()       # L159: fresh shell config
self._agent_config = get_agent_config()       # L160: fresh agent config
```

**Consumers of `self._providers_config`:**
| Usage | Line | Context |
|-------|------|---------|
| `if provider_name not in self._providers_config:` | 420 | `set_provider()` validation |
| `provider_config = self._providers_config[provider_name]` | 428 | `set_provider()` lookup |
| `for provider_id, config in self._providers_config.items():` | 497 | `list_providers()` |

**Consumers of `self._agent_config`:**
| Usage | Line | Context |
|-------|------|---------|
| `self.tool_manager.max_iterations = self._agent_config.get(...)` | 472, 603 | Agent start |
| `return self._agent_config` | 686 | `get_agent_config()` property |

**Consumer of `self._shell_config`:**
| Usage | Line | Context |
|-------|------|---------|
| `classify_shell_command(command, self._shell_config)` | 995 | Shell consent |

#### C. All PROVIDERS Import Sites (Workarounds)

| File | Line | Pattern | Workaround? |
|------|------|---------|-------------|
| `ppxai/config/__init__.py` | 88-98 | `__getattr__` lazy dispatch | **Source of the problem** |
| `ppxai/engine/client.py` | 137 | `self._providers_config = PROVIDERS` | **Snapshot** (goes stale) |
| `ppxai/engine/client.py` | 157-158 | `from ..config import _get_providers` | **Workaround** (post-reload re-fetch) |
| `ppxai/commands/provider.py` | 119 | `from ..config import PROVIDERS` | **Workaround** (deferred import after reload) |
| `ppxai/tui/app.py` | 646 | `from ppxai.config import PROVIDERS` | **Workaround** (local import for freshness) |
| `ppxai/tui/completer.py` | 19 | `from ..config import PROVIDERS` | Top-level (reads fresh via `__getattr__`) |
| `ppxai/rich/ui.py` | 14 | `from ..config import MODELS, ..., PROVIDERS` | Top-level (MODELS is perplexity-only legacy) |
| Tests (5 files) | various | `from ppxai.config import PROVIDERS` | Local imports in test functions |

#### D. All `reload_config()` Call Sites

| File | Lines | Context | Pattern |
|------|-------|---------|---------|
| `ppxai/engine/client.py` | 147-160 | `reload_config()` method | Refreshes 3 of 7 cached attrs |
| `ppxai/commands/provider.py` | 41 | `/model` handler | `engine_client.reload_config()` before listing |
| `ppxai/commands/provider.py` | 116 | `/provider` handler | `engine_client.reload_config()` then re-imports PROVIDERS |
| `ppxai/commands/utility.py` | 268 | `/config reload` handler | `engine_client.reload_config()` or raw `reload_config()` |
| `ppxai/tui/app.py` | 629 | Session restore | `self._engine_client.reload_config()` |
| `ppxai/rich/main.py` | 575 | Session restore | `handler.engine_client.reload_config()` |
| `ppxai/server/http.py` | 607 | `/config/reload` POST | Raw `reload_config()` (no engine refresh!) |
| `ppxai/server/http.py` | 765 | `GET /providers` | `engine.reload_config()` |
| `ppxai/server/http.py` | 799 | `POST /provider` | `engine.reload_config()` |
| `ppxai/server/http.py` | 824 | `GET /models` | `engine.reload_config()` |
| `ppxai/server/http.py` | 853 | `POST /model` | `engine.reload_config()` |
| `ppxai/server/http.py` | 1449 | Session restore | `engine.reload_config()` |
| `ppxai/server/jsonrpc.py` | 174, 187, 194, 207 | All 4 RPC methods | `self.engine.reload_config()` before every op |

#### E. Findings Summary

**3 distinct problems:**

1. **`__getattr__` re-evaluates on every access** (lines 94-98) — no module-level caching, each `PROVIDERS` access triggers `_get_providers()` → `ConfigStore.config.get("providers", {})`. Wasteful but functionally correct.

2. **EngineClient snapshots go stale** (line 137) — `self._providers_config = PROVIDERS` captures a dict reference at init. After `ConfigStore.reload()`, this reference points to the old dict. Fixed by `reload_config()` but only when explicitly called.

3. **Workaround proliferation** — 4 files use deferred/dynamic imports after reload to get fresh PROVIDERS. This is fragile and easy to get wrong (e.g., `http.py:607` calls raw `reload_config()` without refreshing engine caches).

**1 latent bug found:**
- `ppxai/server/http.py:607` — The `/config/reload` POST endpoint calls raw `reload_config()` but does NOT call `engine.reload_config()`. This means the HTTP server's EngineClient keeps stale `_providers_config`, `_shell_config`, `_agent_config` until the next provider/model endpoint call.

**1 dead attribute:**
- `self._default_provider` (line 141) — Set at init, never refreshed, and **never used** anywhere in the codebase after init.

---

### Current Flow (Broken)

```
Import time:    config.__getattr__("PROVIDERS") -> _get_providers() -> ConfigStore.config
EngineClient:   self._providers_config = PROVIDERS   <- snapshot, never auto-refreshed
Config change:  ConfigStore.reload()                  <- new dict, but snapshot is stale
Workaround:     engine_client.reload_config()         <- manually re-fetches _get_providers()
```

### Proposed Flow (DAG Init)

```
Startup:        config.initialize()  -> loads config, sets module-level PROVIDERS/MODELS
                engine.initialize()  -> depends on config, no snapshot needed
Config change:  config.reload()      -> updates module PROVIDERS/MODELS in place
                engine reads config.PROVIDERS (always current)
```

### Implementation

#### Step 1: Replace `__getattr__` with explicit `initialize()`

**File: `ppxai/config/__init__.py` (lines 82-98)**

Remove:
```python
_lazy_attrs = {
    "PROVIDERS": _get_providers,
    "MODELS": _get_models,
}

def __getattr__(name: str):
    """Lazy module attribute access for PROVIDERS and MODELS."""
    if name in _lazy_attrs:
        return _lazy_attrs[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

Replace with:
```python
# Module-level attributes - populated by initialize()
PROVIDERS: Dict[str, Any] = {}
MODELS: Dict[str, Any] = {}
_initialized = False

def initialize():
    """Load config and populate module-level PROVIDERS/MODELS.
    Safe to call multiple times (idempotent).
    """
    global PROVIDERS, MODELS, _initialized
    config = ConfigStore.get_instance().config
    PROVIDERS.clear()
    PROVIDERS.update(config.get("providers", {}))
    MODELS.clear()
    MODELS.update(PROVIDERS.get("perplexity", {}).get("models", {}))
    _initialized = True
```

**Critical:** Use `.clear()` + `.update()` instead of reassignment so that existing references (e.g., `from ppxai.config import PROVIDERS`) see the updated data.

Also update `reload_config()` in `ppxai/config/store.py` (line 119-121):
```python
def reload_config() -> Dict[str, Any]:
    """Reload configuration from disk and refresh module-level attributes."""
    result = ConfigStore.get_instance().reload()
    # Re-populate PROVIDERS/MODELS from fresh config
    from . import initialize
    initialize()
    return result
```

#### Step 2: Simplify EngineClient - remove snapshot pattern

**File: `ppxai/engine/client.py`**

Remove from `_load_config()` (lines 134-145):
```python
self._providers_config = PROVIDERS          # DELETE - snapshot
self._default_provider = get_default_provider()  # DELETE - unused
```

Add property:
```python
@property
def providers_config(self) -> dict:
    """Always returns current providers from config module."""
    from ..config import PROVIDERS
    return PROVIDERS
```

Simplify `reload_config()` (lines 147-160):
```python
def reload_config(self):
    """Reload config from disk and refresh engine state."""
    from ..config import reload_config as _reload_config
    _reload_config()  # Updates PROVIDERS/MODELS in place via initialize()
    self._shell_config = get_shell_config()
    self._agent_config = get_agent_config()
```

Update 3 consumers of `self._providers_config`:
| Line | Before | After |
|------|--------|-------|
| 420 | `if provider_name not in self._providers_config:` | `if provider_name not in self.providers_config:` |
| 428 | `provider_config = self._providers_config[provider_name]` | `provider_config = self.providers_config[provider_name]` |
| 497 | `for provider_id, config in self._providers_config.items():` | `for provider_id, config in self.providers_config.items():` |

#### Step 3: Remove workarounds from commands

**File: `ppxai/commands/provider.py`** — Remove deferred re-import (line 119):
```python
# Before (workaround):
engine_client.reload_config()
from ..config import PROVIDERS  # re-import after reload

# After (clean):
from ..config import PROVIDERS  # top-level import works now
engine_client.reload_config()
# PROVIDERS dict is updated in-place by reload_config() -> initialize()
```

**File: `ppxai/tui/app.py`** — Remove local import (line 646):
```python
# Before: local import inside method for freshness
from ppxai.config import PROVIDERS

# After: top-level import works (PROVIDERS is mutated in-place)
```

#### Step 4: Fix latent bug in HTTP server

**File: `ppxai/server/http.py` (line 607)**

```python
# Before (bug): raw reload doesn't refresh engine caches
reload_config()

# After: use engine.reload_config() if available
if engine:
    engine.reload_config()
else:
    reload_config()
```

#### Step 5: Add `initialize()` calls at entry points

| Entry Point | File | Change |
|-------------|------|--------|
| Rich TUI | `ppxai/main.py` | Add `config.initialize()` at startup |
| Textual TUI | `ppxai/tui/app.py` | Add `config.initialize()` in `on_mount()` |
| HTTP server | `ppxai/server/http.py` | Add `config.initialize()` in startup |
| Desktop app | `ppxai/desktop/app.py` | Add `config.initialize()` at startup |
| Tests | `tests/conftest.py` | Add `config.initialize()` in session-scoped fixture |

#### Step 6: Clean up dead code

| Item | File | Line | Action |
|------|------|------|--------|
| `self._default_provider` | `engine/client.py` | 141 | Delete (unused after init) |
| `self._get_default_model` | `engine/client.py` | 140 | Delete (stored but never used as cached ref) |
| `_lazy_attrs` dict | `config/__init__.py` | 88-91 | Delete |
| `__getattr__` function | `config/__init__.py` | 94-98 | Delete |

### Files Changed Summary

| File | Action | Est. Lines |
|------|--------|-----------|
| `ppxai/config/__init__.py` | Replace `__getattr__` with `initialize()`, add `PROVIDERS`/`MODELS` as real module vars | ~20 |
| `ppxai/config/store.py` | `reload_config()` calls `initialize()` after store reload | ~5 |
| `ppxai/engine/client.py` | Remove snapshot + dead attrs, add `providers_config` property, simplify `reload_config()` | ~25 |
| `ppxai/commands/provider.py` | Move PROVIDERS import to top-level, remove deferred import workaround | ~5 |
| `ppxai/tui/app.py` | Move PROVIDERS import to top-level, add `initialize()` in `on_mount()` | ~5 |
| `ppxai/server/http.py` | Fix `/config/reload` endpoint to use engine reload, add `initialize()` | ~5 |
| `ppxai/main.py` | Add `config.initialize()` at startup | ~2 |
| `ppxai/rich/ui.py` | No change needed (top-level import already works) | 0 |
| `ppxai/tui/completer.py` | No change needed (top-level import already works) | 0 |

### Testing

- [ ] Test `config.initialize()` called at all 4 entry points
- [ ] Test `config.reload_config()` updates `PROVIDERS` and `MODELS` **in place** (same dict object)
- [ ] Test `EngineClient.providers_config` property returns fresh data after reload
- [ ] Test `/provider list` shows correct providers after external config edit
- [ ] Test `/model list` shows correct models after external config edit
- [ ] Test session restore works with updated config
- [ ] Test top-level `from ppxai.config import PROVIDERS` sees updates after `reload_config()`
- [ ] Verify no `__getattr__` remains in `config/__init__.py`
- [ ] Test `/config reload` via HTTP POST refreshes engine caches (latent bug fix)
- [ ] Verify `self._default_provider` and `self._get_default_model` removal has no side effects

### Migration Safety

- **Backward compatible**: `from ppxai.config import PROVIDERS` still works (real module var, mutated in-place)
- **Fail-fast**: If `initialize()` not called, PROVIDERS is `{}` - fails early with clear error
- **Thread-safe**: ConfigStore.reload() is lock-protected; `initialize()` uses `.clear()/.update()` which are atomic under GIL
- **Tests**: Existing tests work - `initialize()` is idempotent, can be called in fixtures
- **In-place mutation**: `.clear()` + `.update()` ensures all existing references see new data (no dangling snapshots)

---

## 3. File Navigation ⏳

**Priority:** High
**Status:** Planned
**Effort:** ~7 days (Phase 0: 2 days, Phase 1: 5 days)

### Phase 0: Command-Based Navigation (MVP) - 2 days

Add `/ls` and `/tree` commands that work in ALL clients.

**New Commands:**
- `/ls [path]` - List files/directories (sizes, permissions, mod times, color-coded)
- `/tree [depth]` - Render directory tree (default depth: 3, icons, counts)

**Files to Create:**
- `ppxai/commands/builtin/navigation.py` - `/ls` and `/tree` implementation

**Files to Modify:**
- `ppxai/commands/handler.py` - Register new commands
- `ppxai/rendering/rich_renderer.py` - Handle DirectoryListingResult
- `ppxai/rendering/textual_renderer.py` - Handle DirectoryListingResult for TUI

**Command Result Types:**
```python
@dataclass
class DirectoryListingResult:
    """Result of /ls command"""
    path: str
    entries: List[FileEntry]  # name, size, modified, type, permissions
    total_size: int

@dataclass
class DirectoryTreeResult:
    """Result of /tree command"""
    path: str
    tree_data: Dict[str, Any]  # Nested dict for rendering
    total_dirs: int
    total_files: int
    max_depth: int
```

**Testing:**
- [ ] Test `/ls` in all three clients (ppxaide, Web, CLI)
- [ ] Test `/ls` with relative and absolute paths
- [ ] Test `/ls` with non-existent paths (error handling)
- [ ] Test `/tree` with different depth levels (1, 3, 5)
- [ ] Test `/tree` on large repositories (performance)
- [ ] Verify `.gitignore` patterns are respected
- [ ] Test with directories containing special characters

### Phase 1: ppxaide Interactive File Tree Sidebar - 5 days

NvChad-inspired interactive file tree in ppxaide (Textual TUI).

**Features:**
- Left sidebar with expandable directory tree (Textual's DirectoryTree)
- Keyboard navigation: arrows, Enter to open, Space to expand/collapse
- `Ctrl+E` toggle visibility, `Ctrl+I` inject `@file path` into input
- File icons, lazy loading, `.gitignore` awareness
- Click to open in side panel (read-only view)

**Layout:**
```
+--------------------------------------------------+
|  Header (Provider/Model/Tools/Badges)            |
+--------------+-----------------------------------+
| File Tree    | Chat Messages                     |
| (left panel) |                                   |
|              +-----------------------------------+
| > src/       | Code Preview / Editor             |
|   main.py    | (side panel - optional)           |
|   utils.py   |                                   |
| > tests/     |                                   |
+--------------+-----------------------------------+
| Input Box                                         |
+--------------------------------------------------+
```

**Files to Create:**
- `ppxai/tui/widgets/file_tree.py` - FileTree widget (~200 lines)

**Files to Modify:**
- `ppxai/tui/app.py` - Layout integration, keyboard bindings, events
- `ppxai/tui/themes/layout.tcss` - File tree panel sizing and styles
- `ppxai/tui/widgets/input_box.py` - `@file path` injection at cursor
- `ppxai/tui/widgets/side_panel.py` - Handle file tree selections

**Testing:**
- [ ] Test with small project (<100 files) and large project (>10,000 files)
- [ ] Test keyboard navigation (all bindings)
- [ ] Test file opening in side panel
- [ ] Test `@file` injection into input
- [ ] Test filtering/search functionality
- [ ] Test working directory sync (`/cd` updates tree root)
- [ ] Test resize with `Ctrl+[` / `Ctrl+]`

**Documentation:**
- [ ] Update `AGENTS.md` with new commands
- [ ] Add examples to `/help` output
- [ ] Add file tree section to ppxaide documentation
- [ ] Document keyboard bindings

---

## 4. Platform Alignment (Unix/macOS/Linux/Windows) ✅

**Priority:** High (critical)
**Status:** Done
**Effort:** 1 day (Completed)

### Completed Changes

All 4 sub-tasks implemented and documented:

1. ✅ **Signal handling** - TUI now handles SIGINT/SIGTERM on all platforms (Windows, macOS, Linux)
   - File: `ppxai/tui/__init__.py` lines 66-79
   - Removed Windows exclusion, both signals supported

2. ✅ **Binary search paths** - Platform-aware filtering for efficiency
   - File: `ppxai/config/__init__.py` line 517 (`get_bin_search_paths()`)
   - Windows skips `/usr/*` paths, Unix/macOS/Linux skip `AppData` paths
   - File: `ppxai-desktop.py` updated to use filtered paths

3. ✅ **Path expansion** - Standardized to `Path.home()`, intentional `os.path.expanduser()` only in tool handlers
   - `ppxai/usage.py`, `ppxai/checkpoint.py` already using `Path.home()`
   - Remaining `os.path.expanduser()` uses are correct (handle `~username` syntax)

4. ✅ **Documentation** - Platform-specific behaviors documented
   - File: `docs/installation.md` lines 978-1040
   - Covers clipboard support, signal handling, Linux headless requirements

### Issues Identified

#### A. Signal Handling Inconsistencies

| Issue | File | Line | Description | Platform |
|-------|------|------|-------------|----------|
| **SIGINT handler only on Unix** | `ppxai/tui/__init__.py` | 78-79 | SIGINT handler skipped on Windows with comment "Windows signal handling has quirks" | Windows needs handling |
| **SIGTERM not handled** | `ppxai/tui/__init__.py` | - | TUI only handles SIGINT, not SIGTERM (server handles both) | All platforms |
| **Server signal handling** | `ppxai/server/http.py` | 2364-2365 | Both SIGINT and SIGTERM handled in server | ✅ Good |

**Action:** Align TUI signal handling with server pattern - handle both SIGINT and SIGTERM on all platforms.

#### B. Binary Search Path Platform Logic

| Issue | File | Line | Description |
|-------|------|------|-------------|
| **Mixed platform paths** | `ppxai/config/__init__.py` | 491-496 | Hardcoded list includes both Unix (`~/.local/bin`) and Windows (`~/AppData/Local/ppxai`) paths |
| **No platform filtering** | `ppxai-desktop.py` | 74-88 | All paths checked regardless of platform (inefficient) |
| **Unix system paths on Windows** | `ppxai-desktop.py` | 84-85 | `/usr/local/bin` and `/usr/bin` checked on Windows |

**Action:** Add platform-specific filtering to `get_bin_search_paths()`:
```python
def get_bin_search_paths() -> List[str]:
    """Get list of directories to search for ppxai binaries (platform-aware)."""
    paths_config = get_paths_config()
    all_paths = paths_config.get("bin_search_paths", [])

    # Filter platform-specific paths
    if sys.platform == 'win32':
        # Windows: Skip Unix system paths
        return [p for p in all_paths if not p.startswith('/usr')]
    else:
        # Unix/macOS/Linux: Skip Windows AppData
        return [p for p in all_paths if 'AppData' not in p]
```

#### C. File Path Hyperlink Patterns (Windows Support)

| Issue | File | Line | Description |
|-------|------|------|-------------|
| **Unix path bias** | `ppxai/tui/hyperlinks.py` | 63-64 | Regex pattern prioritizes Unix paths (`/path/to/file`) before Windows (`C:\path\to\file`) |
| **Windows drive detection** | `ppxai/tui/hyperlinks.py` | 66 | Pattern `[A-Za-z]:` only matches single-letter drives (standard, but documented) |

**Status:** ✅ Actually OK - both patterns present, just ordered Unix-first (most common in dev environments).

#### D. Path Expansion Consistency

| Issue | File | Function | Description |
|-------|------|----------|-------------|
| **Mixed `Path.home()` and `os.path.expanduser()`** | Multiple | Various | Some code uses `Path.home()`, some uses `os.path.expanduser("~")` |

**Examples:**
- `ppxai/engine/session.py:24` → `Path.home() / ".ppxai"`
- `ppxai/engine/tools/builtin/editor.py:65` → `os.path.expanduser(file_path)`
- `ppxai/server/http.py:1131` → `os.path.expanduser(request.path)`

**Action:** Standardize on `Path.home()` (more pythonic, better type safety):
```python
# Before:
expanded = os.path.expanduser("~/.ppxai/config.json")

# After:
expanded = str(Path.home() / ".ppxai" / "config.json")
```

**Exception:** Keep `os.path.expanduser()` when handling user-provided paths that may contain `~username` syntax (not just `~`).

#### E. Clipboard Backend Detection (pyperclip)

| Issue | File | Line | Description |
|-------|------|------|-------------|
| **No fallback** | `ppxai/tui/clipboard.py` | 10-14 | If pyperclip import fails, all clipboard ops return False/None |
| **Platform-specific quirks** | - | - | pyperclip behavior varies by platform (needs xclip/xsel on Linux headless) |

**Status:** ✅ OK - graceful degradation with `CLIPBOARD_AVAILABLE` flag. Document pyperclip installation in setup guide.

### Implementation Plan

#### Step 1: Fix TUI Signal Handling (0.2 days)

**File: `ppxai/tui/__init__.py` (lines 66-79)**

```python
# Current (Unix-only SIGINT):
if sys.platform != 'win32':
    signal.signal(signal.SIGINT, sigint_handler)

# Proposed (all platforms, both signals):
def signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM gracefully."""
    try:
        app.call_from_thread(app.action_quit)
    except Exception:
        sys.exit(0)

# Install handlers on all platforms
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

**Testing:**
- [ ] Test Ctrl+C on Windows (should gracefully quit, not crash)
- [ ] Test Ctrl+C on macOS/Linux (no regression)
- [ ] Test SIGTERM via `kill -TERM <pid>` on Unix
- [ ] Test SIGTERM on Windows via Task Manager "End Task"

#### Step 2: Add Platform Filtering to Binary Search Paths (0.3 days)

**File: `ppxai/config/__init__.py` (line 517)**

Add platform-aware filtering to `get_bin_search_paths()`.

**Files to Update:**
- `ppxai/config/__init__.py` - Add filtering logic
- `ppxai-desktop.py` - Use filtered paths from config
- `scripts/release_preflight_check.py` - Update binary search

**Testing:**
- [ ] Test Windows binary search doesn't check `/usr/local/bin`
- [ ] Test Unix binary search doesn't check `AppData/Local/ppxai`
- [ ] Verify backward compatibility (custom paths in config still work)

#### Step 3: Standardize Path Expansion (0.3 days)

**Pattern:**
```python
# Prefer: Path.home() / ".ppxai" / "file.json"
# Over:   os.path.expanduser("~/.ppxai/file.json")
```

**Exception:** Keep `os.path.expanduser()` in tool handlers that accept user paths:
- `ppxai/engine/tools/builtin/editor.py` (handles `~username/file.txt`)
- `ppxai/server/http.py` (handles user-submitted paths via API)

**Files to Update:**
- `ppxai/engine/session.py` - Already uses `Path.home()` ✅
- `ppxai/config/loader.py` - Already uses `PPXAI_HOME = Path.home() / ".ppxai"` ✅
- `ppxai/usage.py` - Standardize to `Path.home()`
- `ppxai/checkpoint.py` - Standardize to `Path.home()`

**Testing:**
- [ ] Run full test suite on Windows
- [ ] Run full test suite on macOS
- [ ] Run full test suite on Linux
- [ ] Verify `~username` syntax still works in tool paths

#### Step 4: Document Platform-Specific Behaviors (0.2 days)

**Add to installation.md:**
- Windows: Clipboard requires pyperclip (auto-installed)
- Linux headless: Clipboard requires xclip or xsel (`apt install xclip`)
- macOS: All clipboard ops work out of box
- Signal handling: Ctrl+C and SIGTERM supported on all platforms (v1.15.3+)

### Files Changed Summary

| File | Action | Est. Lines |
|------|--------|-----------|
| `ppxai/tui/__init__.py` | Fix signal handling for all platforms | ~10 |
| `ppxai/config/__init__.py` | Add platform filtering to binary search | ~15 |
| `ppxai-desktop.py` | Use filtered paths from config | ~5 |
| `ppxai/usage.py` | Standardize to `Path.home()` | ~5 |
| `ppxai/checkpoint.py` | Standardize to `Path.home()` | ~5 |
| `docs/installation.md` | Document platform-specific requirements | ~30 |
| `CLAUDE.md` | Update platform alignment notes | ~10 |

### Migration Safety

- **Backward compatible**: Path resolution logic unchanged, just standardized
- **No config migration**: Users don't need to change configs
- **Signal handling**: Windows users get new Ctrl+C support (improvement)
- **Binary search**: Faster (fewer unnecessary path checks)

---

## 7. Tool Calling Clarification ✅

**Priority:** High (accuracy)
**Status:** ✅ Complete
**Effort:** 0.5 days (4 hours)
**Created:** 2026-02-08
**Completed:** 2026-02-14
**Commit:** 26217e0

### Problem

API verification tests revealed that ppxai uses **TWO different tool calling methods**:
1. **Native Tool Calling** - Provider returns `tool_calls` in API response
2. **Prompt-Based Tool Calling** - Inject tools into prompt, parse JSON from text

Current issues:
- ❌ Not documented which providers use which method
- ❌ Benchmarks don't distinguish between native vs prompt-based
- ❌ Perplexity marked as supporting tools (it doesn't - uses prompt-based workaround)
- ❌ Gemini provider uses deprecated SDK (`google.generativeai`)
- ⚠️ Capability flags don't reflect actual API behavior

### Test Results (2026-02-08)

**Perplexity (sonar-pro, sonar-reasoning-pro):**
```
Direct API: IGNORED ⚠️
- API accepts `tools` parameter without error
- Returns NO tool_calls in response
- Models explain they "cannot access files" instead of calling tools

ppxai Engine: WORKS ✅
- TOOL_CALL events detected via prompt-based parsing
- Extracts JSON from text responses
```

**Conclusion:** Perplexity Sonar models do NOT support native function calling.

**Gemini (gemini-2.5-flash, gemini-2.5-pro):**
```
Direct API: ERROR 💥
- SDK is deprecated (google.generativeai)
- Need to migrate to google.genai

ppxai Engine: WORKS (intermittently) ⚠️
- Sometimes detects TOOL_CALL events
- May be using prompt-based instead of native
```

**Conclusion:** Gemini DOES support native function calling (per official docs), but our implementation needs SDK update.

**Documentation:**
- Full analysis: `benchmarks/llm-eval/TOOL_CALLING_ANALYSIS.md`
- Action plan: `benchmarks/llm-eval/ACTION_PLAN.md`
- Test results: `benchmarks/llm-eval/debug/api_tool_calling_test_results.json`

### Implementation Plan

#### Step 1: Add Capability Flags (0.1 days)

**File:** `ppxai/engine/providers/perplexity.py`

```python
# Line 56 - Update default_capabilities
default_capabilities = ProviderCapabilities(
    web_search=True,
    web_fetch=True,
    weather=True,
    citations=True,
    streaming=True,
    native_tool_calling=False,  # ← ADD: Sonar models don't support native API
)
```

**File:** `ppxai/config/loader.py`

```python
DEFAULT_CAPABILITIES = {
    ...
    "native_tool_calling": False,  # Default to False, enable per-provider
    ...
}
```

**Status:** Ready to implement

---

#### Step 2: Update Provider Docstrings (0.05 days)

**File:** `ppxai/engine/providers/perplexity.py`

Update line 97 from:
```python
tools: Ignored - Perplexity uses native search, not tools
```

To:
```python
tools: Converted to prompt-based tool calling. Perplexity Sonar models
       do not support native function calling via the API (tool_calls response).
       Instead, tool definitions are injected into the system prompt and
       responses are parsed for JSON tool call format.

       Note: Perplexity's Agentic Research API supports native tools for
       third-party models (openai/gpt-*, etc.) but NOT for Sonar models.

       See: https://docs.perplexity.ai/docs/agentic-research/tools
```

**Status:** Ready to implement

---

#### Step 3: Fix Gemini SDK (0.25 days)

**File:** `ppxai/engine/providers/gemini.py`

**Current:** Uses deprecated `google.generativeai`

**Replace with:** `google.genai` (official SDK)

**Changes:**
```python
# OLD
import google.generativeai as genai
from google.generativeai import types as genai_types

# NEW
from google import genai
from google.genai import types
```

**Reference:** https://github.com/google-gemini/deprecated-generative-ai-python

**Testing:**
```bash
cd benchmarks/llm-eval
uv run python test_tool_calling_apis.py
```

**Status:** Ready to implement
**Priority:** High (SDK is deprecated)

---

#### Step 4: Update Benchmarks (0.1 days)

**File:** `benchmarks/llm-eval/engine_runner.py`

Add tool calling method detection:

```python
async def run_async(self, categories: Optional[list[str]] = None):
    # Check provider capabilities
    from ppxai.config import get_provider_config
    provider_config = get_provider_config(self.provider)
    has_native_tools = provider_config.get("capabilities", {}).get("native_tool_calling", False)

    # Inform user about tool calling method
    if not has_native_tools and categories and "tool_calling" in categories:
        print(f"\nNOTE: {self.provider} uses prompt-based tool calling (not native API)")
        print(f"      Tests validate JSON format compliance and parsing reliability\n")

    # ... test loop ...

    # Add to metadata
    metadata={
        "runner": "engine",
        "timeout": self.timeout,
        "retries": self.retries,
        "tool_calling_method": "native" if has_native_tools else "prompt_based",  # ← ADD
    },
```

**Status:** Ready to implement

---

#### Step 5: Create Documentation (0.1 days)

**File:** `docs/tool-calling.md` (NEW)

Create comprehensive documentation:
- Native vs prompt-based tool calling
- Provider support matrix
- Configuration examples
- Troubleshooting guide

**Template:** See `benchmarks/llm-eval/ACTION_PLAN.md` for content

**Status:** Ready to implement

---

#### Step 6: Update Config Example (0.05 days)

**File:** `ppxai-config.example.json`

**Add to Perplexity:**
```json
"perplexity": {
  "capabilities": {
    "native_tool_calling": false,
    "__comment": "Sonar models use prompt-based tool calling"
  }
}
```

**Add to Gemini:**
```json
"gemini": {
  "capabilities": {
    "native_tool_calling": true,
    "__comment": "Gemini 2.5+ supports native function calling"
  },
  "generation_params": {
    "temperature": 0.0,
    "__comment": "Use 0.0 for deterministic tool calls"
  }
}
```

**Status:** ✅ Implemented (config example updated)

---

### ✅ Implementation Summary (2026-02-14)

**All 6 steps completed:**

| Step | Task | Status | Files Modified |
|------|------|--------|----------------|
| 1 | Add capability flags | ✅ Done | Already existed in v1.15.2 |
| 2 | Update provider docstrings | ✅ Done | Already existed in v1.15.2 |
| 3 | Fix Gemini SDK | ✅ Done | Migrated to google.genai in v1.15.2 |
| 4 | Update benchmarks | ✅ Done | engine_runner.py (+13 lines) |
| 5 | Create documentation | ✅ Done | docs/tool-calling.md (exists, 267 lines) |
| 6 | Update config example | ✅ Done | ppxai-config.example.json (+6 lines) |

**Changes made (commit 26217e0):**

1. **benchmarks/llm-eval/engine_runner.py** (+13 lines)
   - Added `_detect_tool_calling_method()` method
   - Added `tool_calling_method` field to metadata
   - Returns "native" or "prompt_based"

2. **ppxai-config.example.json** (+6 lines)
   - Fixed OpenAI: added `native_tool_calling: true`
   - Fixed OpenRouter: added `native_tool_calling: true`

**Results:**
- Perplexity → `prompt_based` ✓
- Gemini → `native` ✓
- OpenAI → `native` ✓
- OpenRouter → `native` ✓

**Note:** Steps 1-3 and 5 were already complete from v1.15.2 work. This task completed the remaining metadata and config updates.

---

### Testing Plan

**After implementation:**

1. **Verify capability flags:**
   ```bash
   uv run python -c "
   from ppxai.config import initialize, get_provider_config
   initialize()
   print('Perplexity:', get_provider_config('perplexity').get('capabilities', {}).get('native_tool_calling'))
   print('Gemini:', get_provider_config('gemini').get('capabilities', {}).get('native_tool_calling'))
   "
   ```

2. **Re-run API tests:**
   ```bash
   cd benchmarks/llm-eval
   uv run python test_tool_calling_apis.py
   ```

3. **Re-run benchmarks with debug:**
   ```bash
   python benchmark.py --provider perplexity --model sonar-pro --categories tool_calling --debug
   python benchmark.py --provider gemini --model gemini-2.5-flash --categories tool_calling --debug
   ```

4. **Verify unit tests:**
   ```bash
   uv run pytest tests/ -v -k tool
   ```

### Success Criteria

- [ ] Capability flags correctly set for all providers
- [ ] Documentation clearly explains native vs prompt-based
- [ ] Benchmark results include `tool_calling_method` metadata
- [ ] Test suite passes without regressions
- [ ] Gemini uses new SDK successfully
- [ ] Config example updated with correct settings

### Files Changed Summary

| File | Action | Est. Lines |
|------|--------|-----------|
| `ppxai/engine/providers/perplexity.py` | Add capability flag, update docstring | ~10 |
| `ppxai/engine/providers/gemini.py` | Migrate to new SDK | ~50 |
| `ppxai/config/loader.py` | Add native_tool_calling to defaults | ~2 |
| `benchmarks/llm-eval/engine_runner.py` | Add method detection and metadata | ~15 |
| `docs/tool-calling.md` | Create new documentation | ~150 (new) |
| `ppxai-config.example.json` | Add capability comments | ~10 |

### Impact

**User Benefits:**
- ✅ Clear understanding of tool calling methods
- ✅ Accurate benchmark comparisons
- ✅ Better configuration guidance
- ✅ Documented limitations per provider

**No Breaking Changes:**
- All existing functionality preserved
- Additive changes only
- Backward compatible

### References

- Test results: `benchmarks/llm-eval/debug/api_tool_calling_test_results.json`
- Full analysis: `benchmarks/llm-eval/TOOL_CALLING_ANALYSIS.md`
- Action plan: `benchmarks/llm-eval/ACTION_PLAN.md`
- Perplexity docs: https://docs.perplexity.ai/docs/agentic-research/tools
- Gemini docs: https://ai.google.dev/gemini-api/docs/function-calling
- Deprecated SDK: https://github.com/google-gemini/deprecated-generative-ai-python

---

## 5. Outstanding TODOs (Code-Level) ⏳

**Priority:** Medium
**Status:** Planned

| # | Item | File | Description |
|---|------|------|-------------|
| 3 | Interactive consent prompt (Rich TUI) | `rich_renderer.py:382` | Shows consent options but can't select - implement actual interactive prompt |
| 4 | Save dialog on side panel close | `side_panel.py:243` | Users may lose edits without warning - prompt to save on close |
| 6 | Cancel streaming on Ctrl+C | `tui/app.py:1920` | Ctrl+C closes panel but doesn't cancel in-flight streaming request |
| 7 | Git backend cleanup prompt | `chatPanel.ts:2268` | Add second prompt for git cleanup on checkpoint restore |

---

## Explicitly NOT in v1.15.3

### Web App File Tree Sidebar
Deferred to **v1.16.0**. See [TODO-v1.16.0.md](TODO-v1.16.0.md) Phase 2.

### ppxai (Rich CLI) Interactive File Tree
Not feasible - Rich is a rendering library, not a TUI framework. Users can use `/ls` and `/tree` commands (static output) or switch to `ppxaide`.

---

## Success Metrics & Release Criteria

### Completed Features

| Workstream | Status | Metric | Result |
|------------|--------|--------|--------|
| Config Hot-Reload | ✅ Done | Config changes reflected without restart | ✅ Achieved |
| TUI EventBus | ✅ Done | No NoMatches crashes, warnings displayed | ✅ Achieved |
| Benchmarks | ✅ Done | Results tracked in `benchmarks/llm-eval/results/` | ✅ Achieved |

### Open Items for v1.15.3

| Workstream | Status | Metric | Target |
|------------|--------|--------|--------|
| Tool Calling Clarification | ⏳ Open | Capability flags accurate, benchmarks distinguish native vs prompt-based | 0.5 days |

### Deferred to v1.16.0

| Workstream | Status | Metric | Target |
|------------|--------|--------|--------|
| `/ls`, `/tree` | 🔲 Planned | Commands work in all 3 clients, <2s on 10K files | Phase 0: 2 days |
| ppxaide tree | 🔲 Planned | File tree renders <500ms, no keyboard lag | Phase 1: 5 days |

---

## Next Steps for v1.15.3 Release

### ✅ Implementation Complete (5/7 workstreams)

Completed workstreams:
- ✅ Config Hot-Reload Fix
- ✅ TUI EventBus Stability
- ✅ DGX Spark Benchmarks
- ✅ Platform Alignment
- ✅ DAG-Based Config Init

**Test Status:** 1157/1157 tests pass (100% pass rate)

### ⏳ Remaining Work

High priority for release:
- ⏳ Tool Calling Clarification (4 hours)
  - Add capability flags (Perplexity: native_tool_calling=false)
  - Update provider docstrings
  - Fix Gemini SDK (migrate to google.genai)
  - Update benchmarks with tool_calling_method metadata
  - Create docs/tool-calling.md

See: `benchmarks/llm-eval/ACTION_PLAN.md` for detailed steps

### Ready for Release After Tool Calling Work

1. **Cross-Platform Testing**
   - Test on Windows, macOS, Linux
   - Verify signal handling (Ctrl+C, SIGTERM)
   - Verify binary search path filtering
   - Verify config hot-reload

2. **Documentation & Release**
   - Update CHANGELOG.md
   - Write RELEASE-NOTES-v1.15.3.md
   - Commit all changes
   - Run `/release v1.15.3`

3. **Post-Release**
   - Begin v1.16.0 planning
   - File navigation features (Phase 0: `/ls`, `/tree`)

---

## Version Alignment Note

**Current:** v1.15.3 scope reduced from 4 workstreams to 2 open items
**Next:** v1.16.0 will focus on file navigation features
**Impact:** Faster release cycle, focused stability improvements

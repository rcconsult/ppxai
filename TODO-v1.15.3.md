# TODO: v1.15.3 - Config Hot-Reload, DAG Init & File Navigation

**Created:** 2026-02-07
**Branch:** bugfix/v1.15.3
**Status:** In Progress
**Previous Release:** v1.15.2

---

## Overview

Three workstreams for v1.15.3:

1. **Config Hot-Reload Fix** (Done) - Stale config cache fix for `/model`, `/provider`, session restore
2. **DAG-Based Config Initialization** (Planned) - Replace `__getattr__` lazy loading with explicit `initialize()` calls
3. **File Navigation** (Planned) - `/ls`, `/tree` commands + ppxaide interactive file tree sidebar

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

## 2. DAG-Based Config Initialization ⏳

**Priority:** High (tech debt)
**Status:** Planned
**Effort:** 0.5 days

### Problem

`ppxai/config/__init__.py` uses module-level `__getattr__` to lazily compute `PROVIDERS` and `MODELS`. This creates:

1. **No caching** - `PROVIDERS` is recomputed from ConfigStore on every access
2. **Snapshot staleness** - `EngineClient._providers_config = PROVIDERS` captures a dict at init that goes stale on reload
3. **Fragile workarounds** - Commands must re-import PROVIDERS after reload, call `_get_providers()` directly, or use dynamic imports

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

**File: `ppxai/config/__init__.py`**

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
    PROVIDERS = config.get("providers", {})
    MODELS = PROVIDERS.get("perplexity", {}).get("models", {})
    _initialized = True

def reload_config():
    """Reload config from disk and refresh module-level attributes."""
    ConfigStore.get_instance().reload()
    initialize()

# Remove __getattr__ entirely
```

#### Step 2: Simplify EngineClient - remove snapshot pattern

**File: `ppxai/engine/client.py`**

```python
# Remove: self._providers_config = PROVIDERS (snapshot)
# Add property that reads directly from config module:

@property
def providers_config(self):
    """Always returns current providers from config module."""
    from ..config import PROVIDERS
    return PROVIDERS

def reload_config(self):
    """Reload config from disk and refresh engine state."""
    from ..config import reload_config
    reload_config()  # Updates PROVIDERS/MODELS in place
    self._shell_config = get_shell_config()
    self._agent_config = get_agent_config()
```

#### Step 3: Remove workarounds from commands

**File: `ppxai/commands/provider.py`** - Remove post-reload re-import:
```python
# Before (workaround):
engine_client.reload_config()
from ..config import PROVIDERS  # re-import after reload

# After (clean):
engine_client.reload_config()
# PROVIDERS is already current
```

**File: `ppxai/tui/app.py`** - Remove dynamic import in session restore:
```python
# Before: dynamic import for freshness
# After: top-level import works fine
```

#### Step 4: Add `initialize()` calls at entry points

| Entry Point | File | Change |
|-------------|------|--------|
| Rich TUI | `ppxai/main.py` | Add `config.initialize()` at startup |
| Textual TUI | `ppxai/tui/app.py` | Add `config.initialize()` in `on_mount()` |
| HTTP server | `ppxai/server/http.py` | Add `config.initialize()` in startup |
| Desktop app | `ppxai/desktop/app.py` | Add `config.initialize()` at startup |

#### Step 5: Update all `self._providers_config` references

| File | Change |
|------|--------|
| `ppxai/engine/client.py` | `self._providers_config` -> `self.providers_config` (property) |
| `ppxai/commands/provider.py` | Use `engine.providers_config` or `from config import PROVIDERS` |
| `ppxai/tui/completer.py` | Top-level import unchanged (works now) |
| `ppxai/rich/main.py` | Top-level import unchanged |
| `ppxai/rich/ui.py` | Top-level import unchanged |

### Files Changed Summary

| File | Action | Lines |
|------|--------|-------|
| `ppxai/config/__init__.py` | Replace `__getattr__` with `initialize()` | ~20 lines |
| `ppxai/engine/client.py` | Remove snapshot, add property, simplify reload | ~25 lines |
| `ppxai/commands/provider.py` | Remove re-import workaround | ~5 lines |
| `ppxai/tui/app.py` | Add `init_config()`, remove dynamic imports | ~5 lines |
| `ppxai/server/http.py` | Add `init_config()` | ~2 lines |
| `ppxai/main.py` | Add `init_config()` | ~2 lines |

### Testing

- [ ] Test `config.initialize()` called at all 4 entry points
- [ ] Test `config.reload_config()` updates `PROVIDERS` and `MODELS` in place
- [ ] Test `EngineClient.providers_config` returns fresh data after reload
- [ ] Test `/provider list` shows correct providers after external config edit
- [ ] Test `/model list` shows correct models after external config edit
- [ ] Test session restore works with updated config
- [ ] Test top-level `from ppxai.config import PROVIDERS` returns current data
- [ ] Verify no `__getattr__` remains in `config/__init__.py`

### Migration Safety

- **Backward compatible**: `from ppxai.config import PROVIDERS` still works (real module var)
- **Fail-fast**: If `initialize()` not called, PROVIDERS is `{}` - fails early with clear error
- **Thread-safe**: ConfigStore.reload() is lock-protected; initialize() writes are atomic (GIL)
- **Tests**: Existing tests work - `initialize()` is idempotent, can be called in fixtures

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

## 4. Outstanding TODOs (Code-Level) ⏳

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

## Success Metrics

| Workstream | Metric | Target |
|------------|--------|--------|
| Config Hot-Reload | Config changes reflected without restart | ✅ Achieved |
| DAG Init | No `__getattr__` in config module, no snapshot workarounds | Pending |
| `/ls`, `/tree` | Commands work in all 3 clients | Pending |
| `/tree` perf | Completes in <2s on 10K file repo | Pending |
| ppxaide tree | File tree renders in <500ms for typical projects | Pending |
| ppxaide tree | Users can navigate without keyboard lag | Pending |

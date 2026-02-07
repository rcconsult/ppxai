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
**Status:** Audit Complete → Ready for Implementation
**Effort:** 0.5 days

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

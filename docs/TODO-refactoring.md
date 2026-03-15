# TODO: Technical Debt & Refactoring Plan

**Status:** In progress
**Priority:** Medium — address incrementally across v1.17.x releases
**Created:** 2026-03-15

---

## Overview

This document tracks structural refactoring opportunities identified through codebase analysis.
All items are non-functional improvements — the codebase works correctly but has accumulated
complexity in several key files that will slow future development if left unaddressed.

**Guiding principles:**
- Each refactoring is a standalone commit (no feature coupling)
- All existing tests must pass after each step
- No public API changes (HTTP endpoints, CLI commands, config schema)
- DAG-style imports — no circular dependencies, no deferred imports
- Measure twice, cut once — read the file before splitting it

---

## Completed

### ~~1. Split `server/http.py` (2,936 lines → 18 modules)~~

**Status:** DONE — 2026-03-15

Split into `server/{models,state,streaming}.py` + `server/routes/` (13 route modules).
`http.py` reduced to 372-line facade (app creation, lifespan, CLI entry points).

### ~~2. Consolidate `config/__init__.py` (943 lines → submodules)~~

**Status:** DONE — 2026-03-15

Split into `config/{providers,tools,features,paths,context,prompts}.py`.
`__init__.py` reduced to 262-line re-export hub. All circular imports eliminated
via clean DAG + reload callback pattern in `store.py`.

---

## 3. Unified AppState — Cross-Client State Management

**Priority:** HIGH — foundational change that enables items 4–7 and streamlines all clients.
**Target:** v1.17.1

### Problem

Application state is duplicated and managed differently in every client layer:

| Client | State location | State fields | Sync mechanism |
|--------|---------------|--------------|----------------|
| **EngineClient** | 60 `self.*` attrs on 1,588-line class | provider, model, tools, session, agent, checkpoints, consent, bootstrap, context | Direct mutation |
| **Textual TUI** | 15+ `self._*` fields on 2,303-line app | `_provider`, `_model`, `_is_streaming`, `_tools_enabled`, `_cancel_requested`, `_reasoning_*`, `_tool_group_*` | Manual badge updates, scattered `update_badge()` calls |
| **Rich TUI** | Fields on handler class | provider, model, streaming state | Manual status bar updates |
| **HTTP Server** | `SessionManager` + per-session `EngineClient` | Session isolation via dict lookup | Stateless endpoints read from engine |
| **Web App** | `AppState` (observable Proxy) | 20+ fields with `state.on()` observers | **Already solved** — centralized + reactive |
| **CommandContext** | Protocol with 12+ properties/methods | Delegates to engine + client-specific state | Each adapter (Rich/Textual/Server) re-implements |

Each client maintains its own shadow copy of provider/model/tools state, manually
syncing with `EngineClient`. When state changes (e.g., session restore), every client
must remember to update its local copies + UI badges + subtitle — leading to bugs
where one piece gets missed.

### Solution: `AppState` for Python

Port the web app's `AppState` pattern to Python. A single observable state object
shared between the engine and its client, with change notifications that auto-sync UI.

```python
# ppxai/state.py — shared across all Python clients

class AppState:
    """Observable application state with change notifications.

    All mutable session state lives here. Clients subscribe to changes
    instead of polling or manually syncing.

    Mirrors the web app's AppState (ppxai/web/shared/app-state.js) but
    uses Python descriptors instead of JS Proxy.
    """

    def __init__(self, initial: dict = None):
        self._data = dict(initial or {})
        self._listeners: dict[str, list[Callable]] = {}

    def __getattr__(self, key):
        if key.startswith('_'):
            return super().__getattribute__(key)
        return self._data.get(key)

    def __setattr__(self, key, value):
        if key.startswith('_'):
            super().__setattr__(key, value)
            return
        old = self._data.get(key)
        if old == value:
            return  # No-op dedup
        self._data[key] = value
        for fn in self._listeners.get(key, []):
            fn(value)

    def on(self, key: str, fn: Callable) -> "AppState":
        """Subscribe to changes on a state key."""
        self._listeners.setdefault(key, []).append(fn)
        return self

    def snapshot(self) -> dict:
        """Plain dict copy for debugging/serialization."""
        return dict(self._data)
```

### How It Flows

```
                    AppState (single source of truth)
                   ╱          │           ╲
          EngineClient    TUI/Rich App   HTTP endpoints
          (reads/writes)  (subscribes)   (reads)

State change example — session restore:
  1. engine.restore_session() updates AppState fields
  2. AppState notifies subscribers
  3. TUI: status_bar.update_badge() fires automatically
  4. TUI: self.sub_title updates automatically
  5. HTTP: next GET /status reads fresh values from AppState
  6. No manual sync code anywhere
```

### State Fields (unified across all clients)

```python
state = AppState({
    # Provider / model
    "provider": "perplexity",
    "model": "sonar-pro",

    # Tools
    "tools_enabled": False,
    "tools_verbose": False,
    "agent_mode": False,

    # Streaming
    "is_streaming": False,
    "cancel_requested": False,

    # Context
    "working_dir": "/path/to/project",
    "auto_inject": True,
    "bootstrap_loaded": False,

    # Session
    "session_name": None,
    "message_count": 0,

    # Reasoning (TUI-specific, ignored by server)
    "reasoning_active": False,

    # Tool groups (TUI-specific)
    "tool_group_active": False,
})
```

### Impact on Each Component

#### EngineClient (item 5)
- Replace 60 scattered `self.*` fields with `self.state = AppState({...})`
- Checkpoint/consent/bootstrap helpers receive `state` reference
- `restore_session()` updates `state.provider`, `state.model` etc. — subscribers notified

#### Textual TUI (item 7)
- Replace 15+ `self._*` fields with `self.state = engine.state`
- Register observers at mount time:
  ```python
  self.state.on("provider", lambda v: status_bar.update_badge("provider", v))
  self.state.on("model", lambda v: status_bar.update_badge("model", v))
  self.state.on("tools_enabled", lambda v: status_bar.update_badge("tools", "ON" if v else "OFF"))
  self.state.on("provider", lambda _: self._update_subtitle())
  self.state.on("model", lambda _: self._update_subtitle())
  ```
- Eliminates ~30 manual `update_badge()` / `self.sub_title =` calls

#### Rich TUI
- Same pattern — observers update Rich Live display

#### HTTP Server
- `GET /status` reads from `engine.state.snapshot()` — no per-field assembly
- Session restore response built from `state.snapshot()` subset

#### CommandContext (item 4)
- Protocol properties (`provider`, `model`, `tools_enabled`) delegate to `state`:
  ```python
  class TextualCommandContext:
      @property
      def provider(self) -> str:
          return self._state.provider
  ```
- Mixin becomes trivial since all contexts read from the same `AppState`

### Migration Steps

1. **Create `ppxai/state.py`** — `AppState` class with `__getattr__`/`__setattr__`
   override, `on()` subscription, `snapshot()`, no-op dedup on identical writes.

2. **Wire into `EngineClient`** — Add `self.state = AppState({...})` in `__init__`.
   Keep existing `self.*` properties as thin wrappers that read/write `state` (backward
   compat). Gradually remove the wrappers as clients migrate.

3. **Wire into Textual TUI** — Replace `self._provider` etc. with `self.state` observers.
   Remove manual badge update calls.

4. **Wire into Rich TUI** — Same pattern.

5. **Simplify CommandContext** — All 3 adapters delegate to `state` instead of
   re-implementing getters.

6. **HTTP endpoints already work** — They read from `EngineClient` which reads from `state`.

### Dependency Chain

This item is the **foundation** for all remaining items:

```
3. AppState (this item)
   ├── 4. CommandContext simplification (trivial once state exists)
   ├── 5. EngineClient decomposition (helpers share state instead of self)
   ├── 6. TUI modularization (delegates subscribe to state)
   └── 7. Event router pattern (handlers read state instead of passing context)
```

### Risk

- Medium — touches all clients, but migration is incremental (wrappers preserve
  backward compat during transition)
- AppState is proven — identical pattern already works in the web app

### Estimated Effort

~4 hours for AppState + EngineClient integration. TUI/Rich migration ~2 hours each.

---

## 4. Simplify CommandContext Adapters

**Priority:** MEDIUM — becomes trivial after AppState (item 3).
**Depends on:** Item 3 (AppState)

### Current State

3 CommandContext adapters (Rich, Textual, Server) each re-implement 12+ property/method
delegations to `EngineClient`. Most are identical boilerplate.

### Target

With AppState, all adapters delegate to the shared state object:

```python
class BaseCommandContext:
    """Common implementation for all command contexts."""

    def __init__(self, engine: EngineClient):
        self._engine = engine

    @property
    def engine_client(self): return self._engine
    @property
    def session(self): return self._engine.session
    @property
    def provider(self): return self._engine.state.provider
    @property
    def current_model(self): return self._engine.state.model
    @property
    def working_dir(self): return self._engine.state.working_dir
    @property
    def tools_enabled(self): return self._engine.state.tools_enabled

    def set_provider(self, p): self._engine.set_provider(p)
    def set_model(self, m): self._engine.set_model(m)
    def get_provider(self): return self._engine.state.provider
    def get_model(self): return self._engine.state.model
```

Client-specific adapters only add what's unique (e.g., Textual's `notify()` method).

### Estimated Effort

~30 minutes once AppState exists.

---

## 5. Decompose `engine/client.py` (1,588 lines)

**Priority:** MEDIUM — `EngineClient` is a god class with 60 methods.
**Depends on:** Item 3 (AppState)

### Target

Extract cohesive delegate classes that share `AppState`:

```
EngineClient (slim orchestrator, ~600 lines)
  ├── self.state: AppState              ← shared observable state
  ├── self.checkpoints: CheckpointOps   ← 8 methods, ~250 lines
  ├── self.consent: ConsentOps          ← 3 methods, ~200 lines
  ├── self.bootstrap: BootstrapOps      ← 5 methods, ~150 lines
  └── core: provider/model, chat, tools ← stays on EngineClient
```

Each delegate receives `state` (not `self`), making them testable in isolation.

### Estimated Effort

~2 hours once AppState exists.

---

## 6. Modularize `tui/app.py` (2,303 lines)

**Priority:** MEDIUM — elevated from LOW because AppState enables clean extraction.
**Depends on:** Item 3 (AppState)

### Target

```
ppxai/tui/
├── app.py                   # PPXAIDEApp — compose, mount, wire observers (~800 lines)
├── theme_manager.py         # Theme cycling, syntax theme mapping
├── key_router.py            # Centralized key binding dispatch
├── stream_handler.py        # Chat streaming event processing
└── widgets/                 # (existing, unchanged)
```

With AppState observers, extracted modules don't need 10+ parameters — they subscribe
to state changes directly.

### Estimated Effort

~3 hours once AppState exists.

---

## 7. Extract Event Router Pattern

**Priority:** LOW — cosmetic improvement, 45 instances across 7 files.
**Depends on:** None (independent), but benefits from AppState context.

### Assessment

Most if/elif chains are context-specific (each branch does different work). A strategy
dict adds indirection without reducing complexity. The only genuine candidate is
`rich/event_handler.py` with two ~15-branch chains.

**Recommendation:** Address opportunistically when touching affected files, not as a
dedicated refactoring pass.

### Estimated Effort

~45 minutes if scoped to `rich/event_handler.py` only.

---

## Implementation Order

Revised sequence — AppState is the foundation that unlocks everything else:

| Phase | Item | Priority | Effort | Depends On |
|-------|------|----------|--------|------------|
| ~~1~~ | ~~Server modularization (#1)~~ | ~~High~~ | ~~Done~~ | — |
| ~~2~~ | ~~Config submodules (#2)~~ | ~~High~~ | ~~Done~~ | — |
| 3 | **AppState — unified state management (#3)** | **High** | 4h | — |
| 4 | CommandContext simplification (#4) | Medium | 30min | #3 |
| 5 | EngineClient decomposition (#5) | Medium | 2h | #3 |
| 6 | TUI app modularization (#6) | Medium | 3h | #3 |
| 7 | Event router pattern (#7) | Low | 45min | — |

**Remaining effort:** ~10 hours across v1.17.x releases.

Phase 3 (AppState) is the critical path — it unblocks phases 4–6 and makes each
subsequent phase significantly simpler.

---

## Non-Goals

These are explicitly **not** part of this refactoring plan:

- **Web app (`app.js`)** — Already has `AppState` (v1.16.2). The Python `AppState` mirrors
  the same pattern for consistency.
- **Feature changes** — This plan is purely structural. No new endpoints, no behavior changes.
- **K8s deployment** — Tracked separately in `TODO-v1.17.0.md`.
- **Multi-model routing** — Tracked separately in `TODO-routing-v1.17.6.md`.
- **Test refactoring** — Tests work; don't fix what isn't broken.

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

### Solution: Separated Concerns — App State + Runtime Schemas

Two separate schemas with a uniform access pattern:

1. **App State Schema** (`ppxai-state.schema.yaml`) — what the app knows about itself.
   Same fields, same names, all clients. This is application logic.

2. **Runtime Schema(s)** (`ppxai-runtime-*.schema.yaml`) — how the app is deployed
   and what the deployment provides. This is infrastructure configuration that gets
   plugged into the state store for uniform `get()`/`set()` access.

3. **Packaging** — how we bundle the app (PyInstaller, Docker, VSIX). Build concern
   only. Not a state concern. Not in any schema.

The desktop web app and k8s web app are the **same app**. k8s just provides a
runtime environment that injects configuration (session manager URL, working dir,
LDAP endpoint). The glue code (session-manager sidecar, nginx BFF, ingress) is
deployment infrastructure — it doesn't change the app's state model.

```
┌──────────────────────────────────────────────┐
│  App State Schema (ppxai-state.schema.yaml)  │  ← application logic
│  currentProvider, currentModel, toolsEnabled │     same across ALL clients
│  isStreaming, agentMode, checkpointCount, ... │
└──────────────────────────────────────────────┘
         │ plugs into
         ▼
┌──────────────────────────────────────────────┐
│  AppState Store (generated per platform)     │  ← uniform public interface
│  get() / set() / on() / off() / update()     │     Python / JS / TS
│  snapshot()                                  │
└──────────────────────────────────────────────┘
         ▲ plugs into
         │
┌──────────────────────────────────────────────┐
│  Runtime Schema (optional, per deployment)   │  ← infrastructure config
│  k8s: sessionIsolation, maxSessions, ttl     │     injected at startup
│  vscode: webviewReady                        │
│  desktop: terminalProtocol                   │
└──────────────────────────────────────────────┘
```

#### App State Schema: `ppxai-state.schema.yaml`

The app state schema is the single source of truth for application-level state.
Every client gets every field. No per-platform conditionals.

**Naming convention:** Schema uses `camelCase`. Generator converts to `snake_case`
for Python. Names map 1:1 across codebases.

**Access convention:** Zero direct field access. All reads via `get()` or property
shorthand. All writes via `set()` or property shorthand. Both resolve to the same
internal mechanism that enforces dedup and fires observers.

```
# Python                             # JS / TS
state.get("current_provider")        state.get("currentProvider")
state.set("current_provider", "x")   state.set("currentProvider", "x")
state.current_provider               state.currentProvider          # shorthand
state.on("current_provider", fn)     state.on("currentProvider", fn)
state.off("current_provider", fn)    state.off("currentProvider", fn)
state.snapshot()                     state.snapshot()
state.update(current_provider="x",   state.update({currentProvider: "x",
             current_model="y")                    currentModel: "y"})
```

```yaml
# ppxai-state.schema.yaml — generates AppState for Python, JS, TS
version: "1.0"

fields:
  # --- Provider / Model ---
  currentProvider:       { type: string,  default: "perplexity" }
  currentModel:          { type: string,  default: "sonar-pro" }
  workingDir:            { type: string,  default: null, nullable: true }

  # --- Session ---
  sessionName:           { type: string,  default: null, nullable: true }
  messageCount:          { type: integer, default: 0 }

  # --- Tools ---
  toolsEnabled:          { type: boolean, default: false }
  toolsVerbose:          { type: boolean, default: false }
  agentMode:             { type: boolean, default: false }

  # --- Streaming ---
  isStreaming:            { type: boolean, default: false }
  cancelRequested:       { type: boolean, default: false }

  # --- Context ---
  autoInject:            { type: boolean, default: true }
  bootstrapLoaded:       { type: boolean, default: false }

  # --- Checkpoints ---
  lastCheckpoint:        { type: string,  default: null, nullable: true }
  checkpointCount:       { type: integer, default: 0 }

  # --- Usage ---
  usagePromptTokens:     { type: integer, default: 0 }
  usageCompletionTokens: { type: integer, default: 0 }
  usageCost:             { type: number,  default: 0.0 }

  # --- Debug ---
  debugLogEnabled:       { type: boolean, default: false }

# Feature groups — logical grouping for documentation and selective observation.
# All fields are always present in all clients. Groups are for wiring observers
# and for GET /status to return a coherent subset.
features:
  core:        [currentProvider, currentModel, workingDir, sessionName, messageCount]
  tools:       [toolsEnabled, toolsVerbose, agentMode]
  streaming:   [isStreaming, cancelRequested]
  context:     [autoInject, bootstrapLoaded]
  checkpoints: [lastCheckpoint, checkpointCount]
  usage:       [usagePromptTokens, usageCompletionTokens, usageCost]
  debug:       [debugLogEnabled]
```

#### Runtime Schemas (Separate Concern, Pluggable)

Runtime configuration is NOT app state. It's deployment infrastructure that the app
reads but doesn't own. Each runtime environment has its own schema that gets plugged
into the AppState store at startup for uniform `get()`/`set()` access.

```yaml
# ppxai-runtime-k8s.schema.yaml
version: "1.0"
description: "Kubernetes multi-user deployment"

fields:
  sessionIsolation:    { type: boolean, default: true }
  maxSessions:         { type: integer, default: 3 }
  ttlMinutes:          { type: integer, default: 10 }
  ldapEnabled:         { type: boolean, default: false }
  registryPath:        { type: string,  default: "/registry" }
```

```yaml
# ppxai-runtime-vscode.schema.yaml
version: "1.0"
description: "VSCode extension"

fields:
  webviewReady:        { type: boolean, default: false }
  extensionVersion:    { type: string,  default: "" }
```

```yaml
# ppxai-runtime-desktop.schema.yaml
version: "1.0"
description: "Desktop terminal TUI"

fields:
  terminalProtocol:    { type: string,  default: "auto", enum: [auto, sixel, iterm2, kitty] }
```

At startup, the client loads its runtime schema into the same store:

```python
# Desktop TUI startup
state = AppState()                                # Core app state from schema
state.load_runtime("ppxai-runtime-desktop")       # Adds terminalProtocol
# Access uniformly: state.get("terminal_protocol")
```

```javascript
// Web app startup (same app whether standalone or k8s)
const state = new AppState();                     // Core app state from schema
if (isK8sDeployment()) {
    state.loadRuntime('ppxai-runtime-k8s');        // Adds sessionIsolation, maxSessions, etc.
}
// Access uniformly: state.get("sessionIsolation") ?? false
```

The app code doesn't care where the runtime config came from. It calls
`state.get("sessionIsolation")` and gets `true` (k8s) or `undefined` (standalone).
The runtime schema just makes the field names and types explicit so they're
consistent across deployments.

#### Code Generation

```
ppxai-state.schema.yaml              (app state — always generated)
ppxai-runtime-*.schema.yaml          (runtime configs — generated per deployment)
         │
    scripts/generate-state.py
         │
         ├──→ ppxai/state.py                              (Python: thread-safe, async-friendly)
         ├──→ ppxai/web/shared/app-state.js                (JS: Proxy-based, replaces hand-written)
         └──→ vscode-extension/src/shared/appState.ts      (TS: typed interface + class)
```

Each generated file includes:
- All app state fields with platform-appropriate naming
- `get()`, `set()`, `on()`, `off()`, `snapshot()`, `update()` public interface
- `loadRuntime(name)` method to plug in runtime fields
- Property accessors as shorthand
- No-op dedup on identical writes
- `SCHEMA_VERSION` constant
- **Python only:** `threading.Lock` for writes, async listener dispatch
- **JS only:** `Proxy` traps
- **TS only:** `IAppState` interface with typed fields

#### Feature-Driven Development

Adding a new app state field:

1. **Add** to `ppxai-state.schema.yaml`
2. **Regenerate**: `python scripts/generate-state.py`
3. **Wire observers** where needed

Adding a new runtime setting:

1. **Add** to the relevant `ppxai-runtime-*.schema.yaml`
2. **Regenerate**
3. **Access** via `state.get("new_setting")` — works in any client that loads that runtime

#### Design Requirements

**Thread-safety:** ppxai runs in multiple threading/async contexts simultaneously:
- **Textual TUI** — Textual's event loop + worker threads for async engine calls
- **Rich TUI** — Main thread + asyncio event loop
- **HTTP Server** — uvicorn's async event loop + multiple concurrent requests per session
- **Session Manager** — Background idle monitor thread + async session cleanup

State reads and writes can happen from any of these contexts concurrently. The
implementation must guarantee:
- **Atomic reads** — No torn reads when one thread writes while another reads
- **Atomic writes** — No lost updates when concurrent writes race
- **Thread-safe listener dispatch** — Observers fire without corruption of the
  listener registry, even when `on()` is called from a different thread
- **No deadlocks** — Listener callbacks must not re-enter the lock (callbacks
  execute outside the write lock, or the lock is reentrant)

**Async-friendly:** State mutations happen inside `async def` methods (engine chat,
session restore, tool execution). The implementation must:
- **Never block the event loop** — No `threading.Lock.acquire()` in async code paths.
  Use `asyncio.Lock` for async contexts, or lock-free atomic patterns.
- **Support mixed sync/async listeners** — Engine writes state synchronously, but
  TUI observers may need to schedule Textual `call_from_thread()` or `app.post_message()`.
  Listeners should accept both sync and async callables.
- **Event loop awareness** — When a listener is an async coroutine, `AppState` should
  detect and schedule it on the running loop (`asyncio.create_task` or
  `loop.call_soon_threadsafe`) rather than calling it synchronously.

**Practical approach:** Two implementation strategies to evaluate:

1. **Lock-free with atomic dict reference** (preferred for reads):
   ```python
   # Writes: copy-on-write with threading.Lock for mutation only
   # Reads: direct dict access (atomic in CPython due to GIL, but
   #         explicitly safe via immutable snapshot swap)
   # Listeners: dispatched after lock release to prevent deadlocks
   ```

2. **RLock with sync/async dispatch**:
   ```python
   # RLock allows reentrant writes (listener triggers another write)
   # Async listeners scheduled via loop.call_soon_threadsafe()
   # Simpler but slightly higher contention
   ```

```python
# ppxai/state.py — GENERATED from ppxai-state.schema.yaml
# Do not edit by hand. Run: python scripts/generate-state.py

import asyncio
import threading
from typing import Any, Callable

SCHEMA_VERSION = "1.0"

Listener = Callable[[Any], Any]  # sync or async callable


class AppState:
    """Observable application state with change notifications.

    Thread-safe and async-friendly. All mutable session state lives here.
    Clients subscribe to changes instead of polling or manually syncing.

    Public interface (use these, never access _data directly):
      state.get("current_provider")          → read
      state.set("current_provider", "x")     → write (fires observers if changed)
      state.current_provider                 → shorthand read (via __getattr__)
      state.current_provider = "x"           → shorthand write (via __setattr__)
      state.on("current_provider", fn)       → subscribe
      state.off("current_provider", fn)      → unsubscribe
      state.update(current_provider="x", …)  → batch write
      state.snapshot()                       → dict copy

    Thread safety:
    - Writes serialized via threading.Lock
    - Reads are lock-free (atomic dict reference in CPython)
    - Listeners dispatched outside the lock (no deadlocks from re-entrant writes)
    - Listener registry mutations protected by the same lock

    Async safety:
    - Sync listeners called directly
    - Async listeners scheduled via asyncio.create_task() on running loop
    - Safe to call from both sync and async contexts
    """

    def __init__(self, initial: dict = None):
        self._data = dict(initial or {})
        self._listeners: dict[str, list[Listener]] = {}
        self._lock = threading.Lock()

    # === Public Interface ===

    def get(self, key: str, default: Any = None) -> Any:
        """Read a state field by name."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Write a state field by name. No-op if value unchanged. Fires observers."""
        listeners_to_call = []
        with self._lock:
            old = self._data.get(key)
            if old == value:
                return
            self._data[key] = value
            listeners_to_call = list(self._listeners.get(key, []))

        self._dispatch(listeners_to_call, value)

    def on(self, key: str, fn: Listener) -> "AppState":
        """Subscribe to changes on a state key. Accepts sync or async callables."""
        with self._lock:
            self._listeners.setdefault(key, []).append(fn)
        return self

    def off(self, key: str, fn: Listener) -> "AppState":
        """Unsubscribe from changes on a state key."""
        with self._lock:
            fns = self._listeners.get(key, [])
            if fn in fns:
                fns.remove(fn)
        return self

    def update(self, **kwargs) -> None:
        """Batch-update multiple fields. Observers fire once per changed field."""
        for key, value in kwargs.items():
            self.set(key, value)

    def snapshot(self) -> dict:
        """Plain dict copy for debugging/serialization. Lock-free read."""
        return dict(self._data)

    # === Property Shorthand (resolves to get/set) ===

    def __getattr__(self, key: str) -> Any:
        if key.startswith('_'):
            return super().__getattribute__(key)
        return self.get(key)

    def __setattr__(self, key: str, value: Any) -> None:
        if key.startswith('_'):
            super().__setattr__(key, value)
            return
        self.set(key, value)

    # === Internal ===

    def _dispatch(self, listeners: list[Listener], value: Any) -> None:
        """Dispatch listeners outside the lock."""
        for fn in listeners:
            if asyncio.iscoroutinefunction(fn):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(fn(value))
                except RuntimeError:
                    pass  # No running loop — skip async listener
            else:
                fn(value)
```

#### Event Bus Integration

Each platform already has an event bus:
- **Python (Textual):** `EventBus` with blinker signals (`ppxai/tui/event_bus.py`)
- **TypeScript (VSCode):** `ChatEventBus` with typed emit/on (`handlers/eventBus.ts`)
- **JavaScript (Web):** Direct callback wiring

AppState `on()`/`off()` handles state-change observation. The event bus handles
action/intent signals (user clicked, stream started, consent requested). These
are complementary — not competing:

- **Event bus:** "user selected a file" → handler decides what to do
- **AppState observer:** "currentModel changed" → badge auto-updates

Widget-local UI state (autocomplete dropdown, file tree selection, preview mode)
stays on the widget. Only app-level state flows through AppState.

#### Runtime Integration Notes

**Textual TUI:** AppState observers use `app.call_from_thread()` for cross-thread
UI updates. The existing `EventBus` (blinker-based) handles engine→UI events.

**FastAPI/Uvicorn:** State reads happen in async route handlers on the same event
loop — naturally safe. Multi-worker deployments (k8s) get per-process AppState
instances (same model as `ConfigStore`).

**Web App (standalone + k8s):** Same app. k8s deployment calls
`state.loadRuntime('ppxai-runtime-k8s')` at startup to inject session isolation
settings. The app code calls `state.get("sessionIsolation")` and gets `true` (k8s)
or `undefined` (standalone). No conditional code paths — just config.

**VSCode Extension:** Uses VS Code's native `EventEmitter` pattern alongside
AppState observers.

### How It Flows

```
                    AppState (single source of truth)
                   ╱          │           ╲
          EngineClient    TUI/Rich App   HTTP endpoints
          (set/update)    (on/get)        (get/snapshot)

State change example — session restore:
  1. engine.restore_session() calls state.update(
         current_provider="openai", current_model="gpt-4",
         tools_enabled=True, working_dir="/project")
  2. AppState fires observers for each changed field
  3. TUI: status_bar.update_badge("provider", ...) fires automatically
  4. TUI: self._update_subtitle() fires automatically
  5. HTTP: next GET /status calls state.snapshot() — fresh values
  6. No manual sync code anywhere
```

### Impact on Each Component

#### EngineClient (item 5)
- Replace 60 scattered `self.*` fields with `self.state = AppState({...})`
- All reads go through `self.state.get("current_provider")` or shorthand
  `self.state.current_provider`
- All writes go through `self.state.set("current_provider", "openai")` or
  `self.state.update(current_provider="openai", current_model="gpt-4")`
- Checkpoint/consent/bootstrap helpers receive `state` reference
- `restore_session()` uses `state.update()` for atomic multi-field transition

#### Textual TUI (item 6)
- Replace 15+ `self._*` fields — use `engine.state` directly
- Register observers at mount time via public `on()`:
  ```python
  engine.state.on("current_provider", lambda v: status_bar.update_badge("provider", v))
  engine.state.on("current_model", lambda v: status_bar.update_badge("model", v))
  engine.state.on("tools_enabled", lambda v: status_bar.update_badge("tools", "ON" if v else "OFF"))
  engine.state.on("current_provider", lambda _: self._update_subtitle())
  engine.state.on("current_model", lambda _: self._update_subtitle())
  ```
- Eliminates ~30 manual `update_badge()` / `self.sub_title =` calls
- Cleanup: `engine.state.off(...)` on widget unmount

#### Rich TUI
- Same pattern — observers update Rich Live display via `state.on()`

#### HTTP Server
- `GET /status` returns `engine.state.snapshot()` — no per-field assembly
- Session restore response built from `state.snapshot()` subset
- All reads via `state.get("current_provider")` — no direct field access

#### Web App (already has AppState — align to public interface)
- Replace `state.currentProvider` direct access with `state.get("currentProvider")`
  and `state.set("currentProvider", ...)` where explicit access is needed
- Property shorthand via Proxy still works but resolves to get/set internally
- Regenerate `app-state.js` from schema to guarantee field parity

#### VSCode Extension
- Replace `this.currentProvider` on `ConfigManager` with `state.get("currentProvider")`
- New generated `appState.ts` with typed `get<K>()` / `set<K>()` methods
- `EventEmitter` for observer pattern (VS Code convention)

#### CommandContext (item 4)
- All 3 adapters delegate to `state` via public interface:
  ```python
  class BaseCommandContext:
      @property
      def provider(self) -> str:
          return self._engine.state.get("current_provider")

      def set_provider(self, provider: str) -> None:
          self._engine.set_provider(provider)  # engine validates then calls state.set()
  ```
- Zero direct field access — read via `state.get()`, write via engine methods
  (engine validates before calling `state.set()`)

### Migration: Per-Client Phased Rollout

Each phase has its own detailed TODO with implementation steps, acceptance criteria,
and a lessons-learned section that carries forward to the next phase. This creates
a living architecture evidence trail.

| Phase | Client | Detailed Plan | Why This Order |
|-------|--------|---------------|----------------|
| 0 | Schema + Generator | [`TODO-appstate-0-schema.md`](TODO-appstate-0-schema.md) | Prerequisite — produces the foundation |
| 1 | Rich TUI | [`TODO-appstate-1-rich-tui.md`](TODO-appstate-1-rich-tui.md) | Simplest client (single thread, no event bus). Proves core works. |
| 2 | Textual TUI | [`TODO-appstate-2-textual-tui.md`](TODO-appstate-2-textual-tui.md) | Adds threading + async. Proves thread-safety + observers. |
| 3 | Desktop Web App | [`TODO-appstate-3-web-app.md`](TODO-appstate-3-web-app.md) | Cross-language (Python→JS). 200 Playwright tests as safety net. |
| 4 | VSCode Extension | [`TODO-appstate-4-vscode.md`](TODO-appstate-4-vscode.md) | Distinct codebase (TS). More unknowns than k8s. |
| 5 | k8s Web App | [`TODO-appstate-5-k8s.md`](TODO-appstate-5-k8s.md) | Same app as Phase 3 + `loadRuntime()`. Lightest phase. |

Each TODO includes:
- **Current state** — what exists today, what needs to change
- **Implementation steps** — ordered, concrete file-level changes
- **Acceptance criteria** — checkboxes for sign-off
- **What NOT to do** — scope guard to prevent overreach
- **Lessons learned** — filled during/after implementation, carried to next phase

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
- Thread safety is critical — engine writes from worker threads while TUI reads
  on the event loop. Must verify no deadlocks under Textual's threading model.
- Async listener dispatch needs careful testing — ensure `create_task()` doesn't
  fire on a closed loop during shutdown, and `call_from_thread()` doesn't race
  with Textual widget unmounting.

### Testing Requirements

- Unit tests: concurrent read/write from multiple threads (no torn reads)
- Unit tests: async listener dispatch from sync context (scheduled, not called)
- Unit tests: no-op dedup (identical write doesn't fire listeners)
- Unit tests: `off()` unsubscribe prevents stale listener calls
- Integration: Textual app with AppState observers (badge updates from worker thread)
- Integration: FastAPI route reading state while engine writes during SSE stream

### Estimated Effort

- App state schema: ~1 hour
- Runtime schemas (k8s, vscode, desktop): ~1 hour
- Generator (Python/JS/TS templates): ~3 hours
- Python AppState + EngineClient integration + thread-safety tests: ~4 hours
- JS AppState regeneration + Playwright verification: ~2 hours
- TS AppState + VSCode wiring: ~2 hours
- TUI/Rich migration to observers: ~2 hours each
- CI `--check` mode: ~30 minutes
- **Total: ~18 hours** (can be split across 4 sessions)

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
| 3a | **App state schema** (`ppxai-state.schema.yaml`) | **High** | 1h | — |
| 3b | **Runtime schemas** (`ppxai-runtime-{k8s,vscode,desktop}.schema.yaml`) | Medium | 1h | 3a |
| 3c | **Generator** (`scripts/generate-state.py` — Python/JS/TS templates) | **High** | 3h | 3a |
| 3d | **Python AppState** (generate + EngineClient integration + tests) | **High** | 4h | 3c |
| 3e | **JS AppState** (generate, replace hand-written, Playwright verification) | **High** | 2h | 3c |
| 3f | **TS AppState** (generate + VSCode wiring) | Medium | 2h | 3c |
| 4 | CommandContext simplification (#4) | Medium | 30min | 3d |
| 5 | EngineClient decomposition (#5) | Medium | 2h | 3d |
| 6 | TUI app modularization (#6) | Medium | 3h | 3d |
| 7 | Event router pattern (#7) | Low | 45min | — |

**Remaining effort:** ~20 hours across v1.17.x releases.

Phase 3a + 3c (app state schema + generator) is the critical path. 3d/3e/3f
can run in parallel once the generator exists. Runtime schemas (3b) are
independent and can be done anytime. Phases 4–6 plug into generated state.

---

## Non-Goals

These are explicitly **not** part of this refactoring plan:

- **Feature changes** — This plan is purely structural. No new endpoints, no behavior changes.
- **K8s infrastructure** — Session manager, nginx BFF, ingress. Tracked in `TODO-v1.17.0.md`.
  Phase 5 only verifies AppState + runtime schema integration, not infrastructure changes.
- **Multi-model routing** — Tracked separately in `TODO-routing-v1.17.6.md`.
- **Test refactoring** — Tests work; don't fix what isn't broken.
- **Web app restructuring** — `app.js` was already refactored in v1.16.2. Phase 3 is
  a drop-in AppState replacement + public interface enforcement, not a rewrite.

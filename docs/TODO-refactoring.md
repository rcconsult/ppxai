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

### Solution: Unified `AppState` — Schema-Driven, Cross-Platform

A single state schema defines all application state fields, their types, defaults,
and which client platforms use them. Code generators produce platform-specific
implementations (Python, JS, TS) from the schema, ensuring consistency across all
three codebases and enabling feature-driven plug-n-play development.

#### Schema File: `ppxai-state.schema.yaml`

The schema is the single source of truth. It defines a **unified field set** shared
by all clients. Every client gets every field — the difference is only in runtime
behavior (thread-safe locks in Python, Proxy in JS, EventEmitter in TS).

Widget-local UI state (autocomplete dropdown visibility, RightPanelFrame stack depth,
Textual theme index) does NOT belong in AppState. Those stay on the widget that owns
them. AppState holds only **application-level state** that multiple components need.

**Naming convention:** Schema uses `camelCase` field names. The generator applies
platform-appropriate casing:
- **JS/TS:** `camelCase` as-is → `state.currentProvider`
- **Python:** converted to `snake_case` → `state.current_provider`

The names must map 1:1 so a developer reading any codebase recognizes the same field.

**Access convention:** All state access goes through the public interface — **zero
direct field access**. The generated `AppState` enforces this:
- **JS/TS:** `state.get('currentProvider')` / `state.set('currentProvider', 'openai')`
  (Proxy shorthand `state.currentProvider` also works but resolves to get/set internally)
- **Python:** `state.get('current_provider')` / `state.set('current_provider', 'openai')`
  (property shorthand `state.current_provider` also works but resolves to get/set internally)

No client code ever reads `self._data['current_provider']` or writes to internal
storage directly. This enables the runtime to enforce dedup, fire observers, and
add validation/logging without client changes.

```yaml
# ppxai-state.schema.yaml — generates AppState for Python, JS, TS
version: "1.0"

# Unified field set — ALL clients get ALL fields.
# camelCase names are converted to snake_case for Python.
fields:
  # --- Provider / Model ---
  currentProvider:
    type: string
    default: "perplexity"
    description: "Active provider ID"

  currentModel:
    type: string
    default: "sonar-pro"
    description: "Active model ID"

  workingDir:
    type: string
    default: null
    nullable: true
    description: "Current working directory for file operations"

  # --- Session ---
  sessionName:
    type: string
    default: null
    nullable: true
    description: "Name of loaded session (null if unsaved)"

  messageCount:
    type: integer
    default: 0
    description: "Number of messages in current conversation"

  # --- Tools ---
  toolsEnabled:
    type: boolean
    default: false
    description: "Whether tool calling is active"

  toolsVerbose:
    type: boolean
    default: false
    description: "Verbose tool output logging"

  agentMode:
    type: boolean
    default: false
    description: "Autonomous agent mode"

  # --- Streaming ---
  isStreaming:
    type: boolean
    default: false
    description: "Chat response currently streaming"

  cancelRequested:
    type: boolean
    default: false
    description: "User requested stream cancellation"

  # --- Context ---
  autoInject:
    type: boolean
    default: true
    description: "Automatic @file/@git context injection"

  bootstrapLoaded:
    type: boolean
    default: false
    description: "AGENTS.md/CLAUDE.md bootstrap context loaded"

  # --- Checkpoints ---
  lastCheckpoint:
    type: string
    default: null
    nullable: true
    description: "ID of most recent checkpoint (git SHA or file ID)"

  checkpointCount:
    type: integer
    default: 0
    description: "Number of available checkpoints"

  # --- Usage ---
  usagePromptTokens:
    type: integer
    default: 0
    description: "Prompt tokens used in current session"

  usageCompletionTokens:
    type: integer
    default: 0
    description: "Completion tokens used in current session"

  usageCost:
    type: number
    default: 0.0
    description: "Estimated cost in USD for current session"

  # --- Debug ---
  debugLogEnabled:
    type: boolean
    default: false
    description: "Server debug logging active"

# Feature flags — enable/disable groups of fields per deployment target.
# Fields are always generated in all clients; flags control runtime behavior
# (e.g., whether observers are wired, whether fields are exposed in GET /status).
features:
  core:        [currentProvider, currentModel, workingDir, sessionName, messageCount]
  tools:       [toolsEnabled, toolsVerbose, agentMode]
  streaming:   [isStreaming, cancelRequested]
  context:     [autoInject, bootstrapLoaded]
  checkpoints: [lastCheckpoint, checkpointCount]
  usage:       [usagePromptTokens, usageCompletionTokens, usageCost]
  debug:       [debugLogEnabled]
```

#### Public Interface (Generated, All Platforms)

The generator produces identical method signatures across all three languages.
Client code MUST use these methods — no direct field access.

```
# Python                             # JS / TS
state.get("current_provider")        state.get("currentProvider")
state.set("current_provider", "x")   state.set("currentProvider", "x")
state.current_provider               state.currentProvider          # shorthand (resolves to get/set)
state.on("current_provider", fn)     state.on("currentProvider", fn)
state.off("current_provider", fn)    state.off("currentProvider", fn)
state.snapshot()                     state.snapshot()
state.update(current_provider="x",   state.update({currentProvider: "x",
             current_model="y")                    currentModel: "y"})
```

The `update()` method applies multiple field changes and fires observers only
once per changed field (not per `update()` call). This supports atomic multi-field
transitions like session restore where provider + model + tools must change together.

#### Code Generation

```
ppxai-state.schema.yaml
         │
    scripts/generate-state.py
         │
         ├──→ ppxai/state.py                              (Python: thread-safe, async-friendly)
         ├──→ ppxai/web/shared/app-state.js                (JS: Proxy-based, replaces hand-written)
         └──→ vscode-extension/src/shared/appState.ts      (TS: typed interface + class)
```

Each generated file includes:
- All fields from the schema with platform-appropriate naming
- `get()`, `set()`, `on()`, `off()`, `snapshot()`, `update()` public interface
- Property accessors as shorthand (Python `__getattr__`/`__setattr__`, JS Proxy,
  TS get/set accessors)
- No-op dedup on identical writes
- `SCHEMA_VERSION` constant for runtime compatibility checks
- **Python only:** `threading.Lock` for writes, async listener dispatch
- **JS only:** `Proxy` traps (existing pattern, now generated)
- **TS only:** `IAppState` interface with typed fields

#### Feature-Driven Development

Adding a new state field is a 3-step process:

1. **Define** in `ppxai-state.schema.yaml`:
   ```yaml
   fields:
     routingEnabled:
       type: boolean
       default: false
       description: "Cross-model routing active"
     routingMode:
       type: string
       default: "manual"
       enum: ["manual", "auto", "hybrid"]
       description: "Routing strategy"
   features:
     routing: [routingEnabled, routingMode]
   ```

2. **Regenerate**: `python scripts/generate-state.py`
   - Python gets `state.routing_enabled` / `state.routing_mode`
   - JS/TS gets `state.routingEnabled` / `state.routingMode`
   - All with correct types, defaults, observers

3. **Wire observers** in the clients that need reactivity.
   Other clients get the fields automatically (for GET /status, session
   serialize, etc.) even if they don't observe them.

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

#### Composable State: Core + Feature Slices + Runtime Settings

AppState is not a flat bag of fields. It's composed of three layers:

```
┌─────────────────────────────────────────────────────┐
│  Runtime Settings (injected at startup)              │
│  k8s: sessionIsolation, maxSessions, ttlMinutes     │
│  vscode: webviewReady, extensionVersion              │
│  web: themeStorage, commandHistory                   │
│  desktop: terminalProtocol                           │
├─────────────────────────────────────────────────────┤
│  Feature Slices (opt-in per deployment target)       │
│  fileTree: visible, currentPath, selectedItem        │
│  preview: active, filePath, viewMode                 │
│  autocomplete: visible, items, index                 │
│  reasoning: active, content                          │
├─────────────────────────────────────────────────────┤
│  Core State (always present, all clients)             │
│  currentProvider, currentModel, toolsEnabled, ...    │
└─────────────────────────────────────────────────────┘
```

**Core state** = the unified schema fields (provider, model, tools, streaming, etc.).
Always present in every client.

**Feature slices** = UI features that may or may not be active depending on the
deployment target. Each feature declares its state fields, events, and which runtimes
include it. A feature slice registers itself with AppState at startup — the core
AppState doesn't know about feature-specific fields until they're registered.

**Runtime settings** = deployment-specific configuration injected at startup. The k8s
web app has session isolation settings; VSCode has extension version tracking; the
desktop TUI has terminal protocol detection. These are just another feature slice
that happens to be runtime-specific.

#### Schema: Features as First-Class Composable Units

```yaml
# ppxai-state.schema.yaml
version: "1.0"

# ─── Core State (always present, all clients) ───
core:
  fields:
    currentProvider:  { type: string,  default: "perplexity" }
    currentModel:     { type: string,  default: "sonar-pro" }
    workingDir:       { type: string,  default: null, nullable: true }
    sessionName:      { type: string,  default: null, nullable: true }
    messageCount:     { type: integer, default: 0 }
    toolsEnabled:     { type: boolean, default: false }
    toolsVerbose:     { type: boolean, default: false }
    agentMode:        { type: boolean, default: false }
    isStreaming:       { type: boolean, default: false }
    cancelRequested:  { type: boolean, default: false }
    autoInject:       { type: boolean, default: true }
    bootstrapLoaded:  { type: boolean, default: false }
    lastCheckpoint:   { type: string,  default: null, nullable: true }
    checkpointCount:  { type: integer, default: 0 }
    usagePromptTokens:      { type: integer, default: 0 }
    usageCompletionTokens:  { type: integer, default: 0 }
    usageCost:               { type: number,  default: 0.0 }
    debugLogEnabled:  { type: boolean, default: false }

# ─── Feature Slices (composable, opt-in per runtime) ───
features:
  fileTree:
    description: "File browser panel"
    runtimes: [desktop, web, k8s]
    fields:
      fileTreeVisible:    { type: boolean, default: false }
      fileTreePath:       { type: string,  default: null, nullable: true }
      fileTreeSelected:   { type: string,  default: null, nullable: true }
    events:
      - fileTree:toggle
      - fileTree:navigate
      - fileTree:select

  preview:
    description: "File preview / editor panel"
    runtimes: [web, k8s]
    fields:
      previewActive:      { type: boolean, default: false }
      previewFilePath:    { type: string,  default: null, nullable: true }
      previewViewMode:    { type: string,  default: "rendered", enum: [rendered, source, split] }
    events:
      - preview:open
      - preview:close
      - preview:switchMode

  autocomplete:
    description: "Input autocomplete suggestions"
    runtimes: [web, k8s, desktop]
    fields:
      autocompleteVisible: { type: boolean, default: false }
      autocompleteIndex:   { type: integer, default: 0 }
    events:
      - autocomplete:show
      - autocomplete:hide
      - autocomplete:select

  reasoning:
    description: "Reasoning/thinking chunk display"
    runtimes: [desktop]
    fields:
      reasoningActive:    { type: boolean, default: false }
    events:
      - reasoning:start
      - reasoning:chunk
      - reasoning:end

  htmlPreview:
    description: "Live HTML preview with hot reload"
    runtimes: [web, k8s]
    fields:
      htmlPreviewActive:   { type: boolean, default: false }
      htmlPreviewFilepath: { type: string,  default: null, nullable: true }
    events:
      - htmlPreview:open
      - htmlPreview:close

# ─── Runtime Profiles ───
runtimes:
  desktop:
    description: "Textual/Rich terminal TUI"
    features: [fileTree, autocomplete, reasoning]
    settings:
      terminalProtocol:    { type: string,  default: "auto", enum: [auto, sixel, iterm2, kitty] }

  web:
    description: "Browser-based web app (standalone desktop-server)"
    features: [fileTree, preview, autocomplete, htmlPreview]
    settings:
      themeStorage:        { type: string,  default: "localStorage" }

  k8s:
    description: "Kubernetes multi-user deployment (same web components)"
    extends: web
    settings:
      sessionIsolation:    { type: boolean, default: true }
      maxSessions:         { type: integer, default: 3 }
      ttlMinutes:          { type: integer, default: 10 }
      ldapEnabled:         { type: boolean, default: false }

  vscode:
    description: "VSCode extension webview"
    features: []    # VSCode has its own tree, preview, etc.
    settings:
      webviewReady:        { type: boolean, default: false }
```

#### How Feature Slices Register

At startup, the runtime activates its features. The state store composes
itself from core + active feature slices + runtime settings:

```python
# Python — desktop TUI startup
from ppxai.state import AppState, load_feature, load_runtime

state = AppState()                           # Core fields only
load_feature(state, "fileTree")              # Adds fileTree.* fields
load_feature(state, "autocomplete")          # Adds autocomplete.* fields
load_feature(state, "reasoning")             # Adds reasoning.* fields
load_runtime(state, "desktop")              # Adds terminalProtocol setting
```

```javascript
// JS — web app startup
const state = new AppState();                // Core fields only
loadFeature(state, 'fileTree');              // Adds fileTree.* fields
loadFeature(state, 'preview');               // Adds preview.* fields
loadFeature(state, 'autocomplete');          // Adds autocomplete.* fields
loadFeature(state, 'htmlPreview');           // Adds htmlPreview.* fields
loadRuntime(state, 'web');                   // Adds themeStorage setting

// k8s deployment — same components, extra settings
loadRuntime(state, 'k8s');                   // Adds sessionIsolation, maxSessions, ttlMinutes
```

```typescript
// TS — VSCode extension startup
const state = new AppState();                // Core fields only
loadRuntime(state, 'vscode');               // Adds webviewReady setting
// No feature slices — VSCode has native tree, preview, etc.
```

#### Event Bus Integration

Each platform already has an event bus:
- **Python (Textual):** `EventBus` with blinker signals (`ppxai/tui/event_bus.py`)
- **TypeScript (VSCode):** `ChatEventBus` with typed emit/on (`handlers/eventBus.ts`)
- **JavaScript (Web):** CustomEvent dispatch or direct callback wiring

The schema's `events` field per feature generates event constants and typed
handler signatures for each platform. Features communicate through the bus,
not by reading/writing AppState directly:

```
User clicks file tree item
  → bus.emit("fileTree:select", { path: "src/main.py" })
  → fileTree handler: state.set("fileTreeSelected", "src/main.py")
  → preview handler (subscribed to fileTree:select): state.set("previewFilePath", "src/main.py")
  → AppState observer fires: preview panel renders the file
```

State changes are the **result** of event handling, not the event itself.
Events carry intent ("user selected a file"), state carries truth ("the selected
file is src/main.py"). This separation means:
- Features can react to each other's events without coupling
- The bus is the integration point, not shared mutable state
- A feature can be disabled by simply not registering its event handlers

#### Code Generation Output (Revised)

```
ppxai-state.schema.yaml
         │
    scripts/generate-state.py
         │
         ├──→ ppxai/state.py                  # AppState class + load_feature/load_runtime
         ├──→ ppxai/state_features.py          # Feature slice definitions (fields, defaults)
         ├──→ ppxai/state_events.py            # Event constants (like Events class today)
         │
         ├──→ ppxai/web/shared/app-state.js    # AppState + loadFeature/loadRuntime
         ├──→ ppxai/web/shared/state-features.js  # Feature slice definitions
         ├──→ ppxai/web/shared/state-events.js    # Event constants
         │
         ├──→ vscode-extension/src/shared/appState.ts      # AppState + loadFeature/loadRuntime
         ├──→ vscode-extension/src/shared/stateFeatures.ts  # Feature slice definitions
         └──→ vscode-extension/src/shared/stateEvents.ts    # Event type map (replaces hand-written)
```

#### Runtime Integration Notes

**Textual TUI:** AppState observers use `app.call_from_thread()` for cross-thread
UI updates. The existing `EventBus` (blinker-based) handles engine→UI events.
Feature slice event handlers subscribe via the same bus.

**FastAPI/Uvicorn:** State reads happen in async route handlers on the same event
loop — naturally safe. Multi-worker deployments (k8s) get per-process AppState
instances (same model as `ConfigStore`).

**Web App (standalone + k8s):** k8s deployment uses the exact same web components.
The difference is `loadRuntime(state, 'k8s')` which adds session isolation settings
and configures the API client to include session headers. The web app doesn't know
or care whether it's running standalone or in k8s — it just reads `state.get("sessionIsolation")`
and acts accordingly.

**VSCode Extension:** Uses VS Code's native `EventEmitter` pattern. The generated
`ChatEventBus` replaces the hand-written one with schema-generated event types.

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

### Migration Steps

1. **Write `ppxai-state.schema.yaml`** — Define all state fields across features
   and platforms. Start with fields already used in web app's `AppState`, TUI's
   `self._*` fields, and VSCode's `config.ts` fields.

2. **Write `scripts/generate-state.py`** — Schema-to-code generator that produces
   Python, JS, and TS implementations. Jinja2 templates or plain string formatting.

3. **Generate `ppxai/state.py`** — Replace hand-written AppState with generated
   version. Verify thread-safety and async listener dispatch with unit tests.

4. **Generate `ppxai/web/shared/app-state.js`** — Replace current hand-written
   `AppState` class. Run Playwright e2e tests (200 tests) to verify no regression.

5. **Generate `vscode-extension/src/shared/appState.ts`** — New file. Wire into
   `config.ts` to replace `currentProvider`/`currentModel` fields.

6. **Wire into `EngineClient`** — Add `self.state = AppState({...})` in `__init__`.
   Keep existing `self.*` properties as thin wrappers that read/write `state` (backward
   compat). Gradually remove the wrappers as clients migrate.

7. **Wire into Textual TUI** — Replace `self._provider` etc. with `self.state`
   observers. Remove manual badge update calls.

8. **Wire into Rich TUI** — Same pattern.

9. **Simplify CommandContext** — All 3 adapters delegate to `state` instead of
   re-implementing getters.

10. **HTTP endpoints already work** — They read from `EngineClient` which reads
    from `state`.

11. **Add to CI** — `generate-state.py --check` verifies generated files match
    schema (fails build if someone edits generated files by hand instead of updating
    the schema).

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

- Schema design (`ppxai-state.schema.yaml`): ~2 hours
- Generator (`scripts/generate-state.py` — Python/JS/TS templates): ~3 hours
- Python AppState + feature slices + EngineClient integration + tests: ~5 hours
- JS AppState regeneration + feature slices + Playwright verification: ~2 hours
- TS AppState + feature slices + VSCode wiring: ~3 hours
- Event constants generation + bus alignment: ~2 hours
- TUI/Rich migration to observers: ~2 hours each
- CI `--check` mode: ~30 minutes
- **Total: ~22 hours** (can be split across 4–5 sessions)

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
| 3a | **Schema** (`ppxai-state.schema.yaml` — core + features + runtimes) | **High** | 2h | — |
| 3b | **Generator** (`scripts/generate-state.py` — Python/JS/TS templates) | **High** | 3h | 3a |
| 3c | **Python AppState** (generate + feature slices + EngineClient + tests) | **High** | 5h | 3b |
| 3d | **JS AppState** (generate + feature slices + Playwright verification) | **High** | 2h | 3b |
| 3e | **TS AppState** (generate + feature slices + VSCode wiring) | Medium | 3h | 3b |
| 3f | **Event constants** (generate from schema, align with existing buses) | Medium | 2h | 3b |
| 4 | CommandContext simplification (#4) | Medium | 30min | 3c |
| 5 | EngineClient decomposition (#5) | Medium | 2h | 3c |
| 6 | TUI app modularization (#6) | Medium | 3h | 3c |
| 7 | Event router pattern (#7) | Low | 45min | — |

**Remaining effort:** ~23 hours across v1.17.x releases.

Phase 3a–3b (schema + generator) is the critical path. Once the generator exists,
3c/3d/3e can run in parallel. Phases 4–6 plug into the generated state naturally.

---

## Non-Goals

These are explicitly **not** part of this refactoring plan:

- **Web app (`app.js`)** — Already has `AppState` (v1.16.2). The Python `AppState` mirrors
  the same pattern for consistency.
- **Feature changes** — This plan is purely structural. No new endpoints, no behavior changes.
- **K8s deployment** — Tracked separately in `TODO-v1.17.0.md`.
- **Multi-model routing** — Tracked separately in `TODO-routing-v1.17.6.md`.
- **Test refactoring** — Tests work; don't fix what isn't broken.

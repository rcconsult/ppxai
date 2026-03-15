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

The schema is the single source of truth. Each field declares its type, default,
description, and which platforms consume it. Features group related fields and
can be enabled/disabled per deployment target.

```yaml
# ppxai-state.schema.yaml — generates AppState for Python, JS, TS
version: "1.0"

features:
  core:
    description: "Provider, model, session — required by all clients"
    platforms: [python, web, vscode]
    fields:
      provider:
        type: string
        default: "perplexity"
        description: "Active provider ID"
      model:
        type: string
        default: "sonar-pro"
        description: "Active model ID"
      working_dir:
        type: string
        default: null
        nullable: true
        description: "Current working directory for file operations"
      session_name:
        type: string
        default: null
        nullable: true
        description: "Name of loaded session (null if unsaved)"
      message_count:
        type: integer
        default: 0
        description: "Number of messages in current conversation"

  tools:
    description: "Tool calling and agent mode"
    platforms: [python, web, vscode]
    fields:
      tools_enabled:
        type: boolean
        default: false
      tools_verbose:
        type: boolean
        default: false
      agent_mode:
        type: boolean
        default: false

  streaming:
    description: "Chat streaming flow control"
    platforms: [python, web, vscode]
    fields:
      is_streaming:
        type: boolean
        default: false
      cancel_requested:
        type: boolean
        default: false

  context:
    description: "Context injection and bootstrap"
    platforms: [python, web]
    fields:
      auto_inject:
        type: boolean
        default: true
      bootstrap_loaded:
        type: boolean
        default: false

  checkpoints:
    description: "Checkpoint/undo support"
    platforms: [python, web, vscode]
    fields:
      last_checkpoint:
        type: string
        default: null
        nullable: true
      checkpoint_count:
        type: integer
        default: 0

  usage:
    description: "Token usage tracking"
    platforms: [python, web]
    fields:
      usage_prompt_tokens:
        type: integer
        default: 0
      usage_completion_tokens:
        type: integer
        default: 0
      usage_cost:
        type: number
        default: 0.0

  reasoning:
    description: "Reasoning/thinking display (TUI-specific)"
    platforms: [python]
    fields:
      reasoning_active:
        type: boolean
        default: false

  ui_web:
    description: "Web-only UI state"
    platforms: [web]
    fields:
      theme:
        type: string
        default: "dark"
      autocomplete_visible:
        type: boolean
        default: false
      html_preview_active:
        type: boolean
        default: false
      rpf_stack_size:
        type: integer
        default: 10
      rpf_active_title:
        type: string
        default: null
        nullable: true

  ui_vscode:
    description: "VSCode-only UI state"
    platforms: [vscode]
    fields:
      webview_ready:
        type: boolean
        default: false
```

#### Code Generation

```
ppxai-state.schema.yaml
         │
    scripts/generate-state.py
         │
         ├──→ ppxai/state.py            (Python: thread-safe, async-friendly AppState)
         ├──→ ppxai/web/shared/app-state.js   (JS: Proxy-based observable, replaces hand-written)
         └──→ vscode-extension/src/shared/appState.ts  (TS: typed interface + observable class)
```

The generator produces:
- **Python:** `AppState` class with typed fields, `__getattr__`/`__setattr__`,
  `threading.Lock`, async listener dispatch, `on()`/`off()` subscription
- **JavaScript:** `AppState` class with `Proxy` get/set traps, no-op dedup,
  `on()` subscription (replaces current hand-written `app-state.js`)
- **TypeScript:** `IAppState` interface with typed fields + `AppState` class
  implementing the observable pattern with `EventEmitter`

Each generated file includes:
- Only fields from features enabled for that platform
- Type-correct defaults
- A `SCHEMA_VERSION` constant for runtime compatibility checks
- A `snapshot()` method for serialization/debugging

#### Feature-Driven Development

Adding a new feature is a 3-step process:

1. **Define** in `ppxai-state.schema.yaml`:
   ```yaml
   features:
     multi_model_routing:
       description: "Cross-model routing (v1.17.6+)"
       platforms: [python, web]
       fields:
         routing_enabled:
           type: boolean
           default: false
         routing_mode:
           type: string
           default: "manual"
           enum: ["manual", "auto", "hybrid"]
         active_routing_table:
           type: string
           default: null
           nullable: true
   ```

2. **Regenerate**: `python scripts/generate-state.py`

3. **Use** — the field exists in Python and JS with correct types and defaults.
   Wire observers in the client that needs reactivity. Clients that don't enable
   the feature never see the fields.

#### Plug-n-Play Deployment Targets

The schema's `platforms` field enables deployment-specific builds:

```yaml
# k8s multi-user server: no TUI state, no VSCode state
deploy_targets:
  k8s-server:
    features: [core, tools, streaming, context, checkpoints, usage]

  # Desktop TUI: full feature set minus web/vscode UI
  desktop-tui:
    features: [core, tools, streaming, context, checkpoints, usage, reasoning]

  # Web app: full web feature set
  web-app:
    features: [core, tools, streaming, context, checkpoints, usage, ui_web]

  # VSCode extension: core + VSCode UI
  vscode:
    features: [core, tools, streaming, checkpoints, ui_vscode]
```

This means the k8s server binary doesn't carry TUI reasoning state, and the
VSCode extension doesn't carry web autocomplete state — each deployment target
gets exactly the state fields it needs.

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
# ppxai/state.py — shared across all Python clients

import asyncio
import threading
from typing import Any, Callable, Union

AsyncListener = Callable[[Any], Any]  # sync or async callable


class AppState:
    """Observable application state with change notifications.

    Thread-safe and async-friendly. All mutable session state lives here.
    Clients subscribe to changes instead of polling or manually syncing.

    Mirrors the web app's AppState (ppxai/web/shared/app-state.js) but
    adapted for Python's threading + asyncio model.

    Thread safety:
    - Writes are serialized via threading.Lock
    - Reads are lock-free (atomic dict reference in CPython)
    - Listeners are dispatched outside the lock to prevent deadlocks
    - Listener registry mutations are protected by the same lock

    Async safety:
    - Sync listeners called directly (for thread-local UI updates)
    - Async listeners scheduled via asyncio.create_task() if a running
      loop is detected, or loop.call_soon_threadsafe() from worker threads
    - Safe to call from both sync and async contexts
    """

    def __init__(self, initial: dict = None):
        self._data = dict(initial or {})
        self._listeners: dict[str, list[AsyncListener]] = {}
        self._lock = threading.Lock()

    def __getattr__(self, key):
        if key.startswith('_'):
            return super().__getattribute__(key)
        return self._data.get(key)

    def __setattr__(self, key, value):
        if key.startswith('_'):
            super().__setattr__(key, value)
            return
        # Serialize writes; dispatch listeners outside the lock
        listeners_to_call = []
        with self._lock:
            old = self._data.get(key)
            if old == value:
                return  # No-op dedup
            self._data[key] = value
            listeners_to_call = list(self._listeners.get(key, []))

        # Dispatch outside lock — prevents deadlocks from re-entrant writes
        for fn in listeners_to_call:
            if asyncio.iscoroutinefunction(fn):
                # Async listener: schedule on the running event loop
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(fn(value))
                except RuntimeError:
                    # No running loop (called from sync thread) — skip async listener
                    pass
            else:
                fn(value)

    def on(self, key: str, fn: AsyncListener) -> "AppState":
        """Subscribe to changes on a state key. Accepts sync or async callables."""
        with self._lock:
            self._listeners.setdefault(key, []).append(fn)
        return self

    def off(self, key: str, fn: AsyncListener) -> "AppState":
        """Unsubscribe from changes on a state key."""
        with self._lock:
            fns = self._listeners.get(key, [])
            if fn in fns:
                fns.remove(fn)
        return self

    def snapshot(self) -> dict:
        """Plain dict copy for debugging/serialization. Lock-free read."""
        return dict(self._data)

    def update(self, **kwargs) -> None:
        """Batch-update multiple fields. Listeners fire for each changed field."""
        for key, value in kwargs.items():
            setattr(self, key, value)
```

#### Textual Integration Note

Textual runs its own async event loop and uses `call_from_thread()` for cross-thread
communication. AppState listeners registered by the TUI should use Textual's
`app.call_from_thread()` to safely post UI updates:

```python
# In PPXAIDEApp.on_mount():
def _badge_updater(key, badge_fn):
    """Create a thread-safe listener that posts badge update to Textual."""
    def listener(value):
        self.call_from_thread(badge_fn, value)
    return listener

self.state.on("provider", _badge_updater("provider", lambda v: status_bar.update_badge("provider", v)))
self.state.on("model", _badge_updater("model", lambda v: status_bar.update_badge("model", v)))
```

This ensures badge updates always execute on Textual's event loop thread, even when
the engine writes state from a worker thread.

#### FastAPI/Uvicorn Integration Note

The HTTP server runs on uvicorn's asyncio event loop. State reads happen inside
`async def` route handlers — these are naturally safe since they run on the same
loop. State writes from the engine (e.g., during SSE streaming) happen within
`asyncio.Task`s on the same loop — also safe. No special integration needed beyond
the base `AppState` thread safety.

For multi-worker deployments (k8s with multiple uvicorn workers), each worker
process gets its own `AppState` instance — no cross-process synchronization needed
(same model as `ConfigStore`).

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

- Schema + generator: ~3 hours
- Python AppState + EngineClient integration + thread-safety tests: ~4 hours
- JS AppState regeneration + Playwright verification: ~1 hour
- TS AppState + VSCode wiring: ~2 hours
- TUI/Rich migration: ~2 hours each
- CI integration: ~30 minutes
- **Total: ~14 hours** (can be split across multiple sessions)

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
| 3a | **Schema + generator** (`ppxai-state.schema.yaml`, `scripts/generate-state.py`) | **High** | 3h | — |
| 3b | **Python AppState** (generate + EngineClient integration + tests) | **High** | 4h | 3a |
| 3c | **JS AppState** (regenerate from schema, replace hand-written) | **High** | 1h | 3a |
| 3d | **TS AppState** (generate + VSCode wiring) | Medium | 2h | 3a |
| 4 | CommandContext simplification (#4) | Medium | 30min | 3b |
| 5 | EngineClient decomposition (#5) | Medium | 2h | 3b |
| 6 | TUI app modularization (#6) | Medium | 3h | 3b |
| 7 | Event router pattern (#7) | Low | 45min | — |

**Remaining effort:** ~16 hours across v1.17.x releases.

Phase 3a (schema + generator) is the critical path — once the schema exists,
Python/JS/TS implementations can be generated in parallel. Phases 4–6 become
natural follow-ups that plug into the generated state.

---

## Non-Goals

These are explicitly **not** part of this refactoring plan:

- **Web app (`app.js`)** — Already has `AppState` (v1.16.2). The Python `AppState` mirrors
  the same pattern for consistency.
- **Feature changes** — This plan is purely structural. No new endpoints, no behavior changes.
- **K8s deployment** — Tracked separately in `TODO-v1.17.0.md`.
- **Multi-model routing** — Tracked separately in `TODO-routing-v1.17.6.md`.
- **Test refactoring** — Tests work; don't fix what isn't broken.

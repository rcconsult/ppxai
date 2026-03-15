# TODO: Technical Debt & Refactoring Plan

**Status:** Planning
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
- Measure twice, cut once — read the file before splitting it

---

## ~~1. Split `server/http.py` (2,936 lines → ~5 modules)~~

**Status:** DONE — completed 2026-03-15
**Priority:** HIGH — this is the single largest file and grows with every new endpoint.

### Current State

`ppxai/server/http.py` contains:
- 80+ route handlers (functions prefixed with `async def`)
- Request/response models (8 Pydantic `BaseModel` classes)
- SSE event generators (`sse_event_generator`, `sse_coding_task_generator`)
- Session management (`get_or_create_session`, `cleanup_expired_sessions`)
- File operations (`search_files`, `list_files`, `get_file_tree`, `write_file`, `read_file`)
- Static file serving (7 `serve_*` functions for web UI assets)
- Consent handlers (`http_consent_handler`, `http_shell_consent_handler`)
- Preview system (`preview_poll`, `preview_static`, `preview_html`)
- Checkpoint management (5 endpoints)
- Server lifecycle (`lifespan`, `run_server`, `run_desktop`, `_run_server_with_graceful_shutdown`)

### Target Structure

```
ppxai/server/
├── __init__.py              # (existing, unchanged)
├── __main__.py              # (existing, unchanged)
├── app.py                   # FastAPI app creation, lifespan, middleware, run_server/run_desktop
├── models.py                # All Pydantic request/response models
├── session_manager.py       # (existing, unchanged)
├── jsonrpc.py               # (existing, unchanged)
├── routes/
│   ├── __init__.py          # Router aggregation
│   ├── chat.py              # POST /chat, POST /coding-task, SSE generators
│   ├── providers.py         # GET/POST /providers, /models, /tools, /tools-config
│   ├── sessions.py          # GET/POST /sessions, /save, /load, /clear, /restore
│   ├── files.py             # POST /files/search, GET /files, /file-tree, /file, POST /file
│   ├── config.py            # GET /config/paths, /config/path, POST /config/reload
│   ├── usage.py             # GET/POST /usage, /usage/display-mode, /usage/report
│   ├── context.py           # GET/POST /working-dir, /auto-inject, /context, /bootstrap
│   ├── agent.py             # GET/POST /agent/status, /agent/config, /agent/enable|disable
│   ├── checkpoints.py       # GET/POST /checkpoints, /undo, /checkpoint-backend
│   ├── consent.py           # POST /consent, /shell-consent + handler functions
│   ├── preview.py           # GET /preview/*, serve_image
│   ├── commands.py          # POST /command (CommandFactory)
│   └── static.py            # serve_index, serve_app_js, serve_styles, serve_lib, favicon
└── streaming.py             # sse_event_generator, sse_coding_task_generator
```

### Migration Steps

1. **Create `server/models.py`** — Move all `BaseModel` classes (ChatRequest, CodingTaskRequest,
   SetProviderRequest, SetModelRequest, ToolsRequest, ToolsConfigRequest, WorkingDirRequest,
   AutoInjectRequest, ConsentRequest, ShellConsentRequest, FileReadRequest, FileSearchRequest,
   FileWriteRequest, CommandRequest, UsageDisplayModeRequest). Pure move, no logic changes.

2. **Create `server/streaming.py`** — Move `sse_event_generator()` and
   `sse_coding_task_generator()`. These are self-contained async generators that depend only
   on `EngineClient` and event types. Import `get_or_create_session` from the session module.

3. **Create `server/routes/` directory** — Start with the easiest, most self-contained groups:
   - `static.py` first (7 `serve_*` functions, zero business logic)
   - `config.py` next (3 endpoints, read-only)
   - `usage.py` (5 endpoints, isolated concern)
   - `checkpoints.py` (5 endpoints, isolated concern)
   - `preview.py` (3 endpoints + `serve_image` + `_extract_session_from_referer`)
   - Work toward larger groups: `files.py`, `providers.py`, `sessions.py`, `chat.py`

4. **Create `server/app.py`** — Move FastAPI app creation, `lifespan()`, middleware,
   `run_server()`, `run_desktop()`, `_run_server_with_graceful_shutdown()`. Import and
   `include_router()` for each route module.

5. **Update `server/__main__.py`** — Import `run_server` from `server.app` instead of
   `server.http`.

6. **Preserve `server/http.py` as re-export shim** (temporary) — For any external imports
   (e.g., `from ppxai.server.http import app`), add thin re-exports. Remove after verifying
   no consumers remain.

### Shared Dependencies (routes need access to)

Each route module will need:
- `get_or_create_session()` — from `server/app.py` or a shared `server/sessions.py`
- `update_activity()` — activity tracking
- `is_path_allowed()` — security check for file operations
- Session dict / lock management

**Approach:** Keep session state in `server/app.py` as module-level state, expose via
`get_session_state()` function that route modules import. This avoids circular imports
since routes depend on app state but app depends on routes only at registration time.

### Risk

- Medium — many routes share `get_or_create_session()` and session dict access
- Mitigate by extracting session access into a shared module first
- Test every endpoint after migration (Playwright e2e tests cover most routes)

### Estimated Effort

~3 hours for the full split. Can be done incrementally (models.py → streaming.py → routes/).

---

## ~~2. Consolidate `config/__init__.py` (943 lines → submodules)~~

**Status:** DONE — completed 2026-03-15
**Priority:** MEDIUM — 50+ flat functions make navigation difficult.

### Current State

`ppxai/config/__init__.py` has 50+ top-level `def` functions organized roughly by topic
but all in a single flat namespace. The module manages:
- Config loading/initialization (`_get_config`, `initialize`)
- Provider queries (`get_provider_config`, `get_api_key`, `get_base_url`, `get_provider_capabilities`)
- Model queries (`get_default_model`, `get_model_pricing`, `get_model_context_limit`, `get_model_max_tokens`, `get_generation_params`)
- Tool queries (`get_tool_config`, `get_tool_description_overrides`, `get_tool_pricing`, `get_tool_calling_config`)
- Path/data dir queries (`get_paths_config`, `get_bin_search_paths`, `get_data_dir`)
- Feature configs (`get_tui_config`, `get_session_config`, `get_shell_config`, `get_agent_config`, `get_server_config`, `get_context_config`, `get_bootstrap_config`)
- System prompt (`get_system_prompt`, `get_system_prompt_mode`)
- Cost calculation (`calculate_cost`)
- Validation (`validate_config`)

### Target Structure

```
ppxai/config/
├── __init__.py              # Re-exports all public functions (backward compat)
├── loader.py                # _get_config(), initialize(), get_config_source(), validate_config()
├── providers.py             # get_provider_config(), get_api_key(), get_base_url(),
│                            # get_provider_capabilities(), provider_needs_tool(),
│                            # get_available_providers(), get_default_provider()
├── models.py                # get_default_model(), get_active_models(), get_model_pricing(),
│                            # get_model_context_limit(), get_model_max_tokens(),
│                            # get_generation_params(), get_coding_model(), calculate_cost()
├── tools.py                 # get_tool_config(), get_tool_description_overrides(),
│                            # get_tool_pricing(), get_tool_calling_config()
├── paths.py                 # get_paths_config(), get_bin_search_paths(), get_data_dir(),
│                            # _expand_path_template(), get_server_config(), get_idle_timeout()
├── features.py              # get_tui_config(), get_tui_theme(), set_tui_config(),
│                            # get_session_config(), get_auto_restore_mode(),
│                            # get_auto_save_interval(), get_shell_config(), get_agent_config(),
│                            # get_visualization_config(), get_container_config()
├── context.py               # get_system_prompt(), get_system_prompt_mode(),
│                            # get_context_config(), get_bootstrap_config(),
│                            # get_bootstrap_files(), is_bootstrap_enabled(),
│                            # get_max_injection_size(), get_default_context_limit(),
│                            # get_context_warn_percent()
└── pricing.py               # get_active_pricing(), get_model_pricing() (if separate from models)
```

### Migration Steps

1. **Create `config/loader.py`** — Move `_get_config()`, `_get_providers()`, `_get_models()`,
   `initialize()`, `get_config_source()`, `validate_config()`. These are the foundation
   everything else depends on.

2. **Create submodules** in dependency order: `paths.py` → `providers.py` → `models.py` →
   `tools.py` → `features.py` → `context.py`. Each imports `_get_config` from `loader`.

3. **Update `config/__init__.py`** — Replace function definitions with re-exports:
   ```python
   from ppxai.config.loader import initialize, validate_config, get_config_source
   from ppxai.config.providers import get_provider_config, get_api_key, ...
   from ppxai.config.models import get_default_model, get_model_pricing, ...
   # etc.
   ```

4. **No external changes needed** — All consumers import from `ppxai.config`, which still
   exports everything at the same path.

### Risk

- Low — pure reorganization with re-exports preserving backward compatibility
- No circular imports since all submodules depend only on `loader`

### Estimated Effort

~1.5 hours. Mechanical move-and-re-export.

---

## 3. Extract Event Router Pattern

**Priority:** LOW — cosmetic improvement, reduces if/elif chains.

### Current State

Event dispatching uses sequential if/elif chains in 3 locations:
- `ppxai/rich/event_handler.py` — ~15 branches
- `ppxai/tui/app.py` — event processing in message handler
- `ppxai/server/http.py` — SSE event serialization in `sse_event_generator`

Pattern:
```python
if event.type == EventType.STREAM_CHUNK:
    handle_chunk(event)
elif event.type == EventType.STREAM_END:
    handle_end(event)
elif event.type == EventType.TOOL_CALL:
    handle_tool_call(event)
# ... 10+ more branches
```

### Target Pattern

Strategy dict with typed handlers:

```python
from typing import Callable, Dict
from ppxai.engine.types import Event, EventType

EventHandler = Callable[[Event], None]

EVENT_HANDLERS: Dict[EventType, EventHandler] = {
    EventType.STREAM_CHUNK: handle_chunk,
    EventType.STREAM_END: handle_end,
    EventType.TOOL_CALL: handle_tool_call,
    # ...
}

def dispatch_event(event: Event) -> None:
    handler = EVENT_HANDLERS.get(event.type)
    if handler:
        handler(event)
```

### Scope

- `ppxai/rich/event_handler.py` — Replace if/elif with dict dispatch
- `ppxai/server/http.py:sse_event_generator` — Replace if/elif with dict of SSE formatters
- `ppxai/tui/app.py` — Same pattern for TUI event processing

### Risk

- Very low — local refactoring, no API changes
- Each location is independent, can be done one at a time

### Estimated Effort

~45 minutes total (15 min per location).

---

## 4. Reduce Provider/Model Setter Boilerplate

**Priority:** LOW — protocol-based design is correct, but boilerplate is repetitive.

### Current State

`set_provider()`, `set_model()`, `get_provider()`, `get_model()` appear in 7+ files:
- `engine/client.py` (canonical implementation)
- `commands/protocol.py` (interface definition)
- `commands/handler.py` (delegates to context)
- `commands/context.py` (TUI/server adapters)
- `tui/app.py` (TUI implementation)
- `server/http.py` (HTTP endpoints)
- `server/jsonrpc.py` (JSON-RPC endpoints)

Most implementations are thin wrappers that delegate to `EngineClient`.

### Target

Extract a `ProviderModelMixin` or base class that provides the common delegation pattern:

```python
class ProviderModelMixin:
    """Mixin for classes that delegate provider/model ops to an EngineClient."""

    @property
    def _engine(self) -> EngineClient:
        raise NotImplementedError

    async def set_provider(self, provider: str) -> bool:
        return await self._engine.set_provider(provider)

    async def set_model(self, model: str) -> bool:
        return await self._engine.set_model(model)

    def get_provider(self) -> str:
        return self._engine.provider

    def get_model(self) -> str:
        return self._engine.model
```

### Scope

- Create `ppxai/commands/mixins.py` with `ProviderModelMixin`
- Apply to `commands/context.py` adapters (TUICommandContext, ServerCommandContext)
- HTTP/JSON-RPC routes remain as-is (they're FastAPI route functions, not classes)

### Risk

- Low — but benefit is marginal since the protocol pattern is intentional
- Only worth doing if the command context classes grow more shared methods

### Estimated Effort

~30 minutes if scoped to command contexts only.

---

## 5. Slim Down `engine/client.py` (1,588 lines)

**Priority:** MEDIUM — `EngineClient` is a god class with too many responsibilities.

### Current State

`EngineClient` (single class, 1,534 lines of methods) handles:
- Provider/model management (set_provider, set_model, get available providers/models)
- Session lifecycle (restore_session, save, load, clear, export)
- Chat orchestration (chat, chat_with_tools delegation)
- Tool management (set_tools, get_tools, tool config)
- Context injection (inject_context, clear_context, get_context_info)
- Bootstrap context (load_bootstrap, reload_bootstrap)
- Working directory management
- Usage tracking (get_usage, reset_usage)
- Agent mode (enable/disable/status)
- Checkpoint management (undo, list, clear, set backend)
- Debug logging

### Target Structure

Extract cohesive groups into helper classes that `EngineClient` composes:

```
ppxai/engine/
├── client.py                # EngineClient — thin facade, delegates to helpers
├── client_session.py        # SessionHelper — save, load, clear, export, restore_session
├── client_context.py        # ContextHelper — inject, clear, get_info, bootstrap
├── client_checkpoints.py    # CheckpointHelper — undo, list, clear, set_backend
├── chat.py                  # (existing, unchanged)
├── session.py               # (existing, unchanged — lower-level session storage)
└── ...
```

`EngineClient` becomes a composition root:

```python
class EngineClient:
    def __init__(self, ...):
        self._session = SessionHelper(self)
        self._context = ContextHelper(self)
        self._checkpoints = CheckpointHelper(self)

    # Thin delegations
    async def save_session(self, name): return await self._session.save(name)
    async def inject_context(self, path): return await self._context.inject(path)
    async def undo_checkpoint(self): return await self._checkpoints.undo()

    # Provider/model/chat stay on EngineClient (core responsibility)
```

### Migration Steps

1. **Extract `client_checkpoints.py`** first — most isolated group (5 methods, no
   cross-dependencies beyond `self.messages` and checkpoint storage)
2. **Extract `client_context.py`** — context injection, bootstrap loading (depends on
   `self.messages` and config)
3. **Extract `client_session.py`** — session save/load/restore (depends on provider,
   model, messages, tools — more coupled, do last)
4. **Keep on `EngineClient`:** provider/model management, chat orchestration, tool management,
   usage tracking (these are the core identity of the facade)

### Risk

- Medium — `restore_session()` is the canonical session restore and touches provider,
  model, tools, messages, and working directory. Must stay atomic.
- Mitigate: helpers receive a reference to `EngineClient` (not copies of its state)

### Estimated Effort

~2 hours. Extract checkpoints first as proof of concept, then context, then sessions.

---

## 6. Modularize `tui/app.py` (2,303 lines)

**Priority:** LOW — marked "works, just messy" in v1.17.0 TODO. Only address if adding
significant new TUI features.

### Current State

`PPXAIDEApp` handles layout, key bindings, event routing, theme management, status bar
updates, session management UI, side panel management, and command dispatch. Many concerns
are already partially extracted (file tree, input box, code editor, chat view as separate
widgets), but coordination logic remains in the app class.

### Target (if addressed)

```
ppxai/tui/
├── app.py                   # PPXAIDEApp — compose, mount, route events
├── theme_manager.py         # Theme cycling, APP_THEME_TO_SYNTAX mapping, watch_theme
├── key_router.py            # Centralized key binding dispatch (see TODO-v1.17.0.md)
├── message_handler.py       # on_message routing for custom Textual messages
└── widgets/                 # (existing, unchanged)
```

### Scope

- Extract theme management first (self-contained, ~150 lines)
- Key binding centralization is already tracked in `docs/TODO-v1.17.0.md`
- Message handler extraction depends on how many custom messages exist

### Risk

- Medium — Textual's reactive system (`watch_*` methods) must stay on the app class
- Theme watchers can be delegated but the `watch_theme` method itself stays on the app

### Estimated Effort

~2 hours for theme extraction. Key binding cleanup is a separate TODO item.

---

## Implementation Order

Recommended sequence, prioritized by risk/reward:

| Phase | Item | Priority | Effort | Can Ship Independently |
|-------|------|----------|--------|----------------------|
| ~~1~~ | ~~Config submodules (#2)~~ | ~~Medium~~ | ~~Done~~ | ~~Yes~~ |
| ~~2~~ | ~~Server models + streaming extraction (#1 steps 1-2)~~ | ~~High~~ | ~~Done~~ | ~~Yes~~ |
| ~~3~~ | ~~Server route split (#1 steps 3-5)~~ | ~~High~~ | ~~Done~~ | ~~Yes~~ |
| 4 | Engine client checkpoint/context extraction (#5) | Medium | 2h | Yes |
| 5 | Event router pattern (#3) | Low | 45min | Yes |
| 6 | Provider/model mixin (#4) | Low | 30min | Yes |
| 7 | TUI app modularization (#6) | Low | 2h | Yes |

**Total estimated effort:** ~10 hours across v1.17.x releases.

Each phase produces a clean commit that passes all tests. No phase depends on another.

---

## Non-Goals

These are explicitly **not** part of this refactoring plan:

- **Web app (`app.js`)** — Already refactored in v1.16.2 (api-client, command dispatcher,
  stream handler, editor controller extracted). Further splitting is diminishing returns.
- **Feature changes** — This plan is purely structural. No new endpoints, no behavior changes.
- **K8s deployment** — Tracked separately in `TODO-v1.17.0.md`.
- **Multi-model routing** — Tracked separately in `TODO-routing-v1.17.6.md`.
- **Test refactoring** — Tests work; don't fix what isn't broken.

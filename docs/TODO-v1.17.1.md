# TODO: v1.17.1 — Unified AppState + Code Streamlining

**Status:** Complete — all 14 items done
**Target:** v1.17.1
**Priority:** HIGH — validate AppState pattern, reduce complexity before routing (v1.17.2)

---

## Goal

Hand-craft a **single AppState interface** with identical fields and semantics
across all four clients (ppxai Rich TUI, ppxaide Textual TUI, Web app, VSCode
extension). No code generation — write each implementation manually to validate
the pattern and build empirical evidence that the schema+generator approach
will work in v1.18.x.

Alongside AppState, streamline server routes, constants, and adapters to reduce
duplication and improve maintainability.

**Success criteria:** All four clients use the same field names, types, and
observer pattern. Server routes use dependency injection. Magic numbers are
centralized.

---

## AppState Convergence

### ~~1. Define AppState interface + Python implementation~~ ✅

**Done.** `ppxai/engine/app_state.py` — thread-safe `AppState` class with
`on()`/`off()`/`get()`/`set()`/`update()`/`snapshot()`. 17 canonical fields.
Integrated in `EngineClient.state`, `commands/handler.py`, and Textual TUI.

### ~~2. Rich TUI — wire AppState~~ ✅

**Done.** Rich TUI now reads all core state through AppState:
- `get_status_line()` reads provider, model, tools_enabled, agent_mode, working_dir via
  handler properties (which delegate to `engine_client.state`)
- `restore_session_to_handler()` relies on `restore_session()` to update AppState
  atomically — no manual handler.provider/handler.current_model sync
- `stream_engine_response()` reads tools_verbose from AppState
- Derived data (checkpoint_status, usage_display, context_percentage) still uses
  engine_client method calls — these are computed on demand, not stored in AppState

### ~~3. Textual TUI — wire AppState~~ ✅

**Done.** 5 observers registered in `_initialize_engine()`: provider, model,
tools_enabled, tools_verbose, working_dir. Auto-updates status bar badges.

### ~~4. Web app — align AppState~~ ✅

**Done.** `ppxai/web/shared/app-state.js` — Proxy-based observable with aligned
field names. E2E tests in `tests/e2e/app-state.spec.ts`.

### ~~5. VSCode extension — align AppState~~ ✅

**Done.** `vscode-extension/src/appState.ts` — typed `AppStateFields` interface
with `get<K>()`/`set<K>()`/`on()`/`off()`/`update()`/`snapshot()`.

---

## File Decomposition

### ~~6. Decompose `engine/client.py`~~ ✅

**Done.** Extracted `checkpoint_ops.py`, `consent_ops.py`, `bootstrap_ops.py`.
`client.py` reduced to 955 lines (from 1,588).

### 7. Modularize `tui/app.py` — mostly done

**Mostly done.** Three modules extracted:
- `stream_handler.py` (425 lines) — engine event processing, tool/reasoning display
- `event_bus.py` (225 lines) — blinker-based pub/sub for Textual TUI
- `keys.py` (243 lines) — key binding registry (`get_app_bindings()`)

`app.py` reduced from 2,303 → 1,718 lines. Remaining inline: theme management
(`watch_theme()`, `action_cycle_theme()` — ~20 lines). A `theme_manager.py`
extraction is optional — the code is small and tightly coupled to Textual's
reactive `watch_theme()` pattern.

---

## Server Streamlining

### ~~8. Consolidate `reload_config()` calls~~ ✅

**Done.** Centralized in `server/state.py`'s `get_or_create_session()` (v1.17.1
consolidation). Only intentional reload in `/config/reload` endpoint remains.

### ~~9. Server route dependency injection~~ ✅

**Done.** All 13 route modules use `Depends(get_session)`. 65+ dependency injection
call sites. No manual `get_or_create_session()` in route handlers.

---

## Code Cleanup

### ~~10. Centralize constants~~ ✅

**Done.** `ppxai/constants.py` — `Default`, `ToolSetting`, `ConfigKey` classes.
`MAX_ITERATIONS=10`, `CONTEXT_CHAR_LIMIT=2000`, `IDLE_TIMEOUT=300`, etc.

### ~~11. CommandContext `__getattr__` proxy~~ ✅

**Done.** `ppxai/commands/context.py` — `_CommandContextProxy` base class (v1.17.1).
`RichCommandContext` and `TextualCommandContext` are 2-3 line stubs. 143 lines total.

---

## Dependency Graph

```
#1 Define AppState interface ✅
  ├→ #2 Rich TUI ✅
  ├→ #3 Textual TUI ✅
  ├→ #4 Web app ✅
  └→ #5 VSCode ✅

#6 EngineClient decompose ✅
#7 tui/app.py modularize ✅ mostly done (stream_handler + event_bus + keys extracted)

#8 reload_config consolidation ✅ ──→ #9 server dependency injection ✅

#10 constants ✅
#11 CommandContext proxy ✅
#12 chat_with_tools helpers ✅
#13 preview --serve ✅
#14 web terminal xterm.js ✅
```

## Effort Summary

| Item | Status | Hours |
|------|--------|------:|
| **AppState** | | |
| ~~Define interface + Python impl~~ | ✅ Done | — |
| ~~Rich TUI wire-up~~ | ✅ Done | — |
| ~~Textual TUI wire-up~~ | ✅ Done | — |
| ~~Web app align~~ | ✅ Done | — |
| ~~VSCode align~~ | ✅ Done | — |
| **Decomposition** | | |
| ~~EngineClient decompose~~ | ✅ Done | — |
| tui/app.py modularize | ✅ Mostly done | — |
| **Server** | | |
| ~~reload_config consolidation~~ | ✅ Done | — |
| ~~Server dependency injection~~ | ✅ Done | — |
| **Cleanup** | | |
| ~~Centralize constants~~ | ✅ Done | — |
| ~~CommandContext proxy~~ | ✅ Done | — |
| ~~chat_with_tools helpers~~ | ✅ Done | — |
| ~~preview --serve~~ | ✅ Done | — |
| ~~web terminal (xterm.js)~~ | ✅ Done | — |
| **Remaining** | | **0** |

---

## Code Review Graph Analysis (2026-03-22)

Graph stats: 5,800 nodes, 38,232 edges, 293 files (Python, JS, TS).

### Findings

**Test coverage gaps (94 changed functions untested):**
- ✅ Ops modules: `bootstrap_ops`, `checkpoint_ops`, `consent_ops`, `session_ops` — **73 tests added** (`tests/test_ops_modules.py`)
- ✅ Server routes: `reload_config`, `list_models`, `get_providers`, `export_answer` — **7 tests added** (`tests/test_server_routes.py`)
- Remaining gaps: scattered across server routes, TUI handlers — lower priority

**AppState import verification:**
- ✅ Verified wired correctly: `engine/client.py`, `tui/app.py` (15+ refs), `commands/handler.py` (12+ refs), 2 test files
- Graph showed 0 importers (IMPORTS_FROM edge resolution quirk, not a real gap)

**`chat_with_tools` decomposition (543 lines, largest function):**
- 6 clear phases: setup, provider call, tool parsing, tool execution, final response, max-iterations epilogue
- 3 duplicated blocks suitable for immediate extraction:
  - `_accumulate_tool_usage()` — lines 929–938 / 956–965
  - `_finalize_usage()` — lines 942–950 / 967–974
  - `_commit_and_signal()` — lines 916–926 / 978–989
- Larger phase extraction deferred — async generator yield/continue/return interleaving makes it risky without more integration tests
- Only 2 direct callers (both test helpers in `test_chat_profile_routing.py` and `test_tool_messages.py`)

### 12. Extract `chat_with_tools` helper functions (~1h)

- Extract 3 duplicated blocks into helpers (see above)
- ~50 lines of duplication removed, 6 call sites → 3
- Safe refactoring — no control flow changes

### 13. Preview `--serve` flag — full-stack preview (~4h)

Start user's backend process and preview through it instead of static file serving.

**Usage:** `/preview static/index.html --serve "python main.py"` or `--serve` (auto-detect)

**Server-side (3 files):**
- `state.py` — `PreviewBackend` dataclass (process, port, command, url) + session-keyed storage
- `models.py` — `PreviewServeRequest` model
- `routes/preview.py` — `POST /preview/serve` (start + port detect + health poll), `POST /preview/serve/stop`
- `http.py` — kill orphaned backends on server shutdown
- Port detection: regex stdout patterns + framework defaults (uvicorn=8000, express=3000, vite=5173)
- Use `asyncio.create_subprocess_exec` (not `subprocess.Popen`) to avoid blocking event loop
- Use `os.setsid` + `os.killpg` for process group cleanup (npm spawns child nodes)

**Client-side (3 files):**
- `command-dispatcher.js` — parse `--serve` / `--port` flags
- `api-client.js` — `startPreviewServe()` / `stopPreviewServe()`
- `app.js` — `openServedPreview()`, external URL iframe, stop on close

**UI additions:**
- Stop button in preview tab header (visible only in `--serve` mode)
- Process status badge: `⚡ running :8000`
- Auto-stop on `unmount()` + `beforeunload` fallback
- Server-side orphan watchdog: kill backends with no health check after 5 min TTL

**Safeguards:**
- One backend per session (kill previous before starting new)
- Skip reload script injection in `--serve` mode (backend has own hot-reload)
- iframe cross-port works (different ports allowed for iframe navigation)
- `unmount()` removes iframe from DOM to stop any leaked polling

### 14. Web terminal — xterm.js + PTY/K8s exec (~4h)

Lightweight terminal in the web app right panel, configurable shell via ppxai-config.json.

**Frontend (web/lib/ + BaseView):**
- `xterm.js` + `xterm.css` (~120KB minified, MIT) — terminal emulator
- `xterm-addon-fit.js` — auto-resize to container
- `xterm-addon-web-links.js` — clickable URLs (optional)
- Terminal as `BaseView` subclass in right panel frame
- Open via `/terminal` command or keyboard shortcut
- Multiple terminals supported (tab per terminal in RPF stack)

**Backend — local mode (routes/terminal.py):**
- `WS /ws/terminal` — WebSocket endpoint
- `pty.spawn()` (Python stdlib) for local shell
- Shell binary from `tools.shell.shell_bin` config, fallback to `$SHELL` or `/bin/sh`
- Login shell from `tools.shell.login_shell` config (sources profile for PATH/env)
- PTY resize on xterm fit events
- Working directory set to engine's current `working_dir`
- Clean process kill on WebSocket close / server shutdown

**Backend — K8s mode (routes/terminal.py):**
- Same WebSocket endpoint, different spawner
- `kubernetes.stream(v1.connect_get_namespaced_pod_exec(...))` — exec into pod
- Shell: `/bin/sh` or configurable per pod
- Session manager already has K8s SDK, reuse auth/namespace config
- Detect mode from env: `KUBERNETES_SERVICE_HOST` present → K8s exec

**Config (existing, no changes needed):**
```json
{
  "tools": {
    "shell": {
      "shell_bin": "/bin/zsh",
      "login_shell": true
    }
  }
}
```

**Nginx ingress (already configured):**
- `proxy-http-version: "1.1"` — required for WebSocket upgrade
- `proxy-read-timeout: "3600"` — long-lived connections
- WebSocket path: `/s/<user>/ws/terminal` → rewrite → `/ws/terminal`

**Platform notes:**
- macOS/Linux: `pty` module (stdlib), no extra deps
- Windows: needs `pywinpty` — defer to later
- K8s: `kubernetes` SDK already in deploy deps

---

## Deferred

- **v1.17.2:** Multi-model routing → `docs/TODO-routing-v1.17.2.md`
- **v1.18.x:** AppState schema+generator (YAML → Python/JS/TS codegen), error hierarchy, ConfigLoader DI, K8s AppState phase

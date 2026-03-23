# TODO: v1.17.1 — Unified AppState + Code Streamlining

**Status:** In progress
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

### 1. Define AppState interface + Python implementation (~3h)

- `ppxai/engine/app_state.py` — canonical `AppState` class
- Fields: `provider`, `model`, `tools_enabled`, `tools_verbose`, `working_dir`,
  `is_streaming`, `cancel_requested`, `session_id`, `session_name`,
  `total_tokens`, `prompt_tokens`, `completion_tokens`, `total_cost`,
  `context_percentage`, `auto_route`, `agent_iterations`, `reasoning_active`
- Observer pattern: `on(field, callback)`, `set(field, value)` triggers listeners
- Thread-safe: RLock for Python clients
- Reference: Web app's existing `AppState` (Proxy-based observable) as model

### 2. Rich TUI — wire AppState (~3h)

**Plan:** [`docs/TODO-appstate-1-rich-tui.md`](TODO-appstate-1-rich-tui.md)

- Simplest client — single thread, sync handlers
- Replace scattered state fields in EngineClient/event_handler with AppState
- Status bar reads from AppState observers instead of manual updates

### 3. Textual TUI — wire AppState (~3h)

**Plan:** [`docs/TODO-appstate-2-textual-tui.md`](TODO-appstate-2-textual-tui.md)

- Replace 15+ `self._*` shadow state fields with AppState observers
- Eliminate ~30 manual `update_badge()` calls
- Threading/async complexity — AppState must dispatch to correct event loop

### 4. Web app — align AppState (~2h)

**Plan:** [`docs/TODO-appstate-3-web-app.md`](TODO-appstate-3-web-app.md)

- Web app already HAS an observable AppState (Proxy-based)
- Align field names and types to match the Python canonical definition
- 200 Playwright E2E tests as safety net

### 5. VSCode extension — align AppState (~2h)

**Plan:** [`docs/TODO-appstate-4-vscode.md`](TODO-appstate-4-vscode.md)

- TypeScript interface matching the canonical fields
- Align with Web app's field names

---

## File Decomposition

### 6. Decompose `engine/client.py` (~2h)

**Plan:** `docs/TODO-refactoring.md` item #5

- Extract: `checkpoint_ops.py` (~250 lines), `consent_ops.py` (~200 lines), `bootstrap_ops.py` (~150 lines)
- EngineClient: ~600 lines (from 1,588)
- Easier after #2 since AppState absorbs some fields

### 7. Modularize `tui/app.py` (~3h)

**Plan:** `docs/TODO-refactoring.md` item #6

- Extract: `theme_manager.py`, `key_router.py`, `stream_handler.py`
- app.py: ~800 lines (from 2,303)
- Easier after #3 since AppState absorbs shadow state

---

## Server Streamlining

### 8. Consolidate `reload_config()` calls (~2h)

- 10+ redundant `engine.reload_config()` calls scattered across 13 route files
- Move to `get_or_create_session()` in `server/state.py` so reload happens once
- Some routes reload, others don't — make it consistent

### 9. Server route dependency injection (~2h)

- Every route starts with `session_id, engine, _ = await get_or_create_session(x_session_id)`
- Create FastAPI `Depends(get_engine)` dependency in `server/dependencies.py`
- Reduces boilerplate in all 13 route modules
- Standardize error responses (some routes raise HTTPException, others return error dicts)

---

## Code Cleanup

### 10. Centralize constants (~1h)

- `ppxai/constants.py` — single source of truth for magic numbers
- `AGENT_MAX_ITERATIONS` (currently 15 in manager.py, 20 in chat.py — which is it?)
- `TOOL_RESULT_CHAR_LIMIT`, `CHECKPOINT_KEEP_LAST`, `SESSION_TTL_SECONDS`
- Import everywhere instead of hardcoded values

### 11. CommandContext `__getattr__` proxy (~1h)

- Two 40-line adapter classes (Rich, Textual) with identical property forwarding
- Replace with 5-line `__getattr__` proxy base class
- All adapters delegate to wrapped object automatically

---

## Dependency Graph

```
#1 Define AppState interface
  ├→ #2 Rich TUI ──→ #6 EngineClient decompose
  ├→ #3 Textual TUI ──→ #7 tui/app.py modularize
  ├→ #4 Web app (align fields)
  └→ #5 VSCode (align fields)

#8 reload_config consolidation ──→ #9 server dependency injection

#10 constants (independent)
#11 CommandContext proxy (independent)
#12 chat_with_tools helpers (independent)
#13 preview --serve (independent) ✅ done
#14 web terminal xterm.js (independent)
```

## Estimated Effort

| Item | Hours |
|------|------:|
| **AppState** | |
| Define interface + Python impl | 3 |
| Rich TUI wire-up | 3 |
| Textual TUI wire-up | 3 |
| Web app align | 2 |
| VSCode align | 2 |
| **Decomposition** | |
| EngineClient decompose | 2 |
| tui/app.py modularize | 3 |
| **Server** | |
| reload_config consolidation | 2 |
| Server dependency injection | 2 |
| **Cleanup** | |
| Centralize constants | 1 |
| CommandContext proxy | 1 |
| chat_with_tools helpers | 1 |
| preview --serve | 4 |
| web terminal (xterm.js) | 4 |
| **Total** | **33** |

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

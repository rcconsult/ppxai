# Release Notes: v1.17.1

**Release Date:** 2026-03-23
**Branch:** feature/v1.17.1
**Focus:** AppState convergence, web terminal, preview hardening, server dependency injection, client.py decomposition

---

## Overview

v1.17.1 delivers the AppState architecture planned in v1.17.0's TODO series. A canonical observable
state object is wired into all four clients (EngineClient, Textual TUI, Web, VSCode), replacing
ad-hoc state tracking. The server gains FastAPI dependency injection and the engine client monolith
is decomposed into focused ops modules. A new web terminal (xterm.js + PTY WebSocket) provides
interactive shell access from all browser-based clients. The preview system is hardened with
`--serve`/`--proxy` flags, route collision fixes, and K8s ingress compatibility.

**Key Numbers:**
- 80 new tests (ops modules + server routes)
- 34 commits
- AppState wired into 4 clients with 243 dedicated unit tests

---

## New Features

### AppState — Canonical Observable State

`ppxai/engine/app_state.py` introduces a single source of truth for application state:

- **Observable fields**: provider, model, session_id, working_dir, tools_enabled, web_search,
  thinking_enabled, thinking_budget, token counts, cost, system prompt
- **`subscribe(field, callback)`** — register callbacks for specific field changes
- **`notify(field)`** — triggers all registered callbacks when a field changes
- **Wired into EngineClient** — state updates flow through AppState instead of ad-hoc attributes
- **Wired into CommandHandler** — `/provider`, `/model`, `/tools` commands update AppState
- **Wired into Textual TUI** — `PPXAIDEApp` subscribes to AppState for status bar updates
- **Wired into Web app** — `AppState` fields aligned with JS `appState` object
- **Wired into VSCode extension** — TypeScript `AppState` interface aligned with Python fields
- 243 unit tests covering subscribe/notify, field isolation, and edge cases

### Web Terminal (xterm.js + PTY)

Interactive terminal accessible from browser-based clients:

- **xterm.js frontend** — full terminal emulator in the web UI
- **PTY WebSocket backend** — server spawns pseudo-terminal, bridges I/O over WebSocket
- **Commands**: `/terminal`, `/term`, `/sh` — launch terminal from chat input
- **Event loop fd reader** — PTY output uses `loop.add_reader()` instead of polling threads
- HTTP middleware updated to skip WebSocket upgrade requests

### Preview Enhancements

- **`--serve` flag** — `ppxai-desktop` launches a backend process alongside the preview,
  enabling full-stack previews (frontend + API server)
- **`--proxy` flag** — K8s deployments can preview through the reverse proxy, routing
  API calls through the ingress path prefix
- **K8s ingress detection** — automatic path prefix injection for reverse proxy compatibility
- **Helpful 404** — when previewed HTML makes API calls to the preview server, returns an
  actionable error message instead of a generic 404

---

## Fixes

- **Preview route collision** — previewing files in `static/` directories no longer collides
  with FastAPI's static file mount
- **Preview absolute URLs** — poll and asset paths in subdirectories use absolute URLs
- **Preview python→python3** — macOS compatibility; backend stderr surfaced on failure
- **SSE keepalive 15s→5s** — prevents false disconnect detection in browsers with aggressive
  connection timeouts
- **Consent route crash** — undefined `x_session_id` variable caused 500 errors
- **Sessions route variable collision** — `get_sessions` route had a variable name collision
- **Web preview iframe** — URL encoding and sandbox warning fixes
- **Terminal WebSocket 403** — HTTP middleware was intercepting WebSocket upgrades
- **Lazy imports** — 5 remaining lazy imports moved to module level (DAG compliance)
- **Swallowed exceptions** — logging added to 8 previously silent exception handlers

---

## Refactoring

### Engine Client Decomposition

`ppxai/engine/client.py` split into focused ops modules:

- `session_ops.py` — session lifecycle (create, load, save, restore)
- `provider_ops.py` — provider/model switching, capabilities
- `tool_ops.py` — tool registration, enable/disable, consent
- `context_ops.py` — context injection, file handling, working directory
- `client.py` reduced to a facade that delegates to ops modules

### Server Dependency Injection

- Session resolution extracted from individual route handlers into FastAPI `Depends()` dependencies
- `reload_config` calls consolidated into `get_or_create_session` (single entry point)

### Code Streamlining

- **`stream_handler.py`** — stream handling logic extracted from Textual `app.py` (separation of concerns)
- **`constants.Default`** — magic numbers (keepalive interval, debounce delay, max retries, buffer sizes)
  centralized in a single enum
- **`CommandContext.__getattr__`** — adapter boilerplate in command handlers replaced with
  attribute proxy pattern, eliminating repetitive delegation methods

---

## Tests

- **80 new tests** covering ops modules (`session_ops`, `provider_ops`, `tool_ops`, `context_ops`)
  and server route handlers
- Test targets identified via code-review-graph analysis for maximum coverage impact
- AppState module includes 243 dedicated unit tests

---

## Upgrade Notes

- **No breaking changes** to HTTP API, CLI commands, or config schema
- **New WebSocket endpoint** at `/ws/terminal` — requires WebSocket-capable reverse proxy
  configuration if deploying behind nginx/ingress
- **AppState is additive** — existing state management continues to work; AppState provides
  an additional subscription-based notification layer

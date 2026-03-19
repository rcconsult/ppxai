# Release Notes: v1.17.0

**Release Date:** 2026-03-19
**Branch:** feature/v1.17.0
**Focus:** Server/config modularization, K8s deployment POC, key bindings registry, Textual 8.1.1, import DAG cleanup

---

## Overview

v1.17.0 is an architecture and infrastructure release. The server monolith (`http.py`, 2,936 lines) is
split into 13 route modules with shared state/models/streaming. The config monolith is split into 6
submodules. A Kubernetes deployment POC delivers session-isolated multi-user deployments with LDAP auth.
The TUI gets a centralized key binding registry, Textual is upgraded to 8.1.1, and the entire codebase
is cleaned of lazy imports and TYPE_CHECKING blocks using protocol-based dependency inversion.

**Key Numbers:**
- 1,647 unit tests passing (up from 1,639 in v1.16.2)
- 200 Playwright E2E tests passing
- 146 files changed, +13,118 / -5,682 lines vs v1.16.2

---

## New Features

### Server Modularization

`ppxai/server/http.py` (2,936 lines) split into focused modules:

- **13 route modules** under `ppxai/server/routes/`: agent, chat, checkpoints, commands, config,
  consent, context, files, preview, providers, sessions, static, usage
- **Shared modules**: `state.py` (session manager, utilities), `models.py` (Pydantic request/response),
  `streaming.py` (SSE event generators)
- `http.py` reduced to 372-line facade (app creation, lifespan, CLI entry points)

### Config Modularization

`ppxai/config/__init__.py` (943 lines) split into submodules:

- `providers.py` — provider, model, pricing, capabilities
- `tools.py` — tool, shell, agent, visualization, container config
- `features.py` — TUI and session config
- `paths.py` — paths, data dir, server config
- `prompts.py` — system prompts, context, bootstrap queries
- `context.py` — context injection, bootstrap configuration
- `__init__.py` reduced to 262-line re-export hub

### Kubernetes Deployment POC (Phases 1-5)

Multi-user K8s deployment with session isolation:

- **Phase 1**: Namespace, StorageClasses (ephemeral/workspace), in-cluster registry, Kaniko build jobs
- **Phase 2**: Dockerfile.server, nginx ingress, web URL path-prefix support
- **Phase 3**: Session Manager (FastAPI + k8s SDK) — create/delete/heartbeat/TTL watchdog
- **Phase 4**: Login Service (nginx + HTML/JS), dynamic sessions ingress
- **Phase 5**: LDAP auth module for session-manager
- Helm chart under `deploy/k8s/helm/ppxai/`
- Shared deploy configs under `deploy/shared/`

### Key Bindings Registry

Centralized key binding management for ppxaide TUI:

- **`ppxai/tui/keys.py`** — single source of truth for all keyboard shortcuts (32 key definitions)
- All widget `BINDINGS` generated via `get_widget_bindings()` from registry
- **`/keys` command** — shows all effective shortcuts at runtime
- **`/keys conflicts`** — documents known binding conflicts and resolution rules
- Display-only `ctrl+enter` hack replaced with explicit `action_noop()`

### Protocol-Based Dependency Inversion

Architectural pattern for breaking circular import chains:

- **`ToolEngineProtocol`** in `engine/types.py` — interface tools use for engine interaction
- **`ToolManagerProtocol`** in `engine/types.py` — interface for tool registration
- All 9 builtin tool modules migrated from TYPE_CHECKING to direct protocol imports
- Pattern documented in CLAUDE.md as recommended architecture

### Client Log Forwarding

- Server-side log forwarding from web/VSCode clients
- Web heartbeat watchdog for stale connection detection

### Benchmark: qwen2.5-coder-7b

- LM Studio evaluation: 69.4% without hints, 72.2% with AGENTS.md
- Multi-model routing architecture plan (`docs/TODO-routing-v1.17.6.md`)

---

## Fixes

- **Web streaming layout thrashing** — RAF-based rendering prevents layout recalculation storms
- **Preview panel freeze on display_file** — panel now properly handles concurrent file display requests
- **Preview URLs for reverse proxy** — all preview URLs are now relative (works behind ingress path prefix)
- **Stale session detection** — session manager verifies pod exists before returning "existing"
- **Tool fixes** — container.py and display.py error handling improvements

---

## Refactoring

### Lazy Import Cleanup

~70 lazy imports moved to top-level across 30+ files:

- Redundant stdlib imports (re, os, Path, asyncio inside functions that already had them at top)
- Unnecessary try/except guards on always-available modules (config, logger)
- Internal ppxai imports moved from function bodies to module level
- Test mock targets updated after import restructuring

### TYPE_CHECKING Elimination

All 14 `TYPE_CHECKING` blocks removed:

- 9 tool modules → protocol-based imports
- 6 command modules → dead import removal
- Remaining circular refs → `Any` for duck-typed adapters or direct imports where no cycle exists

### Textual 8.1.1 Upgrade

- Upgraded from 7.4.0 (DirectoryTree threading fixes, weak-ref DOM, GC improvements)
- textual-image 0.8.0 → 0.8.5

---

## Architecture Documentation

- `docs/TODO-appstate-{0..5}.md` — unified AppState architecture plan (6-part series)
- `docs/TODO-routing-v1.17.6.md` — multi-model routing architecture plan
- `docs/TODO-refactoring.md` — remaining tech debt tracker
- `docs/TODO-keybindings-cleanup.md` — key bindings implementation plan (completed)

---

## Upgrade Notes

- **No breaking changes** to HTTP API, CLI commands, or config schema
- **Textual 8.1.1** — `Select.BLANK` renamed to `Select.NULL` (not used by ppxai)
- **pyproject.toml** already allows Textual 8.x (`textual>=0.47.0`)
- K8s deployment requires colima or compatible k8s cluster (see `deploy/k8s/docs/`)

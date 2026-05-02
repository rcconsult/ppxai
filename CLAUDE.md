# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ppxai is a terminal-based UI application for interacting with multiple AI providers (Perplexity AI, OpenAI, OpenRouter, local models). It provides an interactive chat interface with model selection, conversation history, streaming responses, and AI-powered tools.

**Current Version:** v1.18.3

**Release state:** v1.18.2 tagged + published 2026-04-29. Active branch: `master`.
GitHub release: https://github.com/rcconsult/ppxai/releases/tag/v1.18.2 (15 assets:
13 binaries + 1 dmg + 1 vsix). 5 trigger-deferred items remain in
[docs/DEBT-INVENTORY-v1.18.2.md](docs/DEBT-INVENTORY-v1.18.2.md): Item 3 (k8s
session-manager security tests), Item 12 (Node.js 20 deprecation → bump
actions/* to v5), Item 13 (release.py step 15 silent-failure), Item 14
(Anthropic provider with TOS-aware auth fallback), Item 15 (deploy/shared/
AGENTS.md stale parallel copy). All trigger-deferred — pick up when their
forcing conditions hit.

**Major architectural patterns** — each has its own dedicated section below; respect these when changing code:
- **AppState** (v1.17.x) — observable state across all 4 clients (Python, JS, TS); SSE `state_sync` push; engine-owned invalidation via session callbacks. See "Cross-Client State Through AppState" below.
- **Engine ops decomposition** (v1.17.x) — `EngineClient` is a thin facade (~1058 LoC) over 6 ops modules in `engine/*_ops.py`. Same pattern applied to `tui/session_restore_ops.py` (v1.18.2 Item 1).
- **Server modularization** (v1.17.x) — `http.py` 411 lines + 17 route modules under `server/routes/`. DI via `Depends(get_session)`.
- **Command Dispatch via Envelope** (v1.18.1) — every slash command flows through `POST /command/<name>` returning `{ok, result, side_effects, events, version}`. See dedicated section below.
- **State-Sync Determinism** (v1.18.1) — Phases A-D: `/state` snapshot + visibility/focus re-anchor + REST event piggyback + `cwd_anchor` 409 mismatch. See dedicated section.
- **Agent Heartbeat Primitives** (v1.18.0) — `EventType.AGENT_BEAT` / `AGENT_RUN_START` / `AGENT_RUN_COMPLETE` / `AGENT_RUN_ERROR` / `AGENT_ZOMBIE` lifecycle events; zombie circuit-breaker via `tools.agent.zombie_threshold`. See [docs/ARCHITECTURE.md] §"Agent Heartbeat Primitives".
- **EngineClientProtocol** (v1.18.2 Item 10) — commands type against the protocol, not the concrete `EngineClient`. See [ppxai/engine/types.py].
- **CommandContext three-pattern split** (v1.18.2) — Rich uses Pattern A proxy, Textual passes `self`, Server uses Pattern B explicit. **Don't unify on speculation** — see [docs/decisions/0002-command-context-three-pattern-split.md].

**Capability surface (also documented in dedicated sections):**
- AppState schema DTO (`engine/app_state_schema.json`) — single source of truth for 4 clients; mirrors in `web/shared/app-state.js` + `vscode-extension/src/appState.ts`; cross-language sentinel tests.
- CompletionProvider engine layer (`engine/completion.py`) — single source of truth for autocomplete; clients are thin glue.
- File upload + multimodal — `/attach` command, SessionFileStore, file preprocessing, image validation, VL sidecar, PDF/Excel/PPTX/DOCX tools.
- `/doctor` config advisor — deprecation table, dead/deprecated/new/recommended model scanning.
- VSCode extension bundled via esbuild (v1.18.2 Item 5) — 128 KB VSIX (was 1.1 MB), 15 files (was 804); CI has 500 KB size-budget gate.

For per-version release notes, see [CHANGELOG.md](CHANGELOG.md) and `docs/RELEASE-NOTES-v*.md`.
For architecture decisions, see `docs/decisions/`.

## Codebase Statistics (v1.18.2, approximate)

| Language | Files | Lines |
|----------|------:|------:|
| Python (core) | ~175 | ~55,000 |
| Python (tests) | ~100 | ~38,000 |
| TypeScript (VSCode) | 19 | ~9,000 |
| JavaScript (Web) | 19 | ~9,400 |
| CSS | 6 | ~3,400 |
| **Total** | **~319** | **~115,000** |

Breakdown: ~81% Python, ~8% JavaScript, ~8% TypeScript, ~3% CSS

Tests: **3,067 passing**, 9 skipped (7 are Unix-only `TestKillPreviewBackend`
that can't `patch()` `os.getpgid`/`os.killpg` on Windows; the
`kill_preview_backend` Windows branch IS cross-platform and tested
separately).

## Installation Locations (CRITICAL)

**IMPORTANT: Follow these exact paths. NEVER use `AppData\Local\ppxai` on Windows.**

| Item | Linux | macOS | Windows |
|------|-------|-------|---------|
| **Binaries** | `~/.local/bin/` | `~/.local/bin/` | `~/.ppxai/bin/` |
| **App bundle** | - | `/Applications/ppxai.app` | - |
| **Config** | `~/.ppxai/ppxai-config.json` | `~/.ppxai/ppxai-config.json` | `~/.ppxai/ppxai-config.json` |
| **API keys** | `~/.ppxai/.env` | `~/.ppxai/.env` | `~/.ppxai/.env` |
| **Data** | `~/.ppxai/` | `~/.ppxai/` | `~/.ppxai/` |
| **Web UI** | `~/.ppxai/web/` | `~/.ppxai/web/` | `~/.ppxai/web/` |

**Windows structure (`%USERPROFILE%\.ppxai\`):**
```
~/.ppxai/
├── bin/                    # Binaries
│   ├── ppxai.exe          # TUI binary
│   ├── ppxai-server.exe   # Server binary
│   └── ppxai-desktop.exe  # Desktop app binary
├── web/                    # Web UI files (app.js, index.html, lib/)
│   ├── lib/               # JavaScript libraries (js-yaml, toml, hcl2-parser, etc.)
│   └── shared/            # Shared command definitions
├── sessions/              # Saved sessions
├── exports/               # Exported markdown files
├── checkpoints/           # File-based undo snapshots
├── logs/                  # Debug logs
├── usage/                 # Usage statistics
├── ppxai-config.json      # User configuration
└── .env                   # API keys
```

**Linux/macOS structure:**
```
~/.local/bin/
├── ppxai                   # TUI binary
├── ppxai-server            # Server binary
└── ppxai-desktop           # Desktop app binary

~/.ppxai/
├── web/                    # Web UI files
├── sessions/              # Saved sessions
├── exports/               # Exported markdown files
├── checkpoints/           # File-based undo snapshots
├── logs/                  # Debug logs
├── usage/                 # Usage statistics
├── ppxai-config.json      # User configuration
└── .env                   # API keys
```

**When deploying/copying files:**
- **Windows**: Use `~/.ppxai/bin/` for binaries, `~/.ppxai/` for data + web
- **Linux/macOS**: Use `~/.local/bin/` for binaries, `~/.ppxai/` for data + web

The `AppData\Local\ppxai` path exists only as a **search path** for finding binaries, NOT as an installation target.

## Development Setup

### File Encoding: UTF-8 without BOM

**IMPORTANT**: All source files MUST be UTF-8 encoded **without** BOM (Byte Order Mark).

- Windows PowerShell's `Out-File` cmdlet adds BOM by default - avoid using it
- Use `Set-Content -Encoding UTF8` or write files via Python with `encoding='utf-8'`
- The config loader uses `utf-8-sig` to handle BOM gracefully when reading

### uv Resolution (all platforms)

Always resolve `uv` the same way: use the system-installed binary if available,
otherwise bootstrap `.uv/uv` via the project script and use that.

**macOS / Linux:**
```bash
# One-time: resolve uv
command -v uv >/dev/null 2>&1 || python scripts/bootstrap.py --all
export UV=$(command -v uv 2>/dev/null || echo ".uv/uv")

# All subsequent commands use $UV:
$UV sync --all-extras
$UV run ppxai
$UV run pytest tests/ -v
```

**Windows (cmd):**
```cmd
where uv >nul 2>&1 && set UV=uv || (python scripts\bootstrap.py --all && set UV=.uv\uv)
%UV% sync --all-extras
%UV% run ppxai
```

**Windows (PowerShell):**
```powershell
if (Get-Command uv -ErrorAction SilentlyContinue) { $UV = "uv" } else { python scripts\bootstrap.py --all; $UV = ".uv\uv" }
& $UV sync --all-extras
& $UV run ppxai
```

Once `$UV` (or `%UV%`) is set, all `uv` commands below use the same variable.

### Quick Start with uv (recommended)

```bash
# Step 1: resolve uv (system or bootstrapped)
command -v uv >/dev/null 2>&1 || python scripts/bootstrap.py --all
export UV=$(command -v uv 2>/dev/null || echo ".uv/uv")

# Step 2: set up project
$UV sync --all-extras

# Step 3: configure API keys
cp .env.example .env
# Edit .env and add your API keys

# Step 4: run
$UV run ppxai           # Rich TUI
$UV run ppxaide         # Textual TUI
$UV run ppxai-server    # HTTP server for VSCode

# Step 5: test
$UV run pytest tests/ -v
```

### Alternative: pip

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python ppxai.py
```

## Windows Store Python + uv/venv Recovery (CRITICAL)

**Problem:** Windows Store Python prevents uv from creating temporary virtualenvs (Error 1920: "The file cannot be accessed by the system")

### Using Existing venv with `$UV run`
```bash
# ✅ Use --no-sync to skip package rebuild
$UV run --no-sync python -m <command>

# ❌ Without --no-sync triggers temp virtualenv creation (fails on Windows Store Python)
$UV run python -m <command>
```

### Checking venv/lock Status
```bash
# Check if lock file is up to date
$UV lock --check

# Check installed package version
$UV pip list | grep ppxai

# Verify runtime version
.venv/Scripts/python.exe -c "import ppxai; print(ppxai.__version__)"
```

### Corporate Proxy / TLS (CRITICAL)
```bash
# ✅ Use UV_NATIVE_TLS=true to use Windows native TLS (SChannel) - trusts system cert store
set UV_NATIVE_TLS=true   # cmd
$env:UV_NATIVE_TLS="true"  # PowerShell

# Then all uv commands work without SSL_CERT_FILE:
$UV run python -m PyInstaller ppxai.spec --noconfirm
$UV pip install hatchling editables
```
**Why:** `UV_NATIVE_TLS=true` tells uv to use the OS native TLS stack (Windows SChannel) instead of bundled rustls. This automatically trusts certificates from the Windows certificate store (including corporate proxy CAs). No need for `SSL_CERT_FILE`.

### Refreshing Package Metadata (After Version Bump)
When version numbers change in source but venv metadata is stale:

```bash
# 1. Install build dependencies in venv
$UV pip install hatchling editables

# 2. Reinstall package with --no-build-isolation
$UV pip install --no-build-isolation --reinstall --no-deps -e .

# 3. Verify metadata updated
$UV pip list | grep ppxai  # Should show new version
```

### Building Binaries with PyInstaller
```bash
# ✅ Preferred: use UV_NATIVE_TLS for corporate proxy environments
set UV_NATIVE_TLS=true && %UV% run python -m PyInstaller ppxai.spec --noconfirm

# Alternative: use venv's Python directly
.venv/Scripts/python.exe -m PyInstaller ppxai.spec --noconfirm
```

### Key Insights
- **Editable install:** Changes to source files (`.py`) are reflected immediately without reinstall
- **Metadata stale:** Package metadata (version, dependencies) requires reinstall to update
- **Lock file:** Only needs refresh when pyproject.toml dependencies change, not for source code changes
- **Windows Store Python:** Fundamental limitation - uv cannot create temp virtualenvs from Store Python executables
- **UV_NATIVE_TLS:** Preferred over SSL_CERT_FILE - uses OS native TLS, no hardcoded cert paths
- **Workaround:** Use existing venv with `--no-sync` or `.venv/Scripts/python.exe` directly

## Architecture

Layered architecture with clear separation of concerns:

```
ppxai/
├── engine/              # Core business logic (no UI)
│   ├── client.py        # EngineClient facade (restore_session() is canonical session restore)
│   ├── types.py         # Message, Event, UsageStats
│   ├── session.py       # Session management
│   ├── session_store.py # SessionFileStore — content-addressed file storage for uploads
│   ├── file_preprocessing.py  # Central file dispatcher (images/text/PDF/Office)
│   ├── image_validation.py    # Magic-byte sniffing, size/dimension limits, token estimation
│   ├── model_deprecations.py  # Deprecation table for /doctor command
│   ├── model_profiles.py      # ModelProfile registry with supports_vision flag
│   ├── providers/       # Perplexity, OpenAI-compat (BaseProvider ABC)
│   └── tools/           # Tool system + builtins (incl. pdf_tools.py)
├── server/              # HTTP/SSE server for IDE
│   ├── http.py          # FastAPI app, lifespan, CLI entry points (run_server, run_desktop)
│   ├── models.py        # Pydantic request/response models
│   ├── state.py         # Shared server state (session manager, utilities)
│   ├── streaming.py     # SSE event generators
│   └── routes/          # Route modules (chat, providers, files, sessions, etc.)
├── tui/
│   ├── keys.py          # Key binding registry — single source of truth for all shortcuts
│   └── widgets/
│       └── file_tree.py # FileTree widget — Norton Commander browser (Ctrl+B, @file inject)
├── main.py              # TUI entry point
├── commands.py          # Slash command handlers
├── commands/            # Command modules (attach.py, doctor.py, etc.)
└── config/              # Configuration system
    ├── __init__.py      # Re-exports (backward compat)
    ├── providers.py     # Provider, model, pricing, capabilities
    ├── tools.py         # Tool, shell, agent, visualization, container
    ├── features.py      # TUI and session config
    ├── paths.py         # Paths, data dir, server config
    └── prompts.py       # System prompts, context, bootstrap

vscode-extension/        # TypeScript VSCode extension
├── src/
│   ├── extension.ts     # Entry point
│   ├── httpClient.ts    # HTTP + SSE client
│   ├── chatPanel.ts     # Webview chat UI
│   └── handlers/        # Extracted handlers (Phase 2-4)
│       ├── eventBus.ts  # Pub/sub communication
│       ├── stream.ts    # Stream event processing
│       ├── consent.ts   # Consent dialog handlers
│       └── agentStateMachine.ts  # Agent loop state
├── media/webview/       # External CSS/JS (Phase 1)
└── package.json
```

### Configuration Files

| File | Purpose | Git |
|------|---------|-----|
| `.env` | API keys (secrets) | ❌ Never commit |
| `ppxai-config.json` | Provider definitions | ✅ Can commit |

## Common Commands

```bash
# Resolve uv first (see "uv Resolution" section above)
export UV=$(command -v uv 2>/dev/null || echo ".uv/uv")   # macOS/Linux
# set UV=uv || set UV=.uv\uv                               # Windows cmd

# Run application
$UV run ppxai                    # Rich TUI
$UV run ppxaide                  # Textual TUI (syntax highlighting, file tree)
$UV run ppxai-server             # HTTP server for VSCode
$UV run ppxai-desktop            # Desktop web app

# Testing
$UV run pytest tests/ -v
# Some tests import ppxai.tui which requires blinker (not always installed).
# If collection fails with "No module named 'blinker'", exclude TUI tests:
$UV run pytest tests/ -q $(python3 -c "import subprocess; r=subprocess.run(['grep','-rl','from ppxai.tui','tests/'],capture_output=True,text=True); files=r.stdout.strip().split('\n'); print(' '.join(['--ignore='+f for f in files if f]))")

# Build binaries (macOS/Linux — all four in parallel)
$UV run pyinstaller ppxai.spec --noconfirm
$UV run pyinstaller ppxaide.spec --noconfirm
$UV run pyinstaller ppxai-server.spec --noconfirm
$UV run pyinstaller ppxai-desktop.spec --noconfirm

# Build binaries (Windows with corporate proxy)
set UV_NATIVE_TLS=true && %UV% run pyinstaller ppxai.spec --noconfirm

# Build VSCode extension
cd vscode-extension && npm run compile && npx vsce package --allow-missing-repository

# Create macOS DMG
bash scripts/create-macos-app.sh

# Copy beta binaries to external drive (Windows)
powershell -File scripts/copy-beta.ps1 -TargetDir "I:\Software\ppxai"
```

## Release Process

**CRITICAL: Always use the `/release` skill for releases.**

```bash
/release v1.x.x
# Or: uv run python scripts/release.py v1.x.x
```

**NEVER manually:** update version files, create git tags, run `gh release create`, or upload assets.

### Files Updated by Release Script

| File | Pattern |
|------|---------|
| `pyproject.toml` | `version = "X.Y.Z"` |
| `ppxai/__init__.py` | `__version__ = "X.Y.Z"` |
| `vscode-extension/package.json` | `"version": "X.Y.Z"` |
| `vscode-extension/package-lock.json` | `"version": "X.Y.Z"` |
| `ppxai/rich/event_handler.py` | `Version: vX.Y.Z` |
| `ppxai/common/logger.py` | `Version: vX.Y.Z` |
| `README.md` | `ppxai-X.Y.Z.vsix` + version/test badges |
| `vscode-extension/README.md` | `ppxai-X.Y.Z.vsix` |
| `CLAUDE.md` | `**Current Version:** vX.Y.Z` |
| `ROADMAP.md` | `**Current Version**: vX.Y.Z` |
| `AGENTS.md` | `### Current Version: vX.Y.Z` |
| `docs/README.md` | `**Current Version**: vX.Y.Z` + `**Last Updated**` |

### Pre-Release Checklist

1. Create CHANGELOG entry: `## [X.Y.Z] - YYYY-MM-DD`
2. Write release notes: `docs/RELEASE-NOTES-vX.Y.Z.md`
3. Merge feature branch to master
4. Run: `python scripts/validate-release.py vX.Y.Z`

### Release Assets (Built by CI)

- `ppxai-{version}.vsix` - VSCode extension
- `ppxai-{platform}` - TUI binaries (linux-amd64, macos-arm64, macos-intel, windows.exe)
- `ppxai-server-{platform}` - Server binaries
- `ppxai-desktop-{platform}` - Desktop web app binaries
- `ppxai-{version}-macos-arm64.dmg` - macOS installer

## GitHub CLI Authentication

Use token from `.github/gh-token.env` (gitignored):

```bash
GH_TOKEN=$(cat .github/gh-token.env) gh release list
```

## Key Design Decisions

1. **Layered Architecture** - Engine (no UI) → Server (HTTP/SSE) → Clients (TUI, VSCode, Web)
2. **Provider Abstraction** - All providers implement `BaseProvider` interface
3. **Event-Based Communication** - Engine emits events; clients render them
4. **OpenAI SDK for all providers** - OpenAI-compatible API format
5. **Hybrid config** - Secrets (`.env`) separate from settings (`ppxai-config.json`)
6. **Built-in providers** - Perplexity and Gemini always available without config
7. **Transactional State Management** - Checkpoint/commit/rollback for atomic multi-step operations (v1.15.0)

## Critical Architecture Pattern: Transactional State Management

**Added:** v1.15.0
**Status:** **CRITICAL - Apply to all multi-step state operations**
**Reference:** `docs/ARCHITECTURE.md` (full documentation)

### Problem

AI agents perform multi-step operations that must succeed atomically or fail completely. Partial state updates create inconsistent UI, broken sessions, and user confusion.

### Solution: GitOps-Style Transactions

```python
with status_bar.transaction() as txn:
    txn.add("tokens", "Tokens", "1234")
    txn.update("provider", "ollama")
    txn.remove("cost")
    success, error = txn.commit()
    if not success:
        # All changes rolled back automatically
        notify_user(f"Update failed: {error}")
```

### Pattern Components

1. **Checkpoint** - Automatic backup of current state on transaction enter
2. **Stage Operations** - Chainable operations queued for validation
3. **Validate** - All operations checked before any are applied
4. **Commit** - Atomic application (all succeed or none do)
5. **Rollback** - Restore checkpoint on failure or exception

### Where to Apply

**REQUIRED for:**
- Provider/model switching with related config updates
- Context injection with multiple files
- Session state updates (messages + tokens + cost)
- Multi-step tool execution
- UI state synchronization across multiple widgets

**Example - Provider Switch:**
```python
async def switch_provider(new_provider: str, new_model: str):
    with status_bar.transaction() as txn:
        txn.update("provider", new_provider)
        txn.update("model", new_model)
        # Provider-specific badges
        if new_provider == "perplexity":
            txn.add("web", "Web", "ON")
            txn.remove("thinking")  # If exists
        success, error = txn.commit()
        if not success:
            notify(f"UI update failed: {error}")
            return False

    # Only update engine if UI transaction succeeded
    try:
        await engine_client.set_provider(new_provider)
        await engine_client.set_model(new_model)
        return True
    except Exception as e:
        # Rollback UI if engine update failed
        with status_bar.transaction() as txn:
            txn.update("provider", old_provider)
            txn.update("model", old_model)
            txn.commit()
        notify(f"Engine error: {e}")
        return False
```

### Benefits

- **State Consistency** - No partial updates, system always in valid state
- **Error Recovery** - Automatic rollback with clear error messages
- **User Trust** - Predictable all-or-nothing behavior
- **Debugging** - Clear transaction boundaries identify failures
- **Composability** - Complex workflows from simple atomic units

### Implementation Status

- ✅ StatusBar badge management (`ppxai/tui/widgets/status_bar.py`)
- ✅ Provider/model switching (badge updates in `_restore_session`, `handle_load`)
- ✅ Session state management (`EngineClient.restore_session()` — atomic restore)
- ⏳ Context injection (planned)

**Rule:** Any operation that modifies multiple related pieces of state MUST use this pattern.

## Critical Architecture Pattern: Protocol-Based Dependency Inversion

**Added:** v1.17.0
**Status:** **CRITICAL - Required for all cross-module type dependencies**
**Reference:** `ppxai/engine/types.py` (protocol definitions)

### Problem

Circular imports occur when module A imports from module B, and module B needs types from module A. Example: `client.py` → `tools/builtin/` → needs `EngineClient` from `client.py`.

### Solution: Protocols in Leaf Modules

Define `Protocol` classes in leaf modules (no upstream dependencies). Concrete classes satisfy them structurally without inheritance.

```python
# engine/types.py (leaf module — no circular dependency risk)
@runtime_checkable
class ToolEngineProtocol(Protocol):
    def get_working_dir(self) -> Optional[str]: ...
    def set_working_dir(self, path: str) -> None: ...
    async def request_file_edit_consent(self, file_path: str) -> bool: ...

# engine/tools/builtin/filesystem.py (imports protocol, not concrete class)
from ...types import ToolEngineProtocol

class ReadFileTool(BaseTool):
    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
```

### Where Protocols Are Defined

| Protocol | Location | Satisfying Class | Used By |
|----------|----------|-----------------|---------|
| `ToolEngineProtocol` | `engine/types.py` | `EngineClient` | All tool modules |
| `ToolManagerProtocol` | `engine/types.py` | `ToolManager` | All tool modules |

### Rules

1. **NEVER use `TYPE_CHECKING`** — it's a lazy import in disguise
2. **NEVER use `Any` to dodge a circular import** unless the parameter is truly duck-typed (e.g., thin adapter wrapping an opaque object)
3. When a direct import would create a cycle, define a `Protocol` in a leaf module
4. Protocols go in `engine/types.py` (for engine-layer types) or the appropriate leaf module
5. Use `@runtime_checkable` so protocols can be used with `isinstance()` checks

## Critical Architecture Pattern: Cross-Client State Through AppState

**Added:** v1.17.4 (Phase 1 follow-up, multimodal file upload work)
**Status:** **CRITICAL — Required for every new piece of state that more than one client needs**
**Reference:** `ppxai/engine/app_state.py`, `ppxai/engine/client.py::_refresh_context_attachments`

### Problem

State that multiple clients need to read (Rich, Textual, Web, VSCode)
tends to get re-implemented per client: each scans `session.messages`
on demand, each keeps its own cache, each rerenders on its own schedule.
This produces four near-identical bugs, four drift points, and four places
to update when the shape changes.

### Solution: AppState owns the canonical value; clients subscribe

Any piece of state that more than one client needs to render or react to
must live in `AppState.FIELDS` with these invariants:

1. **Stable JSON-serializable schema** — plain dicts, not dataclasses.
   The field round-trips through SSE `state_sync` events to
   `ppxai/web/shared/app-state.js` and `vscode-extension/src/appState.ts`,
   which mirror the same field names in camelCase. Cross-language schema
   drift is a production bug.

2. **Engine-owned invalidation** — `EngineClient` recomputes the field on
   mutation via a session callback. For `session.messages`, the callback
   is `SessionManager.on_messages_changed`, installed once and fired from
   every mutation site (`add_message`, `remove_last_message`, `clear`,
   `load`, `reset_for_model_switch`, `validate_and_fix_alternation`).
   When adding a new mutable store in the engine, give it an analogous
   `on_<thing>_changed` callback hook — never expect clients to poll.

3. **No client-side scanning** — clients read `state.get("field_name")` or
   subscribe via `state.on("field_name", listener)`. They never iterate
   `session.messages` (or the equivalent store) themselves. The Rich
   status bar and the Textual footer badge both call
   `state.get("context_attachments")` — they don't know how the value is
   computed.

4. **Equality-dedup on writes** — `AppState.set()` short-circuits when the
   new value equals the old, so callbacks stay quiet on no-op mutations.
   This matters for SSE: a conversation sending only text turns doesn't
   flood the wire with redundant `state_sync` events. Test this behavior
   explicitly when adding a new field.

5. **Defensive getter copies** — public getters
   (`engine_client.get_<thing>()`) return copies so external mutation
   can't corrupt canonical state. Callers that want to mutate must go
   through a proper write method.

### Worked Example: `context_attachments` (v1.17.4 Phase 1)

```python
# engine/app_state.py
"context_attachments": [],  # List of {name, kind, media_type, turn_index}
                            # Stable JSON schema — JS/TS mirrors in camelCase
```

```python
# engine/session.py — new callback, fired from 6 mutation sites
self.on_messages_changed: Optional[Callable[[], None]] = None

def add_message(self, message):
    self.messages.append(message)
    self.metadata["message_count"] = len(self.messages)
    self._notify_messages_changed()  # → engine refreshes AppState
```

```python
# engine/client.py — wire the callback, recompute on each mutation
self.session.on_messages_changed = self._refresh_context_attachments

def _refresh_context_attachments(self):
    """Walk session.messages, write to AppState — equality-dedup'd."""
    attachments = [...]  # scan once
    self.state.set("context_attachments", attachments)  # no-op if unchanged
```

```python
# rich/main.py — status bar reads AppState, never scans messages
attachments = state.get("context_attachments")  # canonical source
render_status_panel(..., pending_files=attachments)
```

Clients that arrive later (Textual, Web, VSCode) do the same:
subscribe with `state.on("context_attachments", listener)`, render from
the pushed value, done. No per-client scanning.

### Rules

1. **Ask "does more than one client need this?"** before inventing
   per-client state. If yes, it goes in AppState.
2. **Schemas must be JSON-serializable plain dicts** — no dataclasses, no
   enums, no custom types. Document the schema inline in `FIELDS`.
3. **Mirror the field in `web/shared/app-state.js` and
   `vscode-extension/src/appState.ts`** when adding to Python. Use
   camelCase. The three AppState implementations are copies of the same
   contract.
4. **Invalidation is engine-side**, triggered by a single observable
   callback on the mutable store. Never have clients call a "refresh
   state" method manually.
5. **Test the dedup path** — write a test that verifies a no-op mutation
   does NOT fire the field's listeners. Without this test, regressions
   that spam SSE events go unnoticed until production.
6. **Bump `len(AppState.FIELDS)` sentinel test** in `tests/test_app_state.py`
   when adding a new field — intentional friction so every addition gets
   reviewed against the cross-client schema contract.

### Reading the graphify signal about this pattern (don't misdiagnose)

The community-detection graph at `graphify-out/GRAPH_REPORT.md`
consistently shows AppState's host community (typically the largest
one, e.g. "Engine + AppState Core") with **cohesion ≈ 0.0** and
~1,000–1,500 nodes pulled into it. This is **expected, not a smell.**

Why it shows that way: AppState is hub-and-spoke by design (one
canonical engine-side store, four renderers subscribing). Louvain sees
no internal subgroup boundaries inside the hub and assigns minimum
cohesion. The graph is correctly describing the topology — it is *not*
labelling the design as broken.

**Do not** propose to "decompose" or "refactor" this community based
on the graphify reading alone. The pattern was deliberately chosen to
eliminate cross-client drift (4 clients re-implementing the same
state-derivation = 4 places to fix when the shape changes), and the
maintenance cost is paid for by mirroring rules 3 and 6 above plus
the planned AppState codegen (`docs/TODO-appstate-codegen.md`).

**Do** use the graph as a steady-state gauge:
- C0 size growing rapidly between rebuilds → AppState may be absorbing
  state that doesn't need cross-client parity (transient UI flicker,
  per-client view state). That belongs in a non-AppState observable.
- A new top-10 god node appearing inside C0 *without* a corresponding
  entry in `SSE_SYNC_FIELDS` (`ppxai/engine/client.py`) → cross-client
  state escaped the contract. Investigate.
- If C0 ever splits into multiple communities of comparable size, the
  hub-and-spoke contract has eroded — that *is* a design regression.

The misreading to avoid: "C0 has cohesion 0.0 → leaky abstraction →
let's redesign." That was a verify-don't-assume miss caught on
2026-04-27. The graph signal is honest; the *interpretation* matters.

## Critical Architecture Pattern: Command Dispatch via Envelope (v1.18.1)

**Added:** v1.18.1
**Status:** **CRITICAL — ALL slash command logic flows through `POST /command/<name>`**
**Reference:** `ppxai/server/routes/commands.py`, `ppxai/commands/results.py::SideEffect`,
`docs/TODO-v1.18.1-command-unification.md`, `docs/decisions/0001-keys-command-cross-client.md`

### Problem

Pre-v1.18.1, the same slash command was implemented twice — once in
the Python `CommandFactory` (Rich + Textual TUIs) and once in
`ppxai/web/shared/command-dispatcher.js` / `vscode-extension/src/chatPanel.ts`.
Most commands didn't actually go through `POST /command/<name>`;
they hit bespoke REST endpoints (`/sessions`, `/checkpoint/list`,
`/working-dir`, `/files/read`, ...) and the JS/TS clients duplicated
the formatting logic. The factory and the JS/TS lists drifted — at
v1.18.0 nine of ten builtin command modules were missing from the
PyInstaller specs and nobody noticed for six releases because only
`/usage` actually exercised the factory path.

### Solution: One dispatch path, one wire envelope, intent-named side-effects

1. **Every command** (server logic) lives in `CommandFactory`. The
   web JS dispatcher and the VSCode extension dispatcher are thin
   shells that call `apiClient.executeCommand(name, args)` →
   `POST /command/<name>` → `CommandFactory.get(name).handler(context, args)`.
2. **The wire envelope** (`POST /command/<name>` response) is:
   ```json
   {
     "ok": true,
     "result": { ...CommandResult.to_dict()... },
     "side_effects": [{"kind": "...", ...payload}],
     "version": 1
   }
   ```
   `result` is the rendered payload (TableResult, MarkdownResult,
   FileViewResult, etc.). `side_effects` are orthogonal UI directives.
3. **Side-effect kinds name the user's intent, not the rendering.**
   Web builds panels (xterm.js, CodeMirror, iframe); VSCode delegates
   to first-party APIs (`createTerminal`, `showTextDocument`,
   `executeCommand('vscode.open')`). The kind is the contract; the
   rendering is the client's choice. See
   `ppxai/commands/results.py::SideEffectKind` for the canonical
   list (15 kinds in v1.18.1).
4. **Open-enum invariant.** Clients ignore unknown kinds gracefully.
   Adding a new kind is non-breaking. `vscode_delegate` is the
   escape hatch for VSCode-only features (e.g.
   `workbench.action.openGlobalKeybindings`); web ignores it.

### TUI handlers vs HTTP handlers

The factory handlers are called from BOTH paths:
- **In-process** (Rich/Textual): `CommandFactory.get("name").handler(context, args)`
  with a `RichCommandContext` / `TextualCommandContext`. The result's
  `side_effects` field is read directly by the TUI renderer; no envelope wrap.
- **HTTP** (web/VSCode): `POST /command/<name>` →
  `ServerCommandContext` → handler → route layer wraps the result
  in the v1 envelope.

Handlers branch on `isinstance(context, ServerCommandContext)` when
they need to format differently for HTTP (e.g. `/help` returns
`MarkdownResult` for HTTP and `TextResult` with Rich markup for
TUI; same content, two formatters via
`CommandFactory.generate_help(markdown=True)`).

### `prompt_quick_pick` resume protocol (v1.18.1)

Per ADR `docs/decisions/0001-keys-command-cross-client.md`'s related
Q3 decision: when an engine handler needs the user to pick one of N
options, it emits `PROMPT_QUICK_PICK` with `items: [{label, value}]`.
**The chosen value IS the literal next args.** The client re-issues
`POST /command/<command_to_resume>` with `args=<chosen value>` —
no server-side continuation state. Every POST is idempotent given
the args.

Example: `/show @config` finds 3 matches → emits `PROMPT_QUICK_PICK`
with each item's `value` set to the absolute path. User picks one →
client POSTs `/command/show` with `args=<absolute path>`. Second
pass takes the direct branch, returns the rendered file view.

### Rules

1. **Never add a bespoke REST endpoint for command logic.** Routes
   like `/sessions`, `/checkpoint/list` exist for non-command UI
   (dropdowns, file-tree widget); they MUST NOT duplicate handler
   logic that lives in the factory. Phase 6 of the v1.18.1 plan
   retires the duplicates.
2. **`SideEffectKind` constants over bare strings.** Use
   `result.add_side_effect(SideEffectKind.OPEN_EDITOR, filepath=p)`
   so a typo is a `AttributeError`, not a silently-ignored unknown
   kind. The taxonomy sentinel test
   (`tests/test_command_envelope.py::TestSideEffectKindTaxonomy`)
   pins the exact set of v1.18.1 kinds; add a new kind in BOTH the
   constants class AND the `SideEffect` docstring AND the
   sentinel's `EXPECTED_KINDS_V1` set.
3. **Test the envelope shape, not just the result type.** The
   envelope contract (`{ok, result, side_effects, version}`) is
   what web/VSCode read. `tests/test_command_envelope.py` pins it.
4. **Per-command behavior tests live next to the handler.** Each
   handler gets a `tests/test_<command>_handler.py` with branches
   for: existing-arg, missing-arg, malformed-arg, server-side
   capability mismatch (e.g. headless server can't pyperclip).
5. **Mock persistence at the binding site.** Tests that drive
   handlers writing to disk (`set_tui_config`, etc.) must mock
   the helper on the importing module's namespace —
   monkeypatching `HOME` does NOT redirect the path because
   `USER_CONFIG_FILE` is module-load-resolved. See
   [memory/feedback_test_persistence_pollution.md](memory/feedback_test_persistence_pollution.md).

## Critical Architecture Pattern: State-Sync Determinism (v1.18.1)

**Added:** v1.18.1
**Status:** **CRITICAL — Engine state must be observable to clients within one round-trip**
**Reference:** `ppxai/web/app.js::_reanchorFromServer`,
`vscode-extension/src/chatPanel.ts::_reanchorFromServer`,
`docs/TODO-v1.18.1-state-sync-determinism.md`

### Problem

Pre-v1.18.1, the only path that delivered engine state changes to
clients was the SSE stream inside `POST /chat`. Outside an active
chat, `engine.set_working_dir()` (and similar) enqueued
`state_sync` events into `engine._event_queue`, but no consumer
drained the queue until the next chat opened an SSE generator.

The drift symptoms:
- File-tree clicks against a stale cwd → 404 file-not-found.
- Multi-tab divergence: tab A runs `/cd /x`, tab B's mirror is
  still on the old cwd.
- Tab sleep / focus restore / browser back-forward: web only
  re-anchors after two consecutive heartbeat failures.
- Agent tool fires `working_dir_changed` after `STREAM_END` but
  before the SSE generator exits → timing-dependent loss.

This non-determinism makes confident agent execution impossible:
the engine state can drift arbitrarily far from the UI between
chat turns.

### Solution: Many channels, one truth

Engine state is canonical. Web/VSCode are renderers, not
co-owners. Every mutation that lands in engine MUST be observable
to clients within one round-trip via at least one of these
channels:

1. **SSE during chat** — `state_sync` events on the `/chat`
   stream (existing).
2. **`/state` snapshot on demand** — `GET /state` returns the
   current values of every `SSE_SYNC_FIELDS` field. Clients call
   it on:
   - **Web**: `document.visibilitychange` → `visible` (Phase A,
     v1.18.1) AND on heartbeat reconnect (existing).
   - **VSCode**: `vscode.window.onDidChangeWindowState` →
     `focused` AND on reconnect.
3. **REST response piggyback** — state-mutating REST endpoints
   include drained events in the response body's `events: [...]`
   field (Phase B, planned for Step 2 of the v1.18.1 plan). The
   client feeds them through the same dispatcher that handles
   live SSE.
4. **`cwd_anchor` for stale-relpath detection** — `/files/list`
   returns the `working_dir` it resolved against; `/files/read`
   returns 409 + new cwd if the client's anchor doesn't match
   (Phase D, planned for Step 4).

### The `_reanchorFromServer` helper

Both web and VSCode have a private async helper named
`_reanchorFromServer` that does:
```
GET /state → updateFromPython(snapshot)
```
The same helper is called from BOTH the visibility/focus path
AND the heartbeat reconnect path. Tests
(`tests/test_web_visibility_reanchor.py`,
`tests/test_vscode_visibility_reanchor.py`) enforce that the
shape stays parity across the two clients — if the helpers
diverge in what they re-anchor, drift fixes won't compose.

### Rules

1. **Engine state is canonical.** Web/VSCode read AppState; they
   never invent their own copy of the same field. Optimistic
   client-side updates (e.g. set `state.workingDir = data.path`
   from a REST response) are fine but the server's value wins
   on the next sync.
2. **Visibility/focus events trigger re-anchor.** Any new client
   widget that depends on AppState must subscribe to AppState,
   not cache the value at mount time. The `_reanchorFromServer`
   helper updates the canonical mirror; subscribers receive the
   new value automatically.
3. **No new state channels without justification.** Persistent
   `GET /events` (Phase F) is deferred until A–E prove
   insufficient. Polling + REST piggyback is enough for current
   needs and avoids long-lived-connection complexity.
4. **`cwd_anchor` instead of "404 file not found".** When a
   route resolves a relpath against a working dir, return the
   working dir it used in the response. Clients send back the
   anchor on follow-up calls; mismatch → 409 with the new cwd
   in the body. Drift becomes named, surfaced, recoverable.

## VSCode Extension

### Installation

Download from [GitHub Releases](https://github.com/rcconsult/ppxai/releases):
- `ppxai-server-{platform}` - Server binary
- `ppxai-{version}.vsix` - Extension

```bash
code --install-extension ppxai-X.Y.Z.vsix
./ppxai-server-{platform}
```

### Extension Settings

- `ppxai.serverUrl` - Server URL (default: `http://127.0.0.1:54320`)
- `ppxai.defaultProvider` - Default AI provider
- `ppxai.defaultModel` - Default model
- `ppxai.enableTools` - Enable AI tools

### Commands

- `ppxai.openChat` - Open chat panel
- `ppxai.explainSelection` - Explain selected code
- `ppxai.generateTests` - Generate tests
- `ppxai.switchProvider` / `ppxai.switchModel` - Switch provider/model

## Known Issues

**Accepted behavior:**
- Perplexity/Gemini may use shell commands for web data instead of native search when tools enabled

**Resolved:** TUI Markdown Tables (v1.10.4), Ctrl-C Message Alternation (v1.10.5)

## Debug Logging

Default: **off** for fresh installs. Toggle with `/debug-log on|off`
(Rich + Textual) or `POST /config/debug-log` (web/VSCode). The flag is
persisted to `ppxai-config.json → tui.debug_log` and restored inside
`config.initialize()`, so logging is active **before** any client code
runs — critical for diagnosing early-startup regressions like silent
session-recovery failures.

See [docs/DEBUG-LOGGING.md](docs/DEBUG-LOGGING.md) for the full flow
and [memory/feedback_session_recovery_ordering.md](memory/feedback_session_recovery_ordering.md)
for the regression pattern this persistence is designed to catch.

## ppxaide TUI Implementation (CRITICAL)

The `ppxaide` command launches a Textual-based TUI with syntax-highlighted code editing. This section documents key implementation details that MUST be preserved.

### Syntax Highlighting Requirements

**Dependencies (pyproject.toml):** Syntax highlighting requires tree-sitter packages:
```
tree-sitter>=0.23
tree-sitter-python>=0.25.0
tree-sitter-javascript>=0.25.0
tree-sitter-json>=0.24.8
tree-sitter-yaml>=0.7.2
tree-sitter-toml>=0.7.0
tree-sitter-html>=0.23.2
tree-sitter-css>=0.25.0
tree-sitter-markdown>=0.5.1
tree-sitter-bash>=0.25.1
```

Without these packages, TextArea shows plain text with no syntax colors.

### Two Theme Systems

The TUI has **two separate theme systems** that must stay synchronized:

| System | Purpose | Available Options |
|--------|---------|-------------------|
| **App Theme** | Overall UI colors (Textual CSS) | 17+ themes (catppuccin-mocha, dracula, etc.) |
| **Syntax Theme** | Code highlighting (TextArea) | 5 themes only: dracula, github_light, monokai, vscode_dark, css |

### Theme Synchronization

**Key files:**
- `ppxai/tui/widgets/code_editor.py` - Contains `APP_THEME_TO_SYNTAX` mapping and `get_syntax_theme_for_app_theme()`
- `ppxai/tui/app.py` - Contains `watch_theme()` method that updates all CodeEditor widgets

**How it works:**
1. `CodeEditor.compose()` gets current app theme and selects matching syntax theme
2. `PPXAIDEApp.watch_theme()` is called automatically when theme changes (Ctrl+T or Ctrl+P)
3. All mounted CodeEditor widgets have their `syntax_theme` property updated

**Theme mapping logic:**
```python
# Dark app themes → dark syntax themes
"catppuccin-mocha": "dracula"
"dracula": "dracula"
"tokyo-night": "dracula"
"tron-legacy": "vscode_dark"
"matrix": "vscode_dark"
# Light app themes → light syntax theme
"textual-light": "github_light"
"solarized-light": "github_light"
```

**Framework limitation:** Custom app themes (tron-legacy, matrix) cannot have matching custom syntax themes. Textual's TextArea only supports 5 built-in syntax themes. The best we can do is map to the closest built-in theme (vscode_dark for cyan/green themes).

### Why Markdown Renders Nicely But Code Needs Manual Sync

Textual uses two different rendering approaches:

| Content | Widget | Theme Source | Behavior |
|---------|--------|--------------|----------|
| **Markdown** | `Markdown` widget | CSS variables (`$primary`, `$secondary`, etc.) | Auto-syncs with app theme |
| **Code** | `TextArea` widget | Internal syntax themes (dracula, etc.) | Needs manual `watch_theme()` sync |

The `Markdown` widget styles headers, links, and code blocks using CSS rules like:
```css
Markdown H1 { color: $primary; }
Markdown H2 { color: $secondary; }
```

These CSS variables are redefined by each app theme, so Markdown automatically updates when themes change.

The `TextArea` widget has its own internal rendering engine with hardcoded color palettes that don't use CSS variables. That's why we need the `watch_theme()` → `syntax_theme` chain to manually switch between the 5 available syntax themes.

### Key Bindings

All key bindings are defined in `ppxai/tui/keys.py` (single source of truth). Widget `BINDINGS` lists are generated via `get_widget_bindings()`. Use `/keys` at runtime to see all effective bindings, `/keys conflicts` for known conflicts.

- `Ctrl+Enter` - Submit message (plain Enter inserts newlines)
- `Ctrl+J` - Submit message (universal fallback for all terminals)
- `Ctrl+B` - Toggle file tree browser (Norton Commander style)
- `Ctrl+T` - Cycle through 8 curated themes
- `Ctrl+P` - Command palette (all 17+ themes)
- `Ctrl+W` - Close side panel
- `Ctrl+S` - Save side panel content
- `Escape` - Close help panel / modal screen / side panel (priority order)
- `F6` / `Ctrl+Tab` - Cycle focus: input → file tree → side panel → input
- `-` / `=` - Resize split panes (primary, works in all terminals)
- `Ctrl+[` / `Ctrl+]` - Resize split panes (fallback, Ghostty/Kitty only)

**File tree bindings (when file tree focused):**
- `Enter` - Preview file read-only in side panel
- `Ctrl+Enter` - Open file for editing in side panel
- `Space` - Inject `@file:path ` at cursor in chat input
- `Escape` - Return focus to chat input

### Kitty Keyboard Protocol

Textual 8.1.1 does NOT auto-negotiate Kitty keyboard protocol (upstream issue #6074 open). Ctrl+Enter only works in terminals that send CSI u sequences:
- **Kitty** — works natively
- **Ghostty** — requires `ctrl+enter=text:\x1b[13;5u` in config
- **WezTerm** — requires `enable_kitty_keyboard = true`
- **All others** — use `Ctrl+J` fallback

No changes planned — fallback keys cover all terminals.

### DO NOT BREAK

1. **Key registry:** `ppxai/tui/keys.py` → `get_app_bindings()` / `get_widget_bindings()` → all BINDINGS
2. **Theme sync chain:** `watch_theme()` → `get_syntax_theme_for_app_theme()` → `CodeEditor.syntax_theme`
3. **Tree-sitter dependencies** in pyproject.toml
4. **Language detection** via `EXTENSION_TO_LANGUAGE` mapping in code_editor.py

## Terminal Image Rendering (v1.15.2)

ppxai supports high-resolution inline image display in terminals that support image protocols.

### Supported Terminals and Protocols

| Terminal | Protocol | ppxaide (Textual) | ppxai (Rich) |
|----------|----------|-------------------|--------------|
| Windows Terminal | Sixel | ✅ textual-image | ✅ textual-image |
| WezTerm | iTerm2 | ✅ ITerm2ImageWidget | ✅ ITerm2Image |
| iTerm2 (macOS) | TGP/iTerm2 | ✅ textual-image | ✅ ITerm2Image |
| Kitty | TGP | ✅ textual-image | ⚠️ Fallback |

### Key Implementation Details

**Textual TUI (ppxaide):**
- Uses `render_lines()` override to inject escape sequences into Textual's rendering pipeline
- Cannot use Rich renderables directly because Textual processes segments differently
- See `ppxai/tui/widgets/iterm2_widget.py` for the implementation pattern

**Rich TUI (ppxai):**
- Uses Rich renderables with the `_NULL_CONTROL` trick to pass escape sequences through
- Terminal detection in `ppxai/rendering/rich_renderer.py`

**The `_NULL_CONTROL` trick:**
```python
_NULL_CONTROL = [(ControlType.CURSOR_FORWARD, 0)]
yield Segment(escape_sequence, control=_NULL_CONTROL)
```
This tells Rich the segment contains control codes, so it passes the content through unchanged.

### WezTerm Configuration

WezTerm requires `TERM_PROGRAM` environment variable for detection:
```lua
-- ~/.wezterm.lua
config.set_environment_variables = {
  TERM_PROGRAM = 'WezTerm',
}
```

### Key Files

- `ppxai/tui/renderable/iterm2.py` - ITerm2Image Rich renderable
- `ppxai/tui/widgets/iterm2_widget.py` - Textual widget using render_lines() injection
- `ppxai/tui/widgets/image_handlers.py` - Terminal detection and widget selection
- `ppxai/rendering/rich_renderer.py` - Rich TUI image rendering

## vLLM Tool Calling Reference

### **Tool Call Parsers: Hermes vs Harmony**

vLLM supports multiple tool calling formats via `--tool-call-parser` flag. Different model families use different parsers:

| Model Family | Parser | vLLM Flag | Stability | Notes |
|--------------|--------|-----------|-----------|-------|
| **GPT-OSS** | Harmony | `--tool-call-parser openai` | ⚠️ Intermittent | See Harmony section below |
| **Qwen3** | Hermes | `--tool-call-parser hermes` | ✅ Stable | Different grammar than Harmony |
| **Qwen2.5** | Hermes | `--tool-call-parser hermes` | ✅ Stable | - |
| **Nous Hermes** | Hermes | `--tool-call-parser hermes` | ✅ Stable | - |

**Key Point:** Always use the correct parser for your model family. Using the wrong parser causes tool calling to fail completely.

---

### **GPT-OSS (Harmony Format)**

**Critical Finding:** Harmony format is **mandatory** for GPT-OSS. From official documentation:
> "GPT-OSS should not be used without using the Harmony format as it will not work correctly."

The model was trained specifically on Harmony's response format with control tokens (`<|recipient|>`, `<|thinking|>`, `<|call|>`, etc.). These tokens are always output—they're not optional. If vLLM doesn't parse them, they leak into responses causing `HarmonyError`.

**Problem:** vLLM with GPT-OSS models can hit `HarmonyError: unexpected tokens remaining in message header` when using native tool calling (`--enable-auto-tool-choice --tool-call-parser openai`). This is a known vLLM/Harmony library issue ([vLLM #23567](https://github.com/vllm-project/vllm/issues/23567)).

**ppxai supports two tool calling modes:**

| Mode | Config | vLLM Flags | Reliability |
|------|--------|------------|-------------|
| **Native** | `native_tool_calling: true` | `--enable-auto-tool-choice --tool-call-parser openai` | ⚠️ HarmonyError risk |
| **Prompt-Based** | `native_tool_calling: false` | None required | ✅ Stable (recommended) |

**Key insight:** vLLM only triggers Harmony parsing when `request.tools` is provided. With `native_tool_calling: false`, ppxai doesn't send `tools` parameter, so vLLM returns plain text that ppxai parses client-side. This bypasses the unstable Harmony parser.

**Implementation details:**
- Tool prompt injection: `ppxai/engine/tools/manager.py:get_tools_prompt()`
- Multi-strategy parser: `ppxai/engine/tools/parser.py:parse_tool_call()`
- GPT-OSS nested unwrapping: `ppxai/engine/tools/parser.py:_normalize_tool_call()`
- Parameter aliasing: `ppxai/engine/tools/manager.py:PARAM_ALIAS_GROUPS`

**Documentation:**
- [docs/vllm-tool-calling-guide.md](docs/vllm-tool-calling-guide.md) - ppxai-specific guide
- [docs/prompt-based-tool-calling.md](docs/prompt-based-tool-calling.md) - General developer guide
- [examples/prompt_based_tools.py](examples/prompt_based_tools.py) - Standalone example

**Current production setup:**
- vLLM 0.11.x nightly with LMCache
- `--tool-call-parser openai` (correct flag)
- Model: `openai/gpt-oss-120b`
- ppxai default: `native_tool_calling: true`

**For developers hitting HarmonyError:** Set `native_tool_calling: false` in provider config, or use the standalone example for non-ppxai applications.

---

### **Qwen3 / Qwen2.5 (Hermes Format)**

**Status:** Generally more stable than Harmony. Hermes grammar is well-tested and widely adopted.

**vLLM Server Setup:**
```bash
vllm serve Qwen/Qwen3-... \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --max-model-len 32768
```

**ppxai Config:**
```json
{
  "providers": {
    "custom": {
      "base_url": "http://localhost:8000/v1",
      "native_tool_calling": true,
      "models": {
        "Qwen/Qwen3-...": {
          "max_tokens": 8192,
          "temperature": 0.2
        }
      }
    }
  }
}
```

**Known Issues:**
- Same truncation issues as GPT-OSS if `max_tokens` too low
- Unicode whitespace in code (Pattern #2 still applies)
- May still exhibit "I'll use X tool" behavior (test with your specific model)

**Fallback:** If native tool calling fails, set `native_tool_calling: false` for prompt-based tools.

---

**Known Issue: "I'll use X tool" followed by JSON text (v1.15.2)**

Sometimes GPT-OSS outputs tool calls as JSON text in the response instead of using native tool calling:
```
I'll use the apply_patch tool.
```json
{"tool": "apply_patch", "arguments": {...}}
```

**Root causes:**
1. vLLM's Harmony parser intermittently fails to capture tool calls
2. Model explains what it will do before calling the tool (learned behavior)
3. Long tool calls (e.g., apply_patch with large diffs) may be truncated if no `max_tokens` is set

**Mitigation:**
1. Add `max_tokens: 8192` (or higher) to model config to prevent truncation
2. Add system prompt instruction: "NEVER say 'I'll use X tool' then output JSON - call tools directly"
3. Add AGENTS.md hint: "Do NOT output tool call JSON in your response text"
4. The fallback parser (`ppxai/engine/tools/parser.py`) will attempt to extract tool calls from text responses

**Example config:**
```json
{
  "models": {
    "openai/gpt-oss-120b": {
      "max_tokens": 8192,
      "generation_params": { "temperature": 0.2 }
    }
  }
}
```

## Verify, Don't Assume

**Before dismissing an anomaly (warning, error, unexpected output) as
"pre-existing", "unrelated", "normal", or "expected to fail", run the
actual check that proves it.** Confident-sounding assumptions on this
project have repeatedly cost corrective iterations.

Concrete examples from project history:
- v1.18.1 needed 4 retag cycles in part because Linux-vs-Windows test
  divergence was assumed-equivalent (HOME-includes-tmp_path fallback was
  Windows-only). See `memory/release-lessons.md` §4.
- v1.18.1 streaming felt sluggish — a 100ms tick from 6 weeks earlier
  that was *assumed* to be fine because it was unchanged.
- PyInstaller binaries shipped without `dotenv` because the build venv
  was *assumed* to have every `hiddenimport` installed. See
  `memory/feedback_pyinstaller_silent_module_drop.md`.
- Test persistence pollution: `monkeypatch HOME` was *assumed* to redirect
  a path that was actually module-load-resolved. See
  `memory/feedback_test_persistence_pollution.md`.

Common 30-second verifications to run before dismissing:
- "Does this fail on master too?" → `git stash`, rerun, restore.
- "Is this output from my edit or pre-existing?" → check timestamps,
  `git blame`, or run the tool against a baseline.
- "Does the file parse?" → run the parser on JUST the section edited,
  not the whole file (whole-file parsers often error on legitimate
  non-target content like markdown bodies after YAML frontmatter).
- "Is the binary actually working?" → `<binary> --version` after every
  PyInstaller rebuild, even when the build succeeded.

If verification is genuinely impractical, say "I'm assuming X because Y,
but haven't confirmed" — make the uncertainty explicit so the user can
decide whether to trust it. Trust-but-verify especially applies to:
PyInstaller builds, cross-platform test failures, encoding/CRLF behaviour,
Windows-specific path code, YAML parsing of multi-format files, and
anything to do with releases.

**Verify both directions, not just "is there a problem".** When a
signal flags X as broken AND when someone pushes back saying the
signal is wrong, both readings need the same Tier-2-style
verification (production-code-only inbound counts, channel-ratio
inspection, source-code grep). Pattern-matched three times on
`bugfix/v1.18.2` (`EngineClient`, `ChatViewProvider`,
`PPXAIDEApp`) before the discipline was pinned. Concrete
heuristic for graphify-flagged "god classes":

```bash
# Production-code-only inbound count.
grep -rc "ClassName" ppxai/ --include="*.py" | grep -v ":0$"

# Channel ratio in the suspect file.
grep -cE 'event_bus\.(emit|subscribe)|state\.(on|set|get)' file.py
```

If textual references are <30 across production code AND
bus/state/protocol channels carry communication, the class is NOT
a god class regardless of whole-repo graphify edge count.

## Commit Guidelines

- Do NOT include Claude credits or co-authored-by lines. Keep commit messages clean.
- **Never commit sensitive information:** tokens, API keys, passwords, hostnames, usernames, file paths with usernames, or other environment-specific details.
- In PRs and documentation, use generic placeholders (e.g., `your-token`, `/path/to/project`) instead of real values.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)

**Whole-repo god-node ranking is biased by test coverage.** As of
v1.18.2 (2026-04-29), `.graphifyignore` excludes `tests/`,
`benchmarks/`, `scripts/`, `examples/`, `docs/archive/` — without
them, `tests/test_tui.py` (4,788 LoC) alone drove 71-79% of the
"god class" edges on `PPXAIDEApp`/`MessageBox`/`ChatView` and
made the whole-repo ranking misleading. With exclusions: 11.6k →
4.5k nodes (-61%); the post-exclusion top hubs reflect actual
architectural hubs (`EventType`, `CommandResult`, `SessionManager`,
`BaseTool`, `BaseProvider`, `ToolManagerProtocol`).

**Subtree-build pattern for subsystem analysis.** When the
whole-repo graph is too coarse (e.g. "what are the actual UI
hubs?"), build a per-subtree graph with `c:\tmp\subtree_build.py
<input_path> <output_dir>`. Used three times in v1.18.2
(`engine`, `server`, `commands`, `vscode`, `tui`) to surface
subsystem-internal structure that the whole-repo graph hides.

**Don't read whole-repo "god class" rank as architectural smell
without verifying.** Apply the production-code-only inbound count
heuristic above before concluding. The same trap caught
`EngineClient`, `ChatViewProvider`, and `PPXAIDEApp` on this
branch.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ppxai is a terminal-based UI application for interacting with multiple AI providers (Perplexity AI, OpenAI, OpenRouter, local models). It provides an interactive chat interface with model selection, conversation history, streaming responses, and AI-powered tools.

**Current Version:** v1.17.7

**v1.17.x highlights:**
- **NEW:** AppState schema DTO — `ppxai/engine/app_state_schema.json` is the golden source of truth for all 4 clients. Python loads via `importlib.resources`, Web via `window.APP_STATE_SCHEMA` injected into `index.html` by FastAPI, VSCode via bundled copy kept in sync by `scripts/sync-schema.js` precompile hook. Rich + Textual TUIs consume it transitively via the Python `AppState`. `GET /schema/app-state` diagnostic endpoint. Zero hand-maintained parallel schemas.
- **NEW:** AppState — observable state across all 4 clients (Python, JS, TS), SSE `state_sync` push
- **NEW:** Server modularization — `http.py` 2,936→411 lines, 17 route modules (agent, chat, checkpoints, commands, completion, config, consent, context, file_serve, files, preview, providers, schema, sessions, static, terminal, usage), DI via `Depends(get_session)`. The v1.17.1 baseline was 13 modules; v1.17.4 added `completion.py` (cross-client autocomplete), `file_serve.py` + `preview.py` (file upload Phase 3), and `schema.py` (AppState DTO)
- **NEW:** Config submodules — `config/__init__.py` 943→262 lines, 6 submodules
- **NEW:** EngineClient decomposition — 1,588→977 lines across **6 ops modules**: `bootstrap_ops`, `checkpoint_ops`, `consent_ops`, `session_ops`, `multimodal_ops` (v1.17.4 Phase 2 extraction: context attachments + VL sidecar), `provider_ops` (v1.17.4: provider/model switching, list, current). `client.py` stays ~977 lines as a thin facade; each ops module is <500 lines and independently testable.
- **NEW:** CodeMirror modular — shared core + 30 language addons (6.3MB→2.3MB), lazy loading
- **NEW:** K8s POC — 5 phases: namespace, Dockerfile.server, session manager, login, LDAP auth
- **NEW:** Benchmark infra — K8s benchmark jobs, `--agents-md` toggle, delta test results
- **NEW:** File upload Phases 0-7 complete — multimodal message plumbing, `/attach` command, SessionFileStore, file preprocessing, image validation, VL sidecar, PDF/Excel/PPTX tools, web drag-drop + thumbnails, VSCode drag-drop overlay + inline thumbnails + context badge, Textual file tree attach
- **NEW:** CompletionProvider engine layer — `engine/completion.py` is the single source of truth for autocomplete across ALL 4 clients (Rich, Textual, Web, VSCode). Covers: slash commands + aliases, path args, @file refs, `@git`/`@tree`/`@clipboard`/`@url` context providers, `/tools`/`/usage`/`/checkpoint`/`/status`/`/theme` subcommands, dynamic `/model` + `/provider` lookups, `/tools help <tool>`. Rich + Textual call in-process; Web + VSCode call via `POST /complete`. Client completers are pure glue (~85 lines Rich, ~100 lines Textual, down from ~594 / ~238). No more duplicated subcommand tables.
- **NEW:** Gemini 3.1 Flash Lite + Gemma 4 family (31B, 26B MoE, E4B, E2B); deprecated 2.0/2.5 models with shutdown dates
- **NEW:** `/doctor` config advisor — deprecation table, dead/deprecated/new/recommended model scanning
- **FIX:** Heartbeat during streaming — skip health failures while single-worker busy with LLM tokens
- **FIX:** `/save <name>` now honors name argument; `/ls <file>` supports single-file listing
- **FIX:** Session autorestore for directory-format sessions; context attachment badge visibility
- **FIX:** Inline attachment thumbnails with split panel lightbox (images) and PDF embed
- **FIX:** Terminal PTY Windows crash — guarded Unix-only imports; server starts cleanly on Windows
- **FIX:** ppxai-desktop version reporting — PyInstaller spec includes `ppxai.version` hidden import

**Version Alignment:**
- Python package (pyproject.toml): v1.17.7
- VSCode extension (package.json): v1.17.7
- Last release tag: v1.17.7
- Active branch: `feature/v1.18.0` (P0 agent heartbeat primitives — see [docs/RELEASE-NOTES-v1.18.0.md](docs/RELEASE-NOTES-v1.18.0.md))

**v1.18.0 (in progress) — P0 agent heartbeat primitives:**
- **NEW:** `EventType.AGENT_BEAT` / `AGENT_RUN_START` / `AGENT_RUN_COMPLETE` / `AGENT_RUN_ERROR` / `AGENT_ZOMBIE` lifecycle events emitted by `chat_with_tools`
- **NEW:** `AgentBeatState` dataclass (`ppxai/engine/types.py`) with `as_event_data()` JSON payload helper
- **NEW:** `AppState.agent_beat` field (schema-driven across Python/JS/TS) — heartbeat pushed via `state_sync` SSE, cleared on run end
- **NEW:** Zombie circuit-breaker — `tools.agent.zombie_threshold` config (default 3, 0 disables) stops the tool loop after N consecutive failed iterations, emits `AGENT_ZOMBIE` + `AGENT_RUN_ERROR`
- **NEW:** Client renderers — dim status line in Rich, status-bar badge in ppxaide with `success`/`warning`/`error` variants, header badge in Web + VSCode
- See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §"Agent Heartbeat Primitives" for the emission contract

**v1.18.0 (in progress) — stabilization pass (Phases 1–5):**
- **NEW:** `GET /state` snapshot endpoint (`ppxai/server/routes/state.py`) returns the SSE-synced AppState fields for web/VSCode reconnect catch-up. `SSE_SYNC_FIELDS` hoisted to module-level constant in `ppxai/engine/client.py` as the canonical whitelist.
- **NEW:** `AppState.last_message_role` field — Rich and Textual interrupt handlers no longer scan `session.messages` directly; `EngineClient._on_messages_changed` is now a fan-out callback for every message-derived AppState field.
- **NEW:** Cross-language formatting helpers — `ppxai/common/format.py` (canonical `format_tokens` + `format_usage_badge`) with byte-identical JS/TS mirrors guarded by `tests/test_usage_format.py`. Zero-cost suppression unified across Rich/web/VSCode.
- **NEW:** `ppxai/common/autosave_guard.py::AutosaveFailureGuard` — surfaces auto-save failures to the user after 3 consecutive failures (was silently logged before, hiding "session not saving" from users with full disks / revoked permissions).
- **NEW:** `ppxai/common/atomic_file.py::atomic_replace` and `ppxai/common/docx_to_pdf.py::convert_docx_to_pdf` — I/O helpers extracted from private routes/tools modules so tests consume them via documented public contracts. Six other pure helpers (`is_empty_or_context_only`, `load_dotenv_with_bom_handling`, `count_csv_rows_cols`, `get_effective_profile`, `normalize_content_to_text`, `is_word_document`) promoted to public — signature + docstring is the interface.
- **NEW:** Cross-client AGENT_BEAT rendering parity test (`tests/test_agent_beat_cross_client_parity.py`) — proves the four clients agree on the contract, including known Rich divergence captured explicitly.
- **REMOVED:** `EngineClient.has_vision_model` back-compat alias (deprecated in v1.17.4; verified zero external callers).
- **FIX:** `/attach` of Windows text files no longer ships CRLF bytes to the LLM (`PendingFile.text` normalises). CSV attachment on Windows no longer fails — `mimetypes.guess_type` resolves `.csv` to `application/vnd.ms-excel` on Windows, file_preprocessing now special-cases CSV before the office dispatch.
- **FIX:** 19 pre-existing test failures cleared on Windows (CRLF, mimetype, path-separator, config-default issues).
- See [docs/STABILIZATION-v1.18.0.md](docs/STABILIZATION-v1.18.0.md) for the full pass summary.

For detailed release history, see [CHANGELOG.md](CHANGELOG.md) and `docs/RELEASE-NOTES-v*.md`.

## Codebase Statistics (v1.18.0 in progress, approximate)

| Language | Files | Lines |
|----------|------:|------:|
| Python (core) | 174 | ~54,000 |
| Python (tests) | 100 | ~37,500 |
| TypeScript (VSCode) | 17 | ~8,900 |
| JavaScript (Web) | 19 | ~9,400 |
| CSS | 6 | ~3,400 |
| **Total** | **~316** | **~113,200** |

Breakdown: ~81% Python, ~8% JavaScript, ~8% TypeScript, ~3% CSS

Tests: **2,591 passing**, 2 skipped. Up from 2,410 at the v1.17.7
release tag — heartbeat P0 added 1,682 lines of new test coverage,
the stabilization pass added 181 more (cross-client parity, AppState
fields, autosave guard, format-string mirrors, etc.).

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

## Commit Guidelines

- Do NOT include Claude credits or co-authored-by lines. Keep commit messages clean.
- **Never commit sensitive information:** tokens, API keys, passwords, hostnames, usernames, file paths with usernames, or other environment-specific details.
- In PRs and documentation, use generic placeholders (e.g., `your-token`, `/path/to/project`) instead of real values.

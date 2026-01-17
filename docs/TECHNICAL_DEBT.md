# Technical Debt Tracker

**Last Updated:** 2026-01-17
**Version:** v1.13.10

This document tracks identified technical debt and refactoring opportunities in the ppxai codebase. Items are removed as they are addressed.

---

## Critical Priority

### 1. Global State Management

**Status:** ✅ Completed (v1.13.10)
**Files:** [ppxai/server/http.py](../ppxai/server/http.py), [ppxai/server/session_manager.py](../ppxai/server/session_manager.py)

**Resolution:** Refactored to `SessionManager` class with:
- Thread-safe singleton pattern using `threading.Lock` for creation
- Async-safe operations using `asyncio.Lock` for session access
- Centralized session, consent, and activity tracking
- Proper initialization/shutdown via FastAPI lifespan
- Added `/health` and `/ready` endpoints for container orchestration

**New Files Created:**
- `ppxai/server/session_manager.py` - SessionManager class (467 lines)

**Changes to http.py:**
- Removed global variables: `sessions`, `default_engine`, `default_lock`, `pending_consent_requests`, etc.
- Added single `session_manager: SessionManager` global
- All endpoints now use `await get_or_create_session()` for thread-safe session access

---

### 2. Monolithic Files

**Status:** Partially Addressed (v1.13.10)

| File | Lines | Issue | Status |
|------|------:|-------|--------|
| [ppxai/commands/handler.py](../ppxai/commands/handler.py) | 507 | CommandHandler class (legacy methods commented) | ✅ Command Factory |
| [ppxai/server/http.py](../ppxai/server/http.py) | 2,247 | HTTP + session + consent mixed | ✅ SessionManager extracted |
| [ppxai/engine/client.py](../ppxai/engine/client.py) | 2,035 | Core logic, providers, tools, sessions | Open |
| [ppxai/config/](../ppxai/config/) | ~700 | Config package with store, loader, public API | ✅ ConfigStore pattern |
| [vscode-extension/src/chatPanel.ts](../vscode-extension/src/chatPanel.ts) | 5,061 | Massive event handling | Open |

**Large Functions:**
- `client.py:1100-1400` (chat loop): 300+ lines

**commands.py Refactoring - ✅ Completed (v1.13.10):**
Migrated to Command Factory pattern in `ppxai/commands/` package:
- `factory.py` - CommandSpec, CommandFactory registry with self-registration
- `session.py` - /save, /export, /sessions, /load
- `provider.py` - /model, /provider, /autoroute
- `system.py` - /help, /theme, /status, /spec
- `coding.py` - /generate, /test, /docs, /implement, /debug, /explain, /convert
- `utility.py` - /cd, /pwd, /config, /debug_log, /context
- `tools.py` - /tools, /usage
- `display.py` - /show
- `agent.py` - /agent, /undo, /checkpoint
- Legacy methods in handler.py commented with deprecation notice (removal in v1.14.x)

**config.py Package Conversion - ✅ Completed (v1.13.10):**
Converted monolithic `config.py` (1,352 lines) to `config/` package (~700 lines):
- `config/store.py` - Thread-safe ConfigStore singleton with double-check locking
- `config/loader.py` - Config loading, validation, environment handling
- `config/__init__.py` - Full public API with module-level `__getattr__`

Key improvements:
- Thread-safe and asyncio-safe for containerized deployments
- `ConfigStore.set_for_testing()` replaces direct `_config` patching in tests
- Module-level `__getattr__` provides lazy `PROVIDERS` and `MODELS` access
- Removed legacy globals: `MODEL_PROVIDER`, `set_active_provider()`
- Added `get_default_provider()` function for runtime provider resolution

**Recommendation:**
- client.py: Extract chat loop and tool parsing (medium priority)

---

### 3. Silent Error Handling

**Status:** ✅ Completed (v1.13.10)
**Scope:** Reviewed 48 instances of silent error handling across 8 files

**Resolution:** Applied selective logging based on value:
- **22 instances** now log with `logger.debug()` or `logger.warning()`
- **11 instances** kept silent (intentional fallbacks, expected errors)
- **15 instances** in LOW priority files left as-is (trial-error detection, cleanup)

**Key Changes:**
- Fixed 2 bare `except:` clauses in client.py (security risk - caught KeyboardInterrupt)
- Added `logger.warning()` for invalid regex patterns in consent.py (security config)
- Added `logger.warning()` for auto-save failures and corrupted session files
- Added `logger.debug()` for checkpoint, session restore, and tool status errors

**Files Modified:**
- `ppxai/usage.py` - Usage data loading
- `ppxai/commands.py` - Tool/consent status, file search, git status
- `ppxai/server/http.py` - Consent mode retrieval
- `ppxai/engine/client.py` - Checkpoint restore, regex patterns, shell consent
- `ppxai/common/consent.py` - Shell command pattern compilation
- `ppxai/main.py` - Session restore, auto-save
- `ppxai/engine/session.py` - Corrupted session files
- `ppxai/checkpoint.py` - Checkpoint creation

---

## High Priority

### 4. Code Duplication - Container Tools

**Status:** ✅ Completed (v1.13.10)
**File:** [ppxai/engine/tools/builtin/container.py](../ppxai/engine/tools/builtin/container.py) (738 lines)

**Resolution:** Refactored to use inheritance hierarchy:
- `CLITool` - Base class for read-only CLI tools
- `ConsentCLITool` - Base class for tools requiring user consent
- `DockerTool` / `DockerConsentTool` - Docker/Podman specific bases
- `KubeTool` / `KubeConsentTool` - Kubernetes specific bases

Each tool now only defines `build_command()` method and metadata, reducing boilerplate by ~40%.

---

### 5. Code Duplication - Consent Manager

**Status:** ✅ Completed (v1.13.10)
**File:** [ppxai/common/consent.py](../ppxai/common/consent.py)

**Resolution:** Extracted `BaseConsentManager` class with shared logic:
- All state initialization (files, commands, patterns)
- Pattern loading and command classification
- Status reporting and non-prompting approval checks
- Decision processing helpers

Both `ConsentManager` (async) and `SyncConsentManager` now inherit from `BaseConsentManager`, reducing duplication by ~100 lines (708 → 609 lines, 14% reduction).

---

### 6. Import Structure

**Status:** ✅ Refactored (v1.13.10)

**Pattern:** The codebase follows a DAG (Directed Acyclic Graph) import structure:
1. `TYPE_CHECKING` - For type hints in builtin tools (required to avoid actual cycles)
2. Clean leaf modules - config.py, themes.py, types.py have no ppxai imports
3. Top-level imports - commands.py now uses standard top-level imports

**Refactoring Done:**
- Removed unnecessary lazy imports from `commands.py` (moved to top-level)
- Verified no circular dependencies exist in the codebase
- Updated `docs/ARCHITECTURE.md` with accurate DAG documentation

**Note:** The only pattern truly needed is `TYPE_CHECKING` in `tools/builtin/*.py`.

**Future Improvement:** A Tool Factory pattern could eliminate TYPE_CHECKING entirely and enable dynamic tool loading. See [DESIGN-TOOL-FACTORY.md](DESIGN-TOOL-FACTORY.md) for detailed analysis.

---

### 7. Dangerous eval() Usage

**Status:** ✅ Completed (v1.13.10)
**File:** [ppxai/engine/tools/builtin/calculator.py](../ppxai/engine/tools/builtin/calculator.py)

**Resolution:** Replaced `eval()` with AST-based safe evaluation:
- Uses `ast.parse()` to parse expressions into AST
- Custom `_safe_eval()` function walks the AST
- Only supports numeric constants, binary ops (+,-,*,/,//,%,**), and unary ops
- Rejects function calls, name references, and any other constructs
- Better error messages (division by zero, syntax errors, unsupported expressions)

---

## Medium Priority

### 8. Missing Type Hints

**Status:** ✅ Partially Addressed (v1.13.10)

**TypeScript (resolved):**
- Created `FileConsentRequest`, `ShellConsentRequest` interfaces in httpClient.ts
- Added `EventMetadata` interface replacing `metadata?: any`
- Added `ConsentResponse` type for consent response values
- Updated chatPanel.ts to use new types

**Remaining (low priority):**
- `backend.ts:25, 64` - generic result types (truly polymorphic)
- Python provider methods - already have good type coverage in base.py

---

### 9. Inconsistent Error Handling in HTTP Endpoints

**Status:** ✅ Partially Addressed (v1.13.10)
**File:** [ppxai/server/http.py](../ppxai/server/http.py)

**Resolution (v1.13.10):**
- Removed unused `JSONResponse` import
- Standardized static file 404 error messages to include requested filename
- Fixed string concatenation in error details (use f-strings consistently)
- All error responses now use `HTTPException` exclusively (45 occurrences)

**Remaining items:**
- Silent pass patterns for expected errors (intentional, kept for graceful degradation)

**Original mixed patterns (now resolved):**
- ~~JSONResponse for errors~~ → Removed (was unused import)
- HTTPException (standard) → All errors now use this pattern consistently

---

### 10. Configuration Complexity

**Status:** ✅ Completed (v1.13.10)
**File:** [ppxai/config/](../ppxai/config/) (~700 lines across 3 files)

**Resolution:** Split monolithic `config.py` into `config/` package:
- `config/store.py` - Thread-safe ConfigStore singleton
- `config/loader.py` - Loading, validation, built-in providers
- `config/__init__.py` - Public API with 50+ functions

Key improvements:
- Clear separation of concerns (storage vs loading vs API)
- Thread-safe and asyncio-safe for multi-worker deployments
- Lazy loading via proxy classes (_ProvidersProxy, _ModelsProxy)
- Test-friendly with `ConfigStore.set_for_testing()` method

---

### 11. Abrupt Process Termination

**Status:** ✅ Completed (v1.13.10)
**File:** [ppxai/server/http.py](../ppxai/server/http.py)

**Resolution (v1.13.10):**
- Replaced `os._exit(0)` with graceful shutdown via `asyncio.Event`
- Added `_shutdown_event` global for signaling shutdown
- Created `_run_server_with_graceful_shutdown()` helper using `uvicorn.Server` directly
- `/shutdown` endpoint now sets event instead of calling `os._exit()`
- Cleanup handlers (atexit) now run properly
- Lifespan shutdown hooks execute correctly

---

## Low Priority

### 12. Legacy Backward Compatibility Code

**Status:** ✅ Addressed (v1.13.10)
**File:** [ppxai/commands/handler.py](../ppxai/commands/handler.py)

**Resolution:** Added deprecation warning for legacy constructor signature:
```python
warnings.warn(
    "Passing client object to CommandHandler is deprecated. "
    "Use CommandHandler(api_key, model, base_url, provider) instead. "
    "Will be removed in v2.0.0.",
    DeprecationWarning,
    stacklevel=2
)
```

**Next step:** Remove legacy signature in v2.0.0.

---

### 13. Version Marker Comments

**Status:** Policy Defined
**Scope:** Throughout codebase (~150+ markers)

**Pattern:** Code annotated with version numbers (v1.11.0, v1.12.0, v1.13.x) scattered as comments.

**Impact:** Maintenance burden, harder to track when compatibility code can be removed.

**Policy (Agreed):**

1. **Remove informational markers** - Feature annotations like `# v1.13.4: Tool usage tracking` provide no value; git history serves this purpose

2. **Keep only compatibility markers** - Code that needs removal in a future version should use:
   ```python
   # COMPAT(v2.0.0): Remove legacy signature support
   ```

3. **EOL dates** - Compatibility code has 3-month EOL from introduction

**Cleanup Schedule:**
- Cleanup happens at **minor version releases**
- Example: When releasing v1.14.0, remove all v1.13.x informational markers
- Compatibility markers remain until their stated EOL version

**Files Most Affected:**
- `vscode-extension/src/chatPanel.ts` (~45 markers)
- `ppxai/engine/client.py` (~20 markers)
- `vscode-extension/src/httpClient.ts` (~15 markers)
- `ppxai/engine/session.py` (~12 markers)

---

### 14. Magic String Literals

**Status:** ✅ Completed (v1.13.10)
**File:** [ppxai/constants.py](../ppxai/constants.py)

**Resolution:** Converted class-based constants to `str, Enum` with validation helpers:
- `ProviderName`, `MessageRole`, `ConsentMode`, `ConsentResponse` - Now proper enums
- `SystemPromptMode`, `ShellRiskLevel`, `FileEncoding`, `CheckpointBackend` - Now proper enums
- Added `is_valid_*()` helper functions for runtime validation
- Added generic `is_valid_enum()` and `get_enum_values()` helpers
- Kept `ConfigKey`, `ToolSetting`, `Default`, `APIEndpoint` as classes (dict keys/URLs/integers)

**Benefits:**
- Seamless string comparison (no `.value` needed due to `str, Enum`)
- IDE autocompletion and type safety
- Runtime validation via helper functions
- Works with Python 3.10+ (no StrEnum dependency)

---

### 15. TypeScript let vs const

**Status:** ✅ Verified Correct (v1.13.10)
**File:** [vscode-extension/src/chatPanel.ts](../vscode-extension/src/chatPanel.ts)

**Analysis (v1.13.10):** Reviewed all 46 `let` declarations in chatPanel.ts:
- All are legitimately reassigned (if/else branches, loops, async operations)
- Original line numbers were outdated/incorrect
- No changes needed - code is properly using `let` where variables are mutable

**Original claim:** "Lines 179, 317, 357, 481, 658, 659, 823, 1215, 1338, 1352-1353 should be const"
**Finding:** All checked variables ARE reassigned after declaration.

---

### 16. Container Deployment Support

**Status:** ✅ Completed (v1.13.10)
**Scope:** New files created

**Resolution:** Full containerized deployment support added:
- [Dockerfile](../Dockerfile) - Multi-stage build with uv package manager
- [docker-compose.yaml](../docker-compose.yaml) - Local development setup
- [kubernetes/deployment.yaml](../kubernetes/deployment.yaml) - Deployment with health probes
- [kubernetes/service.yaml](../kubernetes/service.yaml) - ClusterIP service
- [kubernetes/ingress.yaml](../kubernetes/ingress.yaml) - Nginx ingress with SSE support

**Health endpoints** (added in v1.13.10):
- `/health` - Liveness probe (always returns 200)
- `/ready` - Readiness probe (checks session manager)

**Files Created:**
```
ppxai/
├── Dockerfile                    # Multi-stage build (Python 3.11-slim)
├── docker-compose.yaml           # Local dev with volume mounts
└── kubernetes/
    ├── deployment.yaml           # 1 replica, resource limits, probes
    ├── service.yaml              # ClusterIP on port 80
    └── ingress.yaml              # Nginx with SSE proxy settings
```

**Usage:**
```bash
# Docker
docker compose up --build

# Kubernetes
kubectl create secret generic ppxai-secrets --from-literal=PERPLEXITY_API_KEY=xxx
kubectl apply -f kubernetes/
```

---

## Completed Items

Items moved here after being addressed:

| Item | Description | Fixed In | Date |
|------|-------------|----------|------|
| #1 | Global state management - SessionManager singleton with thread safety | v1.13.10 | 2026-01-14 |
| #2 | commands.py - Migrated to Command Factory pattern in commands/ package | v1.13.10 | 2026-01-16 |
| #3 | Silent error handling - Added selective logging to 22 instances | v1.13.10 | 2026-01-15 |
| #4 | Container tools code duplication - refactored to CLITool hierarchy | v1.13.10 | 2026-01-14 |
| #5 | Consent Manager duplication - Extracted BaseConsentManager class | v1.13.10 | 2026-01-15 |
| #6 | Import structure - Refactored commands.py to DAG imports, updated ARCHITECTURE.md | v1.13.10 | 2026-01-15 |
| #7 | eval() usage - Replaced with AST-based safe evaluation | v1.13.10 | 2026-01-15 |
| #10 | config.py complexity - Split into config/ package with ConfigStore pattern | v1.13.10 | 2026-01-16 |
| #9 | HTTP error handling - Standardized on HTTPException, removed unused JSONResponse | v1.13.10 | 2026-01-16 |
| #11 | Abrupt process termination - Graceful shutdown via asyncio.Event | v1.13.10 | 2026-01-16 |
| #15 | TypeScript let vs const - Verified all 46 uses are correct | v1.13.10 | 2026-01-16 |
| - | Magic strings - Created ppxai/constants.py with centralized constants | v1.13.10 | 2026-01-16 |
| - | BUILTIN_PROVIDERS removal - JSON config as single source of truth | v1.13.10 | 2026-01-16 |
| #8 | Type hints - Added TypeScript interfaces for consent requests | v1.13.10 | 2026-01-17 |
| #12 | Legacy compat - Added deprecation warning for CommandHandler | v1.13.10 | 2026-01-17 |
| #14 | Magic strings - Converted constants.py to str,Enum with validation helpers | v1.13.10 | 2026-01-17 |
| #16 | Container deployment - Dockerfile, docker-compose, K8s manifests | v1.13.10 | 2026-01-17 |

---

## Refactoring Priority Matrix

| Priority | Category | Effort | Impact |
|----------|----------|--------|--------|
| ~~**Critical**~~ | ~~Global state~~ | ~~High~~ | ✅ Done |
| **Critical** | Monolithic files | High | Maintainability |
| ~~**Critical**~~ | ~~Silent errors~~ | ~~Medium~~ | ✅ Done |
| ~~**High**~~ | ~~Container tools duplication~~ | ~~Medium~~ | ✅ Done |
| ~~**High**~~ | ~~Consent duplication~~ | ~~Medium~~ | ✅ Done |
| ~~**High**~~ | ~~Circular imports~~ | ~~Medium~~ | ✅ Documented |
| ~~**High**~~ | ~~eval() usage~~ | ~~Low~~ | ✅ Done |
| ~~**Medium**~~ | ~~Type hints~~ | ~~Medium~~ | ✅ Partial |
| ~~**Medium**~~ | ~~HTTP error handling~~ | ~~Medium~~ | ✅ Done |
| ~~**Medium**~~ | ~~Config complexity~~ | ~~Medium~~ | ✅ Done |
| ~~**Low**~~ | ~~Legacy compatibility~~ | ~~Low~~ | ✅ Done |
| ~~**Low**~~ | ~~Magic strings~~ | ~~Low~~ | ✅ Done (constants.py) |

---

## Files Most in Need of Refactoring

1. ~~**`ppxai/server/http.py`**~~ - ✅ Done (SessionManager extracted)
2. ~~**`ppxai/commands.py`**~~ - ✅ Done (Command Factory pattern in `commands/` package)
3. ~~**`ppxai/config.py`**~~ - ✅ Done (Split into `config/` package with ConfigStore)
4. **`ppxai/engine/client.py`** - Extract tool execution, message building
5. ~~**`ppxai/engine/tools/builtin/container.py`**~~ - ✅ Done (refactored to CLITool hierarchy)
6. **`vscode-extension/src/chatPanel.ts`** - Extract handlers, formatters, UI

---

## How to Use This Document

1. **Before starting work:** Check if your area has known debt
2. **After fixing an item:** Move it to "Completed Items" with version and date
3. **Found new debt:** Add it with appropriate priority
4. **Review regularly:** During planning, assess what can be addressed

# Technical Debt Tracker

**Last Updated:** 2026-01-15
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
| [ppxai/commands.py](../ppxai/commands.py) | 2,404 | 68+ methods in CommandHandler class | Open |
| [ppxai/server/http.py](../ppxai/server/http.py) | 2,247 | HTTP + session + consent mixed | ✅ SessionManager extracted |
| [ppxai/engine/client.py](../ppxai/engine/client.py) | 2,035 | Core logic, providers, tools, sessions | Open |
| [ppxai/config.py](../ppxai/config.py) | 1,352 | 90+ functions | ⚠️ Blocked (see below) |
| [vscode-extension/src/chatPanel.ts](../vscode-extension/src/chatPanel.ts) | 5,061 | Massive event handling | Open |

**Large Functions:**
- `commands.py:1438-1609` (handle_show): 172 lines
- `client.py:1100-1400` (chat loop): 300+ lines

**config.py Package Conversion - Blocked:**
Attempted conversion to `config/` package failed due to Python import mechanics:
- Tests patch `ppxai.config._config` module variable directly
- Re-exporting `_config` from package creates a copy, not a reference
- Patching the package's `_config` doesn't affect the implementation module's `_config`
- Would require rewriting 15+ tests to patch `ppxai._config_impl._config` instead

**Recommendation:**
- config.py: Keep as single file, add section documentation (lower priority)
- commands.py: Can be safely split with method extraction (high priority)
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

**Status:** Open

**TypeScript (any types):**
- `http.py:15` - `metadata?: any`
- `chatPanel.ts:574, 639` - `data: any`
- `backend.ts:25, 64` - `result?: any`, `resolve: (value: any) => void`

**Python:**
- Various provider methods returning `None` without type hints
- Tool manager signatures inconsistent

**Recommendation:** Create discriminated union types; define proper interfaces.

---

### 9. Inconsistent Error Handling in HTTP Endpoints

**Status:** Open
**File:** [ppxai/server/http.py](../ppxai/server/http.py)

**Mixed patterns:**
- HTTPException (standard): lines 825, 873, 948
- Silent pass: lines 292, 300, 1459, 1519
- JSONResponse for errors: line 464

**Recommendation:** Standardize on HTTPException; use custom exception handlers.

---

### 10. Configuration Complexity

**Status:** Open
**File:** [ppxai/config.py](../ppxai/config.py) (1,352 lines)

**Issues:**
- 90+ functions in single file
- Built-in provider config hardcoded (lines 66-154)
- No clear separation: defaults vs user config vs session overrides

**Recommendation:** Split into:
- `config/defaults.py`
- `config/providers.py`
- `config/tools.py`
- `config/schema.py`
- `ConfigManager` class

---

### 11. Abrupt Process Termination

**Status:** Open
**File:** [ppxai/server/http.py](../ppxai/server/http.py)

- Line 169: `os._exit(0)`
- Line 590: `os._exit(0)`

**Issue:** Bypasses cleanup handlers (atexit), skips resource cleanup.

**Recommendation:** Use proper asyncio shutdown or SystemExit.

---

## Low Priority

### 12. Legacy Backward Compatibility Code

**Status:** Open
**File:** [ppxai/commands.py:222-298](../ppxai/commands.py)

```python
def __init__(self, client_or_api_key, api_key_or_model: str = None, ...):
    """Supports both old and new signatures for backward compatibility."""
```

**Issue:** Complex constructor with dual-purpose parameters, no deprecation warning.

**Recommendation:** Add deprecation warning; set EOL date (e.g., v2.0.0).

---

### 13. Version Marker Comments

**Status:** Open
**Scope:** Throughout codebase

**Pattern:** Code annotated with version numbers (v1.11.0, v1.12.0, v1.13.x) scattered as comments.

**Impact:** Maintenance burden, harder to track when compatibility code can be removed.

**Recommendation:** Extract compatibility layer with clear EOL dates.

---

### 14. Magic String Literals

**Status:** Open

**Examples:**
- Response parsing: `'y', 'n', 'yes', 'no', 'always', 'never'`
- Event types: `'chat', 'clear', 'save', 'saveAnswer'`
- Command names: `'explain', 'test', 'docs', 'debug', 'implement'`

**Recommendation:** Use enums for command types and response types.

---

### 15. TypeScript let vs const

**Status:** Open
**File:** [vscode-extension/src/chatPanel.ts](../vscode-extension/src/chatPanel.ts)

Multiple `let` declarations that should be `const` (no reassignment):
- Lines 179, 317, 357, 481, 658, 659, 823, 1215, 1338, 1352-1353

**Recommendation:** Use `const` for immutable bindings.

---

### 16. Container Deployment Support

**Status:** Open
**Scope:** New files needed

**Issue:** No containerized deployment support exists:
- No `Dockerfile` for building container images
- No `docker-compose.yaml` for local development
- No Kubernetes manifests for orchestrated deployment
- No `/health` endpoint for container health checks
- No `/ready` endpoint for readiness probes

**Impact:** Cannot deploy ppxai-server in containerized environments (Docker, Podman, Kubernetes).

**Files to Create:**
```
ppxai/
├── Dockerfile                    # Multi-stage build
├── docker-compose.yaml           # Local development
└── kubernetes/
    ├── deployment.yaml           # Deployment spec
    ├── service.yaml              # Service exposure
    ├── configmap.yaml            # Config injection
    └── secret.yaml               # API keys template
```

**Recommendation:**
1. Add `/health` and `/ready` endpoints to http.py
2. Create Dockerfile with multi-stage build (builder + runtime)
3. Create docker-compose.yaml for local testing
4. Create Kubernetes manifests for production deployment
5. Document environment variable configuration for secrets

---

## Completed Items

Items moved here after being addressed:

| Item | Description | Fixed In | Date |
|------|-------------|----------|------|
| #1 | Global state management - SessionManager singleton with thread safety | v1.13.10 | 2026-01-14 |
| #3 | Silent error handling - Added selective logging to 22 instances | v1.13.10 | 2026-01-15 |
| #4 | Container tools code duplication - refactored to CLITool hierarchy | v1.13.10 | 2026-01-14 |
| #5 | Consent Manager duplication - Extracted BaseConsentManager class | v1.13.10 | 2026-01-15 |
| #6 | Import structure - Refactored commands.py to DAG imports, updated ARCHITECTURE.md | v1.13.10 | 2026-01-15 |
| #7 | eval() usage - Replaced with AST-based safe evaluation | v1.13.10 | 2026-01-15 |

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
| **Medium** | Type hints | Medium | IDE support |
| **Medium** | HTTP error handling | Medium | Consistency |
| **Medium** | Config complexity | Medium | Maintainability |
| **Low** | Legacy compatibility | Low | Code clarity |
| **Low** | Magic strings | Low | Type safety |

---

## Files Most in Need of Refactoring

1. ~~**`ppxai/server/http.py`**~~ - ✅ Done (SessionManager extracted)
2. **`ppxai/commands.py`** - Split into `commands/` package
3. **`ppxai/config.py`** - Split into `config/` package
4. **`ppxai/engine/client.py`** - Extract tool execution, message building
5. ~~**`ppxai/engine/tools/builtin/container.py`**~~ - ✅ Done (refactored to CLITool hierarchy)
6. **`vscode-extension/src/chatPanel.ts`** - Extract handlers, formatters, UI

---

## How to Use This Document

1. **Before starting work:** Check if your area has known debt
2. **After fixing an item:** Move it to "Completed Items" with version and date
3. **Found new debt:** Add it with appropriate priority
4. **Review regularly:** During planning, assess what can be addressed

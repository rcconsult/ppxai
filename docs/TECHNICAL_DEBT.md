# Technical Debt Tracker

**Last Updated:** 2026-01-14
**Version:** v1.13.10

This document tracks identified technical debt and refactoring opportunities in the ppxai codebase. Items are removed as they are addressed.

---

## Critical Priority

### 1. Global State Management

**Status:** Open
**Files:** [ppxai/server/http.py](../ppxai/server/http.py), [ppxai/config.py](../ppxai/config.py)

**Issue:** Excessive use of global variables for session management, consent tracking, and configuration.

**Examples in http.py:**
- Line 41: `sessions: dict[str, dict]`
- Line 45: `default_engine: Optional[EngineClient]`
- Line 63: `pending_consent_requests: dict[tuple[str, str], asyncio.Future]`
- Multiple `global` statements: lines 77, 116, 134, 145, 174, 192, 227, 278, 579, 664, 1644, 1693

**Impact:** Race conditions, difficult to test, reduced maintainability.

**Recommendation:** Refactor to `SessionManager` class with dependency injection.

---

### 2. Monolithic Files

**Status:** Open

| File | Lines | Issue |
|------|------:|-------|
| [ppxai/commands.py](../ppxai/commands.py) | 2,404 | 68+ methods in CommandHandler class |
| [ppxai/server/http.py](../ppxai/server/http.py) | 2,247 | HTTP + session + consent mixed |
| [ppxai/engine/client.py](../ppxai/engine/client.py) | 2,035 | Core logic, providers, tools, sessions |
| [ppxai/config.py](../ppxai/config.py) | 1,352 | 90+ functions |
| [vscode-extension/src/chatPanel.ts](../vscode-extension/src/chatPanel.ts) | 5,061 | Massive event handling |

**Large Functions:**
- `commands.py:1438-1609` (handle_show): 172 lines
- `client.py:1100-1400` (chat loop): 300+ lines

**Recommendation:** Extract into focused modules/packages.

---

### 3. Silent Error Handling

**Status:** Open
**Scope:** 90+ instances of `except: pass` throughout codebase

**Affected Files:**
- `ppxai/usage.py:85`
- `ppxai/commands.py:315, 322, 1073, 1082, 1366, 1423, 1656`
- `ppxai/server/http.py:285, 899, 1459, 1519, 1854`
- `ppxai/engine/client.py:220, 848, 857, 866, 897, 929, 951, 1362`
- `ppxai/common/consent.py:123, 130, 137, 474, 480, 486`

**Impact:** Hidden bugs, difficult debugging, no error tracking.

**Recommendation:** Replace with logging or explicit error handling.

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

**Status:** Open
**File:** [ppxai/common/consent.py](../ppxai/common/consent.py)

**Issue:** ~250 lines duplicated between:
- `ConsentManager` (async): lines 49-425
- `SyncConsentManager` (sync): lines 426-679

**Recommendation:** Use composition or async-to-sync wrapper pattern.

---

### 6. Circular Import Dependencies

**Status:** Open

**Pattern:** Lazy imports inside functions to break circular dependencies.

**Examples:**
- `commands.py:187-189, 234, 260-261, 281, 297`
- `client.py:324, 613, 748, 774, 839`
- `commands.py:1540-1546` (data parsing imports)

**Impact:** Runtime import failures, performance penalty, indicates architecture issues.

**Recommendation:** Refactor module boundaries; use Protocol/ABC for type hints.

---

### 7. Dangerous eval() Usage

**Status:** Open
**File:** [ppxai/engine/tools/builtin/calculator.py:24](../ppxai/engine/tools/builtin/calculator.py)

```python
result = eval(expression, {"__builtins__": {}}, {})
```

**Risk:** Even with sandboxed globals, eval can be exploited via attribute access.

**Recommendation:** Use `ast.literal_eval()` or `simpleeval` library.

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

## Completed Items

Items moved here after being addressed:

| Item | Description | Fixed In | Date |
|------|-------------|----------|------|
| #4 | Container tools code duplication - refactored to CLITool hierarchy | v1.13.10 | 2026-01-14 |

---

## Refactoring Priority Matrix

| Priority | Category | Effort | Impact |
|----------|----------|--------|--------|
| **Critical** | Global state | High | Race conditions, testability |
| **Critical** | Monolithic files | High | Maintainability |
| **Critical** | Silent errors | Medium | Debugging |
| ~~**High**~~ | ~~Container tools duplication~~ | ~~Medium~~ | ✅ Done |
| **High** | Consent duplication | Medium | Code size |
| **High** | Circular imports | Medium | Reliability |
| **High** | eval() usage | Low | Security |
| **Medium** | Type hints | Medium | IDE support |
| **Medium** | HTTP error handling | Medium | Consistency |
| **Medium** | Config complexity | Medium | Maintainability |
| **Low** | Legacy compatibility | Low | Code clarity |
| **Low** | Magic strings | Low | Type safety |

---

## Files Most in Need of Refactoring

1. **`ppxai/server/http.py`** - Extract SessionManager class
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

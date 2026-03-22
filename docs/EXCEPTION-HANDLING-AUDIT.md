# Exception Handling Audit — v1.17.1

**Date:** 2026-03-22
**Scope:** ppxai/ core (engine, commands, server, config, common, rich, tui/app.py)
**Total findings:** 40 swallowed exceptions

---

## Categories

### A — CORRECT (14 instances)
Truly ignorable: expected failures, graceful degradation, lifecycle guards.

| File | Line | Exception | Why OK |
|------|------|-----------|--------|
| `engine/bootstrap.py` | 519, 523 | ValueError | Expected: YAML front matter parsing (missing keys) |
| `engine/bootstrap.py` | 697 | subprocess errors | Expected: git not available |
| `engine/chat.py` | 360 | CancelledError | Expected: task cancellation pattern |
| `engine/tools/builtin/datetime_tool.py` | 25, 33, 35 | ImportError, Exception | Expected: timezone lib detection |
| `engine/tools/builtin/editor.py` | 48 | OSError | Expected: atomic rename fallback |
| `engine/tools/builtin/web.py` | 113 | ImportError | Expected: ddgs package detection |
| `server/routes/preview.py` | 64, 121 | OSError | Expected: sibling file scan (network drive) |
| `server/routes/files.py` | 68, 73, 377 | ValueError, PermissionError | Expected: file access guards |
| `common/async_compat.py` | 91 | RuntimeError | Expected: event loop detection |

### B — SHOULD LOG (18 instances)
Non-critical but silently discarded — add logging for debuggability.

| File | Line | Exception | Operation | Proposed Fix |
|------|------|-----------|-----------|-------------|
| `engine/chat.py` | 396 | Exception | Tool usage tracking | `logger.debug(f"Tool usage tracking: {e}")` |
| `engine/context.py` | 211 | Exception | Clipboard read | `logger.debug(f"Clipboard: {e}")` |
| `engine/context.py` | 245 | Exception | Git root detection | `logger.debug(f"Git root: {e}")` |
| `engine/context.py` | 280 | Exception | Fetch URL | `logger.debug(f"URL fetch: {e}")` |
| `engine/context.py` | 480 | Exception | Tree context | `logger.debug(f"Tree: {e}")` |
| `engine/context.py` | 571 | PermissionError | File read | `logger.debug(f"Permission: {e}")` |
| `engine/session.py` | 593 | Exception | Session load | `logger.warning(f"Session load: {e}")` |
| `engine/session.py` | 853 | Exception | State file read | `logger.debug(f"State file: {e}")` |
| `engine/session_ops.py` | 37 | Exception | Provider restore | `logger.warning(f"Provider restore: {e}")` |
| `commands/display.py` | 342-362 | ImportError, Exception | Data format detection | `logger.debug(f"Format detect: {e}")` |
| `commands/provider.py` | 301, 336 | AttributeError, TypeError | Provider config access | `logger.debug(f"Provider config: {e}")` |
| `commands/tools.py` | 186, 197 | Exception | Tool display | `logger.debug(f"Tool display: {e}")` |
| `config/features.py` | 69 | IOError | Config save | `logger.warning(f"Config save: {e}")` |
| `rich/main.py` | 587, 781, 792 | Exception | Session auto-save, cleanup | `logger.debug(f"Cleanup: {e}")` |
| `rich/ui_components.py` | 271 | Exception | Theme rendering | `logger.debug(f"Theme: {e}")` |

### C — SHOULD NARROW (5 instances)
Exception type too broad — should catch specific exceptions.

| File | Line | Current | Should Be |
|------|------|---------|-----------|
| `engine/session.py` | 593 | `Exception` | `(json.JSONDecodeError, IOError, KeyError)` |
| `engine/session.py` | 853 | `Exception` | `(json.JSONDecodeError, IOError)` |
| `engine/checkpoint_ops.py` | 129 | `CalledProcessError` | OK type, but should log |
| `common/consent.py` | 647, 705 | `Exception` | `(re.error, ValueError)` |
| `config/loader.py` | 79 | `Exception` | `(UnicodeDecodeError, IOError)` |

### D — NEEDS REVIEW (3 instances)
Potentially masks real problems.

| File | Line | Exception | Risk |
|------|------|-----------|------|
| `engine/session.py:593` | Session load swallows ALL errors | User gets "session not found" for a corrupt session instead of the real error |
| `engine/session_ops.py:37` | Provider restore silently fails | After session load, wrong provider may be active with no notification |
| `rich/main.py:587` | Session save on quit swallowed | User thinks session was saved but it may have failed |

---

## Proposed Action

**Phase 1 (this PR):** Fix the 18 SHOULD LOG items by adding `logger.debug/warning`.
**Phase 2 (v1.17.2):** Narrow the 5 TOO BROAD exception types.
**Phase 3 (v1.18.x):** Review the 3 NEEDS REVIEW items for proper error propagation.

# Legacy Code Modernization Plan

**Created:** 2025-12-26
**Target Version:** v1.12.0
**Status:** Planning

## Executive Summary

This document outlines the plan to eliminate legacy code and complete the migration to the new engine-based architecture introduced in v1.7.0 and refined through v1.11.x.

## Current Architecture State

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER INTERFACES                          │
├──────────────────────┬──────────────────────┬───────────────────┤
│      TUI (main.py)   │   VSCode Extension   │   Future CLIs     │
│  ┌────────────────┐  │  ┌────────────────┐  │                   │
│  │ EngineClient   │◄─┼──│ HTTP/SSE       │  │                   │
│  │ (PRIMARY)      │  │  │ ppxai-server   │  │                   │
│  ├────────────────┤  │  └────────────────┘  │                   │
│  │ AIClient       │  │                      │                   │
│  │ (FALLBACK)     │  │                      │                   │
│  └────────────────┘  │                      │                   │
└──────────────────────┴──────────────────────┴───────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                      ENGINE LAYER (NEW)                         │
├─────────────────────────────────────────────────────────────────┤
│  ppxai/engine/                                                  │
│  ├── client.py         EngineClient facade                      │
│  ├── session.py        Session management                       │
│  ├── context.py        @file, @git, @tree injection            │
│  ├── providers/        BaseProvider abstraction                 │
│  │   ├── base.py                                                │
│  │   ├── perplexity.py                                          │
│  │   └── openai_compat.py                                       │
│  └── tools/            Modern tool system                       │
│      ├── manager.py                                             │
│      └── builtin/      File editing, shell, etc.               │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                     LEGACY LAYER (DEPRECATED)                   │
├─────────────────────────────────────────────────────────────────┤
│  ppxai/client.py              AIClient, PerplexityClient        │
│  perplexity_tools_prompt_based.py   PerplexityClientPromptTools │
│  tool_manager.py              Legacy MCP tool loading           │
│  ppxai/server.py              Backward compat wrapper           │
└─────────────────────────────────────────────────────────────────┘
```

## Priority Classification

### P0 - CRITICAL (Remove in v1.12.0)
Issues that cause confusion, bugs, or maintenance burden.

### P1 - HIGH (Remove in v1.12.0-v1.13.0)
Legacy code that's actively maintained but should be eliminated.

### P2 - MEDIUM (Remove in v1.13.0+)
Backward compatibility code that can stay longer.

### P3 - LOW (Keep indefinitely or until next major version)
Config compatibility, deprecated exports for external users.

---

## Detailed Findings and Actions

### 1. Dual Code Paths in main.py

**Location:** `ppxai/main.py` lines 264-308
**Priority:** P0 - CRITICAL
**Issue:** Two code paths for chat - EngineClient (primary) and AIClient (fallback)

**Current Code:**
```python
if handler.engine_client:
    # Use engine with event-based streaming (v1.11.4+)
    async for event in handler.engine_client.chat(user_input, stream=True):
        ...
else:
    # Fallback path: EngineClient not available (shouldn't happen)
    console.print("[yellow]Warning: Using legacy client...[/yellow]")
    response = client.chat(augmented_input, current_model, stream=True)
```

**Problem:**
- Fallback path is dead code (EngineClient always available since v1.7.0)
- Legacy path doesn't support @git/@tree context
- Maintenance burden of two code paths

**Action:**
1. Remove fallback path entirely
2. Remove `AIClient` instantiation from main loop
3. Update error handling to fail fast if EngineClient unavailable

---

### 2. PerplexityClientPromptTools Naming

**Location:** `perplexity_tools_prompt_based.py`
**Priority:** P1 - HIGH
**Issue:** Class name is misleading - works with ALL providers, not just Perplexity

**Current State:**
- Line 1338: Alias added `AIClientWithTools = PerplexityClientPromptTools`
- Both names exported
- Internal code uses old name

**Action:**
1. v1.12.0: Add deprecation warning when old name used
2. v1.13.0: Remove old name, keep only `AIClientWithTools`
3. Eventually: Remove entirely when EngineClient tools are complete

---

### 3. Tool Enable/Disable Client Swapping

**Location:** `ppxai/commands.py` lines 620-690
**Priority:** P1 - HIGH
**Issue:** Swaps between `AIClient` and `PerplexityClientPromptTools` to enable/disable tools

**Current Pattern:**
```python
# Enable: Upgrade client
if not isinstance(self.client, self.PerplexityClientPromptTools):
    tool_client = self.PerplexityClientPromptTools(...)
    self.client = tool_client

# Disable: Downgrade client
if isinstance(self.client, self.PerplexityClientPromptTools):
    regular_client = AIClient(...)
    self.client = regular_client
```

**Problem:**
- Complex state management
- Requires history sync between clients
- EngineClient handles this with a simple flag

**Action:**
1. Use `engine_client.enable_tools()` / `engine_client.disable_tools()` exclusively
2. Remove client swapping logic
3. Remove `AIClient` instantiation in commands.py

---

### 4. Multiple isinstance() Checks

**Location:** `ppxai/commands.py` lines 420, 630, 697, 709, 720, 731, 757
**Priority:** P1 - HIGH
**Issue:** Repeated pattern checking both legacy and engine

**Current Pattern:**
```python
tools_enabled = (
    (self.engine_client and self.engine_client.tools_enabled) or
    isinstance(self.client, self.PerplexityClientPromptTools)
)
```

**Action:**
1. Replace with single check: `self.engine_client.tools_enabled`
2. Remove all `isinstance()` checks for tool detection

---

### 5. History Synchronization

**Location:** Multiple files
**Priority:** P1 - HIGH
**Issue:** Dual history tracking between legacy client and engine

**Affected:**
- `commands.py` lines 221-227: Syncs from AIClient to engine
- `ppxai/tui_logger.py` line 134
- `ppxai/common/logger.py` line 179

**Problem:**
- Both `self.client.conversation_history` and `self.engine_client.session.messages` maintained
- One-way sync (legacy → engine)
- Potential desync bugs

**Action:**
1. Use engine session as single source of truth
2. Remove `conversation_history` from AIClient
3. Remove sync code

---

### 6. Legacy tool_manager.py

**Location:** `tool_manager.py` (299 lines)
**Priority:** P1 - HIGH
**Issue:** Duplicates functionality in `ppxai/engine/tools/manager.py`

**Usage:**
- `commands.py` line 236: `from tool_manager import load_tool_config`
- Only used for MCP configuration loading

**Action:**
1. Migrate MCP config loading to engine tool manager
2. Delete `tool_manager.py`

---

### 7. Dead Code: process_file_references()

**Location:** `ppxai/commands.py` lines 960-1015
**Priority:** P2 - MEDIUM
**Issue:** Never called - engine's ContextInjector handles all references

**Action:**
1. Verify it's truly unused (grep for calls)
2. Remove method if unused

---

### 8. Legacy Server Wrapper

**Location:** `ppxai/server.py` (15 lines)
**Priority:** P3 - LOW
**Issue:** Backward compat wrapper, just re-exports from new location

**Content:**
```python
# Re-export from new location for backward compatibility
from .server.jsonrpc import JsonRpcServer, main
```

**Action:**
- Keep for external compatibility
- Add deprecation notice in docstring
- Remove in v2.0.0

---

### 9. CUSTOM_* Environment Variables

**Location:** `ppxai/config.py` lines 221-257
**Priority:** P3 - LOW
**Issue:** Legacy config method, but properly abstracted

**Action:**
- Keep for backward compatibility
- Document migration path to ppxai-config.json
- Consider deprecation warning in v1.13.0

---

### 10. PerplexityClient Alias

**Location:** `ppxai/client.py` line 447, `ppxai/__init__.py` line 73
**Priority:** P3 - LOW
**Definition:** `PerplexityClient = AIClient`

**Action:**
- Keep for external compatibility
- Remove when AIClient is removed

---

## Refactoring Phases

### Phase 1: Clean Up Dead Code (v1.11.7)
**Risk: LOW | Effort: LOW**

- [ ] Remove fallback path in main.py (lines 298-308)
- [ ] Remove `process_file_references()` if unused
- [ ] Remove dead context_injector in client.py line 86-87
- [ ] Add deprecation warnings to legacy classes

### Phase 2: Unify Tool Management (v1.12.0)
**Risk: MEDIUM | Effort: MEDIUM**

- [ ] Remove client swapping in commands.py
- [ ] Replace all `isinstance()` checks with engine flag
- [ ] Migrate MCP loading to engine tool manager
- [ ] Delete tool_manager.py
- [ ] Rename PerplexityClientPromptTools → AIClientWithTools

### Phase 3: Remove Legacy Clients (v1.13.0)
**Risk: HIGH | Effort: HIGH**

- [ ] Remove AIClient class
- [ ] Remove PerplexityClientPromptTools class
- [ ] Remove history sync code
- [ ] Update all tests to use EngineClient
- [ ] Remove backward compat exports

### Phase 4: Final Cleanup (v2.0.0)
**Risk: LOW | Effort: LOW**

- [ ] Remove server.py wrapper
- [ ] Remove CUSTOM_* env var support
- [ ] Remove PerplexityClient alias

---

## Test Migration Plan

13+ test files currently use legacy classes:
- `tests/test_prompt_tools.py`
- `tests/test_shell_command_tool.py`
- `tests/test_file_tool.py`
- And more...

**Strategy:**
1. Create equivalent tests using EngineClient
2. Run both test sets in parallel during transition
3. Remove legacy tests after Phase 3

---

## Validation Checklist

Before removing legacy code, verify:

- [ ] All TUI features work with EngineClient only
- [ ] VSCode extension works (uses HTTP server, not affected)
- [ ] All tests pass or are migrated
- [ ] @file, @git, @tree context injection works
- [ ] Tool consent system works
- [ ] Provider switching works
- [ ] Model switching works
- [ ] Session save/load works
- [ ] Streaming works
- [ ] Error handling works

---

## Files to Delete (Final State)

After all phases complete:

```
DELETE: ppxai/client.py               (447 lines)
DELETE: perplexity_tools_prompt_based.py (1,342 lines)
DELETE: tool_manager.py               (299 lines)
DELETE: ppxai/server.py               (15 lines)
TOTAL:  ~2,100 lines of legacy code removed
```

---

## Metrics

| Metric | Before | After |
|--------|--------|-------|
| Lines of legacy code | ~2,100 | 0 |
| Dual code paths | 3 | 0 |
| isinstance() checks for tools | 7 | 0 |
| Client classes | 3 (AIClient, PerplexityClientPromptTools, PerplexityClient) | 1 (EngineClient) |
| Tool managers | 2 | 1 |
| History sources | 2 | 1 |

---

## References

- [Architecture Refactoring Plan](PROVIDER-ABSTRACTION-REFACTORING.md)
- [v1.11.0 Agentic Workflow Plan](v1.11.0-agentic-workflow-plan.md)
- [Engine Layer Documentation](../ppxai/engine/README.md)

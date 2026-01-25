# ppxai Architecture

This document describes the high-level architecture and import patterns used in the ppxai codebase.

## Module Hierarchy

```
ppxai/
├── config.py          # LEAF: No ppxai imports (safe to import anywhere)
├── themes.py          # LEAF: No ppxai imports
├── prompts.py         # LEAF: No ppxai imports
├── utils.py           # LEAF: No ppxai imports
├── common/            # Low-level utilities
│   ├── logger.py      # LEAF: No ppxai imports
│   └── consent.py     # Uses logger only
├── engine/            # Core business logic
│   ├── types.py       # LEAF: No ppxai imports
│   ├── bootstrap.py   # LEAF: Bootstrap context parsing (v1.14.0)
│   ├── providers/     # Provider implementations
│   ├── tools/         # Tool system
│   │   ├── manager.py # Uses types only
│   │   └── builtin/   # Built-in tools (TYPE_CHECKING pattern)
│   └── client.py      # Facade (uses bootstrap.py)
├── server/            # HTTP server
│   └── http.py        # Uses engine, config
├── commands/          # Command handlers (v1.13.10 factory pattern)
│   ├── factory.py     # CommandFactory and CommandSpec
│   ├── system.py      # /help, /status, /theme
│   └── utility.py     # /context, /debug-log
└── main.py            # Entry point
```

## Import Patterns

### 1. TYPE_CHECKING Pattern (Static Analysis Only)

Used in builtin tools to avoid circular imports with manager.py and client.py.

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..manager import ToolManager
    from ...client import EngineClient

def register_tools(manager: 'ToolManager', engine: 'EngineClient'):
    ...
```

**Why**: Type hints are evaluated lazily (as strings) at runtime, so the imports
inside TYPE_CHECKING block are only needed for static type checkers like mypy.

**Files using this pattern**:
- `ppxai/engine/tools/builtin/*.py` (all builtin tools)
- `ppxai/server/session_manager.py`

### 2. DAG Import Structure

The codebase follows a Directed Acyclic Graph (DAG) for imports:

```
config.py, types.py, logger.py  (leaf modules - no ppxai imports)
           ↓
engine/providers/, engine/tools/manager.py
           ↓
engine/client.py
           ↓
commands.py, server/http.py
           ↓
main.py (entry point)
```

**Rule**: Each module only imports from modules "below" it in the hierarchy.
No circular dependencies exist in the current codebase.

**Verified**: `commands.py` uses top-level imports for all dependencies
including `EngineClient`, `web_premium`, and config functions

### 3. Clean Leaf Modules

Modules that have no ppxai imports and can be imported by anything.

- `ppxai/config.py` - Configuration loading and defaults
- `ppxai/themes.py` - Theme definitions
- `ppxai/prompts.py` - Prompt templates
- `ppxai/utils.py` - Utility functions
- `ppxai/engine/types.py` - Type definitions (Message, Event, etc.)
- `ppxai/engine/bootstrap.py` - Bootstrap context parsing (v1.14.0)
- `ppxai/common/logger.py` - Logging setup

These form the "bottom" of the import hierarchy.

### 4. Bootstrap Context (v1.14.0)

The bootstrap module provides project-specific AI instructions:

```
ppxai/engine/bootstrap.py
├── BootstrapContext class
│   ├── base_instructions: str      # Content below YAML ---
│   ├── provider_hints: dict        # provider_id → list[str]
│   ├── model_hints: dict           # regex pattern → list[str]
│   ├── get_prompt_for(provider, model) → str
│   └── get_active_hints_for(provider, model) → dict
│
└── Helper functions:
    ├── find_bootstrap_file(directory, aliases) → Path
    ├── get_bootstrap_files_config() → list[str]
    └── is_bootstrap_enabled() → bool
```

**Integration with client.py:**
- `EngineClient._bootstrap_context: BootstrapContext` stores parsed context
- `set_provider()` and `set_model()` trigger prompt rebuild
- `get_active_hints()` returns detailed breakdown for debugging

## Architectural Layers

```
┌─────────────────────────────────────────────────────┐
│                    Entry Points                      │
│              main.py, server/http.py                 │
├─────────────────────────────────────────────────────┤
│                   Command Layer                      │
│                    commands.py                       │
├─────────────────────────────────────────────────────┤
│                   Engine Layer                       │
│     client.py, session.py, providers/, tools/        │
├─────────────────────────────────────────────────────┤
│                   Common Layer                       │
│           config.py, types.py, logger.py             │
└─────────────────────────────────────────────────────┘
```

**Rule**: Lower layers should NOT import from higher layers.

## Adding New Modules

When adding a new module:

1. **Determine the layer** - Where does it fit in the hierarchy?
2. **Check for cycles** - Will importing it create a circular dependency?
3. **Use appropriate pattern**:
   - If needed only for type hints → TYPE_CHECKING
   - If needed at runtime but causes cycle → Lazy import
   - If no cycle risk → Regular import

## Testing Import Health

To verify no circular imports exist:

```bash
python -c "import ppxai"
```

If this fails with ImportError, there's a circular dependency.

---

## Critical Architecture Patterns

### Transactional State Management (GitOps-Style)

**Added:** v1.15.0
**Status:** Critical pattern for AI/agent workflows
**Location:** `ppxai/tui/widgets/status_bar.py` (BadgeTransaction)

#### Problem

AI agents perform multi-step operations that must succeed atomically or fail completely. Partial state updates create inconsistent UI, broken sessions, and user confusion.

**Examples of problematic partial updates:**
- Provider switch succeeds, but model update fails → inconsistent state
- 3 files added to context, 4th fails → partial context injection
- Badge updates half-applied → confusing status display

#### Solution: Checkpoint/Commit/Rollback Pattern

```python
class BadgeTransaction:
    """Transaction for atomic badge updates with rollback support.

    GitOps-style API:
    1. Checkpoint current state (automatic on enter)
    2. Stage operations (add, update, remove, hide, show)
    3. Commit changes (atomic - all succeed or all rollback)
    4. Rollback on failure with user-friendly error messages
    """

    def checkpoint(self) -> None:
        """Backup current badge state."""

    def commit(self) -> tuple[bool, Optional[str]]:
        """Apply staged changes atomically.
        Returns: (success, error_message)
        """

    def rollback(self) -> None:
        """Restore badge state from backup."""
```

#### Usage Pattern

```python
# Atomic multi-operation update
with status_bar.transaction() as txn:
    txn.add("tokens", "Tokens", "1234")
    txn.update("provider", "ollama")
    txn.remove("cost")
    success, error = txn.commit()
    if not success:
        notify_user(f"Update failed: {error}")
        # State automatically rolled back
```

#### Key Features

**1. Validation Phase**
All operations validated before any are applied. Prevents partial updates.

**2. Atomic Application**
Either all operations succeed or none do. No inconsistent intermediate states.

**3. Automatic Rollback**
On failure or exception, state restored to checkpoint. System remains consistent.

**4. User-Friendly Errors**
Clear error messages explain what failed and why.

**5. Chainable Operations**
Fluent API: `txn.add(...).update(...).remove(...).commit()`

**6. Exception Safety**
Context manager auto-rollbacks on exceptions via `__exit__`.

#### Where to Apply This Pattern

**Provider/Model Switching:**
```python
with config_transaction() as txn:
    txn.set_provider("ollama")
    txn.set_model("qwen2.5-coder:32b")
    txn.update_tools(enabled=True)
    txn.update_context_limit(32000)
    success, error = txn.commit()
```

**Context Injection:**
```python
with context_transaction() as txn:
    txn.inject_file("src/main.py")
    txn.inject_file("tests/test_main.py")
    txn.inject_git_diff("HEAD~1")
    success, error = txn.commit()
```

**Session State Management:**
```python
with session_transaction() as txn:
    txn.add_message(user_message)
    txn.update_token_count(tokens_used)
    txn.update_cost(cost)
    txn.save_checkpoint()
    success, error = txn.commit()
```

**Multi-Step Tool Calls:**
```python
with tool_transaction() as txn:
    txn.read_file("config.json")
    txn.modify_config("api_key", new_value)
    txn.write_file("config.json")
    txn.git_commit("Update API key")
    success, error = txn.commit()
```

**UI State Synchronization:**
```python
with ui_transaction() as txn:
    txn.update_statusbar("provider", "ollama")
    txn.update_statusbar("model", "llama3:70b")
    txn.show_panel("side-panel")
    txn.update_title("ollama/llama3:70b")
    success, error = txn.commit()
```

#### Benefits for AI Agents

**State Consistency**
No partial updates that leave system in inconsistent state. Agent actions are atomic units.

**Error Recovery**
Automatic rollback on failure. User sees coherent error messages, not broken UI.

**User Trust**
Predictable behavior: operations complete fully or not at all. No "half-done" states.

**Debugging**
Clear transaction boundaries. Error messages identify which operation failed.

**Composability**
Transactions can be nested or chained. Complex workflows built from simple atomic units.

#### Implementation Guidelines

**1. Identify State Boundaries**
What constitutes a consistent state? What operations must happen together?

**2. Design Checkpoint Format**
What state needs backup? How to serialize/deserialize it?

**3. Implement Validation**
Check all operations before applying any. Fail fast with clear errors.

**4. Ensure Idempotent Rollback**
Rollback should work even if partially applied. Test with intentional failures.

**5. Provide Error Context**
Error messages should explain what failed, why, and what was attempted.

#### Testing Transactional Code

```python
def test_successful_transaction():
    """All operations succeed - state updated."""
    with transaction() as txn:
        txn.add("a", "A", "1")
        txn.add("b", "B", "2")
        success, error = txn.commit()
        assert success
        assert error is None

def test_failed_transaction_rollback():
    """One operation fails - all rollback."""
    initial_state = get_state()
    with transaction() as txn:
        txn.add("a", "A", "1")
        txn.add("a", "Duplicate", "2")  # Fails
        success, error = txn.commit()
        assert not success
        assert "already exists" in error
    assert get_state() == initial_state  # Rolled back

def test_exception_safety():
    """Exception during commit - auto rollback."""
    initial_state = get_state()
    try:
        with transaction() as txn:
            txn.add("a", "A", "1")
            raise RuntimeError("Simulated error")
    except RuntimeError:
        pass
    assert get_state() == initial_state  # Rolled back
```

#### Future Applications

This pattern should be applied to:
- ✅ StatusBar badge management (implemented)
- ⏳ EngineClient provider/model switching (planned)
- ⏳ Context injection (`@file`, `@git`, etc.) (planned)
- ⏳ Session state management (planned)
- ⏳ File operations with undo (planned)
- ⏳ Multi-step tool execution (planned)

**Rule:** Any operation that modifies multiple related pieces of state should use this pattern.

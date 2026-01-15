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
│   ├── providers/     # Provider implementations
│   ├── tools/         # Tool system
│   │   ├── manager.py # Uses types only
│   │   └── builtin/   # Built-in tools (TYPE_CHECKING pattern)
│   └── client.py      # Facade
├── server/            # HTTP server
│   └── http.py        # Uses engine, config
├── commands.py        # Command handlers
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
- `ppxai/common/logger.py` - Logging setup

These form the "bottom" of the import hierarchy.

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

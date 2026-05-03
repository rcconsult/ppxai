# Pattern: Protocol-Based Dependency Inversion

**Added:** v1.17.0
**Status:** **CRITICAL — Required for all cross-module type dependencies**
**Reference:** `ppxai/engine/types.py`

## Problem

Circular imports occur when module A imports from module B, and module B needs types from module A. Example: `client.py` → `tools/builtin/` → needs `EngineClient` from `client.py`.

## Solution: Protocols in Leaf Modules

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

## Where Protocols Are Defined

| Protocol | Location | Satisfying Class | Used By |
|----------|----------|-----------------|---------|
| `ToolEngineProtocol` | `engine/types.py` | `EngineClient` | All tool modules |
| `ToolManagerProtocol` | `engine/types.py` | `ToolManager` | All tool modules |
| `EngineClientProtocol` | `engine/types.py` | `EngineClient` | All command modules |

## Rules

1. **NEVER use `TYPE_CHECKING`** — it's a lazy import in disguise
2. **NEVER use `Any` to dodge a circular import** unless the parameter is truly duck-typed (e.g., thin adapter wrapping an opaque object)
3. When a direct import would create a cycle, define a `Protocol` in a leaf module
4. Protocols go in `engine/types.py` (for engine-layer types) or the appropriate leaf module
5. Use `@runtime_checkable` so protocols can be used with `isinstance()` checks

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
| `ProtocolHandler` | `engine/providers/wire/protocol.py` | the four wire handlers | `BaseProvider` + each provider |
| `SessionRestoreHost` | `tui/session_restore_ops.py` | `PPXAIDEApp` | `tui/session_restore_ops.py` |

## Rules

1. **NEVER use `TYPE_CHECKING`** — it's a lazy import in disguise

   > Enforced by grep, not by a test. As of 2026-09-20 production code has
   > **zero** `if TYPE_CHECKING:` blocks: `grep -rn "TYPE_CHECKING" ppxai/`
   > returns two hits, both prose in docstrings explaining why the idiom is
   > *not* used. The last real one lived in
   > `ppxai/tui/session_restore_ops.py`, which imported `PPXAIDEApp` that
   > way from 2026-06 until it was replaced with the `SessionRestoreHost`
   > protocol above — the exact circular-import case this pattern exists to
   > solve, sitting inside the layer the pattern was written for, unnoticed
   > for three months. If you are adding one, you are one `Protocol` away
   > from not needing it.
2. **NEVER use `Any` to dodge a circular import** unless the parameter is truly duck-typed (e.g., thin adapter wrapping an opaque object)
3. When a direct import would create a cycle, define a `Protocol` in a leaf module
4. Protocols go in `engine/types.py` (for engine-layer types) or the appropriate leaf module
5. Use `@runtime_checkable` so protocols can be used with `isinstance()` checks

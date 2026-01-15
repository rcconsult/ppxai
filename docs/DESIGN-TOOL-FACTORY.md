# Design: Tool Factory Pattern

**Status:** Proposed
**Created:** 2026-01-15
**Related:** [TECHNICAL_DEBT.md](TECHNICAL_DEBT.md) Item #6 (Import Structure)

---

## Problem Statement

The current tool system creates an import cycle between `client.py` and `builtin/__init__.py`:

```
client.py ──imports──> builtin/__init__.py ──needs type──> EngineClient (cycle!)
```

This is currently resolved using `TYPE_CHECKING` pattern - a workaround, not a solution.

Additionally:
- Tools are **statically defined** - adding a tool requires editing `builtin/__init__.py`
- No dynamic tool loading at runtime (unlike OpenWebUI)
- Tight coupling between tools and engine internals

---

## Proposed Solution: Tool Factory with Dependency Injection

### Architecture

```
                    ┌─────────────────┐
                    │  ToolFactory    │  (leaf module - no ppxai imports)
                    │  - registry     │
                    │  - get(name)    │
                    │  - call(...)    │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   filesystem.py       calculator.py         shell.py
   (self-registers)    (self-registers)    (self-registers)
```

### Key Components

#### 1. ToolFactory (new leaf module)

```python
# ppxai/engine/tools/factory.py
from typing import Callable, Dict, Any, Optional
from dataclasses import dataclass, field

@dataclass
class ToolSpec:
    """Tool specification - metadata + callable."""
    name: str
    description: str
    parameters: Dict[str, Any]
    fn: Callable
    requires_engine: bool = False  # Flag, not type reference
    requires_consent: bool = False
    category: str = "general"

class ToolFactory:
    """Central registry for all tools. Leaf module - no ppxai imports."""
    _registry: Dict[str, ToolSpec] = {}

    @classmethod
    def register(cls, spec: ToolSpec):
        """Register a tool specification."""
        cls._registry[spec.name] = spec

    @classmethod
    def get(cls, name: str) -> Optional[ToolSpec]:
        """Get tool spec by name."""
        return cls._registry.get(name)

    @classmethod
    def list_tools(cls) -> list[str]:
        """List all registered tool names."""
        return list(cls._registry.keys())

    @classmethod
    def list_by_category(cls, category: str) -> list[ToolSpec]:
        """List tools in a category."""
        return [t for t in cls._registry.values() if t.category == category]

    @classmethod
    def call(cls, name: str, args: dict, engine=None) -> Any:
        """Call a tool by name with dependency injection."""
        spec = cls._registry.get(name)
        if not spec:
            raise ValueError(f"Unknown tool: {name}")

        if spec.requires_engine:
            return spec.fn(**args, engine=engine)
        return spec.fn(**args)

    @classmethod
    def clear(cls):
        """Clear registry (for testing)."""
        cls._registry.clear()
```

#### 2. Tool Self-Registration

```python
# ppxai/engine/tools/builtin/filesystem.py
from ..factory import ToolFactory, ToolSpec

def read_file(path: str, engine=None) -> str:
    """Read file contents."""
    with open(path, 'r') as f:
        return f.read()

def write_file(path: str, content: str, engine=None) -> str:
    """Write content to file."""
    # Consent check via engine if provided
    if engine and hasattr(engine, 'request_file_consent'):
        approved, _ = engine.request_file_consent(path)
        if not approved:
            return f"Permission denied: {path}"

    with open(path, 'w') as f:
        f.write(content)
    return f"Written: {path}"

# Self-registration at module import time
ToolFactory.register(ToolSpec(
    name="read_file",
    description="Read contents of a file",
    parameters={
        "path": {"type": "string", "description": "File path", "required": True}
    },
    fn=read_file,
    requires_engine=False,
    category="filesystem"
))

ToolFactory.register(ToolSpec(
    name="write_file",
    description="Write content to a file",
    parameters={
        "path": {"type": "string", "description": "File path", "required": True},
        "content": {"type": "string", "description": "Content to write", "required": True}
    },
    fn=write_file,
    requires_engine=True,
    requires_consent=True,
    category="filesystem"
))
```

#### 3. Dynamic Tool Discovery in Client

```python
# ppxai/engine/client.py
from .tools.factory import ToolFactory

class EngineClient:
    def enable_tools(self):
        """Enable tools with dynamic discovery."""
        self._discover_and_load_tools()
        self.tools_enabled = True

    def _discover_and_load_tools(self):
        """Discover and import all tool modules."""
        import importlib
        import pkgutil
        from .tools import builtin

        # Import all modules in builtin/ - they self-register
        for _, name, _ in pkgutil.iter_modules(builtin.__path__):
            if not name.startswith('_'):
                importlib.import_module(f".{name}", "ppxai.engine.tools.builtin")

    def call_tool(self, name: str, args: dict) -> Any:
        """Call a registered tool."""
        return ToolFactory.call(name, args, engine=self)

    def get_tool_definitions(self) -> list[dict]:
        """Get OpenAI-format tool definitions for API calls."""
        definitions = []
        for name in ToolFactory.list_tools():
            spec = ToolFactory.get(name)
            definitions.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": {
                        "type": "object",
                        "properties": spec.parameters,
                        "required": [k for k, v in spec.parameters.items() if v.get("required")]
                    }
                }
            })
        return definitions
```

---

## Benefits

| Aspect | Current | Factory Pattern |
|--------|---------|-----------------|
| Import cycle | TYPE_CHECKING hack | No cycle - factory is leaf module |
| Dynamic tools | No - edit `__init__.py` | Yes - drop file in `builtin/` |
| Tool coupling | Knows about EngineClient | Just receives dependencies |
| Testing | Need mock engine | Pure functions, easy to test |
| Plugin system | Not possible | Foundation for user tools |

---

## Performance Analysis

### Latency Considerations

| Operation | Latency | Notes |
|-----------|---------|-------|
| Tool discovery (one-time) | ~10-50ms | Import all tool modules |
| Factory lookup | ~1μs | Dictionary lookup |
| Function call overhead | ~100ns | Standard Python call |
| Actual tool execution | 10ms - 10s | File I/O, API calls, shell commands |

**Conclusion:** The factory indirection adds ~1μs per tool call. Given that tools involve file I/O (1-100ms), API calls (100ms-5s), or shell execution (10ms-10s), this overhead is **completely negligible** (<0.01% of total latency).

### Memory Impact

- ToolSpec: ~500 bytes per tool
- Registry: ~10KB for 20 tools
- **Negligible** compared to tool execution buffers

---

## Migration Path

### Phase 1: Create Factory (Non-Breaking)
1. Create `ppxai/engine/tools/factory.py`
2. Add ToolSpec and ToolFactory classes
3. No changes to existing code yet

### Phase 2: Migrate Tools (Gradual)
1. Update one tool module to self-register
2. Keep backward compatibility in `register_all_builtin_tools()`
3. Test thoroughly
4. Repeat for each tool module

### Phase 3: Update Client
1. Add `_discover_and_load_tools()` to EngineClient
2. Update `call_tool()` to use factory
3. Remove `register_all_builtin_tools()` function
4. Remove TYPE_CHECKING imports

### Phase 4: Enable Dynamic Loading
1. Add user tool directory scanning
2. Support `~/.ppxai/tools/` for custom tools
3. Hot-reload capability (optional)

---

## Future Extensions

### User-Defined Tools

```python
# ~/.ppxai/tools/my_tool.py
from ppxai.engine.tools.factory import ToolFactory, ToolSpec

def my_custom_tool(arg1: str) -> str:
    return f"Custom: {arg1}"

ToolFactory.register(ToolSpec(
    name="my_custom_tool",
    description="My custom tool",
    parameters={"arg1": {"type": "string", "required": True}},
    fn=my_custom_tool
))
```

### Tool Versioning

```python
@dataclass
class ToolSpec:
    name: str
    version: str = "1.0.0"
    deprecated: bool = False
    replacement: Optional[str] = None  # For deprecation path
```

### Tool Categories for UI

```python
ToolFactory.list_by_category("filesystem")  # [read_file, write_file, ...]
ToolFactory.list_by_category("web")         # [web_search, fetch_url, ...]
ToolFactory.list_by_category("shell")       # [run_command, ...]
```

---

## Decision Record

**Decision:** Defer implementation until v1.14.x or later.

**Rationale:**
- Current TYPE_CHECKING pattern works and is well-documented
- Factory pattern is a significant refactor touching all tool modules
- Should be combined with user tool support for maximum value
- No immediate pain point driving this change

**When to Implement:**
- If adding user-defined tool support
- If TYPE_CHECKING causes maintenance issues
- If dynamic tool loading becomes a requirement

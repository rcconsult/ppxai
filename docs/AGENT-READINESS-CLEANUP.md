# `/agent` Feature Readiness: Legacy Cleanup Plan

**Created:** 2025-12-26
**Target:** Clean codebase before implementing `/agent` command
**Status:** Planning

## Executive Summary

Before implementing the `/agent` autonomous execution feature (Phase 5 of v1.11.0 plan), we must:

1. **Remove all legacy code paths** - No dual architectures
2. **Fix tool calling reliability** - Gemini JSON parsing, tool error handling
3. **Migrate tests to EngineClient** - No tests using legacy classes
4. **Create tool writing guide** - Enable custom tool development

This is a **code freeze** on new features until the codebase is clean.

---

## Current State Analysis

### Architecture Status (from v1.11.0 plan)

| Component | Plan | Current Status |
|-----------|------|----------------|
| Phase 1: File editing tools | Complete | ✅ v1.11.0 |
| Phase 2: @git context | Complete | ✅ v1.11.4 |
| Phase 3: @tree context | Complete | ✅ v1.11.4 |
| Phase 4: Manual testing | Partial | ⚠️ Bugs found |
| Phase 5: /agent loop | Blocked | ❌ Legacy code blocks |
| Phase 6: Testing & docs | Blocked | ❌ Tests use legacy |

### Legacy Code Inventory

| File | Lines | Type | Blocking /agent? |
|------|-------|------|------------------|
| `ppxai/client.py` | 447 | Legacy AIClient | ✅ YES |
| `perplexity_tools_prompt_based.py` | 1,342 | Legacy tools client | ✅ YES |
| `tool_manager.py` | 299 | Legacy MCP loader | ✅ YES |
| `ppxai/server.py` | 15 | Compat wrapper | No |
| Dual code paths in `main.py` | ~50 | Fallback logic | ✅ YES |
| isinstance() checks in `commands.py` | 7 places | Tool detection | ✅ YES |
| History sync code | ~30 | Session duplication | ✅ YES |

**Total legacy code: ~2,200 lines**

### Known Tool Reliability Issues

From `docs/BUGFIX-gemini-tool-calling.md` and recent testing:

1. **Gemini tool JSON parsing** - Fixed in v1.11.2.1 but using legacy client
2. **Tool status not persisting on provider switch** - Fixed but using legacy pattern
3. **7 isinstance() checks** - Fragile detection of tools enabled
4. **Dual history tracking** - Potential desync bugs

---

## Cleanup Tasks

### Task 1: Remove Legacy Client Code Paths

**Files to modify:**

#### 1.1 `ppxai/main.py` - Remove fallback path

```python
# REMOVE lines 298-308 (fallback to AIClient)
else:
    # Fallback path: EngineClient not available (shouldn't happen)
    console.print("[yellow]Warning: Using legacy client...[/yellow]")
    augmented_input, resolved_files = handler.process_file_references(user_input)
    response = client.chat(augmented_input, current_model, stream=True)
```

**Replace with:** Hard error if EngineClient unavailable (it's required now)

#### 1.2 `ppxai/commands.py` - Remove tool client swapping

```python
# REMOVE lines 620-690 (client upgrade/downgrade)
# Enable: Upgrade client
if not isinstance(self.client, self.PerplexityClientPromptTools):
    tool_client = self.PerplexityClientPromptTools(...)
    self.client = tool_client

# REMOVE: Disable downgrade logic
if isinstance(self.client, self.PerplexityClientPromptTools):
    regular_client = AIClient(...)
    self.client = regular_client
```

**Replace with:** `engine_client.enable_tools()` / `engine_client.disable_tools()` only

#### 1.3 `ppxai/commands.py` - Remove all isinstance() checks

```python
# REMOVE pattern (7 locations: lines 420, 630, 697, 709, 720, 731, 757):
tools_enabled = (
    (self.engine_client and self.engine_client.tools_enabled) or
    isinstance(self.client, self.PerplexityClientPromptTools)
)

# REPLACE with:
tools_enabled = self.engine_client.tools_enabled
```

#### 1.4 `ppxai/commands.py` - Remove legacy tool loading

```python
# REMOVE lines 233-241:
try:
    from perplexity_tools_prompt_based import PerplexityClientPromptTools
    from tool_manager import load_tool_config
    self.tools_available = True
    self.PerplexityClientPromptTools = PerplexityClientPromptTools
except ImportError:
    pass
```

#### 1.5 Remove legacy history sync

```python
# REMOVE lines 292-296 in main.py:
client.conversation_history = [
    {"role": msg.role, "content": msg.content}
    for msg in handler.engine_client.session.messages
]
```

### Task 2: Delete Legacy Files

After Task 1 is complete and tests pass:

```bash
# Delete these files:
rm ppxai/client.py                    # 447 lines - Legacy AIClient
rm perplexity_tools_prompt_based.py   # 1,342 lines - Legacy tools
rm tool_manager.py                    # 299 lines - Legacy MCP loader

# Update imports in __init__.py
# Remove backward compat exports
```

### Task 3: Migrate Tests to EngineClient

**Test files using legacy classes:**

| File | Legacy Usage | Migration Effort |
|------|--------------|------------------|
| `tests/test_prompt_tools.py` | PerplexityClientPromptTools | HIGH - Core tool tests |
| `tests/test_shell_command_tool.py` | PerplexityClientPromptTools | MEDIUM |
| `tests/test_file_tool.py` | PerplexityClientPromptTools | MEDIUM |
| `tests/test_provider_tools_bugfixes.py` | PerplexityClientPromptTools | LOW - Update imports |
| `tests/test_client.py` | AIClient | MEDIUM |
| `tests/test_config.py` | AIClient | LOW |
| `tests/test_autorouter.py` | send_coding_task() | MEDIUM |
| ~6 more files | Various | LOW-MEDIUM |

**Migration pattern:**

```python
# OLD:
from perplexity_tools_prompt_based import PerplexityClientPromptTools
client = PerplexityClientPromptTools(api_key="test")
client.enable_tools = True
response = client.chat("test", "model")

# NEW:
from ppxai.engine import EngineClient
engine = EngineClient()
engine.set_provider("perplexity")
engine.set_model("sonar-pro")
engine.enable_tools()
async for event in engine.chat("test"):
    if event.type == EventType.STREAM_END:
        response = event.data
```

### Task 4: Fix Tool Reliability

#### 4.1 Move Gemini JSON parsing fix to EngineClient

The fix in `perplexity_tools_prompt_based.py` lines 1054-1083 needs to be in the engine:

```python
# ppxai/engine/tools/manager.py or client.py
def parse_tool_call(self, text: str) -> Optional[Dict]:
    """Parse tool call with nested JSON support (Gemini fix)."""
    first_brace = text.find('{')
    last_brace = text.rfind('}')

    if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
        json_candidate = text[first_brace:last_brace+1]
        try:
            data = json.loads(json_candidate)
            if isinstance(data, dict) and "tool" in data:
                return self.normalize_tool_call(data)
        except json.JSONDecodeError:
            pass
    return None
```

#### 4.2 Consolidate tool error handling

Currently scattered across:
- `ppxai/engine/client.py` line 740-751
- `perplexity_tools_prompt_based.py` line 951
- `ppxai/common/event_handler.py` lines 275-280

**Consolidate to:** Single `TOOL_ERROR` event handling in EngineClient

#### 4.3 Provider-specific tool behavior

Move tool persistence logic to engine:

```python
# EngineClient
def set_provider(self, provider_name: str) -> bool:
    """Switch provider while preserving tool state."""
    tools_were_enabled = self.tools_enabled
    # ... switch provider ...
    if tools_were_enabled:
        self.enable_tools()  # Re-enable for new provider
    return True
```

### Task 5: Create Tool Writing Guide

**File:** `docs/CUSTOM-TOOLS-GUIDE.md`

```markdown
# Custom Tools Development Guide

## Overview

ppxai v1.12.0+ uses the EngineClient tool system exclusively.
This guide explains how to create custom tools.

## Tool Architecture

```
ppxai/engine/tools/
├── base.py          # BaseTool abstract class
├── manager.py       # ToolManager
└── builtin/         # Built-in tools
    ├── __init__.py  # Tool registration
    ├── filesystem.py
    ├── shell.py
    ├── calculator.py
    ├── datetime_tool.py
    ├── web.py
    └── editor/      # File editing tools (v1.11.0+)
        ├── apply_patch.py
        ├── replace_block.py
        ├── insert_text.py
        └── delete_lines.py
```

## Creating a Custom Tool

### Step 1: Implement BaseTool

```python
from ppxai.engine.tools.base import BaseTool
from typing import Dict, Any

class MyCustomTool(BaseTool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Description shown to AI"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "..."},
                "param2": {"type": "integer", "description": "..."}
            },
            "required": ["param1"]
        }

    async def execute(self, **kwargs) -> str:
        """Execute the tool and return result string."""
        param1 = kwargs.get("param1")
        param2 = kwargs.get("param2", 0)
        # ... implementation ...
        return f"Result: {result}"
```

### Step 2: Register the Tool

```python
# In ppxai/engine/tools/builtin/__init__.py
from .my_custom_tool import MyCustomTool

def register_builtin_tools(manager: ToolManager):
    # ... existing tools ...
    manager.register(MyCustomTool())
```

### Step 3: Provider-Specific Tools

```python
class MyPerplexityOnlyTool(BaseTool):
    @property
    def provider_specific(self) -> Optional[List[str]]:
        return ["perplexity"]  # Only available for Perplexity
```

## Tool Consent (for Dangerous Operations)

```python
class DangerousTool(BaseTool):
    async def execute(self, **kwargs) -> str:
        # Check consent before proceeding
        if not await self._check_consent("operation_name"):
            return "Error: Operation denied by user"
        # ... proceed with operation ...
```

## Testing Your Tool

```python
import pytest
from ppxai.engine.tools.builtin.my_tool import MyCustomTool

@pytest.mark.asyncio
async def test_my_tool():
    tool = MyCustomTool()
    result = await tool.execute(param1="test")
    assert "expected" in result
```

## Best Practices

1. **Idempotent operations** - Same inputs = same outputs
2. **Clear error messages** - Help AI understand failures
3. **Atomic operations** - No partial state changes
4. **Reasonable timeouts** - Don't block indefinitely
5. **Logging** - Use ppxai logger for debugging
```

---

## Execution Order

```
Phase A: Code Cleanup (Blocking)
├── A1: Remove fallback path in main.py
├── A2: Remove client swapping in commands.py
├── A3: Remove isinstance() checks
├── A4: Remove legacy history sync
└── A5: Run existing tests (expect some failures)

Phase B: Test Migration (Blocking)
├── B1: Identify all legacy test imports
├── B2: Create EngineClient test fixtures
├── B3: Migrate test_prompt_tools.py
├── B4: Migrate test_client.py
├── B5: Migrate remaining test files
└── B6: All tests pass with EngineClient

Phase C: Legacy Deletion (Blocking)
├── C1: Delete ppxai/client.py
├── C2: Delete perplexity_tools_prompt_based.py
├── C3: Delete tool_manager.py
├── C4: Update __init__.py exports
└── C5: Full test run passes

Phase D: Tool Reliability (Blocking)
├── D1: Move JSON parsing fix to EngineClient
├── D2: Consolidate error handling
├── D3: Add provider switch tool persistence
└── D4: Tool reliability tests pass

Phase E: Documentation (Non-blocking)
├── E1: Create CUSTOM-TOOLS-GUIDE.md
├── E2: Update CLAUDE.md for v1.12.0
├── E3: Update README.md
└── E4: Update architecture docs

Phase F: Release v1.12.0 (Gate for /agent)
├── F1: Version bump
├── F2: CHANGELOG update
├── F3: Release notes
└── F4: Tag and push

=== /agent UNBLOCKED ===

Phase G: Implement /agent (v1.12.0+)
├── G1: Implement /agent command handler
├── G2: Add agent loop to EngineClient
├── G3: Add agent event types
├── G4: Manual testing
└── G5: Release v1.13.0 with /agent
```

---

## Success Criteria

### Before Starting /agent:

- [ ] **Zero legacy imports** in ppxai/ (no AIClient, PerplexityClientPromptTools)
- [ ] **All tests use EngineClient** (no legacy test fixtures)
- [ ] **Deleted files:** client.py, perplexity_tools_prompt_based.py, tool_manager.py
- [ ] **Tool reliability:** Gemini JSON parsing in engine, error handling unified
- [ ] **Documentation:** CUSTOM-TOOLS-GUIDE.md exists
- [ ] **Test count:** ≥308 tests passing (current baseline)

### Validation Commands:

```bash
# No legacy imports
grep -r "from perplexity_tools" ppxai/ tests/ && echo "FAIL: Legacy import found"
grep -r "from tool_manager" ppxai/ tests/ && echo "FAIL: Legacy import found"
grep -r "AIClient" ppxai/ tests/ | grep -v "# Legacy" && echo "FAIL: Legacy usage found"

# Legacy files deleted
test ! -f ppxai/client.py && echo "OK: client.py deleted"
test ! -f perplexity_tools_prompt_based.py && echo "OK: legacy tools deleted"
test ! -f tool_manager.py && echo "OK: tool_manager deleted"

# All tests pass
uv run pytest tests/ -v --tb=short
```

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Breaking external users | Keep deprecated exports in __init__.py with warnings |
| Test failures | Migrate tests incrementally, run after each change |
| Missing functionality | Audit legacy code for hidden features |
| Tool reliability regression | Add specific tool tests before deleting legacy |

---

## Timeline Estimate

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| A: Code Cleanup | 4-6 hours | None |
| B: Test Migration | 6-8 hours | Phase A |
| C: Legacy Deletion | 1-2 hours | Phase B |
| D: Tool Reliability | 3-4 hours | Phase C |
| E: Documentation | 2-3 hours | None (parallel) |
| F: Release v1.12.0 | 2-3 hours | Phases A-E |
| **Total** | **18-26 hours** | |

---

## References

- [Architecture Refactoring Plan](architecture-refactoring.md) - Original engine design
- [v1.11.0 Agentic Workflow Plan](v1.11.0-agentic-workflow-plan.md) - /agent implementation details
- [Gemini Tool Calling Bugfix](BUGFIX-gemini-tool-calling.md) - JSON parsing fix to migrate
- [Legacy Code Modernization](LEGACY-CODE-MODERNIZATION.md) - Detailed inventory

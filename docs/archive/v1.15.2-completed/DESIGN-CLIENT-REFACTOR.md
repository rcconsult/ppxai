# Design: client.py Refactoring Plan

**Status:** ✅ Complete
**Created:** 2026-01-17
**Completed:** 2026-01-18
**Related:** [TECHNICAL_DEBT.md](TECHNICAL_DEBT.md) Item #2 (Monolithic Files)

---

## Problem Statement

`ppxai/engine/client.py` is 2,037 lines - the largest file in the codebase. It contains:
- Chat implementation (streaming, tools)
- Tool call parsing
- Consent handling
- Checkpoint management
- Provider/model management
- Session wrappers
- Configuration loading

This makes it hard to maintain, test, and extend.

---

## Current State

### client.py Structure by Category

| Category | Lines | Methods |
|----------|------:|---------|
| **Chat Core** | ~490 | `chat`, `_chat_simple`, `_chat_with_tools` |
| **Tool Parsing** | ~250 | `_parse_tool_call` + 5 nested helpers |
| **Consent System** | ~180 | `request_file_edit_consent`, `request_shell_consent`, `_classify_shell_command` |
| **Checkpoint Mgmt** | ~180 | `create_checkpoint`, `undo_last_checkpoint`, `commit_agent_changes`, etc. |
| **Provider Mgmt** | ~130 | `set_provider`, `list_providers`, `set_model`, `list_models` |
| **Agent Mode** | ~120 | `enable_agent_mode`, `disable_agent_mode`, `get_agent_config` |
| **Init & Config** | ~100 | `__init__`, `_load_config` |
| **Session Mgmt** | ~100 | `save_session`, `load_session`, `export_*` |
| **Status/Usage** | ~100 | `get_usage`, `get_status`, `get_context_info` |
| **Tools Mgmt** | ~80 | `enable_tools`, `disable_tools`, `list_tools` |
| **Misc** | ~50 | `interrupt_stream`, `cleanup`, etc. |

### Lazy Imports (5 locations)

```python
# Line 114 - inside _load_config()
from ..config import (PROVIDERS, get_api_key, ...)

# Line 753 - inside request_file_edit_consent()
from ..checkpoint import FileCheckpointBackend

# Line 1258 - inside _chat_with_tools()
from ..config import get_system_prompt, get_system_prompt_mode

# Line 1903 - inside export_conversation()
from ..config import EXPORTS_DIR

# Line 1979 - inside get_context_info()
from ..config import get_model_context_limit
```

### Tests Using EngineClient (8 files)

- `test_commands.py`
- `test_context_injection.py`
- `test_custom_endpoint_integration.py`
- `test_engine_context.py`
- `test_engine_streaming.py`
- `test_engine_tool_parsing.py`
- `test_file_editing_tools.py`
- `test_http_server.py`

---

## Already Refactored Modules (Targets for Code Movement)

| Module | Lines | Can Absorb From client.py |
|--------|------:|---------------------------|
| `config/` | 1,247 | Shell config defaults, agent config defaults |
| `tools/manager.py` | 447 | Tool loop detection (already there), tool parsing |
| `common/consent.py` | 606 | Shell command classification |
| `checkpoint.py` | 479 | - (already has CheckpointManager) |
| `engine/session.py` | 704 | - (already has SessionManager) |
| `engine/context.py` | 562 | - (already has ContextInjector) |

---

## Proposed Solution: Phased Extraction

### Phase 1: Remove Lazy Imports, Streamline Config (~50 lines saved)

**Goal:** Clean top-level imports, move config defaults to config module

**Changes:**
1. Move `_load_config()` lazy imports to top of file
2. Move shell config defaults (`dangerous_commands`, `never_allow`, `allowed_commands`) to `config/loader.py` as `get_shell_config()`
3. Move agent config defaults to `config/loader.py` as `get_agent_config()`
4. Remove duplicated fallback defaults in client.py

**Files Modified:**
- `ppxai/engine/client.py` - Remove lazy imports, use new config functions
- `ppxai/config/loader.py` - Add `get_shell_config()`, `get_agent_config()`
- `ppxai/config/__init__.py` - Export new functions

**Test:** `pytest tests/test_commands.py tests/test_engine_*.py -v`

---

### Phase 2: Extract Tool Parser to tools/ (~250 lines moved)

**Goal:** Move `_parse_tool_call` to `tools/parser.py`, align with Tool Factory design

**Changes:**
1. Create `ppxai/engine/tools/parser.py` (leaf module - no EngineClient dependency)
2. Move `_parse_tool_call()` and its 5 nested helpers:
   - `normalize_tool_call()`
   - `infer_tool_from_arguments()`
   - `match_rule()`
   - `try_parse_json()`
3. Export as `parse_tool_call(text: str, tool_manager: ToolManager) -> Optional[Dict]`
4. Client delegates: `self._parse_tool_call(text)` → `parse_tool_call(text, self.tool_manager)`

**Files Created:**
- `ppxai/engine/tools/parser.py` (~250 lines)

**Files Modified:**
- `ppxai/engine/client.py` - Import and delegate to parser

**Test:** `pytest tests/test_engine_tool_parsing.py -v`

---

### Phase 3: Move Shell Classification to consent.py (~50 lines moved)

**Goal:** `_classify_shell_command` belongs with consent logic

**Changes:**
1. Move `_classify_shell_command()` to `common/consent.py` as standalone function
2. Signature: `classify_shell_command(command: str, config: dict) -> str`
3. Returns: "safe", "dangerous", or "blocked"
4. Client delegates to consent module

**Files Modified:**
- `ppxai/common/consent.py` - Add `classify_shell_command()` function
- `ppxai/engine/client.py` - Import and delegate

**Test:** `pytest tests/test_commands.py -v` (covers shell consent)

---

### Phase 4: Extract Chat Implementation (~500 lines moved)

**Goal:** Move `_chat_simple` and `_chat_with_tools` to `engine/chat.py`

**Changes:**
1. Create `ppxai/engine/chat.py`
2. Define protocol/interface that chat functions need from client:
   ```python
   class ChatContext(Protocol):
       provider: BaseProvider
       model: str
       session: SessionManager
       tool_manager: ToolManager
       context_injector: ContextInjector
       # ... other needed attributes
   ```
3. Move chat implementations as functions receiving context:
   ```python
   async def chat_simple(ctx: ChatContext, stream: bool) -> AsyncIterator[Event]:
       ...

   async def chat_with_tools(ctx: ChatContext, stream: bool) -> AsyncIterator[Event]:
       ...
   ```
4. Client delegates to chat module

**Files Created:**
- `ppxai/engine/chat.py` (~500 lines)

**Files Modified:**
- `ppxai/engine/client.py` - Import and delegate

**Test:** `pytest tests/test_engine_streaming.py tests/test_custom_endpoint_integration.py -v`

---

### Phase 5: Streamline EngineClient Interface (~100 lines simplified)

**Goal:** Remove redundant wrappers, direct delegation

**Changes:**
1. Evaluate thin wrapper methods that just delegate:
   - `save_session()` → consider exposing `self.session.save()`
   - `load_session()` → consider exposing `self.session.load()`
   - `list_sessions()` → consider exposing `self.session.list()`
2. Simplify checkpoint methods to direct delegation
3. Clean up unused/redundant methods
4. Document public API clearly

**Note:** This phase requires careful consideration of breaking changes.

**Test:** `pytest tests/ -v` (full suite)

---

## Final Structure

```
engine/
├── client.py           # Facade (~800 lines, down from 2,037)
├── chat.py             # Chat implementation (~500 lines) [NEW]
├── session.py          # SessionManager (unchanged)
├── context.py          # ContextInjector (unchanged)
├── types.py            # Types (unchanged)
├── providers/          # Providers (unchanged)
└── tools/
    ├── manager.py      # ToolManager (unchanged)
    ├── parser.py       # Tool call parsing (~250 lines) [NEW]
    ├── base.py         # Base tool classes
    └── builtin/        # Built-in tools

config/
├── __init__.py         # Public API (updated exports)
├── loader.py           # + get_shell_config(), get_agent_config()
└── store.py            # ConfigStore (unchanged)

common/
└── consent.py          # + classify_shell_command()
```

---

## Import DAG After Refactoring

```
config/ (leaf)
    ↑
common/consent.py
    ↑
engine/tools/parser.py (leaf - no client dependency)
    ↑
engine/tools/manager.py
    ↑
engine/chat.py (receives ChatContext protocol)
    ↑
engine/client.py (facade, composes everything)
```

**Key principle:** Lower modules never import from higher modules. Dependencies flow upward.

---

## Alignment with Tool Factory Design

The planned Tool Factory pattern (see [DESIGN-TOOL-FACTORY.md](DESIGN-TOOL-FACTORY.md)) uses:
- **Leaf modules** with no ppxai imports
- **Self-registration** at import time
- **Dependency injection** via `engine` parameter

This refactoring aligns by:
1. Making `tools/parser.py` a leaf module (no EngineClient import)
2. Using dependency injection pattern in `chat.py` (receives context, not imports client)
3. Preparing the structure for future Tool Factory integration

---

## Summary

| Phase | Lines Moved | Status | Notes |
|-------|------------:|--------|-------|
| 1. Config cleanup | ~70 | ✅ Complete | defaults.py created, lazy imports removed |
| 2. Tool parser | ~230 | ✅ Complete | tools/parser.py created |
| 3. Shell classify | ~30 | ✅ Complete | classify_shell_command() in consent.py |
| 4. Chat extraction | ~360 | ✅ Complete | chat.py with ChatContext Protocol |
| 5. Interface cleanup | ~30 | ✅ Complete | Removed session wrappers, use engine.session |
| **Total** | **~720** | - | - |

**Final client.py:** 1,311 lines (36% reduction from 2,037)

---

## Implementation Record

**Completed:** 2026-01-18

**Phase 5 Complete:** Removed thin wrapper methods (`save_session`, `load_session`,
`list_sessions`, `clear_history`) and updated http.py and jsonrpc.py to use
`engine.session` directly. This simplifies the EngineClient interface.

**Files Created:**
- `ppxai/config/defaults.py` - Centralized default constants
- `ppxai/engine/tools/parser.py` - Tool call parsing
- `ppxai/engine/chat.py` - Chat implementation with Protocol

**Files Modified:**
- `ppxai/engine/client.py` - Facade reduced from 2,037 to 1,340 lines
- `ppxai/config/__init__.py` - Added get_agent_config()
- `ppxai/common/consent.py` - Added classify_shell_command()
- `ppxai/engine/tools/__init__.py` - Export parse_tool_call

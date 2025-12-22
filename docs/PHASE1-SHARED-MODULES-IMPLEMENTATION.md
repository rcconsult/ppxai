# Phase 1: Shared Modules Implementation Plan

**Date**: 2025-12-22
**Status**: ✅ COMPLETED and RELEASED
**Goal**: Extract shared logic into `ppxai/common/` module
**Version**: v1.11.2 (released 2025-12-22)

---

## Overview

Extract shared business logic from TUI-specific code into reusable modules that can be used by **TUI**, **VSCode extension server**, and any future clients.

**Key Principles**:
- **100% backward compatibility** - all existing functionality continues to work
- **Both TUI and VSCode work** - refactoring must not break either client
- **Incremental migration** - shared modules coexist with old code during transition

**Related Documents**:
- [PHASE1-VSCODE-ADAPTER.md](PHASE1-VSCODE-ADAPTER.md) - VSCode server integration details
- [REFACTORING-PLAN-SHARED-MODULES.md](REFACTORING-PLAN-SHARED-MODULES.md) - Overall refactoring strategy

---

## Implementation Tasks

### Task 1: Create `ppxai/common/` Module Structure ✅

**Estimated Time**: 30 minutes

**Files to Create**:
```
ppxai/common/
├── __init__.py           # Public exports
├── event_handler.py      # Shared event handling
├── logger.py             # Unified logging (replaces tui_logger.py)
├── commands.py           # Command parsing and execution
└── consent.py            # File editing consent management
```

**Deliverables**:
- [ ] Create directory structure
- [ ] Add `__init__.py` with public exports
- [ ] Add module docstrings

---

### Task 2: Implement `ppxai/common/event_handler.py` 🔴 HIGH PRIORITY

**Estimated Time**: 2-3 hours

**Purpose**: Centralize event processing logic that's currently duplicated in TUI and HTTP server.

**Implementation**:

```python
"""Shared event handling for all ppxai clients."""
from typing import AsyncIterator, Callable, Optional, Any
from ppxai.engine.types import Event, EventType


class EventHandler:
    """
    Base event handler that all clients can use.

    Handles engine events in a client-agnostic way by delegating
    rendering to client-specific callbacks.
    """

    def __init__(
        self,
        on_stream_start: Optional[Callable[[], None]] = None,
        on_stream_chunk: Optional[Callable[[str], None]] = None,
        on_stream_end: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[dict], None]] = None,
        on_tool_result: Optional[Callable[[Any], None]] = None,
        on_tool_error: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_consent_request: Optional[Callable[[dict], bool]] = None,
    ):
        """
        Initialize event handler with callbacks.

        Args:
            on_stream_start: Called when streaming starts
            on_stream_chunk: Called for each chunk (for live preview)
            on_stream_end: Called when streaming ends with full response
            on_tool_call: Called when tool is invoked
            on_tool_result: Called when tool returns result
            on_tool_error: Called when tool execution fails
            on_error: Called on errors
            on_consent_request: Called to request file editing consent
        """
        self.on_stream_start = on_stream_start or (lambda: None)
        self.on_stream_chunk = on_stream_chunk or (lambda x: None)
        self.on_stream_end = on_stream_end or (lambda x: None)
        self.on_tool_call = on_tool_call or (lambda x: None)
        self.on_tool_result = on_tool_result or (lambda x: None)
        self.on_tool_error = on_tool_error or (lambda x: None)
        self.on_error = on_error or (lambda x: None)
        self.on_consent_request = on_consent_request or (lambda x: True)

    async def process_events(
        self,
        event_stream: AsyncIterator[Event],
        accumulate_response: bool = True
    ) -> str:
        """
        Process events from engine client.

        This is the SHARED logic that:
        1. Handles all event types
        2. Calls appropriate callbacks for client-specific rendering
        3. Returns final response

        IMPORTANT: Safe to break on STREAM_END because the engine
        already added the assistant message to session BEFORE yielding.

        Args:
            event_stream: Async iterator of events from EngineClient
            accumulate_response: Whether to accumulate chunks into full response

        Returns:
            Final response string
        """
        full_response = ""

        async for event in event_stream:
            if event.type == EventType.STREAM_START:
                self.on_stream_start()

            elif event.type == EventType.STREAM_CHUNK:
                self.on_stream_chunk(event.data)
                if accumulate_response:
                    full_response += event.data

            elif event.type == EventType.STREAM_END:
                # Safe to break here - message already added in engine!
                self.on_stream_end(event.data)
                if not accumulate_response:
                    full_response = event.data
                break

            elif event.type == EventType.TOOL_CALL:
                self.on_tool_call(event.data)

            elif event.type == EventType.TOOL_RESULT:
                self.on_tool_result(event.data)

            elif event.type == EventType.TOOL_ERROR:
                self.on_tool_error(event.data)

            elif event.type == EventType.CONSENT_REQUEST:
                # Handle consent request synchronously
                approved = self.on_consent_request(event.data)
                # Approval communicated back to engine via callback

            elif event.type == EventType.ERROR:
                self.on_error(event.data)
                break

        return full_response
```

**Tests** (`tests/test_common_event_handler.py`):
- [ ] Test event processing with mocked callbacks
- [ ] Test STREAM_END breaks safely
- [ ] Test tool call/result handling
- [ ] Test consent request handling
- [ ] Test error handling

**Benefits**:
- ✅ Eliminates duplicate event handling code in TUI and HTTP server
- ✅ Ensures consistent behavior across all clients
- ✅ Safe break on STREAM_END (message already added)
- ✅ Easy to add new client types

---

### Task 3: Implement `ppxai/common/logger.py` 🟡 MEDIUM PRIORITY

**Estimated Time**: 1-2 hours

**Purpose**: Replace `tui_logger.py` with unified logging system for all clients.

**Implementation**:

```python
"""Unified logging system for all ppxai clients."""
import logging
import os
from pathlib import Path
from typing import Optional, List, Dict, Any


class PPXAILogger:
    """
    Unified logger for TUI, VSCode extension server, and other clients.

    Creates separate log files per client type but shares implementation.
    """

    _instances: Dict[str, "PPXAILogger"] = {}

    @classmethod
    def get_logger(cls, client_type: str = "default") -> "PPXAILogger":
        """
        Get logger instance for specific client type.

        Args:
            client_type: "tui", "server", "test", etc.

        Returns:
            Logger instance for this client type
        """
        if client_type not in cls._instances:
            cls._instances[client_type] = cls(client_type)
        return cls._instances[client_type]

    def __init__(self, client_type: str):
        """Initialize logger for specific client type."""
        self.client_type = client_type
        self._logger: Optional[logging.Logger] = None
        self._enabled = False

        # Check if logging is enabled
        if not self._enabled:
            self._enabled = os.getenv('PPXAI_DEBUG', '').lower() in ['1', 'true', 'yes', 'on']

        if self._enabled:
            self._setup_logger()

    def _setup_logger(self):
        """Setup file-based logging."""
        log_dir = Path.home() / '.ppxai' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)

        log_file = log_dir / f'{self.client_type}-debug.log'

        # Create logger
        self._logger = logging.getLogger(f'ppxai.{self.client_type}')
        self._logger.setLevel(logging.DEBUG)

        # Avoid duplicate handlers
        if not self._logger.handlers:
            # File handler with custom format
            handler = logging.FileHandler(log_file)
            formatter = logging.Formatter(
                '%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s',
                datefmt='%H:%M:%S'
            )
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

    @property
    def enabled(self) -> bool:
        """Check if logging is enabled."""
        return self._enabled

    def enable(self):
        """Enable logging at runtime."""
        if not self._enabled:
            self._enabled = True
            self._setup_logger()

    def disable(self):
        """Disable logging at runtime."""
        self._enabled = False
        if self._logger:
            for handler in self._logger.handlers[:]:
                handler.close()
                self._logger.removeHandler(handler)
        self._logger = None

    # Logging methods (same as tui_logger.py)
    def info(self, message: str):
        """Log info message."""
        if self._logger:
            self._logger.info(message)

    def debug(self, message: str):
        """Log debug message."""
        if self._logger:
            self._logger.debug(message)

    def warning(self, message: str):
        """Log warning message."""
        if self._logger:
            self._logger.warning(message)

    def error(self, message: str):
        """Log error message."""
        if self._logger:
            self._logger.error(message)

    def log_user_message(self, message: str):
        """Log user input."""
        self.info(f"USER INPUT: {message[:200]}")

    def log_command(self, command: str):
        """Log command execution."""
        self.info(f"COMMAND: {command}")

    def log_assistant_message(self, message: str):
        """Log assistant response."""
        preview = message[:200] if message else ""
        self.info(f"ASSISTANT RESPONSE: {preview}")

    def log_api_request(self, iteration: int, messages: List[Any]):
        """Log API request."""
        self.info(f"API REQUEST: iteration={iteration}, messages={len(messages)}")
        for i, msg in enumerate(messages):
            role = getattr(msg, 'role', 'unknown')
            content = getattr(msg, 'content', '')
            preview = content[:100] if content else ""
            self.debug(f"  [{i}] {role:10s} : {preview}")

    def log_api_error(self, error_code: int, error_message: str):
        """Log API error."""
        self.error(f"API ERROR {error_code}: {error_message[:200]}")

    def log_tool_call(self, tool_name: str, arguments: dict):
        """Log tool call."""
        self.info(f"TOOL CALL: {tool_name}")
        self.debug(f"  Arguments: {arguments}")

    def log_tool_result(self, tool_name: str, result: str):
        """Log tool result."""
        self.info(f"TOOL RESULT: {tool_name}")
        preview = result[:200] if result else ""
        self.debug(f"  Result: {preview}")

    def log_tool_error(self, tool_name: str, error: str):
        """Log tool error."""
        self.error(f"TOOL ERROR: {tool_name} - {error[:200]}")

    def log_history_sync(self, legacy_count: int, engine_count: int, messages: List[Any]):
        """Log conversation history sync."""
        self.info(f"HISTORY SYNC: legacy={legacy_count}, engine={engine_count}")
        for i, msg in enumerate(messages):
            role = getattr(msg, 'role', 'unknown')
            content = getattr(msg, 'content', '')
            preview = content[:100] if content else ""
            self.debug(f"  [{i}] {role:10s} : {preview}")

    def log_event(self, event_type: str, data: str):
        """Log generic event."""
        self.debug(f"EVENT: {event_type} - {data[:200]}")


# Backward compatibility alias
def get_logger(client_type: str = "tui") -> PPXAILogger:
    """Get logger instance (backward compatible)."""
    return PPXAILogger.get_logger(client_type)
```

**Migration Steps**:
1. [ ] Create `ppxai/common/logger.py`
2. [ ] Update `ppxai/main.py` to use `from ppxai.common.logger import get_logger`
3. [ ] Update `ppxai/commands.py` to use `from ppxai.common.logger import get_logger`
4. [ ] Update `ppxai/engine/client.py` to use `from ppxai.common.logger import get_logger`
5. [ ] Mark `ppxai/tui_logger.py` as deprecated (keep for backward compatibility)
6. [ ] Add tests for logger

**Tests** (`tests/test_common_logger.py`):
- [ ] Test logger initialization
- [ ] Test enable/disable at runtime
- [ ] Test log file creation
- [ ] Test logging methods
- [ ] Test backward compatibility

---

### Task 4: Implement `ppxai/common/commands.py` 🟢 LOW PRIORITY

**Estimated Time**: 2-3 hours

**Purpose**: Share command parsing and execution logic across clients.

**Note**: This is lower priority because commands are mostly TUI-specific currently. The HTTP server uses JSON-RPC methods instead. However, this will be useful when we add command support to other clients.

**Implementation Outline**:
```python
"""Shared command system for all ppxai clients."""

class CommandResult:
    """Result of command execution."""
    def __init__(self, success: bool, message: str = None, data: dict = None, should_exit: bool = False):
        ...

class CommandHandler:
    """Shared command handler."""

    COMMANDS = {
        'help': 'Show available commands',
        'quit': 'Exit the application',
        # ... etc
    }

    def __init__(self, engine_client, callbacks: dict = None):
        ...

    def parse_command(self, input_str: str) -> tuple:
        ...

    def execute(self, input_str: str) -> CommandResult:
        ...
```

**Defer to v1.13.0** - Not critical for v1.11.2

---

### Task 5: Implement `ppxai/common/consent.py` 🟢 LOW PRIORITY

**Estimated Time**: 1-2 hours

**Purpose**: Unified consent management for file editing tools.

**Note**: Current consent implementation works well. This refactoring will make it easier to share consent logic, but it's not urgent.

**Defer to v1.13.0** - Not critical for v1.11.2

---

## Testing Strategy

### Unit Tests

**New Test Files**:
- `tests/test_common_event_handler.py` (HIGH PRIORITY)
- `tests/test_common_logger.py` (MEDIUM PRIORITY)
- `tests/test_common_commands.py` (LOW PRIORITY)
- `tests/test_common_consent.py` (LOW PRIORITY)

### Integration Tests

**Existing Tests to Update**:
- `tests/test_engine_streaming.py` - Verify still passes
- `tests/test_file_editing_tools.py` - Verify still passes
- All other tests should continue passing (backward compatibility)

### Manual Testing

**Test Scenarios**:

**TUI Testing**:
1. [ ] TUI with event handler - multi-turn conversation with tools
2. [ ] TUI with logger - enable/disable debug logging
3. [ ] TUI commands - all slash commands work
4. [ ] TUI file editing - consent system works
5. [ ] TUI `/debug-log` command - show/clear/on/off

**VSCode Extension Testing**:
6. [ ] HTTP server starts with debug logging (`PPXAI_DEBUG=1 uv run ppxai-server`)
7. [ ] VSCode extension connects and chats
8. [ ] Server log file created (`~/.ppxai/logs/server-debug.log`)
9. [ ] Server logs show requests/responses/tool calls
10. [ ] VSCode tools work (list_directory, read_file, etc.)
11. [ ] VSCode consent dialogs work for file editing
12. [ ] No regressions - all existing functionality works

**Both Clients**:
13. [ ] Compare TUI and VSCode logs - consistent format
14. [ ] Verify both use shared logger correctly
15. [ ] Verify both handle events correctly (no 400 errors)

---

## Deliverables for v1.11.2

### Minimum Viable Product (MVP)

**Must Have** (6-9 hours total):
1. ✅ `ppxai/common/event_handler.py` with tests (2-3h)
2. ✅ `ppxai/common/logger.py` with tests (1-2h)
3. ✅ **VSCode Server Integration** - `ppxai/server/http.py` uses shared logger (1-2h)
   - See [PHASE1-VSCODE-ADAPTER.md](PHASE1-VSCODE-ADAPTER.md) for details
4. ✅ TUI updated to use shared modules (1-2h)
5. ✅ Backward compatibility maintained
6. ✅ All existing tests pass (303/308 or better)
7. ✅ **Both TUI and VSCode work** with shared modules
8. ✅ Documentation updated

**Nice to Have** (optional):
- `ppxai/common/commands.py` (defer to v1.13.0)
- `ppxai/common/consent.py` (defer to v1.13.0)

---

## Migration Path

### Step 1: Create New Modules (Non-Breaking)

```bash
# Create new directory
mkdir -p ppxai/common

# Create files
touch ppxai/common/__init__.py
touch ppxai/common/event_handler.py
touch ppxai/common/logger.py
```

### Step 2: Keep Old Code Working

**Do NOT delete** `ppxai/tui_logger.py` yet - keep it for backward compatibility.

### Step 3: Gradual Adoption

Update files one by one:
1. `ppxai/main.py` - Use new event handler and logger
2. `ppxai/commands.py` - Use new logger
3. `ppxai/engine/client.py` - Use new logger
4. `ppxai/server/http.py` - Use new event handler (future)

### Step 4: Deprecation (v1.13.0)

Mark old modules as deprecated but keep them working.

### Step 5: Removal (v1.14.0)

Remove deprecated modules after 2 releases.

---

## Success Criteria

### Phase 1 Complete When:

**Core Modules**:
- [ ] `ppxai/common/event_handler.py` implemented and tested
- [ ] `ppxai/common/logger.py` implemented and tested
- [ ] All existing tests pass (303/308 or better)

**TUI Integration**:
- [ ] TUI uses shared event handler
- [ ] TUI uses shared logger
- [ ] TUI debug logging works (`/debug-log on`)
- [ ] Multi-turn conversations with tools work (no 400 errors)

**VSCode Extension Integration**:
- [ ] HTTP server uses shared logger
- [ ] Server debug logging works (`PPXAI_DEBUG=1`)
- [ ] VSCode extension connects and chats successfully
- [ ] Server logs to `~/.ppxai/logs/server-debug.log`
- [ ] No regressions in VSCode functionality

**Both Clients**:
- [ ] Consistent logging format across TUI and server
- [ ] No breaking changes
- [ ] Documentation updated
- [ ] Ready to start Phase 2 (agentic workflow: @git context)

---

## Timeline

**Target**: Complete by end of week (Dec 27, 2025)

| Task | Priority | Effort | Status |
|------|----------|--------|--------|
| Event Handler | HIGH | 2-3 hours | ⏳ Ready |
| Logger | MEDIUM | 1-2 hours | ⏳ Ready |
| **VSCode Server Integration** | **HIGH** | **1-2 hours** | **⏳ Ready** |
| TUI Integration | HIGH | 1-2 hours | ⏳ Ready |
| Testing (both clients) | HIGH | 1 hour | ⏳ Ready |
| Commands | LOW | 2-3 hours | 🔵 Deferred to v1.13.0 |
| Consent | LOW | 1-2 hours | 🔵 Deferred to v1.13.0 |
| **Total (v1.11.2)** | | **6-9 hours** | |

---

## Next Steps After Phase 1

Once Phase 1 is complete and all tests pass:

1. **Commit and tag**: `v1.11.2 - Shared Modules Architecture`
2. **Update ROADMAP.md**: Mark Phase 1 complete
3. **Start Phase 2**: Implement @git context provider (agentic workflow)

---

**Last Updated**: 2025-12-22
**Status**: Ready to implement
**Assignee**: Ready for user approval

# Refactoring Plan: Shared Module Architecture

**Date**: 2025-12-22
**Version**: v1.11.1+
**Goal**: Maximize code sharing across TUI, VSCode Extension, and HTTP Server

---

## Current Architecture (Before Refactoring)

```
ppxai/
├── engine/                 # ✅ Shared business logic (good!)
│   ├── client.py           # EngineClient - used by all clients
│   ├── session.py          # Session management
│   ├── providers/          # Provider implementations
│   └── tools/              # Tool system
│
├── server/                 # HTTP/JSON-RPC server
│   ├── jsonrpc.py          # JSON-RPC over stdio
│   └── http.py             # HTTP + SSE server
│
├── main.py                 # TUI main loop ⚠️ TUI-specific
├── commands.py             # TUI command handlers ⚠️ TUI-specific
├── ui.py                   # TUI UI components ⚠️ TUI-specific
├── tui_logger.py           # TUI debug logging ⚠️ TUI-specific
│
└── vscode-extension/       # VSCode extension
    ├── src/extension.ts    # Extension entry point ⚠️ VSCode-specific
    ├── src/httpClient.ts   # HTTP client ⚠️ VSCode-specific
    └── src/chatPanel.ts    # Webview UI ⚠️ VSCode-specific
```

### Problems with Current Architecture

1. **TUI Event Handling** - Event loop logic in `main.py` is TUI-specific
2. **Logging Duplication** - `tui_logger.py` is TUI-only, VSCode has own logging
3. **Command Parsing** - `/commands` are handled in TUI's `commands.py` only
4. **History Sync** - Bidirectional sync between legacy and engine clients (TUI-specific hack)
5. **Consent Handling** - Different implementations for TUI (async callbacks) vs VSCode (SSE events)

---

## Proposed Architecture (After Refactoring)

### 1. Shared Modules (Common Across All Clients)

```
ppxai/
├── engine/                 # ✅ Already shared
│   ├── client.py
│   ├── session.py
│   ├── providers/
│   └── tools/
│
├── common/                 # 🆕 NEW - Shared client logic
│   ├── __init__.py
│   ├── event_handler.py    # 🆕 Shared event handling logic
│   ├── logger.py           # 🆕 Unified logging (replaces tui_logger.py)
│   ├── commands.py         # 🆕 Command parsing & execution
│   ├── consent.py          # 🆕 Unified consent system
│   └── session_sync.py     # 🆕 Session history synchronization
│
├── clients/                # 🆕 NEW - Client-specific implementations
│   ├── __init__.py
│   ├── tui/                # TUI-specific
│   │   ├── main.py         # TUI entry point
│   │   ├── ui.py           # Rich console UI
│   │   └── completer.py    # Prompt completion
│   │
│   ├── http/               # HTTP server (for VSCode)
│   │   ├── server.py       # HTTP + SSE server
│   │   └── jsonrpc.py      # JSON-RPC server
│   │
│   └── base.py             # Base client interface
│
└── vscode-extension/       # VSCode extension (unchanged)
    └── src/
        ├── extension.ts
        ├── httpClient.ts
        └── chatPanel.ts
```

---

## Detailed Refactoring Steps

### Phase 1: Extract Shared Event Handling

**File**: `ppxai/common/event_handler.py`

**Purpose**: Handle engine events in a client-agnostic way.

```python
"""Shared event handling for all clients."""
from typing import AsyncIterator, Callable, Optional
from ppxai.engine.types import Event, EventType


class EventHandler:
    """Base event handler that all clients can use."""

    def __init__(
        self,
        on_stream_start: Optional[Callable] = None,
        on_stream_chunk: Optional[Callable[[str], None]] = None,
        on_stream_end: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[dict], None]] = None,
        on_tool_result: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_consent_request: Optional[Callable[[dict], bool]] = None,
    ):
        """Initialize event handler with callbacks."""
        self.on_stream_start = on_stream_start or (lambda: None)
        self.on_stream_chunk = on_stream_chunk or (lambda x: None)
        self.on_stream_end = on_stream_end or (lambda x: None)
        self.on_tool_call = on_tool_call or (lambda x: None)
        self.on_tool_result = on_tool_result or (lambda x: None)
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
        2. Calls appropriate callbacks
        3. Returns final response

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
                self.on_stream_end(event.data)
                if not accumulate_response:
                    full_response = event.data
                break  # Always safe to break - message already added in engine

            elif event.type == EventType.TOOL_CALL:
                self.on_tool_call(event.data)

            elif event.type == EventType.TOOL_RESULT:
                self.on_tool_result(event.data)

            elif event.type == EventType.CONSENT_REQUEST:
                # Handle consent request synchronously
                approved = self.on_consent_request(event.data)
                # Consent approval handled by callback

            elif event.type == EventType.ERROR:
                self.on_error(event.data)
                break

        return full_response
```

**Benefits**:
- ✅ Shared event processing logic
- ✅ Safe to break on STREAM_END (message already added in engine)
- ✅ Client-specific rendering via callbacks
- ✅ Works for TUI, VSCode, and any future clients

---

### Phase 2: Unified Logging System

**File**: `ppxai/common/logger.py`

**Purpose**: Single logging system used by all clients.

```python
"""Unified logging system for all ppxai clients."""
import logging
import os
from pathlib import Path
from typing import Optional


class PPXAILogger:
    """Unified logger for TUI, VSCode extension server, and other clients."""

    _instances = {}  # One instance per client type

    @classmethod
    def get_logger(cls, client_type: str = "default") -> "PPXAILogger":
        """
        Get logger instance for specific client type.

        Args:
            client_type: "tui", "server", "test", etc.
        """
        if client_type not in cls._instances:
            cls._instances[client_type] = cls(client_type)
        return cls._instances[client_type]

    def __init__(self, client_type: str):
        """Initialize logger for specific client type."""
        self.client_type = client_type
        self._logger = None
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

        # File handler with custom format
        handler = logging.FileHandler(log_file)
        formatter = logging.Formatter(
            '%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        )
        handler.setFormatter(formatter)
        self._logger.addHandler(handler)

    # ... rest of logging methods (same as tui_logger.py but shared)
```

**Benefits**:
- ✅ One logger implementation for all clients
- ✅ Separate log files per client type (`tui-debug.log`, `server-debug.log`)
- ✅ Same format and features across all clients
- ✅ Easy to enable/disable via `PPXAI_DEBUG` env var

---

### Phase 3: Shared Command System

**File**: `ppxai/common/commands.py`

**Purpose**: Command parsing and execution logic shared across clients.

```python
"""Shared command system for all ppxai clients."""
from typing import Optional, Callable, Dict, Any


class CommandResult:
    """Result of command execution."""

    def __init__(
        self,
        success: bool,
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        should_exit: bool = False
    ):
        self.success = success
        self.message = message
        self.data = data
        self.should_exit = should_exit


class CommandHandler:
    """Shared command handler for all clients."""

    COMMANDS = {
        'help': 'Show available commands',
        'quit': 'Exit the application',
        'exit': 'Exit the application',
        'clear': 'Clear conversation history',
        'save': 'Save session to JSON',
        'export': 'Export last answer to markdown',
        'model': 'Switch model',
        'provider': 'Switch provider',
        'tools': 'Manage AI tools',
        'status': 'Show current status',
        'usage': 'Show token usage',
        # ... etc
    }

    def __init__(self, engine_client, callbacks: Optional[Dict[str, Callable]] = None):
        """
        Initialize command handler.

        Args:
            engine_client: EngineClient instance
            callbacks: Optional dict of command-specific callbacks for client-specific behavior
        """
        self.engine = engine_client
        self.callbacks = callbacks or {}

    def parse_command(self, input_str: str) -> tuple[str, str]:
        """
        Parse command and arguments.

        Returns:
            (command, arguments)
        """
        if not input_str.startswith('/'):
            return ('', input_str)

        parts = input_str[1:].split(None, 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ''

        return (command, args)

    def execute(self, input_str: str) -> CommandResult:
        """
        Execute a command.

        Returns:
            CommandResult with success, message, data, and should_exit
        """
        command, args = self.parse_command(input_str)

        if not command:
            return CommandResult(False, "Not a command")

        # Map command to handler method
        handler_name = f'_handle_{command}'
        handler = getattr(self, handler_name, None)

        if not handler:
            return CommandResult(False, f"Unknown command: /{command}")

        return handler(args)

    def _handle_quit(self, args: str) -> CommandResult:
        """Handle /quit command."""
        return CommandResult(
            success=True,
            message="Goodbye!",
            should_exit=True
        )

    def _handle_tools(self, args: str) -> CommandResult:
        """Handle /tools command."""
        parts = args.split()
        subcommand = parts[0] if parts else 'status'

        if subcommand == 'enable':
            self.engine.enable_tools()
            return CommandResult(True, "Tools enabled")

        elif subcommand == 'disable':
            self.engine.disable_tools()
            return CommandResult(True, "Tools disabled")

        elif subcommand == 'status':
            enabled = self.engine.tool_manager is not None
            return CommandResult(
                True,
                f"Tools: {'enabled' if enabled else 'disabled'}",
                data={'enabled': enabled}
            )

        # ... etc

    # ... other command handlers
```

**Benefits**:
- ✅ Shared command parsing logic
- ✅ Client-agnostic command execution
- ✅ Callbacks for client-specific UI rendering
- ✅ Easy to add new commands in one place

---

### Phase 4: Unified Consent System

**File**: `ppxai/common/consent.py`

**Purpose**: Shared consent handling for file editing tools.

```python
"""Shared consent system for file editing tools."""
from typing import Dict, Callable, Optional
from enum import Enum


class ConsentDecision(Enum):
    """Consent decision types."""
    APPROVE = "approve"
    REJECT = "reject"
    ALWAYS = "always"
    NEVER = "never"


class ConsentManager:
    """Shared consent management."""

    def __init__(self, request_consent_callback: Callable[[dict], ConsentDecision]):
        """
        Initialize consent manager.

        Args:
            request_consent_callback: Function to request consent from user
                                     (client-specific implementation)
        """
        self.request_consent = request_consent_callback
        self.session_consents: Dict[str, ConsentDecision] = {}

    def should_allow(self, file_path: str, operation: str, details: dict) -> bool:
        """
        Check if operation should be allowed.

        Args:
            file_path: Path to file being modified
            operation: Operation type (e.g., "apply_patch", "delete_lines")
            details: Operation details for display

        Returns:
            True if approved, False if rejected
        """
        # Check session consent
        if file_path in self.session_consents:
            decision = self.session_consents[file_path]
            if decision == ConsentDecision.ALWAYS:
                return True
            elif decision == ConsentDecision.NEVER:
                return False

        # Request consent from user (client-specific)
        decision = self.request_consent({
            'file_path': file_path,
            'operation': operation,
            'details': details
        })

        # Store session consent if always/never
        if decision in [ConsentDecision.ALWAYS, ConsentDecision.NEVER]:
            self.session_consents[file_path] = decision

        return decision in [ConsentDecision.APPROVE, ConsentDecision.ALWAYS]
```

**Benefits**:
- ✅ Shared consent logic
- ✅ Session-scoped consent storage
- ✅ Client-specific UI via callback
- ✅ Works for TUI (prompt_toolkit) and VSCode (modal dialog)

---

## Migration Strategy

### Step 1: Create `ppxai/common/` Module

1. Create new directory structure
2. Move shared logic piece by piece
3. Keep backward compatibility during migration

### Step 2: Refactor TUI to Use Common Modules

**Before** (`ppxai/main.py`):
```python
# TUI-specific event handling
async for event in engine_client.chat(message):
    if event.type == EventType.STREAM_START:
        console.print("\\n[bold cyan]Assistant:[/bold cyan]")
    elif event.type == EventType.STREAM_CHUNK:
        full_response += event.data
    elif event.type == EventType.STREAM_END:
        render_markdown(full_response)
        break
```

**After** (`ppxai/clients/tui/main.py`):
```python
from ppxai.common.event_handler import EventHandler

# Define TUI-specific rendering callbacks
handler = EventHandler(
    on_stream_start=lambda: console.print("\\n[bold cyan]Assistant:[/bold cyan]"),
    on_stream_chunk=lambda chunk: None,  # Accumulate silently
    on_stream_end=lambda response: render_markdown(response),
    on_tool_call=lambda data: console.print(f"[cyan]→ Calling tool: {data['tool']}[/cyan]"),
)

# Use shared event processing
response = await handler.process_events(engine_client.chat(message))
```

### Step 3: Refactor HTTP Server to Use Common Modules

**Before** (`ppxai/server/http.py`):
```python
# Duplicate event handling logic
async for event in engine.chat(message):
    if event.type == EventType.STREAM_CHUNK:
        await send_sse(event.data)
    elif event.type == EventType.STREAM_END:
        result = event.data
```

**After** (`ppxai/clients/http/server.py`):
```python
from ppxai.common.event_handler import EventHandler

# Define SSE-specific callbacks
handler = EventHandler(
    on_stream_chunk=lambda chunk: asyncio.create_task(send_sse('chunk', chunk)),
    on_stream_end=lambda response: asyncio.create_task(send_sse('end', response)),
    on_tool_call=lambda data: asyncio.create_task(send_sse('tool_call', data)),
)

# Use shared event processing
response = await handler.process_events(engine.chat(message))
```

### Step 4: Update VSCode Extension (No Changes Needed)

The VSCode extension already uses the HTTP server, so it automatically benefits from the refactoring!

---

## Benefits of This Refactoring

### Code Sharing

| Component | Before | After |
|-----------|--------|-------|
| Event handling | Duplicated in TUI, HTTP server | **Shared** in `common/event_handler.py` |
| Logging | TUI-only (`tui_logger.py`) | **Shared** in `common/logger.py` |
| Commands | TUI-only (`commands.py`) | **Shared** in `common/commands.py` |
| Consent | Duplicated in TUI, HTTP server | **Shared** in `common/consent.py` |

### Maintenance

- ✅ Fix bugs in one place → all clients benefit
- ✅ Add features once → works everywhere
- ✅ Consistent behavior across all clients
- ✅ Easier to test shared logic

### Extensibility

- ✅ Easy to add new client types (CLI, web UI, mobile app)
- ✅ Client-specific UI via callbacks
- ✅ Clear separation of concerns

---

## Breaking Changes

### None!

This refactoring maintains **100% backward compatibility**:
- TUI entry point remains `ppxai`
- HTTP server entry point remains `ppxai-server`
- VSCode extension unchanged
- All existing functionality preserved

---

## Implementation Timeline

### v1.12.0 (Next Release)

**Phase 1**: Extract shared modules (no breaking changes)
- Create `ppxai/common/` with shared logic
- Keep existing code working alongside new code
- Add tests for shared modules

### v1.13.0 (Future Release)

**Phase 2**: Migrate TUI to use common modules
- Update `ppxai/main.py` to use `common/event_handler.py`
- Replace `tui_logger.py` with `common/logger.py`
- Migrate commands to `common/commands.py`

### v1.14.0 (Future Release)

**Phase 3**: Migrate HTTP server to use common modules
- Update `ppxai/server/` to use shared modules
- Remove duplicate code

**Phase 4**: Deprecate old code
- Mark old modules as deprecated
- Keep backward compatibility for one more release

### v1.15.0 (Future Release)

**Phase 5**: Remove deprecated code
- Delete duplicated code
- Final cleanup

---

## Testing Strategy

### Unit Tests

- Test each shared module independently
- Mock client-specific callbacks
- Verify behavior is consistent

### Integration Tests

- Test TUI with shared modules
- Test HTTP server with shared modules
- Test VSCode extension (unchanged)

### Regression Tests

- Ensure all existing tests pass
- Add new tests for shared modules
- Verify no breaking changes

---

## Related Documentation

- [400-ERROR-INVESTIGATION.md](400-ERROR-INVESTIGATION.md) - Event handling bug fix
- [architecture-refactoring.md](architecture-refactoring.md) - Engine layer architecture
- [TUI_VSCODE_CONSISTENCY_ANALYSIS.md](TUI_VSCODE_CONSISTENCY_ANALYSIS.md) - Behavioral consistency

---

**Last Updated**: 2025-12-22
**Status**: Proposed
**Next Steps**: Review and approve plan before implementation

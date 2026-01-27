# TODO: v1.15.0 - Blinker Event Bus Integration

**Date:** 2026-01-27
**Priority:** HIGH - Critical for debugging and bug resolution
**Goal:** Integrate blinker event bus to resolve current ppxaide bugs
**Timeline:** 3-4 days

---

## Rationale

Current bugs are caused by complex async event handling between EngineClient and Textual UI:
1. **AI Responses Not Displayed** - Event handling issues in _handle_event
2. **Tool Consent Broken** - Callbacks not triggering properly
3. **Hard to Debug** - Complex Future-based coordination, race conditions

**Solution:** Event bus provides:
- ✅ **Visibility** - All events logged through central bus
- ✅ **Decoupling** - Engine doesn't directly call UI
- ✅ **Debugging** - Can intercept/log all events
- ✅ **Simplification** - No Future-based coordination
- ✅ **Testing** - Mock event bus for unit tests

---

## Current Status (186f910)

**Last Code Change:** feat(tui): consent dialog callback pattern, dynamic help, filetype lib

**Working:**
- ✅ Consent dialog UI exists
- ✅ Consent handlers wired to EngineClient
- ✅ STREAM_END extraction improved (handles dict response)
- ✅ Debug logging added throughout

**Broken:**
- ❌ AI responses sometimes not displayed
- ❌ Consent callbacks not being triggered
- ❌ Complex event flow hard to debug

**File Status:**
- `ppxai/tui/app.py` - 1,545 lines, complex _handle_event() method
- `ppxai/tui/widgets/dialog.py` - ConsentDialog exists
- Consent handlers exist but not triggering reliably

---

## Implementation Plan

### Phase 1: Add Blinker Infrastructure (Day 1 - 4 hours)

#### Task 1.1: Add Dependency
```toml
# pyproject.toml
[project.optional-dependencies]
tui = [
    "textual>=0.47.0",
    "textual-image>=0.8.0",
    "blinker>=1.7.0",  # NEW
]
```

**Files:** `pyproject.toml`
**Time:** 5 minutes

#### Task 1.2: Create Event Bus Module
```python
# ppxai/tui/event_bus.py (NEW)
"""
Event bus for decoupled ppxaide components using blinker.

Provides pub/sub pattern to simplify async coordination and improve debugging.
"""

from blinker import Signal
from typing import Callable, Dict, Any, Optional
import asyncio
import logging

logger = logging.getLogger(__name__)


class EventBus:
    """
    NATS-like event bus for ppxaide using blinker.

    Features:
    - Pub/sub decoupling (engine → UI via events)
    - Async handler support (automatic detection)
    - Error isolation (one handler crash doesn't break others)
    - Event logging (visibility for debugging)
    - Thread-safe (ready for embedded server thread)

    Usage:
        bus = EventBus()

        # Subscribe
        bus.on("engine:chunk", lambda sender, data, **kw: print(data))

        # Emit
        bus.emit("engine:chunk", data="Hello")

        # Unsubscribe
        unsubscribe = bus.on("engine:chunk", handler)
        unsubscribe()
    """

    def __init__(self, log_events: bool = True):
        """
        Initialize event bus.

        Args:
            log_events: Enable event logging for debugging
        """
        self._signals: Dict[str, Signal] = {}
        self._log_events = log_events

    def signal(self, name: str) -> Signal:
        """Get or create signal by name."""
        if name not in self._signals:
            self._signals[name] = Signal(name)
        return self._signals[name]

    def on(self, event: str, handler: Callable) -> Callable:
        """
        Subscribe to event.

        Args:
            event: Event name (e.g., "engine:chunk")
            handler: Handler function (sync or async)

        Returns:
            Unsubscribe function
        """
        signal = self.signal(event)
        signal.connect(handler, weak=False)  # Don't use weak refs (can cause bugs)

        if self._log_events:
            logger.debug(f"[EventBus] Subscribed to '{event}': {handler.__name__}")

        # Return unsubscribe function
        def unsubscribe():
            signal.disconnect(handler)
            if self._log_events:
                logger.debug(f"[EventBus] Unsubscribed from '{event}': {handler.__name__}")

        return unsubscribe

    def emit(self, event: str, **kwargs):
        """
        Emit event to all subscribers.

        Handlers are called based on their type:
        - Async handlers: scheduled as tasks
        - Sync handlers: called immediately

        Errors in handlers are logged but don't stop other handlers.

        Args:
            event: Event name
            **kwargs: Arguments passed to handlers
        """
        if self._log_events:
            # Log event with abbreviated data
            data_preview = self._preview_data(kwargs)
            logger.debug(f"[EventBus] Emit '{event}': {data_preview}")

        signal = self.signal(event)

        # Get all receivers for this signal
        receivers = list(signal.receivers_for(None))

        if not receivers:
            if self._log_events:
                logger.debug(f"[EventBus] No handlers for '{event}'")
            return

        # Call each handler
        for receiver in receivers:
            try:
                if asyncio.iscoroutinefunction(receiver):
                    # Schedule async handler as task
                    asyncio.create_task(
                        self._handle_async(event, receiver, kwargs)
                    )
                else:
                    # Call sync handler immediately
                    receiver(sender=self, **kwargs)

            except Exception as e:
                logger.error(f"[EventBus] Error in handler for '{event}': {e}", exc_info=True)

    async def _handle_async(self, event: str, handler: Callable, kwargs: Dict[str, Any]):
        """Handle async event handler with error catching."""
        try:
            await handler(sender=self, **kwargs)
        except Exception as e:
            logger.error(f"[EventBus] Async handler error for '{event}': {e}", exc_info=True)

    def _preview_data(self, kwargs: Dict[str, Any]) -> str:
        """Create abbreviated preview of event data for logging."""
        if not kwargs:
            return "{}"

        preview_parts = []
        for key, value in kwargs.items():
            if isinstance(value, str):
                if len(value) > 50:
                    preview_parts.append(f"{key}='{value[:50]}...'")
                else:
                    preview_parts.append(f"{key}='{value}'")
            elif isinstance(value, dict):
                preview_parts.append(f"{key}={{{len(value)} keys}}")
            elif isinstance(value, list):
                preview_parts.append(f"{key}=[{len(value)} items]")
            else:
                preview_parts.append(f"{key}={type(value).__name__}")

        return ", ".join(preview_parts)

    def clear(self, event: Optional[str] = None):
        """
        Clear handlers.

        Args:
            event: Clear specific event, or all if None
        """
        if event:
            self._signals.pop(event, None)
            if self._log_events:
                logger.debug(f"[EventBus] Cleared handlers for '{event}'")
        else:
            self._signals.clear()
            if self._log_events:
                logger.debug("[EventBus] Cleared all handlers")


# Event name constants (type-safe)
class Events:
    """Event name constants for type safety and IDE autocomplete."""

    # Engine events (from EngineClient)
    ENGINE_STREAM_START = "engine:stream_start"
    ENGINE_STREAM_CHUNK = "engine:stream_chunk"
    ENGINE_STREAM_END = "engine:stream_end"
    ENGINE_ERROR = "engine:error"
    ENGINE_TOOL_CALL = "engine:tool_call"
    ENGINE_TOOL_RESULT = "engine:tool_result"
    ENGINE_CONTEXT_INJECTED = "engine:context_injected"
    ENGINE_CONSENT_FILE = "engine:consent_file"
    ENGINE_CONSENT_SHELL = "engine:consent_shell"

    # Consent responses (from UI)
    CONSENT_FILE_RESPONSE = "consent:file_response"
    CONSENT_SHELL_RESPONSE = "consent:shell_response"

    # UI events
    UI_CLEAR = "ui:clear"
    UI_STATUS_UPDATE = "ui:status_update"
    UI_THEME_CHANGED = "ui:theme_changed"

    # Session events
    SESSION_LOADED = "session:loaded"
    SESSION_SAVED = "session:saved"
    SESSION_CLEARED = "session:cleared"
```

**Files:** `ppxai/tui/event_bus.py` (NEW)
**Lines:** ~200
**Time:** 2 hours

#### Task 1.3: Add Event Bus to App
```python
# ppxai/tui/app.py (MODIFY - around line 80)

from .event_bus import EventBus, Events  # NEW

class PPXAIDEApp(App):
    def __init__(self):
        super().__init__()
        # ... existing code ...

        # Add event bus (NEW)
        self._event_bus = EventBus(log_events=True)  # Enable logging for debugging
        self._log.info("Event bus initialized")
```

**Files:** `ppxai/tui/app.py`
**Changes:** Add 2 lines
**Time:** 5 minutes

#### Task 1.4: Test Event Bus
```bash
# Test that event bus works
uv sync --all-extras  # Install blinker
uv run python -c "from ppxai.tui.event_bus import EventBus; bus = EventBus(); print('✅ EventBus imported')"
```

**Time:** 15 minutes

**Phase 1 Total:** 3 hours

---

### Phase 2: Wire Engine Events to Bus (Day 1-2 - 6 hours)

#### Task 2.1: Create Engine Event Bridge
```python
# ppxai/tui/app.py (MODIFY)

def _initialize_engine(self) -> None:
    """Initialize the engine client."""
    # ... existing initialization code ...

    # NEW: Subscribe to all engine events via event bus
    self._subscribe_to_engine_events()

    # Set working directory
    self._engine_client.set_working_dir(self._working_dir)

    if self._provider and self._model:
        self._log.info(f"Engine initialized: {self._provider}/{self._model}")
    else:
        self._log.warning("Engine not fully initialized")


def _subscribe_to_engine_events(self):
    """Subscribe to engine events via event bus (NEW)."""
    # Subscribe to engine events
    self._event_bus.on(Events.ENGINE_STREAM_START, self._on_stream_start)
    self._event_bus.on(Events.ENGINE_STREAM_CHUNK, self._on_stream_chunk)
    self._event_bus.on(Events.ENGINE_STREAM_END, self._on_stream_end)
    self._event_bus.on(Events.ENGINE_ERROR, self._on_error)
    self._event_bus.on(Events.ENGINE_TOOL_CALL, self._on_tool_call)
    self._event_bus.on(Events.ENGINE_TOOL_RESULT, self._on_tool_result)
    self._event_bus.on(Events.ENGINE_CONSENT_FILE, self._on_consent_file_request)
    self._event_bus.on(Events.ENGINE_CONSENT_SHELL, self._on_consent_shell_request)

    self._log.info("Subscribed to engine events via event bus")
```

**Files:** `ppxai/tui/app.py`
**Time:** 30 minutes

#### Task 2.2: Bridge _handle_event to Event Bus
```python
# ppxai/tui/app.py (MODIFY - around line 870)

async def _handle_event(self, event: Event) -> None:
    """
    Handle engine events by emitting to event bus.

    This bridges the old EngineClient event system to the new event bus.
    Event handlers are subscribed in _subscribe_to_engine_events().

    Args:
        event: Engine event
    """
    # Map EventType to event bus events
    event_map = {
        EventType.STREAM_START: Events.ENGINE_STREAM_START,
        EventType.STREAM_CHUNK: Events.ENGINE_STREAM_CHUNK,
        EventType.STREAM_END: Events.ENGINE_STREAM_END,
        EventType.ERROR: Events.ENGINE_ERROR,
        EventType.TOOL_CALL: Events.ENGINE_TOOL_CALL,
        EventType.TOOL_RESULT: Events.ENGINE_TOOL_RESULT,
        EventType.CONTEXT_INJECTED: Events.ENGINE_CONTEXT_INJECTED,
        # Consent events handled separately via callbacks
    }

    # Emit to event bus
    event_name = event_map.get(event.type)
    if event_name:
        self._event_bus.emit(event_name, event=event, data=event.data)
    else:
        self._log.warning(f"Unknown event type: {event.type}")
```

**Files:** `ppxai/tui/app.py`
**Changes:** Replace complex _handle_event with simple bridge
**Time:** 1 hour

#### Task 2.3: Implement Event Handlers
```python
# ppxai/tui/app.py (MODIFY)

# Event handlers (NEW - cleaner than before)

async def _on_stream_start(self, sender, event, data, **kwargs):
    """Handle stream start event."""
    self._log.debug("[Event] Stream started")
    self._current_message_content = ""

async def _on_stream_chunk(self, sender, event, data, **kwargs):
    """Handle stream chunk event."""
    self._log.debug(f"[Event] Chunk: {len(data)} chars")
    self._current_message_content += data

async def _on_stream_end(self, sender, event, data, **kwargs):
    """Handle stream end event."""
    self._log.info(f"[Event] Stream ended: data type={type(data).__name__}")

    chat_view = self.query_one("#chat-view", ChatView)

    # Get final response - use accumulated chunks OR event.data directly
    final_response = self._current_message_content

    # If no chunks accumulated, try to extract from event.data
    if not final_response:
        if isinstance(data, str):
            final_response = data
        elif isinstance(data, dict):
            final_response = data.get("content") or data.get("message") or data.get("text") or ""
            self._log.info(f"[Event] Extracted from dict: {len(final_response)} chars")
        else:
            final_response = str(data) if data else ""

    self._log.info(f"[Event] Final response: {len(final_response)} chars")

    # Display if there's content
    if final_response.strip():
        chat_view.add_assistant_message(final_response)
        self._log.info(f"[Event] Added assistant message")
    else:
        self._log.warning("[Event] STREAM_END with no content to display")

    self._current_message_content = ""

    # Update usage stats
    self._update_usage_display()

    # Auto-save session
    self._auto_save_session()

async def _on_error(self, sender, event, data, **kwargs):
    """Handle error event."""
    self._log.error(f"[Event] Error: {data}")
    chat_view = self.query_one("#chat-view", ChatView)
    chat_view.add_system_message(f"❌ Error: {data}", style="error")

async def _on_tool_call(self, sender, event, data, **kwargs):
    """Handle tool call event."""
    tool_name = data.get("tool", "unknown")
    self._log.info(f"[Event] Tool call: {tool_name}")

    chat_view = self.query_one("#chat-view", ChatView)

    # Format arguments for display
    args_str = self._format_tool_args(data.get("arguments", {}))

    # Display tool call
    chat_view.add_system_message(
        f"🔧 Tool: {tool_name}({args_str})",
        style="tool"
    )

async def _on_tool_result(self, sender, event, data, **kwargs):
    """Handle tool result event."""
    tool_name = data.get("tool", "unknown")
    success = data.get("success", True)
    self._log.info(f"[Event] Tool result: {tool_name} success={success}")

    # Display result (if needed)
    # ... existing code ...

async def _on_consent_file_request(self, sender, event, data, **kwargs):
    """Handle file consent request via event bus."""
    self._log.info(f"[Event] File consent requested: {data.get('filepath')}")

    # Show consent dialog
    result = await self._show_consent_dialog(
        title="⚠️  File Edit Request",
        message=f"AI wants to edit: {data.get('filepath')}",
        question="Allow this file edit?"
    )

    # Emit response back to engine (via callback)
    self._log.info(f"[Event] File consent response: {result}")
    # Note: Response is handled by callback return value

async def _on_consent_shell_request(self, sender, event, data, **kwargs):
    """Handle shell consent request via event bus."""
    command = data.get('command')
    risk = data.get('risk_level', 'medium')
    self._log.info(f"[Event] Shell consent requested: {command} (risk: {risk})")

    # Show consent dialog
    result = await self._show_consent_dialog(
        title="⚠️  Shell Command Request",
        message=f"AI wants to run: {command}",
        question=f"Allow this command? (Risk: {risk})",
        details=f"Working directory: {data.get('working_dir')}"
    )

    # Emit response back to engine (via callback)
    self._log.info(f"[Event] Shell consent response: {result}")
    # Note: Response is handled by callback return value
```

**Files:** `ppxai/tui/app.py`
**Changes:** Replace old handlers with event bus handlers
**Time:** 3 hours

#### Task 2.4: Wire Consent Callbacks to Event Bus
```python
# ppxai/tui/app.py (MODIFY)

async def _file_edit_consent_handler(self, file_path: str) -> tuple[bool, str]:
    """
    Handle file edit consent request using event bus.

    This is called by EngineClient. We emit to event bus and handle via event.
    """
    self._log.info(f"File consent callback invoked for: {file_path}")

    # Emit to event bus for handling
    # Note: We still use callback pattern, but log via event bus
    self._event_bus.emit(
        Events.ENGINE_CONSENT_FILE,
        filepath=file_path,
        data={"filepath": file_path}
    )

    try:
        result = await self._show_consent_dialog(
            title="⚠️  File Edit Request",
            message=f"AI wants to edit: {file_path}",
            question="Allow this file edit?"
        )
        return result

    except Exception as e:
        self._log.error(f"Consent dialog error: {e}")
        return (False, "no")


async def _shell_consent_handler(self, command: str, working_dir: str, risk_level: str) -> tuple[bool, str]:
    """
    Handle shell command consent request using event bus.

    This is called by EngineClient. We emit to event bus and handle via event.
    """
    self._log.info(f"Shell consent callback invoked: {command}")

    # Emit to event bus for handling
    self._event_bus.emit(
        Events.ENGINE_CONSENT_SHELL,
        command=command,
        working_dir=working_dir,
        risk_level=risk_level,
        data={"command": command, "working_dir": working_dir, "risk_level": risk_level}
    )

    try:
        result = await self._show_consent_dialog(
            title="⚠️  Shell Command Request",
            message=f"AI wants to run: {command}",
            question=f"Allow this command? (Risk: {risk_level})",
            details=f"Working directory: {working_dir}"
        )
        return result

    except Exception as e:
        self._log.error(f"Consent dialog error: {e}")
        return (False, "no")
```

**Files:** `ppxai/tui/app.py`
**Changes:** Add event bus emission to consent callbacks
**Time:** 1 hour

**Phase 2 Total:** 5.5 hours

---

### Phase 3: Testing & Debugging (Day 2-3 - 8 hours)

#### Task 3.1: Test Basic Chat Flow
```bash
# Run ppxaide with tracing
PPXAI_CONFIG_FILE=~/.ppxai/ppxai-config.json uv run ppxaide --trace

# Test scenarios:
# 1. Send simple message (check STREAM_CHUNK events in log)
# 2. Check STREAM_END handling (non-streaming provider)
# 3. Verify message displayed
```

**Expected log output:**
```
[EventBus] Emit 'engine:stream_start': {}
[Event] Stream started
[EventBus] Emit 'engine:stream_chunk': data='Hello...'
[Event] Chunk: 5 chars
[EventBus] Emit 'engine:stream_end': data={1 keys}
[Event] Stream ended: data type=dict
[Event] Extracted from dict: 100 chars
[Event] Final response: 100 chars
[Event] Added assistant message
```

**Time:** 2 hours

#### Task 3.2: Test Consent Dialogs
```bash
# Enable tools
/tools enable

# Try file edit (should trigger consent)
# User: "Edit example.txt and add 'test'"

# Try shell command (should trigger consent)
# User: "Run ls -la"
```

**Expected log output:**
```
File consent callback invoked for: example.txt
[EventBus] Emit 'engine:consent_file': filepath='example.txt'
[Event] File consent requested: example.txt
[Event] File consent response: (True, 'yes')
```

**Time:** 2 hours

#### Task 3.3: Debug Any Issues
- Check event bus logs for missing events
- Verify all handlers are subscribed
- Check for race conditions
- Fix any async coordination issues

**Time:** 3 hours

#### Task 3.4: Test Edge Cases
- Non-streaming providers (Gemini, custom)
- Error handling
- Session save/restore
- Multiple tool calls in sequence

**Time:** 1 hour

**Phase 3 Total:** 8 hours

---

### Phase 4: Fix Language Cycle Crash (Day 3 - 2 hours)

While testing, also fix the language cycle crash bug.

#### Task 4.1: Remove Unsupported Languages
```python
# ppxai/tui/widgets/code_editor.py (MODIFY)

SUPPORTED_LANGUAGES = {
    "bash", "css", "html", "javascript", "json",
    "markdown", "python", "toml", "yaml"
}  # Removed: go, rust, sql, xml, java, regex
```

**Files:** `ppxai/tui/widgets/code_editor.py`
**Time:** 30 minutes

#### Task 4.2: Test Language Cycling
```bash
# Run ppxaide
uv run ppxaide

# Open file: /show .env
# Press Ctrl+L repeatedly to cycle languages
# Should not crash
```

**Time:** 30 minutes

#### Task 4.3: Update Documentation
Update BUG-LANGUAGE-CYCLE-CRASH.md with resolution.

**Time:** 1 hour

**Phase 4 Total:** 2 hours

---

### Phase 5: Documentation & Cleanup (Day 4 - 2 hours)

#### Task 5.1: Update Technical Debt Doc
```markdown
# docs/PPXAIDE-TECHNICAL-DEBT-2026-01-27.md

### CRITICAL (Blocking Basic Functionality)

| Issue | Status | File | Problem |
|-------|--------|------|---------|
| ~~**AI Responses Not Displayed**~~ | ✅ FIXED | Event bus integration | Now visible via event logging |
| ~~**Tool Consent Broken**~~ | ✅ FIXED | Event bus integration | Callbacks now logged and debuggable |
| **Tab Autocomplete** | DISABLED | `ppxai/tui/widgets/input_box.py` | Deferred to v1.16.0 (readline-style) |
```

#### Task 5.2: Add Event Bus Documentation
```markdown
# docs/EVENT-BUS-USAGE.md (NEW)

Guide for using event bus in ppxaide.
```

#### Task 5.3: Update CHANGELOG
```markdown
# CHANGELOG.md

## [1.15.0] - 2026-01-XX

### Added - Event Bus Pattern
- **Event bus** using blinker for decoupled component communication
- Event logging for improved debugging visibility
- Simplified async event handling (no Future complexity)
```

#### Task 5.4: Clean Up Old Code
- Remove unused Future-based consent code (if any)
- Remove old complex event handling
- Clean up imports

**Phase 5 Total:** 2 hours

---

## Timeline Summary

| Phase | Tasks | Time | Day |
|-------|-------|------|-----|
| **Phase 1** | Add blinker infrastructure | 3 hours | Day 1 |
| **Phase 2** | Wire engine events to bus | 5.5 hours | Day 1-2 |
| **Phase 3** | Testing & debugging | 8 hours | Day 2-3 |
| **Phase 4** | Fix language cycle crash | 2 hours | Day 3 |
| **Phase 5** | Documentation & cleanup | 2 hours | Day 4 |
| **TOTAL** | | **20.5 hours** | **3-4 days** |

---

## Success Criteria

### Must Have (Blocking Release)
- ✅ Event bus integrated and working
- ✅ AI responses displayed correctly
- ✅ Consent dialogs working and debuggable
- ✅ Event logging visible in --trace mode
- ✅ Language cycle crash fixed
- ✅ No regressions in existing features
- ✅ All manual tests pass

### Should Have (Nice to Have)
- ✅ Event bus documentation
- ✅ Technical debt doc updated
- ✅ CHANGELOG updated
- ✅ Code cleanup done

### Nice to Have (Can Defer)
- Event bus unit tests
- Performance benchmarks
- More event types

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Event bus breaks existing code | Low | High | Incremental integration, keep old _handle_event as fallback |
| Async coordination issues | Medium | Medium | Thorough testing, event logging helps debug |
| Performance degradation | Low | Low | Event bus is lightweight, minimal overhead |
| Blinker dependency issues | Very Low | Low | Well-maintained library, stable API |

**Overall Risk:** Low-Medium

---

## Testing Plan

### Unit Tests (Optional for v1.15.0)
```python
# tests/test_event_bus.py (optional)
def test_event_bus_emit():
    bus = EventBus()
    received = []
    bus.on("test", lambda sender, **kw: received.append(kw))
    bus.emit("test", data="hello")
    assert received[0]["data"] == "hello"
```

### Manual Tests (Required)
1. **Basic chat** - Send message, verify response displayed
2. **Non-streaming** - Test with non-streaming provider (Gemini)
3. **Consent** - Enable tools, trigger file/shell consent
4. **Errors** - Trigger error, verify displayed
5. **Session** - Save/load session, verify works
6. **Language cycle** - Press Ctrl+L, verify no crash
7. **Theme cycle** - Press Ctrl+T, verify works

### Regression Tests
- All existing slash commands work
- Status bar updates correctly
- Help system works
- Session save/restore works

---

## Rollback Plan

If event bus integration causes critical issues:

1. **Revert commits** - `git revert <commit-hash>`
2. **Keep improvements** - Language cycle fix can stay
3. **Release v1.15.0** without event bus
4. **Plan v1.15.1** with event bus fixes

**Revert time:** <30 minutes

---

## Post-Integration Benefits

### Immediate (v1.15.0)
- ✅ AI responses visible (bug fixed)
- ✅ Consent dialogs debuggable (logging)
- ✅ Easier debugging (event visibility)
- ✅ Cleaner code (~200 lines reduction estimated)

### Near-term (v1.16.0)
- ✅ Ready for embedded server thread (events cross threads)
- ✅ Easier to add new event types
- ✅ Better testing (mock event bus)

### Long-term (v1.17.0+)
- ✅ Easy migration to NATS (same pattern)
- ✅ Distributed architecture ready
- ✅ Multi-agent coordination possible

---

## Next Steps

1. **Review this plan** with team
2. **Start Phase 1** - Add blinker infrastructure
3. **Test incrementally** - Don't integrate everything at once
4. **Use event logging** - Monitor all events in --trace mode
5. **Fix bugs as found** - Event visibility helps debug
6. **Document learnings** - Update this doc with findings

---

## Status Tracking

- [ ] Phase 1: Add blinker infrastructure
  - [ ] Task 1.1: Add dependency
  - [ ] Task 1.2: Create event bus module
  - [ ] Task 1.3: Add event bus to app
  - [ ] Task 1.4: Test event bus

- [ ] Phase 2: Wire engine events to bus
  - [ ] Task 2.1: Create engine event bridge
  - [ ] Task 2.2: Bridge _handle_event to event bus
  - [ ] Task 2.3: Implement event handlers
  - [ ] Task 2.4: Wire consent callbacks

- [ ] Phase 3: Testing & debugging
  - [ ] Task 3.1: Test basic chat flow
  - [ ] Task 3.2: Test consent dialogs
  - [ ] Task 3.3: Debug any issues
  - [ ] Task 3.4: Test edge cases

- [ ] Phase 4: Fix language cycle crash
  - [ ] Task 4.1: Remove unsupported languages
  - [ ] Task 4.2: Test language cycling
  - [ ] Task 4.3: Update documentation

- [ ] Phase 5: Documentation & cleanup
  - [ ] Task 5.1: Update technical debt doc
  - [ ] Task 5.2: Add event bus documentation
  - [ ] Task 5.3: Update CHANGELOG
  - [ ] Task 5.4: Clean up old code

**Target Completion:** End of Day 4
**Release Target:** v1.15.0

# TUI vs VSCode Consistency Analysis

**Date**: 2025-12-22
**Version**: v1.11.1
**Status**: Critical Analysis Post-Regression

## Executive Summary

The v1.11.0 regression ("TUI doesn't display AI responses when tools enabled") was **not caught by tests** because there are **no integration tests for the main TUI chat loop**. This document analyzes TUI/VSCode consistency and test coverage gaps.

---

## Critical Test Coverage Gaps

### 1. **Main TUI Loop - UNTESTED** ⚠️

**File**: `ppxai/main.py` (lines 213-377)

**What's Missing**:
- No tests for the main chat loop
- No tests for message display after AI responses
- No tests for event stream handling
- No tests for EngineClient integration in TUI context

**Why Regression Wasn't Caught**:
```python
# v1.11.0 BUG (not caught by tests):
response = engine_client.chat_sync(message)  # Returns string
# BUT: No console.print(response) - user sees nothing!
```

**What Tests Exist**:
- `tests/test_commands.py` - Only tests command handlers in isolation
- `tests/test_client.py` - Only tests AIClient (legacy)
- **ZERO tests for main.py chat loop**

### 2. **EngineClient TUI Integration - UNTESTED** ⚠️

**File**: `ppxai/main.py` (lines 268-335)

**What's Missing**:
- No tests for `hasattr(handler, 'engine_client')` path
- No tests for async event stream consumption
- No tests for tool execution with engine client
- No tests for conversation history sync

**What Tests Exist**:
- `tests/test_file_editing_tools.py` - Tests tools in isolation
- `tests/test_http_server.py` - Tests EngineClient for server context
- **ZERO tests for TUI context**

### 3. **Conversation History Sync - PARTIALLY TESTED** ⚠️

**Files**:
- `ppxai/commands.py` (lines 541-549) - Sync on enable
- `ppxai/main.py` (lines 330-335) - Sync after response

**What's Missing**:
- No tests for history sync when enabling tools
- No tests for history sync after each response
- No tests for 400 error prevention

**Current Behavior**: The 400 error you encountered was due to history desync between legacy client and engine client.

---

## TUI vs VSCode Execution Paths

### VSCode Extension Flow (TESTED)

**File**: `vscode-extension/src/chatPanel.ts`

```typescript
// Event-based from day 1
const response = await fetch('/api/chat', {
  method: 'POST',
  body: JSON.stringify({message})
});

const reader = response.body.getReader();
while (true) {
  const {value, done} = await reader.read();
  if (done) break;

  const event = parseSSE(value);
  if (event.type === 'stream_chunk') {
    appendToUI(event.data);  // Always renders!
  }
}
```

**Why It Works**: HTTP server (`test_http_server.py`) tests the full event flow.

### TUI Flow (UNTESTED Until v1.11.1)

**File**: `ppxai/main.py` (lines 268-335)

```python
# v1.11.0 (BROKEN - untested)
response = engine_client.chat_sync(message)  # No display!

# v1.11.1 (FIXED - still untested)
async for event in engine_client.chat(message, stream=True):
    if event.type == EventType.STREAM_CHUNK:
        full_response += event.data
    elif event.type == EventType.STREAM_END:
        render_markdown_with_tables(full_response, console)  # NOW displays
```

**Why v1.11.0 Broke**: Changed execution path without integration tests.

---

## Command Behavior Consistency

### Commands Currently Consistent ✅

| Command | TUI Behavior | VSCode Behavior | Status |
|---------|-------------|-----------------|--------|
| `/help` | Shows welcome | N/A (VSCode doesn't use slash commands) | ✅ N/A |
| `/clear` | Clears history | Clear button | ✅ Consistent |
| `/model` | Interactive selection | Dropdown | ✅ Consistent |
| `/provider` | Interactive selection | N/A (server-level) | ✅ N/A |
| `/save` | Saves to JSON | Save button | ✅ Consistent (v1.10.8+) |
| `/export` | Exports to markdown | Save Answer button | ✅ Consistent (v1.10.8+) |
| `/usage` | Shows token usage | N/A | ✅ N/A |

### Tool Commands - Newly Consistent ✅

| Command | TUI Behavior | VSCode Behavior | Status |
|---------|-------------|-----------------|--------|
| `/tools enable` | Enables engine client | Toggle button | ✅ Consistent (v1.11.1) |
| `/tools disable` | Disables engine client | Toggle button | ✅ Consistent (v1.11.1) |
| `/tools list` | Shows available tools | N/A | ✅ N/A |
| `/tools status` | Shows tools status | Shows in UI | ✅ Consistent |
| `/tools set verbose` | Toggle tool logging | N/A | ✅ New (v1.11.1) |

### Coding Commands (TUI-Only)

| Command | TUI Behavior | VSCode Equivalent | Status |
|---------|-------------|-------------------|--------|
| `/explain <file>` | Explains code | Editor context menu | ✅ Equivalent |
| `/test <file>` | Generates tests | Editor context menu | ✅ Equivalent |
| `/review <file>` | Reviews code | N/A | ⚠️ TUI-only |
| `/debug <error>` | Debugs error | N/A | ⚠️ TUI-only |
| `/optimize <file>` | Optimizes code | N/A | ⚠️ TUI-only |
| `/generate <spec>` | Generates code | N/A | ⚠️ TUI-only |
| `/implement <spec>` | Implements feature | N/A | ⚠️ TUI-only |

---

## Event Stream Behavior Consistency

### v1.11.1 - NOW CONSISTENT ✅

| Event Type | TUI Handler | VSCode Handler | Status |
|------------|------------|----------------|--------|
| `STREAM_START` | Print header | Show loading | ✅ Consistent |
| `STREAM_CHUNK` | Accumulate silently | Accumulate + preview | ✅ Similar |
| `TOOL_CALL` | Print tool name | Show in UI | ✅ Consistent |
| `TOOL_RESULT` | Print if verbose | Show if verbose | ✅ Consistent (v1.11.1) |
| `CONSENT_REQUEST` | Modal prompt | Modal dialog | ✅ Consistent |
| `STREAM_END` | Render markdown | Render markdown | ✅ Consistent |
| `ERROR` | Print error | Show error | ✅ Consistent |

---

## Test Coverage Recommendations

### Priority 1: Main Loop Integration Tests (CRITICAL)

**File**: `tests/test_main_loop.py` (NEW)

```python
@pytest.mark.asyncio
async def test_tui_displays_response_with_tools_enabled():
    """Regression test for v1.11.0 bug."""
    # Setup
    handler = CommandHandler(...)
    handler.tools_available = True
    handler.engine_client = EngineClient(...)

    # Capture console output
    captured_output = []

    with patch('ppxai.main.console.print') as mock_print:
        mock_print.side_effect = lambda *args: captured_output.append(str(args))

        # Send message
        user_input = "What is 2+2?"

        # Execute main loop logic
        async for event in handler.engine_client.chat(user_input, stream=True):
            if event.type == EventType.STREAM_END:
                render_markdown_with_tables(event.data, console)

        # Verify response was displayed
        assert len(captured_output) > 0
        assert "4" in "".join(captured_output)


@pytest.mark.asyncio
async def test_conversation_history_sync_prevents_400_error():
    """Test that history stays synced between clients."""
    handler = CommandHandler(...)
    handler.engine_client = EngineClient(...)

    # First message
    await handler.engine_client.chat("Hello")

    # Sync history
    handler.client.conversation_history = [
        {"role": msg.role, "content": msg.content}
        for msg in handler.engine_client.session.messages
    ]

    # Second message (should not error)
    async for event in handler.engine_client.chat("How are you?"):
        if event.type == EventType.ERROR:
            pytest.fail(f"Got error: {event.data}")
```

### Priority 2: Event Stream Tests

**File**: `tests/test_tui_event_stream.py` (NEW)

```python
@pytest.mark.asyncio
async def test_tui_handles_all_event_types():
    """Test that TUI processes all event types correctly."""
    events = [
        Event(EventType.STREAM_START, {"model": "sonar-pro"}),
        Event(EventType.STREAM_CHUNK, "Hello"),
        Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {}}),
        Event(EventType.TOOL_RESULT, {"tool": "read_file", "result": "content"}),
        Event(EventType.CONSENT_REQUEST, {"file": "/tmp/test.txt"}),
        Event(EventType.STREAM_END, "Hello, how can I help?"),
    ]

    # Verify each event is handled without errors
    for event in events:
        # Process event through TUI event handlers
        # (lines 281-324 in main.py)
        pass  # Implement actual logic
```

### Priority 3: Tool Integration Tests

**File**: `tests/test_tui_tools_integration.py` (NEW)

```python
@pytest.mark.asyncio
async def test_verbose_mode_shows_tool_details():
    """Test /tools set verbose on shows arguments and results."""
    handler = CommandHandler(...)
    handler.tools_verbose = True
    handler.engine_client = EngineClient(...)

    # Capture output
    captured = []
    with patch('ppxai.main.console.print') as mock_print:
        mock_print.side_effect = lambda *args: captured.append(str(args))

        # Execute tool call
        async for event in handler.engine_client.chat("read README.md"):
            if event.type == EventType.TOOL_CALL:
                # Should show arguments
                pass

        # Verify verbose output
        assert any("Arguments:" in line for line in captured)
        assert any("Result:" in line for line in captured)
```

---

## Behavioral Consistency Checklist

### Core Chat Flow
- [x] TUI displays AI responses when tools enabled (v1.11.1)
- [x] TUI uses event-based streaming like VSCode (v1.11.1)
- [x] TUI renders markdown tables properly (v1.10.4)
- [x] TUI handles Ctrl-C gracefully (v1.10.5)
- [ ] **TUI chat flow has integration tests** ⚠️ MISSING
- [ ] **Conversation history sync tested** ⚠️ MISSING

### Tool Behavior
- [x] TUI shows tool calls during execution (v1.11.1)
- [x] TUI requests consent for file edits (v1.11.0)
- [x] TUI verbose mode shows tool I/O (v1.11.1)
- [ ] **Tool execution flow tested end-to-end** ⚠️ PARTIAL

### Error Handling
- [x] TUI handles API errors gracefully
- [x] TUI cleans up conversation on interrupt (v1.10.5)
- [ ] **400 error prevention tested** ⚠️ MISSING

---

## Recommendations

### Immediate (v1.11.1)
1. ✅ **DONE**: Fix TUI response display
2. ✅ **DONE**: Fix conversation history sync
3. ✅ **DONE**: Add verbose tool logging
4. ⚠️ **TODO**: Add integration tests for main loop

### Short-term (v1.11.2)
1. Add `tests/test_main_loop.py` with regression tests
2. Add `tests/test_tui_event_stream.py`
3. Add `tests/test_tui_tools_integration.py`
4. Set up CI to catch regressions

### Long-term (v1.12.0+)
1. Add visual regression testing for TUI
2. Add end-to-end tests for full workflows
3. Add performance regression tests
4. Add compatibility tests for all providers

---

## Conclusion

**Why v1.11.0 Regression Wasn't Caught**:
- **Zero integration tests** for main TUI loop
- **Command tests** only test handlers in isolation
- **No end-to-end tests** for chat flow with tools

**How to Prevent Future Regressions**:
- Add integration tests that exercise full chat flow
- Test with `engine_client` both enabled and disabled
- Test conversation history sync explicitly
- Add visual/behavioral assertions, not just unit tests

**Current Status (v1.11.1)**:
- Behavior is now **consistent** between TUI and VSCode
- Event stream processing is **unified**
- But tests still **don't cover the main loop** ⚠️

---

**Last Updated**: 2025-12-22
**Author**: Claude Code
**Related Docs**:
- [ROADMAP.md](../ROADMAP.md)
- [CHANGELOG.md](../CHANGELOG.md)
- [docs/tui-rendering-options.md](tui-rendering-options.md)

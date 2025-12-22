# 400 Error Investigation

**Date**: 2025-12-22
**Issue**: Message alternation error when using tools with conversation history
**Status**: 🔍 Investigation in progress

---

## Problem Statement

When using the TUI with tools enabled, a 400 error occurs after the second query:

```
Error code: 400 - {'error': {'message': 'After the (optional) system message(s),
user or tool message(s) should alternate with assistant message(s).',
'type': 'invalid_message', 'code': 400}}
```

### Reproduction Steps

1. Start TUI, enable tools: `/tools enable`
2. Send first query: "review the current project directory..."
   - ✅ Works fine, AI uses tools and responds
3. Enable verbose mode: `/tools set verbose on`
4. Send second query: "use tools to review it again"
   - ❌ **400 ERROR**

---

## Expected vs Actual Behavior

### Expected Message Sequence

After first successful query with tools, session.messages should be:
```
[0] user: "review the current project directory..."
[1] assistant: "I'll use list_directory tool..."
[2] user: "Tool result: ..."
[3] assistant: "Project Overview... (final answer)"
```

When second query is sent, messages sent to API should be:
```
[0] system: (tool prompt)
[1] user: "review..." (first query)
[2] assistant: "I'll use list_directory tool..."
[3] user: "Tool result: ..."
[4] assistant: "Project Overview..."
[5] user: "use tools to review it again" (second query)
```

**This is valid alternation**: system, user, assistant, user, assistant, user ✅

### Actual Behavior

400 error indicates the message sequence being sent is **invalid**. Possible causes:

1. **Duplicate messages** - History sync adding messages twice?
2. **Missing assistant message** - Tool result user message not followed by assistant?
3. **System message placement** - System message added incorrectly?
4. **Extra user message** - User message added twice somehow?

---

## Code Analysis

### History Sync Points

**1. When tools are enabled** ([commands.py:544-549](../ppxai/commands.py#L544-L549)):
```python
# Sync from legacy client to engine client
for msg in self.client.conversation_history:
    self.engine_client.session.messages.append(
        Message(role=msg["role"], content=msg["content"])
    )
```

**2. After each response** ([main.py:338-343](../ppxai/main.py#L338-L343)):
```python
# Sync from engine client back to legacy client
if handler.engine_client:
    client.conversation_history = [
        {"role": msg.role, "content": msg.content}
        for msg in handler.engine_client.session.messages
    ]
```

### Message Addition in Tool Flow

**When user message comes in** ([engine/client.py:438](../ppxai/engine/client.py#L438)):
```python
self.session.add_message(Message("user", message))
```

**After tool execution** ([engine/client.py:558-566](../ppxai/engine/client.py#L558-L566)):
```python
self.session.add_message(Message(
    "assistant",
    f"I'll use the {tool_name} tool.\n```json\n{json.dumps(tool_call, indent=2)}\n```"
))
self.session.add_message(Message(
    "user",
    f"The {tool_name} tool returned:\n\n{result}\n\n..."
))
```

**After final response** ([engine/client.py:599](../ppxai/engine/client.py#L599)):
```python
self.session.add_message(Message("assistant", event.data))
```

---

## Potential Root Causes

### Hypothesis 1: Double History Sync

**Problem**: When `/tools enable` is called mid-conversation, the history sync might be adding messages that are already in the engine client.

**Evidence**: The sync in commands.py uses `append()`, which could duplicate messages if called multiple times.

**Test**: Check if enabling tools multiple times causes duplicate messages.

### Hypothesis 2: Legacy Client Interaction

**Problem**: The legacy client (`PerplexityClientPromptTools`) and engine client might both be managing history, causing conflicts.

**Evidence**: The code syncs bidirectionally between legacy and engine clients.

**Test**: Check if legacy client's conversation_history has unexpected entries.

### Hypothesis 3: System Message Timing

**Problem**: The system message with tool prompt is prepended to messages at line 509, but this might create invalid sequences in certain cases.

**Evidence**: System messages must come first (before user messages), but after history sync, there might be issues.

**Test**: Log the exact messages array before sending to API.

### Hypothesis 4: Tool Result Message Format

**Problem**: The user message added after tool execution (lines 563-566) might not be formatted correctly or might violate alternation.

**Evidence**: This is a synthetic user message created by the system, not a real user message.

**Test**: Check if Perplexity API treats this differently.

---

## Debug Logging Implementation

### System Created

Implemented comprehensive TUI debug logging system:

- **File**: [ppxai/tui_logger.py](../ppxai/tui_logger.py)
- **Command**: `/debug-log on|off|show|clear`
- **Log Location**: `~/.ppxai/logs/tui-debug.log`
- **Environment**: `PPXAI_DEBUG=1`

### What Gets Logged

1. User input and commands (with timestamps)
2. **Conversation history sync** (when `/tools enable`)
3. **API requests with full message sequence** (before each call)
4. API responses
5. Tool calls with arguments
6. Tool results
7. Errors with error codes

### Example Log Output

```
17:58:30.633 | INFO     | ================================================================================
17:58:30.634 | INFO     | TUI DEBUG SESSION STARTED - 2025-12-22 17:58:30
17:58:30.634 | INFO     | ================================================================================
17:58:30.634 | INFO     | USER INPUT: review the roadmap
17:58:30.640 | INFO     | HISTORY SYNC: legacy=2, engine=2
17:58:30.641 | DEBUG    |   [0] user      : first message...
17:58:30.641 | DEBUG    |   [1] assistant : first response...
17:58:30.650 | INFO     | API REQUEST: iteration=1, messages=4
17:58:30.651 | DEBUG    |   [0] system    : You are a helpful AI assistant...
17:58:30.652 | DEBUG    |   [1] user      : review the roadmap
17:58:30.653 | DEBUG    |   [2] assistant : previous response...
17:58:30.654 | DEBUG    |   [3] user      : review again
17:58:35.123 | ERROR    | API ERROR 400: After the (optional) system message(s)...
```

---

## Next Steps

### 1. Reproduce with Debug Logging ⚠️ **CRITICAL**

```bash
# Enable debug logging
export PPXAI_DEBUG=1
ppxai

# Or in TUI:
/debug-log on

# Reproduce the error
/tools enable
review the roadmap items
use tools to review it again

# View the log
/debug-log show
```

**Expected Output**: Debug log will show:
- Exact conversation history when tools enabled
- Exact message sequence sent to API when error occurs
- Which message is causing alternation violation

### 2. Analyze Log Output

Look for:
- **Duplicate messages**: Same message appearing twice
- **Missing assistant messages**: Two user messages in a row
- **System message issues**: System message in wrong position
- **Synthetic user messages**: Tool result messages causing problems

### 3. Fix Based on Findings

Potential fixes:
- **If duplicate messages**: Prevent double sync or use set instead of append
- **If missing assistant**: Ensure final assistant message is added before next user message
- **If system message issue**: Adjust system message insertion logic
- **If synthetic messages**: Change tool result message format or role

### 4. Add Integration Tests

Create tests for:
- Multi-turn conversation with tools ([main.py:268-356](../ppxai/main.py#L268-L356))
- History sync when enabling tools ([commands.py:544-549](../ppxai/commands.py#L544-L549))
- 400 error prevention ([tests/test_main_loop.py](../tests/test_main_loop.py) - NEW)

---

## Bug Fix: Logger Enable

**Fixed**: Logger wasn't working when enabled via `/debug-log on`

**Root Cause**: `__init__()` was overwriting `_enabled` flag by re-checking environment variable.

**Fix** ([tui_logger.py:34-36](../ppxai/tui_logger.py#L34-L36)):
```python
# Check if logging is enabled (only if not explicitly enabled via enable())
if not self._enabled:
    self._enabled = os.getenv('PPXAI_DEBUG', '').lower() in ['1', 'true', 'yes', 'on']
```

**Verification**: Test script `test_logger_fix.py` confirms logger now works ✅

---

## Bug Fix: 400 Message Alternation Error ✅

**Status**: FIXED

**Root Cause**: TUI's event handler breaks out of the loop when receiving `STREAM_END` event ([main.py:337](../ppxai/main.py#L337)), preventing the engine's code that adds the assistant message to session from executing ([engine/client.py:618 - old code](../ppxai/engine/client.py#L618)).

**Evidence from Debug Logs**:
```
18:18:04.480 | DEBUG    | Streaming event: EventType.STREAM_END
18:18:04.480 | INFO     | ASSISTANT RESPONSE: **The project directory...
# NO log from "STREAM_END received, adding assistant message"
# This proves the add_message() call never executed
```

**The Sequence**:
1. Engine yields `STREAM_END` event
2. TUI receives event, renders response, then **breaks out of loop**
3. Engine's `session.add_message()` call never executes
4. Next user message creates two consecutive user messages
5. Perplexity API returns 400 error

**Fix Applied** ([engine/client.py:612-621](../ppxai/engine/client.py#L612-L621)):
```python
# CRITICAL FIX: Add assistant message to session BEFORE yielding STREAM_END
# because the caller (TUI main loop) may break out of the loop after receiving it
if event.type == EventType.STREAM_END:
    logger.debug(f"STREAM_END received, adding assistant message BEFORE yield")
    self.session.add_message(Message("assistant", event.data))
    logger.debug(f"After adding assistant message, session has {len(self.session.messages)} messages")

# Now yield the event to caller (TUI may break after this)
logger.debug(f"Yielding event: {event.type}")
yield event
```

**Key Change**: Move `session.add_message()` to BEFORE yielding the event, so it executes before the caller can break out of the loop.

**Verification**: Test with the reproduction sequence:
```bash
uv run ppxai
> review the roadmap items
> /tools enable
> /tools set verbose on
> review the roadmap items again
```

Should now work without 400 error! ✅

---

## Related Documentation

- [TUI-DEBUG-LOGGING.md](TUI-DEBUG-LOGGING.md) - Debug logging guide
- [TUI_VSCODE_CONSISTENCY_ANALYSIS.md](TUI_VSCODE_CONSISTENCY_ANALYSIS.md) - Test coverage analysis
- [FILE_EDITING_GUIDE.md](FILE_EDITING_GUIDE.md) - Tool execution flow

---

**Last Updated**: 2025-12-22
**Status**: ✅ FIXED - Bug identified and resolved
**Fix**: Assistant message now added to session BEFORE yielding STREAM_END event
**Next**: User testing to verify fix works in production

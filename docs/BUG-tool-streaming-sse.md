# BUG: Tool Call JSON Leaks to VSCode Extension During Streaming

**Created:** 2025-12-26
**Status:** Open
**Priority:** High (blocks `/agent` feature)
**Affects:** VSCode Extension with tools enabled

## Problem

When tools are enabled and the AI decides to call a tool, the raw JSON tool call is visible to the user in the VSCode extension before the tool executes.

## Expected Behavior

User asks: "Explore the project"
→ AI calls `list_directory` tool internally
→ User sees: "Here's the project structure: ..."

## Actual Behavior

User asks: "Explore the project"
→ User sees: "I'll use the list_directory tool.\n```json\n{\"tool\": \"list_directory\", ...}\n```"
→ Response ends
→ User must type "continue" to trigger tool execution

## Root Cause Analysis

1. **Engine Architecture**: `_chat_with_tools()` uses `stream=False` for provider calls (line 683 in client.py)
2. **SSE Events**: The engine emits `stream_chunk` and `stream_end` events for the raw response
3. **VSCode Extension**: Treats `stream_end` as "conversation complete" and displays the response
4. **Tool Loop Continues**: Engine parses tool call and continues, but VSCode already closed connection

## Evidence from Logs

```
03:31:34.231 | DEBUG    | SSE: stream_end - I'll use the list_directory tool.
```json
{
  "tool": "list_directory",
  ...
}
```

03:31:44.597 | INFO     | HTTP POST /chat from vscode
03:31:44.599 | INFO     | USER INPUT: continue
03:31:48.025 | INFO     | TOOL CALL: list_directory  ← Tool executes in NEW request
```

## Proposed Fix

**Option A: Suppress stream events during tool iterations**
- Don't emit `stream_chunk`/`stream_end` until tool loop completes
- Buffer intermediate responses internally
- Only emit final synthesized response

**Option B: New event type for tool iterations**
- Add `TOOL_ITERATION_START` / `TOOL_ITERATION_END` events
- VSCode extension knows to wait for final response
- More complex but preserves visibility

**Option C: Buffer in SSE generator**
- `sse_event_generator()` buffers tool iteration responses
- Only emits when iteration contains no tool call
- Simpler change, localized to server layer

## Files to Modify

- `ppxai/engine/client.py` - `_chat_with_tools()` method
- `ppxai/server/http.py` - `sse_event_generator()` function
- `vscode-extension/src/httpClient.ts` - Event handling (if Option B)

## Testing

1. Enable tools in VSCode extension
2. Ask "Explore this project" or similar
3. Verify no raw JSON appears in response
4. Verify tool results are synthesized into response

## Impact on /agent

This bug must be fixed before implementing `/agent` command, as the agent loop will make multiple tool calls per turn.

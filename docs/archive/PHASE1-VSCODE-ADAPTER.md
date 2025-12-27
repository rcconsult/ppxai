### Task 3.5: Update HTTP Server for VSCode Extension 🔴 HIGH PRIORITY

**Estimated Time**: 1-2 hours

**Purpose**: Update `ppxai/server/http.py` to use shared logger, ensuring VSCode extension has debug logging capabilities.

**Current State**:
- HTTP server handles events directly in `sse_event_generator`
- No debug logging for server operations
- VSCode extension has no visibility into server-side processing

**Implementation** (Simpler Approach for v1.12.0):

Add shared logger to HTTP server without changing event handling logic. This minimal change gives VSCode extension debug logging without refactoring risk.

**Code Changes**:

1. **Import shared logger** (top of file):
```python
from ..common.logger import get_logger

# Get server logger (separate log file from TUI)
logger = get_logger("server")
```

2. **Update `sse_event_generator`** (add logging):
```python
async def sse_event_generator(prompt: str) -> AsyncGenerator[str, None]:
    global engine
    if not engine:
        logger.error("Engine not initialized for SSE request")
        yield f"data: {json.dumps({'type': 'error', 'data': 'Engine not initialized'})}\n\n"
        return

    try:
        logger.log_api_request(1, [])  # Log request start
        logger.log_user_message(prompt)

        async for event in engine.chat(prompt):
            # Check for consent requests (existing code)
            while engine._consent_event_queue:
                consent_event = engine._consent_event_queue.pop(0)
                logger.debug(f"Consent request for: {consent_event.data.get('file_path')}")
                # ... existing SSE emission ...

            # Log key events
            if event.type == EventType.STREAM_END:
                logger.log_assistant_message(event.data)
            elif event.type == EventType.TOOL_CALL:
                logger.log_tool_call(
                    event.data.get('tool', 'unknown'),
                    event.data.get('arguments', {})
                )
            elif event.type == EventType.TOOL_RESULT:
                tool_name = event.data.get('tool', 'unknown') if isinstance(event.data, dict) else 'unknown'
                logger.log_tool_result(tool_name, str(event.data))
            elif event.type == EventType.ERROR:
                logger.log_api_error(0, str(event.data))

            # Emit SSE event (UNCHANGED - existing code continues to work)
            event_data = {"type": event.type.value, "data": event.data}
            if event.metadata:
                event_data["metadata"] = event.metadata
            yield f"data: {json.dumps(event_data)}\n\n"
            await asyncio.sleep(0)

    except Exception as e:
        logger.error(f"SSE stream error: {str(e)}")
        yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"
```

3. **Update `sse_coding_task_generator`** (same logging pattern):
```python
async def sse_coding_task_generator(prompt: str, task_type: str) -> AsyncGenerator[str, None]:
    global engine
    if not engine:
        logger.error("Engine not initialized for coding task")
        # ... existing error handling ...

    try:
        logger.info(f"CODING TASK: {task_type}")
        logger.log_user_message(prompt)
        # ... rest of function with same logging as above ...
```

4. **Update `lifespan` manager** (log startup/shutdown):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine

    # Startup
    logger.info("=" * 80)
    logger.info("HTTP SERVER STARTED")
    logger.info("=" * 80)

    engine = EngineClient(consent_callback=http_consent_handler)
    # ... existing initialization ...

    logger.info(f"Provider: {engine.provider_name}")
    logger.info(f"Model: {engine.model}")

    yield

    # Shutdown
    logger.info("HTTP SERVER STOPPED")
    pending_consent_requests.clear()
    engine = None
```

**Why This Minimal Approach**:
- ✅ **Low risk** - Only adding logging, not changing logic
- ✅ **VSCode benefits** - Debug logging without breaking changes
- ✅ **Consistent logs** - Same format as TUI (`server-debug.log`)
- ✅ **Foundation** - Can integrate full EventHandler in v1.13.0
- ✅ **Fast** - 1-2 hours vs 3-4 hours for full refactoring

**Future Enhancement (v1.13.0)**:
Later, we can refactor to use full `EventHandler` for complete code sharing, but that's not critical for v1.12.0.

---

## Implementation Checklist

### Files to Modify:

- [ ] `ppxai/server/http.py`:
  - [ ] Import `get_logger` from `ppxai.common.logger`
  - [ ] Create `logger = get_logger("server")`
  - [ ] Add logging to `sse_event_generator`
  - [ ] Add logging to `sse_coding_task_generator`
  - [ ] Add logging to `lifespan` manager

### Testing Strategy:

**Manual Testing** (VSCode Extension):
1. [ ] Start server with debug logging:
   ```bash
   PPXAI_DEBUG=1 uv run ppxai-server
   ```

2. [ ] Check log file created:
   ```bash
   ls -la ~/.ppxai/logs/server-debug.log
   ```

3. [ ] Open VSCode extension, send chat message

4. [ ] Verify server log shows:
   ```
   17:30:45.123 | INFO     | HTTP SERVER STARTED
   17:30:45.124 | INFO     | Provider: perplexity
   17:30:45.124 | INFO     | Model: sonar-pro
   17:31:00.456 | INFO     | API REQUEST: iteration=1, messages=0
   17:31:00.457 | INFO     | USER INPUT: explain this code
   17:31:02.789 | INFO     | ASSISTANT RESPONSE: Here's an explanation...
   ```

5. [ ] Test with tools enabled:
   ```bash
   # In VSCode extension, enable tools, send message
   # Check server log shows:
   17:32:15.111 | INFO     | TOOL CALL: read_file
   17:32:15.112 | DEBUG    |   Arguments: {'filepath': 'README.md'}
   17:32:15.234 | INFO     | TOOL RESULT: read_file
   ```

6. [ ] Verify extension still works (no regressions):
   - [ ] Chat works
   - [ ] Streaming works
   - [ ] Tools work
   - [ ] Consent dialogs work

**Automated Testing** (Update `tests/test_http_server.py`):
- [ ] Add test for server logger initialization
- [ ] Add test for logging during chat
- [ ] Verify existing tests still pass

---

## Benefits Summary

### For VSCode Extension Users:
- ✅ Can enable debug logging to diagnose issues
- ✅ See full server-side message flow
- ✅ Compare TUI vs VSCode behavior via logs
- ✅ Report bugs with complete log context

### For Development:
- ✅ Consistent logging across TUI and VSCode
- ✅ Easy to debug SSE streaming issues
- ✅ Foundation for full EventHandler integration
- ✅ Low-risk incremental refactoring

---

**Estimated Total Time for VSCode Integration**: 1-2 hours
**Priority**: HIGH (ensures both TUI and VSCode work after refactoring)
**Status**: Ready to implement after Task 3 (logger) is complete

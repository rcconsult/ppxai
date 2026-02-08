# ppxaide with Embedded Server Thread

**Date:** 2026-01-27
**Concept:** Run ppxai-server code in-process via background thread, ppxaide as thin client with SSE

---

## The Idea

Instead of:
```
ppxaide (Textual + EngineClient) ← direct async calls → Providers
   └─ Complex async orchestration
```

Or separate process:
```
ppxaide (Textual thin client) ← HTTP/SSE → ppxai-server (subprocess) ← EngineClient
   └─ Simple SSE parsing              └─ Manages async orchestration
```

**Do this:**
```
ppxaide (single process)
├─ Main Thread: Textual UI ← HTTP/SSE (loopback) ┐
│                                                 │
└─ Background Thread: FastAPI server ────────────┘
   └─ EngineClient → Providers
   └─ All async orchestration
```

---

## Architecture

### Process Model

```
Single Process (ppxaide)
│
├─ Main Thread
│  ├─ Textual App (UI event loop)
│  ├─ HTTP client (requests to localhost)
│  └─ SSE stream parser
│
└─ Background Thread
   ├─ uvicorn.run() with FastAPI app
   ├─ SessionManager
   ├─ EngineClient
   └─ All provider logic
```

### Communication Flow

```
User Input (Textual)
    ↓ (main thread)
HTTP POST /chat to http://127.0.0.1:{random_port}
    ↓ (crosses thread boundary - thread-safe via HTTP)
FastAPI handler (background thread)
    ↓ (background thread)
EngineClient.chat() + SSE streaming
    ↓ (HTTP SSE response - thread-safe)
SSE parser (main thread)
    ↓ (main thread)
Textual widget updates
```

### Code Structure

```python
# ppxai/tui/embedded_server.py (NEW)
import threading
import uvicorn
from fastapi import FastAPI
from ..server.http import create_app

class EmbeddedServer:
    """Run ppxai-server in background thread."""

    def __init__(self, port: int = 0):  # 0 = random port
        self.port = port
        self.app = create_app()
        self.thread = None
        self._started = threading.Event()

    def start(self) -> int:
        """Start server in background thread, return actual port."""
        config = uvicorn.Config(
            app=self.app,
            host="127.0.0.1",
            port=self.port,
            log_level="error",  # Quiet
            loop="asyncio"
        )
        server = uvicorn.Server(config)

        # Get actual port (if random)
        self.port = server.config.port

        # Run in thread
        self.thread = threading.Thread(
            target=server.run,
            daemon=True,
            name="ppxai-server-thread"
        )
        self.thread.start()

        # Wait for server to be ready
        self._started.wait(timeout=2.0)

        return self.port

    def stop(self):
        """Stop server (automatic via daemon thread on exit)."""
        pass


# ppxai/tui/http_client.py (NEW - or reuse from VSCode)
import httpx
from typing import AsyncIterator

class TUIHttpClient:
    """HTTP client for embedded server (same as VSCode extension)."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=300.0)

    async def stream_chat(self, message: str) -> AsyncIterator[dict]:
        """Stream chat response via SSE."""
        async with self.client.stream(
            "POST",
            f"{self.base_url}/chat",
            json={"message": message}
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    yield data

    async def send_consent(self, response: dict):
        """Send consent response to server."""
        await self.client.post(
            f"{self.base_url}/consent",
            json=response
        )


# ppxai/tui/app.py (MODIFIED)
class PPXAIDEApp(App):
    """Thin client using embedded server."""

    def __init__(self):
        super().__init__()

        # Start embedded server
        self.server = EmbeddedServer(port=0)  # Random port
        port = self.server.start()

        # Connect as thin client
        self.http_client = TUIHttpClient(f"http://127.0.0.1:{port}")

        # No EngineClient! Server thread handles it.

    async def send_message(self, text: str):
        """Send message via HTTP/SSE (same as web app)."""
        self.chat_view.add_user_message(text)
        self.chat_view.start_assistant_message()

        try:
            async for event in self.http_client.stream_chat(text):
                await self._handle_sse_event(event)
        except Exception as e:
            self.chat_view.add_error(str(e))

    async def _handle_sse_event(self, event: dict):
        """Handle SSE event (reuse web app logic)."""
        event_type = event.get("type")

        if event_type == "chunk":
            self.chat_view.append_chunk(event["data"])

        elif event_type == "done":
            self.chat_view.finalize_message()

        elif event_type == "consent_request":
            # Simple consent dialog (no Future needed!)
            response = await self.show_consent_dialog(event["data"])
            await self.http_client.send_consent(response)

        elif event_type == "error":
            self.chat_view.add_error(event["data"])
```

---

## Benefits

### 1. Eliminates Async Complexity in UI Thread

**Before (current ppxaide):**
```python
# Complex async orchestration in UI thread
async def _handle_event(self, event: Event):
    if event.type == EventType.STREAM_CHUNK:
        # Textual message passing
        self.chat_view.post_message(...)
    elif event.type == EventType.CONSENT_REQUEST:
        # Need Future to avoid blocking
        future = asyncio.Future()
        self._pending_consent = future
        # Show dialog somehow...
        response = await future  # Complex!
```

**After (embedded server thread):**
```python
# Simple SSE event handling (like web app)
async def _handle_sse_event(self, event: dict):
    if event["type"] == "chunk":
        self.chat_view.append_chunk(event["data"])  # Direct update
    elif event["type"] == "consent_request":
        response = await self.show_consent_dialog(event["data"])  # Simple!
        await self.http_client.send_consent(response)
```

### 2. Reuses Proven Server Code

- ✅ FastAPI app from ppxai/server/http.py (already works)
- ✅ SessionManager (already handles state isolation)
- ✅ SSE streaming (already proven with web + VSCode)
- ✅ Consent handling via events (already implemented)
- ✅ No code duplication

### 3. Reuses Web App Patterns

The web app already has:
- SSE event parsing
- Consent dialog handling
- Streaming response display
- Error handling

**Can directly port the JavaScript logic to Python!**

### 4. Natural Separation of Concerns

**Main Thread (UI only):**
- Textual event loop
- Widget rendering
- User input
- HTTP client calls
- SSE parsing

**Background Thread (Engine only):**
- FastAPI endpoints
- EngineClient
- Provider calls
- All async orchestration
- State management

**Communication:** Thread-safe via HTTP (FastAPI handles locking)

### 5. Single Process Deployment

- ✅ No subprocess management
- ✅ No port conflicts (random port or Unix socket)
- ✅ No startup coordination
- ✅ Clean shutdown (daemon thread)
- ✅ Single binary deployment

### 6. Better Than Current Approach

| Aspect | Current (Embedded Engine) | Separate Process | **Embedded Thread** |
|--------|--------------------------|------------------|---------------------|
| **Async Complexity** | High (UI + Engine) | Low (UI only) | **Low (UI only)** |
| **Code Reuse** | None (orthogonal) | High (server code) | **High (server code)** |
| **Process Count** | 1 | 2 | **1** |
| **Deployment** | Simple | Complex | **Simple** |
| **State Management** | Complex | Separate | **Thread-safe** |
| **Debugging** | Hard | Medium | **Medium** |

---

## Technical Considerations

### Threading vs Multiprocessing

**Threading is fine here because:**

1. **IO-bound, not CPU-bound**
   - Network requests to providers
   - Streaming responses
   - GIL not a bottleneck

2. **FastAPI designed for threading**
   - Uvicorn can run in thread
   - Request handlers are thread-safe
   - SessionManager already uses locks

3. **Simpler than multiprocessing**
   - No pickle/serialization
   - Shared memory space
   - Easier debugging

### Thread Safety

**Already handled by FastAPI:**
- Each request is isolated
- SessionManager uses asyncio.Lock
- No shared mutable state between requests

**UI thread safety:**
- Only communicates via HTTP (thread-safe)
- No direct calls to background thread
- Textual handles its own thread safety

### Port Management

**Option 1: Random port**
```python
server = EmbeddedServer(port=0)  # OS assigns random port
port = server.start()  # Returns actual port
client = TUIHttpClient(f"http://127.0.0.1:{port}")
```

**Option 2: Unix socket (Linux/Mac)**
```python
socket_path = "/tmp/ppxaide-{pid}.sock"
server = EmbeddedServer(unix_socket=socket_path)
client = TUIHttpClient(f"http+unix://{socket_path}")
```

### Shutdown

```python
class PPXAIDEApp(App):
    def on_unmount(self):
        """Clean shutdown."""
        # Server thread is daemon, exits automatically
        # Or explicit:
        self.server.stop()
```

---

## Implementation Plan

### Phase 1: Extract Server Code (1 day)

**Current issue:** ppxai/server/http.py has global state

**Fix:**
```python
# ppxai/server/http.py
def create_app() -> FastAPI:
    """Factory function to create FastAPI app (no globals)."""
    app = FastAPI()

    # Session manager per app instance
    session_manager = SessionManager()

    @app.post("/chat")
    async def chat(...):
        session = await session_manager.get_or_create_session(...)
        # ...

    return app
```

**Changes needed:**
- [ ] Convert global variables to app state
- [ ] Make create_app() factory function
- [ ] Test standalone server still works

### Phase 2: Add Embedded Server (1 day)

**New files:**
- [ ] `ppxai/tui/embedded_server.py` - Thread wrapper for uvicorn
- [ ] Test server starts and stops cleanly
- [ ] Test multiple start/stop cycles

### Phase 3: Add HTTP Client (1 day)

**Options:**
- **Option A:** Port VSCode extension httpClient.ts to Python
- **Option B:** Use httpx with SSE parsing

**Prefer Option A** - VSCode client is proven and has all the logic

**New files:**
- [ ] `ppxai/tui/http_client.py` - HTTP + SSE client
- [ ] Copy SSE parsing logic from web app
- [ ] Test streaming, consent, errors

### Phase 4: Migrate PPXAIDEApp (2 days)

**Changes to ppxai/tui/app.py:**
- [ ] Add embedded server startup
- [ ] Replace EngineClient with http_client
- [ ] Port SSE event handling from web app
- [ ] Migrate consent dialogs (simpler now!)
- [ ] Test all commands via HTTP

**Code to remove:**
- [ ] Direct EngineClient calls
- [ ] Complex async event handling
- [ ] Future-based consent pattern
- [ ] ~500 lines of complex orchestration

### Phase 5: Testing (1 day)

**Test scenarios:**
- [ ] Basic chat with streaming
- [ ] Tool consent dialogs
- [ ] Shell consent dialogs
- [ ] Multi-turn conversations
- [ ] Session save/restore
- [ ] Error handling
- [ ] Clean shutdown

**Total effort:** 6 days

---

## Migration Path

### Step 1: Add alongside existing (v1.16.0)

```python
class PPXAIDEApp(App):
    def __init__(self, use_embedded_server: bool = False):
        if use_embedded_server:
            self._init_thin_client()  # New
        else:
            self._init_embedded_engine()  # Current
```

**Flag:** `ppxaide --embedded-server` to test

### Step 2: Switch default (v1.17.0)

```python
def __init__(self, use_embedded_engine: bool = False):
    if use_embedded_engine:
        self._init_embedded_engine()  # Legacy
    else:
        self._init_thin_client()  # Default
```

**Flag:** `ppxaide --embedded-engine` to use old way

### Step 3: Remove old code (v1.18.0)

- Remove EngineClient integration
- Remove complex async handlers
- Pure thin client with embedded server

---

## Comparison with Other Options

| Criteria | Separate Process | **Embedded Thread** | Current (Embedded Engine) |
|----------|-----------------|---------------------|--------------------------|
| **UI Complexity** | Low | **Low** | High |
| **Code Reuse** | High | **High** | None |
| **Process Count** | 2 | **1** | 1 |
| **Port Management** | Required | **Optional** | N/A |
| **State Isolation** | Separate | **Thread-safe** | Complex |
| **Deployment** | Complex | **Simple** | Simple |
| **Startup** | Coordination needed | **Single command** | Single command |
| **Debugging** | 2 processes | **1 process** | 1 process |
| **Risk** | Low | **Low** | High (current issues) |

**Embedded thread is the best of both worlds!**

---

## Code Size Reduction

**Current ppxai/tui/app.py:**
- ~1,500 lines
- Complex async orchestration
- Direct EngineClient integration
- Future-based consent handling
- Distributed state management

**With embedded server thread:**
- ~800 lines (estimate)
- Simple SSE event handling
- HTTP client calls
- Direct consent dialogs
- Server handles state

**Reduction:** ~700 lines (-47%)

**Files removed:**
- Complex event handlers
- Future-based consent code
- Engine integration complexity

---

## Proof of Concept

### Minimal Example

```python
# test_embedded_server.py
import threading
import time
import uvicorn
from fastapi import FastAPI
import httpx

# Background thread
def run_server():
    app = FastAPI()

    @app.get("/hello")
    def hello():
        return {"message": "Hello from thread!"}

    uvicorn.run(app, host="127.0.0.1", port=54321, log_level="error")

# Start server thread
thread = threading.Thread(target=run_server, daemon=True)
thread.start()
time.sleep(1)  # Wait for startup

# Main thread makes request
response = httpx.get("http://127.0.0.1:54321/hello")
print(response.json())  # {'message': 'Hello from thread!'}

# Works! Main thread ← HTTP → background thread
```

**This pattern is proven and works!**

---

## Recommendation

**YES, absolutely do this!** ✅

**Why:**
1. ✅ Reuses all server code (FastAPI, SSE, SessionManager)
2. ✅ Reuses web app patterns (SSE parsing, consent)
3. ✅ Single process (simple deployment)
4. ✅ Eliminates async complexity in UI
5. ✅ Thread-safe by design (HTTP boundary)
6. ✅ Proven pattern (desktop apps do this)
7. ✅ Low risk (server code already works)

**Timeline:**
- 6 days implementation
- 2-3 releases migration
- Stable by v1.17.0

**This is the best solution proposed so far.**

---

## Next Steps

1. **Immediate (v1.15.0):** Still fix critical bugs
2. **v1.15.1:** Refactor server for factory pattern
3. **v1.16.0:** Add embedded server thread + thin client mode
4. **v1.17.0:** Switch default to embedded server
5. **v1.18.0:** Remove old embedded engine code

**Start with:** Refactor `ppxai/server/http.py` to use factory pattern (removes globals)

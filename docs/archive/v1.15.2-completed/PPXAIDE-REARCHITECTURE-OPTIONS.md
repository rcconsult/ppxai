# ppxaide Re-Architecture Options

**Date:** 2026-01-27
**Context:** Struggling with asyncio + Textual event processing complexity
**Goal:** Evaluate simpler architectures by aligning with web/VSCode patterns

---

## Current Architecture Comparison

### 1. ppxai (Rich TUI) - **Simple, Works**

**Architecture:**
```
prompt_toolkit → CommandHandler → EngineClient → Providers
      ↓                                  ↓
   Readline UI                    async chat() → sync loop
```

**Characteristics:**
- **Runtime:** Synchronous loop with async engine calls
- **UI Library:** prompt_toolkit (readline-style)
- **Event Processing:** Simple linear flow - wait for input → call engine → display response
- **State Management:** Simple instance variables
- **LOC:** ~800 lines (ppxai/rich/main.py)

**Pros:**
- ✅ Simple, predictable control flow
- ✅ Easy to debug (linear execution)
- ✅ No complex event handling
- ✅ Works reliably

**Cons:**
- ❌ Basic UI (no split panes, limited styling)
- ❌ No file viewer/editor integration
- ❌ Limited theming

---

### 2. ppxaide (Textual TUI) - **Complex, Struggling**

**Architecture:**
```
Textual App → Widgets → EngineClient
    ↓           ↓            ↓
 Event Loop  Messages    async events
    ↓           ↓            ↓
Async handlers → State updates → Re-render
```

**Characteristics:**
- **Runtime:** Fully async event-driven (Textual framework)
- **UI Library:** Textual (React-like, async)
- **Event Processing:** Complex async message passing between widgets
- **State Management:** Distributed across widgets + app + engine
- **LOC:** ~1,500 lines (ppxai/tui/app.py) + 14 widget files

**Pros:**
- ✅ Rich UI (split panes, syntax highlighting, modals)
- ✅ Modern theming (17+ themes)
- ✅ File viewer/editor integration
- ✅ Keyboard-driven UX

**Cons:**
- ❌ **MAJOR:** Complex async event orchestration
- ❌ **MAJOR:** Race conditions between Textual events and engine events
- ❌ **MAJOR:** Consent dialog blocking issues
- ❌ **MAJOR:** Streaming response display issues
- ❌ Hard to debug (non-deterministic event ordering)
- ❌ State synchronization nightmares
- ❌ Can't reuse Rich TUI patterns (fundamentally different)

**Current Issues:**
- AI responses not displayed (STREAM_END handling)
- Tool consent broken (callback timing)
- Tab autocomplete disabled (needs refactor)
- Asyncio debugging complexity

---

### 3. Web App - **Thin Client, Simple**

**Architecture:**
```
Browser (HTML/CSS/JS) ← HTTP/SSE → ppxai-server (FastAPI)
    ↓                                      ↓
DOM updates ← Events                  EngineClient
    ↓                                      ↓
User actions → /chat                   Providers
```

**Characteristics:**
- **Runtime:** Single-threaded JavaScript event loop
- **UI Library:** DOM + CSS (vanilla JS)
- **Event Processing:** SSE stream → simple event handlers
- **State Management:** Class instance variables
- **LOC:** ~2,800 lines (ppxai/web/app.js)
- **Server Dependency:** Required (ppxai-server)

**Pros:**
- ✅ Simple event model (browser handles it)
- ✅ No asyncio complexity
- ✅ Server handles all engine logic
- ✅ Easy consent dialogs (native modals)
- ✅ Streaming just works (SSE)
- ✅ Rich UI capabilities

**Cons:**
- ❌ Requires running server
- ❌ Not a true terminal app
- ❌ Browser dependency

---

### 4. VSCode Extension - **Thin Client, Event Bus**

**Architecture:**
```
VSCode WebView ← EventBus → httpClient ← HTTP/SSE → ppxai-server
      ↓            ↓              ↓                        ↓
  UI handlers  Pub/Sub      Stream parser            EngineClient
```

**Characteristics:**
- **Runtime:** Node.js (TypeScript) + WebView (HTML)
- **UI Library:** VSCode WebView API
- **Event Processing:** Event bus (pub/sub pattern) for decoupling
- **State Management:** Separated into isolated handlers
- **LOC:** ~1,200 lines (chatPanel.ts) + event bus + handlers
- **Server Dependency:** Required (ppxai-server)

**Pros:**
- ✅ Clean pub/sub architecture
- ✅ Isolated handlers (testable)
- ✅ Server handles engine complexity
- ✅ Consent via native VSCode dialogs
- ✅ Streaming via SSE (simple)
- ✅ No asyncio complexity

**Cons:**
- ❌ Requires running server
- ❌ VSCode-specific APIs
- ❌ Not standalone

---

### 5. ppxai-server - **Shared Backend**

**Architecture:**
```
FastAPI endpoints
    ↓
SessionManager (per-client state isolation)
    ↓
EngineClient (one per session)
    ↓
Providers (OpenAI, Perplexity, etc.)
```

**Characteristics:**
- **Runtime:** Async FastAPI (uvicorn)
- **State Management:** Session-based isolation
- **Event Processing:** SSE streaming to clients
- **LOC:** ~1,500 lines (ppxai/server/)

**Features:**
- ✅ Handles all engine complexity
- ✅ Session isolation for multiple clients
- ✅ SSE streaming for responses
- ✅ REST API for commands
- ✅ Consent via SSE events to clients
- ✅ Already used by web + VSCode

---

## Problem Analysis: Why ppxaide is Hard

### Orthogonal Event Models

**ppxai (Rich) - Linear:**
```
while True:
    user_input = await prompt()  # Blocks until input
    response = await engine.chat(user_input)  # Blocks until done
    print(response)  # Display when ready
```

**ppxaide (Textual) - Event-Driven:**
```
# Events fire asynchronously, order not guaranteed
on_input_submitted() → sends to engine
    engine fires events → _handle_event()
        updates widgets → triggers re-render
            Textual schedules message → eventually updates UI
                meanwhile user can press keys → new events
```

### Race Conditions

1. **Consent Dialog During Streaming:**
   - Engine fires consent event
   - Need to show modal → blocks Textual event loop
   - Meanwhile engine is still streaming
   - Future-based solution complex

2. **Response Display:**
   - Non-streaming providers send full response in STREAM_END
   - But ppxaide expects chunks first
   - Result: response never displayed

3. **State Synchronization:**
   - Engine has state (messages, tokens, cost)
   - StatusBar has state (badges)
   - ChatView has state (displayed messages)
   - Must keep all in sync across async boundaries

### Code Reuse Failure

Rich TUI patterns don't translate:
- Rich uses sync loop → Textual requires async
- Rich blocks on input → Textual uses messages
- Rich displays immediately → Textual schedules updates
- Rich has simple state → Textual has distributed state

---

## Re-Architecture Options

### Option 1: Make ppxaide Thin Client (Like Web App)

**Architecture:**
```
Textual TUI ← HTTP/SSE → ppxai-server
     ↓                        ↓
 UI widgets              EngineClient
     ↓                        ↓
SSE parser              All business logic
```

**Changes:**
- Remove direct EngineClient integration
- Add HTTP client (like VSCode extension)
- Add SSE stream parser
- Keep Textual for UI only
- All commands via server API

**Implementation:**
```python
# ppxaide becomes:
class PPXAIDEApp(App):
    def __init__(self):
        self.http_client = HttpClient("http://127.0.0.1:54320")
        # No EngineClient!

    async def send_message(self, text: str):
        # Simple SSE streaming
        async for event in self.http_client.stream_chat(text):
            if event.type == "chunk":
                self.chat_view.append_chunk(event.data)
            elif event.type == "consent_request":
                response = await self.show_consent_dialog(event.data)
                await self.http_client.send_consent(response)
```

**Pros:**
- ✅ **MAJOR:** Eliminates asyncio complexity in TUI
- ✅ **MAJOR:** Server handles all engine orchestration
- ✅ Consent via simple dialog (no Future needed)
- ✅ Streaming via SSE (proven pattern)
- ✅ Can reuse web app SSE parsing logic
- ✅ Easier to debug (TUI only handles display)
- ✅ Code reuse with web/VSCode patterns

**Cons:**
- ❌ Requires running server (dependency)
- ❌ Extra process (complexity for standalone use)
- ❌ Network overhead (localhost HTTP)
- ❌ Can't use ppxaide without server

**Effort:** 3-4 days
- Day 1: Add HTTP client + SSE parser
- Day 2: Migrate chat to SSE streaming
- Day 3: Migrate commands to REST API
- Day 4: Testing + consent dialogs

---

### Option 2: Adopt Event Bus Pattern (Like VSCode)

**Architecture:**
```
Textual TUI
     ↓
EventBus (pub/sub) ← handlers → EngineClient
     ↓
Isolated handlers:
  - StreamHandler (events → UI updates)
  - ConsentHandler (consent → dialogs)
  - AgentHandler (agent state)
```

**Changes:**
- Add EventBus class (from VSCode)
- Separate handlers for concerns
- Engine emits to bus, handlers subscribe
- Handlers update UI via bus

**Implementation:**
```python
# Add event bus
class TUIEventBus:
    def on(self, event: str, handler: Callable): ...
    def emit(self, event: str, data: Any): ...

# Separate handlers
class StreamHandler:
    def __init__(self, bus, chat_view):
        bus.on("stream:chunk", self.on_chunk)
        bus.on("stream:done", self.on_done)

    def on_chunk(self, content: str):
        self.chat_view.append_chunk(content)

class ConsentHandler:
    def __init__(self, bus, app):
        bus.on("consent:request", self.on_request)

    async def on_request(self, data):
        response = await self.app.show_consent_dialog(data)
        self.bus.emit("consent:response", response)
```

**Pros:**
- ✅ Decouples handlers (easier to test)
- ✅ Clearer separation of concerns
- ✅ Proven pattern (VSCode works well)
- ✅ No server dependency
- ✅ Keeps EngineClient direct access

**Cons:**
- ❌ Still has asyncio complexity
- ❌ Event bus adds layer of indirection
- ❌ Doesn't solve core async orchestration
- ❌ Still need to sync Textual + Engine events

**Effort:** 2-3 days
- Day 1: Implement EventBus
- Day 2: Extract handlers
- Day 3: Migrate event handling

---

### Option 3: Simplify ppxaide to Rich-Like Model

**Architecture:**
```
Textual TUI (simplified)
     ↓
Sync-style loop with async calls
     ↓
EngineClient (same as Rich TUI)
```

**Changes:**
- Remove complex async event orchestration
- Use simpler message passing
- Block on engine responses (like Rich)
- Reduce widget complexity

**Implementation:**
```python
# Simplified chat loop
async def handle_message(self, text: str):
    self.chat_view.add_user_message(text)
    self.chat_view.start_assistant_message()

    # Block until response complete (like Rich TUI)
    async for event in self.engine.chat(text):
        if event.type == EventType.STREAM_CHUNK:
            self.chat_view.append_chunk(event.data)
        elif event.type == EventType.CONSENT_REQUEST:
            # Simple blocking dialog
            response = await self.show_consent_dialog(event.data)
            await self.engine.send_consent_response(response)

    self.chat_view.finalize_message()
```

**Pros:**
- ✅ Simpler control flow
- ✅ Easier to debug
- ✅ No server dependency
- ✅ Keeps rich UI features

**Cons:**
- ❌ Still has some async complexity
- ❌ Textual not designed for blocking operations
- ❌ May conflict with Textual's event model
- ❌ Doesn't fully solve the problem

**Effort:** 2 days
- Day 1: Simplify event handling
- Day 2: Test + fix issues

---

### Option 4: Hybrid - Thin TUI + Optional Embedded Server

**Architecture:**
```
Textual TUI
     ↓
Mode switch:
  - Standalone: Embedded engine (current)
  - Client: HTTP/SSE to external server
```

**Changes:**
- Add HTTP client option
- Keep EngineClient for standalone
- Runtime mode switch via config/flag
- Best of both worlds

**Implementation:**
```python
class PPXAIDEApp(App):
    def __init__(self, mode: str = "standalone"):
        if mode == "client":
            self.backend = HttpBackend(server_url)
        else:
            self.backend = EngineBackend(EngineClient())

    async def send_message(self, text: str):
        # Abstract backend handles implementation
        await self.backend.send_message(text)
```

**Pros:**
- ✅ Flexibility - works standalone or as client
- ✅ Can simplify when using server
- ✅ Keeps existing functionality
- ✅ Migration path (start with server mode)

**Cons:**
- ❌ Complex - maintaining two code paths
- ❌ More code to maintain
- ❌ Standalone still has async issues

**Effort:** 4-5 days
- Day 1-2: Abstract backend interface
- Day 3: HTTP backend implementation
- Day 4-5: Testing both modes

---

## Recommendation

### Short-Term (v1.15.0) - Fix Critical Bugs

**Do NOT re-architect now.** Fix the immediate issues:

1. **Fix STREAM_END handling** - Extract content when no chunks
2. **Fix consent callbacks** - Debug why they're not firing
3. **Add debug logging** - Trace event flow
4. **Remove unsupported languages** - Fix crash

**Effort:** 2-3 days
**Risk:** Low
**Benefit:** ppxaide becomes usable

---

### Long-Term (v1.16.0+) - **Option 1: Thin Client**

**Recommended approach:**

1. **Phase 1:** Make ppxai-server run automatically with ppxaide
   - ppxaide starts server as subprocess if not running
   - Transparent to user
   - Effort: 1 day

2. **Phase 2:** Add HTTP/SSE client mode
   - Keep EngineClient for now
   - Add --client-mode flag
   - Test server mode thoroughly
   - Effort: 3-4 days

3. **Phase 3:** Switch default to client mode
   - Once proven stable
   - Keep standalone as fallback
   - Effort: 1 day

4. **Phase 4:** Remove embedded EngineClient
   - After 1-2 releases of stability
   - Full thin client
   - Effort: 2 days

**Total effort:** 7-8 days spread across 2-3 releases

**Why this is best:**
- ✅ Proven pattern (web + VSCode work great)
- ✅ Eliminates async complexity
- ✅ Better code reuse
- ✅ Easier to maintain
- ✅ Can make server auto-start (transparent)
- ✅ Gradual migration path

---

## Decision Matrix

| Criteria | Option 1: Thin | Option 2: EventBus | Option 3: Simplify | Option 4: Hybrid |
|----------|---------------|-------------------|-------------------|-----------------|
| **Complexity Reduction** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ |
| **Code Reuse** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| **Maintainability** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ |
| **Standalone Use** | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Implementation Effort** | 3-4 days | 2-3 days | 2 days | 4-5 days |
| **Risk** | Medium | Low | Medium | High |
| **Solves Core Issue** | ✅ Yes | ⚠️ Partial | ⚠️ Partial | ✅ Yes (client mode) |

---

## Implementation Plan (Recommended)

### Phase 1: Fix v1.15.0 Bugs (NOW)
- [ ] Fix STREAM_END content extraction
- [ ] Debug consent callback invocation
- [ ] Fix language cycle crash
- [ ] Add comprehensive debug logging
- **Timeline:** 2-3 days
- **Release:** v1.15.0

### Phase 2: Auto-Start Server (v1.15.1)
- [ ] ppxaide checks if server running
- [ ] Auto-starts ppxai-server if needed
- [ ] Falls back to embedded engine if start fails
- **Timeline:** 1 day
- **Release:** v1.15.1

### Phase 3: Add Client Mode (v1.16.0)
- [ ] Implement HTTP client + SSE parser
- [ ] Add --client-mode flag
- [ ] Keep embedded engine as default
- [ ] Thorough testing of both modes
- **Timeline:** 3-4 days
- **Release:** v1.16.0

### Phase 4: Switch Default (v1.17.0)
- [ ] Make client mode default
- [ ] Keep embedded as --standalone flag
- [ ] Monitor for issues
- **Timeline:** 1 day
- **Release:** v1.17.0

### Phase 5: Full Thin Client (v1.18.0)
- [ ] Remove embedded EngineClient
- [ ] ppxaide is pure UI + HTTP client
- [ ] Document server requirement
- **Timeline:** 2 days
- **Release:** v1.18.0

---

## Conclusion

The struggle with ppxaide stems from **fundamental architectural mismatch:**
- **Rich TUI** uses simple sync loop → Works great
- **Textual TUI** requires async event orchestration → Complex and brittle
- **Web/VSCode** delegate to server → Simple and stable

**Recommendation:** Evolve ppxaide toward thin client model (Option 1) over 3-4 releases, starting with auto-start server in v1.15.1. This aligns with proven web/VSCode patterns and eliminates the async complexity that's causing current issues.

**Immediate action:** Focus on fixing v1.15.0 bugs to make ppxaide usable, then plan migration to thin client architecture.

# ppxaide Event Bus Options: In-Process Message Patterns

**Date:** 2026-01-27
**Goal:** Simplify ppxaide async orchestration using NATS-like pub/sub patterns in-process
**Context:** Decouple EngineClient from Textual UI using event bus

---

## Problem

Current ppxaide has tight coupling between EngineClient (async) and Textual UI (async event loop):

```python
# Current - Tightly coupled
async def _handle_event(self, event: Event):
    if event.type == EventType.STREAM_CHUNK:
        # Direct widget manipulation
        self.chat_view.post_message(ChunkMessage(event.data))
    elif event.type == EventType.CONSENT_REQUEST:
        # Complex Future-based coordination
        future = asyncio.Future()
        self._pending_consent = future
        # ... show dialog somehow ...
        response = await future
```

**Issues:**
- Direct coupling (engine → UI widgets)
- Complex async coordination (Futures, event loop interaction)
- Hard to test (need full Textual app)
- Race conditions (multiple async sources)

---

## Solution: In-Process Event Bus

Use NATS-like pub/sub pattern internally (same as VSCode extension):

```python
# With event bus - Decoupled
class PPXAIDEApp(App):
    def __init__(self):
        self.bus = EventBus()

        # UI handlers subscribe
        self.bus.on("engine:chunk", self._on_chunk)
        self.bus.on("engine:consent", self._on_consent)

        # Engine publishes
        self.engine_client.set_event_handler(
            lambda event: self.bus.emit(f"engine:{event.type}", event.data)
        )

    async def _on_chunk(self, data: str):
        """Simple handler - no Future complexity."""
        self.chat_view.append_chunk(data)

    async def _on_consent(self, data: dict):
        """Simple handler - direct dialog."""
        response = await self.show_consent_dialog(data)
        self.bus.emit("consent:response", response)
```

**Benefits:**
- ✅ Decoupled (engine doesn't know about widgets)
- ✅ Simple handlers (no Future coordination)
- ✅ Testable (mock event bus)
- ✅ Same pattern as NATS (easy migration later)

---

## Option 1: Blinker (Recommended for ppxaide) ⭐

**GitHub:** https://github.com/pallets-eco/blinker
**PyPI:** `pip install blinker`
**Maintained by:** Pallets (Flask, Werkzeug maintainers)

### Why Blinker?

- ✅ **Zero dependencies** (pure Python)
- ✅ **Fast** (C extension available)
- ✅ **Async support** (works with asyncio)
- ✅ **Type hints** (good IDE support)
- ✅ **Thread-safe** (can use with background threads)
- ✅ **Well-tested** (used by Flask, Django extensions)
- ✅ **Small** (~500 lines of code)

### Example Usage

```python
from blinker import Signal

# ppxai/tui/event_bus.py
class EventBus:
    """NATS-like event bus for ppxaide (using blinker)."""

    def __init__(self):
        self._signals = {}

    def signal(self, name: str) -> Signal:
        """Get or create signal by name."""
        if name not in self._signals:
            self._signals[name] = Signal(name)
        return self._signals[name]

    def emit(self, name: str, **kwargs):
        """Emit event (sync or async)."""
        self.signal(name).send(sender=self, **kwargs)

    def on(self, name: str, handler):
        """Subscribe to event."""
        self.signal(name).connect(handler)
        return lambda: self.signal(name).disconnect(handler)


# ppxai/tui/app.py
class PPXAIDEApp(App):
    def __init__(self):
        super().__init__()
        self.bus = EventBus()

        # Subscribe to engine events
        self.bus.on("engine:chunk", self._on_chunk)
        self.bus.on("engine:done", self._on_done)
        self.bus.on("engine:consent_request", self._on_consent_request)
        self.bus.on("engine:tool_call", self._on_tool_call)
        self.bus.on("engine:error", self._on_error)

        # Initialize engine with event emitter
        self._engine_client = EngineClient()
        self._engine_client.set_event_handler(self._emit_engine_event)

    def _emit_engine_event(self, event: Event):
        """Bridge engine events to event bus."""
        self.bus.emit(
            f"engine:{event.type.value}",
            data=event.data,
            event=event
        )

    async def _on_chunk(self, sender, data: str, **kwargs):
        """Handle stream chunk (simple!)."""
        self.chat_view.append_chunk(data)

    async def _on_consent_request(self, sender, data: dict, **kwargs):
        """Handle consent request (no Future needed!)."""
        response = await self.show_consent_dialog(data)
        # Emit consent response back
        self.bus.emit("consent:response", response=response)

    async def _on_tool_call(self, sender, data: dict, **kwargs):
        """Handle tool call notification."""
        self.chat_view.add_tool_call(data["tool"], data["arguments"])

    async def _on_error(self, sender, data: str, **kwargs):
        """Handle error."""
        self.chat_view.add_error(data)


# Engine side - Subscribe to consent responses
class EngineHandler:
    def __init__(self, engine_client: EngineClient, bus: EventBus):
        self.engine = engine_client
        self.bus = bus

        # Subscribe to consent responses
        self.bus.on("consent:response", self._on_consent_response)

    async def _on_consent_response(self, sender, response: dict, **kwargs):
        """Handle consent response from UI."""
        await self.engine.send_consent_response(response)
```

**Code reduction:**
- Before: ~150 lines of Future-based consent handling
- After: ~30 lines of event handlers

---

## Option 2: PyPubSub

**GitHub:** https://github.com/schollii/pypubsub
**PyPI:** `pip install PyPubSub`

### Why PyPubSub?

- ✅ **Hierarchical topics** (like NATS subjects)
- ✅ **Type-safe** (topic validation)
- ✅ **Message filtering** (conditional subscriptions)
- ⚠️ More complex API than blinker
- ⚠️ Primarily sync (async requires wrapper)

### Example Usage

```python
from pubsub import pub

# ppxai/tui/app.py
class PPXAIDEApp(App):
    def on_mount(self):
        # Subscribe with hierarchical topics (like NATS!)
        pub.subscribe(self._on_chunk, "engine.stream.chunk")
        pub.subscribe(self._on_consent, "engine.consent.request")
        pub.subscribe(self._on_tool, "engine.tool.call")

    def _on_chunk(self, data: str):
        """Handler receives only data argument."""
        self.chat_view.append_chunk(data)

    def _on_consent(self, filepath: str, mode: str):
        """Type-safe handler with named arguments."""
        response = await self.show_consent_dialog(filepath, mode)
        pub.sendMessage("consent.response", filepath=filepath, approved=response)


# Engine side
class EngineEventBridge:
    def handle_event(self, event: Event):
        if event.type == EventType.STREAM_CHUNK:
            pub.sendMessage("engine.stream.chunk", data=event.data)
        elif event.type == EventType.CONSENT_REQUEST:
            pub.sendMessage(
                "engine.consent.request",
                filepath=event.data["filepath"],
                mode=event.data["mode"]
            )
```

**Pros:**
- ✅ Hierarchical topics (closer to NATS)
- ✅ Type-safe message definitions

**Cons:**
- ⚠️ Primarily sync (need async wrapper)
- ⚠️ More complex API

---

## Option 3: asyncio Queues (Built-in)

**No dependencies** - Use Python's built-in asyncio.Queue

### Example Usage

```python
import asyncio
from typing import Dict, Callable
from dataclasses import dataclass

@dataclass
class BusMessage:
    topic: str
    data: any

class AsyncEventBus:
    """Simple async event bus using queues."""

    def __init__(self):
        self._queue = asyncio.Queue()
        self._handlers: Dict[str, list[Callable]] = {}
        self._task = None

    def start(self):
        """Start event loop."""
        self._task = asyncio.create_task(self._process_events())

    async def stop(self):
        """Stop event loop."""
        await self._queue.put(None)  # Sentinel
        await self._task

    def on(self, topic: str, handler: Callable):
        """Subscribe to topic."""
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)

    def emit(self, topic: str, data: any):
        """Emit event (non-blocking)."""
        self._queue.put_nowait(BusMessage(topic, data))

    async def _process_events(self):
        """Event loop - process messages."""
        while True:
            msg = await self._queue.get()
            if msg is None:  # Sentinel
                break

            # Call all handlers for topic
            if msg.topic in self._handlers:
                for handler in self._handlers[msg.topic]:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(msg.data)
                        else:
                            handler(msg.data)
                    except Exception as e:
                        logger.error(f"Handler error: {e}")


# Usage
class PPXAIDEApp(App):
    def on_mount(self):
        self.bus = AsyncEventBus()
        self.bus.start()

        # Subscribe
        self.bus.on("engine:chunk", self._on_chunk)
        self.bus.on("engine:consent", self._on_consent)

        # Engine emits
        self.engine.set_event_handler(
            lambda event: self.bus.emit(f"engine:{event.type}", event.data)
        )

    async def on_unmount(self):
        await self.bus.stop()
```

**Pros:**
- ✅ No dependencies (built-in)
- ✅ Full async support
- ✅ Simple to understand

**Cons:**
- ⚠️ More boilerplate than blinker
- ⚠️ Need to manage task lifecycle

---

## Option 4: Custom EventBus (Like VSCode Extension)

**Port the TypeScript EventBus from VSCode extension to Python.**

### Implementation

```python
# ppxai/tui/event_bus.py
from typing import Callable, Dict, Set, Any, TypeVar, Generic
from dataclasses import dataclass
import asyncio
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')

class EventBus:
    """
    Type-safe event bus for decoupled handler communication.

    Port of VSCode extension's EventBus pattern to Python.

    Features:
    - Type-safe event names and handler signatures
    - Synchronous event delivery (predictable ordering)
    - Error isolation (one handler crash doesn't break others)
    - Automatic unsubscribe via returned function

    Usage:
        bus = EventBus()

        # Subscribe
        unsubscribe = bus.on('stream:chunk', lambda data: print(data))

        # Emit
        bus.emit('stream:chunk', 'Hello')

        # Unsubscribe
        unsubscribe()
    """

    def __init__(self):
        self._listeners: Dict[str, Set[Callable]] = {}

    def on(self, event: str, handler: Callable) -> Callable:
        """
        Subscribe to an event.

        Args:
            event: Event name
            handler: Handler function (sync or async)

        Returns:
            Unsubscribe function
        """
        if event not in self._listeners:
            self._listeners[event] = set()

        self._listeners[event].add(handler)

        # Return unsubscribe function
        def unsubscribe():
            self.off(event, handler)

        return unsubscribe

    def off(self, event: str, handler: Callable):
        """Unsubscribe from event."""
        if event in self._listeners:
            self._listeners[event].discard(handler)

    def emit(self, event: str, *args, **kwargs):
        """
        Emit event to all subscribers.

        Handlers are called synchronously in order of subscription.
        Errors in handlers are logged but don't stop other handlers.

        Args:
            event: Event name
            *args: Positional arguments for handlers
            **kwargs: Keyword arguments for handlers
        """
        if event not in self._listeners:
            return

        for handler in list(self._listeners[event]):  # Copy to allow unsubscribe during emit
            try:
                if asyncio.iscoroutinefunction(handler):
                    # Schedule async handler
                    asyncio.create_task(handler(*args, **kwargs))
                else:
                    # Call sync handler immediately
                    handler(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in event handler for '{event}': {e}", exc_info=True)

    def clear(self, event: str = None):
        """Clear all handlers for event, or all events if event is None."""
        if event:
            self._listeners.pop(event, None)
        else:
            self._listeners.clear()


# Type-safe event definitions (like VSCode)
@dataclass
class StreamChunkEvent:
    content: str

@dataclass
class ConsentRequestEvent:
    filepath: str
    mode: str
    content: str

@dataclass
class ToolCallEvent:
    tool: str
    arguments: dict
    call_id: str

# Usage with type hints
class PPXAIDEApp(App):
    def on_mount(self):
        self.bus = EventBus()

        # Type-safe subscriptions
        self.bus.on('stream:chunk', self._on_chunk)
        self.bus.on('consent:request', self._on_consent)
        self.bus.on('tool:call', self._on_tool_call)

    async def _on_chunk(self, event: StreamChunkEvent):
        """Type-safe handler."""
        self.chat_view.append_chunk(event.content)

    async def _on_consent(self, event: ConsentRequestEvent):
        """Type-safe consent handler."""
        response = await self.show_consent_dialog(
            event.filepath,
            event.mode,
            event.content
        )
        self.bus.emit('consent:response', approved=response)
```

**Pros:**
- ✅ No dependencies
- ✅ Full async support
- ✅ Same pattern as VSCode (proven)
- ✅ Type-safe with dataclasses
- ✅ Complete control over implementation

**Cons:**
- ⚠️ Need to maintain custom code
- ⚠️ ~150 lines of implementation

---

## Comparison Matrix

| Feature | Blinker | PyPubSub | asyncio Queues | Custom EventBus |
|---------|---------|----------|----------------|-----------------|
| **Dependencies** | 1 (blinker) | 1 (PyPubSub) | 0 (built-in) | 0 (custom) |
| **Async Support** | ✅ Good | ⚠️ Requires wrapper | ✅ Native | ✅ Native |
| **Type Safety** | ✅ With hints | ✅ Built-in | ⚠️ Manual | ✅ With dataclasses |
| **Hierarchical Topics** | ⚠️ Manual | ✅ Built-in | ⚠️ Manual | ⚠️ Manual |
| **Learning Curve** | Low | Medium | Low | Low |
| **Code Size** | Minimal | Minimal | Medium | Medium |
| **Thread Safety** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **Maintenance** | Community | Community | Python core | You |
| **Migration to NATS** | Easy | Easy | Easy | Easy |

---

## Recommendation for ppxaide: Blinker ⭐

**Why Blinker is best for ppxaide:**

1. **Minimal dependencies** (1 small package, pure Python)
2. **Works perfectly with asyncio** (no wrapper needed)
3. **Simple API** (signal, connect, send)
4. **Well-maintained** (Pallets ecosystem)
5. **Fast** (C extension available)
6. **Type-safe** (works with type hints)
7. **Thread-safe** (ready for embedded server thread)

**Migration path:**
```
v1.16.0: Add blinker + EventBus wrapper
v1.17.0: Migrate event handling to bus
v1.18.0: Ready for embedded server thread (events cross thread boundary)
v1.19.0: Migrate to NATS (same pub/sub pattern)
```

---

## Implementation Plan for ppxaide

### Phase 1: Add Blinker EventBus (2 days)

**Files to create:**

```python
# ppxai/tui/event_bus.py (NEW)
"""Event bus for decoupled ppxaide components."""

from blinker import Signal
from typing import Callable, Dict
import asyncio
import logging

logger = logging.getLogger(__name__)


class EventBus:
    """
    NATS-like event bus for ppxaide using blinker.

    Provides pub/sub pattern to decouple EngineClient from UI.
    """

    def __init__(self):
        self._signals: Dict[str, Signal] = {}

    def signal(self, name: str) -> Signal:
        """Get or create signal."""
        if name not in self._signals:
            self._signals[name] = Signal(name)
        return self._signals[name]

    def on(self, event: str, handler: Callable) -> Callable:
        """Subscribe to event."""
        signal = self.signal(event)
        signal.connect(handler, weak=False)
        return lambda: signal.disconnect(handler)

    def emit(self, event: str, **kwargs):
        """Emit event (async handlers supported)."""
        signal = self.signal(event)

        # Get all handlers
        receivers = signal.receivers_for(None)

        for receiver in receivers:
            try:
                if asyncio.iscoroutinefunction(receiver):
                    # Schedule async handler
                    asyncio.create_task(receiver(sender=self, **kwargs))
                else:
                    # Call sync handler
                    receiver(sender=self, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler for '{event}': {e}", exc_info=True)

    def clear(self):
        """Clear all subscriptions."""
        self._signals.clear()


# Event definitions (type-safe)
class Events:
    """Event name constants."""

    # Engine events
    ENGINE_CHUNK = "engine:chunk"
    ENGINE_DONE = "engine:done"
    ENGINE_ERROR = "engine:error"
    ENGINE_CONSENT_REQUEST = "engine:consent_request"
    ENGINE_TOOL_CALL = "engine:tool_call"
    ENGINE_TOOL_RESULT = "engine:tool_result"
    ENGINE_CONTEXT_INJECTED = "engine:context_injected"

    # UI events
    CONSENT_RESPONSE = "consent:response"
    UI_CLEAR = "ui:clear"
    UI_STATUS_UPDATE = "ui:status_update"
```

**Files to modify:**

```python
# ppxai/tui/app.py (MODIFY)
from .event_bus import EventBus, Events

class PPXAIDEApp(App):
    def __init__(self):
        super().__init__()

        # Add event bus
        self.bus = EventBus()

        # Subscribe to engine events
        self.bus.on(Events.ENGINE_CHUNK, self._on_stream_chunk)
        self.bus.on(Events.ENGINE_DONE, self._on_stream_done)
        self.bus.on(Events.ENGINE_ERROR, self._on_stream_error)
        self.bus.on(Events.ENGINE_CONSENT_REQUEST, self._on_consent_request)
        self.bus.on(Events.ENGINE_TOOL_CALL, self._on_tool_call)

        # Initialize engine
        self._engine_client = EngineClient()
        self._engine_client.set_event_handler(self._emit_engine_event)

    def _emit_engine_event(self, event: Event):
        """Bridge engine events to event bus."""
        event_name = {
            EventType.STREAM_CHUNK: Events.ENGINE_CHUNK,
            EventType.STREAM_END: Events.ENGINE_DONE,
            EventType.ERROR: Events.ENGINE_ERROR,
            EventType.CONSENT_REQUEST: Events.ENGINE_CONSENT_REQUEST,
            EventType.TOOL_CALL: Events.ENGINE_TOOL_CALL,
        }.get(event.type)

        if event_name:
            self.bus.emit(event_name, data=event.data, event=event)

    # Simple event handlers (no Future complexity!)

    async def _on_stream_chunk(self, sender, data: str, **kwargs):
        """Handle stream chunk."""
        self.chat_view.append_chunk(data)

    async def _on_stream_done(self, sender, data: dict, **kwargs):
        """Handle stream completion."""
        self.chat_view.finalize_message()
        # Extract final content if no chunks accumulated
        if hasattr(data, 'get') and 'content' in data:
            self.chat_view.set_content(data['content'])

    async def _on_stream_error(self, sender, data: str, **kwargs):
        """Handle error."""
        self.chat_view.add_error(data)

    async def _on_consent_request(self, sender, data: dict, event: Event, **kwargs):
        """Handle consent request (simplified!)."""
        # Show consent dialog
        response = await self.show_consent_dialog(data)

        # Emit response back
        self.bus.emit(Events.CONSENT_RESPONSE, response=response)

    async def _on_tool_call(self, sender, data: dict, **kwargs):
        """Handle tool call notification."""
        self.chat_view.add_tool_call(
            tool=data.get("tool"),
            arguments=data.get("arguments")
        )
```

**Add dependency:**

```toml
# pyproject.toml
[project.optional-dependencies]
tui = [
    "textual>=0.47.0",
    "textual-image>=0.8.0",
    "blinker>=1.7.0",  # NEW
]
```

### Phase 2: Migrate Event Handling (1 day)

- Replace all `_handle_event()` logic with event bus
- Remove Future-based consent handling
- Test all event flows

### Phase 3: Add Consent Handler (1 day)

```python
# ppxai/tui/handlers/consent.py (NEW)
class ConsentHandler:
    """Handles consent requests via event bus."""

    def __init__(self, bus: EventBus, engine_client: EngineClient):
        self.bus = bus
        self.engine = engine_client

        # Subscribe to consent responses
        self.bus.on(Events.CONSENT_RESPONSE, self._on_consent_response)

    async def _on_consent_response(self, sender, response: dict, **kwargs):
        """Send consent response to engine."""
        await self.engine.send_consent_response(response)
```

**Total effort:** 4 days

**Code reduction:**
- Before: ~1,500 lines with complex Future handling
- After: ~1,000 lines with simple event handlers (-33%)

---

## Benefits

### 1. Decoupling

**Before:**
```python
# Tight coupling
self.chat_view.post_message(ChunkMessage(data))
```

**After:**
```python
# Decoupled
self.bus.emit(Events.ENGINE_CHUNK, data=data)
```

### 2. Simpler Consent Handling

**Before (complex):**
```python
future = asyncio.Future()
self._pending_consent = future
# ... complex coordination ...
response = await future
```

**After (simple):**
```python
response = await self.show_consent_dialog(data)
self.bus.emit(Events.CONSENT_RESPONSE, response=response)
```

### 3. Testability

**Before:**
```python
# Need full Textual app to test
app = PPXAIDEApp()
await app._handle_event(event)  # Complex
```

**After:**
```python
# Test event handlers in isolation
bus = EventBus()
handler = ConsentHandler(bus, mock_engine)
bus.emit(Events.CONSENT_RESPONSE, response={"approved": True})
# Easy to mock!
```

### 4. Migration Path to Embedded Server

**Event bus pattern prepares for embedded server thread:**

```python
# Future: Embedded server thread
server_thread = EmbeddedServer()
server_thread.start()

# Events cross thread boundary naturally
http_client = PpxaiHttpClient(server_thread.url)
async for event in http_client.stream_chat(message):
    # Same event bus pattern!
    self.bus.emit(f"engine:{event.type}", data=event.data)
```

---

## Summary

**Recommendation: Use Blinker**

1. **Add blinker** to dependencies (1 small package)
2. **Create EventBus wrapper** (~100 lines)
3. **Migrate event handling** (4 days effort)
4. **Gain benefits:**
   - ✅ Decoupled components
   - ✅ Simpler consent handling
   - ✅ Better testability
   - ✅ Ready for embedded server thread
   - ✅ Same pattern as NATS (easy migration)

**Code reduction:** ~500 lines (-33%)
**Complexity reduction:** Significant (no Future-based coordination)
**Risk:** Low (blinker is mature and well-tested)

---

## Next Steps

1. **Add blinker to pyproject.toml**
2. **Create event_bus.py module**
3. **Port VSCode EventBus pattern**
4. **Migrate one event handler as POC**
5. **Incrementally migrate all handlers**
6. **Remove Future-based consent code**

**Timeline:** Can be done in v1.16.0 alongside embedded server work, or as standalone improvement in v1.15.1.

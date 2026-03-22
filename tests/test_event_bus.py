#!/usr/bin/env python3
"""Test script for event bus integration."""

import asyncio
import sys
from ppxai.tui.event_bus import EventBus, Events


def test_basic_event_flow():
    """Test basic event emission and handling with sync handlers."""
    print("=" * 60)
    print("TEST 1: Basic Event Flow (Sync Handlers)")
    print("=" * 60)

    bus = EventBus(log_events=True)

    # Track received events
    received_events = []

    def on_test_event(sender, **kwargs):
        """Simple sync handler."""
        received_events.append(("sync", kwargs))
        print(f"[Handler] Sync handler received: {kwargs}")

    def on_test_event_2(sender, **kwargs):
        """Second sync handler."""
        received_events.append(("sync2", kwargs))
        print(f"[Handler] Sync handler 2 received: {kwargs}")

    # Subscribe handlers
    bus.on("test:event", on_test_event)
    bus.on("test:event", on_test_event_2)

    # Emit event
    print("\n[Test] Emitting test:event with data='Hello'")
    bus.emit("test:event", data="Hello", count=42)

    # Verify
    assert len(received_events) == 2, f"Expected 2 events, got {len(received_events)}"
    assert received_events[0][0] == "sync", "First handler should be sync"
    assert received_events[1][0] == "sync2", "Second handler should be sync2"
    assert received_events[0][1]["data"] == "Hello", "Data mismatch"
    assert received_events[0][1]["count"] == 42, "Count mismatch"

    print("\n✅ Test 1 PASSED: Basic event flow works")


def test_engine_event_constants():
    """Test that all engine event constants are defined."""
    print("\n" + "=" * 60)
    print("TEST 2: Engine Event Constants")
    print("=" * 60)

    required_events = [
        "ENGINE_STREAM_START",
        "ENGINE_STREAM_CHUNK",
        "ENGINE_STREAM_END",
        "ENGINE_TOOL_CALL",
        "ENGINE_TOOL_RESULT",
        "ENGINE_ERROR",
        "ENGINE_CONSENT_FILE",
        "ENGINE_CONSENT_SHELL",
    ]

    for event_name in required_events:
        assert hasattr(Events, event_name), f"Missing event constant: {event_name}"
        event_value = getattr(Events, event_name)
        print(f"  ✓ {event_name} = '{event_value}'")

    print("\n✅ Test 2 PASSED: All engine event constants defined")


def test_event_bus_in_app():
    """Test that PPXAIDEApp has event bus integrated."""
    print("\n" + "=" * 60)
    print("TEST 3: Event Bus in PPXAIDEApp")
    print("=" * 60)

    from ppxai.tui.app import PPXAIDEApp

    # Create app instance (don't run it)
    app = PPXAIDEApp()

    # Verify event bus exists
    assert hasattr(app, "_event_bus"), "App missing _event_bus attribute"
    assert app._event_bus is not None, "Event bus not initialized"
    assert isinstance(app._event_bus, EventBus), "Event bus wrong type"

    print("  ✓ PPXAIDEApp has _event_bus attribute")
    print(f"  ✓ Event bus type: {type(app._event_bus).__name__}")
    print(f"  ✓ Event logging enabled: {app._event_bus._log_events}")

    # Verify event handler functions exist in stream_handler module
    from ppxai.tui import stream_handler
    required_handlers = [
        "on_stream_start",
        "on_stream_chunk",
        "on_stream_end",
        "on_tool_call",
        "on_tool_result",
        "on_engine_error",
    ]

    for handler_name in required_handlers:
        assert hasattr(stream_handler, handler_name), f"Missing handler: {handler_name}"
        handler = getattr(stream_handler, handler_name)
        assert callable(handler), f"Handler not callable: {handler_name}"
        print(f"  ✓ Handler exists: stream_handler.{handler_name}")

    print("\n✅ Test 3 PASSED: Event bus integrated in PPXAIDEApp")


async def test_stream_event_simulation_async():
    """Test simulated stream events with async handlers."""
    bus = EventBus(log_events=True)

    # Track stream content
    stream_data = {
        "started": False,
        "chunks": [],
        "ended": False,
    }

    async def on_stream_start(sender, **kwargs):
        stream_data["started"] = True
        print(f"[Handler] Stream started")

    async def on_stream_chunk(sender, data, **kwargs):
        stream_data["chunks"].append(data)
        print(f"[Handler] Chunk received: '{data}'")

    async def on_stream_end(sender, data, **kwargs):
        stream_data["ended"] = True
        print(f"[Handler] Stream ended")

    # Subscribe
    bus.on(Events.ENGINE_STREAM_START, on_stream_start)
    bus.on(Events.ENGINE_STREAM_CHUNK, on_stream_chunk)
    bus.on(Events.ENGINE_STREAM_END, on_stream_end)

    # Simulate streaming
    print("\n[Test] Simulating stream: START -> CHUNK x3 -> END")

    bus.emit(Events.ENGINE_STREAM_START)
    bus.emit(Events.ENGINE_STREAM_CHUNK, data="Hello")
    bus.emit(Events.ENGINE_STREAM_CHUNK, data=" ")
    bus.emit(Events.ENGINE_STREAM_CHUNK, data="World!")
    bus.emit(Events.ENGINE_STREAM_END, data={})

    # Wait for async handlers to complete
    await asyncio.sleep(0.1)

    # Verify
    assert stream_data["started"], "Stream didn't start"
    assert len(stream_data["chunks"]) == 3, f"Expected 3 chunks, got {len(stream_data['chunks'])}"
    assert "".join(stream_data["chunks"]) == "Hello World!", "Content mismatch"
    assert stream_data["ended"], "Stream didn't end"


def test_stream_event_simulation():
    """Test simulated stream events."""
    print("\n" + "=" * 60)
    print("TEST 4: Simulated Stream Events (Async Handlers)")
    print("=" * 60)

    # Run async test
    asyncio.run(test_stream_event_simulation_async())

    print("\n✅ Test 4 PASSED: Stream events work correctly")


def main():
    """Run all tests."""
    print("\n" + "🧪 " * 30)
    print("EVENT BUS INTEGRATION TESTS")
    print("🧪 " * 30 + "\n")

    tests = [
        test_basic_event_flow,
        test_engine_event_constants,
        test_event_bus_in_app,
        test_stream_event_simulation,
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"\n❌ Test FAILED: {test_func.__name__}")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"  ✅ Passed: {passed}/{len(tests)}")
    print(f"  ❌ Failed: {failed}/{len(tests)}")

    if failed == 0:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️  {failed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())

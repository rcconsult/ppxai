#!/usr/bin/env python3
"""
Test script to reproduce the 400 error.

This simulates the exact sequence from the terminal:
1. Query without tools (uses legacy client)
2. Enable tools (syncs history to engine client)
3. Query with tools (uses engine client) ← 400 ERROR
"""

import asyncio
from ppxai.engine import EngineClient
from ppxai.engine.types import Message

async def main():
    print("=== Reproducing 400 Error ===\n")

    # Create engine client
    engine = EngineClient()
    engine.set_provider("perplexity")
    engine.set_model("sonar-pro")

    # Simulate first query (before tools enabled)
    # In reality, this would use legacy client, but let's simulate the history
    print("1. Simulating first query (tools OFF)...")
    engine.session.add_message(Message("user", "review the roadmap items"))
    engine.session.add_message(Message("assistant", "Here is the roadmap review..."))

    print(f"   History after first query: {len(engine.session.messages)} messages")
    for i, msg in enumerate(engine.session.messages):
        print(f"     [{i}] {msg.role}: {msg.content[:50]}...")

    # Enable tools (this is what /tools enable does)
    print("\n2. Enabling tools...")
    engine.enable_tools()

    print(f"   History after enabling tools: {len(engine.session.messages)} messages")

    # Try to send another query (this should cause 400 error)
    print("\n3. Sending query with tools enabled...")
    print("   Expected: AI tries to call list_directory tool")
    print("   Actual result:")

    try:
        async for event in engine.chat("use tools to review the current project", stream=True):
            print(f"     Event: {event.type} - {str(event.data)[:100]}")

            if event.type.value == "error":
                print(f"\n❌ ERROR OCCURRED:")
                print(f"   {event.data}")
                break
    except Exception as e:
        print(f"\n❌ EXCEPTION:")
        print(f"   {type(e).__name__}: {e}")

    # Print final history state
    print(f"\n4. Final history: {len(engine.session.messages)} messages")
    for i, msg in enumerate(engine.session.messages):
        print(f"   [{i}] {msg.role}: {msg.content[:80]}...")

if __name__ == "__main__":
    asyncio.run(main())

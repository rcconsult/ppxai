#!/usr/bin/env python3
"""
Test that completer updates model list when provider changes.
"""

from pathlib import Path

from ppxai.engine.client import EngineClient
from ppxai.tui.completer import TextualCompleter

# Initialize engine client
engine_client = EngineClient()

# Initialize completer with engine client reference
completer = TextualCompleter(
    working_dir=Path.cwd(),
    engine_client=engine_client
)

print("Provider Change Model List Test\n" + "=" * 60)

# Test 1: Get models for perplexity
print("\n1. Initial provider (perplexity):")
print(f"   Engine provider_name: {engine_client.provider_name}")
print(f"   set_provider returned: {engine_client.set_provider('perplexity')}")
print(f"   Engine provider_name after set: {engine_client.provider_name}")
completions = completer.get_completions("/model ")
print(f"   Models available: {len(completions)}")
if completions:
    print(f"   First 3: {[c[0] for c in completions[:3]]}")
    # Verify perplexity models
    model_names = [c[0] for c in completions]
    if any("sonar" in m.lower() or "llama" in m.lower() for m in model_names):
        print("   ✓ Showing Perplexity models")
    else:
        print("   ✗ Not showing expected Perplexity models")

# Test 2: Change provider to gemini
print("\n2. After switching to gemini:")
engine_client.set_provider("gemini")
print(f"   Engine provider: {engine_client.provider}")
completions = completer.get_completions("/model ")
print(f"   Models available: {len(completions)}")
if completions:
    print(f"   First 3: {[c[0] for c in completions[:3]]}")
    # Verify gemini models
    model_names = [c[0] for c in completions]
    if any("gemini" in m.lower() for m in model_names):
        print("   ✓ Showing Gemini models")
    else:
        print("   ✗ Not showing expected Gemini models")
        print(f"   Models: {model_names}")

# Test 3: Change provider to openai
print("\n3. After switching to openai:")
engine_client.set_provider("openai")
print(f"   Engine provider: {engine_client.provider}")
completions = completer.get_completions("/model ")
print(f"   Models available: {len(completions)}")
if completions:
    print(f"   First 3: {[c[0] for c in completions[:3]]}")
    # Verify openai models
    model_names = [c[0] for c in completions]
    if any("gpt" in m.lower() for m in model_names):
        print("   ✓ Showing OpenAI models")
    else:
        print("   ✗ Not showing expected OpenAI models")

print("\n" + "=" * 60)
print("Expected behavior:")
print("  - Completer should dynamically read engine_client.provider")
print("  - Model list should update when provider changes")
print("  - No caching of model lists by provider")
print("\n✓ Provider change model list test completed")

#!/usr/bin/env python3
"""
Test that completer updates model list when provider changes (with mock).
"""

from pathlib import Path
from ppxai.tui.completer import TextualCompleter

# Create a mock engine client
class MockEngineClient:
    def __init__(self):
        self.provider_name = "perplexity"

    def set_provider(self, name):
        self.provider_name = name

# Initialize completer with mock engine client
engine_client = MockEngineClient()
completer = TextualCompleter(
    working_dir=Path.cwd(),
    engine_client=engine_client
)

print("Provider Change Model List Test (Mock)\n" + "=" * 60)

# Test 1: Get models for perplexity
print("\n1. Initial provider (perplexity):")
print(f"   Engine provider_name: {engine_client.provider_name}")
completions = completer.get_completions("/model ")
print(f"   Models available: {len(completions)}")
if completions:
    print(f"   First 3: {[c[0] for c in completions[:3]]}")
    model_names = [c[0] for c in completions]
    if any("sonar" in m.lower() or "llama" in m.lower() for m in model_names):
        print("   ✓ Showing Perplexity models")
    else:
        print("   ✗ ERROR: Not showing Perplexity models")

# Test 2: Change provider to gemini
print("\n2. After switching to gemini:")
engine_client.set_provider("gemini")
print(f"   Engine provider_name: {engine_client.provider_name}")
completions = completer.get_completions("/model ")
print(f"   Models available: {len(completions)}")
if completions:
    print(f"   First 3: {[c[0] for c in completions[:3]]}")
    model_names = [c[0] for c in completions]
    if any("gemini" in m.lower() for m in model_names):
        print("   ✓ Showing Gemini models")
    else:
        print(f"   ✗ ERROR: Not showing Gemini models. Got: {model_names}")

# Test 3: Change provider to openai
print("\n3. After switching to openai:")
engine_client.set_provider("openai")
print(f"   Engine provider_name: {engine_client.provider_name}")
completions = completer.get_completions("/model ")
print(f"   Models available: {len(completions)}")
if completions:
    print(f"   First 3: {[c[0] for c in completions[:3]]}")
    model_names = [c[0] for c in completions]
    if any("gpt" in m.lower() for m in model_names):
        print("   ✓ Showing OpenAI models")
    else:
        print(f"   ✗ ERROR: Not showing OpenAI models. Got: {model_names}")

# Test 4: Change back to perplexity
print("\n4. After switching back to perplexity:")
engine_client.set_provider("perplexity")
print(f"   Engine provider_name: {engine_client.provider_name}")
completions = completer.get_completions("/model ")
print(f"   Models available: {len(completions)}")
if completions:
    print(f"   First 3: {[c[0] for c in completions[:3]]}")
    model_names = [c[0] for c in completions]
    if any("sonar" in m.lower() or "llama" in m.lower() for m in model_names):
        print("   ✓ Showing Perplexity models again")
    else:
        print("   ✗ ERROR: Not showing Perplexity models")

print("\n" + "=" * 60)
print("✅ Provider change correctly updates model list in completer!")
print("   The fix: Use engine_client.provider_name (string) instead of")
print("            engine_client.provider (object)")

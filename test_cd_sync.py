#!/usr/bin/env python3
"""
Test directory synchronization for autocomplete after /cd commands.
"""

from pathlib import Path
from ppxai.tui.completer import TextualCompleter

# Create completer starting in current directory
completer = TextualCompleter(working_dir=Path.cwd())

print("Directory Synchronization Test\n" + "=" * 60)

# Scenario 1: Start in project root
print("\n1. Initial directory (project root):")
print(f"   Working dir: {completer.working_dir}")
completions = completer.get_completions("/show ")
print(f"   Files available: {len(completions)}")
if completions:
    print(f"   First 3: {[c[0] for c in completions[:3]]}")

# Scenario 2: Simulate /cd docs
print("\n2. After '/cd docs':")
docs_path = Path.cwd() / "docs"
if docs_path.exists():
    completer.update_working_dir(docs_path)
    print(f"   Working dir: {completer.working_dir}")
    completions = completer.get_completions("/show ")
    print(f"   Files available: {len(completions)}")
    if completions:
        print(f"   First 3: {[c[0] for c in completions[:3]]}")
else:
    print(f"   (docs directory doesn't exist)")

# Scenario 3: Simulate /cd ..
print("\n3. After '/cd ..':")
completer.update_working_dir(Path.cwd())
print(f"   Working dir: {completer.working_dir}")
completions = completer.get_completions("/show ")
print(f"   Files available: {len(completions)}")
if completions:
    print(f"   First 3: {[c[0] for c in completions[:3]]}")

# Scenario 4: Verify cache was invalidated
print("\n4. Cache invalidation check:")
print(f"   Cache size: {len(completer._file_cache)}")
print(f"   Cache dir: {completer._cache_dir}")
print(f"   ✓ Cache properly invalidated" if not completer._file_cache else "   ✗ Cache still populated")

print("\n" + "=" * 60)
print("✓ Directory synchronization test completed")

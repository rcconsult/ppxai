#!/usr/bin/env python3
"""
Test directory synchronization when AI uses set_working_dir tool.

This tests the event-based synchronization path:
1. AI uses set_working_dir tool
2. Engine emits WorkingDirChangedEvent
3. App's _on_working_dir_changed handler fires
4. Completer is updated to new directory
"""

from pathlib import Path
from ppxai.tui.completer import TextualCompleter

# Simulate the event-based directory change flow
completer = TextualCompleter(working_dir=Path.cwd())

print("AI Tool-Based Directory Synchronization Test\n" + "=" * 60)

# Scenario: AI uses set_working_dir tool (event-based)
print("\n1. Initial directory (project root):")
print(f"   Working dir: {completer.working_dir}")
completions = completer.get_completions("/show ")
print(f"   Files available: {len(completions)}")
if completions:
    print(f"   First 3: {[c[0] for c in completions[:3]]}")

# Simulate: AI executes set_working_dir("docs")
# → Engine emits WorkingDirChangedEvent
# → App's _on_working_dir_changed handler calls completer.update_working_dir()
print("\n2. After AI tool changes directory to 'docs':")
print("   (Simulating: _on_working_dir_changed event handler)")
docs_path = Path.cwd() / "docs"
if docs_path.exists():
    completer.update_working_dir(docs_path)
    print(f"   Working dir: {completer.working_dir}")
    completions = completer.get_completions("/show ")
    print(f"   Files available: {len(completions)}")
    if completions:
        print(f"   First 3: {[c[0] for c in completions[:3]]}")

    # Verify we're showing docs files, not root files
    filenames = [c[0] for c in completions]
    if any("TODO" in f or "ARCHITECTURE" in f for f in filenames):
        print("   ✓ Showing docs/ files (not root files)")
    else:
        print("   ⚠ May still be showing root files")
else:
    print(f"   (docs directory doesn't exist)")

# Scenario: AI uses shell command "cd .."
# → Engine emits WorkingDirChangedEvent
# → App's _on_working_dir_changed handler calls completer.update_working_dir()
print("\n3. After AI tool changes directory back to '..':")
print("   (Simulating: _on_working_dir_changed event handler)")
completer.update_working_dir(Path.cwd())
print(f"   Working dir: {completer.working_dir}")
completions = completer.get_completions("/show ")
print(f"   Files available: {len(completions)}")
if completions:
    print(f"   First 3: {[c[0] for c in completions[:3]]}")

# Verify cache was invalidated
print("\n4. Cache invalidation check:")
print(f"   Cache size: {len(completer._file_cache)}")
print(f"   Cache dir: {completer._cache_dir}")
print(f"   ✓ Cache properly invalidated" if not completer._file_cache else "   ✗ Cache still populated")

print("\n" + "=" * 60)
print("Test Flow:")
print("  User prompt: 'change to docs directory'")
print("  → AI calls set_working_dir('docs')")
print("  → Engine emits WorkingDirChangedEvent")
print("  → App._on_working_dir_changed() fires")
print("  → completer.update_working_dir(Path('docs'))")
print("  → User types '/show <TAB>' and sees docs/ files")
print("\n✓ AI tool-based directory synchronization test completed")

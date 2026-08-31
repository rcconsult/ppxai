#!/usr/bin/env python3
"""Test directory path completion."""

from pathlib import Path

from ppxai.tui.completer import TextualCompleter

completer = TextualCompleter(working_dir=Path.cwd())

print("Directory Path Completion Test\n" + "=" * 60)

tests = [
    ("/show ppxai/", "Directory path", "Should complete to ppxai/file.py"),
    ("/show ppxai/s", "Directory + prefix", "Should complete to ppxai/server.py"),
    ("/show ppxai/tui/", "Nested directory", "Should complete to ppxai/tui/file.py"),
    ("/show README", "Simple filename", "Should complete to README.md"),
    ("/edit tests/", "Tests directory", "Should complete to tests/file.py"),
]

for text, description, expected in tests:
    completions = completer.get_completions(text)
    print(f"\n{description}")
    print(f"  Input: {text!r}")
    print(f"  Expected: {expected}")
    print(f"  Matches: {len(completions)}")

    if completions:
        comp_text, comp_desc = completions[0]
        print(f"  Result: {comp_text!r}")

        # Verify directory paths return full paths
        if '/' in text.split()[-1]:
            if '/' in comp_text:
                print("  ✓ Correctly returns full path")
            else:
                print("  ✗ ERROR: Should return full path, got just filename")
        else:
            if '/' not in comp_text:
                print("  ✓ Correctly returns just filename")
            else:
                print("  ✗ ERROR: Should return just filename, got path")
    else:
        print("  ⚠ No matches (files may not be in cache)")

print("\n" + "=" * 60)
print("✓ Directory completion test completed")

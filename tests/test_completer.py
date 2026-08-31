#!/usr/bin/env python3
"""
Quick test of TextualCompleter logic.
"""

from pathlib import Path

from ppxai.tui.completer import TextualCompleter

# Create completer
completer = TextualCompleter(working_dir=Path.cwd())

# Test cases
test_cases = [
    # Slash commands
    ("/", "Slash commands"),
    ("/to", "Slash command prefix"),

    # Subcommands
    ("/tools ", "Tools subcommands"),
    ("/tools e", "Tools subcommand prefix"),
    ("/checkpoint backend ", "Nested subcommands"),

    # File commands
    ("/show ", "Show file completions"),
    ("/show RE", "Show file prefix"),
    ("/edit ", "Edit file completions"),

    # Context providers
    ("@", "Context providers"),
    ("@f", "Context provider prefix"),
    ("@g", "Context provider prefix (git)"),
    ("tell me about @", "Context in message"),
]

print("TextualCompleter Test\n" + "=" * 60)

for text, description in test_cases:
    completions = completer.get_completions(text)
    print(f"\nInput: '{text}' ({description})")
    if completions:
        print(f"  Found {len(completions)} completions:")
        for comp, desc in completions[:5]:  # Show first 5
            print(f"    - {comp:30s} | {desc}")
        if len(completions) > 5:
            print(f"    ... and {len(completions) - 5} more")
    else:
        print("  No completions")

print("\n" + "=" * 60)
print("✓ Test completed")

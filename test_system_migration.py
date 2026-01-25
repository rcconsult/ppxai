#!/usr/bin/env python3
"""
Integration test for System Operations commands migration.

Tests v2 handlers for:
- /cd (handle_cd)
- /pwd (handle_pwd)
- /config (handle_config)
- /debug-log (handle_debug_log)
- /context (handle_context)
- /checkpoint (handle_checkpoint)
- /undo (handle_undo)

v1.15.0: Type-based renderer dispatch testing
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console

from ppxai.commands.context import RichCommandContext
from ppxai.commands.handler import CommandHandler
from ppxai.commands.utility import (
    handle_cd,
    handle_pwd,
    handle_config,
    handle_debug_log,
    handle_context,
)
from ppxai.commands.agent import (
    handle_checkpoint,
    handle_undo,
)
from ppxai.commands.results import (
    CommandResult,
    KeyValueResult,
    ConfirmationResult,
    ErrorResult,
    TreeResult,
    TableResult,
    TextResult,
)
from ppxai.rendering.rich_renderer import RichRenderer
from ppxai.config import get_default_provider, get_default_model, get_api_key, get_base_url

console = Console()


def test_pwd():
    """Test /pwd command with type-based rendering."""
    console.print("\n[bold cyan]Test 1: /pwd command[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        result = handle_pwd(context, "")

        assert isinstance(result, KeyValueResult), f"Expected KeyValueResult, got {type(result)}"
        assert "Working Directory" in result.pairs, "Result should contain working directory"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Result rendered successfully")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_cd():
    """Test /cd command with type-based rendering."""
    console.print("\n[bold cyan]Test 2: /cd command[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test without arguments (should delegate to pwd)
        result = handle_cd(context, "")

        assert isinstance(result, KeyValueResult), f"Expected KeyValueResult, got {type(result)}"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Result rendered successfully")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_config():
    """Test /config command with type-based rendering."""
    console.print("\n[bold cyan]Test 3: /config command[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test config path
        result = handle_config(context, "path")

        assert isinstance(result, KeyValueResult), f"Expected KeyValueResult, got {type(result)}"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Result rendered successfully")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_debug_log():
    """Test /debug-log command with type-based rendering."""
    console.print("\n[bold cyan]Test 4: /debug-log command[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test status (no args)
        result = handle_debug_log(context, "")

        assert isinstance(result, KeyValueResult), f"Expected KeyValueResult, got {type(result)}"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Result rendered successfully")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_context():
    """Test /context command with type-based rendering."""
    console.print("\n[bold cyan]Test 5: /context command[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test context usage (no args)
        result = handle_context(context, "")

        assert isinstance(result, KeyValueResult), f"Expected KeyValueResult, got {type(result)}"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Result rendered successfully")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_checkpoint():
    """Test /checkpoint command with type-based rendering."""
    console.print("\n[bold cyan]Test 6: /checkpoint command[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test checkpoint status
        result = handle_checkpoint(context, "status")

        assert isinstance(result, KeyValueResult), f"Expected KeyValueResult, got {type(result)}"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Result rendered successfully")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_undo():
    """Test /undo command with type-based rendering."""
    console.print("\n[bold cyan]Test 7: /undo command[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test undo (should return ErrorResult since no checkpoint exists)
        result = handle_undo(context, "")

        assert isinstance(result, ErrorResult), f"Expected ErrorResult, got {type(result)}"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Result rendered successfully (expected error)")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    console.print("\n[bold magenta]═══════════════════════════════════════════════════[/bold magenta]")
    console.print("[bold magenta]  System Operations Commands Migration Tests[/bold magenta]")
    console.print("[bold magenta]═══════════════════════════════════════════════════[/bold magenta]")

    tests = [
        test_pwd,
        test_cd,
        test_config,
        test_debug_log,
        test_context,
        test_checkpoint,
        test_undo,
    ]

    results = []
    for test in tests:
        results.append(test())

    # Summary
    passed = sum(results)
    total = len(results)

    console.print(f"\n[bold]Results: {passed}/{total} tests passed[/bold]")

    if passed == total:
        console.print("[bold green]✓ All System Operations commands migrated successfully![/bold green]\n")
        return 0
    else:
        console.print(f"[bold red]✗ {total - passed} test(s) failed[/bold red]\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())

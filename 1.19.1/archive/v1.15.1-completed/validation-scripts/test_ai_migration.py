#!/usr/bin/env python3
"""
Integration test for AI Commands migration.

Tests v2 handlers for:
- /generate (handle_generate)
- /test (handle_test)
- /docs (handle_docs)
- /implement (handle_implement)
- /debug (handle_debug)
- /explain (handle_explain)
- /convert (handle_convert)
- /agent (handle_agent)

v1.15.0: Type-based renderer dispatch testing
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console

from ppxai.commands.agent import handle_agent
from ppxai.commands.coding import (
    handle_convert,
    handle_debug,
    handle_docs,
    handle_explain,
    handle_generate,
    handle_implement,
    handle_test,
)
from ppxai.commands.context import RichCommandContext
from ppxai.commands.handler import CommandHandler
from ppxai.commands.results import (
    ConfirmationResult,
    ErrorResult,
)
from ppxai.config import get_api_key, get_base_url, get_default_model, get_default_provider
from ppxai.rendering.rich_renderer import RichRenderer

console = Console()


def test_generate_validation():
    """Test /generate command validation (no args)."""
    console.print("\n[bold cyan]Test 1: /generate validation[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test without arguments (should return ErrorResult)
        result = handle_generate(context, "")

        assert isinstance(result, ErrorResult), f"Expected ErrorResult, got {type(result)}"
        assert "description" in result.message.lower(), "Error message should mention description"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Validation works correctly")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_test_validation():
    """Test /test command validation (no args)."""
    console.print("\n[bold cyan]Test 2: /test validation[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test without arguments (should return ErrorResult)
        result = handle_test(context, "")

        assert isinstance(result, ErrorResult), f"Expected ErrorResult, got {type(result)}"
        assert "file" in result.message.lower(), "Error message should mention file"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Validation works correctly")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_docs_validation():
    """Test /docs command validation (no args)."""
    console.print("\n[bold cyan]Test 3: /docs validation[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test without arguments (should return ErrorResult)
        result = handle_docs(context, "")

        assert isinstance(result, ErrorResult), f"Expected ErrorResult, got {type(result)}"
        assert "file" in result.message.lower(), "Error message should mention file"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Validation works correctly")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_implement_validation():
    """Test /implement command validation (no args)."""
    console.print("\n[bold cyan]Test 4: /implement validation[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test without arguments (should return ErrorResult)
        result = handle_implement(context, "")

        assert isinstance(result, ErrorResult), f"Expected ErrorResult, got {type(result)}"
        assert "specification" in result.message.lower(), "Error message should mention specification"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Validation works correctly")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_debug_validation():
    """Test /debug command validation (no args)."""
    console.print("\n[bold cyan]Test 5: /debug validation[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test without arguments (should return ErrorResult)
        result = handle_debug(context, "")

        assert isinstance(result, ErrorResult), f"Expected ErrorResult, got {type(result)}"
        assert "error" in result.message.lower(), "Error message should mention error details"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Validation works correctly")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_explain_validation():
    """Test /explain command validation (no args)."""
    console.print("\n[bold cyan]Test 6: /explain validation[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test without arguments (should return ErrorResult)
        result = handle_explain(context, "")

        assert isinstance(result, ErrorResult), f"Expected ErrorResult, got {type(result)}"
        assert "file" in result.message.lower(), "Error message should mention file"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Validation works correctly")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_convert_validation():
    """Test /convert command validation (no args)."""
    console.print("\n[bold cyan]Test 7: /convert validation[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test without arguments (should return ErrorResult)
        result = handle_convert(context, "")

        assert isinstance(result, ErrorResult), f"Expected ErrorResult, got {type(result)}"
        assert "source-lang" in result.message.lower() or "target-lang" in result.message.lower(), \
            "Error message should mention language conversion"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Validation works correctly")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_agent_validation():
    """Test /agent command validation (no args)."""
    console.print("\n[bold cyan]Test 8: /agent validation[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test without arguments (should return ErrorResult)
        result = handle_agent(context, "")

        assert isinstance(result, ErrorResult), f"Expected ErrorResult, got {type(result)}"
        assert "task" in result.message.lower() or "usage" in result.message.lower(), \
            "Error message should mention task or usage"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Validation works correctly")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_agent_toggle():
    """Test /agent on/off toggle commands."""
    console.print("\n[bold cyan]Test 9: /agent toggle[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test agent on (should return ConfirmationResult)
        result = handle_agent(context, "on")

        assert isinstance(result, ConfirmationResult), f"Expected ConfirmationResult, got {type(result)}"
        assert "enabled" in result.message.lower(), "Message should mention enabled"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Agent toggle works correctly")

        # Test agent off
        result = handle_agent(context, "off")

        assert isinstance(result, ConfirmationResult), f"Expected ConfirmationResult, got {type(result)}"
        assert "disabled" in result.message.lower(), "Message should mention disabled"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Agent toggle off works correctly")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_agent_vague_task():
    """Test /agent with vague task (should reject)."""
    console.print("\n[bold cyan]Test 10: /agent vague task validation[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Test with vague task (should return ErrorResult)
        result = handle_agent(context, "fix bug")

        assert isinstance(result, ErrorResult), f"Expected ErrorResult, got {type(result)}"
        assert "vague" in result.message.lower() or "specific" in result.message.lower(), \
            "Error message should mention vague/specific task requirement"

        RichRenderer.render(result)
        console.print("[green]✓[/green] Vague task rejection works correctly")

        return True
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    console.print("\n[bold magenta]═══════════════════════════════════════════════════[/bold magenta]")
    console.print("[bold magenta]  AI Commands Migration Tests[/bold magenta]")
    console.print("[bold magenta]═══════════════════════════════════════════════════[/bold magenta]")

    tests = [
        test_generate_validation,
        test_test_validation,
        test_docs_validation,
        test_implement_validation,
        test_debug_validation,
        test_explain_validation,
        test_convert_validation,
        test_agent_validation,
        test_agent_toggle,
        test_agent_vague_task,
    ]

    results = []
    for test in tests:
        results.append(test())

    # Summary
    passed = sum(results)
    total = len(results)

    console.print(f"\n[bold]Results: {passed}/{total} tests passed[/bold]")

    if passed == total:
        console.print("[bold green]✓ All AI commands migrated successfully![/bold green]\n")
        return 0
    else:
        console.print(f"[bold red]✗ {total - passed} test(s) failed[/bold red]\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())

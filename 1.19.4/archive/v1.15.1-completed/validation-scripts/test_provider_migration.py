"""
Quick integration test for model/provider command migration.

Tests that the new typed-result model/provider commands work end-to-end.
"""

from rich.console import Console

from ppxai.commands import CommandHandler
from ppxai.commands.context import RichCommandContext
from ppxai.commands.provider import handle_autoroute, handle_model, handle_provider
from ppxai.commands.results import (
    ErrorResult,
    KeyValueResult,
    ListResult,
    TableResult,
)
from ppxai.commands.tools import handle_tools, handle_usage
from ppxai.config import get_api_key, get_base_url, get_default_model, get_default_provider
from ppxai.rendering.rich_renderer import RichRenderer

console = Console()

def test_model_list():
    """Test /model list command with type-based rendering."""
    console.print("\n[bold cyan]Test 1: /model list command[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        # Create command handler
        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Call command
        result = handle_model(context, "list")

        # Verify result type
        assert isinstance(result, ListResult), \
            f"Expected ListResult, got {type(result)}"

        console.print("[green]✓[/green] Command returned typed result:", type(result).__name__)

        # Render result
        RichRenderer.render(result)
        console.print("[green]✓[/green] Result rendered successfully")

        return True

    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_provider_list():
    """Test /provider list command with type-based rendering."""
    console.print("\n[bold cyan]Test 2: /provider list command[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        # Create command handler
        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Call command
        result = handle_provider(context, "list")

        # Verify result type
        assert isinstance(result, ListResult), \
            f"Expected ListResult, got {type(result)}"

        console.print("[green]✓[/green] Command returned typed result:", type(result).__name__)

        # Render result
        RichRenderer.render(result)
        console.print("[green]✓[/green] Result rendered successfully")

        return True

    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_autoroute_status():
    """Test /autoroute status command with type-based rendering."""
    console.print("\n[bold cyan]Test 3: /autoroute command[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        # Create command handler
        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Call command (no args = show status)
        result = handle_autoroute(context, "")

        # Verify result type
        assert isinstance(result, KeyValueResult), \
            f"Expected KeyValueResult, got {type(result)}"

        console.print("[green]✓[/green] Command returned typed result:", type(result).__name__)

        # Render result
        RichRenderer.render(result)
        console.print("[green]✓[/green] Result rendered successfully")

        return True

    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_tools_status():
    """Test /tools status command with type-based rendering."""
    console.print("\n[bold cyan]Test 4: /tools status command[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        # Create command handler
        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Call command
        result = handle_tools(context, "status")

        # Verify result type (KeyValueResult or ErrorResult if tools not available)
        assert isinstance(result, (KeyValueResult, ErrorResult)), \
            f"Expected KeyValueResult or ErrorResult, got {type(result)}"

        console.print("[green]✓[/green] Command returned typed result:", type(result).__name__)

        # Render result
        RichRenderer.render(result)
        console.print("[green]✓[/green] Result rendered successfully")

        return True

    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_usage():
    """Test /usage command with type-based rendering."""
    console.print("\n[bold cyan]Test 5: /usage command[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        # Create command handler
        handler = CommandHandler(api_key, model, base_url, provider)
        context = RichCommandContext(handler)

        # Call command (no args = session totals)
        result = handle_usage(context, "")

        # Verify result type
        assert isinstance(result, TableResult), \
            f"Expected TableResult, got {type(result)}"

        console.print("[green]✓[/green] Command returned typed result:", type(result).__name__)

        # Render result
        RichRenderer.render(result)
        console.print("[green]✓[/green] Result rendered successfully")

        return True

    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    console.print("[bold]Testing Model/Provider Command Migration[/bold]")
    console.print("=" * 60)

    test1_pass = test_model_list()
    test2_pass = test_provider_list()
    test3_pass = test_autoroute_status()
    test4_pass = test_tools_status()
    test5_pass = test_usage()

    console.print("\n" + "=" * 60)
    if all([test1_pass, test2_pass, test3_pass, test4_pass, test5_pass]):
        console.print("[bold green]✓ All tests passed![/bold green]")
    else:
        console.print("[bold red]✗ Some tests failed[/bold red]")
        exit(1)

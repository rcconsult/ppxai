"""
Quick integration test for session command migration.

Tests that the new typed-result session commands work end-to-end.
"""

from rich.console import Console

from ppxai.commands import CommandHandler
from ppxai.commands.context import RichCommandContext
from ppxai.commands.results import ConfirmationResult, TableResult
from ppxai.commands.session import handle_clear_v2, handle_sessions_v2
from ppxai.config import get_api_key, get_base_url, get_default_model, get_default_provider
from ppxai.rendering.rich_renderer import RichRenderer

console = Console()

def test_sessions_command():
    """Test /sessions command with type-based rendering."""
    console.print("\n[bold cyan]Test 1: /sessions command[/bold cyan]")

    # Create a mock handler with engine client
    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        # Create command handler (which creates engine client internally)
        handler = CommandHandler(api_key, model, base_url, provider)

        # Create context adapter
        context = RichCommandContext(handler)

        # Call command
        result = handle_sessions_v2(context, "")

        # Verify result type
        assert isinstance(result, (TableResult, type(None))) or result.__class__.__name__ == 'NotificationResult', \
            f"Expected TableResult or NotificationResult, got {type(result)}"

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


def test_clear_command():
    """Test /clear command with type-based rendering."""
    console.print("\n[bold cyan]Test 2: /clear command[/bold cyan]")

    try:
        provider = get_default_provider()
        model = get_default_model(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        # Create command handler (which creates engine client internally)
        handler = CommandHandler(api_key, model, base_url, provider)

        # Create context adapter
        context = RichCommandContext(handler)

        # Call command
        result = handle_clear_v2(context, "")

        # Verify result type
        assert isinstance(result, ConfirmationResult), \
            f"Expected ConfirmationResult, got {type(result)}"

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
    console.print("[bold]Testing Session Command Migration[/bold]")
    console.print("=" * 60)

    test1_pass = test_sessions_command()
    test2_pass = test_clear_command()

    console.print("\n" + "=" * 60)
    if test1_pass and test2_pass:
        console.print("[bold green]✓ All tests passed![/bold green]")
    else:
        console.print("[bold red]✗ Some tests failed[/bold red]")
        exit(1)

#!/usr/bin/env python3
"""
Phase 6.2 Command Handler Validation Script

Manual validation script for TUI command factory integration.
Tests critical commands to ensure they work correctly with the engine.

Usage:
    uv run python scripts/validate_tui_commands.py

"""

import asyncio

# Add project root to path
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent))

from ppxai.commands.factory import CommandFactory
from ppxai.commands.results import ResultStatus

console = Console()


def print_header(text: str):
    """Print section header."""
    console.print()
    console.print(Panel(f"[bold cyan]{text}[/bold cyan]", expand=False))
    console.print()


def print_result(command: str, result, success: bool):
    """Print command result."""
    status_emoji = "✅" if success else "❌"
    status_color = "green" if success else "red"

    console.print(f"{status_emoji} [bold]{command}[/bold]: ", end="")
    console.print(f"[{status_color}]{result.status.value}[/{status_color}]")

    if hasattr(result, 'message') and result.message:
        console.print(f"   {result.message[:100]}")


async def validate_factory_registration():
    """Validate command factory registration."""
    print_header("Phase 6.2.1: Factory Registration")

    commands = CommandFactory.list_all()
    categories = CommandFactory.get_categories()

    table = Table(title="Command Factory Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Commands", str(len(commands)))
    table.add_row("Categories", str(len(categories)))
    table.add_row("Categories List", ", ".join(categories))

    console.print(table)

    # Check critical commands
    critical = ["help", "status", "provider", "model", "tools", "save", "load", "sessions"]
    missing = [cmd for cmd in critical if cmd not in commands]

    if missing:
        console.print(f"\n[red]❌ Missing critical commands: {missing}[/red]")
        return False
    else:
        console.print("\n[green]✅ All critical commands registered[/green]")
        return True


async def validate_command_execution():
    """Validate command execution without engine (dry run)."""
    print_header("Phase 6.2.2: Command Execution (No Engine)")

    # Create minimal mock context for testing
    class MockEngineClient:
        def get_working_dir(self):
            return str(Path.cwd())

    class MockContext:
        def __init__(self):
            self.engine_client = MockEngineClient()

        def get_provider(self):
            return "openai"

        def get_model(self):
            return "gpt-4"

        def get_theme(self):
            return "catppuccin-mocha"

        def set_theme(self, theme):
            pass

    ctx = MockContext()

    # Test commands that should work without engine
    test_cases = [
        ("help", ""),
        ("pwd", ""),
        ("theme", "list"),
    ]

    success_count = 0
    for cmd, args in test_cases:
        spec = CommandFactory.get(cmd)
        if not spec:
            console.print(f"❌ [bold]{cmd}[/bold]: Command not found")
            continue

        try:
            result = spec.handler(ctx, args)
            success = result.status in (ResultStatus.SUCCESS, ResultStatus.INFO)
            print_result(f"/{cmd} {args}", result, success)
            if success:
                success_count += 1
        except Exception as e:
            console.print(f"❌ [bold]{cmd}[/bold]: Exception: {e}")

    console.print(f"\n[bold]Success rate:[/bold] {success_count}/{len(test_cases)}")
    return success_count == len(test_cases)


async def validate_command_aliases():
    """Validate command aliases work correctly."""
    print_header("Phase 6.2.3: Command Aliases")

    # Test known aliases
    aliases = [
        ("cat", "show"),  # /cat is alias for /show
        ("h", "help"),
        ("m", "model"),
        ("p", "provider"),
        ("t", "tools"),
        ("s", "save"),
        ("l", "load"),
        ("c", "clear"),
    ]

    success_count = 0
    for alias, canonical in aliases:
        alias_spec = CommandFactory.get(alias)
        canonical_spec = CommandFactory.get(canonical)

        if alias_spec is canonical_spec:
            console.print(f"✅ [bold]/{alias}[/bold] → /{canonical}")
            success_count += 1
        else:
            console.print(f"❌ [bold]/{alias}[/bold] does not resolve to /{canonical}")

    console.print(f"\n[bold]Success rate:[/bold] {success_count}/{len(aliases)}")
    return success_count == len(aliases)


async def validate_category_organization():
    """Validate commands are organized by category."""
    print_header("Phase 6.2.4: Category Organization")

    categories = CommandFactory.get_categories()

    table = Table(title="Commands by Category")
    table.add_column("Category", style="cyan")
    table.add_column("Commands", style="green")
    table.add_column("Count", style="yellow")

    for category in sorted(categories):
        specs = CommandFactory.list_by_category(category)
        commands = [f"/{s.name}" for s in specs]
        table.add_row(
            category,
            ", ".join(commands[:5]) + ("..." if len(commands) > 5 else ""),
            str(len(commands))
        )

    console.print(table)
    return True


async def validate_result_types():
    """Validate commands return proper result types."""
    print_header("Phase 6.2.5: Result Type Validation")

    from ppxai.commands.results import (
        KeyValueResult,
        ListResult,
        TextResult,
    )

    # Simple mock context
    class MockEngineClient:
        def get_working_dir(self):
            return str(Path.cwd())

    class MockContext:
        def __init__(self):
            self.engine_client = MockEngineClient()
        def get_provider(self): return "openai"
        def get_model(self): return "gpt-4"
        def get_theme(self): return "catppuccin-mocha"
        def set_theme(self, t): pass

    ctx = MockContext()

    # Test a few commands and check their result types
    test_cases = [
        ("help", "", (TextResult,)),
        ("pwd", "", (TextResult, KeyValueResult)),
        ("theme", "list", (TextResult, ListResult, KeyValueResult)),
    ]

    success_count = 0
    for cmd, args, expected_types in test_cases:
        spec = CommandFactory.get(cmd)
        if not spec:
            console.print(f"❌ [bold]{cmd}[/bold]: Not found")
            continue

        try:
            result = spec.handler(ctx, args)
            if isinstance(result, expected_types):
                console.print(f"✅ [bold]/{cmd}[/bold]: {type(result).__name__}")
                success_count += 1
            else:
                console.print(f"❌ [bold]/{cmd}[/bold]: Expected {expected_types}, got {type(result).__name__}")
        except Exception as e:
            console.print(f"❌ [bold]/{cmd}[/bold]: Exception: {str(e)[:80]}")

    console.print(f"\n[bold]Success rate:[/bold] {success_count}/{len(test_cases)}")
    return success_count == len(test_cases)


async def main():
    """Run all validation checks."""
    console.print("[bold cyan]═" * 40)
    console.print("[bold cyan]Phase 6.2: Command Handler Validation[/bold cyan]")
    console.print("[bold cyan]═" * 40)

    results = []

    # Run validation phases
    results.append(("Factory Registration", await validate_factory_registration()))
    results.append(("Command Execution", await validate_command_execution()))
    results.append(("Command Aliases", await validate_command_aliases()))
    results.append(("Category Organization", await validate_category_organization()))
    results.append(("Result Types", await validate_result_types()))

    # Summary
    print_header("Validation Summary")

    summary_table = Table(title="Phase 6.2 Results")
    summary_table.add_column("Check", style="cyan")
    summary_table.add_column("Status", style="bold")

    passed = 0
    for name, success in results:
        status = "[green]✅ PASS[/green]" if success else "[red]❌ FAIL[/red]"
        summary_table.add_row(name, status)
        if success:
            passed += 1

    console.print(summary_table)
    console.print()

    if passed == len(results):
        console.print("[bold green]🎉 All validation checks passed![/bold green]")
        console.print("[bold green]Phase 6.2 is complete and ready for engine integration.[/bold green]")
        return 0
    else:
        console.print(f"[bold yellow]⚠️  {passed}/{len(results)} checks passed[/bold yellow]")
        console.print("[bold yellow]Some issues need to be addressed before Phase 6.3[/bold yellow]")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

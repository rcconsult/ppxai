#!/usr/bin/env python3
"""
Phase 6.3 Bootstrap Context Loading Validation Script

Tests that bootstrap context is properly loaded and displayed in the TUI.

Usage:
    uv run python scripts/validate_tui_bootstrap.py

"""

import asyncio
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ppxai.engine import EngineClient
from ppxai.engine.bootstrap import find_bootstrap_files_by_scope, ContextScope
from ppxai.commands.factory import CommandFactory

console = Console()


def print_header(text: str):
    """Print section header."""
    console.print()
    console.print(Panel(f"[bold cyan]{text}[/bold cyan]", expand=False))
    console.print()


async def validate_bootstrap_discovery():
    """Validate bootstrap file discovery."""
    print_header("Phase 6.3.1: Bootstrap File Discovery")

    cwd = Path.cwd()
    files = find_bootstrap_files_by_scope(cwd)

    if not files:
        console.print("[yellow]⚠️  No bootstrap files found[/yellow]")
        console.print(f"[dim]Working directory: {cwd}[/dim]")
        console.print("[dim]Looking for: AGENTS.md or CLAUDE.md in:[/dim]")
        console.print("  [dim]- ~/.ppxai/ (global scope)[/dim]")
        console.print("  [dim]- {git_root}/ (project scope)[/dim]")
        console.print("  [dim]- {cwd}/ (subdir scope)[/dim]")
        return False

    console.print(f"[green]✅ Found {len(files)} bootstrap file(s):[/green]")
    for path, scope in files:
        scope_color = {
            ContextScope.GLOBAL: "blue",
            ContextScope.PROJECT: "green",
            ContextScope.SUBDIR: "yellow",
        }.get(scope, "white")

        size_kb = path.stat().st_size / 1024
        console.print(f"  [{scope_color}][{scope.value}][/{scope_color}] {path} ({size_kb:.1f} KB)")

    return True


async def validate_engine_bootstrap_loading():
    """Validate engine client bootstrap loading."""
    print_header("Phase 6.3.2: Engine Bootstrap Loading")

    # Create engine client (should auto-load bootstrap)
    engine = EngineClient()

    status = engine.get_bootstrap_status()

    if not status["loaded"]:
        console.print("[yellow]⚠️  Bootstrap context not loaded[/yellow]")
        console.print("[dim]This is normal if no bootstrap files exist[/dim]")
        return True  # Not an error, just no bootstrap files

    console.print(f"[green]✅ Bootstrap context loaded successfully[/green]")
    console.print(f"  Sources: {len(status['sources'])}")
    console.print(f"  Char count: {status['char_count']:,}")
    console.print(f"  Total size: {status['total_size']:,} bytes")
    console.print(f"  Has hints: {status['has_hints']}")

    if status['sources']:
        console.print("\n[cyan]Sources:[/cyan]")
        for src in status['sources']:
            scope = src['scope']
            path = src['path']
            size = src['size']
            console.print(f"  [{scope}] {path} ({size:,} bytes)")

    if status['provider_hints']:
        console.print(f"\n[cyan]Provider hints:[/cyan] {', '.join(status['provider_hints'])}")

    if status['model_hints']:
        console.print(f"[cyan]Model hints:[/cyan] {', '.join(status['model_hints'])}")

    return True


async def validate_context_commands():
    """Validate /context command implementations."""
    print_header("Phase 6.3.3: Context Commands")

    # Mock context for testing
    class MockEngineClient:
        def __init__(self):
            self.engine = EngineClient()

        def get_working_dir(self):
            return str(Path.cwd())

        def get_bootstrap_status(self):
            return self.engine.get_bootstrap_status()

        def get_active_hints(self):
            return self.engine.get_active_hints()

        def reload_bootstrap_context(self):
            return self.engine.reload_bootstrap_context()

        def get_context_info(self):
            return self.engine.get_context_info()

        def clear_injected_contexts(self):
            return self.engine.clear_injected_contexts()

    class MockContext:
        def __init__(self):
            self.engine_client = MockEngineClient()

    ctx = MockContext()

    # Test context commands
    commands_to_test = [
        ("context", ""),        # Default: show context usage
        ("context", "show"),    # Show bootstrap hierarchy
        ("context", "hints"),   # Show active hints
    ]

    success_count = 0
    for cmd, args in commands_to_test:
        spec = CommandFactory.get(cmd)
        if not spec:
            console.print(f"❌ [bold]/{cmd}[/bold]: Not registered in factory")
            continue

        try:
            result = spec.handler(ctx, args)
            result_type = type(result).__name__
            status = result.status.value

            # Check if result is appropriate
            if result is not None and hasattr(result, 'status'):
                console.print(f"✅ [bold]/{cmd} {args}[/bold]: {result_type} ({status})")
                success_count += 1
            else:
                console.print(f"❌ [bold]/{cmd} {args}[/bold]: Invalid result type")

        except Exception as e:
            console.print(f"❌ [bold]/{cmd} {args}[/bold]: Exception: {str(e)[:80]}")

    console.print(f"\n[bold]Success rate:[/bold] {success_count}/{len(commands_to_test)}")
    return success_count == len(commands_to_test)


async def validate_bootstrap_reload():
    """Validate bootstrap context reload functionality."""
    print_header("Phase 6.3.4: Bootstrap Reload")

    engine = EngineClient()

    # Get initial status
    status_before = engine.get_bootstrap_status()
    loaded_before = status_before["loaded"]

    # Reload bootstrap
    reload_success = engine.reload_bootstrap_context()

    # Get status after reload
    status_after = engine.get_bootstrap_status()
    loaded_after = status_after["loaded"]

    if not loaded_before and not loaded_after:
        console.print("[yellow]⚠️  No bootstrap files to reload[/yellow]")
        console.print("[dim]Create AGENTS.md or CLAUDE.md to test reload functionality[/dim]")
        return True  # Not an error

    if reload_success and loaded_after:
        console.print("[green]✅ Bootstrap context reloaded successfully[/green]")
        console.print(f"  Sources: {len(status_after['sources'])}")
        return True
    elif not loaded_before:
        console.print("[yellow]⚠️  No bootstrap context available to reload[/yellow]")
        return True
    else:
        console.print("[red]❌ Bootstrap reload failed[/red]")
        return False


async def validate_context_badge_display():
    """Validate that context badge can be added to status bar."""
    print_header("Phase 6.3.5: Context Badge Display")

    engine = EngineClient()
    status = engine.get_bootstrap_status()

    if not status["loaded"]:
        console.print("[yellow]⚠️  No bootstrap context to display[/yellow]")
        return True

    sources = status.get("sources", [])
    if sources:
        scopes = [src["scope"] for src in sources]
        scope_text = "/".join(scopes)

        console.print(f"[green]✅ Context badge data available:[/green]")
        console.print(f"  Badge text: \"Context: {scope_text}\"")
        console.print(f"  Sources: {len(sources)}")
        return True

    return False


async def main():
    """Run all validation checks."""
    console.print("[bold cyan]═" * 40)
    console.print("[bold cyan]Phase 6.3: Bootstrap Context Loading Validation[/bold cyan]")
    console.print("[bold cyan]═" * 40)

    results = []

    # Run validation phases
    results.append(("Bootstrap Discovery", await validate_bootstrap_discovery()))
    results.append(("Engine Loading", await validate_engine_bootstrap_loading()))
    results.append(("Context Commands", await validate_context_commands()))
    results.append(("Bootstrap Reload", await validate_bootstrap_reload()))
    results.append(("Context Badge", await validate_context_badge_display()))

    # Summary
    print_header("Validation Summary")

    passed = 0
    for name, success in results:
        status = "[green]✅ PASS[/green]" if success else "[red]❌ FAIL[/red]"
        console.print(f"{status} - {name}")
        if success:
            passed += 1

    console.print()

    if passed == len(results):
        console.print("[bold green]🎉 All validation checks passed![/bold green]")
        console.print("[bold green]Phase 6.3 is complete and ready for Phase 6.4[/bold green]")
        return 0
    else:
        console.print(f"[bold yellow]⚠️  {passed}/{len(results)} checks passed[/bold yellow]")
        console.print("[bold yellow]Some issues need to be addressed[/bold yellow]")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

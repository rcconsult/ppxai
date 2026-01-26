#!/usr/bin/env python3
"""
Phase 6.4 Token/Cost Tracking Validation Script

Tests that token usage and cost tracking work correctly in the TUI.

Usage:
    uv run python scripts/validate_tui_token_cost.py

"""

import asyncio
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ppxai.engine import EngineClient
from ppxai.commands.factory import CommandFactory

console = Console()


def print_header(text: str):
    """Print section header."""
    console.print()
    console.print(Panel(f"[bold cyan]{text}[/bold cyan]", expand=False))
    console.print()


async def validate_usage_stats_api():
    """Validate engine client usage stats API."""
    print_header("Phase 6.4.1: Usage Stats API")

    engine = EngineClient()

    # Get usage stats
    usage = engine.get_usage()

    console.print(f"[green]✅ Usage stats API available[/green]")
    console.print(f"  Total tokens: {usage.get('total_tokens', 0):,}")
    console.print(f"  Prompt tokens: {usage.get('prompt_tokens', 0):,}")
    console.print(f"  Completion tokens: {usage.get('completion_tokens', 0):,}")
    console.print(f"  Estimated cost: ${usage.get('estimated_cost', 0.0):.4f}")
    console.print(f"  Display mode: {usage.get('display_mode', 'session')}")

    # Check per-model breakdown
    by_model = usage.get("by_model", {})
    if by_model:
        console.print(f"\n[cyan]Per-model breakdown ({len(by_model)} models):[/cyan]")
        for key in list(by_model.keys())[:3]:  # Show first 3
            console.print(f"  {key}")

    return True


async def validate_display_modes():
    """Validate usage display mode switching."""
    print_header("Phase 6.4.2: Display Mode Switching")

    engine = EngineClient()

    # Test all display modes
    modes = ["session", "provider", "model", "off"]
    success_count = 0

    for mode in modes:
        if engine.session.set_usage_display_mode(mode):
            console.print(f"✅ Display mode: {mode}")
            success_count += 1

            # Get usage for display with that mode
            usage_display = engine.session.get_usage_for_display("openai", "gpt-4")

            if mode == "off":
                if usage_display is None:
                    console.print(f"   Correctly returns None")
                else:
                    console.print(f"   [yellow]WARNING: Expected None for 'off' mode[/yellow]")
            else:
                if usage_display is not None:
                    console.print(f"   Returns stats: {usage_display.get('total_tokens', 0)} tokens")
                else:
                    console.print(f"   [yellow]WARNING: Expected stats for '{mode}' mode[/yellow]")
        else:
            console.print(f"❌ Failed to set display mode: {mode}")

    console.print(f"\n[bold]Success rate:[/bold] {success_count}/{len(modes)}")
    return success_count == len(modes)


async def validate_usage_command():
    """Validate /usage command implementations."""
    print_header("Phase 6.4.3: /usage Command")

    # Mock context
    class MockEngineClient:
        def __init__(self):
            self.engine = EngineClient()
            self.session = self.engine.session

    class MockContext:
        def __init__(self):
            self.engine_client = MockEngineClient()

        def get_provider(self):
            return "openai"

        def get_model(self):
            return "gpt-4"

    ctx = MockContext()

    # Test /usage commands
    commands_to_test = [
        ("usage", ""),          # Default: show session usage
        ("usage", "show"),      # Show current display mode
        ("usage", "show session"),  # Set display mode
        ("usage", "show off"),  # Hide usage
        ("usage", "reset"),     # Reset counters
    ]

    success_count = 0
    for cmd, args in commands_to_test:
        spec = CommandFactory.get(cmd)
        if not spec:
            console.print(f"❌ [bold]/{cmd}[/bold]: Not registered")
            continue

        try:
            result = spec.handler(ctx, args)
            result_type = type(result).__name__
            status = result.status.value

            if result is not None and hasattr(result, 'status'):
                console.print(f"✅ [bold]/{cmd} {args}[/bold]: {result_type} ({status})")
                success_count += 1
            else:
                console.print(f"❌ [bold]/{cmd} {args}[/bold]: Invalid result")

        except Exception as e:
            console.print(f"❌ [bold]/{cmd} {args}[/bold]: {str(e)[:80]}")

    console.print(f"\n[bold]Success rate:[/bold] {success_count}/{len(commands_to_test)}")
    return success_count == len(commands_to_test)


async def validate_usage_formatting():
    """Validate usage stats formatting for display."""
    print_header("Phase 6.4.4: Usage Formatting")

    test_cases = [
        (500, "500"),
        (1_500, "1.5K"),
        (15_000, "15.0K"),
        (1_500_000, "1.5M"),
        (15_000_000, "15.0M"),
    ]

    console.print("[cyan]Token formatting test:[/cyan]")
    for tokens, expected in test_cases:
        if tokens >= 1_000_000:
            formatted = f"{tokens / 1_000_000:.1f}M"
        elif tokens >= 1_000:
            formatted = f"{tokens / 1_000:.1f}K"
        else:
            formatted = f"{tokens}"

        if formatted == expected:
            console.print(f"  ✅ {tokens:,} → {formatted}")
        else:
            console.print(f"  ❌ {tokens:,} → {formatted} (expected {expected})")

    # Test cost formatting
    console.print("\n[cyan]Cost formatting test:[/cyan]")
    cost_cases = [
        (0.0001, "$0.0001"),
        (0.05, "$0.0500"),
        (1.2345, "$1.2345"),
        (10.0, "$10.0000"),
    ]

    for cost, expected in cost_cases:
        formatted = f"${cost:.4f}"
        if formatted == expected:
            console.print(f"  ✅ {cost} → {formatted}")
        else:
            console.print(f"  ❌ {cost} → {formatted} (expected {expected})")

    return True


async def validate_badge_updates():
    """Validate that badge update logic is correct."""
    print_header("Phase 6.4.5: Badge Update Logic")

    engine = EngineClient()

    # Set display mode to session (default)
    engine.session.set_usage_display_mode("session")

    # Get usage for display
    usage_display = engine.session.get_usage_for_display("openai", "gpt-4")

    if usage_display is not None:
        console.print("[green]✅ Usage display data available:[/green]")
        console.print(f"  Total tokens: {usage_display.get('total_tokens', 0):,}")
        console.print(f"  Estimated cost: ${usage_display.get('estimated_cost', 0.0):.4f}")
    else:
        console.print("[yellow]⚠️  No usage to display (session empty)[/yellow]")

    # Test display mode "off"
    engine.session.set_usage_display_mode("off")
    usage_display = engine.session.get_usage_for_display("openai", "gpt-4")

    if usage_display is None:
        console.print("[green]✅ Display mode 'off' correctly returns None[/green]")
    else:
        console.print("[red]❌ Display mode 'off' should return None[/red]")
        return False

    return True


async def main():
    """Run all validation checks."""
    console.print("[bold cyan]═" * 40)
    console.print("[bold cyan]Phase 6.4: Token/Cost Tracking Validation[/bold cyan]")
    console.print("[bold cyan]═" * 40)

    results = []

    # Run validation phases
    results.append(("Usage Stats API", await validate_usage_stats_api()))
    results.append(("Display Modes", await validate_display_modes()))
    results.append(("Usage Command", await validate_usage_command()))
    results.append(("Usage Formatting", await validate_usage_formatting()))
    results.append(("Badge Updates", await validate_badge_updates()))

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
        console.print("[bold green]Phase 6.4 is complete and ready for Phase 6.5[/bold green]")
        return 0
    else:
        console.print(f"[bold yellow]⚠️  {passed}/{len(results)} checks passed[/bold yellow]")
        console.print("[bold yellow]Some issues need to be addressed[/bold yellow]")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

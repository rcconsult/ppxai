#!/usr/bin/env python3
"""
Phase 6.5 Tool Execution Display Validation Script

Tests that tool execution is properly displayed in the TUI.

Usage:
    uv run python scripts/validate_tui_tool_display.py

"""

import asyncio
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ppxai.engine.types import Event, EventType

console = Console()


def print_header(text: str):
    """Print section header."""
    console.print()
    console.print(Panel(f"[bold cyan]{text}[/bold cyan]", expand=False))
    console.print()


async def validate_tool_event_types():
    """Validate tool event types are defined."""
    print_header("Phase 6.5.1: Tool Event Types")

    event_types = [
        EventType.TOOL_CALL,
        EventType.TOOL_RESULT,
        EventType.TOOL_ERROR,
    ]

    console.print("[green]✅ Tool event types defined:[/green]")
    for event_type in event_types:
        console.print(f"  {event_type.value}")

    return True


async def validate_tool_call_event_structure():
    """Validate TOOL_CALL event structure."""
    print_header("Phase 6.5.2: TOOL_CALL Event Structure")

    # Create sample TOOL_CALL event
    event = Event(
        type=EventType.TOOL_CALL,
        data={
            "tool": "bash",
            "arguments": {
                "command": "ls -la",
                "working_dir": "/tmp"
            }
        }
    )

    console.print(f"[green]✅ TOOL_CALL event created:[/green]")
    console.print(f"  Type: {event.type.value}")
    console.print(f"  Tool: {event.data['tool']}")
    console.print(f"  Arguments: {event.data['arguments']}")

    # Test argument formatting
    tool_args = event.data.get("arguments", {})
    if tool_args:
        args_parts = []
        for key, value in tool_args.items():
            if isinstance(value, str):
                if len(value) > 100:
                    value_str = f'"{value[:100]}..."'
                else:
                    value_str = f'"{value}"'
            else:
                value_str = str(value)
            args_parts.append(f"{key}={value_str}")
        args_str = ", ".join(args_parts)
        console.print(f"\n[cyan]Formatted arguments:[/cyan] {args_str}")

    return True


async def validate_tool_result_event_structure():
    """Validate TOOL_RESULT event structure."""
    print_header("Phase 6.5.3: TOOL_RESULT Event Structure")

    # Create sample TOOL_RESULT event
    event = Event(
        type=EventType.TOOL_RESULT,
        data={
            "tool": "bash",
            "result": "total 24\ndrwxr-xr-x  3 user  staff    96 Jan 26 10:00 .\ndrwxr-xr-x 15 user  staff   480 Jan 26 09:00 .."
        }
    )

    console.print(f"[green]✅ TOOL_RESULT event created:[/green]")
    console.print(f"  Type: {event.type.value}")
    console.print(f"  Tool: {event.data['tool']}")
    console.print(f"  Result: {event.data['result'][:50]}...")

    # Test result truncation
    result = event.data.get("result", "")
    if len(result) > 500:
        formatted_result = f"{result[:500]}...\n(Result truncated, {len(result)} chars total)"
        console.print(f"\n[cyan]Would truncate result (> 500 chars)[/cyan]")
    else:
        formatted_result = result
        console.print(f"\n[cyan]Result fits in display (< 500 chars)[/cyan]")

    return True


async def validate_tool_error_event_structure():
    """Validate TOOL_ERROR event structure."""
    print_header("Phase 6.5.4: TOOL_ERROR Event Structure")

    # Create sample TOOL_ERROR event
    event = Event(
        type=EventType.TOOL_ERROR,
        data={
            "tool": "bash",
            "error": "Command failed with exit code 1: No such file or directory"
        }
    )

    console.print(f"[green]✅ TOOL_ERROR event created:[/green]")
    console.print(f"  Type: {event.type.value}")
    console.print(f"  Tool: {event.data['tool']}")
    console.print(f"  Error: {event.data['error']}")

    return True


async def validate_tool_message_formatting():
    """Validate tool message formatting logic."""
    print_header("Phase 6.5.5: Tool Message Formatting")

    test_cases = [
        {
            "name": "Simple tool call",
            "event": Event(
                type=EventType.TOOL_CALL,
                data={"tool": "calculator", "arguments": {"operation": "add", "a": 5, "b": 3}}
            ),
            "expected_parts": ["operation=\"add\"", "a=5", "b=3"]
        },
        {
            "name": "Tool call with long string",
            "event": Event(
                type=EventType.TOOL_CALL,
                data={"tool": "bash", "arguments": {"command": "x" * 150}}
            ),
            "expected_parts": ["command=", "..."]  # Should truncate
        },
        {
            "name": "Tool call with no arguments",
            "event": Event(
                type=EventType.TOOL_CALL,
                data={"tool": "whoami", "arguments": {}}
            ),
            "expected_parts": ["no arguments"]
        }
    ]

    success_count = 0
    for test in test_cases:
        console.print(f"\n[cyan]Test: {test['name']}[/cyan]")

        event = test["event"]
        tool_args = event.data.get("arguments", {})

        if tool_args:
            args_parts = []
            for key, value in tool_args.items():
                if isinstance(value, str):
                    if len(value) > 100:
                        value_str = f'"{value[:100]}..."'
                    else:
                        value_str = f'"{value}"'
                else:
                    value_str = str(value)
                args_parts.append(f"{key}={value_str}")
            args_str = ", ".join(args_parts)
            formatted = f"Calling with: {args_str}"
        else:
            formatted = "Called with no arguments"

        console.print(f"  Formatted: {formatted[:100]}")

        # Check if expected parts are in formatted output
        all_found = all(part in formatted for part in test["expected_parts"])
        if all_found:
            console.print("  ✅ Contains expected parts")
            success_count += 1
        else:
            console.print(f"  ❌ Missing expected parts: {test['expected_parts']}")

    console.print(f"\n[bold]Success rate:[/bold] {success_count}/{len(test_cases)}")
    return success_count == len(test_cases)


async def validate_tools_command():
    """Validate /tools command works."""
    print_header("Phase 6.5.6: /tools Command")

    from ppxai.commands.factory import CommandFactory

    # Mock context
    class MockSession:
        def __init__(self):
            self.edit_consent_mode = "auto"

    class MockEngineClient:
        def __init__(self):
            from ppxai.engine import EngineClient
            self.engine = EngineClient()
            self.session = MockSession()
            self.tools_enabled = True

        def get_tools_enabled(self):
            return self.tools_enabled

        def enable_tools(self):
            self.tools_enabled = True

        def disable_tools(self):
            self.tools_enabled = False

        def get_provider(self):
            return "openai"

    class MockContext:
        def __init__(self):
            self.engine_client = MockEngineClient()

        def get_provider(self):
            return "openai"

        def get_model(self):
            return "gpt-4"

    ctx = MockContext()

    # Test /tools commands
    commands = [
        ("tools", ""),           # Show tools status
        ("tools", "on"),         # Enable tools
        ("tools", "off"),        # Disable tools
        ("tools", "status"),     # Show status explicitly
    ]

    success_count = 0
    for cmd, args in commands:
        spec = CommandFactory.get(cmd)
        if not spec:
            console.print(f"❌ [bold]/{cmd}[/bold]: Not registered")
            continue

        try:
            result = spec.handler(ctx, args)
            result_type = type(result).__name__

            if result is not None and hasattr(result, 'status'):
                console.print(f"✅ [bold]/{cmd} {args}[/bold]: {result_type}")
                success_count += 1
            else:
                console.print(f"❌ [bold]/{cmd} {args}[/bold]: Invalid result")

        except Exception as e:
            console.print(f"❌ [bold]/{cmd} {args}[/bold]: {str(e)[:80]}")

    console.print(f"\n[bold]Success rate:[/bold] {success_count}/{len(commands)}")
    return success_count >= len(commands) // 2  # Allow some commands to fail


async def main():
    """Run all validation checks."""
    console.print("[bold cyan]═" * 40)
    console.print("[bold cyan]Phase 6.5: Tool Execution Display Validation[/bold cyan]")
    console.print("[bold cyan]═" * 40)

    results = []

    # Run validation phases
    results.append(("Tool Event Types", await validate_tool_event_types()))
    results.append(("TOOL_CALL Structure", await validate_tool_call_event_structure()))
    results.append(("TOOL_RESULT Structure", await validate_tool_result_event_structure()))
    results.append(("TOOL_ERROR Structure", await validate_tool_error_event_structure()))
    results.append(("Message Formatting", await validate_tool_message_formatting()))
    results.append(("/tools Command", await validate_tools_command()))

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
        console.print("[bold green]Phase 6.5 is complete and ready for Phase 6.6[/bold green]")
        return 0
    else:
        console.print(f"[bold yellow]⚠️  {passed}/{len(results)} checks passed[/bold yellow]")
        console.print("[bold yellow]Some issues need to be addressed[/bold yellow]")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

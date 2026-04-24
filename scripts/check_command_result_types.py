#!/usr/bin/env python3
"""
Check Command Result Types

Verifies that all command handlers return appropriate result types
and that tests accept all possible result types.

Usage:
    uv run python scripts/check_command_result_types.py

"""

import sys
import ast
from pathlib import Path
from typing import Dict, Set, List, Tuple
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def extract_return_types_from_file(filepath: Path) -> Dict[str, Set[str]]:
    """Extract return statement result types from command handlers."""
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except Exception as e:
        console.print(f"[red]Error parsing {filepath}: {e}[/red]")
        return {}

    function_returns = {}

    class ReturnVisitor(ast.NodeVisitor):
        def __init__(self):
            self.current_function = None
            self.returns = {}

        def visit_FunctionDef(self, node):
            # Track function name
            old_function = self.current_function
            self.current_function = node.name
            self.returns[node.name] = set()

            # Visit function body
            self.generic_visit(node)

            # Restore previous function
            self.current_function = old_function

        def visit_Return(self, node):
            if self.current_function and node.value:
                # Try to extract result type
                if isinstance(node.value, ast.Call):
                    if isinstance(node.value.func, ast.Name):
                        result_type = node.value.func.id
                        self.returns[self.current_function].add(result_type)
                elif isinstance(node.value, ast.Name):
                    # Variable return - can't determine type easily
                    self.returns[self.current_function].add("Variable")

            self.generic_visit(node)

    visitor = ReturnVisitor()
    visitor.visit(tree)

    return visitor.returns


def extract_test_expectations(test_file: Path) -> Dict[str, Set[str]]:
    """Extract expected result types from test assertions."""
    try:
        content = test_file.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except Exception as e:
        console.print(f"[red]Error parsing {test_file}: {e}[/red]")
        return {}

    test_expectations = {}

    class AssertVisitor(ast.NodeVisitor):
        def __init__(self):
            self.current_test = None
            self.expectations = {}

        def visit_FunctionDef(self, node):
            if node.name.startswith('test_'):
                old_test = self.current_test
                self.current_test = node.name
                self.expectations[node.name] = set()

                self.generic_visit(node)

                self.current_test = old_test

        def visit_Call(self, node):
            # Look for isinstance calls in assert statements
            if isinstance(node.func, ast.Name) and node.func.id == 'isinstance':
                if len(node.args) >= 2:
                    # Second argument is the type(s)
                    type_arg = node.args[1]

                    if isinstance(type_arg, ast.Tuple):
                        # Multiple types: isinstance(x, (TypeA, TypeB))
                        for elt in type_arg.elts:
                            if isinstance(elt, ast.Name):
                                if self.current_test:
                                    self.expectations[self.current_test].add(elt.id)
                    elif isinstance(type_arg, ast.Name):
                        # Single type: isinstance(x, TypeA)
                        if self.current_test:
                            self.expectations[self.current_test].add(type_arg.id)

            self.generic_visit(node)

    visitor = AssertVisitor()
    visitor.visit(tree)

    return visitor.expectations


def main():
    """Check all command result types."""
    console.print(Panel("[bold cyan]Command Result Type Verification[/bold cyan]", expand=False))
    console.print()

    # Find all command handler files
    commands_dir = Path("ppxai/commands")
    command_files = list(commands_dir.glob("*.py"))

    # Collect all return types from command handlers
    console.print("[cyan]Analyzing command handlers...[/cyan]")
    all_handlers = {}

    for cmd_file in command_files:
        if cmd_file.name == "__init__.py" or cmd_file.name == "factory.py":
            continue

        returns = extract_return_types_from_file(cmd_file)

        # Filter to handler functions (handle_*)
        handlers = {k: v for k, v in returns.items() if k.startswith('handle_')}

        if handlers:
            all_handlers[cmd_file.stem] = handlers

    # Create summary table
    table = Table(title="Command Handler Return Types", show_lines=True)
    table.add_column("File", style="cyan")
    table.add_column("Handler", style="yellow")
    table.add_column("Return Types", style="green")

    total_handlers = 0
    result_types_used = set()

    for file_name, handlers in sorted(all_handlers.items()):
        for handler_name, return_types in sorted(handlers.items()):
            total_handlers += 1
            types_str = ", ".join(sorted(return_types)) if return_types else "[dim]Unknown[/dim]"
            result_types_used.update(return_types)
            table.add_row(file_name, handler_name, types_str)

    console.print(table)
    console.print()
    console.print(f"[bold]Total handlers analyzed:[/bold] {total_handlers}")
    console.print(f"[bold]Unique result types:[/bold] {len(result_types_used)}")
    console.print(f"[bold]Types found:[/bold] {', '.join(sorted(result_types_used))}")
    console.print()

    # Check test file
    console.print("[cyan]Analyzing test expectations...[/cyan]")
    test_file = Path("tests/test_tui_command_factory.py")

    if test_file.exists():
        expectations = extract_test_expectations(test_file)

        # Create test expectations table
        test_table = Table(title="Test Expected Result Types", show_lines=True)
        test_table.add_column("Test Function", style="cyan")
        test_table.add_column("Expected Types", style="yellow")

        for test_name, types in sorted(expectations.items()):
            if types:
                types_str = ", ".join(sorted(types))
                test_table.add_row(test_name, types_str)

        console.print(test_table)
        console.print()

    # Check for potential mismatches
    console.print("[bold cyan]Potential Issues:[/bold cyan]")
    console.print()

    issues_found = False

    # Common result types that should be accepted
    standard_result_types = {
        'TextResult', 'ErrorResult', 'ConfirmationResult',
        'ListResult', 'KeyValueResult', 'TableResult',
        'NotificationResult', 'FileViewResult', 'TreeResult'
    }

    # Check if any handlers return types not in standard set
    non_standard = result_types_used - standard_result_types - {'Variable', 'None'}

    if non_standard:
        console.print("[yellow]⚠️  Non-standard result types found:[/yellow]")
        for rtype in sorted(non_standard):
            console.print(f"  - {rtype}")
        console.print()
        issues_found = True

    # Recommendations
    console.print("[bold cyan]Recommendations:[/bold cyan]")
    console.print()

    console.print("1. [green]Standard result types (use these):[/green]")
    for rtype in sorted(standard_result_types):
        console.print(f"   - {rtype}")
    console.print()

    console.print("2. [yellow]Test expectations should include all possible types:[/yellow]")
    console.print("   Example: assert isinstance(result, (TextResult, ErrorResult, ConfirmationResult))")
    console.print()

    console.print("3. [cyan]Commands that can fail should always include ErrorResult:[/cyan]")
    console.print("   Example: handle_cd should accept ErrorResult for invalid paths")
    console.print()

    if not issues_found:
        console.print("[bold green]✅ No obvious issues found![/bold green]")
        console.print()
        return 0
    else:
        console.print("[bold yellow]⚠️  Review recommendations above[/bold yellow]")
        console.print()
        return 1


if __name__ == "__main__":
    sys.exit(main())

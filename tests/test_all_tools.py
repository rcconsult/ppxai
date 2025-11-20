#!/usr/bin/env python3
"""
Test all built-in tools with Perplexity
"""

import asyncio
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from perplexity_tools_prompt_based import PerplexityClientPromptTools

console = Console()

async def test_tool(client, name, prompt):
    """Test a specific tool."""
    console.print(f"\n{'='*70}")
    console.print(Panel(f"[bold cyan]Testing: {name}[/bold cyan]", border_style="cyan"))
    console.print(f"[yellow]Prompt:[/yellow] {prompt}\n")

    await client.chat_with_tools(prompt, model='sonar-pro')

async def main():
    load_dotenv()
    api_key = os.getenv('PERPLEXITY_API_KEY')

    if not api_key:
        console.print("[red]Error: PERPLEXITY_API_KEY not set[/red]")
        return

    console.print(Panel.fit(
        "[bold cyan]Testing All Built-in Tools[/bold cyan]\n\n"
        "This will test each tool to verify they work with Perplexity",
        border_style="cyan"
    ))

    client = PerplexityClientPromptTools(
        api_key=api_key,
        enable_tools=True
    )

    await client.initialize_tools()

    # Test 1: Calculator
    await test_tool(
        client,
        "Calculator Tool",
        "Use the calculator tool to compute (123 + 456) * 2"
    )

    # Test 2: Search Files
    await test_tool(
        client,
        "Search Files Tool",
        "Use the search_files tool to find all Python files (*.py) in the current directory"
    )

    # Test 3: List Directory
    await test_tool(
        client,
        "List Directory Tool",
        "Use the list_directory tool to show me what files are in the current directory"
    )

    # Test 4: Read File (using a file we know exists)
    await test_tool(
        client,
        "Read File Tool",
        "Use the read_file tool to read the first 20 lines of README.md if it exists"
    )

    await client.cleanup()

    console.print("\n" + "="*70)
    console.print("[bold green]✓ All tests completed![/bold green]")
    console.print("="*70)

if __name__ == "__main__":
    asyncio.run(main())

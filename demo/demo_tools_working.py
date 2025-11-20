#!/usr/bin/env python3
"""
Working Demo: Prompt-Based Tools for Perplexity

Since Perplexity doesn't support OpenAI function calling,
this demo uses prompt engineering instead.
"""

import asyncio
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from perplexity_tools_prompt_based import PerplexityClientPromptTools

console = Console()


async def demo_basic():
    """Demo basic tool usage."""
    console.print(Panel.fit(
        "[bold cyan]Demo: Prompt-Based Tools[/bold cyan]\n\n" +
        "This works with Perplexity by using prompt engineering\n" +
        "instead of native function calling.",
        border_style="cyan"
    ))

    load_dotenv()
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        console.print("[red]Error: PERPLEXITY_API_KEY not set[/red]")
        return

    client = PerplexityClientPromptTools(
        api_key=api_key,
        enable_tools=True
    )

    # Initialize tools (skip MCP for simplicity)
    await client.initialize_tools(mcp_servers=[])

    # Test 1: File search
    console.print("\n" + "="*70)
    console.print("[bold green]Test 1: File Search[/bold green]")
    console.print("="*70 + "\n")

    await client.chat_with_tools(
        "Please use the search_files tool to find all Python files in the current directory. "
        "Be sure to use the tool by responding with a JSON code block.",
        model="sonar-pro"
    )

    # Test 2: Calculator
    console.print("\n" + "="*70)
    console.print("[bold green]Test 2: Calculator[/bold green]")
    console.print("="*70 + "\n")

    await client.chat_with_tools(
        "Use the calculator tool to compute 1234 * 5678. "
        "Respond with a JSON code block to use the tool.",
        model="sonar-pro"
    )

    # Test 3: Directory listing
    console.print("\n" + "="*70)
    console.print("[bold green]Test 3: List Directory[/bold green]")
    console.print("="*70 + "\n")

    await client.chat_with_tools(
        "Use the list_directory tool to show me what's in the current directory.",
        model="sonar-pro"
    )

    await client.cleanup()


async def demo_multi_step():
    """Demo multi-step tool usage."""
    console.print("\n\n" + "="*70)
    console.print(Panel.fit(
        "[bold cyan]Demo: Multi-Step Tool Usage[/bold cyan]\n\n" +
        "Asking the model to use multiple tools in sequence.",
        border_style="cyan"
    ))

    load_dotenv()
    api_key = os.getenv("PERPLEXITY_API_KEY")

    client = PerplexityClientPromptTools(
        api_key=api_key,
        enable_tools=True
    )

    await client.initialize_tools(mcp_servers=[])

    console.print("\n[bold green]Multi-step task:[/bold green]")
    console.print("[dim]The model should use search_files, then calculator[/dim]\n")

    await client.chat_with_tools(
        "First, use the search_files tool to find all Python files. "
        "Then, use the calculator tool to multiply the number of files found by 10. "
        "Use JSON code blocks to invoke the tools.",
        model="sonar-pro",
        max_iterations=10  # Allow more iterations for multi-step
    )

    await client.cleanup()


async def main():
    """Run demos."""
    console.print(Panel(
        Markdown("""
# Working Tool Demo for Perplexity

This demonstrates **prompt-based tool usage** that works with Perplexity:

**Why this approach?**
- Perplexity doesn't support OpenAI function calling (yet)
- Instead, we use prompt engineering
- Model responds with JSON to invoke tools
- We parse and execute, then continue conversation

**How it works:**
1. Tools described in system prompt
2. Model responds with: `{"tool": "name", "arguments": {...}}`
3. We execute the tool
4. Result added to conversation
5. Model continues with final answer

Press Ctrl+C to exit.
        """),
        title="Welcome",
        border_style="cyan"
    ))

    try:
        await demo_basic()

        console.print("\n[dim]Press Enter to continue to multi-step demo...[/dim]")
        input()

        await demo_multi_step()

    except KeyboardInterrupt:
        console.print("\n[yellow]Demo interrupted[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")

    console.print("\n\n" + "="*70)
    console.print("[bold green]Demo completed![/bold green]")
    console.print("="*70)
    console.print("\n[cyan]Summary:[/cyan]")
    console.print("• Prompt-based tools work with any LLM (no native support needed)")
    console.print("• Model learns to use JSON format from instructions")
    console.print("• Flexible and portable across different APIs")
    console.print("• Trade-off: Less reliable than native function calling")
    console.print("\n[dim]For APIs with native function calling support, use perplexity_with_tools.py instead[/dim]\n")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Manual test script to verify prompt-based tools work with Perplexity

This is not a pytest test - it's a manual testing script.
Run directly with: python tests/test_prompt_tools.py
"""

import asyncio
import os
from dotenv import load_dotenv
from rich.console import Console
from perplexity_tools_prompt_based import PerplexityClientPromptTools

console = Console()

async def manual_test():
    load_dotenv()
    api_key = os.getenv('PERPLEXITY_API_KEY')

    if not api_key:
        console.print("[red]Error: PERPLEXITY_API_KEY not set[/red]")
        return

    console.print("[cyan]Testing prompt-based tools with Perplexity...[/cyan]\n")

    client = PerplexityClientPromptTools(
        api_key=api_key,
        enable_tools=True
    )

    await client.initialize_tools()

    console.print("[yellow]Test: Asking model to use calculator tool[/yellow]")
    console.print("[dim]This will show if Perplexity responds with JSON format[/dim]\n")

    # Explicitly ask it to use a tool with clear instructions
    await client.chat_with_tools(
        'Please use the calculator tool to compute 42 * 58. '
        'You must respond with a JSON code block in this exact format:\n'
        '```json\n{"tool": "calculator", "arguments": {"expression": "42 * 58"}}\n```',
        model='sonar-pro'
    )

    await client.cleanup()

if __name__ == "__main__":
    asyncio.run(manual_test())

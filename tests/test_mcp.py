#!/usr/bin/env python3
"""
MCP Diagnostics - Test if MCP servers can work on your system

This script checks:
1. Is MCP library installed?
2. Is Node.js available?
3. Can we start an MCP server?
4. Can we list tools from the server?
"""

import asyncio
import subprocess
import sys
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def check_python_mcp():
    """Check if MCP library is installed."""
    try:
        import mcp
        version = getattr(mcp, '__version__', 'unknown')
        console.print(f"[green]✓[/green] MCP library installed (version: {version})")
        return True
    except ImportError:
        console.print("[red]✗[/red] MCP library not installed")
        console.print("  [yellow]Install with:[/yellow] pip install mcp")
        return False


def check_nodejs():
    """Check if Node.js is available."""
    try:
        result = subprocess.run(
            ['node', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            console.print(f"[green]✓[/green] Node.js installed ({version})")
            return True
        else:
            console.print("[red]✗[/red] Node.js command failed")
            return False
    except FileNotFoundError:
        console.print("[red]✗[/red] Node.js not found")
        console.print("  [yellow]Install from:[/yellow] https://nodejs.org")
        return False
    except subprocess.TimeoutExpired:
        console.print("[red]✗[/red] Node.js check timed out")
        return False


def check_npx():
    """Check if npx is available."""
    try:
        result = subprocess.run(
            ['npx', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            console.print(f"[green]✓[/green] npx available ({version})")
            return True
        else:
            console.print("[red]✗[/red] npx command failed")
            return False
    except FileNotFoundError:
        console.print("[red]✗[/red] npx not found (should come with Node.js)")
        return False
    except subprocess.TimeoutExpired:
        console.print("[red]✗[/red] npx check timed out")
        return False


async def manual_test_mcp_server():
    """Test starting a simple MCP server."""
    console.print("\n[bold]Testing MCP Server Connection[/bold]")
    console.print("Attempting to start @modelcontextprotocol/server-filesystem...")

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        )

        console.print("  [dim]Starting server...[/dim]")

        # Use timeout for the entire operation
        async with asyncio.timeout(30):
            context = stdio_client(server_params)
            read, write = await context.__aenter__()

            try:
                console.print("  [dim]Creating session...[/dim]")
                session = ClientSession(read, write)
                await session.initialize()

                console.print("  [dim]Listing tools...[/dim]")
                tools_result = await session.list_tools()

                console.print(f"[green]✓[/green] MCP server works! Found {len(tools_result.tools)} tools:")
                for tool in tools_result.tools[:5]:  # Show first 5
                    console.print(f"    • {tool.name}: {tool.description or 'No description'}")
                if len(tools_result.tools) > 5:
                    console.print(f"    ... and {len(tools_result.tools) - 5} more")

                # Clean up
                await context.__aexit__(None, None, None)
                return True

            except Exception as e:
                console.print(f"[red]✗[/red] Error during MCP operations: {e}")
                await context.__aexit__(None, None, None)
                return False

    except asyncio.TimeoutError:
        console.print("[red]✗[/red] MCP server connection timed out (30s)")
        console.print("  [yellow]This might mean:[/yellow]")
        console.print("    - Server is slow to start")
        console.print("    - Network issues downloading package")
        console.print("    - Server crashed on startup")
        return False
    except ImportError:
        console.print("[red]✗[/red] MCP library not available")
        return False
    except Exception as e:
        console.print(f"[red]✗[/red] Unexpected error: {e}")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return False


async def main():
    """Run all diagnostics."""
    console.print(Panel.fit(
        "[bold cyan]MCP Diagnostics Tool[/bold cyan]\n\n"
        "This will check if MCP servers can run on your system.",
        border_style="cyan"
    ))

    # Create results table
    results = {
        "Python MCP Library": False,
        "Node.js": False,
        "npx": False,
        "MCP Server": False
    }

    console.print("\n[bold]Step 1: Checking Dependencies[/bold]\n")

    # Check Python MCP
    results["Python MCP Library"] = check_python_mcp()

    # Check Node.js
    results["Node.js"] = check_nodejs()

    # Check npx
    if results["Node.js"]:
        results["npx"] = check_npx()

    # Test MCP server only if all dependencies are available
    if all([results["Python MCP Library"], results["Node.js"], results["npx"]]):
        console.print("\n[bold]Step 2: Testing MCP Server[/bold]\n")
        results["MCP Server"] = await manual_test_mcp_server()
    else:
        console.print("\n[yellow]Skipping MCP server test (missing dependencies)[/yellow]")

    # Summary
    console.print("\n" + "="*70)
    console.print("[bold]Summary[/bold]\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="white")

    for component, status in results.items():
        status_text = "[green]✓ Working[/green]" if status else "[red]✗ Not Working[/red]"
        table.add_row(component, status_text)

    console.print(table)

    # Recommendations
    console.print("\n[bold]Recommendations:[/bold]\n")

    if not results["Python MCP Library"]:
        console.print("1. Install MCP library:")
        console.print("   [cyan]pip install mcp[/cyan]\n")

    if not results["Node.js"]:
        console.print("2. Install Node.js (v16 or higher):")
        console.print("   [cyan]https://nodejs.org[/cyan]")
        console.print("   Or via Homebrew: [cyan]brew install node[/cyan]\n")

    if all([results["Python MCP Library"], results["Node.js"], results["npx"]]) and not results["MCP Server"]:
        console.print("3. MCP server failed to start. This could be due to:")
        console.print("   • Network issues (check your internet connection)")
        console.print("   • Firewall blocking npm/npx")
        console.print("   • Insufficient permissions")
        console.print("   • Try manually: [cyan]npx -y @modelcontextprotocol/server-filesystem /tmp[/cyan]\n")

    if all(results.values()):
        console.print("[green]✓ All checks passed! MCP servers should work.[/green]\n")
        console.print("You can now use MCP servers in ppxai.")
    else:
        console.print("[yellow]⚠ Some checks failed. MCP servers may not work.[/yellow]\n")
        console.print("[bold]Alternative:[/bold] You can still use built-in Python tools without MCP!")
        console.print("Built-in tools don't require Node.js or MCP servers.\n")

    console.print("="*70)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Diagnostics interrupted[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Unexpected error: {e}[/red]")
        import traceback
        traceback.print_exc()

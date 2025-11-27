"""
Utility functions for the ppxai application.
"""

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Prompt

# Initialize Rich console
console = Console()


def read_file_content(filepath: str) -> Optional[str]:
    """Read and return file content, handling errors gracefully."""
    try:
        path = Path(filepath).expanduser().resolve()
        if not path.exists():
            console.print(f"[red]Error: File not found: {filepath}[/red]")
            return None

        if not path.is_file():
            console.print(f"[red]Error: Not a file: {filepath}[/red]")
            return None

        # Check file size (limit to 100KB for safety)
        if path.stat().st_size > 100 * 1024:
            console.print(f"[yellow]Warning: File is large ({path.stat().st_size // 1024}KB). This may use many tokens.[/yellow]")
            response = Prompt.ask("Continue?", choices=["y", "n"], default="n")
            if response.lower() != "y":
                return None

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        return content
    except UnicodeDecodeError:
        console.print(f"[red]Error: File is not a text file or has encoding issues: {filepath}[/red]")
        return None
    except Exception as e:
        console.print(f"[red]Error reading file: {e}[/red]")
        return None

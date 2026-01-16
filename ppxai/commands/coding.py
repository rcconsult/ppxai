"""
Coding commands - code generation, testing, documentation, and analysis.

Commands for AI-assisted coding tasks including generation, testing,
documentation, debugging, explanation, and language conversion.

v1.13.10: Migrated to Command Factory pattern
"""

import os
from typing import TYPE_CHECKING

from .factory import CommandFactory, CommandSpec

if TYPE_CHECKING:
    from .handler import CommandHandler


def handle_generate(handler: "CommandHandler", args: str) -> None:
    """Handle /generate command - generate code from description.

    Args:
        handler: CommandHandler instance providing context
        args: Description of code to generate
    """
    from ..ui import console
    from .handler import send_coding_task

    if not args:
        console.print("[red]Please provide a description: /generate <description>[/red]")
        console.print("[yellow]Example: /generate a function to validate email addresses in Python[/yellow]\n")
        return

    console.print(f"\n[cyan]Generating code for:[/cyan] {args}\n")
    send_coding_task(handler, "generate", args, handler.current_model, handler.provider)


def handle_test(handler: "CommandHandler", args: str) -> None:
    """Handle /test command - generate unit tests for code.

    Args:
        handler: CommandHandler instance providing context
        args: File path to generate tests for
    """
    from ..ui import console
    from ..utils import read_file_content
    from .handler import send_coding_task

    if not args:
        console.print("[red]Please provide a file path: /test <file>[/red]")
        console.print("[yellow]Example: /test ./src/utils.py[/yellow]\n")
        return

    file_content = read_file_content(args.strip())
    if file_content:
        console.print(f"\n[cyan]Generating tests for:[/cyan] {args}\n")
        task_message = f"Generate comprehensive unit tests for the following code:\n\n```\n{file_content}\n```"
        send_coding_task(handler, "test", task_message, handler.current_model, handler.provider)


def handle_docs(handler: "CommandHandler", args: str) -> None:
    """Handle /docs command - generate documentation for code.

    Args:
        handler: CommandHandler instance providing context
        args: File path to generate documentation for
    """
    from ..ui import console
    from ..utils import read_file_content
    from .handler import send_coding_task

    if not args:
        console.print("[red]Please provide a file path: /docs <file>[/red]")
        console.print("[yellow]Example: /docs ./src/api.py[/yellow]\n")
        return

    file_content = read_file_content(args.strip())
    if file_content:
        console.print(f"\n[cyan]Generating documentation for:[/cyan] {args}\n")
        task_message = f"Generate comprehensive documentation for the following code:\n\n```\n{file_content}\n```"
        send_coding_task(handler, "docs", task_message, handler.current_model, handler.provider)


def handle_implement(handler: "CommandHandler", args: str) -> None:
    """Handle /implement command - implement feature from specification.

    Args:
        handler: CommandHandler instance providing context
        args: Feature specification to implement
    """
    from ..ui import console
    from .handler import send_coding_task

    if not args:
        console.print("[red]Please provide a feature specification: /implement <specification>[/red]")
        console.print("[yellow]Example: /implement a REST API endpoint for user authentication[/yellow]")
        console.print("[cyan]Tip: Use /spec to see specification guidelines and templates[/cyan]\n")
        return

    console.print(f"\n[cyan]Implementing feature:[/cyan] {args}\n")
    send_coding_task(handler, "implement", args, handler.current_model, handler.provider)


def handle_debug(handler: "CommandHandler", args: str) -> None:
    """Handle /debug command - analyze and debug error.

    Args:
        handler: CommandHandler instance providing context
        args: Error message or stack trace to debug
    """
    from ..ui import console
    from .handler import send_coding_task

    if not args:
        console.print("[red]Please provide error details or paste your error message/stack trace[/red]")
        console.print("[yellow]Example: /debug TypeError: 'NoneType' object is not subscriptable at line 42[/yellow]\n")
        return

    console.print(f"\n[cyan]Analyzing error:[/cyan] {args[:100]}...\n")
    send_coding_task(handler, "debug", args, handler.current_model, handler.provider)


def handle_explain(handler: "CommandHandler", args: str) -> None:
    """Handle /explain command - explain code in detail.

    Args:
        handler: CommandHandler instance providing context
        args: File path to explain
    """
    from ..ui import console
    from ..utils import read_file_content
    from .handler import send_coding_task

    if not args:
        console.print("[red]Please provide a file path: /explain <file>[/red]")
        console.print("[yellow]Example: /explain ./src/algorithm.py[/yellow]\n")
        return

    file_content = read_file_content(args.strip())
    if file_content:
        console.print(f"\n[cyan]Explaining code:[/cyan] {args}\n")
        task_message = f"Explain the following code in detail, including logic, design decisions, and how it works:\n\n```\n{file_content}\n```"
        send_coding_task(handler, "explain", task_message, handler.current_model, handler.provider)


def handle_convert(handler: "CommandHandler", args: str) -> None:
    """Handle /convert command - convert code between languages.

    Args:
        handler: CommandHandler instance providing context
        args: Format: <source-lang> <target-lang> <file-or-code>
    """
    from ..ui import console
    from ..utils import read_file_content
    from .handler import send_coding_task

    if not args:
        console.print("[red]Please provide: /convert <source-lang> <target-lang> <file-or-code>[/red]")
        console.print("[yellow]Example: /convert python javascript ./utils.py[/yellow]")
        console.print("[yellow]Example: /convert go rust 'func hello() { fmt.Println(\"Hi\") }'[/yellow]\n")
        return

    parts = args.split(maxsplit=2)
    if len(parts) < 3:
        console.print("[red]Invalid format. Use: /convert <source-lang> <target-lang> <file-or-code>[/red]\n")
        return

    source_lang, target_lang, code_or_file = parts

    # Check if it's a file or inline code
    if os.path.exists(code_or_file.strip('\'"')):
        file_content = read_file_content(code_or_file.strip('\'"'))
        if not file_content:
            return
        code_to_convert = file_content
    else:
        code_to_convert = code_or_file.strip('\'"')

    console.print(f"\n[cyan]Converting from {source_lang} to {target_lang}[/cyan]\n")
    task_message = f"Convert the following {source_lang} code to {target_lang}:\n\n```{source_lang}\n{code_to_convert}\n```"
    send_coding_task(handler, "convert", task_message, handler.current_model, handler.provider)


# =============================================================================
# Command Registration
# =============================================================================

CommandFactory.register(CommandSpec(
    name="generate",
    description="Generate code from description",
    handler=handle_generate,
    category="coding",
    aliases=["gen", "g"],
    usage="/generate <description>"
))

CommandFactory.register(CommandSpec(
    name="test",
    description="Generate unit tests for code",
    handler=handle_test,
    category="coding",
    aliases=["t"],
    usage="/test <file>"
))

CommandFactory.register(CommandSpec(
    name="docs",
    description="Generate documentation for code",
    handler=handle_docs,
    category="coding",
    aliases=["d"],
    usage="/docs <file>"
))

CommandFactory.register(CommandSpec(
    name="implement",
    description="Implement feature from specification",
    handler=handle_implement,
    category="coding",
    aliases=["impl"],
    usage="/implement <specification>"
))

CommandFactory.register(CommandSpec(
    name="debug",
    description="Analyze and debug error",
    handler=handle_debug,
    category="coding",
    usage="/debug <error-details>"
))

CommandFactory.register(CommandSpec(
    name="explain",
    description="Explain code in detail",
    handler=handle_explain,
    category="coding",
    usage="/explain <file>"
))

CommandFactory.register(CommandSpec(
    name="convert",
    description="Convert code between languages",
    handler=handle_convert,
    category="coding",
    usage="/convert <source-lang> <target-lang> <file-or-code>"
))

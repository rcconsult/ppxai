"""
Coding commands - code generation, testing, documentation, and analysis.

Commands for AI-assisted coding tasks including generation, testing,
documentation, debugging, explanation, and language conversion.

v1.13.10: Migrated to Command Factory pattern
v1.15.0: Migrated to type-based renderer dispatch
"""

import asyncio
import os
import re
from concurrent.futures import ThreadPoolExecutor

from ..common.async_compat import is_event_loop_running
from ..config import get_coding_model
from ..engine.types import EventType
from ..rich.ui import console
from ..rich.utils import read_file_content
from .factory import CommandFactory, CommandSpec
from .handler import CODING_PROMPTS
from .protocol import CommandContext
from .results import (
    AIResponseResult,
    CommandResult,
    ErrorResult,
    ResultStatus,
)

# =============================================================================
# Type-Based Result Handlers (v1.15.0)
# =============================================================================

def _execute_ai_task(context: CommandContext, task_type: str, user_message: str, initial_message: str) -> CommandResult:
    """Execute AI coding task with streaming and return AIResponseResult.

    Helper function for all AI coding commands. Streams response in real-time
    (preserving UX) while accumulating content for final result.

    This function works in both sync (Rich TUI) and async (Textual TUI) contexts
    by detecting the event loop state and adapting accordingly.

    Args:
        context: Command context providing access to engine client
        task_type: Type of coding task (generate, test, docs, etc.)
        user_message: The prepared message to send to LLM
        initial_message: Message to display before streaming

    Returns:
        AIResponseResult with complete content and extracted code blocks
    """
    if not context.engine_client:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Engine client not available"
        )

    if task_type not in CODING_PROMPTS:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Unknown task type: {task_type}"
        )

    # Auto-route to coding model if enabled
    provider = context.get_provider()
    model = context.get_model()
    coding_model = get_coding_model(provider)

    auto_routed = False
    if context.get_auto_route() and model != coding_model:
        model = coding_model
        auto_routed = True

    # Prepare system prompt + user message
    system_prompt = CODING_PROMPTS[task_type]
    full_message = f"{system_prompt}\n\n{user_message}"

    # Show initial message
    console.print(initial_message)

    async def run_task():
        """Stream response and accumulate content."""
        content = ""
        original_model = context.engine_client.model

        # Temporarily switch model if auto-routed
        if model != original_model:
            context.engine_client.set_model(model, reset_context=False)

        try:
            async for event in context.engine_client.chat(full_message, stream=True):
                if event.type == EventType.STREAM_CHUNK:
                    chunk = event.data
                    console.print(chunk, end="")  # Stream for UX
                    content += chunk
                elif event.type == EventType.ERROR:
                    console.print(f"\n[red]Error: {event.data}[/red]")
                    return None, str(event.data)
        finally:
            # Restore original model
            if model != original_model:
                context.engine_client.set_model(original_model, reset_context=False)

        console.print()  # New line after streaming
        return content, None

    # Execute async task - handle both sync and async contexts
    if is_event_loop_running():
        # Textual TUI context - event loop already running
        # Run async code in separate thread with its own event loop
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: asyncio.run(run_task()))
            content, error = future.result()
    else:
        # Rich TUI context - no event loop running
        # Use asyncio.run() directly
        content, error = asyncio.run(run_task())

    if error:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="AI task failed",
            error_details=error
        )

    if not content:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="No response received from AI"
        )

    # Extract code blocks from the raw AI content (before prepending any
    # notice, so the auto-route note can't be mistaken for a code fence).
    code_blocks = []
    code_block_pattern = r'```(\w+)?\n(.*?)```'
    for match in re.finditer(code_block_pattern, content, re.DOTALL):
        language = match.group(1) or "text"
        code = match.group(2).strip()
        code_blocks.append({"language": language, "code": code})

    # Surface the auto-route notice via the result `content` so EVERY client
    # sees it. (Web/VSCode render `content` and only fall back to `message`
    # when content is empty, so `message` alone would be invisible there.)
    # Item 30: command handlers return data; they don't print to a console
    # only the Rich TUI can see.
    if auto_routed:
        content = (
            f"_Auto-routed to {coding_model} for this coding task "
            f"(disable with `/autoroute off`)._\n\n{content}"
        )

    return AIResponseResult(
        status=ResultStatus.SUCCESS,
        message=f"Completed {task_type} task",
        content=content,
        code_blocks=code_blocks
    )


def handle_generate(context: CommandContext, args: str) -> CommandResult:
    """Handle /generate command - generate code from description.

    Args:
        context: Command context providing access to engine client
        args: Description of code to generate

    Returns:
        AIResponseResult with generated code
    """
    if not args:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Please provide a description: /generate <description>",
            suggestions=["Example: /generate a function to validate email addresses in Python"]
        )

    initial_msg = f"\n[cyan]Generating code for:[/cyan] {args}\n"
    return _execute_ai_task(context, "generate", args, initial_msg)


def handle_test(context: CommandContext, args: str) -> CommandResult:
    """Handle /test command - generate unit tests for code.

    Args:
        context: Command context providing access to engine client
        args: File path to generate tests for

    Returns:
        AIResponseResult with generated tests
    """
    if not args:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Please provide a file path: /test <file>",
            suggestions=["Example: /test ./src/utils.py"]
        )

    file_content = read_file_content(args.strip())
    if not file_content:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Could not read file: {args}"
        )

    task_message = f"Generate comprehensive unit tests for the following code:\n\n```\n{file_content}\n```"
    initial_msg = f"\n[cyan]Generating tests for:[/cyan] {args}\n"
    return _execute_ai_task(context, "test", task_message, initial_msg)


def handle_docs(context: CommandContext, args: str) -> CommandResult:
    """Handle /docs command - generate documentation for code.

    Args:
        context: Command context providing access to engine client
        args: File path to generate documentation for

    Returns:
        AIResponseResult with generated documentation
    """
    if not args:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Please provide a file path: /docs <file>",
            suggestions=["Example: /docs ./src/api.py"]
        )

    file_content = read_file_content(args.strip())
    if not file_content:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Could not read file: {args}"
        )

    task_message = f"Generate comprehensive documentation for the following code:\n\n```\n{file_content}\n```"
    initial_msg = f"\n[cyan]Generating documentation for:[/cyan] {args}\n"
    return _execute_ai_task(context, "docs", task_message, initial_msg)


def handle_implement(context: CommandContext, args: str) -> CommandResult:
    """Handle /implement command - implement feature from specification.

    Args:
        context: Command context providing access to engine client
        args: Feature specification to implement

    Returns:
        AIResponseResult with implementation
    """
    if not args:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Please provide a feature specification: /implement <specification>",
            suggestions=[
                "Example: /implement a REST API endpoint for user authentication",
                "Tip: Use /spec to see specification guidelines and templates"
            ]
        )

    initial_msg = f"\n[cyan]Implementing feature:[/cyan] {args}\n"
    return _execute_ai_task(context, "implement", args, initial_msg)


def handle_debug(context: CommandContext, args: str) -> CommandResult:
    """Handle /debug command - analyze and debug error.

    Args:
        context: Command context providing access to engine client
        args: Error message or stack trace to debug

    Returns:
        AIResponseResult with debugging analysis
    """
    if not args:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Please provide error details or paste your error message/stack trace",
            suggestions=["Example: /debug TypeError: 'NoneType' object is not subscriptable at line 42"]
        )

    preview = args[:100] + "..." if len(args) > 100 else args
    initial_msg = f"\n[cyan]Analyzing error:[/cyan] {preview}\n"
    return _execute_ai_task(context, "debug", args, initial_msg)


def handle_explain(context: CommandContext, args: str) -> CommandResult:
    """Handle /explain command - explain code in detail.

    Args:
        context: Command context providing access to engine client
        args: File path to explain

    Returns:
        AIResponseResult with code explanation
    """
    if not args:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Please provide a file path: /explain <file>",
            suggestions=["Example: /explain ./src/algorithm.py"]
        )

    file_content = read_file_content(args.strip())
    if not file_content:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Could not read file: {args}"
        )

    task_message = f"Explain the following code in detail, including logic, design decisions, and how it works:\n\n```\n{file_content}\n```"
    initial_msg = f"\n[cyan]Explaining code:[/cyan] {args}\n"
    return _execute_ai_task(context, "explain", task_message, initial_msg)


def handle_convert(context: CommandContext, args: str) -> CommandResult:
    """Handle /convert command - convert code between languages.

    Args:
        context: Command context providing access to engine client
        args: Format: <source-lang> <target-lang> <file-or-code>

    Returns:
        AIResponseResult with converted code
    """
    if not args:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Please provide: /convert <source-lang> <target-lang> <file-or-code>",
            suggestions=[
                "Example: /convert python javascript ./utils.py",
                "Example: /convert go rust 'func hello() { fmt.Println(\"Hi\") }'"
            ]
        )

    parts = args.split(maxsplit=2)
    if len(parts) < 3:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Invalid format. Use: /convert <source-lang> <target-lang> <file-or-code>"
        )

    source_lang, target_lang, code_or_file = parts

    # Check if it's a file or inline code
    if os.path.exists(code_or_file.strip('\'"')):
        file_content = read_file_content(code_or_file.strip('\'"'))
        if not file_content:
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=f"Could not read file: {code_or_file}"
            )
        code_to_convert = file_content
    else:
        code_to_convert = code_or_file.strip('\'"')

    task_message = f"Convert the following {source_lang} code to {target_lang}:\n\n```{source_lang}\n{code_to_convert}\n```"
    initial_msg = f"\n[cyan]Converting from {source_lang} to {target_lang}[/cyan]\n"
    return _execute_ai_task(context, "convert", task_message, initial_msg)


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
    aliases=[],  # Removed "t" alias - conflicts with /tools
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

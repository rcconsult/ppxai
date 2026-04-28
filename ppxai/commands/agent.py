"""
Agent commands - autonomous task execution and checkpoint management.

Commands for running autonomous agent tasks and managing checkpoints/undo.

v1.13.10: Migrated to Command Factory pattern
v1.15.0: Migrated to type-based renderer dispatch
"""

import asyncio
import subprocess
from typing import Optional

from prompt_toolkit import prompt as pt_prompt

from .factory import CommandFactory, CommandSpec
from .protocol import CommandContext
from .results import (
    ResultStatus,
    CommandResult,
    AIResponseResult,
    ConfirmationResult,
    ErrorResult,
    KeyValueResult,
    NotificationResult,
    TableResult,
    TextResult,
)

from ..common.logger import get_logger
from ..rich.event_handler import TUIEventHandler
from ..rich.ui import console


def _handle_agent_interrupt(
    context,
    checkpoint_id: Optional[str],
    checkpoint_backend: Optional[str]
) -> None:
    """Handle agent interruption and offer automatic rollback.

    Args:
        context: CommandContext instance (provides engine_client)
        checkpoint_id: Checkpoint ID if one was created
        checkpoint_backend: Backend type ('git' or 'file')
    """
    console.print("[yellow]Agent task incomplete due to interrupt.[/yellow]\n")

    if not checkpoint_id:
        console.print("[dim]No checkpoint available. Any partial changes remain in place.[/dim]")
        console.print("[dim]Tip: Review changes manually and clean up as needed.[/dim]\n")
        return

    # Show current state
    console.print(f"[cyan]Checkpoint: {checkpoint_id[:8] if len(checkpoint_id) > 8 else checkpoint_id}[/cyan]")
    console.print(f"[cyan]Backend: {checkpoint_backend}[/cyan]\n")

    # Prompt for rollback
    console.print("[bold]Rollback all changes from this task?[/bold]")
    console.print("[dim]  y - Rollback to checkpoint (undo all changes)[/dim]")
    console.print("[dim]  n - Keep partial changes[/dim]\n")

    try:
        response = pt_prompt("Rollback? (y/n): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Keeping partial changes (no rollback)[/yellow]\n")
        return

    if response not in ['y', 'yes']:
        console.print("\n[yellow]Partial changes preserved[/yellow]")
        console.print("[dim]Use /undo later to rollback if needed[/dim]\n")
        return

    # Perform rollback
    console.print("\n[dim]Rolling back changes...[/dim]")
    success = context.engine_client.undo_last_checkpoint()

    if success:
        console.print("[green]✓ Checkpoint reverted successfully[/green]\n")

        # For git backend, check for uncommitted changes
        if checkpoint_backend == "git":
            try:
                result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.returncode == 0 and result.stdout.strip():
                    # Uncommitted changes detected
                    console.print("[yellow]⚠️  Uncommitted changes detected in working directory[/yellow]")
                    console.print("[dim]These are partial changes from the interrupted agent task.[/dim]\n")
                    console.print("[bold]Clean working directory?[/bold]")
                    console.print("[dim]  y - Remove all uncommitted changes (git reset --hard)[/dim]")
                    console.print("[dim]  n - Keep uncommitted changes for manual review[/dim]\n")

                    try:
                        clean_response = pt_prompt("Clean working directory? (y/n): ").strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        console.print("\n[yellow]Keeping uncommitted changes[/yellow]\n")
                        return

                    if clean_response in ['y', 'yes']:
                        console.print("\n[dim]Running git reset --hard...[/dim]")
                        reset_result = subprocess.run(
                            ["git", "reset", "--hard", "HEAD"],
                            capture_output=True,
                            text=True,
                            check=False
                        )

                        if reset_result.returncode == 0:
                            console.print("[green]✓ Working directory cleaned[/green]")

                            # Also clean untracked files
                            console.print("[dim]Removing untracked files...[/dim]")
                            subprocess.run(
                                ["git", "clean", "-fd"],
                                capture_output=True,
                                check=False
                            )
                            console.print("[green]✓ All changes removed[/green]\n")
                        else:
                            console.print(f"[red]✗ git reset failed: {reset_result.stderr}[/red]\n")
                    else:
                        console.print("\n[yellow]Uncommitted changes preserved[/yellow]")
                        console.print("[dim]Run 'git status' to see changes[/dim]")
                        console.print("[dim]Run 'git reset --hard' to clean manually[/dim]\n")
            except Exception as e:
                console.print(f"[yellow]Could not check git status: {e}[/yellow]\n")
    else:
        console.print("[red]✗ Rollback failed[/red]")
        console.print("[dim]Check logs or try /undo manually[/dim]\n")


def _build_agent_prompt(task: str, iteration: int) -> str:
    """Build initial prompt for agent."""
    return f"""Task: {task}

Work on this task autonomously. You have tools available for:
- Reading files (read_file, search_files, list_directory)
- Editing files (apply_patch, replace_block, insert_text, delete_lines)
- Running shell commands (execute_shell_command)
- Web search and fetch (if available for your provider)

Instructions:
1. Analyze the task and plan your approach
2. Use tools to gather information and make changes
3. After each action, assess progress

When the task is complete, respond with:
TASK_COMPLETE: <brief summary of what was done>

If you need to continue working, explain your progress and use the appropriate tools."""


def _build_continuation_prompt(task: str, iteration: int) -> str:
    """Build continuation prompt for subsequent iterations."""
    return f"""Continue working on the task: {task}

Review your previous work and continue toward completion.

If the task is now complete, respond with:
TASK_COMPLETE: <brief summary of what was done>

If more work is needed, explain what you're doing next and use the appropriate tools."""


# =============================================================================
# Public agent-task validation (v1.18.1)
# =============================================================================
#
# Used by:
#   - handle_agent (TUI in-process path)
#   - server-side /chat hook (web /agent <task> safety gate)
#   - VSCode chatPanel.ts via the factory dispatch (5b.2)
#
# Centralising here closes the safety gap where web users could
# previously run `/agent fix` without any min-words check (web's
# streamChat hits /chat which had no /agent awareness).


def validate_agent_task(
    task: str,
    min_words: int,
) -> Optional[CommandResult]:
    """Return a NotificationResult if the task is too vague, else None.

    The non-None return is a friendly nudge framed as a question
    (not an ErrorResult) — same content the user sees when they
    type `/agent fix` in any client. Concrete examples included so
    they know what level of detail is expected. Per the v1.18.1 UX
    decision: ask for more context, don't just bounce them.

    Args:
        task: The user's task string (already trimmed).
        min_words: Threshold from agent config (default 3).

    Returns:
        None when valid. NotificationResult(WARNING) when too vague.
    """
    words = task.split()
    if len(words) >= min_words:
        return None

    quoted = task or "(empty)"
    msg = (
        f"I need a bit more detail before running autonomously.\n\n"
        f"Your task `{quoted}` is too brief — please tell me:\n"
        f"  • **What** to do? (a bug to fix, a feature to add, an investigation)\n"
        f"  • **Where**? (which file, function, or area)\n"
        f"  • **How** will I know it's done? (acceptance criteria, optional)\n\n"
        f"Examples:\n"
        f"  `/agent Fix the off-by-one in src/parser.py:line_count()`\n"
        f"  `/agent Review @git changes and suggest improvements`\n"
        f"  `/agent Investigate why login.test.js times out and fix the cause`\n"
    )
    return NotificationResult(
        status=ResultStatus.WARNING,
        message=msg,
        metadata={
            "reason": "agent_task_too_vague",
            "min_words": min_words,
            "actual_words": len(words),
            "task": task,
        },
    )


# =============================================================================
# Type-Based Result Handlers (v1.15.0)
# =============================================================================

def handle_undo(context: CommandContext, args: str) -> CommandResult:
    """Handle /undo command - revert last agent task.

    Args:
        context: Command context providing access to engine client
        args: Command arguments (unused)

    Returns:
        ErrorResult on failure, ConfirmationResult on success
    """
    if not context.engine_client:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Undo command requires engine client"
        )

    # Get checkpoint status
    status = context.engine_client.get_checkpoint_status()
    if not status.get("enabled"):
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Checkpoints are not enabled",
            suggestions=["Initialize a git repository to enable automatic checkpoints"]
        )

    last_checkpoint = status.get("last_checkpoint")
    if not last_checkpoint:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="No checkpoint to undo",
            suggestions=["Run an /agent task first to create a checkpoint"]
        )

    # Check if checkpoint is still valid (not stale)
    is_valid = status.get("is_valid", True)
    if not is_valid:
        validity_reason = status.get("validity_reason", "Checkpoint is stale")
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Cannot undo: {validity_reason}",
            error_details="New commits have been made since the agent task",
            suggestions=[f"Use 'git revert {last_checkpoint[:8]}' manually if you still want to revert"]
        )

    # Check for uncommitted changes before undo (git revert requires clean working tree)
    backend = status.get("backend")
    if backend == "git":
        try:
            working_dir = context.engine_client.context_injector.working_dir
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=working_dir,
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                return ErrorResult(
            status=ResultStatus.ERROR,
                    message="Cannot undo: uncommitted changes in working directory",
                    suggestions=["Commit or stash your changes first, then try again"]
                )
        except subprocess.CalledProcessError:
            # Let the undo attempt proceed
            pass

    # Note: Interactive confirmation is handled by the old handler for now
    # In a future version, we could return a ConfirmationPromptResult
    # For now, perform the undo directly

    success = context.engine_client.undo_last_checkpoint()

    if success:
        details = {
            "backend": backend,
            "checkpoint": last_checkpoint[:8] if len(last_checkpoint) > 8 else last_checkpoint
        }

        if backend == "git":
            details["note"] = "Check `git log` to see the revert commit"

        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message="Undo successful",
            details=details
        )
    else:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Undo failed",
            suggestions=["Check checkpoint status with /checkpoint or enable verbose tools logging"]
        )


def handle_checkpoint(context: CommandContext, args: str) -> CommandResult:
    """Handle /checkpoint command - checkpoint management.

    Subcommands:
        /checkpoint              - Show checkpoint status (default)
        /checkpoint status       - Show checkpoint status
        /checkpoint list         - List recent checkpoints
        /checkpoint backend <x>  - Set backend (git/file/auto/none)
        /checkpoint clear        - Clear old file-based snapshots
        /checkpoint info <id>    - Show details about a checkpoint
        /checkpoint undo         - Alias for /undo

    Args:
        context: Command context providing access to engine client
        args: Subcommand and arguments

    Returns:
        KeyValueResult for status, TableResult for list, ConfirmationResult for actions
    """
    if not context.engine_client:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Checkpoint command requires engine client")

    parts = args.strip().split() if args else []
    subcommand = parts[0].lower() if parts else "status"

    if subcommand == "status" or not parts:
        return _checkpoint_status(context)
    elif subcommand == "list":
        return _checkpoint_list(context)
    elif subcommand == "backend":
        backend = parts[1] if len(parts) > 1 else None
        return _checkpoint_backend(context, backend)
    elif subcommand == "clear":
        return _checkpoint_clear(context)
    elif subcommand == "info":
        checkpoint_id = parts[1] if len(parts) > 1 else None
        return _checkpoint_info(context, checkpoint_id)
    elif subcommand == "undo":
        return handle_undo(context, "")  # Delegate to /undo handler
    else:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Unknown subcommand: {subcommand}",
            suggestions=["Available: status, list, backend, clear, info, undo"]
        )


def _checkpoint_status(context: CommandContext) -> CommandResult:
    """Show current checkpoint status."""
    status = context.engine_client.get_checkpoint_status()

    enabled = status.get("enabled", False)
    backend = status.get("backend", "none")
    last_checkpoint = status.get("last_checkpoint")
    is_valid = status.get("is_valid", False)
    validity_reason = status.get("validity_reason", "")

    # Backend status
    backend_labels = {
        "git": "git (atomic)",
        "file": "file (snapshot)",
        "none": "none (disabled)"
    }
    backend_display = backend_labels.get(backend, backend)

    pairs = {
        "Backend": backend_display,
        "Enabled": "Yes" if enabled else "No"
    }

    if last_checkpoint:
        checkpoint_display = last_checkpoint[:8] if len(last_checkpoint) > 8 else last_checkpoint
        if is_valid:
            pairs["Last checkpoint"] = f"{checkpoint_display} (valid)"
        else:
            pairs["Last checkpoint"] = f"{checkpoint_display} (stale)"
            if validity_reason:
                pairs["Reason"] = validity_reason
    else:
        pairs["Last checkpoint"] = "None"

    result_status = ResultStatus.SUCCESS if enabled else ResultStatus.WARNING

    return KeyValueResult(
        status=result_status,
        message="Checkpoint Status",
        pairs=pairs
    )


def _checkpoint_list(context: CommandContext) -> CommandResult:
    """List recent checkpoints."""
    checkpoints = context.engine_client.list_checkpoints(limit=10)

    if not checkpoints:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="No checkpoints found",
            suggestions=["Run an /agent task to create checkpoints"]
        )

    # Build table
    columns = ["#", "ID", "Timestamp", "Description"]
    rows = []

    for i, cp in enumerate(checkpoints, 1):
        cp_id = cp.get("id", "")[:8]
        desc = cp.get("description", "")[:50]
        timestamp = cp.get("timestamp", "")[:19]  # Truncate to datetime
        rows.append([str(i), cp_id, timestamp, desc])

    return TableResult(
        status=ResultStatus.SUCCESS,
        message="Recent Checkpoints",
        columns=columns,
        rows=rows
    )


def _checkpoint_backend(context: CommandContext, backend: Optional[str]) -> CommandResult:
    """Set or show the checkpoint backend."""
    if not backend:
        # Show current backend
        status = context.engine_client.get_checkpoint_status()
        current = status.get("backend", "none")
        return KeyValueResult(
            status=ResultStatus.INFO,
            message="Current checkpoint backend",
            pairs={
                "Backend": current,
                "Usage": "/checkpoint backend <git|file|auto|none>"
            }
        )

    valid_backends = ('git', 'file', 'auto', 'none')
    if backend not in valid_backends:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Invalid backend: {backend}",
            suggestions=[f"Valid options: {', '.join(valid_backends)}"]
        )

    success = context.engine_client.set_checkpoint_backend(backend)
    if success:
        status = context.engine_client.get_checkpoint_status()
        actual_backend = status.get("backend", "none")

        details = {"backend": actual_backend}

        if backend == "git" and actual_backend != "git":
            details["note"] = "Git backend requested but no git repo found"
        elif backend == "auto":
            details["auto_detected"] = actual_backend

        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message=f"Checkpoint backend set to: {actual_backend}",
            details=details
        )
    else:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Failed to set checkpoint backend")


def _checkpoint_clear(context: CommandContext) -> CommandResult:
    """Clear old file-based checkpoint snapshots."""
    status = context.engine_client.get_checkpoint_status()
    backend = status.get("backend", "none")

    if backend != "file":
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Clear only applies to file-based checkpoints",
            error_details=f"Current backend: {backend}"
        )

    # Note: Interactive confirmation is handled by old handler for now
    # Perform clear directly
    removed = context.engine_client.clear_file_checkpoints(keep_last=0)

    return ConfirmationResult(
        status=ResultStatus.SUCCESS,
        message=f"Cleared {removed} checkpoint(s)",
        details={"removed": removed}
    )


def _checkpoint_info(context: CommandContext, checkpoint_id: Optional[str]) -> CommandResult:
    """Show details about a specific checkpoint."""
    if not checkpoint_id:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Missing checkpoint ID",
            suggestions=["Usage: /checkpoint info <checkpoint_id>", "Use /checkpoint list to see available checkpoints"]
        )

    checkpoints = context.engine_client.list_checkpoints(limit=20)

    # Find matching checkpoint (prefix match)
    matching = [cp for cp in checkpoints if cp.get("id", "").startswith(checkpoint_id)]

    if not matching:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Checkpoint not found: {checkpoint_id}",
            suggestions=["Use /checkpoint list to see available checkpoints"]
        )

    cp = matching[0]
    pairs = {
        "ID": cp.get("id", ""),
        "Description": cp.get("description", ""),
        "Timestamp": cp.get("timestamp", "")
    }

    # Check if this is the current checkpoint
    status = context.engine_client.get_checkpoint_status()
    if status.get("last_checkpoint", "").startswith(checkpoint_id):
        if status.get("is_valid"):
            pairs["Status"] = "Current (can undo)"
        else:
            pairs["Status"] = "Stale (cannot undo)"
    else:
        pairs["Status"] = "Historical"

    return KeyValueResult(
        status=ResultStatus.INFO,
        message="Checkpoint Details",
        pairs=pairs
    )


def handle_agent(context: CommandContext, args: str) -> CommandResult:
    """Handle /agent command for autonomous task execution.

    The agent loop runs autonomously until:
    - Task completes (AI signals TASK_COMPLETE)
    - Max iterations reached (default: 10)
    - User interrupts with Ctrl-C

    Args:
        context: Command context providing access to engine client
        args: Task description or toggle command (on/off)

    Returns:
        ErrorResult for invalid input
        ConfirmationResult for toggles
        AIResponseResult for completed tasks
    """
    if not args.strip():
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Usage: /agent <task description>",
            suggestions=[
                "/agent on|off - Toggle agent mode",
                "Example: /agent Fix the bug in auth.py",
                "Example: /agent Review @git changes and fix issues"
            ]
        )

    # Handle toggle commands (on/off/enable/disable)
    first_word = args.strip().split()[0].lower()
    if first_word in ["on", "off", "enable", "disable"]:
        # Redirect to /tools agent handler for toggle
        if first_word in ["on", "enable"]:
            if not context.engine_client:
                return ErrorResult(
                    status=ResultStatus.ERROR,
                    message="Engine client not available"
                )
            context.engine_client.enable_agent_mode()
            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message="Agent mode enabled",
                details={"note": "Tools auto-enabled. Use '/agent <task>' to start autonomous execution."}
            )
        else:  # off/disable
            if not context.engine_client:
                return ErrorResult(
                    status=ResultStatus.ERROR,
                    message="Engine client not available"
                )
            context.engine_client.disable_agent_mode()
            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message="Agent mode disabled",
                details={}
            )

    if not context.engine_client:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Engine client not available"
        )

    task = args.strip()

    # Get agent config
    agent_config = context.engine_client.get_agent_config()
    min_words = agent_config.get("min_task_words", 3)
    max_iterations = agent_config.get("max_iterations", 10)

    # v1.18.1: shared validation. Same nudge text across TUI / web /
    # VSCode — closes the previous safety gap where web could
    # bypass min-words by sending `/agent <task>` to /chat.
    validation = validate_agent_task(task, min_words)
    if validation is not None:
        return validation

    # Ensure agent mode is enabled
    if not context.engine_client.agent_mode:
        console.print("[yellow]Enabling agent mode...[/yellow]")
        context.engine_client.enable_agent_mode()

    console.print(f"\n[cyan]🤖 Starting autonomous agent[/cyan]")
    console.print(f"[dim]Task: {task}[/dim]")
    console.print(f"[dim]Max iterations: {max_iterations}[/dim]")
    console.print(f"[dim]Press Ctrl-C to interrupt[/dim]\n")

    # Create checkpoint before agent task
    checkpoint_id = context.engine_client.create_checkpoint(task[:100])
    checkpoint_backend = None

    if checkpoint_id:
        status = context.engine_client.get_checkpoint_status()
        checkpoint_backend = status.get("backend")
    else:
        status = context.engine_client.get_checkpoint_status()
        if not status.get("enabled"):
            console.print("[yellow]⚠️  Running without checkpoints (no git repo)[/yellow]")
            console.print("[dim]Changes cannot be undone with /undo[/dim]\n")

    async def run_agent_loop():
        """Run autonomous agent loop."""
        iteration = 0
        task_complete = False
        accumulated_output = []

        while iteration < max_iterations and not task_complete:
            iteration += 1
            console.print(f"\n[yellow]━━━ Iteration {iteration}/{max_iterations} ━━━[/yellow]\n")

            # Build prompt for this iteration
            if iteration == 1:
                prompt = _build_agent_prompt(task, iteration)
            else:
                prompt = _build_continuation_prompt(task, iteration)

            # Run chat with event handling.
            #
            # Use the TUI logger directly (not engine_client.logger —
            # which doesn't exist; that path AttributeError'd silently
            # because no test exercised the construction with a real
            # engine). Item 11 (v1.18.2). See
            # tests/test_agent_logger_attribute.py for the regression test.
            event_handler = TUIEventHandler(
                console, get_logger("tui"),
                verbose=context.get_tools_verbose(),
                emoji_mode=getattr(context, 'emoji_mode', False),
                engine_client=context.engine_client
            )

            try:
                async for event in context.engine_client.chat(prompt, stream=True):
                    should_continue = await event_handler.handle_event(event)
                    if not should_continue:
                        break
            except KeyboardInterrupt:
                console.print("\n[yellow]⚠️  Agent interrupted by user (Ctrl-C)[/yellow]\n")
                raise

            response = event_handler.get_response()
            accumulated_output.append(f"Iteration {iteration}:\n{response}")

            # Check for completion signal
            if "TASK_COMPLETE:" in response:
                task_complete = True
                summary_parts = response.split("TASK_COMPLETE:", 1)
                final_summary = summary_parts[1].strip() if len(summary_parts) > 1 else "Done"
                console.print(f"\n[green]✅ Task completed![/green]")
                console.print(f"[dim]Summary: {final_summary[:200]}{'...' if len(final_summary) > 200 else ''}[/dim]\n")
                return "\n\n".join(accumulated_output), final_summary, True

        if not task_complete:
            console.print(f"\n[yellow]⚠️  Max iterations ({max_iterations}) reached[/yellow]")
            console.print("[dim]Task may be incomplete. Review the output above.[/dim]\n")

        return "\n\n".join(accumulated_output), "Max iterations reached", False

    try:
        full_output, summary, success = asyncio.run(run_agent_loop())

        return AIResponseResult(
            status=ResultStatus.SUCCESS if success else ResultStatus.WARNING,
            message=summary,
            content=full_output,
            code_blocks=[]  # Agent loop doesn't extract code blocks
        )

    except KeyboardInterrupt:
        # Handle interrupt — context satisfies the engine_client interface
        _handle_agent_interrupt(
            context,
            checkpoint_id,
            checkpoint_backend
        )
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Agent interrupted by user",
            error_details="Task execution was interrupted with Ctrl-C"
        )


# =============================================================================
# Command Registration
# =============================================================================

CommandFactory.register(CommandSpec(
    name="agent",
    description="Run autonomous agent task",
    handler=handle_agent,
    category="agent",
    usage="/agent <task> | /agent on|off"
))

CommandFactory.register(CommandSpec(
    name="undo",
    description="Undo last agent task (revert checkpoint)",
    handler=handle_undo,
    category="agent",
    usage="/undo"
))

CommandFactory.register(CommandSpec(
    name="checkpoint",
    description="Manage checkpoints for undo functionality",
    handler=handle_checkpoint,
    category="agent",
    usage="/checkpoint [status|list|backend|clear|info]"
))

"""
Agent commands - autonomous task execution and checkpoint management.

Commands for running autonomous agent tasks and managing checkpoints/undo.

v1.13.10: Migrated to Command Factory pattern
"""

import subprocess
from typing import TYPE_CHECKING, Optional

from .factory import CommandFactory, CommandSpec

if TYPE_CHECKING:
    from .handler import CommandHandler


def handle_undo(handler: "CommandHandler", args: str) -> None:
    """Handle /undo command to revert last agent task.

    Args:
        handler: CommandHandler instance providing context
        args: Command arguments (unused)
    """
    from ..common.logger import get_logger
    from ..ui import console

    logger = get_logger("tui")

    if not handler.engine_client:
        console.print("[red]Undo command requires engine client[/red]")
        return

    # Get checkpoint status
    status = handler.engine_client.get_checkpoint_status()
    if not status.get("enabled"):
        console.print("[yellow]⚠️  Checkpoints are not enabled[/yellow]")
        console.print("[dim]Initialize a git repository to enable automatic checkpoints[/dim]\n")
        return

    last_checkpoint = status.get("last_checkpoint")
    if not last_checkpoint:
        console.print("[yellow]⚠️  No checkpoint to undo[/yellow]")
        console.print("[dim]Run an /agent task first to create a checkpoint[/dim]\n")
        return

    # Check if checkpoint is still valid (not stale)
    is_valid = status.get("is_valid", True)
    if not is_valid:
        validity_reason = status.get("validity_reason", "Checkpoint is stale")
        console.print(f"[yellow]⚠️  Cannot undo: {validity_reason}[/yellow]")
        console.print("[dim]New commits have been made since the agent task.[/dim]")
        console.print(f"[dim]Use 'git revert {last_checkpoint[:8]}' manually if you still want to revert.[/dim]\n")
        return

    # Check for uncommitted changes before undo (git revert requires clean working tree)
    backend = status.get("backend")
    if backend == "git":
        try:
            working_dir = handler.engine_client.context_injector.working_dir
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=working_dir,
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                console.print("[yellow]⚠️  Cannot undo: uncommitted changes in working directory[/yellow]")
                console.print("[dim]Commit or stash your changes first, then try again[/dim]\n")
                return
        except subprocess.CalledProcessError as e:
            logger.debug(f"git status failed during undo check: {e}")
            # Let the undo attempt proceed

    # Show what will be undone
    console.print(f"\n[bold yellow]⚠️  Undo Last Agent Task[/bold yellow]")
    console.print(f"[cyan]Backend:[/cyan] {backend}")
    console.print(f"[cyan]Checkpoint:[/cyan] {last_checkpoint}")

    if backend == "git":
        console.print("\n[dim]This will:[/dim]")
        console.print("[dim]  • Create a git revert commit[/dim]")
        console.print("[dim]  • Restore all files to their pre-agent state[/dim]")
    else:
        console.print("\n[dim]This will:[/dim]")
        console.print("[dim]  • Restore files from snapshot[/dim]")
        console.print("[dim]  • Overwrite current file contents[/dim]")

    # Ask for confirmation
    try:
        from prompt_toolkit import prompt as pt_prompt
        response = pt_prompt("\nConfirm undo? (y/n): ")
        if response.lower() not in ["y", "yes"]:
            console.print("[yellow]Undo cancelled[/yellow]\n")
            return
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Undo cancelled[/yellow]\n")
        return

    # Perform undo
    console.print("\n[dim]Reverting changes...[/dim]")
    success = handler.engine_client.undo_last_checkpoint()

    if success:
        console.print("[green]✓ Undo successful[/green]")
        if backend == "git":
            console.print("[dim]Check `git log` to see the revert commit[/dim]")
    else:
        console.print("[red]✗ Undo failed[/red]")
        console.print("[dim]Check checkpoint status with /agent or enable verbose tools logging[/dim]")

    console.print()


def handle_checkpoint(handler: "CommandHandler", args: str) -> None:
    """Handle /checkpoint command for checkpoint management.

    Subcommands:
        /checkpoint              - Show checkpoint status (default)
        /checkpoint status       - Show checkpoint status
        /checkpoint list         - List recent checkpoints
        /checkpoint backend <x>  - Set backend (git/file/auto/none)
        /checkpoint clear        - Clear old file-based snapshots
        /checkpoint info <id>    - Show details about a checkpoint
        /checkpoint undo         - Alias for /undo

    Args:
        handler: CommandHandler instance providing context
        args: Subcommand and arguments
    """
    from ..ui import console

    if not handler.engine_client:
        console.print("[red]Checkpoint command requires engine client[/red]")
        return

    parts = args.strip().split() if args else []
    subcommand = parts[0].lower() if parts else "status"

    if subcommand == "status" or not parts:
        _checkpoint_status(handler)
    elif subcommand == "list":
        _checkpoint_list(handler)
    elif subcommand == "backend":
        backend = parts[1] if len(parts) > 1 else None
        _checkpoint_backend(handler, backend)
    elif subcommand == "clear":
        _checkpoint_clear(handler)
    elif subcommand == "info":
        checkpoint_id = parts[1] if len(parts) > 1 else None
        _checkpoint_info(handler, checkpoint_id)
    elif subcommand == "undo":
        handle_undo(handler, "")  # Delegate to /undo handler
    else:
        console.print(f"[red]Unknown subcommand: {subcommand}[/red]")
        console.print("[dim]Available: status, list, backend, clear, info, undo[/dim]\n")


def _checkpoint_status(handler: "CommandHandler") -> None:
    """Show current checkpoint status."""
    from ..ui import console

    status = handler.engine_client.get_checkpoint_status()

    console.print("\n[bold cyan]━━━ Checkpoint Status ━━━[/bold cyan]")

    enabled = status.get("enabled", False)
    backend = status.get("backend", "none")
    last_checkpoint = status.get("last_checkpoint")
    is_valid = status.get("is_valid", False)
    validity_reason = status.get("validity_reason", "")

    # Backend status with color
    if backend == "git":
        backend_display = "[green]git[/green] (atomic)"
    elif backend == "file":
        backend_display = "[yellow]file[/yellow] (snapshot)"
    else:
        backend_display = "[red]none[/red] (disabled)"

    console.print(f"  [cyan]Backend:[/cyan] {backend_display}")
    console.print(f"  [cyan]Enabled:[/cyan] {'[green]Yes[/green]' if enabled else '[red]No[/red]'}")

    if last_checkpoint:
        checkpoint_display = last_checkpoint[:8] if len(last_checkpoint) > 8 else last_checkpoint
        if is_valid:
            console.print(f"  [cyan]Last checkpoint:[/cyan] {checkpoint_display} [green](valid)[/green]")
        else:
            console.print(f"  [cyan]Last checkpoint:[/cyan] {checkpoint_display} [yellow](stale)[/yellow]")
            console.print(f"  [dim]Reason: {validity_reason}[/dim]")
    else:
        console.print("  [cyan]Last checkpoint:[/cyan] [dim]None[/dim]")

    console.print()


def _checkpoint_list(handler: "CommandHandler") -> None:
    """List recent checkpoints."""
    from ..ui import console

    checkpoints = handler.engine_client.list_checkpoints(limit=10)

    console.print("\n[bold cyan]━━━ Recent Checkpoints ━━━[/bold cyan]")

    if not checkpoints:
        console.print("  [dim]No checkpoints found[/dim]")
        console.print("  [dim]Run an /agent task to create checkpoints[/dim]\n")
        return

    for i, cp in enumerate(checkpoints, 1):
        cp_id = cp.get("id", "")[:8]
        desc = cp.get("description", "")[:50]
        timestamp = cp.get("timestamp", "")[:19]  # Truncate to datetime
        console.print(f"  {i}. [cyan]{cp_id}[/cyan]  {timestamp}  {desc}")

    console.print()


def _checkpoint_backend(handler: "CommandHandler", backend: Optional[str]) -> None:
    """Set or show the checkpoint backend."""
    from ..ui import console

    if not backend:
        # Show current backend
        status = handler.engine_client.get_checkpoint_status()
        current = status.get("backend", "none")
        console.print(f"\n[cyan]Current backend:[/cyan] {current}")
        console.print("[dim]Usage: /checkpoint backend <git|file|auto|none>[/dim]\n")
        return

    valid_backends = ('git', 'file', 'auto', 'none')
    if backend not in valid_backends:
        console.print(f"[red]Invalid backend: {backend}[/red]")
        console.print(f"[dim]Valid options: {', '.join(valid_backends)}[/dim]\n")
        return

    success = handler.engine_client.set_checkpoint_backend(backend)
    if success:
        status = handler.engine_client.get_checkpoint_status()
        actual_backend = status.get("backend", "none")
        console.print(f"[green]✓ Checkpoint backend set to: {actual_backend}[/green]")

        if backend == "git" and actual_backend != "git":
            console.print("[yellow]Note: Git backend requested but no git repo found[/yellow]")
        elif backend == "auto":
            console.print(f"[dim]Auto-detected backend: {actual_backend}[/dim]")
    else:
        console.print("[red]✗ Failed to set checkpoint backend[/red]")

    console.print()


def _checkpoint_clear(handler: "CommandHandler") -> None:
    """Clear old file-based checkpoint snapshots."""
    from prompt_toolkit import prompt as pt_prompt

    from ..ui import console

    status = handler.engine_client.get_checkpoint_status()
    backend = status.get("backend", "none")

    if backend != "file":
        console.print("[yellow]Clear only applies to file-based checkpoints[/yellow]")
        console.print(f"[dim]Current backend: {backend}[/dim]\n")
        return

    # Ask for confirmation
    try:
        response = pt_prompt("Clear all file-based checkpoints? (y/n): ")
        if response.lower() not in ["y", "yes"]:
            console.print("[yellow]Clear cancelled[/yellow]\n")
            return
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Clear cancelled[/yellow]\n")
        return

    removed = handler.engine_client.clear_file_checkpoints(keep_last=0)
    console.print(f"[green]✓ Cleared {removed} checkpoint(s)[/green]\n")


def _checkpoint_info(handler: "CommandHandler", checkpoint_id: Optional[str]) -> None:
    """Show details about a specific checkpoint."""
    from ..ui import console

    if not checkpoint_id:
        console.print("[red]Usage: /checkpoint info <checkpoint_id>[/red]")
        console.print("[dim]Use /checkpoint list to see available checkpoints[/dim]\n")
        return

    checkpoints = handler.engine_client.list_checkpoints(limit=20)

    # Find matching checkpoint (prefix match)
    matching = [cp for cp in checkpoints if cp.get("id", "").startswith(checkpoint_id)]

    if not matching:
        console.print(f"[red]Checkpoint not found: {checkpoint_id}[/red]")
        console.print("[dim]Use /checkpoint list to see available checkpoints[/dim]\n")
        return

    cp = matching[0]
    console.print("\n[bold cyan]━━━ Checkpoint Details ━━━[/bold cyan]")
    console.print(f"  [cyan]ID:[/cyan] {cp.get('id', '')}")
    console.print(f"  [cyan]Description:[/cyan] {cp.get('description', '')}")
    console.print(f"  [cyan]Timestamp:[/cyan] {cp.get('timestamp', '')}")

    # Check if this is the current checkpoint
    status = handler.engine_client.get_checkpoint_status()
    if status.get("last_checkpoint", "").startswith(checkpoint_id):
        if status.get("is_valid"):
            console.print("  [cyan]Status:[/cyan] [green]Current (can undo)[/green]")
        else:
            console.print("  [cyan]Status:[/cyan] [yellow]Stale (cannot undo)[/yellow]")
    else:
        console.print("  [cyan]Status:[/cyan] [dim]Historical[/dim]")

    console.print()


def _handle_agent_interrupt(
    handler: "CommandHandler",
    checkpoint_id: Optional[str],
    checkpoint_backend: Optional[str]
) -> None:
    """Handle agent interruption and offer automatic rollback.

    Args:
        handler: CommandHandler instance
        checkpoint_id: Checkpoint ID if one was created
        checkpoint_backend: Backend type ('git' or 'file')
    """
    from prompt_toolkit import prompt as pt_prompt

    from ..ui import console

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
    success = handler.engine_client.undo_last_checkpoint()

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


def handle_agent(handler: "CommandHandler", args: str) -> None:
    """Handle /agent command for autonomous task execution.

    The agent loop runs autonomously until:
    - Task completes (AI signals TASK_COMPLETE)
    - Max iterations reached (default: 5)
    - User interrupts with Ctrl-C

    Args:
        handler: CommandHandler instance providing context
        args: Task description or toggle command (on/off)
    """
    import asyncio

    from ..ui import console

    if not args.strip():
        console.print("[red]Usage: /agent <task description>[/red]")
        console.print("[yellow]       /agent on|off - Toggle agent mode[/yellow]")
        console.print("[yellow]Example: /agent Fix the bug in auth.py[/yellow]")
        console.print("[yellow]         /agent Review @git changes and fix issues[/yellow]\n")
        return

    # Redirect toggle commands to /tools agent handler
    first_word = args.strip().split()[0].lower()
    if first_word in ["on", "off", "enable", "disable"]:
        from .tools import _tools_agent
        _tools_agent(handler, [first_word])
        return

    if not handler.engine_client:
        console.print("[red]Error: Engine client not available[/red]\n")
        return

    task = args.strip()

    # Handle /agent on|off as toggle commands
    if task.lower() in ['on', 'enable']:
        handler.engine_client.enable_agent_mode()
        console.print("[green]Agent mode enabled[/green]")
        console.print("[dim]Tools auto-enabled. Use '/agent <task>' to start autonomous execution.[/dim]\n")
        return

    if task.lower() in ['off', 'disable']:
        handler.engine_client.disable_agent_mode()
        console.print("[yellow]Agent mode disabled[/yellow]\n")
        return

    # Get agent config from engine
    agent_config = handler.engine_client.get_agent_config()
    min_words = agent_config.get("min_task_words", 3)
    max_iterations = agent_config.get("max_iterations", 10)

    # Reject vague/ambiguous tasks for safety
    words = task.split()
    if len(words) < min_words:
        console.print(f"[red]Task too vague: \"{task}\"[/red]")
        console.print(f"\n[yellow]Agent tasks should be specific and descriptive (at least {min_words} words).[/yellow]")
        console.print("[yellow]Vague tasks can lead to unexpected AI interpretations.[/yellow]")
        console.print("\n[dim]Examples:[/dim]")
        console.print("[green]  ✓ /agent Fix the authentication bug in login.py[/green]")
        console.print("[green]  ✓ /agent Review @git changes and suggest improvements[/green]")
        console.print("[red]  ✗ /agent fix bug[/red]")
        console.print("[red]  ✗ /agent do it[/red]\n")
        return

    # Ensure agent mode is enabled (auto-enables tools)
    if not handler.engine_client.agent_mode:
        console.print("[yellow]Enabling agent mode...[/yellow]")
        handler.engine_client.enable_agent_mode()

    console.print(f"\n[cyan]🤖 Starting autonomous agent[/cyan]")
    console.print(f"[dim]Task: {task}[/dim]")
    console.print(f"[dim]Max iterations: {max_iterations}[/dim]")
    console.print(f"[dim]Press Ctrl-C to interrupt[/dim]\n")

    # Create checkpoint before agent task
    checkpoint_id = handler.engine_client.create_checkpoint(task[:100])  # Truncate long tasks
    checkpoint_backend = None

    if checkpoint_id:
        # Notifications are emitted via events in create_checkpoint()
        status = handler.engine_client.get_checkpoint_status()
        checkpoint_backend = status.get("backend")
    else:
        # If no checkpoint created, show warning if appropriate
        status = handler.engine_client.get_checkpoint_status()
        if not status.get("enabled"):
            console.print("[yellow]⚠️  Running without checkpoints (no git repo)[/yellow]")
            console.print("[dim]Changes cannot be undone with /undo[/dim]\n")

    async def run_agent_loop():
        from ..common.event_handler import TUIEventHandler

        iteration = 0
        task_complete = False

        while iteration < max_iterations and not task_complete:
            iteration += 1
            console.print(f"\n[yellow]━━━ Iteration {iteration}/{max_iterations} ━━━[/yellow]\n")

            # Build prompt for this iteration
            if iteration == 1:
                prompt = _build_agent_prompt(task, iteration)
            else:
                prompt = _build_continuation_prompt(task, iteration)

            # Run chat with event handling
            event_handler = TUIEventHandler(
                console, handler.logger,
                verbose=handler.tools_verbose,
                emoji_mode=handler.emoji_mode
            )

            try:
                async for event in handler.engine_client.chat(prompt, stream=True):
                    should_continue = await event_handler.handle_event(event)
                    if not should_continue:
                        break
            except KeyboardInterrupt:
                console.print("\n[yellow]⚠️  Agent interrupted by user (Ctrl-C)[/yellow]\n")
                raise  # Re-raise to outer handler

            response = event_handler.get_response()

            # Check for completion signal
            if "TASK_COMPLETE:" in response:
                task_complete = True
                # Extract summary after TASK_COMPLETE:
                summary_parts = response.split("TASK_COMPLETE:", 1)
                final_summary = summary_parts[1].strip() if len(summary_parts) > 1 else "Done"
                console.print(f"\n[green]✅ Task completed![/green]")
                console.print(f"[dim]Summary: {final_summary[:200]}{'...' if len(final_summary) > 200 else ''}[/dim]\n")
                return

        if not task_complete:
            console.print(f"\n[yellow]⚠️  Max iterations ({max_iterations}) reached[/yellow]")
            console.print("[dim]Task may be incomplete. Review the output above.[/dim]\n")

    try:
        asyncio.run(run_agent_loop())
    except KeyboardInterrupt:
        # Offer automatic rollback after interrupt
        _handle_agent_interrupt(handler, checkpoint_id, checkpoint_backend)


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

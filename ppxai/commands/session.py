"""
Session management commands.

Commands for saving, loading, listing, clearing, and exporting sessions.

v1.13.10: Migrated to Command Factory pattern
v1.15.0: Migrated to type-based renderer dispatch
"""

from datetime import datetime
from typing import TYPE_CHECKING, Union

from .factory import CommandFactory, CommandSpec
from .protocol import CommandContext
from .results import (
    ResultStatus,
    CommandResult,
    ConfirmationResult,
    TableResult,
    ErrorResult,
    NotificationResult,
)

if TYPE_CHECKING:
    from ..commands import CommandHandler


def handle_save(context: CommandContext, args: str) -> CommandResult:
    """Handle /save command - saves session to JSON.

    Args:
        context: Command context providing access to engine client
        args: Command arguments (unused)

    Returns:
        ConfirmationResult on success, ErrorResult on failure
    """
    try:
        session_name = context.engine_client.session.save()
        filepath = context.engine_client.session.sessions_dir / f"{session_name}.json"
        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message=f"Session saved to: {filepath}",
            details={
                "session_name": session_name,
                "filepath": str(filepath)
            }
        )
    except Exception as e:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Error saving session: {e}",
            error_details=str(e)
        )


def handle_load(context: CommandContext, args: str) -> CommandResult:
    """Handle /load command - loads a saved session.

    Args:
        context: Command context providing access to engine client
        args: Session name to load (optional - shows list if empty)

    Returns:
        ConfirmationResult on success, TableResult if showing list, ErrorResult on failure
    """
    if not args:
        # Show available sessions
        sessions = context.engine_client.session.list_sessions()

        if not sessions:
            return NotificationResult(
                status=ResultStatus.INFO,
                message="No saved sessions found"
            )

        return TableResult(
            status=ResultStatus.INFO,
            message="Available sessions (use /load <name> to load)",
            columns=["Name", "Created", "Saved", "Provider", "Model", "Messages"],
            rows=[
                [
                    s.name,
                    s.created_at.strftime("%Y-%m-%d %H:%M") if hasattr(s.created_at, 'strftime') else str(s.created_at),
                    s.saved_at.strftime("%Y-%m-%d %H:%M") if s.saved_at and hasattr(s.saved_at, 'strftime') else str(s.saved_at or ""),
                    s.provider,
                    s.model,
                    str(s.message_count)
                ]
                for s in sessions
            ]
        )

    try:
        if context.engine_client.session.load(args.strip()):
            # Update model from session metadata
            loaded_model = context.engine_client.session.metadata.get("model")
            if loaded_model:
                context.set_model(loaded_model)
                context.engine_client.set_model(loaded_model, reset_context=False)

            # Return special result with loaded messages
            return ConfirmationResult(
                status=ResultStatus.SUCCESS,
                message=f"Session loaded: {context.engine_client.session.session_name}",
                details={
                    "session_name": context.engine_client.session.session_name,
                    "message_count": len(context.engine_client.session.messages),
                    "messages": context.engine_client.session.messages,  # Pass messages for TUI rendering
                    "action": "load_session"  # Signal to TUI to render messages
                }
            )
        else:
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=f"Session not found: {args.strip()}",
                suggestions=["Use /sessions to see available sessions"]
            )
    except Exception as e:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Error loading session: {e}",
            error_details=str(e)
        )


def handle_sessions(context: CommandContext, args: str) -> CommandResult:
    """Handle /sessions command - lists saved sessions.

    Args:
        context: Command context providing access to engine client
        args: Command arguments (unused)

    Returns:
        TableResult with session list, or NotificationResult if no sessions
    """
    sessions = context.engine_client.session.list_sessions()

    if not sessions:
        return NotificationResult(
            status=ResultStatus.INFO,
            message="No saved sessions found"
        )

    return TableResult(
        status=ResultStatus.SUCCESS,
        message=f"{len(sessions)} saved session(s)",
        columns=["Name", "Created", "Saved", "Provider", "Model", "Messages"],
        rows=[
            [
                s.name,
                s.created_at.strftime("%Y-%m-%d %H:%M") if hasattr(s.created_at, 'strftime') else str(s.created_at),
                s.saved_at.strftime("%Y-%m-%d %H:%M") if s.saved_at and hasattr(s.saved_at, 'strftime') else str(s.saved_at or ""),
                s.provider,
                s.model,
                str(s.message_count)
            ]
            for s in sessions
        ]
    )


def handle_clear(context: CommandContext, args: str) -> CommandResult:
    """Handle /clear command - clears conversation history.

    Args:
        context: Command context providing access to engine client
        args: Command arguments (unused)

    Returns:
        ConfirmationResult
    """
    message_count = len(context.engine_client.session.messages)
    context.engine_client.session.clear()

    return ConfirmationResult(
        status=ResultStatus.SUCCESS,
        message="Conversation history cleared",
        details={
            "messages_cleared": message_count,
            "action": "clear_session"  # Signal to TUI to clear chat view
        }
    )


def handle_export(context: CommandContext, args: str) -> CommandResult:
    """Handle /export command - exports last answer to markdown.

    Args:
        context: Command context providing access to engine client
        args: Optional filename for the export

    Returns:
        ConfirmationResult on success, ErrorResult/NotificationResult on failure
    """
    try:
        # Find last assistant message
        last_assistant_msg = None
        for msg in reversed(context.engine_client.session.messages):
            if msg.role == 'assistant':
                last_assistant_msg = msg.content
                break

        if not last_assistant_msg:
            return NotificationResult(
                status=ResultStatus.WARNING,
                message="No assistant response to export yet"
            )

        # Generate filename with timestamp
        filename = args.strip() if args else None
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"answer_{timestamp}.md"

        if not filename.endswith('.md'):
            filename += '.md'

        filepath = context.engine_client.session.exports_dir / filename

        # Write content
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(last_assistant_msg)

        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message=f"Answer exported to: {filepath}",
            details={
                "filepath": str(filepath),
                "size_bytes": len(last_assistant_msg)
            }
        )
    except Exception as e:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Error exporting answer: {e}",
            error_details=str(e)
        )


def handle_copy(context: CommandContext, args: str) -> CommandResult:
    """Handle /copy command - copies last response to clipboard.

    v1.15.0: Added to provide reliable clipboard copy for Rich TUI
    where text selection copies frame borders.

    Args:
        context: Command context providing access to engine client
        args: "n" to copy nth message from end (default: 1 = last)

    Returns:
        ConfirmationResult on success, ErrorResult/NotificationResult on failure
    """
    try:
        import pyperclip
    except ImportError:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="Clipboard not available: install pyperclip",
            suggestions=["Run: pip install pyperclip"]
        )

    try:
        # Parse optional argument for which message to copy
        offset = 1  # Default: last assistant message
        if args.strip():
            try:
                offset = int(args.strip())
                if offset < 1:
                    offset = 1
            except ValueError:
                pass  # Use default

        # Find nth assistant message from end
        assistant_messages = [
            msg.content for msg in context.engine_client.session.messages
            if msg.role == 'assistant'
        ]

        if not assistant_messages:
            return NotificationResult(
                status=ResultStatus.WARNING,
                message="No assistant response to copy yet"
            )

        # Get the requested message (1-indexed from end)
        if offset > len(assistant_messages):
            offset = len(assistant_messages)

        target_msg = assistant_messages[-offset]

        # Copy to clipboard
        pyperclip.copy(target_msg)

        # Truncate preview for confirmation
        preview = target_msg[:100] + "..." if len(target_msg) > 100 else target_msg
        preview = preview.replace("\n", " ")

        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message=f"Copied to clipboard ({len(target_msg):,} chars)",
            details={
                "length": len(target_msg),
                "preview": preview,
                "message_offset": offset
            }
        )

    except Exception as e:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Error copying to clipboard: {e}",
            error_details=str(e)
        )


# =============================================================================
# Command Registration
# =============================================================================

CommandFactory.register(CommandSpec(
    name="save",
    description="Save current session",
    handler=handle_save,
    category="session",
    aliases=["s"],
    usage="/save"
))

CommandFactory.register(CommandSpec(
    name="load",
    description="Load a saved session",
    handler=handle_load,
    category="session",
    aliases=["l"],
    usage="/load <session_name>"
))

CommandFactory.register(CommandSpec(
    name="sessions",
    description="List saved sessions",
    handler=handle_sessions,
    category="session",
    usage="/sessions"
))

CommandFactory.register(CommandSpec(
    name="clear",
    description="Clear conversation history",
    handler=handle_clear,
    category="session",
    aliases=["c"],
    usage="/clear"
))

CommandFactory.register(CommandSpec(
    name="export",
    description="Export last response to markdown",
    handler=handle_export,
    category="session",
    aliases=["e"],
    usage="/export [filename]"
))

CommandFactory.register(CommandSpec(
    name="copy",
    description="Copy last response to clipboard",
    handler=handle_copy,
    category="session",
    aliases=["cp"],
    usage="/copy [n]  - Copy nth response from end (default: 1 = last)"
))

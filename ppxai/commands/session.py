"""
Session management commands.

Commands for saving, loading, listing, clearing, and exporting sessions.

v1.13.10: Migrated to Command Factory pattern
v1.15.0: Migrated to type-based renderer dispatch
"""

from datetime import datetime
from typing import Optional

import pyperclip

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


def handle_save(context: CommandContext, args: str) -> CommandResult:
    """Handle /save command - saves session to JSON.

    Args:
        context: Command context providing access to engine client
        args: Optional session name override. When provided, the session
              is renamed and saved under the given name (e.g.
              `/save my_experiment`). When empty, the current auto-
              generated `session_<timestamp>` name is used.

    Returns:
        ConfirmationResult on success, ErrorResult on failure

    v1.17.4: Honors the `args` positional parameter (previously ignored),
    reports the correct filesystem path for both flat-file and directory-
    format multimodal sessions, and warns when the user has staged
    attachments via `/attach` that haven't been sent yet (those live
    only in the handler's pending_files buffer and won't land in the
    saved session until a chat message flushes them).
    """
    try:
        session = context.engine_client.session

        # Warn about staged-but-unsent attachments. `pending_files` lives
        # on the CommandHandler (Rich TUI) or the web/vscode client;
        # access it defensively via getattr so headless contexts (tests,
        # server route) don't break.
        pending_files = getattr(context, "pending_files", None) or []
        pending_warning: Optional[str] = None
        if pending_files:
            names = ", ".join(getattr(pf, "name", "?") for pf in pending_files[:3])
            if len(pending_files) > 3:
                names += f", +{len(pending_files) - 3} more"
            pending_warning = (
                f"Note: {len(pending_files)} attachment(s) are staged via /attach "
                f"({names}) but have not been sent yet — they live only in the "
                f"pending buffer and are NOT included in this save. Send your "
                f"message first if you want them committed to the session, "
                f"or run /attach clear to discard them."
            )

        # Pass the optional name through to SessionManager.save() — None
        # means "keep current name" while a stripped arg means "rename
        # and save under the new name".
        new_name = args.strip() if args and args.strip() else None
        session_name = session.save(name=new_name)

        # Determine the actual on-disk path for display. Multimodal
        # sessions save to `<dir>/session.json`, text-only sessions to
        # `<name>.json`. The same resolver used by save() tells us
        # which format we actually wrote.
        json_path, is_dir = session._resolve_session_storage(session_name)
        filepath = json_path

        message = f"Session saved to: {filepath}"
        if pending_warning:
            message = f"{message}\n\n⚠ {pending_warning}"

        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message=message,
            details={
                "session_name": session_name,
                "filepath": str(filepath),
                "format": "directory" if is_dir else "flat",
                "pending_attachments_warning": bool(pending_warning),
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
        restore_result = context.engine_client.restore_session(args.strip())
        if not restore_result["success"]:
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=restore_result.get("error", f"Session not found: {args.strip()}"),
                suggestions=["Use /sessions to see available sessions"]
            )

        tools_enabled = restore_result["tools_enabled"]
        return ConfirmationResult(
            status=ResultStatus.SUCCESS,
            message=f"Session loaded: {context.engine_client.session.session_name}",
            details={
                "session_name": context.engine_client.session.session_name,
                "message_count": len(context.engine_client.session.messages),
                "messages": context.engine_client.session.messages,
                "action": "load_session",
                "tools_enabled": tools_enabled,
            }
        )
    except Exception as e:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"Error loading session: {e}",
            error_details=str(e)
        )


def handle_sessions(context: CommandContext, args: str) -> CommandResult:
    """Handle /sessions command - lists saved sessions, or loads one with 'load <name>'.

    Args:
        context: Command context providing access to engine client
        args: Optional subcommand, e.g. 'load <session_name>'

    Returns:
        TableResult with session list, ConfirmationResult on load, or ErrorResult
    """
    # Support '/sessions load <name>' as alias for '/load <name>'
    if args.strip().startswith("load "):
        session_name = args.strip()[len("load "):].strip()
        return handle_load(context, session_name)

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

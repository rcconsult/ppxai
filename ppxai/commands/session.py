"""
Session management commands.

Commands for saving, loading, listing, clearing, and exporting sessions.

v1.13.10: Migrated to Command Factory pattern
"""

from datetime import datetime
from typing import TYPE_CHECKING

from .factory import CommandFactory, CommandSpec

if TYPE_CHECKING:
    from ..commands import CommandHandler


def handle_save(handler: "CommandHandler", args: str) -> None:
    """Handle /save command - saves session to JSON.

    Args:
        handler: CommandHandler instance providing context
        args: Command arguments (unused)
    """
    from ..ui import console

    try:
        session_name = handler.engine_client.session.save()
        filepath = handler.engine_client.session.sessions_dir / f"{session_name}.json"
        console.print(f"\n[green]Session saved to:[/green] {filepath}\n")
    except Exception as e:
        console.print(f"[red]Error saving session: {e}[/red]\n")


def handle_load(handler: "CommandHandler", args: str) -> None:
    """Handle /load command - loads a saved session.

    Args:
        handler: CommandHandler instance providing context
        args: Session name to load (optional - shows list if empty)
    """
    from ..ui import console, display_sessions

    if not args:
        console.print("[red]Please specify a session name: /load <session_name>[/red]\n")
        sessions = handler.engine_client.session.list_sessions()
        session_dicts = [
            {
                "name": s.name,
                "created_at": s.created_at,
                "saved_at": s.saved_at,
                "provider": s.provider,
                "model": s.model,
                "message_count": s.message_count
            }
            for s in sessions
        ]
        display_sessions(session_dicts)
        return

    try:
        if handler.engine_client.session.load(args.strip()):
            handler.current_model = handler.engine_client.session.metadata.get(
                "model", handler.current_model
            )
            # Update engine client model
            handler.engine_client.set_model(handler.current_model)
            console.print(
                f"\n[green]Session loaded:[/green] {handler.engine_client.session.session_name}"
            )
            console.print(
                f"[dim]Messages: {len(handler.engine_client.session.messages)}[/dim]\n"
            )
        else:
            console.print(f"[red]Session not found: {args.strip()}[/red]\n")
    except Exception as e:
        console.print(f"[red]Error loading session: {e}[/red]\n")


def handle_sessions(handler: "CommandHandler", args: str) -> None:
    """Handle /sessions command - lists saved sessions.

    Args:
        handler: CommandHandler instance providing context
        args: Command arguments (unused)
    """
    from ..ui import display_sessions

    sessions = handler.engine_client.session.list_sessions()
    session_dicts = [
        {
            "name": s.name,
            "created_at": s.created_at,
            "saved_at": s.saved_at,
            "provider": s.provider,
            "model": s.model,
            "message_count": s.message_count
        }
        for s in sessions
    ]
    display_sessions(session_dicts)


def handle_clear(handler: "CommandHandler", args: str) -> None:
    """Handle /clear command - clears conversation history.

    Args:
        handler: CommandHandler instance providing context
        args: Command arguments (unused)
    """
    from ..ui import console

    handler.engine_client.session.clear()
    console.print("\n[green]Conversation history cleared.[/green]\n")


def handle_export(handler: "CommandHandler", args: str) -> None:
    """Handle /export command - exports last answer to markdown.

    Args:
        handler: CommandHandler instance providing context
        args: Optional filename for the export
    """
    from ..ui import console

    try:
        last_assistant_msg = None
        for msg in reversed(handler.engine_client.session.messages):
            if msg.role == 'assistant':
                last_assistant_msg = msg.content
                break

        if not last_assistant_msg:
            console.print("[yellow]No assistant response to export yet.[/yellow]\n")
            return

        # Generate filename with timestamp
        filename = args.strip() if args else None
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"answer_{timestamp}.md"

        if not filename.endswith('.md'):
            filename += '.md'

        filepath = handler.engine_client.session.exports_dir / filename

        # Write content
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(last_assistant_msg)

        console.print(f"\n[green]Answer exported to:[/green] {filepath}\n")
    except Exception as e:
        console.print(f"[red]Error exporting answer: {e}[/red]\n")


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

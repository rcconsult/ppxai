"""
Commands package - Slash command handling for ppxai.

This package provides the Command Factory pattern for registering
and dispatching slash commands. Commands self-register at import time.

Usage:
    from ppxai.commands import CommandFactory, CommandSpec

    def handle_mycommand(handler, args: str):
        # Command implementation
        pass

    CommandFactory.register(CommandSpec(
        name="mycommand",
        description="My custom command",
        handler=handle_mycommand,
        category="custom"
    ))

v1.13.10: Initial implementation (Command Factory pattern)
"""

# asyncio is standard library, re-export for patching compatibility
import asyncio

from .factory import CommandFactory, CommandSpec
from .handler import (
    CommandHandler,
    ConsentValidator,
    console,
    display_file_editing_help,
    display_sessions,
    display_welcome,
    get_api_key,
    get_base_url,
    get_coding_model,
    get_provider_config,
    # Re-export imports for test backward compatibility
    # These were accessible as ppxai.commands.X in the old module structure
    select_model,
    select_provider,
    send_coding_task,
    tui_consent_handler,
)

__all__ = [
    # Factory pattern
    "CommandFactory",
    "CommandSpec",
    # Legacy exports (backward compatibility)
    "CommandHandler",
    "tui_consent_handler",
    "ConsentValidator",
    "send_coding_task",
    # Re-exports for test compatibility
    "select_model",
    "select_provider",
    "display_sessions",
    "display_welcome",
    "display_file_editing_help",
    "get_coding_model",
    "get_api_key",
    "get_base_url",
    "get_provider_config",
    "console",
    "asyncio",
]

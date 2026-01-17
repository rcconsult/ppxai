"""
Shared modules for ppxai clients.

This package contains business logic shared across all ppxai clients (TUI, VSCode, etc.).

Architecture:
- TUI imports these modules directly (self-contained executable)
- Server imports these modules and exposes via HTTP API
- No code duplication, consistent behavior across clients

Modules:
- event_handler: Unified event processing for engine events
- logger: Shared logging system for debugging and observability
- commands: Command execution (slash commands like /tools, /model, etc.)
- consent: File editing consent management

Version: v1.13.11 - Centralized constants
"""

from ppxai.common.event_handler import EventHandler
from ppxai.common.logger import get_logger, Logger
from ppxai.common.commands import CommandHandler, CommandResult
from ppxai.common.consent import ConsentManager

__all__ = [
    "EventHandler",
    "get_logger",
    "Logger",
    "CommandHandler",
    "CommandResult",
    "ConsentManager",
]

"""
Shared modules for ppxai clients.

This package contains business logic shared across all ppxai clients (TUI, VSCode, etc.).

Architecture:
- TUI imports these modules directly (self-contained executable)
- Server imports these modules and exposes via HTTP API
- No code duplication, consistent behavior across clients

Modules:
- logger: Shared logging system for debugging and observability
- consent: File editing consent management

Note: EventHandler moved to ppxai.rich.event_handler (Rich TUI specific)
Note: Command handling moved to ppxai.commands (Command Factory pattern, v1.13.10+)
"""

from ppxai.common.logger import get_logger, Logger
from ppxai.common.consent import ConsentManager

__all__ = [
    "get_logger",
    "Logger",
    "ConsentManager",
]

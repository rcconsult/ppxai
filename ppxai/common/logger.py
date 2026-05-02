"""
Unified logging system for ppxai clients.

Provides detailed logging of message flow, API calls, and tool execution
with timestamps. Can be enabled via environment variable or programmatically.

Architecture:
- TUI logs to: ~/.ppxai/logs/tui-debug.log
- Server logs to: ~/.ppxai/logs/server-debug.log
- Same interface, different log files

Usage:
    # TUI
    logger = get_logger("tui")
    logger.enable()
    logger.log_user_message("Hello")

    # Server
    logger = get_logger("server")
    logger.enable()
    logger.log_api_request(1, messages)

Version: see ``ppxai.__version__`` (single source of truth in ``ppxai/version.py``).
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict
import os


def _sanitize_for_logging(text: str) -> str:
    """Sanitize text for safe logging on Windows.

    Windows console uses cp1252 encoding which can't handle many Unicode characters.
    This replaces problematic characters with ASCII equivalents.

    Args:
        text: Text that may contain Unicode characters

    Returns:
        Text safe for Windows console logging
    """
    # Common Unicode characters that cause issues on Windows cp1252
    replacements = {
        '\u202f': ' ',    # Narrow no-break space -> regular space
        '\u00a0': ' ',    # Non-breaking space -> regular space
        '\u2018': "'",    # Left single quote
        '\u2019': "'",    # Right single quote
        '\u201c': '"',    # Left double quote
        '\u201d': '"',    # Right double quote
        '\u2013': '-',    # En dash
        '\u2014': '--',   # Em dash
        '\u2026': '...',  # Ellipsis
        '\u2022': '*',    # Bullet
        '\u00b7': '*',    # Middle dot
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text


def _preview_message_content(msg, limit: int) -> str:
    """Build a short, single-line preview of a Message or message-dict.

    Handles both `Message` dataclass instances (which may have multimodal
    list content via `text_content()`) and plain dicts used in API payloads.
    Returns at most `limit` characters with newlines escaped.
    """
    if hasattr(msg, 'text_content'):
        text = msg.text_content()
    elif hasattr(msg, 'content'):
        raw = msg.content
        if isinstance(raw, str):
            text = raw
        elif isinstance(raw, list):
            # Mirror Message.text_content() for non-Message objects.
            parts = []
            for block in raw:
                if isinstance(block, dict):
                    if block.get('type') == 'text':
                        parts.append(block.get('text', ''))
                    else:
                        parts.append(f"[{block.get('type', 'part')}]")
            text = '\n'.join(parts)
        else:
            text = str(raw)
    else:
        text = str(msg)
    return text[:limit].replace('\n', '\\n')


class Logger:
    """Unified logger for ppxai clients (TUI, Server, etc.)."""

    # Class-level registry of logger instances
    _instances: Dict[str, 'Logger'] = {}

    def __init__(self, name: str):
        """
        Initialize logger for a specific client.

        Args:
            name: Client name (e.g., "tui", "server")
        """
        self.name = name
        self._logger: Optional[logging.Logger] = None
        self._enabled: bool = False
        self._log_file: Optional[Path] = None

        # Check if logging is enabled via environment
        env_var = f'PPXAI_DEBUG' if name == "tui" else f'PPXAI_{name.upper()}_DEBUG'
        if os.getenv('PPXAI_DEBUG', '').lower() in ['1', 'true', 'yes', 'on']:
            self._enabled = True
            self._initialize_logger()
        elif os.getenv(env_var, '').lower() in ['1', 'true', 'yes', 'on']:
            self._enabled = True
            self._initialize_logger()

    def _initialize_logger(self):
        """Initialize the Python logger with file handler."""
        if self._logger is not None:
            return

        if not self._enabled:
            # Create a no-op logger
            self._logger = logging.getLogger(f'ppxai.{self.name}.noop')
            self._logger.addHandler(logging.NullHandler())
            return

        # Create logs directory
        log_dir = Path.home() / '.ppxai' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create logger
        self._logger = logging.getLogger(f'ppxai.{self.name}')
        self._logger.setLevel(logging.DEBUG)

        # Remove any existing handlers
        self._logger.handlers.clear()

        # File handler - use UTF-8 encoding for Windows compatibility
        self._log_file = log_dir / f'{self.name}-debug.log'
        file_handler = logging.FileHandler(self._log_file, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)

        # Format: timestamp | level | message
        formatter = logging.Formatter(
            '%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        )
        file_handler.setFormatter(formatter)

        self._logger.addHandler(file_handler)

        # Log session start with version + source mtime so log readers
        # can correlate behavior with the running code state. Critical
        # for editable-install setups where a stale Python process can
        # outlive its own source — the process keeps running the OLD
        # code, but operators reading the log later see the NEW source.
        # The source_mtime field makes this gap visible.
        from ..version import format_version_banner  # local import — version is leaf, no cycle
        self._logger.info("=" * 80)
        self._logger.info(f"{self.name.upper()} DEBUG SESSION STARTED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._logger.info(format_version_banner())
        self._logger.info("=" * 80)

    @property
    def enabled(self) -> bool:
        """Check if logging is enabled."""
        return self._enabled

    @property
    def log_file(self) -> Optional[Path]:
        """Get the log file path."""
        return self._log_file

    def enable(self):
        """Enable logging (creates logger if not already created)."""
        if self._enabled:
            return  # Already enabled

        self._enabled = True
        self._logger = None
        self._initialize_logger()

    def disable(self):
        """Disable logging."""
        if not self._enabled:
            return

        if self._logger:
            self._logger.info("=" * 80)
            self._logger.info(f"{self.name.upper()} DEBUG SESSION ENDED")
            self._logger.info("=" * 80)

        self._enabled = False

        # Replace with no-op logger
        self._logger = logging.getLogger(f'ppxai.{self.name}.noop')
        self._logger.addHandler(logging.NullHandler())

    @classmethod
    def enable_all(cls):
        """Enable all existing logger instances."""
        for logger in cls._instances.values():
            logger.enable()

    @classmethod
    def disable_all(cls):
        """Disable all existing logger instances."""
        for logger in cls._instances.values():
            logger.disable()

    def clear(self):
        """Clear the log file."""
        if self._log_file and self._log_file.exists():
            self._log_file.write_text("", encoding="utf-8")
            if self._enabled:
                # Re-log session start
                self._logger.info("=" * 80)
                self._logger.info(f"{self.name.upper()} DEBUG SESSION STARTED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                self._logger.info("=" * 80)

    def info(self, msg: str):
        """Log info message."""
        if self._logger:
            self._logger.info(msg)

    def debug(self, msg: str):
        """Log debug message."""
        if self._logger:
            self._logger.debug(msg)

    def warning(self, msg: str):
        """Log warning message."""
        if self._logger:
            self._logger.warning(msg)

    def error(self, msg: str, exc_info: bool = False):
        """Log error message.

        Args:
            msg: Error message
            exc_info: If True, include exception traceback
        """
        if self._logger:
            self._logger.error(msg, exc_info=exc_info)

    def log_user_message(self, message: str):
        """Log user input."""
        self.info(f"USER INPUT: {_sanitize_for_logging(message[:200])}")

    def log_assistant_message(self, message: str):
        """Log assistant response."""
        self.info(f"ASSISTANT RESPONSE: {_sanitize_for_logging(message[:200])}")

    def log_command(self, command: str):
        """Log slash command execution."""
        self.info(f"COMMAND: {command}")

    def log_history_sync(self, legacy_count: int, engine_count: int, messages: list):
        """Log conversation history sync."""
        self.info(f"HISTORY SYNC: legacy={legacy_count}, engine={engine_count}")
        for i, msg in enumerate(messages):
            content_preview = _preview_message_content(msg, 80)
            role = msg.role if hasattr(msg, 'role') else msg.get('role', 'unknown')
            self.debug(f"  [{i}] {role:10s}: {content_preview}")

    def log_api_request(self, iteration: int, messages: list):
        """Log API request with message sequence."""
        self.info(f"API REQUEST: iteration={iteration}, messages={len(messages)}")
        for i, msg in enumerate(messages):
            content_preview = _preview_message_content(msg, 100)
            role = msg.role if hasattr(msg, 'role') else msg.get('role', 'unknown')
            self.debug(f"  [{i}] {role:10s}: {content_preview}")

    def log_api_response(self, response_preview: str):
        """Log API response."""
        self.info(f"API RESPONSE: {response_preview[:200]}")

    def log_api_error(self, error_code: int, error_message: str):
        """Log API error."""
        self.error(f"API ERROR {error_code}: {error_message}")

    def log_tool_call(self, tool_name: str, arguments: dict):
        """Log tool execution."""
        self.info(f"TOOL CALL: {tool_name}")
        self.debug(f"  Arguments: {arguments}")

    def log_tool_result(self, tool_name: str, result: str):
        """Log tool result."""
        self.info(f"TOOL RESULT: {tool_name}")
        self.debug(f"  Result: {result[:200]}")

    def log_tool_error(self, tool_name: str, error: str):
        """Log tool error."""
        self.error(f"TOOL ERROR: {tool_name} - {error}")

    def log_client_event(self, client: str, level: str, message: str):
        """Log event forwarded from a web/IDE client."""
        tag = f"CLIENT[{client}]"
        if level == "error":
            self.error(f"{tag}: {message[:500]}")
        elif level == "warning":
            self.warning(f"{tag}: {message[:500]}")
        else:
            self.info(f"{tag}: {message[:500]}")

    def log_event(self, event_type: str, data: str = ""):
        """Log generic event."""
        self.debug(f"EVENT: {event_type} - {data[:100]}")

    def log_http_request(self, method: str, path: str, client: str = "unknown"):
        """Log HTTP request (server-specific)."""
        self.info(f"HTTP {method} {path} from {client}")

    def log_http_response(self, status_code: int, path: str):
        """Log HTTP response (server-specific)."""
        self.info(f"HTTP {status_code} {path}")

    def log_sse_event(self, event_type: str, data_preview: str = ""):
        """Log SSE event (server-specific)."""
        self.debug(f"SSE: {event_type} - {data_preview[:100]}")


def get_logger(name: str = "tui") -> Logger:
    """
    Get or create a logger instance for a specific client.

    Args:
        name: Client name (e.g., "tui", "server")

    Returns:
        Logger: Logger instance for the specified client

    Usage:
        # TUI
        logger = get_logger("tui")

        # Server
        logger = get_logger("server")

        # Custom client
        logger = get_logger("webclient")
    """
    if name not in Logger._instances:
        Logger._instances[name] = Logger(name)
    return Logger._instances[name]

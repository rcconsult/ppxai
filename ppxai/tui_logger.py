"""
TUI Debug Logger for ppxai.

Provides detailed logging of message flow, API calls, and tool execution
with timestamps. Can be enabled via environment variable or command.

Logs to: ~/.ppxai/logs/tui-debug.log
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
import os


class TUILogger:
    """Singleton logger for TUI debugging."""

    _instance: Optional['TUILogger'] = None
    _logger: Optional[logging.Logger] = None
    _enabled: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._logger is not None:
            return

        # Check if logging is enabled (only if not explicitly enabled via enable())
        if not self._enabled:
            self._enabled = os.getenv('PPXAI_DEBUG', '').lower() in ['1', 'true', 'yes', 'on']

        if not self._enabled:
            # Create a no-op logger
            self._logger = logging.getLogger('ppxai.tui.noop')
            self._logger.addHandler(logging.NullHandler())
            return

        # Create logs directory
        log_dir = Path.home() / '.ppxai' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create logger
        self._logger = logging.getLogger('ppxai.tui')
        self._logger.setLevel(logging.DEBUG)

        # File handler with rotation
        log_file = log_dir / 'tui-debug.log'
        file_handler = logging.FileHandler(log_file, mode='a')
        file_handler.setLevel(logging.DEBUG)

        # Format: timestamp | level | message
        formatter = logging.Formatter(
            '%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        )
        file_handler.setFormatter(formatter)

        self._logger.addHandler(file_handler)

        # Log session start
        self._logger.info("=" * 80)
        self._logger.info(f"TUI DEBUG SESSION STARTED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._logger.info("=" * 80)

    @property
    def enabled(self) -> bool:
        """Check if logging is enabled."""
        return self._enabled

    def enable(self):
        """Enable logging (creates logger if not already created)."""
        if self._enabled:
            return  # Already enabled

        self._enabled = True

        # Re-initialize with real logger
        self._logger = None
        self.__init__()

    def disable(self):
        """Disable logging."""
        if not self._enabled:
            return

        self._logger.info("=" * 80)
        self._logger.info("TUI DEBUG SESSION ENDED")
        self._logger.info("=" * 80)

        self._enabled = False

        # Replace with no-op logger
        self._logger = logging.getLogger('ppxai.tui.noop')
        self._logger.addHandler(logging.NullHandler())

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

    def error(self, msg: str):
        """Log error message."""
        if self._logger:
            self._logger.error(msg)

    def log_user_message(self, message: str):
        """Log user input."""
        self.info(f"USER INPUT: {message[:200]}")

    def log_assistant_message(self, message: str):
        """Log assistant response."""
        self.info(f"ASSISTANT RESPONSE: {message[:200]}")

    def log_command(self, command: str):
        """Log slash command execution."""
        self.info(f"COMMAND: {command}")

    def log_history_sync(self, legacy_count: int, engine_count: int, messages: list):
        """Log conversation history sync."""
        self.info(f"HISTORY SYNC: legacy={legacy_count}, engine={engine_count}")
        for i, msg in enumerate(messages):
            content_preview = msg.content[:80].replace('\n', '\\n') if hasattr(msg, 'content') else str(msg)[:80]
            role = msg.role if hasattr(msg, 'role') else msg.get('role', 'unknown')
            self.debug(f"  [{i}] {role:10s}: {content_preview}")

    def log_api_request(self, iteration: int, messages: list):
        """Log API request with message sequence."""
        self.info(f"API REQUEST: iteration={iteration}, messages={len(messages)}")
        for i, msg in enumerate(messages):
            content_preview = msg.content[:100].replace('\n', '\\n') if hasattr(msg, 'content') else str(msg)[:100]
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

    def log_event(self, event_type: str, data: str = ""):
        """Log generic event."""
        self.debug(f"EVENT: {event_type} - {data[:100]}")


# Global singleton instance
_tui_logger = TUILogger()


def get_logger() -> TUILogger:
    """Get the global TUI logger instance."""
    return _tui_logger

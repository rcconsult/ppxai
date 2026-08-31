"""
ppxaide - Next generation TUI for ppxai built on Textual.

This module provides a modern terminal UI with:
- Mouse support
- CSS theming
- Widget-based composition
- Proper editor workflows

Entry point: ppxaide command
"""

import argparse
import logging
import os
import signal
import sys

from ppxai import __version__
from ppxai.common.logger import get_logger
from ppxai.config import initialize
from ppxai.tui.app import PPXAIDEApp

from ..config import get_debug_log_enabled

__all__ = ["PPXAIDEApp", "main"]


def main():
    """Entry point for ppxaide command."""

    # Parse CLI arguments
    parser = argparse.ArgumentParser(description="ppxaide - Textual TUI for ppxai")
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"ppxaide {__version__}"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging to stderr"
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Enable full exception tracebacks in debug log (implies --debug)"
    )
    args = parser.parse_args()

    # Configure logging
    logger = get_logger("tui")
    if args.debug or args.trace:
        logger.enable()
        # If --debug specified, also log to stderr for immediate visibility
        if args.debug:
            stderr_handler = logging.StreamHandler(sys.stderr)
            stderr_handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            logger._logger.addHandler(stderr_handler)

    # Store trace flag globally for exception handlers
    if args.trace:
        os.environ['PPXAIDE_TRACE'] = '1'

    # Initialize config and load .env BEFORE starting event loop (matches Rich TUI).
    # initialize() also restores persisted debug-log state — the logger is
    # already writing by the time any TUI code runs.
    initialize()

    # Pick up persisted state for the app's internal debug flags
    persisted_debug = get_debug_log_enabled()

    # Create app instance
    debug_mode = args.debug or args.trace or persisted_debug
    trace_mode = args.trace
    app = PPXAIDEApp(debug_logging=debug_mode, trace_logging=trace_mode)

    # Install signal handlers for graceful shutdown (v1.15.3)
    # Handles SIGINT (Ctrl+C) and SIGTERM on all platforms including Windows
    def signal_handler(signum, frame):
        """Handle SIGINT/SIGTERM gracefully by triggering Textual's quit action."""
        # Use call_from_thread to invoke action_quit in the main thread safely
        try:
            app.call_from_thread(app.action_quit)
        except Exception:
            # If app not running yet or already stopped, just exit cleanly
            sys.exit(0)

    # Install handlers on all platforms (Windows, macOS, Linux)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run app with KeyboardInterrupt handling for graceful shutdown on all platforms
    try:
        app.run()
    except KeyboardInterrupt:
        # Graceful exit on Ctrl+C that bypassed Textual's handling
        logger.info("Received KeyboardInterrupt, exiting gracefully")
        sys.exit(0)

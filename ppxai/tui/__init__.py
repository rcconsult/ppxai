"""
ppxaide - Next generation TUI for ppxai built on Textual.

This module provides a modern terminal UI with:
- Mouse support
- CSS theming
- Widget-based composition
- Proper editor workflows

Entry point: ppxaide command
"""

from ppxai.tui.app import PPXAIDEApp

__all__ = ["PPXAIDEApp", "main"]


def main():
    """Entry point for ppxaide command."""
    import argparse
    import sys
    from ppxai.common.logger import get_logger

    # Parse CLI arguments
    parser = argparse.ArgumentParser(description="ppxaide - Textual TUI for ppxai")
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
            import logging
            stderr_handler = logging.StreamHandler(sys.stderr)
            stderr_handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            logger._logger.addHandler(stderr_handler)

    # Store trace flag globally for exception handlers
    if args.trace:
        import os
        os.environ['PPXAIDE_TRACE'] = '1'

    # Initialize config and load .env BEFORE starting event loop (matches Rich TUI)
    from ppxai.config import initialize
    initialize()

    app = PPXAIDEApp()
    app.run()

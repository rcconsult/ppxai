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
    # Initialize config and load .env BEFORE starting event loop (matches Rich TUI)
    from ppxai.config import initialize
    initialize()

    app = PPXAIDEApp()
    app.run()

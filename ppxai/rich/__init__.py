"""
ppxai Rich TUI - Legacy terminal interface using Rich + prompt_toolkit.

This package contains the original Rich-based TUI implementation.
Entry point: ppxai.rich.main:main

ISOLATION: This package must NOT import from ppxai.tui.*

Note: main is not imported here to avoid circular dependency with ppxai.commands
Import directly from ppxai.rich.main when needed.
"""

__all__ = []

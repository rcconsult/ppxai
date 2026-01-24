"""
ppxai Rich TUI - Legacy terminal interface using Rich + prompt_toolkit.

This package contains the original Rich-based TUI implementation.
Entry point: ppxai.rich.main:main

ISOLATION: This package must NOT import from ppxai.tui.*
"""

from .main import main

__all__ = ["main"]

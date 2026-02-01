"""Custom renderables for ppxaide TUI.

This module provides custom Rich renderables for terminal-specific
image rendering protocols that aren't covered by textual-image.
"""

from .iterm2 import ITerm2Image

__all__ = ["ITerm2Image"]

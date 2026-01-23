"""
ppxaide themes - Textual theme integration.

Uses Textual's built-in themes (17+) plus custom ppxaide themes:
- tron-legacy: Cyan/orange on dark (unique to ppxaide)
- matrix: Green on black (unique to ppxaide)

Built-in themes available via Ctrl+P command palette.
Curated themes cycle via Ctrl+T.
"""

from ppxai.tui.themes.themes import CUSTOM_THEMES, DEFAULT_THEME, CYCLE_THEMES

__all__ = ["CUSTOM_THEMES", "DEFAULT_THEME", "CYCLE_THEMES"]

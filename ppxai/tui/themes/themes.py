"""
ppxaide theme definitions using Textual's Theme system.

Uses Textual's excellent built-in themes (catppuccin-mocha, nord, dracula, etc.)
and adds unique custom themes (tron-legacy, matrix).

Built-in themes available via Ctrl+P command palette:
- catppuccin-mocha (default)
- nord, dracula, tokyo-night, gruvbox, monokai
- textual-dark, textual-light
- solarized-dark, solarized-light
- rose-pine, rose-pine-moon, rose-pine-dawn
- atom-one-dark, atom-one-light
- flexoki, textual-ansi
"""

from textual.theme import Theme

# Tron Legacy theme - Cyan/orange on dark
# Inspired by the movie's aesthetic (unique to ppxaide)
TRON_LEGACY_THEME = Theme(
    name="tron-legacy",
    primary="#6fc3df",      # Cyan - main color
    secondary="#ff9500",    # Orange - secondary
    accent="#ff9500",       # Orange accent
    foreground="#f0f0f0",   # Light gray text
    background="#0c141f",   # Deep dark blue
    surface="#1a2634",      # Dark blue surface
    panel="#243447",        # Lighter blue panel
    success="#00ff00",      # Neon green
    warning="#ff9500",      # Orange
    error="#ff3333",        # Red
    dark=True,
    variables={
        "block-cursor-text-style": "none",
    },
)

# Matrix theme - Green on black
# Classic hacker aesthetic (unique to ppxaide)
MATRIX_THEME = Theme(
    name="matrix",
    primary="#00ff00",      # Bright green
    secondary="#008000",    # Darker green
    accent="#00ff00",       # Bright green accent
    foreground="#00ff00",   # Green text
    background="#000000",   # Pure black
    surface="#0a0a0a",      # Almost black
    panel="#141414",        # Dark gray
    success="#00ff00",      # Green
    warning="#ffff00",      # Yellow (for contrast)
    error="#ff0000",        # Red
    dark=True,
    variables={
        "block-cursor-text-style": "none",
    },
)

# Custom themes to register (unique to ppxaide)
CUSTOM_THEMES = {
    "tron-legacy": TRON_LEGACY_THEME,
    "matrix": MATRIX_THEME,
}

# Default theme (uses Textual built-in)
DEFAULT_THEME = "catppuccin-mocha"

# Curated list for Ctrl+T cycling (mix of built-in and custom)
# Users can access all themes via Ctrl+P command palette
CYCLE_THEMES = [
    "catppuccin-mocha",  # Default - clean, professional
    "dracula",           # Popular dark theme
    "tokyo-night",       # Modern aesthetic
    "nord",              # Arctic blues
    "tron-legacy",       # Custom: cyan/orange
    "matrix",            # Custom: green/black
    "gruvbox",           # Warm retro colors
    "monokai",           # Classic editor theme
]

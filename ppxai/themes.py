"""
Theme system for ppxai TUI.

Provides Theme dataclass and built-in themes for customizing the terminal UI appearance.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class Theme:
    """TUI theme configuration.

    Defines colors and styles for all UI components. Uses Rich markup syntax
    for colors (e.g., "white on blue", "cyan", "bold green").
    """
    name: str

    # Message styles
    user_style: str           # Border color for user messages
    user_title: str           # Title text for user messages
    assistant_style: str      # Border color for assistant messages
    assistant_title: str      # Title text for assistant messages
    system_style: str         # Border color for system messages
    system_title: str         # Title text for system messages

    # Badge styles (Rich markup: "foreground on background")
    provider_badge: str       # Provider name badge
    model_badge: str          # Model name badge
    tools_on_badge: str       # Tools enabled badge
    tools_off_badge: str      # Tools disabled badge
    usage_badge: str          # Usage statistics badge
    agent_badge: str          # Agent mode badge
    checkpoint_badge: str     # Checkpoint status badge

    # Header/footer
    header_style: str         # Header panel style
    footer_style: str         # Footer/status line style

    # Code blocks
    code_theme: str           # Pygments theme name for syntax highlighting

    # Accent colors for special elements
    link_style: str           # Hyperlink style
    error_style: str          # Error message style
    warning_style: str        # Warning message style
    success_style: str        # Success message style
    info_style: str           # Info message style


# Built-in themes
THEMES: Dict[str, Theme] = {
    "standard": Theme(
        name="Standard",
        # Message styles - current ppxai colors
        user_style="blue",
        user_title="You",
        assistant_style="green",
        assistant_title="Assistant",
        system_style="yellow",
        system_title="System",
        # Badge styles
        provider_badge="white on blue",
        model_badge="white on dark_blue",
        tools_on_badge="white on green",
        tools_off_badge="white on red",
        usage_badge="white on dark_green",
        agent_badge="white on magenta",
        checkpoint_badge="white on cyan",
        # Header/footer
        header_style="dim",
        footer_style="dim",
        # Code theme
        code_theme="monokai",
        # Accents
        link_style="cyan underline",
        error_style="bold red",
        warning_style="yellow",
        success_style="green",
        info_style="cyan",
    ),

    "tron-legacy": Theme(
        name="Tron Legacy",
        # Inspired by Tron: Legacy (2010) visual design
        # Cyan: #6FC3DF (Programs/User)
        # Orange: #DF740C (Flynn/System)
        # White: #F8F8F8 (Grid/Text)
        # Dark: #0C141F (Background)
        # Message styles
        user_style="cyan",
        user_title="USER",
        assistant_style="bright_cyan",
        assistant_title="PROGRAM",
        system_style="dark_orange",
        system_title="SYSTEM",
        # Badge styles - Tron aesthetic
        provider_badge="black on cyan",
        model_badge="black on bright_cyan",
        tools_on_badge="black on bright_green",
        tools_off_badge="black on red",
        usage_badge="black on yellow",
        agent_badge="black on bright_magenta",
        checkpoint_badge="black on bright_cyan",
        # Header/footer
        header_style="cyan dim",
        footer_style="cyan dim",
        # Code theme - dark for Tron aesthetic
        code_theme="native",
        # Accents
        link_style="bright_cyan underline",
        error_style="bold red",
        warning_style="dark_orange",
        success_style="bright_green",
        info_style="bright_cyan",
    ),

    "matrix": Theme(
        name="Matrix",
        # Inspired by The Matrix (1999) - green on black
        # Message styles
        user_style="green",
        user_title="NEO",
        assistant_style="bright_green",
        assistant_title="ORACLE",
        system_style="dark_green",
        system_title="MATRIX",
        # Badge styles
        provider_badge="black on green",
        model_badge="black on bright_green",
        tools_on_badge="black on bright_green",
        tools_off_badge="black on red",
        usage_badge="black on dark_green",
        agent_badge="black on bright_green",
        checkpoint_badge="black on green",
        # Header/footer
        header_style="green dim",
        footer_style="green dim",
        # Code theme
        code_theme="native",
        # Accents
        link_style="bright_green underline",
        error_style="bold red",
        warning_style="yellow",
        success_style="bright_green",
        info_style="green",
    ),

    "nord": Theme(
        name="Nord",
        # Inspired by Nord color palette - arctic, bluish colors
        # Polar Night: #2E3440, #3B4252, #434C5E, #4C566A
        # Snow Storm: #D8DEE9, #E5E9F0, #ECEFF4
        # Frost: #8FBCBB, #88C0D0, #81A1C1, #5E81AC
        # Aurora: #BF616A (red), #D08770 (orange), #EBCB8B (yellow), #A3BE8C (green), #B48EAD (purple)
        # Message styles
        user_style="bright_blue",      # Frost blue
        user_title="You",
        assistant_style="cyan",        # Frost cyan
        assistant_title="Assistant",
        system_style="magenta",        # Aurora purple
        system_title="System",
        # Badge styles
        provider_badge="white on blue",
        model_badge="white on bright_blue",
        tools_on_badge="white on green",
        tools_off_badge="white on red",
        usage_badge="white on cyan",
        agent_badge="white on magenta",
        checkpoint_badge="white on bright_cyan",
        # Header/footer
        header_style="bright_blue dim",
        footer_style="bright_blue dim",
        # Code theme
        code_theme="nord-darker",
        # Accents
        link_style="bright_cyan underline",
        error_style="bold red",
        warning_style="yellow",
        success_style="green",
        info_style="cyan",
    ),
}


def get_theme(name: str) -> Theme:
    """Get a theme by name.

    Args:
        name: Theme name (case-insensitive)

    Returns:
        Theme instance

    Raises:
        ValueError: If theme not found
    """
    name_lower = name.lower()
    if name_lower not in THEMES:
        available = ", ".join(THEMES.keys())
        raise ValueError(f"Unknown theme '{name}'. Available: {available}")
    return THEMES[name_lower]


def list_themes() -> list[str]:
    """Get list of available theme names."""
    return list(THEMES.keys())


# Default theme
DEFAULT_THEME = "standard"

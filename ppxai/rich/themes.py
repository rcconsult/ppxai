"""
Theme system for ppxai TUI.

Provides Theme dataclass and built-in themes for customizing the terminal UI appearance.
"""

from dataclasses import dataclass


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
    version_badge: str        # Version number badge
    cwd_badge: str            # Working directory badge
    datetime_badge: str       # Date/time badge

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
THEMES: dict[str, Theme] = {
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
        version_badge="white on grey37",
        cwd_badge="white on grey30",
        datetime_badge="white on grey23",
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
        # Message styles - BOLD cyan for visibility
        user_style="bold cyan",
        user_title="◈ USER",
        assistant_style="bold bright_cyan",
        assistant_title="◈ PROGRAM",
        system_style="bold dark_orange",
        system_title="◈ SYSTEM",
        # Badge styles - Tron aesthetic
        provider_badge="black on cyan",
        model_badge="black on bright_cyan",
        tools_on_badge="black on bright_green",
        tools_off_badge="black on red",
        usage_badge="black on yellow",
        agent_badge="black on bright_magenta",
        checkpoint_badge="black on bright_cyan",
        version_badge="cyan on grey15",
        cwd_badge="bright_cyan on grey11",
        datetime_badge="cyan on grey7",
        # Header/footer
        header_style="cyan",
        footer_style="cyan",
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
        # Inspired by The Matrix (1999) - neon green on black
        # Message styles - BOLD bright green for "digital rain" effect
        user_style="bold green",
        user_title="▶ NEO",
        assistant_style="bold bright_green",
        assistant_title="▶ ORACLE",
        system_style="green",
        system_title="▶ MATRIX",
        # Badge styles - all green theme
        provider_badge="black on bright_green",
        model_badge="black on green",
        tools_on_badge="black on bright_green",
        tools_off_badge="bright_green on red",
        usage_badge="black on bright_green",
        agent_badge="black on bright_green",
        checkpoint_badge="black on green",
        version_badge="bright_green on grey15",
        cwd_badge="green on grey11",
        datetime_badge="bright_green on grey7",
        # Header/footer
        header_style="bright_green",
        footer_style="bright_green",
        # Code theme
        code_theme="native",
        # Accents
        link_style="bold bright_green underline",
        error_style="bold red",
        warning_style="yellow",
        success_style="bold bright_green",
        info_style="bright_green",
    ),

    "nord": Theme(
        name="Nord",
        # Inspired by Nord color palette - arctic, bluish colors
        # Using MAGENTA/PURPLE for contrast with other themes
        # Message styles
        user_style="bright_blue",
        user_title="❄ You",
        assistant_style="bright_magenta",  # Purple for contrast!
        assistant_title="❄ Assistant",
        system_style="yellow",
        system_title="❄ System",
        # Badge styles - purple accents
        provider_badge="white on blue",
        model_badge="white on bright_magenta",
        tools_on_badge="white on green",
        tools_off_badge="white on red",
        usage_badge="white on bright_magenta",
        agent_badge="white on magenta",
        checkpoint_badge="white on bright_blue",
        version_badge="white on grey37",
        cwd_badge="bright_magenta on grey30",
        datetime_badge="white on grey23",
        # Header/footer
        header_style="bright_magenta",
        footer_style="bright_magenta",
        # Code theme
        code_theme="nord-darker",
        # Accents
        link_style="bright_magenta underline",
        error_style="bold red",
        warning_style="yellow",
        success_style="green",
        info_style="bright_magenta",
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

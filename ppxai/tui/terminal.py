"""
Terminal capability detection for ppxaide.

Detects terminal features like:
- Image display protocols (iTerm2, Kitty, Sixel)
- True color support
- Unicode support
- Terminal emulator identification
"""

import os
from dataclasses import dataclass
from enum import Enum, auto
import sys  # noqa: F401 — patched by tests


class ImageProtocol(Enum):
    """Supported image display protocols."""
    NONE = auto()      # No image support
    ITERM2 = auto()    # iTerm2 inline images (OSC 1337)
    KITTY = auto()     # Kitty graphics protocol
    SIXEL = auto()     # Sixel graphics (older, widely supported)


@dataclass
class TerminalCapabilities:
    """Terminal capability information."""
    name: str                          # Terminal emulator name
    true_color: bool                   # 24-bit color support
    unicode: bool                      # Unicode support
    image_protocol: ImageProtocol      # Best available image protocol
    osc_hyperlinks: bool               # OSC 8 hyperlink support
    mouse: bool                        # Mouse support
    bracketed_paste: bool              # Bracketed paste mode


def get_user_terminal_override() -> str | None:
    """Get user-configured terminal override from environment.

    Returns:
        Terminal name if PPXAI_TERMINAL is set and not 'auto', None otherwise
    """
    override = os.environ.get("PPXAI_TERMINAL", "").strip()
    if override and override.lower() != "auto":
        return override
    return None


def get_user_protocol_override() -> ImageProtocol | None:
    """Get user-configured image protocol override from environment.

    Returns:
        ImageProtocol if PPXAI_IMAGE_PROTOCOL is set and not 'auto', None otherwise
    """
    override = os.environ.get("PPXAI_IMAGE_PROTOCOL", "").strip().lower()
    if not override or override == "auto":
        return None

    protocol_map = {
        "iterm2": ImageProtocol.ITERM2,
        "kitty": ImageProtocol.KITTY,
        "sixel": ImageProtocol.SIXEL,
        "none": ImageProtocol.NONE,
    }
    return protocol_map.get(override)


def detect_terminal() -> str:
    """Detect the terminal emulator name.

    Respects PPXAI_TERMINAL environment variable override.

    Returns:
        Terminal emulator name or 'unknown'
    """
    # Check for user override first
    user_override = get_user_terminal_override()
    if user_override:
        return user_override

    # Check common environment variables
    term_program = os.environ.get("TERM_PROGRAM", "")

    if term_program:
        return term_program

    # Check for Windows Terminal (sets WT_SESSION)
    if os.environ.get("WT_SESSION"):
        return "Windows Terminal"

    # Check for Kitty
    if os.environ.get("KITTY_WINDOW_ID"):
        return "kitty"

    # Check for tmux
    if os.environ.get("TMUX"):
        return "tmux"

    # Check for screen
    if os.environ.get("STY"):
        return "screen"

    # Check TERM variable
    term = os.environ.get("TERM", "")
    if "xterm" in term:
        return "xterm"
    if "linux" in term:
        return "linux-console"

    return "unknown"


def detect_true_color() -> bool:
    """Detect if terminal supports 24-bit true color.

    Returns:
        True if true color is supported
    """
    colorterm = os.environ.get("COLORTERM", "")
    if colorterm in ("truecolor", "24bit"):
        return True

    term = os.environ.get("TERM", "")
    if "256color" in term or "truecolor" in term:
        return True

    # Known true color terminals
    term_program = os.environ.get("TERM_PROGRAM", "")
    true_color_terminals = {
        "iTerm.app", "Apple_Terminal", "vscode", "WezTerm",
        "Hyper", "Alacritty", "kitty"
    }

    if term_program in true_color_terminals:
        return True

    if os.environ.get("KITTY_WINDOW_ID"):
        return True

    # Windows Terminal supports true color
    if os.environ.get("WT_SESSION"):
        return True

    return False


def detect_image_protocol() -> ImageProtocol:
    """Detect the best available image display protocol.

    Respects PPXAI_IMAGE_PROTOCOL environment variable override.

    Returns:
        The best available ImageProtocol
    """
    # Check for user override first
    user_override = get_user_protocol_override()
    if user_override is not None:
        return user_override

    term_program = os.environ.get("TERM_PROGRAM", "")

    # iTerm2 and compatible terminals
    if term_program in ("iTerm.app", "WezTerm", "mintty"):
        return ImageProtocol.ITERM2

    # Kitty terminal
    if os.environ.get("KITTY_WINDOW_ID") or term_program == "kitty":
        return ImageProtocol.KITTY

    # Check for Sixel support (many terminals)
    # Note: Proper detection requires terminal query, but these are known to support it
    sixel_terminals = {"mlterm", "xterm", "foot", "contour"}
    if term_program.lower() in sixel_terminals:
        return ImageProtocol.SIXEL

    # Check TERM for sixel hint
    term = os.environ.get("TERM", "")
    if "sixel" in term.lower():
        return ImageProtocol.SIXEL

    # Windows Terminal has experimental Sixel (requires settings.json: experimental.enableImages)
    # We can't detect if it's enabled, so report as available but experimental
    if os.environ.get("WT_SESSION"):
        return ImageProtocol.SIXEL

    return ImageProtocol.NONE


def detect_osc_hyperlinks() -> bool:
    """Detect if terminal supports OSC 8 hyperlinks.

    Returns:
        True if OSC 8 hyperlinks are likely supported
    """
    term_program = os.environ.get("TERM_PROGRAM", "")

    # Known OSC 8 supporting terminals
    osc8_terminals = {
        "iTerm.app", "WezTerm", "vscode", "Hyper",
        "Alacritty", "kitty", "foot", "contour"
    }

    if term_program in osc8_terminals:
        return True

    if os.environ.get("KITTY_WINDOW_ID"):
        return True

    # Recent GNOME Terminal versions support it
    if os.environ.get("GNOME_TERMINAL_SCREEN"):
        return True

    # Windows Terminal supports OSC 8 hyperlinks
    if os.environ.get("WT_SESSION"):
        return True

    return False


def detect_capabilities() -> TerminalCapabilities:
    """Detect all terminal capabilities.

    Returns:
        TerminalCapabilities with detected features
    """
    name = detect_terminal()

    return TerminalCapabilities(
        name=name,
        true_color=detect_true_color(),
        unicode=True,  # Assume unicode support (most modern terminals)
        image_protocol=detect_image_protocol(),
        osc_hyperlinks=detect_osc_hyperlinks(),
        mouse=True,    # Assume mouse support (Textual handles this)
        bracketed_paste=True,  # Assume bracketed paste (most modern terminals)
    )


def can_display_images() -> bool:
    """Quick check if terminal can display images.

    Returns:
        True if any image protocol is available
    """
    return detect_image_protocol() != ImageProtocol.NONE


def get_image_protocol_name() -> str:
    """Get the name of the detected image protocol.

    Returns:
        Protocol name string
    """
    protocol = detect_image_protocol()
    return {
        ImageProtocol.NONE: "none",
        ImageProtocol.ITERM2: "iterm2",
        ImageProtocol.KITTY: "kitty",
        ImageProtocol.SIXEL: "sixel",
    }[protocol]


# Cached capabilities (detected once at import)
_capabilities: TerminalCapabilities | None = None


def get_capabilities() -> TerminalCapabilities:
    """Get cached terminal capabilities.

    Returns:
        TerminalCapabilities (cached after first call)
    """
    global _capabilities
    if _capabilities is None:
        _capabilities = detect_capabilities()
    return _capabilities


def format_capabilities() -> str:
    """Format terminal capabilities as a human-readable string.

    Returns:
        Formatted string with capability information
    """
    caps = get_capabilities()

    # Check for user overrides
    terminal_override = get_user_terminal_override()
    protocol_override = get_user_protocol_override()

    lines = [
        f"Terminal: {caps.name}",
    ]

    if terminal_override:
        lines.append(f"  (override via PPXAI_TERMINAL={terminal_override})")

    lines.extend([
        f"True Color: {'yes' if caps.true_color else 'no'}",
        f"Unicode: {'yes' if caps.unicode else 'no'}",
        f"Image Protocol: {get_image_protocol_name()}",
    ])

    if protocol_override is not None:
        lines.append("  (override via PPXAI_IMAGE_PROTOCOL)")

    lines.extend([
        f"OSC 8 Hyperlinks: {'yes' if caps.osc_hyperlinks else 'no'}",
        f"Mouse: {'yes' if caps.mouse else 'no'}",
    ])

    return "\n".join(lines)


def get_terminal_help() -> str:
    """Get help text for configuring terminal image display.

    Returns:
        Help text with configuration instructions
    """
    caps = get_capabilities()
    protocol = detect_image_protocol()

    lines = [
        "## Terminal Image Configuration",
        "",
        f"**Detected Terminal:** {caps.name}",
        f"**Image Protocol:** {get_image_protocol_name()}",
        "",
    ]

    # Check environment variables
    term_program = os.environ.get("TERM_PROGRAM", "(not set)")
    wt_session = "yes" if os.environ.get("WT_SESSION") else "no"
    kitty_id = "yes" if os.environ.get("KITTY_WINDOW_ID") else "no"

    lines.extend([
        "### Environment Variables",
        f"- `TERM_PROGRAM`: {term_program}",
        f"- `WT_SESSION`: {wt_session}",
        f"- `KITTY_WINDOW_ID`: {kitty_id}",
        "",
    ])

    # User overrides
    terminal_override = os.environ.get("PPXAI_TERMINAL", "(not set)")
    protocol_override = os.environ.get("PPXAI_IMAGE_PROTOCOL", "(not set)")

    lines.extend([
        "### User Overrides",
        f"- `PPXAI_TERMINAL`: {terminal_override}",
        f"- `PPXAI_IMAGE_PROTOCOL`: {protocol_override}",
        "",
    ])

    # Recommendations based on current state
    if protocol == ImageProtocol.NONE:
        lines.extend([
            "### Recommendations",
            "",
            "No image protocol detected. Options:",
            "",
            "1. **Use a supported terminal:**",
            "   - [WezTerm](https://wezfurlong.org/wezterm/) (Windows/macOS/Linux)",
            "   - [iTerm2](https://iterm2.com/) (macOS)",
            "   - [Kitty](https://sw.kovidgoyal.net/kitty/) (macOS/Linux)",
            "   - Windows Terminal (enable Sixel in settings)",
            "",
            "2. **Force a protocol** (if your terminal supports it):",
            "   ```",
            "   # In ~/.ppxai/.env",
            "   PPXAI_IMAGE_PROTOCOL=sixel",
            "   ```",
            "",
        ])
    elif protocol == ImageProtocol.ITERM2 and "wezterm" not in caps.name.lower():
        if os.environ.get("TERM_PROGRAM", "").lower() != "wezterm":
            lines.extend([
                "### WezTerm Users",
                "",
                "If using WezTerm, ensure `TERM_PROGRAM` is set:",
                "",
                "```lua",
                "-- ~/.wezterm.lua",
                "config.set_environment_variables = {",
                "  TERM_PROGRAM = 'WezTerm',",
                "}",
                "```",
                "",
            ])

    return "\n".join(lines)

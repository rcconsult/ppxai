"""
Enhanced UI components for ppxai TUI.

Provides reusable Rich-based components with theme support:
- Message panels with rounded corners
- Status badges for header
- Header/footer rendering
- Emoji width normalization for terminal alignment

This module is designed to be imported by ui.py without breaking existing functionality.
"""

import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from ..common.format import format_usage_badge
from .themes import DEFAULT_THEME, Theme, get_theme

# Single temp file for copy link feature (v1.15.0)
# Gets overwritten with each new assistant response - no accumulation
_TEMP_MSG_FILE = Path(tempfile.gettempdir()) / "ppxai-last-response.md"


def normalize_emoji_width(text: str) -> str:
    """
    Normalize emoji widths for consistent terminal panel rendering.

    Emojis can cause panel misalignment because:
    1. Variation selectors (U+FE0F) affect width calculation differently
       in Rich vs actual terminal rendering
    2. Zero-Width Joiner (ZWJ) sequences create compound emojis with
       unpredictable widths (e.g., family emojis 👨‍👩‍👧‍👦)

    This function:
    - Strips variation selectors (U+FE0F) which force emoji presentation
    - The base characters remain and render correctly

    Args:
        text: Text containing emojis

    Returns:
        Text with normalized emoji widths

    Examples:
        >>> normalize_emoji_width("Warning ⚠️")  # U+26A0 + U+FE0F
        'Warning ⚠'  # U+26A0 only
    """
    if not text:
        return text

    # Remove variation selector-16 (U+FE0F)
    # This selector forces emoji-style rendering but causes width calculation issues
    result = text.replace('\ufe0f', '')

    return result


def normalize_zwj_emojis(text: str) -> str:
    """
    Simplify ZWJ (Zero-Width Joiner) emoji sequences.

    ZWJ sequences combine multiple emojis into one (e.g., family, professions).
    These often have unpredictable widths. This function replaces them with
    simpler single-character emojis.

    Args:
        text: Text containing ZWJ emojis

    Returns:
        Text with simplified emojis

    Examples:
        >>> normalize_zwj_emojis("Family: 👨‍👩‍👧‍👦")
        'Family: 👪'
    """
    if not text:
        return text

    # Pattern: person + ZWJ + person/child combinations -> family emoji
    # This handles: 👨‍👩‍👧, 👨‍👩‍👧‍👦, 👩‍👩‍👧, etc.
    zwj_pattern = r'[\U0001F468\U0001F469](?:\u200d[\U0001F466-\U0001F469\U0001F467])+'
    result = re.sub(zwj_pattern, '👪', text)

    # Handle other common ZWJ sequences (professions, etc.)
    # Person + ZWJ + object -> just the person
    profession_pattern = r'([\U0001F468\U0001F469\U0001F9D1])\u200d[\U0001F3A8-\U0001FAF8]'
    result = re.sub(profession_pattern, r'\1', result)

    return result


# Mapping from emojis to single-width text symbols
# These symbols render at exactly 1 cell in monospace fonts
EMOJI_TO_TEXT_SYMBOL = {
    # Warning/Caution
    '⚠️': '!',
    '⚠': '!',
    '\u26a0': '!',  # warning sign
    '⛔': 'X',
    '🚫': 'X',
    '❌': 'X',
    '❎': 'X',

    # Success/Positive
    '✅': '*',
    '✓': '*',
    '✔️': '*',
    '✔': '*',
    '👍': '+',
    '💚': '*',
    '💙': '*',

    # Info/Note
    'ℹ️': 'i',
    'ℹ': 'i',
    '💡': '*',
    '📝': '>',
    '📌': '>',

    # Error/Negative
    '🔴': 'o',
    '🟠': 'o',
    '🟡': 'o',
    '🟢': 'o',
    '🔵': 'o',
    '⭕': 'o',
    '👎': '-',
    '💔': 'x',

    # Actions
    '🔄': '~',
    '🔃': '~',
    '♻️': '~',
    '🔁': '~',
    '⏳': '-',
    '⏰': '@',
    '🕐': '@',

    # Files/Folders
    '📁': '/',
    '📂': '/',
    '📄': '#',
    '📃': '#',
    '📋': '#',

    # Stars/Rating
    '⭐': '*',
    '🌟': '*',
    '✨': '*',
    '💫': '*',
    '★': '*',
    '☆': '*',

    # Arrows (keep as-is, these are safe)
    '→': '>',
    '←': '<',
    '↑': '^',
    '↓': 'v',

    # Common compound emojis
    '👨‍👩‍👧': '+',
    '👨‍👩‍👧‍👦': '+',
    '👪': '+',

    # Misc
    '🎉': '!',
    '🎊': '!',
    '🔥': '!',
    '💥': '!',
    '🚀': '>',
    '⚡': '!',
    '💻': '#',
    '🖥️': '#',
    '⌨️': '#',
    '🔧': '%',
    '🔨': '%',
    '⚙️': '%',
    '⚙': '%',
    '🔒': '#',
    '🔓': '#',
    '🔑': '#',
}


def emojis_to_text_symbols(text: str) -> str:
    """
    Replace emojis with single-width text symbols.

    This ensures consistent panel alignment in terminals by replacing
    variable-width emoji characters with predictable single-cell symbols.

    Args:
        text: Text containing emojis

    Returns:
        Text with emojis replaced by text symbols

    Examples:
        >>> emojis_to_text_symbols("⚠️ Warning")
        '! Warning'
        >>> emojis_to_text_symbols("✅ Done")
        '* Done'
    """
    if not text:
        return text

    result = text
    for emoji, symbol in EMOJI_TO_TEXT_SYMBOL.items():
        result = result.replace(emoji, symbol)

    return result


def sanitize_for_panel(text: str, use_text_symbols: bool = True) -> str:
    """
    Sanitize text for rendering in Rich panels.

    Applies emoji normalization to ensure panel borders align correctly.

    By default, replaces emojis with single-width text symbols for guaranteed
    alignment. Set use_text_symbols=False for legacy behavior (strip variation
    selectors only).

    Args:
        text: Text to sanitize
        use_text_symbols: Replace emojis with text symbols (recommended)

    Returns:
        Sanitized text safe for panel rendering
    """
    if not text:
        return text

    if use_text_symbols:
        # Most reliable: replace emojis with text symbols
        result = emojis_to_text_symbols(text)
    else:
        # Legacy: strip variation selectors and simplify ZWJ
        result = normalize_emoji_width(text)
        result = normalize_zwj_emojis(result)

    return result


def _save_message_for_copy(content: str) -> str | None:
    """Save message content to temp file for copy link (v1.15.0).

    Overwrites a single temp file with latest response content.
    File can be opened via file:// URL in terminal.

    Args:
        content: Message content to save

    Returns:
        file:// URL path, or None on error
    """
    try:
        _TEMP_MSG_FILE.write_text(content, encoding='utf-8')
        return f"file://{_TEMP_MSG_FILE}"
    except Exception:
        return None


# Shared console instance
console = Console()


def render_message(
    content: str,
    role: str,
    theme: Theme | None = None,
    timestamp: datetime | None = None,
    show_timestamp: bool = True,
    normalize_emojis: bool = True,
    show_copy_link: bool = True,
) -> Panel:
    """Render a chat message with rounded corners and theme styling.

    Args:
        content: Message content (markdown supported)
        role: Message role ('user', 'assistant', 'system')
        theme: Theme to use (defaults to standard)
        timestamp: Message timestamp (optional)
        show_timestamp: Whether to show timestamp in title
        normalize_emojis: Whether to normalize emoji widths for alignment
        show_copy_link: Whether to show clickable copy link (v1.15.0)

    Returns:
        Rich Panel with rounded corners
    """
    if theme is None:
        theme = get_theme(DEFAULT_THEME)

    # Determine style and title based on role
    if role == "user":
        border_style = theme.user_style
        title = theme.user_title
    elif role == "assistant":
        border_style = theme.assistant_style
        title = theme.assistant_title
    else:
        border_style = theme.system_style
        title = theme.system_title

    # Add timestamp to title if provided
    if show_timestamp and timestamp:
        time_str = timestamp.strftime("%H:%M:%S")
        title = f"{title} [{time_str}]"

    # v1.15.0: Add clickable copy link for assistant messages
    # Uses OSC 8 terminal hyperlinks to open temp file with message content
    # Only save for assistant (overwrites single temp file with latest response)
    copy_link_suffix = ""
    if show_copy_link and role == "assistant":
        # Save original content (before emoji normalization) to temp file
        file_url = _save_message_for_copy(content)
        if file_url:
            # Rich supports [link=URL]text[/link] for OSC 8 hyperlinks
            copy_link_suffix = f" [link={file_url}][dim]#[/dim][/link]"

    # Normalize emoji widths to prevent panel misalignment
    display_content = content
    if normalize_emojis:
        display_content = sanitize_for_panel(content)

    # Render content as markdown
    rendered_content = Markdown(display_content)

    # Build title with theme-specific styling
    # Title uses border color for visual consistency
    styled_title = f"[bold {border_style}]{title}[/bold {border_style}]{copy_link_suffix}"

    return Panel(
        rendered_content,
        title=styled_title,
        title_align="left",
        border_style=border_style,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def render_status_panel(
    provider: str,
    model: str,
    tools_enabled: bool = False,
    agent_mode: bool = False,
    usage_str: str | None = None,
    checkpoint_str: str | None = None,
    theme: Theme | None = None,
    version: str | None = None,
    working_dir: str | None = None,
    show_datetime: bool = False,
    context_percent: float | None = None,
    pending_files: list[Any] | None = None,
) -> Panel:
    """Render status line in a framed panel with badges.

    Args:
        provider: Provider name
        model: Model name
        tools_enabled: Whether tools are enabled
        agent_mode: Whether agent mode is active
        usage_str: Usage statistics string
        checkpoint_str: Checkpoint status
        theme: Theme to use
        version: Version string (e.g., "v1.13.5")
        working_dir: Current working directory path
        show_datetime: Whether to show current date/time
        context_percent: Context window usage percentage (v1.13.9)

    Returns:
        Rich Panel with status badges
    """
    if theme is None:
        theme = get_theme(DEFAULT_THEME)

    badges = Text()

    # Version badge (leftmost, subtle)
    if version:
        badges.append(f" {version} ", style=theme.version_badge)
        badges.append(" ")

    # Provider badge
    badges.append(f" {provider} ", style=theme.provider_badge)
    badges.append(" ")

    # Model badge
    badges.append(f" {model} ", style=theme.model_badge)
    badges.append(" ")

    # Tools badge
    if tools_enabled:
        badges.append(" Tools: ON ", style=theme.tools_on_badge)
    else:
        badges.append(" Tools: OFF ", style=theme.tools_off_badge)

    # Agent badge (only show if active)
    if agent_mode:
        badges.append(" ")
        badges.append(" Agent ", style=theme.agent_badge)

    # Checkpoint badge (only show if available)
    if checkpoint_str:
        badges.append(" ")
        badges.append(f" {checkpoint_str} ", style=theme.checkpoint_badge)

    # Usage badge
    if usage_str:
        badges.append(" ")
        badges.append(f" {usage_str} ", style=theme.usage_badge)

    # Attachment badge (v1.17.4 Phase 1) — shows every multimodal file the
    # model currently "sees" in this conversation. That's the union of two
    # sets: files staged by /attach for the next turn, AND images already
    # committed to prior turns of `session.messages`. In-context attachments
    # are re-sent (and re-billed) on every subsequent chat call, so the
    # badge intentionally persists for the whole session rather than
    # disappearing after /attach is consumed.
    #
    # Parameter is named `pending_files` for backward compat; semantically
    # it accepts any iterable of heterogeneous entries — either dataclass
    # instances with `.name` / `.kind` attributes (staged PendingFile from
    # the Rich handler) or plain dicts with `"name"` / `"kind"` keys (the
    # canonical AppState.context_attachments shape mirrored into JS/TS).
    if pending_files:
        def _field(entry, key: str, default: Any = None) -> Any:
            if isinstance(entry, dict):
                return entry.get(key, default)
            return getattr(entry, key, default)

        image_count = sum(1 for pf in pending_files if _field(pf, "kind") == "image")
        text_count = sum(1 for pf in pending_files if _field(pf, "kind") == "text")
        # Compact label: "📎 2 (1🖼 1📄)" when mixed, or "📎 2 files" when uniform.
        names = [_field(pf, "name", "?") for pf in pending_files]
        # Truncate each name to keep the badge narrow on small terminals.
        short = []
        for n in names[:3]:
            short.append(n if len(n) <= 18 else n[:15] + "...")
        names_str = ", ".join(short)
        if len(pending_files) > 3:
            names_str += f", +{len(pending_files) - 3}"
        if image_count and text_count:
            mix = f"{image_count}\U0001F5BC {text_count}\U0001F4C4"  # 🖼 📄
            label = f" \U0001F4CE {len(pending_files)} ({mix}): {names_str} "  # 📎
        else:
            label = f" \U0001F4CE {len(pending_files)}: {names_str} "  # 📎
        badges.append(" ")
        badges.append(label, style=theme.usage_badge)

    # Context usage badge (v1.13.9) - shows context window utilization
    if context_percent is not None:
        badges.append(" ")
        # Dynamic color based on percentage
        if context_percent >= 100:
            ctx_style = "white on red"
            ctx_icon = "!"
        elif context_percent >= 80:
            ctx_style = "black on yellow"
            ctx_icon = "~"
        else:
            ctx_style = "white on dark_green"
            ctx_icon = ""
        badges.append(f" Ctx: {context_percent:.0f}%{ctx_icon} ", style=ctx_style)

    # Working directory badge (compact path)
    if working_dir:
        # Shorten path for display
        path = Path(working_dir)
        # Use ~ for home directory
        try:
            home = Path.home()
            if path.is_relative_to(home):
                display_path = "~/" + str(path.relative_to(home)).replace("\\", "/")
            else:
                display_path = str(path).replace("\\", "/")
        except (ValueError, RuntimeError):
            display_path = str(path).replace("\\", "/")
        # Truncate if too long (keep last 30 chars)
        if len(display_path) > 35:
            display_path = "..." + display_path[-32:]
        badges.append(" ")
        badges.append(f" {display_path} ", style=theme.cwd_badge)

    # DateTime badge (rightmost)
    if show_datetime:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        badges.append(" ")
        badges.append(f" {now} ", style=theme.datetime_badge)

    return Panel(
        badges,
        box=box.ROUNDED,
        border_style=theme.header_style,
        padding=(0, 1),
    )


def format_usage_string(
    prompt_tokens: int,
    completion_tokens: int,
    estimated_cost: float,
) -> str:
    """Format usage statistics into a compact string.

    Thin alias kept for backward-compat with existing Rich callers.
    The actual implementation lives in `ppxai.common.format` so web
    and VSCode clients use the same logic via their JS/TS mirrors.

    Returns:
        Formatted string like "1.2K↓/0.5K↑ $0.0045"
    """
    return format_usage_badge(prompt_tokens, completion_tokens, estimated_cost)

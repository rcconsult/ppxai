"""
Enhanced UI components for ppxai TUI.

Provides reusable Rich-based components with theme support:
- Message panels with rounded corners
- Status badges for header
- Header/footer rendering

This module is designed to be imported by ui.py without breaking existing functionality.
"""

from datetime import datetime
from typing import Optional

from rich import box
from rich.console import Console, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .themes import Theme, get_theme, DEFAULT_THEME, THEMES


# Shared console instance
console = Console()


def render_message(
    content: str,
    role: str,
    theme: Optional[Theme] = None,
    timestamp: Optional[datetime] = None,
    show_timestamp: bool = True,
) -> Panel:
    """Render a chat message with rounded corners and theme styling.

    Args:
        content: Message content (markdown supported)
        role: Message role ('user', 'assistant', 'system')
        theme: Theme to use (defaults to standard)
        timestamp: Message timestamp (optional)
        show_timestamp: Whether to show timestamp in title

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

    # Render content as markdown
    rendered_content = Markdown(content)

    # Build title with theme-specific styling
    # Title uses border color for visual consistency
    styled_title = f"[bold {border_style}]{title}[/bold {border_style}]"

    return Panel(
        rendered_content,
        title=styled_title,
        title_align="left",
        border_style=border_style,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def render_badge(text: str, style: str) -> Text:
    """Render a single status badge.

    Args:
        text: Badge text
        style: Rich style (e.g., "white on blue")

    Returns:
        Rich Text with badge styling
    """
    badge = Text()
    badge.append(f" {text} ", style=style)
    return badge


def render_status_badges(
    provider: str,
    model: str,
    tools_enabled: bool = False,
    agent_mode: bool = False,
    usage_str: Optional[str] = None,
    checkpoint_str: Optional[str] = None,
    theme: Optional[Theme] = None,
) -> Text:
    """Render a row of status badges.

    Args:
        provider: Provider name (e.g., "Perplexity")
        model: Model name (e.g., "sonar-pro")
        tools_enabled: Whether tools are enabled
        agent_mode: Whether agent mode is active
        usage_str: Usage string (e.g., "1.2K↓/0.5K↑ $0.0045")
        checkpoint_str: Checkpoint status (e.g., "abc123")
        theme: Theme to use

    Returns:
        Rich Text with all badges
    """
    if theme is None:
        theme = get_theme(DEFAULT_THEME)

    badges = Text()

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
    badges.append(" ")

    # Agent badge (only show if active)
    if agent_mode:
        badges.append(" Agent ", style=theme.agent_badge)
        badges.append(" ")

    # Checkpoint badge (only show if available)
    if checkpoint_str:
        badges.append(f" {checkpoint_str} ", style=theme.checkpoint_badge)
        badges.append(" ")

    # Usage badge
    if usage_str:
        badges.append(f" {usage_str} ", style=theme.usage_badge)

    return badges


def render_header(
    version: str,
    provider: str,
    model: str,
    tools_enabled: bool = False,
    agent_mode: bool = False,
    usage_str: Optional[str] = None,
    checkpoint_str: Optional[str] = None,
    theme: Optional[Theme] = None,
) -> Panel:
    """Render the application header with status badges.

    Args:
        version: Application version (e.g., "v1.12.0")
        provider: Provider name
        model: Model name
        tools_enabled: Whether tools are enabled
        agent_mode: Whether agent mode is active
        usage_str: Usage statistics string
        checkpoint_str: Checkpoint status
        theme: Theme to use

    Returns:
        Rich Panel with header content
    """
    if theme is None:
        theme = get_theme(DEFAULT_THEME)

    # Create header grid
    header = Table.grid(expand=True)
    header.add_column(justify="left", ratio=1)
    header.add_column(justify="right", ratio=3)

    # Left: version
    title = Text(f"ppxai {version}", style="bold")

    # Right: badges
    badges = render_status_badges(
        provider=provider,
        model=model,
        tools_enabled=tools_enabled,
        agent_mode=agent_mode,
        usage_str=usage_str,
        checkpoint_str=checkpoint_str,
        theme=theme,
    )

    header.add_row(title, badges)

    return Panel(
        header,
        box=box.ROUNDED,
        style=theme.header_style,
        padding=(0, 1),
    )


def render_status_line(
    provider: str,
    model: str,
    tools_enabled: bool = False,
    agent_mode: bool = False,
    usage_str: Optional[str] = None,
    checkpoint_str: Optional[str] = None,
    theme: Optional[Theme] = None,
) -> Text:
    """Render a compact status line (for bottom of screen).

    Args:
        provider: Provider name
        model: Model name
        tools_enabled: Whether tools are enabled
        agent_mode: Whether agent mode is active
        usage_str: Usage statistics string
        checkpoint_str: Checkpoint status
        theme: Theme to use

    Returns:
        Rich Text with status line
    """
    if theme is None:
        theme = get_theme(DEFAULT_THEME)

    status = Text()
    status.append("[", style="dim")

    # Provider
    status.append(provider, style=theme.info_style)
    status.append(" | ", style="dim")

    # Model
    status.append(model, style=theme.info_style)
    status.append(" | ", style="dim")

    # Tools
    if tools_enabled:
        status.append("Tools: ON", style=theme.success_style)
    else:
        status.append("Tools: OFF", style="dim")

    # Agent mode
    if agent_mode:
        status.append(" | ", style="dim")
        status.append("Agent", style=theme.agent_badge.split(" on ")[0])

    # Checkpoint
    if checkpoint_str:
        status.append(" | ", style="dim")
        status.append(checkpoint_str, style=theme.info_style)

    # Usage
    if usage_str:
        status.append(" | ", style="dim")
        status.append(usage_str, style=theme.success_style)

    status.append("]", style="dim")

    return status


def render_input_prompt_header(theme: Optional[Theme] = None) -> str:
    """Render the top border of an input frame.

    This creates a visual frame illusion for the input prompt.
    The actual input is handled by prompt_toolkit below this border.

    Args:
        theme: Theme to use

    Returns:
        String with top border and title
    """
    if theme is None:
        theme = get_theme(DEFAULT_THEME)

    title = theme.user_title
    # Use Rich markup for the border - this gets printed before prompt_toolkit input
    return f"[{theme.user_style}]╭─ {title} ─────────────────────────────────────────────╮[/{theme.user_style}]"


def render_input_prompt_footer(theme: Optional[Theme] = None) -> str:
    """Render the bottom border of an input frame.

    Args:
        theme: Theme to use

    Returns:
        String with bottom border
    """
    if theme is None:
        theme = get_theme(DEFAULT_THEME)

    return f"[{theme.user_style}]╰───────────────────────────────────────────────────────╯[/{theme.user_style}]"


def render_status_panel(
    provider: str,
    model: str,
    tools_enabled: bool = False,
    agent_mode: bool = False,
    usage_str: Optional[str] = None,
    checkpoint_str: Optional[str] = None,
    theme: Optional[Theme] = None,
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

    Returns:
        Rich Panel with status badges
    """
    if theme is None:
        theme = get_theme(DEFAULT_THEME)

    badges = Text()

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

    return Panel(
        badges,
        box=box.ROUNDED,
        border_style=theme.header_style,
        padding=(0, 1),
    )


def render_welcome(theme: Optional[Theme] = None) -> Panel:
    """Render welcome message with theme styling.

    Args:
        theme: Theme to use

    Returns:
        Rich Panel with welcome content
    """
    if theme is None:
        theme = get_theme(DEFAULT_THEME)

    welcome_text = """
# ppxai - AI Text UI

Welcome to the AI terminal interface!

## General Commands
- Type your question or prompt to chat
- `/save` - Save session to JSON file
- `/export [filename]` - Export last answer to markdown
- `/usage` - Show current session usage statistics
- `/theme` - List or switch themes
- `/clear` - Clear conversation history
- `/model` - Change model
- `/help` - Show this help message
- `/quit` or `/exit` - Exit the application

## AI Tools
- `/tools enable` - Enable AI tools
- `/tools disable` - Disable AI tools
- `/tools list` - Show available tools

## Agent Mode
- `/agent <task>` - Execute autonomous agent task
- `/undo` - Revert last agent task
"""
    return Panel(
        Markdown(welcome_text),
        title="[bold]Welcome[/bold]",
        title_align="left",
        border_style=theme.info_style,
        box=box.ROUNDED,
        padding=(1, 2),
    )


def render_error(message: str, theme: Optional[Theme] = None) -> Panel:
    """Render an error message.

    Args:
        message: Error message
        theme: Theme to use

    Returns:
        Rich Panel with error styling
    """
    if theme is None:
        theme = get_theme(DEFAULT_THEME)

    return Panel(
        Text(message, style=theme.error_style),
        title="[bold]Error[/bold]",
        title_align="left",
        border_style="red",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def render_success(message: str, theme: Optional[Theme] = None) -> Panel:
    """Render a success message.

    Args:
        message: Success message
        theme: Theme to use

    Returns:
        Rich Panel with success styling
    """
    if theme is None:
        theme = get_theme(DEFAULT_THEME)

    return Panel(
        Text(message, style=theme.success_style),
        title="[bold]Success[/bold]",
        title_align="left",
        border_style="green",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def render_info(message: str, title: str = "Info", theme: Optional[Theme] = None) -> Panel:
    """Render an info message.

    Args:
        message: Info message
        title: Panel title
        theme: Theme to use

    Returns:
        Rich Panel with info styling
    """
    if theme is None:
        theme = get_theme(DEFAULT_THEME)

    return Panel(
        Text(message, style=theme.info_style),
        title=f"[bold]{title}[/bold]",
        title_align="left",
        border_style=theme.info_style,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def render_theme_list(current_theme: str = DEFAULT_THEME) -> Panel:
    """Render a list of available themes.

    Args:
        current_theme: Currently active theme name

    Returns:
        Rich Panel with theme list
    """
    table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
    table.add_column("Theme", style="green")
    table.add_column("Description", style="white")
    table.add_column("Status", style="yellow")

    for name, theme in THEMES.items():
        status = "← active" if name == current_theme else ""
        table.add_row(name, theme.name, status)

    return Panel(
        table,
        title="[bold]Available Themes[/bold]",
        title_align="left",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def format_usage_string(
    prompt_tokens: int,
    completion_tokens: int,
    estimated_cost: float,
) -> str:
    """Format usage statistics into a compact string.

    Args:
        prompt_tokens: Input tokens
        completion_tokens: Output tokens
        estimated_cost: Estimated cost in USD

    Returns:
        Formatted string like "1.2K↓/0.5K↑ $0.0045"
    """
    def format_tokens(n: int) -> str:
        if n >= 1000:
            return f"{n/1000:.1f}K"
        return str(n)

    prompt_str = format_tokens(prompt_tokens)
    completion_str = format_tokens(completion_tokens)

    return f"{prompt_str}↓/{completion_str}↑ ${estimated_cost:.4f}"

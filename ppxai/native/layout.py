"""
Screen layout calculations for ppxai-native.

Pure functions — no drawing, no state mutation.
"""

from dataclasses import dataclass

from ppxai.native import theme


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float


@dataclass
class LayoutRects:
    status_bar: Rect
    chat_area: Rect
    input_area: Rect
    scrollbar: Rect


def calculate_layout(screen_w: int, screen_h: int, input_lines: int = 1) -> LayoutRects:
    """Calculate layout rectangles for the three-zone UI.

    Args:
        screen_w: Current window width
        screen_h: Current window height
        input_lines: Number of lines in input buffer (affects input area height)
    """
    # Input area height scales with content
    input_content_h = max(1, input_lines) * theme.LINE_HEIGHT + theme.PADDING * 2
    input_h = max(theme.INPUT_MIN_HEIGHT, min(theme.INPUT_MAX_HEIGHT, input_content_h))

    # Status bar at top
    status = Rect(0, 0, screen_w, theme.STATUS_HEIGHT)

    # Chat area fills the middle
    chat_y = theme.STATUS_HEIGHT
    chat_h = screen_h - theme.STATUS_HEIGHT - input_h
    chat = Rect(0, chat_y, screen_w - theme.SCROLLBAR_WIDTH, max(0, chat_h))

    # Scrollbar on right edge of chat area
    scrollbar = Rect(screen_w - theme.SCROLLBAR_WIDTH, chat_y, theme.SCROLLBAR_WIDTH, max(0, chat_h))

    # Input area at bottom
    input_area = Rect(0, screen_h - input_h, screen_w, input_h)

    return LayoutRects(
        status_bar=status,
        chat_area=chat,
        input_area=input_area,
        scrollbar=scrollbar,
    )

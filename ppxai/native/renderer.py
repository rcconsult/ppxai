"""
Rendering for ppxai-native — draws UI components with Raylib.

Pure drawing functions — no state mutation.
"""

from typing import List, Tuple

import pyray as rl

from ppxai.native import theme
from ppxai.native.layout import LayoutRects
from ppxai.native.text_engine import (
    draw_wrapped_text,
    parse_markdown,
    measure_content_height,
    draw_parsed_content,
    measure_wrapped_height,
)


def draw_status_bar(font: rl.Font, layout: LayoutRects,
                    provider: str, model: str, status_text: str = "") -> None:
    """Draw the top status bar with provider/model info."""
    r = layout.status_bar
    rl.draw_rectangle(int(r.x), int(r.y), int(r.w), int(r.h), theme.STATUS_BG)

    x = r.x + theme.PADDING
    y = r.y + (r.h - theme.FONT_SIZE_STATUS) / 2
    rl.draw_text_ex(font, provider.encode("utf-8"),
                    rl.Vector2(x, y), theme.FONT_SIZE_STATUS, 1, theme.ACCENT)

    provider_w = rl.measure_text_ex(font, provider.encode("utf-8"), theme.FONT_SIZE_STATUS, 1).x
    x += provider_w + theme.PADDING
    rl.draw_text_ex(font, b"|", rl.Vector2(x, y), theme.FONT_SIZE_STATUS, 1, theme.TEXT_DIM)

    x += theme.PADDING + 8
    rl.draw_text_ex(font, model.encode("utf-8"),
                    rl.Vector2(x, y), theme.FONT_SIZE_STATUS, 1, theme.TEXT)

    if status_text:
        status_w = rl.measure_text_ex(font, status_text.encode("utf-8"), theme.FONT_SIZE_STATUS, 1).x
        rl.draw_text_ex(font, status_text.encode("utf-8"),
                        rl.Vector2(r.x + r.w - status_w - theme.PADDING, y),
                        theme.FONT_SIZE_STATUS, 1, theme.TEXT_DIM)

    rl.draw_line(int(r.x), int(r.y + r.h - 1), int(r.x + r.w), int(r.y + r.h - 1), theme.BORDER)


def draw_chat_area(font: rl.Font, font_bold: rl.Font, layout: LayoutRects,
                   messages: List[Tuple[str, str]], streaming_text: str,
                   scroll_offset: float) -> float:
    """Draw the scrollable chat area. Returns total content height."""
    r = layout.chat_area
    rl.draw_rectangle(int(r.x), int(r.y), int(r.w), int(r.h), theme.BG)

    rl.begin_scissor_mode(int(r.x), int(r.y), int(r.w), int(r.h))

    content_width = r.w - theme.PADDING * 2
    y = r.y + theme.PADDING - scroll_offset

    for role, content in messages:
        y += _draw_message(font, font_bold, r.x + theme.PADDING, y,
                           content_width, role, content, r.y, r.h)
        y += theme.MESSAGE_GAP

    if streaming_text:
        y += _draw_message(font, font_bold, r.x + theme.PADDING, y,
                           content_width, "assistant", streaming_text + "█", r.y, r.h)
        y += theme.MESSAGE_GAP

    rl.end_scissor_mode()

    total_height = (y + scroll_offset) - r.y
    return total_height


def _draw_message(font: rl.Font, font_bold: rl.Font, x: float, y: float,
                  max_width: float, role: str, content: str,
                  clip_y: float, clip_h: float) -> float:
    """Draw a single message bubble with markdown rendering. Returns height consumed."""
    if role == "user":
        role_color = theme.USER_ACCENT
        bubble_color = theme.USER_BUBBLE
        label = "You"
    elif role == "assistant":
        role_color = theme.ACCENT
        bubble_color = theme.AI_BUBBLE
        label = "AI"
    elif role == "tool":
        role_color = theme.TOOL_ACCENT
        bubble_color = theme.TOOL_BUBBLE
        label = "Tool"
    else:
        role_color = theme.TEXT_SYSTEM
        bubble_color = theme.BG
        label = ""

    # Parse markdown for AI messages
    inner_width = max_width - theme.PADDING * 2
    if role == "assistant":
        parsed = parse_markdown(content)
        text_height = measure_content_height(parsed, font, font_bold, inner_width)
    else:
        parsed = None
        text_height = measure_wrapped_height(content, font, theme.FONT_SIZE,
                                             theme.LINE_HEIGHT, inner_width)

    total_height = text_height + theme.LINE_HEIGHT + theme.PADDING

    # Bubble background
    if y + total_height >= clip_y and y <= clip_y + clip_h:
        rl.draw_rectangle_rounded(
            rl.Rectangle(x - theme.PADDING_SMALL, y,
                         max_width + theme.PADDING_SMALL, total_height),
            0.02, 4, bubble_color
        )

    # Role label
    if label:
        draw_wrapped_text(font_bold, label, x, y + theme.PADDING_SMALL,
                          theme.FONT_SIZE_SMALL, theme.LINE_HEIGHT_SMALL,
                          max_width, role_color, clip_y, clip_h)

    # Message content
    content_y = y + theme.LINE_HEIGHT
    if parsed:
        draw_parsed_content(font, font_bold, parsed, x, content_y,
                            inner_width, clip_y, clip_h)
    else:
        draw_wrapped_text(font, content, x, content_y,
                          theme.FONT_SIZE, theme.LINE_HEIGHT,
                          inner_width, theme.TEXT, clip_y, clip_h)

    return total_height


def draw_input_area(font: rl.Font, layout: LayoutRects,
                    text: str, cursor_pos: int, is_streaming: bool) -> None:
    """Draw the bottom input area with cursor."""
    r = layout.input_area
    rl.draw_rectangle(int(r.x), int(r.y), int(r.w), int(r.h), theme.INPUT_BG)
    rl.draw_line(int(r.x), int(r.y), int(r.x + r.w), int(r.y), theme.BORDER)

    text_x = r.x + theme.PADDING
    text_y = r.y + theme.PADDING

    if not text and not is_streaming:
        rl.draw_text_ex(font, b"Type a message... (Ctrl+Enter to send)",
                        rl.Vector2(text_x, text_y), theme.FONT_SIZE, 1, theme.TEXT_DIM)
        return

    content_width = r.w - theme.PADDING * 2
    draw_wrapped_text(font, text, text_x, text_y,
                      theme.FONT_SIZE, theme.LINE_HEIGHT,
                      content_width, theme.TEXT)

    # Blinking cursor
    if int(rl.get_time() * 2) % 2 == 0:
        before_cursor = text[:cursor_pos]
        lines = before_cursor.split("\n")
        last_line = lines[-1] if lines else ""
        cursor_x_offset = rl.measure_text_ex(font, last_line.encode("utf-8"),
                                              theme.FONT_SIZE, 1).x
        cursor_line = len(lines) - 1
        cx = text_x + cursor_x_offset
        cy = text_y + cursor_line * theme.LINE_HEIGHT
        rl.draw_rectangle(int(cx), int(cy), 2, theme.FONT_SIZE, theme.CURSOR)


def draw_scrollbar(layout: LayoutRects, scroll_offset: float, content_height: float) -> None:
    """Draw scrollbar indicator in the chat area."""
    r = layout.scrollbar
    if content_height <= layout.chat_area.h:
        return

    rl.draw_rectangle(int(r.x), int(r.y), int(r.w), int(r.h), theme.STATUS_BG)

    visible_ratio = layout.chat_area.h / content_height
    thumb_h = max(20, r.h * visible_ratio)
    scroll_ratio = scroll_offset / (content_height - layout.chat_area.h) if content_height > layout.chat_area.h else 0
    thumb_y = r.y + scroll_ratio * (r.h - thumb_h)

    rl.draw_rectangle_rounded(
        rl.Rectangle(r.x + 1, thumb_y, r.w - 2, thumb_h),
        0.5, 4, theme.SCROLLBAR
    )

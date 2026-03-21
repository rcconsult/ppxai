"""
Text utilities for ppxai-native — word wrapping and basic markdown.
"""

from dataclasses import dataclass
from typing import List

import pyray as rl


@dataclass
class Span:
    text: str
    style: str = "normal"  # normal, bold, code, code_block


def wrap_text(text: str, font: rl.Font, font_size: float, max_width: float) -> List[str]:
    """Word-wrap text to fit within max_width pixels."""
    if not text:
        return [""]

    lines = []
    for raw_line in text.split("\n"):
        if not raw_line:
            lines.append("")
            continue

        words = raw_line.split(" ")
        current_line = ""

        for word in words:
            test = f"{current_line} {word}".strip() if current_line else word
            size = rl.measure_text_ex(font, test.encode("utf-8"), font_size, 1)
            if size.x > max_width and current_line:
                lines.append(current_line)
                current_line = word
            else:
                current_line = test

        if current_line:
            lines.append(current_line)

    return lines if lines else [""]


def measure_wrapped_height(text: str, font: rl.Font, font_size: float,
                           line_height: float, max_width: float) -> float:
    """Calculate the pixel height of wrapped text."""
    lines = wrap_text(text, font, font_size, max_width)
    return len(lines) * line_height


def draw_wrapped_text(font: rl.Font, text: str, x: float, y: float,
                      font_size: float, line_height: float,
                      max_width: float, color: rl.Color,
                      clip_y: float = 0, clip_h: float = 99999) -> float:
    """Draw word-wrapped text, returning total height drawn.

    Args:
        clip_y: Top of visible area (skip lines above)
        clip_h: Height of visible area (skip lines below)
    """
    lines = wrap_text(text, font, font_size, max_width)
    drawn_height = 0.0

    for line in lines:
        line_y = y + drawn_height
        # Only draw if within visible clip region
        if line_y + line_height >= clip_y and line_y <= clip_y + clip_h:
            rl.draw_text_ex(font, line.encode("utf-8"),
                            rl.Vector2(x, line_y), font_size, 1, color)
        drawn_height += line_height

    return drawn_height

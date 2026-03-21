"""
Text utilities for ppxai-native — word wrapping and basic markdown.
"""

import re
from dataclasses import dataclass, field
from typing import List

import pyray as rl

from ppxai.native import theme


@dataclass
class Span:
    text: str
    style: str = "normal"  # normal, bold, code_inline, code_block


@dataclass
class ParsedContent:
    """Parsed message content with markdown-like formatting."""
    blocks: List["Block"] = field(default_factory=list)


@dataclass
class Block:
    """A content block — either text or code."""
    kind: str = "text"  # text, code_block
    language: str = ""
    spans: List[Span] = field(default_factory=list)
    raw_text: str = ""


def parse_markdown(text: str) -> ParsedContent:
    """Parse simple markdown into blocks and spans.

    Supports:
    - ``` code blocks (with optional language hint)
    - **bold** text
    - `inline code`
    """
    content = ParsedContent()
    lines = text.split("\n")
    i = 0
    current_text_lines: List[str] = []

    while i < len(lines):
        line = lines[i]

        # Code block start
        if line.strip().startswith("```"):
            # Flush accumulated text
            if current_text_lines:
                content.blocks.append(_parse_text_block("\n".join(current_text_lines)))
                current_text_lines = []

            # Extract language hint
            lang = line.strip()[3:].strip()
            code_lines: List[str] = []
            i += 1

            # Collect until closing ```
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1

            content.blocks.append(Block(
                kind="code_block",
                language=lang,
                raw_text="\n".join(code_lines),
            ))

            if i < len(lines):
                i += 1  # skip closing ```
            continue

        current_text_lines.append(line)
        i += 1

    # Flush remaining text
    if current_text_lines:
        content.blocks.append(_parse_text_block("\n".join(current_text_lines)))

    return content


def _parse_text_block(text: str) -> Block:
    """Parse inline formatting within a text block."""
    spans: List[Span] = []
    # Split on **bold** and `code` patterns
    # Pattern: match **text**, `text`, or plain text
    pattern = r'(\*\*.*?\*\*|`[^`]+`)'
    parts = re.split(pattern, text)

    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            spans.append(Span(text=part[2:-2], style="bold"))
        elif part.startswith("`") and part.endswith("`"):
            spans.append(Span(text=part[1:-1], style="code_inline"))
        else:
            spans.append(Span(text=part, style="normal"))

    return Block(kind="text", spans=spans, raw_text=text)


# =============================================================================
# Drawing functions
# =============================================================================

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


def measure_content_height(content: ParsedContent, font: rl.Font, font_bold: rl.Font,
                           max_width: float) -> float:
    """Calculate total height of parsed markdown content."""
    total = 0.0
    for block in content.blocks:
        if block.kind == "code_block":
            lines = block.raw_text.split("\n")
            total += len(lines) * theme.LINE_HEIGHT + theme.PADDING * 2 + theme.PADDING_SMALL
        else:
            total += measure_wrapped_height(block.raw_text, font, theme.FONT_SIZE,
                                            theme.LINE_HEIGHT, max_width)
    return total


def draw_parsed_content(font: rl.Font, font_bold: rl.Font,
                        content: ParsedContent, x: float, y: float,
                        max_width: float, clip_y: float, clip_h: float) -> float:
    """Draw parsed markdown content, returning total height."""
    cursor_y = y

    for block in content.blocks:
        if block.kind == "code_block":
            cursor_y += _draw_code_block(font, block, x, cursor_y,
                                         max_width, clip_y, clip_h)
            cursor_y += theme.PADDING_SMALL
        else:
            cursor_y += _draw_text_block(font, font_bold, block, x, cursor_y,
                                         max_width, clip_y, clip_h)

    return cursor_y - y


def _draw_code_block(font: rl.Font, block: Block, x: float, y: float,
                     max_width: float, clip_y: float, clip_h: float) -> float:
    """Draw a code block with background rectangle."""
    lines = block.raw_text.split("\n")
    block_h = len(lines) * theme.LINE_HEIGHT + theme.PADDING * 2
    pad = theme.PADDING_SMALL

    # Background rectangle (only if visible)
    if y + block_h >= clip_y and y <= clip_y + clip_h:
        rl.draw_rectangle_rounded(
            rl.Rectangle(x - pad, y, max_width + pad * 2, block_h),
            0.01, 4, theme.CODE_BG
        )
        # Language label
        if block.language:
            rl.draw_text_ex(font, block.language.encode("utf-8"),
                            rl.Vector2(x + max_width - 80, y + 4),
                            theme.FONT_SIZE_SMALL, 1, theme.TEXT_DIM)

    # Draw code lines
    code_y = y + theme.PADDING
    for line in lines:
        if code_y + theme.LINE_HEIGHT >= clip_y and code_y <= clip_y + clip_h:
            rl.draw_text_ex(font, line.encode("utf-8"),
                            rl.Vector2(x + theme.PADDING, code_y),
                            theme.FONT_SIZE, 1, theme.TEXT)
        code_y += theme.LINE_HEIGHT

    return block_h


def _draw_text_block(font: rl.Font, font_bold: rl.Font, block: Block,
                     x: float, y: float, max_width: float,
                     clip_y: float, clip_h: float) -> float:
    """Draw a text block with inline formatting (bold, code)."""
    # For simplicity, draw the raw text with wrapping.
    # Inline formatting is applied per-span on each wrapped line.
    # Full per-span wrapping is complex; start with plain text + bold detection.
    total_height = 0.0

    for span in block.spans:
        if span.style == "bold":
            h = draw_wrapped_text(font_bold, span.text, x, y + total_height,
                                  theme.FONT_SIZE, theme.LINE_HEIGHT,
                                  max_width, theme.ACCENT, clip_y, clip_h)
        elif span.style == "code_inline":
            # Draw with code background on each line
            h = _draw_inline_code(font, span.text, x, y + total_height,
                                  max_width, clip_y, clip_h)
        else:
            h = draw_wrapped_text(font, span.text, x, y + total_height,
                                  theme.FONT_SIZE, theme.LINE_HEIGHT,
                                  max_width, theme.TEXT, clip_y, clip_h)
        total_height += h

    return total_height


def _draw_inline_code(font: rl.Font, text: str, x: float, y: float,
                      max_width: float, clip_y: float, clip_h: float) -> float:
    """Draw inline code with a subtle background."""
    lines = wrap_text(text, font, theme.FONT_SIZE, max_width)
    total_height = 0.0

    for line in lines:
        line_y = y + total_height
        if line_y + theme.LINE_HEIGHT >= clip_y and line_y <= clip_y + clip_h:
            text_w = rl.measure_text_ex(font, line.encode("utf-8"), theme.FONT_SIZE, 1).x
            rl.draw_rectangle_rounded(
                rl.Rectangle(x - 2, line_y, text_w + 4, theme.LINE_HEIGHT),
                0.1, 4, theme.CODE_BG
            )
            rl.draw_text_ex(font, line.encode("utf-8"),
                            rl.Vector2(x, line_y), theme.FONT_SIZE, 1, theme.ACCENT)
        total_height += theme.LINE_HEIGHT

    return total_height


def draw_wrapped_text(font: rl.Font, text: str, x: float, y: float,
                      font_size: float, line_height: float,
                      max_width: float, color: rl.Color,
                      clip_y: float = 0, clip_h: float = 99999) -> float:
    """Draw word-wrapped text, returning total height drawn."""
    lines = wrap_text(text, font, font_size, max_width)
    drawn_height = 0.0

    for line in lines:
        line_y = y + drawn_height
        if line_y + line_height >= clip_y and line_y <= clip_y + clip_h:
            rl.draw_text_ex(font, line.encode("utf-8"),
                            rl.Vector2(x, line_y), font_size, 1, color)
        drawn_height += line_height

    return drawn_height

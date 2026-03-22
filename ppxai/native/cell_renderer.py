"""
Cell grid renderer for ppxai-native — draws terminal cells from pyte screen buffer.

Uses draw_text_codepoint for pixel-perfect grid alignment. Each character is
placed at exactly (col * cell_w, row * cell_h) regardless of the font's
internal advance metrics. This prevents the spacing drift that occurs with
draw_text_ex on long strings.
"""

from typing import Dict, Tuple

import pyray as rl

from ppxai.native import theme


# pyte color names → RGB tuples (xterm-256 standard colors)
_NAMED_COLORS: Dict[str, Tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "red": (205, 49, 49),
    "green": (13, 188, 121),
    "yellow": (229, 229, 16),
    "blue": (36, 114, 200),
    "magenta": (188, 63, 188),
    "cyan": (17, 168, 205),
    "white": (229, 229, 229),
    "brightblack": (102, 102, 102),
    "brightred": (241, 76, 76),
    "brightgreen": (35, 209, 139),
    "brightyellow": (245, 245, 67),
    "brightblue": (59, 142, 234),
    "brightmagenta": (214, 112, 214),
    "brightcyan": (41, 184, 219),
    "brightwhite": (255, 255, 255),
}

_DEFAULT_FG = (205, 214, 244)
_DEFAULT_BG = (30, 30, 46)


def _resolve_color(color: str, is_fg: bool) -> Tuple[int, int, int]:
    """Convert pyte color string to RGB tuple."""
    if color == "default":
        return _DEFAULT_FG if is_fg else _DEFAULT_BG
    named = _NAMED_COLORS.get(color)
    if named is not None:
        return named
    if len(color) == 6:
        try:
            return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
        except ValueError:
            pass
    return _DEFAULT_FG if is_fg else _DEFAULT_BG


def draw_screen(
    font: rl.Font,
    font_bold: rl.Font,
    screen: object,
    cell_w: float,
    cell_h: float,
    offset_x: float,
    offset_y: float,
    font_size: float,
) -> None:
    """Draw the terminal cell grid from pyte screen buffer.

    Each character is drawn at its exact grid position using
    draw_text_codepoint for pixel-perfect monospace alignment.
    """
    buffer = screen.buffer
    default_bg = rl.Color(_DEFAULT_BG[0], _DEFAULT_BG[1], _DEFAULT_BG[2], 255)
    icw = int(cell_w)
    ich = int(cell_h)
    ix0 = int(offset_x)
    row_w = screen.columns * icw

    for row_idx in range(screen.lines):
        row = buffer[row_idx]
        iy = int(row_idx * cell_h + offset_y)

        # Full-row default background
        rl.draw_rectangle(ix0, iy, row_w, ich, default_bg)

        # Scissor clip to row bounds (prevents box-drawing overflow)
        rl.begin_scissor_mode(ix0, iy, row_w, ich)

        # First pass: draw non-default backgrounds
        for col_idx in range(screen.columns):
            cell = row[col_idx]
            bg = _resolve_color(cell.bg, False)
            fg = _resolve_color(cell.fg, True)
            if cell.reverse:
                bg, fg = fg, bg
            if bg != _DEFAULT_BG:
                ix = ix0 + col_idx * icw
                rl.draw_rectangle(ix, iy, icw, ich, rl.Color(bg[0], bg[1], bg[2], 255))

        # Second pass: draw characters
        for col_idx in range(screen.columns):
            cell = row[col_idx]
            ch = cell.data
            if not ch or ch == " ":
                continue

            cp = ord(ch)
            fg = _resolve_color(cell.fg, True)
            bg = _resolve_color(cell.bg, False)
            if cell.reverse:
                fg, bg = bg, fg

            fg_color = rl.Color(fg[0], fg[1], fg[2], 255)
            draw_font = font_bold if cell.bold else font
            ix = ix0 + col_idx * icw

            rl.draw_text_codepoint(draw_font, cp, rl.Vector2(ix, iy), font_size, fg_color)

            if cell.underscore:
                rl.draw_line(ix, iy + ich - 2, ix + icw, iy + ich - 2, fg_color)

            if cell.strikethrough:
                rl.draw_line(ix, iy + ich // 2, ix + icw, iy + ich // 2, fg_color)

        rl.end_scissor_mode()


def draw_cursor(
    cell_w: float,
    cell_h: float,
    cursor_x: int,
    cursor_y: int,
    offset_x: float,
    offset_y: float,
    hidden: bool,
) -> None:
    """Draw the terminal cursor."""
    if hidden:
        return
    if int(rl.get_time() * 2) % 2 != 0:
        return

    x = int(cursor_x * cell_w + offset_x)
    y = int(cursor_y * cell_h + offset_y)

    rl.draw_rectangle(
        x, y, int(cell_w), int(cell_h),
        rl.Color(theme.CURSOR.r, theme.CURSOR.g, theme.CURSOR.b, 180),
    )

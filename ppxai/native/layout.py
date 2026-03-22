"""
Screen layout calculations for ppxai-native.

In terminal emulator mode, layout is simplified to cell grid dimensions.
The terminal handles its own internal layout (status bar, chat area, input).
"""

from ppxai.native import theme


def calculate_grid(
    screen_w: int, screen_h: int, cell_w: float, cell_h: float,
) -> tuple:
    """Calculate terminal grid dimensions (cols, rows) from screen size.

    Args:
        screen_w: Window width in pixels
        screen_h: Window height in pixels
        cell_w: Width of one monospace cell in pixels
        cell_h: Height of one monospace cell in pixels

    Returns:
        (cols, rows) tuple
    """
    pad = theme.CELL_PADDING
    usable_w = screen_w - 2 * pad
    usable_h = screen_h - 2 * pad
    cols = max(20, int(usable_w / cell_w))
    rows = max(5, int(usable_h / cell_h))
    return cols, rows

"""iTerm2 inline image protocol Rich Renderable.

This module implements the iTerm2 inline image protocol as a Rich Renderable,
using the same integration technique as textual-image's Sixel renderer.

Supported terminals:
- iTerm2 (macOS)
- WezTerm (cross-platform)
- mintty (Windows)

Protocol specification:
    ESC ] 1337 ; File = [arguments] : <base64-data> BEL

References:
- https://iterm2.com/documentation-images.html
- https://wezterm.org/imgcat.html
"""

import base64
import io
import logging
from pathlib import Path
from typing import Tuple, Union

from rich.console import Console, ConsoleOptions, RenderResult
from rich.control import Control
from rich.measure import Measurement
from rich.segment import ControlType, Segment

try:
    from PIL import Image as PILImageType
except ImportError:
    PILImageType = None

# No-op control code that tricks Rich into passing our escape sequence through unchanged
# This is the same technique used by textual-image for Sixel rendering
_NULL_CONTROL = [(ControlType.CURSOR_FORWARD, 0)]


def _get_cell_size() -> Tuple[int, int]:
    """Get terminal cell size in pixels.

    Returns:
        Tuple of (cell_width, cell_height) in pixels.
        Defaults to (10, 20) if detection fails.
    """
    # Try to get from textual-image if available
    try:
        from textual_image._terminal import get_cell_size
        sizes = get_cell_size()
        if sizes:
            return (sizes.width, sizes.height)
    except ImportError:
        pass

    # Default cell size (reasonable for most terminals)
    return (10, 20)


class ITerm2Image:
    """Rich Renderable that outputs iTerm2 inline image escape sequences.

    This renderable uses the same integration technique as textual-image's
    Sixel renderer:
    1. Yield placeholder text to reserve space in the layout
    2. Save cursor position
    3. Move cursor back to the top of reserved area
    4. Output the iTerm2 escape sequence
    5. Restore cursor position

    Example:
        >>> from ppxai.tui.renderable.iterm2 import ITerm2Image
        >>> from rich.console import Console
        >>> from pathlib import Path
        >>>
        >>> console = Console()
        >>> img = ITerm2Image(Path('image.png'))
        >>> console.print(img)
    """

    ESC = '\x1b'
    BEL = '\x07'

    def __init__(
        self,
        image: Union[Path, bytes, "PILImageType"],
        width: Union[int, str, None] = None,
        height: Union[int, str, None] = None,
    ):
        """Initialize iTerm2 image.

        Args:
            image: Path to image file, raw bytes, or PIL Image
            width: Width in cells, or "auto" for auto-sizing
            height: Height in cells, or "auto" for auto-sizing
        """
        self._width_spec = width
        self._height_spec = height

        # Load image data and get dimensions
        if isinstance(image, str):
            # Convert string to Path
            image = Path(image)

        if isinstance(image, Path):
            self._data = image.read_bytes()
            self._name = image.name
            self._load_dimensions_from_bytes()
        elif isinstance(image, bytes):
            self._data = image
            self._name = "image"
            self._load_dimensions_from_bytes()
        else:
            # PIL Image
            self._image_width = image.width
            self._image_height = image.height
            buf = io.BytesIO()
            image.save(buf, format='PNG')
            self._data = buf.getvalue()
            self._name = "image.png"

    def _load_dimensions_from_bytes(self) -> None:
        """Load image dimensions from bytes data."""
        try:
            from PIL import Image as PILImage
            img = PILImage.open(io.BytesIO(self._data))
            self._image_width = img.width
            self._image_height = img.height
        except Exception:
            # Default dimensions if we can't read
            self._image_width = 800
            self._image_height = 600

    def _calculate_cell_size(
        self, max_width: int, max_height: int
    ) -> Tuple[int, int]:
        """Calculate the cell size for rendering.

        Args:
            max_width: Maximum width in cells from console options
            max_height: Maximum height in cells from console options

        Returns:
            Tuple of (cell_width, cell_height)
        """
        cell_pixel_w, cell_pixel_h = _get_cell_size()

        # Calculate image aspect ratio
        aspect = self._image_height / self._image_width if self._image_width > 0 else 1.0

        # Handle width specification
        if self._width_spec is None or self._width_spec == "auto":
            # Auto-fit to available width
            cell_width = min(max_width, self._image_width // cell_pixel_w)
        elif isinstance(self._width_spec, int):
            cell_width = self._width_spec
        else:
            cell_width = max_width

        # Handle height specification
        if self._height_spec is None or self._height_spec == "auto":
            # Calculate height from width maintaining aspect ratio
            # Account for terminal cells being ~2x tall as wide
            cell_height = int(cell_width * aspect * (cell_pixel_w / cell_pixel_h))
        elif isinstance(self._height_spec, int):
            cell_height = self._height_spec
        else:
            cell_height = max_height

        # Ensure minimum size
        cell_width = max(1, min(cell_width, max_width))
        cell_height = max(1, min(cell_height, max_height))

        return cell_width, cell_height

    def _build_escape_sequence(self, cell_width: int, cell_height: int) -> str:
        """Build the iTerm2 escape sequence.

        Args:
            cell_width: Width in cells
            cell_height: Height in cells

        Returns:
            Complete escape sequence string ready to write to terminal
        """
        b64_data = base64.b64encode(self._data).decode('ascii')
        b64_name = base64.b64encode(self._name.encode()).decode('ascii')

        args = [
            f"name={b64_name}",
            f"size={len(self._data)}",
            f"width={cell_width}",
            f"height={cell_height}",
            "preserveAspectRatio=1",
            "inline=1",
        ]

        return f"{self.ESC}]1337;File={';'.join(args)}:{b64_data}{self.BEL}"

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        """Render the image using iTerm2 protocol.

        Uses the same technique as textual-image's Sixel renderer:
        1. Yield placeholder text (spaces) to reserve layout space
        2. Save cursor position
        3. Move cursor back to top of reserved area
        4. Output the iTerm2 escape sequence as a control segment
        5. Restore cursor position

        Args:
            console: Rich Console instance
            options: Console rendering options

        Yields:
            Segment objects for Rich to render
        """
        logger = logging.getLogger(__name__)

        cell_width, cell_height = self._calculate_cell_size(
            options.max_width, options.max_height
        )
        logger.debug(f"ITerm2Image.__rich_console__: cell_size={cell_width}x{cell_height}, max={options.max_width}x{options.max_height}")

        # 1. Reserve layout space with placeholder text
        # Rich needs to know how much space the image occupies
        # DEBUG: Use visible placeholder to verify rendering
        logger.debug(f"ITerm2Image: yielding {cell_height} placeholder lines of {cell_width} chars")
        for i in range(cell_height):
            yield Segment(" " * cell_width + "\n")

        # 2. Save cursor position (DEC Save Cursor)
        yield Segment("\x1b7", control=_NULL_CONTROL)

        # 3. Move cursor back to top of reserved area
        yield Control.move(0, -cell_height)

        # 4. Output the iTerm2 escape sequence
        # The _NULL_CONTROL trick makes Rich pass this through unchanged
        escape_seq = self._build_escape_sequence(cell_width, cell_height)
        yield Segment(escape_seq, control=_NULL_CONTROL)

        # 5. Restore cursor position (DEC Restore Cursor)
        yield Segment("\x1b8", control=_NULL_CONTROL)

    def __rich_measure__(
        self, console: Console, options: ConsoleOptions
    ) -> Measurement:
        """Return the render width for Rich's layout calculations.

        Args:
            console: Rich Console instance
            options: Console rendering options

        Returns:
            Measurement with min/max widths
        """
        cell_width, _ = self._calculate_cell_size(
            options.max_width, options.max_height
        )
        return Measurement(cell_width, cell_width)

    def cleanup(self) -> None:
        """No-op for API compatibility with textual-image."""
        pass

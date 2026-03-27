"""iTerm2 Image Textual Widget.

Provides a Textual widget that renders images using iTerm2 inline image protocol.
This uses the same approach as textual-image's SixelImage widget: overriding
render_lines() to inject escape sequences directly into Textual's rendering pipeline.

Note: Using Rich renderables doesn't work with Textual as it relies on printable segments.
Instead, we inject the iTerm2 escape sequence directly via render_lines().
"""

import base64
import io
import logging
from collections import namedtuple
from pathlib import Path
from typing import Any, IO, Iterable, NamedTuple, Union

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None  # type: ignore[assignment,misc]

# Image input type — includes PILImage.Image when available
_ImageInput = Union[Path, bytes, IO[bytes], Any]  # Any covers PILImage.Image

from rich.control import Control
from rich.segment import ControlType, Segment
from rich.style import Style
from textual.dom import NoScreen
from textual.geometry import Region, Size
from textual.strip import Strip
from textual.widget import Widget

logger = logging.getLogger(__name__)

_NULL_STYLE = Style()


def _get_cell_size():
    """Get terminal cell size in pixels."""
    try:
        from textual_image._terminal import get_cell_size
        sizes = get_cell_size()
        if sizes:
            return sizes
    except ImportError:
        pass

    # Return a namedtuple-like object with width/height
    CellSize = namedtuple('CellSize', ['width', 'height'])
    return CellSize(10, 20)


def _read_image_dimensions(data: bytes) -> tuple:
    """Read image dimensions from PNG/JPEG/GIF header without PIL."""
    import struct
    if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
        # PNG: width and height at bytes 16-23 in IHDR chunk
        w, h = struct.unpack('>II', data[16:24])
        return w, h
    if data[:2] == b'\xff\xd8':
        # JPEG: scan for SOF0/SOF2 marker
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            length = struct.unpack('>H', data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC2):  # SOF0 or SOF2
                h, w = struct.unpack('>HH', data[i + 5:i + 9])
                return w, h
            i += 2 + length
    if data[:6] in (b'GIF87a', b'GIF89a') and len(data) >= 10:
        w, h = struct.unpack('<HH', data[6:10])
        return w, h
    return 0, 0


class _CachedImage(NamedTuple):
    """Cache for rendered image data."""
    image_path: Union[Path, bytes, None]
    content_size: Size
    iterm2_sequence: str

    def is_hit(
        self,
        image_path: Union[Path, bytes, None],
        content_size: Size,
    ) -> bool:
        return image_path == self.image_path and content_size == self.content_size


class ITerm2ImageWidget(Widget):
    """Textual widget for iTerm2 inline images.

    This widget injects iTerm2 escape sequences directly into Textual's
    rendering pipeline, similar to how textual-image's SixelImage works.
    Using Rich renderables doesn't work because Textual processes segments
    differently.
    """

    ESC = '\x1b'
    BEL = '\x07'

    DEFAULT_CSS = """
    ITerm2ImageWidget {
        width: auto;
        height: auto;
    }
    """

    def __init__(
        self,
        image: Union[_ImageInput, None] = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ):
        """Initialize the widget."""
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self._image: Union[_ImageInput, None] = None
        self._image_data: bytes | None = None
        self._image_name: str = "image"
        self._image_width: int = 0
        self._image_height: int = 0
        self._cached: _CachedImage | None = None

        self.image = image

    @property
    def image(self) -> Union[_ImageInput, None]:
        """The image to render."""
        return self._image

    @image.setter
    def image(self, value) -> None:
        """Set the image to render."""
        self._cached = None  # Invalidate cache
        self._image = value
        self._image_data = None

        if value is None:
            self._image_width = 0
            self._image_height = 0
            return

        # Load image data and dimensions
        try:
            if isinstance(value, Path):
                self._image_data = value.read_bytes()
                self._image_name = value.name
            elif isinstance(value, bytes):
                self._image_data = value
                self._image_name = "image"
            elif PILImage is not None and isinstance(value, PILImage.Image):
                self._image_width = value.width
                self._image_height = value.height
                buf = io.BytesIO()
                value.save(buf, format='PNG')
                self._image_data = buf.getvalue()
                self._image_name = "image.png"
                self.refresh(layout=True)
                return
            elif hasattr(value, 'read'):
                data = value.read()
                try:
                    value.seek(0)
                except (OSError, io.UnsupportedOperation):
                    pass
                self._image_data = data
                self._image_name = "image"

            # Get dimensions — PIL if available, header parsing as fallback
            if self._image_data:
                if PILImage is not None:
                    img = PILImage.open(io.BytesIO(self._image_data))
                    self._image_width = img.width
                    self._image_height = img.height
                    img.close()
                else:
                    self._image_width, self._image_height = _read_image_dimensions(self._image_data)
        except Exception as e:
            logger.error(f"Failed to load image: {e}")
            self._image_width = 800
            self._image_height = 600

        self.refresh(layout=True)

    def _build_iterm2_sequence(self, cell_width: int, cell_height: int) -> str:
        """Build the iTerm2 escape sequence."""
        if not self._image_data:
            return ""

        b64_data = base64.b64encode(self._image_data).decode('ascii')
        b64_name = base64.b64encode(self._image_name.encode()).decode('ascii')

        args = [
            f"name={b64_name}",
            f"size={len(self._image_data)}",
            f"width={cell_width}",
            f"height={cell_height}",
            "preserveAspectRatio=1",
            "inline=1",
        ]

        return f"{self.ESC}]1337;File={';'.join(args)}:{b64_data}{self.BEL}"

    def render_lines(self, crop: Region) -> list[Strip]:
        """Override render_lines to inject iTerm2 escape sequence directly.

        This is the same approach used by textual-image's SixelImage widget.
        We can't use Rich renderables because Textual processes segments differently.
        """
        # Don't render if no image or screen isn't active
        try:
            if not self._image_data or not self.screen.is_active:
                return []
        except NoScreen:
            return []

        logger.debug(f"ITerm2ImageWidget.render_lines: crop={crop}, content_size={self.content_size}")

        # Check cache
        if self._cached and self._cached.is_hit(self._image, self.content_size):
            logger.debug("Using cached iTerm2 sequence")
            iterm2_sequence = self._cached.iterm2_sequence
        else:
            logger.debug(f"Building iTerm2 sequence for size {self.content_size}")
            iterm2_sequence = self._build_iterm2_sequence(
                self.content_size.width,
                self.content_size.height
            )
            self._cached = _CachedImage(self._image, self.content_size, iterm2_sequence)

        # Get the widget's visible region on screen
        visible_region = self.screen.find_widget(self).visible_region

        # Build segments like textual-image's Sixel widget does:
        # 1. Move cursor to widget position
        # 2. Output image with control trick
        # 3. Move cursor to end of widget
        segments: Iterable[Segment] = [
            # Move to top-left of visible region
            Segment(
                Control.move_to(visible_region.x, visible_region.y).segment.text,
                style=_NULL_STYLE,
            ),
            # Output iTerm2 sequence with control trick (makes Rich pass it through)
            Segment(
                iterm2_sequence,
                style=_NULL_STYLE,
                control=((ControlType.CURSOR_FORWARD, 0),)
            ),
            # Move cursor to bottom-right of visible region
            Segment(
                Control.move_to(visible_region.right, visible_region.bottom).segment.text,
                style=_NULL_STYLE,
            ),
        ]

        # Return strips: empty strips for all but last line, which has the segments
        lines = [Strip([])] * (crop.height - 1) + [Strip(segments, cell_length=crop.width)]
        return lines

    def get_content_width(self, container: Size, viewport: Size) -> int:
        """Calculate content width for Textual's layout."""
        if self._image_width == 0:
            return 1

        cell_size = _get_cell_size()
        aspect = self._image_height / self._image_width

        # Fit to container width
        cell_width = min(container.width, self._image_width // cell_size.width)
        return max(1, cell_width)

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        """Calculate content height for Textual's layout."""
        if self._image_width == 0 or self._image_height == 0:
            return 1

        cell_size = _get_cell_size()
        aspect = self._image_height / self._image_width

        # Calculate from width maintaining aspect ratio
        cell_height = int(width * aspect * (cell_size.width / cell_size.height))
        return max(1, cell_height)

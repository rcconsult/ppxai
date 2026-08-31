"""
ImageViewer widget - Terminal image display with graceful degradation.

Uses factory pattern to dispatch to the appropriate handler:
- FullImageHandler: When textual-imageview is available AND terminal supports images
- FallbackHandler: When library missing OR terminal doesn't support images

Install for full support: pip install ppxai[tui]
"""

from pathlib import Path

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from ppxai.tui.images import get_image_size
from ppxai.tui.validation import MAX_IMAGE_SIZE, format_file_size
from ppxai.tui.widgets.image_handlers import ImageHandler, ImageHandlerFactory

# Default zoom levels for zoom in/out
ZOOM_LEVELS = [0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]
DEFAULT_ZOOM_INDEX = 4  # 1.0 (100%)


class ImageViewer(Widget):
    """A widget for viewing images.

    If textual-image is installed, displays images using terminal protocols.
    The image automatically scales to fit the container width while maintaining aspect ratio.
    Otherwise, displays file information as a fallback.

    Note: textual-image auto-scales to container, so zoom/pan controls are not supported.
    """

    can_focus = True
    can_focus_children = False  # Parent handles keyboard, child handles mouse

    BINDINGS = []  # No bindings - textual-image auto-scales to container

    # Reactive properties
    zoom_level: reactive[float] = reactive(1.0)
    pan_x: reactive[int] = reactive(0)
    pan_y: reactive[int] = reactive(0)

    class ZoomChanged(Message):
        """Posted when zoom level changes."""

        def __init__(self, level: float):
            super().__init__()
            self.level = level

    def __init__(
        self,
        path: Path | None = None,
        id: str = None,
    ):
        """Initialize the image viewer.

        Args:
            path: Path to image file
            id: Widget ID
        """
        super().__init__(id=id)
        self._path = path
        self._image_data: bytes | None = None
        self._dimensions: tuple[int, int] | None = None
        self._file_size: int = 0
        self._format: str = "unknown"
        self._zoom_index = DEFAULT_ZOOM_INDEX
        self._is_loaded = False

        # Create appropriate handler using factory pattern
        self._handler: ImageHandler = ImageHandlerFactory.create(path, self)

        # Load image metadata if path provided
        if path:
            self._load_image_info(path)

    def _load_image_info(self, path: Path) -> bool:
        """Load image metadata (dimensions, size, format).

        Args:
            path: Path to image file

        Returns:
            True if loaded successfully
        """
        if not path.exists():
            return False

        try:
            self._path = path
            self._file_size = path.stat().st_size
            self._format = path.suffix.lower().lstrip(".")

            # Try to get dimensions
            data = path.read_bytes()
            self._image_data = data
            self._dimensions = get_image_size(data)

            self._is_loaded = True
            return True

        except Exception:
            return False

    def compose(self) -> ComposeResult:
        """Compose the image viewer layout using factory-created handler."""
        # Header with filename and info
        filename = self._path.name if self._path else "No image"
        header_parts = [f" [bold]{filename}[/bold]"]

        if self._dimensions:
            header_parts.append(f" [dim]{self._dimensions[0]}×{self._dimensions[1]}[/dim]")

        if self._file_size:
            header_parts.append(f" [dim]({format_file_size(self._file_size)})[/dim]")

        yield Static("".join(header_parts), classes="image-viewer-header", id="image-header")

        # Delegate content composition to handler
        yield from self._handler.compose()

        # Footer with image info
        footer_text = " [dim]Auto-scaled to fit container[/dim]"
        yield Static(footer_text, classes="image-viewer-footer", id="image-footer")

    def on_mount(self) -> None:
        """Called when mounted - focus self to handle keyboard events."""
        # Don't focus handler - we need ImageViewer to have focus for keyboard bindings
        pass

    def watch_zoom_level(self, level: float) -> None:
        """React to zoom level changes (no-op for textual-image)."""
        # Post message for compatibility
        self.post_message(self.ZoomChanged(level))

    def action_zoom_in(self) -> None:
        """Zoom in (+/= key) - delegate to handler."""
        if self._zoom_index < len(ZOOM_LEVELS) - 1:
            self._zoom_index += 1
            self.zoom_level = ZOOM_LEVELS[self._zoom_index]

        self._handler.zoom_in()

    def action_zoom_out(self) -> None:
        """Zoom out (- key) - delegate to handler."""
        if self._zoom_index > 0:
            self._zoom_index -= 1
            self.zoom_level = ZOOM_LEVELS[self._zoom_index]

        self._handler.zoom_out()

    def action_zoom_reset(self) -> None:
        """Reset zoom to fit (0 key) - delegate to handler."""
        self._zoom_index = DEFAULT_ZOOM_INDEX
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0

        self._handler.zoom_reset()

    def action_pan_up(self) -> None:
        """Pan up (w/↑ key) - delegate to handler."""
        self.pan_y -= 10
        self._handler.pan(0, -10)

    def action_pan_down(self) -> None:
        """Pan down (s/↓ key) - delegate to handler."""
        self.pan_y += 10
        self._handler.pan(0, 10)

    def action_pan_left(self) -> None:
        """Pan left (a/← key) - delegate to handler."""
        self.pan_x -= 10
        self._handler.pan(-10, 0)

    def action_pan_right(self) -> None:
        """Pan right (d/→ key) - delegate to handler."""
        self.pan_x += 10
        self._handler.pan(10, 0)

    def load_image(self, path: Path) -> bool:
        """Load a new image.

        Args:
            path: Path to image file

        Returns:
            True if loaded successfully
        """
        if not self._load_image_info(path):
            return False

        # Reset view state
        self._zoom_index = DEFAULT_ZOOM_INDEX
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0

        # Update header
        try:
            header = self.query_one("#image-header", Static)
            header_parts = [f" [bold]{path.name}[/bold]"]
            if self._dimensions:
                header_parts.append(f" [dim]{self._dimensions[0]}×{self._dimensions[1]}[/dim]")
            if self._file_size:
                header_parts.append(f" [dim]({format_file_size(self._file_size)})[/dim]")
            header.update("".join(header_parts))
        except NoMatches:
            pass

        # Delegate to handler
        return self._handler.load(path)

    @property
    def path(self) -> Path | None:
        """Get the current image path."""
        return self._path

    @property
    def dimensions(self) -> tuple[int, int] | None:
        """Get image dimensions (width, height)."""
        return self._dimensions

    @property
    def file_size(self) -> int:
        """Get file size in bytes."""
        return self._file_size

    @property
    def format(self) -> str:
        """Get image format (extension)."""
        return self._format

    @property
    def is_loaded(self) -> bool:
        """Check if an image is loaded."""
        return self._is_loaded

    @staticmethod
    def is_imageview_available() -> bool:
        """Check if full image viewing is available.

        Returns:
            True if both library and terminal support images
        """
        return ImageHandlerFactory.is_full_mode_available()

    @staticmethod
    def check_file_size(path: Path, max_size: int = MAX_IMAGE_SIZE) -> bool:
        """Check if file size is within limits.

        Args:
            path: Path to check
            max_size: Maximum allowed size in bytes

        Returns:
            True if file size is acceptable
        """
        try:
            return path.stat().st_size <= max_size
        except Exception:
            return False

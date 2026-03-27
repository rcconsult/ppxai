"""
Image handler implementations for ImageViewer widget.

Provides different handlers based on library availability and terminal capabilities:
- FullImageHandler: Uses textual-image for full image rendering
- FallbackHandler: Shows file info when images can't be displayed
"""

import logging
import os
from pathlib import Path
from typing import Optional, Protocol, Tuple

from textual.app import ComposeResult
from textual.containers import Center, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from ppxai.tui.images import get_image_size
from ppxai.tui.terminal import (
    ImageProtocol,
    can_display_images,
    get_image_protocol_name,
    get_user_protocol_override,
    get_user_terminal_override,
)
from ppxai.tui.validation import format_file_size


# Check if textual-image is available
_IMAGEVIEW_AVAILABLE = False
_TextualImage = None
_TGPImage = None
_SixelImage = None

try:
    from textual_image.widget import Image as TextualImage
    from textual_image.widget import TGPImage, SixelImage
    _IMAGEVIEW_AVAILABLE = True
    _TextualImage = TextualImage
    _TGPImage = TGPImage
    _SixelImage = SixelImage
except ImportError:
    pass

# Check for our native iTerm2 renderable
_ITerm2Image = None
try:
    from ppxai.tui.renderable.iterm2 import ITerm2Image
    _ITerm2Image = ITerm2Image
except ImportError:
    pass

# Check for our native iTerm2 Textual widget (works without PIL via header parsing)
_ITerm2ImageWidget = None
try:
    from ppxai.tui.widgets.iterm2_widget import ITerm2ImageWidget
    _ITerm2ImageWidget = ITerm2ImageWidget
except ImportError:
    pass


def _get_image_widget_class():
    """Get the best image widget class for the current terminal.

    Respects PPXAI_IMAGE_PROTOCOL and PPXAI_TERMINAL environment overrides.

    textual-image's auto-detection queries the terminal at import time,
    which can fail on Windows. We use our own terminal detection to
    force high-res rendering for known terminals.

    Terminal support:
    - iTerm2: Uses our native iTerm2 protocol implementation (OSC 1337)
    - WezTerm: Same iTerm2 protocol (WezTerm supports it natively)
    - Kitty: Uses TGP (Kitty Graphics Protocol) via textual-image
    - Windows Terminal: Uses textual-image auto-detection (Sixel)

    Returns:
        The appropriate image widget class
    """
    # Check for user protocol override first
    protocol_override = get_user_protocol_override()
    if protocol_override is not None:
        if protocol_override == ImageProtocol.ITERM2:
            if _ITerm2Image is not None:
                from ppxai.tui.widgets.iterm2_widget import ITerm2ImageWidget
                return ITerm2ImageWidget
        elif protocol_override == ImageProtocol.KITTY:
            if _TGPImage is not None:
                return _TGPImage
        elif protocol_override == ImageProtocol.SIXEL:
            if _SixelImage is not None:
                return _SixelImage
        elif protocol_override == ImageProtocol.NONE:
            return None  # Force fallback handler
        # Fall through to auto-detect if override widget not available

    # Check for terminal override
    terminal_override = get_user_terminal_override()
    term_program = (terminal_override or os.environ.get("TERM_PROGRAM", "")).lower()

    # WezTerm: Use our native iTerm2 protocol implementation
    # WezTerm supports iTerm2 inline images but not Kitty TGP or Sixel queries.
    # We use the same integration technique as textual-image's Sixel renderer:
    # placeholder text + cursor save/restore + control segment trick.
    # WezTerm / iTerm2: Use native iTerm2 inline image protocol (OSC 1337)
    if term_program in ("wezterm", "iterm.app"):
        if _ITerm2ImageWidget is not None:
            return _ITerm2ImageWidget

    # Kitty: Use TGP (native support)
    if os.environ.get("KITTY_WINDOW_ID"):
        if _TGPImage is not None:
            return _TGPImage

    # All other terminals (including Windows Terminal): use auto-detection
    # Windows Terminal responds to Sixel queries and works well with textual-image
    return _TextualImage


class ImageHandler(Protocol):
    """Protocol defining the interface for image handlers."""

    def compose(self) -> ComposeResult:
        """Compose the handler's UI elements."""
        ...

    def zoom_in(self) -> None:
        """Zoom in (if supported)."""
        ...

    def zoom_out(self) -> None:
        """Zoom out (if supported)."""
        ...

    def zoom_reset(self) -> None:
        """Reset zoom to default (if supported)."""
        ...

    def pan(self, dx: int, dy: int) -> None:
        """Pan the view (if supported)."""
        ...

    def focus(self) -> None:
        """Focus the handler's main widget."""
        ...

    def load(self, path: Path) -> bool:
        """Load a new image."""
        ...


class FullImageHandler:
    """Handler for full image viewing using textual-image.

    This handler uses the textual-image library which supports
    iTerm2, Kitty, and Sixel protocols for terminal image display.
    Images automatically scale to container size while maintaining aspect ratio.
    """

    def __init__(self, path: Path, parent: Widget):
        """Initialize the full image handler.

        Args:
            path: Path to image file
            parent: Parent widget (for querying)
        """
        self._path = path
        self._parent = parent
        self._viewer: Optional[Widget] = None

        # Create the textual-image widget
        try:
            # Use the best image widget class for this terminal
            # This forces TGPImage for WezTerm/iTerm2 to get high-res rendering
            ImageWidgetClass = _get_image_widget_class()
            # textual-image accepts Path objects directly
            # Sizing is controlled via CSS (width: 100% in layout.tcss)
            self._viewer = ImageWidgetClass(path)
        except Exception as e:
            # Failed to create viewer - will fall back to None
            logging.error(f"Failed to create TextualImage widget: {e}")
            self._viewer = None

    def compose(self) -> ComposeResult:
        """Compose the full image viewer."""
        if self._viewer:
            with Center(id="image-center"):
                yield self._viewer

    def zoom_in(self) -> None:
        """Zoom in (no-op - textual-image auto-scales to container)."""
        pass

    def zoom_out(self) -> None:
        """Zoom out (no-op - textual-image auto-scales to container)."""
        pass

    def zoom_reset(self) -> None:
        """Reset zoom (no-op - textual-image auto-scales to container)."""
        pass

    def pan(self, dx: int, dy: int) -> None:
        """Pan the view (no-op - textual-image auto-scales to container).

        Args:
            dx: Horizontal delta
            dy: Vertical delta
        """
        pass

    def focus(self) -> None:
        """Focus the image viewer."""
        if self._viewer:
            self._viewer.focus()

    def load(self, path: Path) -> bool:
        """Load a new image.

        Args:
            path: Path to image file

        Returns:
            True if loaded successfully
        """
        if not self._viewer:
            return False

        try:
            # textual-image updates via the image property
            self._viewer.image = path
            self._path = path
            return True
        except Exception as e:
            logging.error(f"Failed to load image: {e}")
            return False

    @property
    def is_available(self) -> bool:
        """Check if the viewer is available and working."""
        return self._viewer is not None


class FallbackHandler:
    """Handler for fallback mode when images can't be displayed.

    Shows file information and helpful messages about why images
    can't be displayed (library missing or terminal doesn't support images).
    """

    def __init__(self, path: Optional[Path], parent: Widget, reason: str):
        """Initialize the fallback handler.

        Args:
            path: Path to image file (None if no image)
            parent: Parent widget
            reason: Why we're in fallback mode ('library', 'terminal', or 'error')
        """
        self._path = path
        self._parent = parent
        self._reason = reason
        self._dimensions: Optional[Tuple[int, int]] = None
        self._file_size: int = 0
        self._format: str = "unknown"

        # Load image metadata if path provided
        if path and path.exists():
            try:
                self._file_size = path.stat().st_size
                self._format = path.suffix.lower().lstrip(".")

                # Try to get dimensions
                data = path.read_bytes()
                self._dimensions = get_image_size(data)
            except Exception:
                pass

    def compose(self) -> ComposeResult:
        """Compose fallback view with file information."""
        with Center(id="image-center"):
            with Vertical(id="image-info-container"):
                info_lines = []

                if self._path:
                    info_lines.append(f"[bold]File:[/bold] {self._path.name}")
                    info_lines.append(f"[bold]Format:[/bold] {self._format.upper()}")

                    if self._dimensions:
                        info_lines.append(f"[bold]Dimensions:[/bold] {self._dimensions[0]} × {self._dimensions[1]} px")

                    info_lines.append(f"[bold]Size:[/bold] {format_file_size(self._file_size)}")
                    info_lines.append("")

                    # Explain why we're in fallback mode
                    if self._reason == "library":
                        info_lines.append("[yellow]Image preview not available.[/yellow]")
                        info_lines.append("")
                        info_lines.append("[dim]Install for image preview:[/dim]")
                        info_lines.append("[cyan]pip install ppxai[tui][/cyan]")
                    elif self._reason == "terminal":
                        protocol = get_image_protocol_name()
                        info_lines.append(f"[yellow]Terminal image protocol: {protocol}[/yellow]")
                        info_lines.append("")
                        info_lines.append("[dim]Image display requires iTerm2, Kitty, or WezTerm[/dim]")
                    elif self._reason == "error":
                        info_lines.append("[yellow]Failed to load image viewer.[/yellow]")
                else:
                    info_lines.append("[yellow]No image loaded[/yellow]")

                yield Static("\n".join(info_lines), id="image-info")

    def zoom_in(self) -> None:
        """No-op in fallback mode."""
        pass

    def zoom_out(self) -> None:
        """No-op in fallback mode."""
        pass

    def zoom_reset(self) -> None:
        """No-op in fallback mode."""
        pass

    def pan(self, dx: int, dy: int) -> None:
        """No-op in fallback mode."""
        pass

    def focus(self) -> None:
        """No-op in fallback mode (static content)."""
        pass

    def load(self, path: Path) -> bool:
        """Load new image metadata.

        Args:
            path: Path to image file

        Returns:
            True if metadata loaded successfully
        """
        if not path.exists():
            return False

        try:
            self._path = path
            self._file_size = path.stat().st_size
            self._format = path.suffix.lower().lstrip(".")

            data = path.read_bytes()
            self._dimensions = get_image_size(data)
            return True
        except Exception:
            return False

    @property
    def is_available(self) -> bool:
        """Fallback is always available."""
        return True


class ImageHandlerFactory:
    """Factory for creating image handlers based on capabilities.

    This factory implements the strategy pattern, selecting the appropriate
    handler based on:
    1. Library availability (textual-image installed?)
    2. Terminal capabilities (iTerm2, Kitty, Sixel support?)
    """

    @staticmethod
    def create(path: Optional[Path], parent: Widget) -> ImageHandler:
        """Create appropriate image handler.

        Decision tree:
        1. If textual-image not installed → FallbackHandler(reason='library')
        2. If terminal doesn't support images → FallbackHandler(reason='terminal')
        3. If both available → FullImageHandler
        4. If FullImageHandler creation fails → FallbackHandler(reason='error')

        Args:
            path: Path to image file (None if no image)
            parent: Parent widget

        Returns:
            ImageHandler instance (Full or Fallback)
        """
        # Check library availability — need textual-image OR our native widget
        if not _IMAGEVIEW_AVAILABLE and _ITerm2ImageWidget is None:
            return FallbackHandler(path, parent, reason="library")

        # Check terminal capabilities
        if not can_display_images():
            return FallbackHandler(path, parent, reason="terminal")

        # Both library and terminal support available
        if path:
            handler = FullImageHandler(path, parent)

            # If handler creation failed, fall back
            if not handler.is_available:
                return FallbackHandler(path, parent, reason="error")

            return handler

        # No path provided
        return FallbackHandler(None, parent, reason="library")

    @staticmethod
    def is_full_mode_available() -> bool:
        """Check if full image viewing is possible.

        Returns:
            True if both library and terminal support images
        """
        return _IMAGEVIEW_AVAILABLE and can_display_images()

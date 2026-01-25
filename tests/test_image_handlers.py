"""Tests for image handler factory and delegation pattern."""

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from ppxai.tui.widgets.image_handlers import (
    FallbackHandler,
    FullImageHandler,
    ImageHandler,
    ImageHandlerFactory,
)


class TestImageHandlerFactory:
    """Test ImageHandlerFactory decision logic."""

    def test_factory_creates_fallback_when_library_missing(self):
        """Factory creates FallbackHandler when textual-image is not installed."""
        with mock.patch("ppxai.tui.widgets.image_handlers._IMAGEVIEW_AVAILABLE", False):
            handler = ImageHandlerFactory.create(None, None)
            assert isinstance(handler, FallbackHandler)

    def test_factory_creates_fallback_when_terminal_unsupported(self):
        """Factory creates FallbackHandler when terminal doesn't support images."""
        with mock.patch("ppxai.tui.widgets.image_handlers._IMAGEVIEW_AVAILABLE", True):
            with mock.patch("ppxai.tui.widgets.image_handlers.can_display_images", return_value=False):
                handler = ImageHandlerFactory.create(None, None)
                assert isinstance(handler, FallbackHandler)

    def test_factory_creates_full_handler_when_both_available(self):
        """Factory creates FullImageHandler when both library and terminal support images."""
        # Mock both library and terminal as available
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            path = Path(tmp.name)
            # Write minimal PNG header
            tmp.write(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)

        try:
            with mock.patch("ppxai.tui.widgets.image_handlers._IMAGEVIEW_AVAILABLE", True):
                with mock.patch("ppxai.tui.widgets.image_handlers.can_display_images", return_value=True):
                    # Mock TextualImage widget
                    with mock.patch("ppxai.tui.widgets.image_handlers._TextualImage") as mock_image:
                        mock_image.return_value = mock.Mock()
                        handler = ImageHandlerFactory.create(path, None)
                        assert isinstance(handler, FullImageHandler)
                        # Verify TextualImage was created with path directly
                        mock_image.assert_called_once_with(path)
        finally:
            path.unlink()

    def test_is_full_mode_available_checks_both_conditions(self):
        """is_full_mode_available() returns True only when both library and terminal support images."""
        # Both available
        with mock.patch("ppxai.tui.widgets.image_handlers._IMAGEVIEW_AVAILABLE", True):
            with mock.patch("ppxai.tui.widgets.image_handlers.can_display_images", return_value=True):
                assert ImageHandlerFactory.is_full_mode_available() is True

        # Library missing
        with mock.patch("ppxai.tui.widgets.image_handlers._IMAGEVIEW_AVAILABLE", False):
            with mock.patch("ppxai.tui.widgets.image_handlers.can_display_images", return_value=True):
                assert ImageHandlerFactory.is_full_mode_available() is False

        # Terminal unsupported
        with mock.patch("ppxai.tui.widgets.image_handlers._IMAGEVIEW_AVAILABLE", True):
            with mock.patch("ppxai.tui.widgets.image_handlers.can_display_images", return_value=False):
                assert ImageHandlerFactory.is_full_mode_available() is False


class TestFallbackHandler:
    """Test FallbackHandler functionality."""

    def test_fallback_handler_has_required_methods(self):
        """FallbackHandler has all required methods."""
        handler = FallbackHandler(None, None, "library")
        assert hasattr(handler, "compose")
        assert hasattr(handler, "zoom_in")
        assert hasattr(handler, "zoom_out")
        assert hasattr(handler, "zoom_reset")
        assert hasattr(handler, "pan")
        assert hasattr(handler, "focus")
        assert hasattr(handler, "load")

    def test_fallback_handler_operations_are_noops(self):
        """FallbackHandler operations are no-ops."""
        handler = FallbackHandler(None, None, "library")

        # Should not raise errors
        handler.zoom_in()
        handler.zoom_out()
        handler.zoom_reset()
        handler.pan(10, 10)
        handler.focus()

    def test_fallback_handler_accepts_library_reason(self):
        """FallbackHandler accepts 'library' reason."""
        handler = FallbackHandler(None, None, reason="library")
        assert handler._reason == "library"

    def test_fallback_handler_accepts_terminal_reason(self):
        """FallbackHandler accepts 'terminal' reason."""
        handler = FallbackHandler(None, None, reason="terminal")
        assert handler._reason == "terminal"

    def test_fallback_handler_loads_image_metadata(self):
        """FallbackHandler loads image metadata when path provided."""
        # Create a temporary PNG file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            path = Path(tmp.name)
            # Write minimal valid PNG header
            tmp.write(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x02\x00\x00\x00')

        try:
            handler = FallbackHandler(path, None, reason="library")
            assert handler._path == path
            assert handler._file_size > 0
            assert handler._format == "png"
        finally:
            path.unlink()

    def test_fallback_handler_is_always_available(self):
        """FallbackHandler is_available is always True."""
        handler = FallbackHandler(None, None, "library")
        assert handler.is_available is True


class TestFullImageHandler:
    """Test FullImageHandler functionality."""

    def test_full_handler_has_required_methods(self):
        """FullImageHandler has all required methods."""
        with mock.patch("ppxai.tui.widgets.image_handlers._TextualImage") as mock_image:
            mock_image.return_value = mock.Mock()
            handler = FullImageHandler(Path("test.png"), None)

            # Check all required methods exist
            assert hasattr(handler, "compose")
            assert hasattr(handler, "zoom_in")
            assert hasattr(handler, "zoom_out")
            assert hasattr(handler, "zoom_reset")
            assert hasattr(handler, "pan")
            assert hasattr(handler, "focus")
            assert hasattr(handler, "load")

    def test_full_handler_zoom_operations_are_noops(self):
        """FullImageHandler zoom operations are no-ops (textual-image auto-scales)."""
        with mock.patch("ppxai.tui.widgets.image_handlers._TextualImage") as mock_image:
            mock_image.return_value = mock.Mock()
            handler = FullImageHandler(Path("test.png"), None)

            # Should not raise errors (zoom is handled by auto-scaling)
            handler.zoom_in()
            handler.zoom_out()
            handler.zoom_reset()

    def test_full_handler_pan_is_noop(self):
        """FullImageHandler pan is a no-op (textual-image auto-scales to container)."""
        with mock.patch("ppxai.tui.widgets.image_handlers._TextualImage") as mock_image:
            mock_image.return_value = mock.Mock()
            handler = FullImageHandler(Path("test.png"), None)

            # Should not raise error
            handler.pan(10, 20)

    def test_full_handler_delegates_focus(self):
        """FullImageHandler delegates focus to underlying viewer."""
        with mock.patch("ppxai.tui.widgets.image_handlers._TextualImage") as mock_image:
            mock_instance = mock.Mock()
            mock_image.return_value = mock_instance
            handler = FullImageHandler(Path("test.png"), None)
            handler.focus()
            mock_instance.focus.assert_called_once()

    def test_full_handler_is_available_when_viewer_created(self):
        """FullImageHandler is_available is True when viewer successfully created."""
        with mock.patch("ppxai.tui.widgets.image_handlers._TextualImage") as mock_image:
            mock_image.return_value = mock.Mock()
            handler = FullImageHandler(Path("test.png"), None)
            assert handler.is_available is True

    def test_full_handler_not_available_when_viewer_creation_fails(self):
        """FullImageHandler is_available is False when viewer creation fails."""
        with mock.patch("ppxai.tui.widgets.image_handlers._TextualImage") as mock_image:
            mock_image.side_effect = Exception("Failed to create viewer")
            handler = FullImageHandler(Path("test.png"), None)
            assert handler.is_available is False

    def test_full_handler_load_updates_image_property(self):
        """FullImageHandler.load() updates the image property of the viewer."""
        with mock.patch("ppxai.tui.widgets.image_handlers._TextualImage") as mock_image:
            mock_instance = mock.Mock()
            mock_image.return_value = mock_instance
            handler = FullImageHandler(Path("test.png"), None)

            # Load a new image
            new_path = Path("new_image.png")
            result = handler.load(new_path)

            assert result is True
            # Verify the image property was updated
            assert mock_instance.image == new_path
            assert handler._path == new_path


class TestHandlerDelegation:
    """Test delegation pattern in ImageViewer."""

    def test_image_viewer_uses_factory_for_handler_creation(self):
        """ImageViewer uses factory to create handlers."""
        from ppxai.tui.widgets.image_viewer import ImageViewer

        with mock.patch("ppxai.tui.widgets.image_handlers._IMAGEVIEW_AVAILABLE", False):
            viewer = ImageViewer()
            assert hasattr(viewer, "_handler")
            assert viewer._handler is not None

    def test_image_viewer_delegates_to_handler(self):
        """ImageViewer delegates operations to its handler."""
        from ppxai.tui.widgets.image_viewer import ImageViewer

        with mock.patch("ppxai.tui.widgets.image_handlers._IMAGEVIEW_AVAILABLE", False):
            viewer = ImageViewer()
            # Handler should be FallbackHandler (library unavailable)
            assert isinstance(viewer._handler, FallbackHandler)

    def test_image_viewer_checks_full_mode_availability(self):
        """ImageViewer.is_imageview_available() checks both library and terminal."""
        from ppxai.tui.widgets.image_viewer import ImageViewer

        # Both available
        with mock.patch("ppxai.tui.widgets.image_handlers._IMAGEVIEW_AVAILABLE", True):
            with mock.patch("ppxai.tui.widgets.image_handlers.can_display_images", return_value=True):
                assert ImageViewer.is_imageview_available() is True

        # Library missing
        with mock.patch("ppxai.tui.widgets.image_handlers._IMAGEVIEW_AVAILABLE", False):
            with mock.patch("ppxai.tui.widgets.image_handlers.can_display_images", return_value=True):
                assert ImageViewer.is_imageview_available() is False

"""
Tests for ppxaide TUI module.

Tests widget functionality, themes, clipboard, and hyperlinks.
"""

import pytest
import json
import tempfile
from pathlib import Path


class TestThemes:
    """Tests for theme system."""

    def test_custom_themes_defined(self):
        """Verify custom themes are properly defined."""
        from ppxai.tui.themes import CUSTOM_THEMES, DEFAULT_THEME, CYCLE_THEMES

        assert "tron-legacy" in CUSTOM_THEMES
        assert "matrix" in CUSTOM_THEMES
        assert len(CUSTOM_THEMES) == 2

    def test_default_theme_is_builtin(self):
        """Default theme should be a Textual built-in."""
        from ppxai.tui.themes import DEFAULT_THEME

        assert DEFAULT_THEME == "catppuccin-mocha"

    def test_cycle_themes_includes_custom(self):
        """Cycle themes should include our custom themes."""
        from ppxai.tui.themes import CYCLE_THEMES

        assert "tron-legacy" in CYCLE_THEMES
        assert "matrix" in CYCLE_THEMES
        assert len(CYCLE_THEMES) == 8

    def test_theme_objects_valid(self):
        """Custom Theme objects should have required attributes."""
        from ppxai.tui.themes.themes import TRON_LEGACY_THEME, MATRIX_THEME

        for theme in [TRON_LEGACY_THEME, MATRIX_THEME]:
            assert theme.name is not None
            assert theme.primary is not None
            assert theme.background is not None
            assert theme.dark is True


class TestClipboard:
    """Tests for clipboard functionality."""

    def test_clipboard_module_imports(self):
        """Clipboard module should import without error."""
        from ppxai.tui.clipboard import (
            copy_to_clipboard,
            paste_from_clipboard,
            is_clipboard_available,
        )

    def test_clipboard_availability_check(self):
        """Should be able to check clipboard availability."""
        from ppxai.tui.clipboard import is_clipboard_available

        # Just verify it returns a boolean
        result = is_clipboard_available()
        assert isinstance(result, bool)


class TestHyperlinks:
    """Tests for OSC 8 hyperlink support."""

    def test_make_file_link(self):
        """Test file link generation."""
        from ppxai.tui.hyperlinks import make_file_link

        link = make_file_link("/tmp/test.py")
        assert "\033]8;;" in link
        assert "file://" in link
        assert "/tmp/test.py" in link

    def test_make_file_link_with_line(self):
        """Test file link with line number."""
        from ppxai.tui.hyperlinks import make_file_link

        link = make_file_link("/tmp/test.py", line=42)
        assert ":42" in link

    def test_make_file_link_with_line_and_col(self):
        """Test file link with line and column."""
        from ppxai.tui.hyperlinks import make_file_link

        link = make_file_link("/tmp/test.py", line=42, col=10)
        assert ":42:10" in link

    def test_make_url_link(self):
        """Test URL link generation."""
        from ppxai.tui.hyperlinks import make_url_link

        link = make_url_link("https://example.com")
        assert "\033]8;;" in link
        assert "https://example.com" in link

    def test_strip_hyperlinks(self):
        """Test removing hyperlink escape sequences."""
        from ppxai.tui.hyperlinks import make_url_link, strip_hyperlinks

        link = make_url_link("https://example.com", "Click here")
        stripped = strip_hyperlinks(link)
        assert stripped == "Click here"
        assert "\033" not in stripped

    def test_linkify_urls(self):
        """Test URL detection and linkification."""
        from ppxai.tui.hyperlinks import linkify_urls

        text = "Check out https://example.com for more info"
        result = linkify_urls(text)
        assert "\033]8;;" in result
        assert "https://example.com" in result


class TestTreeViewer:
    """Tests for TreeViewer widget."""

    def test_tree_viewer_imports(self):
        """TreeViewer should import without error."""
        from ppxai.tui.widgets import TreeViewer

    def test_tree_viewer_format_value(self):
        """Test value formatting."""
        from ppxai.tui.widgets.tree_viewer import TreeViewer

        viewer = TreeViewer()

        # Test null
        assert "null" in viewer._format_value(None)

        # Test boolean
        assert "true" in viewer._format_value(True).lower()
        assert "false" in viewer._format_value(False).lower()

        # Test number
        assert "42" in viewer._format_value(42)

        # Test string
        assert "hello" in viewer._format_value("hello")


class TestCodeEditor:
    """Tests for CodeEditor widget."""

    def test_code_editor_imports(self):
        """CodeEditor should import without error."""
        from ppxai.tui.widgets import CodeEditor

    def test_language_detection(self):
        """Test language detection from file extension."""
        from ppxai.tui.widgets.code_editor import EXTENSION_TO_LANGUAGE

        assert EXTENSION_TO_LANGUAGE[".py"] == "python"
        assert EXTENSION_TO_LANGUAGE[".js"] == "javascript"
        assert EXTENSION_TO_LANGUAGE[".ts"] == "typescript"
        assert EXTENSION_TO_LANGUAGE[".json"] == "json"
        assert EXTENSION_TO_LANGUAGE[".yaml"] == "yaml"
        assert EXTENSION_TO_LANGUAGE[".md"] == "markdown"
        assert EXTENSION_TO_LANGUAGE[".rs"] == "rust"
        assert EXTENSION_TO_LANGUAGE[".go"] == "go"


class TestSplitPane:
    """Tests for SplitPane widget."""

    def test_split_pane_imports(self):
        """SplitPane should import without error."""
        from ppxai.tui.widgets import SplitPane, Pane, HorizontalSplit, VerticalSplit

    def test_pane_has_class(self):
        """Pane should add .pane class."""
        from ppxai.tui.widgets.split_pane import Pane

        pane = Pane()
        assert "pane" in pane.classes


class TestWidgetExports:
    """Tests for widget module exports."""

    def test_all_widgets_exported(self):
        """All widgets should be exported from __init__."""
        from ppxai.tui.widgets import (
            StatusBar,
            ChatView,
            InputBox,
            MessageBox,
            TreeViewer,
            CodeEditor,
            SplitPane,
            Pane,
            HorizontalSplit,
            VerticalSplit,
        )

    def test_all_exports_list(self):
        """__all__ should list all exports."""
        from ppxai.tui import widgets

        expected = [
            "StatusBar",
            "ChatView",
            "InputBox",
            "MessageBox",
            "TreeViewer",
            "CodeEditor",
            "SplitPane",
            "Pane",
            "HorizontalSplit",
            "VerticalSplit",
        ]
        for name in expected:
            assert name in widgets.__all__


class TestAppImports:
    """Tests for main app imports."""

    def test_app_imports(self):
        """Main app should import without error."""
        from ppxai.tui.app import PPXAIDEApp

    def test_app_has_bindings(self):
        """App should have keyboard bindings."""
        from ppxai.tui.app import PPXAIDEApp

        app = PPXAIDEApp()
        # Check BINDINGS class attribute
        binding_keys = [b.key for b in PPXAIDEApp.BINDINGS]
        assert "ctrl+c" in binding_keys
        assert "ctrl+l" in binding_keys
        assert "ctrl+t" in binding_keys

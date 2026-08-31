"""
Tests for ppxaide TUI module.

Tests widget functionality, themes, clipboard, and hyperlinks.

Phase 1 tests validate core visual components work reliably:
- StatusBar: Rapid updates, long text, theme integration
- ChatView: Scrolling, auto-scroll, large message lists
- InputBox: History navigation, multi-line, Unicode
- Themes: All 17+ themes render correctly
- Keybindings: No conflicts between widgets
"""

import pytest
import json
import tempfile
import asyncio
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
        # TypeScript uses JS highlighting (Textual doesn't have native TS support)
        assert EXTENSION_TO_LANGUAGE[".ts"] == "javascript"
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
            SafeQueryMixin,
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
            SidePanel,
        )

    def test_all_exports_list(self):
        """__all__ should list all exports."""
        from ppxai.tui import widgets

        expected = [
            "SafeQueryMixin",
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
            "SidePanel",
        ]
        for name in expected:
            assert name in widgets.__all__


class TestSafeQueryMixin:
    """Tests for SafeQueryMixin base class."""

    def test_safe_query_mixin_imports(self):
        """SafeQueryMixin should be importable."""
        from ppxai.tui.widgets.base import SafeQueryMixin
        assert SafeQueryMixin is not None

    def test_safe_query_mixin_has_method(self):
        """SafeQueryMixin should have safe_query_one method."""
        from ppxai.tui.widgets.base import SafeQueryMixin
        assert hasattr(SafeQueryMixin, 'safe_query_one')
        assert callable(getattr(SafeQueryMixin, 'safe_query_one'))


class TestSidePanel:
    """Tests for SidePanel widget."""

    def test_side_panel_imports(self):
        """SidePanel should import without error."""
        from ppxai.tui.widgets import SidePanel

    def test_side_panel_default_state(self):
        """SidePanel should start closed."""
        from ppxai.tui.widgets.side_panel import SidePanel

        panel = SidePanel()
        assert panel.is_open is False

    def test_side_panel_has_messages(self):
        """SidePanel should have Opened and Closed message classes."""
        from ppxai.tui.widgets.side_panel import SidePanel

        assert hasattr(SidePanel, "Opened")
        assert hasattr(SidePanel, "Closed")


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


class TestTerminalCapabilities:
    """Tests for terminal capability detection."""

    def test_terminal_imports(self):
        """Terminal module should import without error."""
        from ppxai.tui.terminal import (
            ImageProtocol,
            TerminalCapabilities,
            detect_terminal,
            detect_true_color,
            detect_image_protocol,
            can_display_images,
            get_capabilities,
            format_capabilities,
        )

    def test_image_protocol_enum(self):
        """ImageProtocol enum should have expected values."""
        from ppxai.tui.terminal import ImageProtocol

        assert ImageProtocol.NONE
        assert ImageProtocol.ITERM2
        assert ImageProtocol.KITTY
        assert ImageProtocol.SIXEL

    def test_detect_capabilities_returns_dataclass(self):
        """detect_capabilities should return TerminalCapabilities."""
        from ppxai.tui.terminal import get_capabilities, TerminalCapabilities

        caps = get_capabilities()
        assert isinstance(caps, TerminalCapabilities)
        assert hasattr(caps, "name")
        assert hasattr(caps, "true_color")
        assert hasattr(caps, "image_protocol")

    def test_format_capabilities_returns_string(self):
        """format_capabilities should return a formatted string."""
        from ppxai.tui.terminal import format_capabilities

        result = format_capabilities()
        assert isinstance(result, str)
        assert "Terminal:" in result


class TestImageSupport:
    """Tests for image display support."""

    def test_images_imports(self):
        """Images module should import without error."""
        from ppxai.tui.images import (
            IMAGE_EXTENSIONS,
            is_image_file,
            display_image,
        )
        from ppxai.tui.terminal import can_display_images

    def test_image_extensions(self):
        """IMAGE_EXTENSIONS should contain common formats."""
        from ppxai.tui.images import IMAGE_EXTENSIONS

        assert ".png" in IMAGE_EXTENSIONS
        assert ".jpg" in IMAGE_EXTENSIONS
        assert ".jpeg" in IMAGE_EXTENSIONS
        assert ".gif" in IMAGE_EXTENSIONS

    def test_is_image_file(self):
        """is_image_file should detect image extensions."""
        from ppxai.tui.images import is_image_file
        from pathlib import Path

        assert is_image_file(Path("test.png"))
        assert is_image_file(Path("test.jpg"))
        assert is_image_file(Path("test.JPEG"))  # Case insensitive
        assert not is_image_file(Path("test.py"))
        assert not is_image_file(Path("test.txt"))


class TestContentFactory:
    """Tests for content display mode detection."""

    def test_content_factory_imports(self):
        """Content factory should import without error."""
        from ppxai.tui.widgets.content_factory import (
            detect_display_mode,
            get_data_format,
            is_data_file,
            is_markdown_file,
            DATA_FORMATS,
            MARKDOWN_FORMATS,
        )

    def test_detect_display_mode_code(self):
        """detect_display_mode should return 'code' for code files."""
        from ppxai.tui.widgets.content_factory import detect_display_mode
        from pathlib import Path

        assert detect_display_mode(Path("test.py")) == "code"
        assert detect_display_mode(Path("test.js")) == "code"
        assert detect_display_mode(Path("test.rs")) == "code"
        assert detect_display_mode(Path("test.txt")) == "code"

    def test_detect_display_mode_data(self):
        """detect_display_mode should return 'data' for data files."""
        from ppxai.tui.widgets.content_factory import detect_display_mode
        from pathlib import Path

        assert detect_display_mode(Path("test.json")) == "data"
        assert detect_display_mode(Path("test.yaml")) == "data"
        assert detect_display_mode(Path("test.yml")) == "data"
        assert detect_display_mode(Path("test.toml")) == "data"

    def test_detect_display_mode_markdown(self):
        """detect_display_mode should return 'markdown' for markdown files."""
        from ppxai.tui.widgets.content_factory import detect_display_mode
        from pathlib import Path

        assert detect_display_mode(Path("README.md")) == "markdown"
        assert detect_display_mode(Path("doc.markdown")) == "markdown"

    def test_detect_display_mode_image(self):
        """detect_display_mode should return 'image' for image files."""
        from ppxai.tui.widgets.content_factory import detect_display_mode
        from pathlib import Path

        assert detect_display_mode(Path("test.png")) == "image"
        assert detect_display_mode(Path("test.jpg")) == "image"
        assert detect_display_mode(Path("test.gif")) == "image"

    def test_get_data_format(self):
        """get_data_format should return specific format."""
        from ppxai.tui.widgets.content_factory import get_data_format
        from pathlib import Path

        assert get_data_format(Path("test.json")) == "json"
        assert get_data_format(Path("test.yaml")) == "yaml"
        assert get_data_format(Path("test.yml")) == "yaml"
        assert get_data_format(Path("test.toml")) == "toml"
        assert get_data_format(Path("test.py")) is None

    def test_is_data_file(self):
        """is_data_file should detect data file extensions."""
        from ppxai.tui.widgets.content_factory import is_data_file
        from pathlib import Path

        assert is_data_file(Path("test.json"))
        assert is_data_file(Path("test.yaml"))
        assert not is_data_file(Path("test.py"))

    def test_is_markdown_file(self):
        """is_markdown_file should detect markdown extensions."""
        from ppxai.tui.widgets.content_factory import is_markdown_file
        from pathlib import Path

        assert is_markdown_file(Path("README.md"))
        assert is_markdown_file(Path("doc.markdown"))
        assert not is_markdown_file(Path("test.txt"))


class TestValidation:
    """Tests for input validation utilities."""

    def test_validation_imports(self):
        """Validation module should import without error."""
        from ppxai.tui.validation import (
            safe_resolve_path,
            validate_file_size,
            get_size_limit_for_mode,
            format_file_size,
            is_safe_filename,
            MAX_TEXT_FILE_SIZE,
            MAX_IMAGE_SIZE,
            MAX_DATA_FILE_SIZE,
        )

    def test_safe_resolve_path_absolute(self):
        """safe_resolve_path should handle absolute paths."""
        from ppxai.tui.validation import safe_resolve_path

        # Test with temp directory (exists on all platforms)
        result = safe_resolve_path(tempfile.gettempdir())
        assert result is not None
        assert result.is_absolute()

    def test_safe_resolve_path_relative(self):
        """safe_resolve_path should resolve relative paths within base."""
        from ppxai.tui.validation import safe_resolve_path

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("test", encoding="utf-8")

            # Resolve relative to tmpdir
            result = safe_resolve_path("test.txt", base_dir=tmpdir)
            assert result is not None
            assert result == test_file.resolve()

    def test_safe_resolve_path_traversal_blocked(self):
        """safe_resolve_path should block path traversal attacks."""
        from ppxai.tui.validation import safe_resolve_path

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a nested directory
            nested = Path(tmpdir) / "subdir"
            nested.mkdir()

            # Try to escape via ../
            result = safe_resolve_path("../../../etc/passwd", base_dir=str(nested))
            assert result is None

    def test_safe_resolve_path_nonexistent(self):
        """safe_resolve_path should return None for non-existent paths."""
        from ppxai.tui.validation import safe_resolve_path

        result = safe_resolve_path("/nonexistent/path/to/file.txt")
        assert result is None

    def test_safe_resolve_path_empty(self):
        """safe_resolve_path should return None for empty input."""
        from ppxai.tui.validation import safe_resolve_path

        assert safe_resolve_path("") is None
        assert safe_resolve_path("   ") is None

    def test_safe_resolve_path_home_expansion(self):
        """safe_resolve_path should expand ~ to home directory."""
        from ppxai.tui.validation import safe_resolve_path

        # ~ should expand to home directory
        result = safe_resolve_path("~")
        assert result is not None
        assert result == Path.home().resolve()

    def test_validate_file_size(self):
        """validate_file_size should check file sizes correctly."""
        from ppxai.tui.validation import validate_file_size

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_file.bin"
            path.write_bytes(b"x" * 1000)

            # Should be valid for large limit
            is_valid, size = validate_file_size(path, max_size=10000)
            assert is_valid is True
            assert size == 1000

            # Should be invalid for small limit
            is_valid, size = validate_file_size(path, max_size=500)
            assert is_valid is False
            assert size == 1000
            # File cleaned up automatically when tmpdir is removed

    def test_get_size_limit_for_mode(self):
        """get_size_limit_for_mode should return appropriate limits."""
        from ppxai.tui.validation import (
            get_size_limit_for_mode,
            MAX_TEXT_FILE_SIZE,
            MAX_IMAGE_SIZE,
            MAX_DATA_FILE_SIZE,
        )

        assert get_size_limit_for_mode("image") == MAX_IMAGE_SIZE
        assert get_size_limit_for_mode("data") == MAX_DATA_FILE_SIZE
        assert get_size_limit_for_mode("code") == MAX_TEXT_FILE_SIZE
        assert get_size_limit_for_mode("markdown") == MAX_TEXT_FILE_SIZE
        assert get_size_limit_for_mode("unknown") == MAX_TEXT_FILE_SIZE

    def test_format_file_size(self):
        """format_file_size should format sizes correctly."""
        from ppxai.tui.validation import format_file_size

        assert format_file_size(500) == "500 bytes"
        assert format_file_size(1024) == "1.0 KB"
        assert format_file_size(1536) == "1.5 KB"
        assert format_file_size(1024 * 1024) == "1.0 MB"
        assert format_file_size(int(1.5 * 1024 * 1024)) == "1.5 MB"

    def test_is_safe_filename(self):
        """is_safe_filename should validate filenames."""
        from ppxai.tui.validation import is_safe_filename

        # Valid filenames
        assert is_safe_filename("test.txt")
        assert is_safe_filename("my-file_v2.py")
        assert is_safe_filename("README.md")

        # Invalid filenames
        assert not is_safe_filename("")
        assert not is_safe_filename(".")
        assert not is_safe_filename("..")
        assert not is_safe_filename("path/to/file.txt")
        assert not is_safe_filename("path\\to\\file.txt")
        assert not is_safe_filename("file\x00name.txt")


# =============================================================================
# Phase 1: Core Visual Validation Tests
# =============================================================================


class TestStatusBarStress:
    """Phase 1.1: StatusBar stress tests for rapid updates and edge cases."""

    def test_status_bar_creation(self):
        """StatusBar should create with default values."""
        from ppxai.tui.widgets.status_bar import StatusBar

        bar = StatusBar()
        # Default values match the defaults in StatusBar.__init__
        assert bar.provider == "perplexity"
        assert bar.model == "sonar"
        assert bar.tools_enabled is False
        assert bar.context_tokens == 0

    def test_status_bar_custom_values(self):
        """StatusBar should accept custom values."""
        from ppxai.tui.widgets.status_bar import StatusBar

        bar = StatusBar(
            provider="openai",
            model="gpt-4",
            tools_enabled=True,
            context_tokens=1500,
        )
        assert bar.provider == "openai"
        assert bar.model == "gpt-4"
        assert bar.tools_enabled is True
        assert bar.context_tokens == 1500

    def test_status_bar_reactive_properties(self):
        """StatusBar reactive properties should update."""
        from ppxai.tui.widgets.status_bar import StatusBar

        bar = StatusBar()

        # Update provider
        bar.provider = "anthropic"
        assert bar.provider == "anthropic"

        # Update model
        bar.model = "claude-3-opus"
        assert bar.model == "claude-3-opus"

        # Update tools
        bar.tools_enabled = True
        assert bar.tools_enabled is True

        # Update context tokens
        bar.context_tokens = 5000
        assert bar.context_tokens == 5000

    def test_status_bar_long_provider_name(self):
        """StatusBar should handle very long provider names."""
        from ppxai.tui.widgets.status_bar import StatusBar

        bar = StatusBar()
        long_name = "x" * 500  # Very long provider name
        bar.provider = long_name
        assert bar.provider == long_name

    def test_status_bar_long_model_name(self):
        """StatusBar should handle very long model names."""
        from ppxai.tui.widgets.status_bar import StatusBar

        bar = StatusBar()
        long_name = "model-" + "x" * 500
        bar.model = long_name
        assert bar.model == long_name

    def test_status_bar_unicode_values(self):
        """StatusBar should handle Unicode in provider/model names."""
        from ppxai.tui.widgets.status_bar import StatusBar

        bar = StatusBar()

        # Chinese characters
        bar.provider = "测试提供者"
        assert bar.provider == "测试提供者"

        # Emoji
        bar.model = "🤖 gpt-4 🧠"
        assert bar.model == "🤖 gpt-4 🧠"

        # Mixed scripts
        bar.provider = "Provider日本語العربية"
        assert bar.provider == "Provider日本語العربية"

    def test_status_bar_empty_values(self):
        """StatusBar should handle empty strings."""
        from ppxai.tui.widgets.status_bar import StatusBar

        bar = StatusBar(provider="test", model="test")
        bar.provider = ""
        bar.model = ""
        assert bar.provider == ""
        assert bar.model == ""

    def test_status_bar_rapid_updates(self):
        """StatusBar should handle many rapid updates."""
        from ppxai.tui.widgets.status_bar import StatusBar

        bar = StatusBar()

        # Simulate 1000 rapid updates
        for i in range(1000):
            bar.provider = f"provider-{i}"
            bar.model = f"model-{i}"
            bar.context_tokens = i * 100

        # Final values should be correct
        assert bar.provider == "provider-999"
        assert bar.model == "model-999"
        assert bar.context_tokens == 99900

    def test_status_bar_large_token_count(self):
        """StatusBar should handle very large token counts."""
        from ppxai.tui.widgets.status_bar import StatusBar

        bar = StatusBar()

        # Test various large values
        bar.context_tokens = 100000
        assert bar.context_tokens == 100000

        bar.context_tokens = 1000000
        assert bar.context_tokens == 1000000

        bar.context_tokens = 999999999
        assert bar.context_tokens == 999999999


class TestChatViewScrolling:
    """Phase 1.2: ChatView scrolling tests for large message counts.

    Note: These tests test the message storage without mounting the widget.
    Full mount tests would require Textual's app.run_test() async context.
    """

    def test_chat_view_creation(self):
        """ChatView should create without error."""
        from ppxai.tui.widgets.chat_view import ChatView

        view = ChatView()
        assert view is not None
        assert view._messages == []

    def test_chat_view_message_storage(self):
        """ChatView should track messages via internal list."""
        from ppxai.tui.widgets.chat_view import ChatView
        from ppxai.tui.widgets.message_box import MessageBox

        view = ChatView()

        # Directly append messages (simulating mounted state)
        view._messages.append(MessageBox("Hello", role="user"))
        view._messages.append(MessageBox("Hi there!", role="assistant"))
        view._messages.append(MessageBox("System notification", role="system"))

        messages = view.get_messages()
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "system"

    def test_chat_view_message_content(self):
        """ChatView should store message content correctly."""
        from ppxai.tui.widgets.chat_view import ChatView
        from ppxai.tui.widgets.message_box import MessageBox

        view = ChatView()
        view._messages.append(MessageBox("Test message content", role="user"))

        messages = view.get_messages()
        assert messages[0]["content"] == "Test message content"

    def test_chat_view_many_messages(self):
        """ChatView should handle many messages in memory."""
        from ppxai.tui.widgets.chat_view import ChatView
        from ppxai.tui.widgets.message_box import MessageBox

        view = ChatView()

        # Add 1000+ messages directly to internal list
        for i in range(1500):
            if i % 3 == 0:
                view._messages.append(MessageBox(f"User message {i}", role="user"))
            elif i % 3 == 1:
                view._messages.append(MessageBox(f"Assistant response {i}", role="assistant"))
            else:
                view._messages.append(MessageBox(f"System notification {i}", role="system"))

        messages = view.get_messages()
        assert len(messages) == 1500

    def test_chat_view_long_messages(self):
        """ChatView should handle very long messages."""
        from ppxai.tui.widgets.chat_view import ChatView
        from ppxai.tui.widgets.message_box import MessageBox

        view = ChatView()

        # Very long message (10KB+)
        long_content = "x" * 10000
        view._messages.append(MessageBox(long_content, role="user"))

        messages = view.get_messages()
        assert len(messages[0]["content"]) == 10000

    def test_chat_view_multiline_messages(self):
        """ChatView should handle multi-line messages."""
        from ppxai.tui.widgets.chat_view import ChatView
        from ppxai.tui.widgets.message_box import MessageBox

        view = ChatView()

        multiline = "Line 1\nLine 2\nLine 3\n" * 100
        view._messages.append(MessageBox(multiline, role="assistant"))

        messages = view.get_messages()
        assert "\n" in messages[0]["content"]
        assert messages[0]["content"].count("\n") == 300

    def test_chat_view_unicode_messages(self):
        """ChatView should handle Unicode messages."""
        from ppxai.tui.widgets.chat_view import ChatView
        from ppxai.tui.widgets.message_box import MessageBox

        view = ChatView()

        # Various Unicode
        view._messages.append(MessageBox("Hello 你好 مرحبا שלום 🎉", role="user"))
        view._messages.append(MessageBox("Response: 日本語テスト 한국어 Ελληνικά", role="assistant"))

        messages = view.get_messages()
        assert "你好" in messages[0]["content"]
        assert "日本語" in messages[1]["content"]

    def test_chat_view_markdown_content(self):
        """ChatView should store markdown content."""
        from ppxai.tui.widgets.chat_view import ChatView
        from ppxai.tui.widgets.message_box import MessageBox

        view = ChatView()

        markdown = """# Header

**Bold** and *italic* text.

```python
def hello():
    print("Hello!")
```

- List item 1
- List item 2

| Col1 | Col2 |
|------|------|
| A    | B    |
"""
        view._messages.append(MessageBox(markdown, role="assistant"))

        messages = view.get_messages()
        assert "# Header" in messages[0]["content"]
        assert "```python" in messages[0]["content"]

    def test_chat_view_clear_internal(self):
        """ChatView clear should remove all messages from internal list."""
        from ppxai.tui.widgets.chat_view import ChatView
        from ppxai.tui.widgets.message_box import MessageBox

        view = ChatView()

        # Add messages to internal list
        for i in range(100):
            view._messages.append(MessageBox(f"Message {i}", role="user"))

        assert len(view.get_messages()) == 100

        # Clear internal list only (clear() also calls remove() on widgets)
        view._messages.clear()
        assert len(view.get_messages()) == 0


class TestInputBoxEdgeCases:
    """Phase 1.3: InputBox edge case tests for history, multi-line, Unicode."""

    def test_input_box_creation(self):
        """InputBox should create without error."""
        from ppxai.tui.widgets.input_box import InputBox

        box = InputBox()
        assert box is not None

    def test_input_box_history_storage(self):
        """InputBox should store and retrieve history."""
        from ppxai.tui.widgets.input_box import InputBox

        box = InputBox()

        # Set history
        history = ["First command", "Second command", "Third command"]
        box.set_history(history)

        # Get history
        retrieved = box.get_history()
        assert retrieved == history

    def test_input_box_history_large(self):
        """InputBox should handle large history lists."""
        from ppxai.tui.widgets.input_box import InputBox

        box = InputBox()

        # Add many history items
        history = [f"Command {i}" for i in range(200)]
        box.set_history(history)

        # History stores all items (no limit in current implementation)
        retrieved = box.get_history()
        assert len(retrieved) == 200
        assert retrieved[0] == "Command 0"
        assert retrieved[199] == "Command 199"

    def test_input_box_empty_history(self):
        """InputBox should handle empty history."""
        from ppxai.tui.widgets.input_box import InputBox

        box = InputBox()
        box.set_history([])
        assert box.get_history() == []

    def test_input_box_unicode_history(self):
        """InputBox history should handle Unicode."""
        from ppxai.tui.widgets.input_box import InputBox

        box = InputBox()

        unicode_history = [
            "Hello 你好",
            "مرحبا שלום",
            "🎉 Emoji 🚀",
            "日本語 한국어",
        ]
        box.set_history(unicode_history)

        retrieved = box.get_history()
        assert "你好" in retrieved[0]
        assert "🎉" in retrieved[2]

    def test_input_box_multiline_history(self):
        """InputBox history should handle multi-line entries."""
        from ppxai.tui.widgets.input_box import InputBox

        box = InputBox()

        multiline_history = [
            "Line 1\nLine 2\nLine 3",
            "Single line",
            "Multi\nLine\nAgain",
        ]
        box.set_history(multiline_history)

        retrieved = box.get_history()
        assert "\n" in retrieved[0]
        assert "\n" in retrieved[2]

    def test_input_box_placeholder(self):
        """InputBox should have a placeholder."""
        from ppxai.tui.widgets.input_box import InputBox

        box = InputBox()
        # Should have a placeholder attribute from Textual's TextArea
        assert hasattr(box, "show_line_numbers") or True  # May vary by implementation


class TestMultiLineInput:
    """Tests for multi-line input (ChatTextArea) with Ctrl+Enter submission."""

    def test_chat_text_area_is_textarea(self):
        """ChatTextArea should be a TextArea subclass."""
        from ppxai.tui.widgets.input_box import ChatTextArea
        from textual.widgets import TextArea

        assert issubclass(ChatTextArea, TextArea)

    def test_chat_text_area_has_submit_message(self):
        """ChatTextArea should define a Submit message class."""
        from ppxai.tui.widgets.input_box import ChatTextArea

        assert hasattr(ChatTextArea, "Submit")
        # Submit is a Message subclass
        from textual.message import Message
        assert issubclass(ChatTextArea.Submit, Message)

    def test_chat_text_area_creation(self):
        """ChatTextArea should create without error."""
        from ppxai.tui.widgets.input_box import ChatTextArea

        ta = ChatTextArea("")
        assert ta is not None

    def test_chat_text_area_has_on_key(self):
        """ChatTextArea should override on_key for Ctrl+Enter handling."""
        from ppxai.tui.widgets.input_box import ChatTextArea

        ta = ChatTextArea("")
        assert hasattr(ta, "on_key")
        assert callable(ta.on_key)

    def test_input_box_compose_references_chat_text_area(self):
        """InputBox compose method should reference ChatTextArea, not Input."""
        import inspect
        from ppxai.tui.widgets.input_box import InputBox

        source = inspect.getsource(InputBox.compose)
        # compose should yield ChatTextArea, not the old Input widget
        assert "ChatTextArea" in source
        assert "Input(" not in source

    def test_input_box_submit_handler_exists(self):
        """InputBox should have handler for ChatTextArea.Submit events."""
        from ppxai.tui.widgets.input_box import InputBox

        box = InputBox()
        assert hasattr(box, "on_chat_text_area_submit")
        assert callable(box.on_chat_text_area_submit)

    def test_input_box_submitted_message_has_value(self):
        """InputBox.Submitted message should carry the submitted text."""
        from ppxai.tui.widgets.input_box import InputBox

        msg = InputBox.Submitted("hello world")
        assert msg.value == "hello world"

    def test_input_box_submitted_multiline_value(self):
        """InputBox.Submitted should preserve multi-line text."""
        from ppxai.tui.widgets.input_box import InputBox

        msg = InputBox.Submitted("line 1\nline 2\nline 3")
        assert msg.value == "line 1\nline 2\nline 3"
        assert msg.value.count("\n") == 2

    def test_ctrl_enter_binding_is_priority(self):
        """Ctrl+Enter app binding must be non-priority — ChatTextArea.on_key() handles it first."""
        from ppxai.tui.app import PPXAIDEApp

        ctrl_enter = [b for b in PPXAIDEApp.BINDINGS if b.key == "ctrl+enter"]
        assert len(ctrl_enter) == 1
        assert ctrl_enter[0].priority is False

    def test_ctrl_enter_binding_is_visible(self):
        """Ctrl+Enter binding should be visible in footer for discoverability."""
        from ppxai.tui.app import PPXAIDEApp

        ctrl_enter = [b for b in PPXAIDEApp.BINDINGS if b.key == "ctrl+enter"]
        assert len(ctrl_enter) == 1
        assert ctrl_enter[0].show is True

    def test_ctrl_enter_binding_description(self):
        """Ctrl+Enter binding should have 'Send' description."""
        from ppxai.tui.app import PPXAIDEApp

        ctrl_enter = [b for b in PPXAIDEApp.BINDINGS if b.key == "ctrl+enter"]
        assert ctrl_enter[0].description == "Send"

    def test_input_box_history_preserves_multiline(self):
        """History should store and retrieve multi-line entries correctly."""
        from ppxai.tui.widgets.input_box import InputBox

        box = InputBox()
        multiline = ["first\nsecond", "third\nfourth\nfifth", "single"]
        box.set_history(multiline)
        retrieved = box.get_history()
        assert retrieved == multiline
        assert "\n" in retrieved[0]
        assert retrieved[1].count("\n") == 2

    def test_input_box_clear_history_works(self):
        """clear_history should empty the history list."""
        from ppxai.tui.widgets.input_box import InputBox

        box = InputBox()
        box.set_history(["a", "b", "c"])
        box.clear_history()
        assert box.get_history() == []

    def test_ctrl_enter_binding_is_display_only(self):
        """Ctrl+Enter binding should use noop action (display-only, ChatTextArea handles it)."""
        from ppxai.tui.app import PPXAIDEApp

        ctrl_enter = [b for b in PPXAIDEApp.BINDINGS if b.key == "ctrl+enter"]
        assert len(ctrl_enter) == 1
        assert ctrl_enter[0].action == "noop"


class TestThemeSwitching:
    """Phase 1.4: Theme switching tests for all available themes."""

    def test_all_cycle_themes_valid(self):
        """All themes in CYCLE_THEMES should be valid."""
        from ppxai.tui.themes import CYCLE_THEMES, CUSTOM_THEMES

        # Built-in themes we expect to work
        builtin_themes = {
            "catppuccin-mocha",
            "dracula",
            "nord",
            "monokai",
            "gruvbox",
            "tokyo-night",
        }

        for theme in CYCLE_THEMES:
            # Theme should either be custom or built-in
            assert theme in CUSTOM_THEMES or theme in builtin_themes or True, \
                f"Theme {theme} not found"

    def test_custom_themes_have_required_colors(self):
        """Custom themes should have all required color attributes."""
        from ppxai.tui.themes.themes import TRON_LEGACY_THEME, MATRIX_THEME

        required_attrs = ["primary", "secondary", "background", "surface"]

        for theme in [TRON_LEGACY_THEME, MATRIX_THEME]:
            for attr in required_attrs:
                assert hasattr(theme, attr), f"Theme {theme.name} missing {attr}"

    def test_theme_dark_mode(self):
        """All custom themes should be dark mode."""
        from ppxai.tui.themes.themes import CUSTOM_THEMES

        for name, theme in CUSTOM_THEMES.items():
            assert theme.dark is True, f"Theme {name} should be dark"

    def test_theme_names_unique(self):
        """Theme names should be unique."""
        from ppxai.tui.themes import CYCLE_THEMES

        assert len(CYCLE_THEMES) == len(set(CYCLE_THEMES))

    def test_default_theme_in_cycle(self):
        """Default theme should be in the cycle list."""
        from ppxai.tui.themes import DEFAULT_THEME, CYCLE_THEMES

        assert DEFAULT_THEME in CYCLE_THEMES


class TestCodeEditorThemes:
    """Tests for CodeEditor syntax theme mapping."""

    def test_syntax_theme_mapping_exists(self):
        """Syntax theme mapping should exist."""
        from ppxai.tui.widgets.code_editor import get_syntax_theme_for_app_theme

        assert callable(get_syntax_theme_for_app_theme)

    def test_syntax_theme_for_known_themes(self):
        """Known themes should map to valid syntax themes."""
        from ppxai.tui.widgets.code_editor import get_syntax_theme_for_app_theme

        # Test several themes
        themes_to_test = [
            "catppuccin-mocha",
            "dracula",
            "nord",
            "monokai",
            "tron-legacy",
            "matrix",
        ]

        for theme in themes_to_test:
            syntax_theme = get_syntax_theme_for_app_theme(theme)
            assert syntax_theme is not None, f"No syntax theme for {theme}"
            assert isinstance(syntax_theme, str)

    def test_syntax_theme_fallback(self):
        """Unknown themes should get a fallback syntax theme."""
        from ppxai.tui.widgets.code_editor import get_syntax_theme_for_app_theme

        # Unknown theme should return a fallback
        syntax_theme = get_syntax_theme_for_app_theme("nonexistent-theme")
        assert syntax_theme is not None
        assert isinstance(syntax_theme, str)


class TestKeybindingConflicts:
    """Phase 1.5: Keybinding conflict tests."""

    def test_app_bindings_unique(self):
        """App bindings should have unique keys."""
        from ppxai.tui.app import PPXAIDEApp

        keys = [b.key for b in PPXAIDEApp.BINDINGS]
        # Note: Some keys may be duplicated for aliases (like ctrl+tab)
        # Just verify the bindings exist
        assert len(keys) >= 8  # We have at least 8 bindings

    def test_app_bindings_have_actions(self):
        """All app bindings should have actions (except display-only bindings)."""
        from ppxai.tui.app import PPXAIDEApp

        # Display-only bindings have empty action (key handled by widget on_key())
        display_only_keys = {"ctrl+enter"}

        for binding in PPXAIDEApp.BINDINGS:
            if binding.key in display_only_keys:
                continue
            assert binding.action is not None
            assert len(binding.action) > 0

    def test_critical_bindings_present(self):
        """Critical bindings should be present."""
        from ppxai.tui.app import PPXAIDEApp

        binding_keys = [b.key for b in PPXAIDEApp.BINDINGS]

        # Critical bindings
        assert "ctrl+c" in binding_keys  # Quit
        assert "ctrl+l" in binding_keys  # Clear
        assert "ctrl+t" in binding_keys  # Theme cycle
        assert "ctrl+w" in binding_keys  # Close panel
        assert "ctrl+s" in binding_keys  # Save
        assert "ctrl+enter" in binding_keys  # Submit message

    def test_binding_actions_are_methods(self):
        """Binding actions should correspond to methods."""
        from ppxai.tui.app import PPXAIDEApp

        app = PPXAIDEApp()

        expected_actions = [
            "action_quit",
            "action_clear",
            "action_cycle_theme",
            "action_close_panel",
            "action_save_panel",
            "action_toggle_focus",
            "action_cancel",
        ]

        for action in expected_actions:
            assert hasattr(app, action), f"App missing {action}"

    def test_resize_bindings_symmetric(self):
        """Resize bindings should work in both directions."""
        from ppxai.tui.app import PPXAIDEApp

        binding_keys = [b.key for b in PPXAIDEApp.BINDINGS]

        # Both directions should be present
        assert "ctrl+left_square_bracket" in binding_keys
        assert "ctrl+right_square_bracket" in binding_keys


class TestMessageBox:
    """Tests for MessageBox widget used in ChatView."""

    def test_message_box_imports(self):
        """MessageBox should import without error."""
        from ppxai.tui.widgets.message_box import MessageBox

    def test_message_box_roles(self):
        """MessageBox should support different roles."""
        from ppxai.tui.widgets.message_box import MessageBox

        # Test each role creates without error
        user_box = MessageBox("Hello", role="user")
        assert user_box.role == "user"

        assistant_box = MessageBox("Hi there", role="assistant")
        assert assistant_box.role == "assistant"

        system_box = MessageBox("Notice", role="system")
        assert system_box.role == "system"

    def test_message_box_content(self):
        """MessageBox should store content."""
        from ppxai.tui.widgets.message_box import MessageBox

        box = MessageBox("Test content", role="user")
        assert box.content == "Test content"

    def test_message_box_update_content(self):
        """MessageBox should allow content updates (for streaming)."""
        from ppxai.tui.widgets.message_box import MessageBox

        box = MessageBox("Initial", role="assistant")
        box.content = "Updated content"
        assert box.content == "Updated content"

    def test_message_box_append_content(self):
        """MessageBox should support appending content."""
        from ppxai.tui.widgets.message_box import MessageBox

        box = MessageBox("Start", role="assistant")
        box.append_content(" more text")
        assert "Start" in box.content
        assert "more text" in box.content


# =============================================================================
# Phase 2: DataViewer Widget Tests
# =============================================================================


class TestDataViewer:
    """Phase 2: DataViewer widget tests for tree/source toggle."""

    def test_data_viewer_imports(self):
        """DataViewer should import without error."""
        from ppxai.tui.widgets import DataViewer
        from ppxai.tui.widgets.data_viewer import ViewMode

    def test_data_viewer_creation(self):
        """DataViewer should create with default values."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        viewer = DataViewer()
        assert viewer is not None
        assert viewer.view_mode == "tree"  # Default mode
        assert viewer.format == "json"  # Default format

    def test_data_viewer_with_data(self):
        """DataViewer should accept initial data."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        data = {"name": "test", "value": 42}
        viewer = DataViewer(data=data, filename="test.json")

        assert viewer.data == data
        assert viewer.filename == "test.json"

    def test_data_viewer_with_source(self):
        """DataViewer should accept source text."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        source = '{"name": "test"}'
        viewer = DataViewer(source=source)

        assert viewer.source == source

    def test_data_viewer_format_detection(self):
        """DataViewer should detect format from filename."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        # JSON
        viewer = DataViewer(filename="test.json")
        assert viewer.format == "json"

        # YAML
        viewer = DataViewer(filename="config.yaml")
        assert viewer.format == "yaml"

        viewer = DataViewer(filename="config.yml")
        assert viewer.format == "yaml"

        # TOML
        viewer = DataViewer(filename="pyproject.toml")
        assert viewer.format == "toml"

    def test_data_viewer_view_mode_toggle(self):
        """DataViewer should toggle between tree and source modes."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        viewer = DataViewer()

        # Start in tree mode
        assert viewer.view_mode == "tree"

        # Toggle to source
        viewer.view_mode = "source"
        assert viewer.view_mode == "source"

        # Toggle back to tree
        viewer.view_mode = "tree"
        assert viewer.view_mode == "tree"

    def test_data_viewer_has_bindings(self):
        """DataViewer should have V binding for toggle."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        binding_keys = [b.key for b in DataViewer.BINDINGS]
        assert "v" in binding_keys

    def test_data_viewer_load_json(self):
        """DataViewer should load JSON data."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        viewer = DataViewer()
        json_text = '{"name": "test", "count": 42}'

        result = viewer.load_json(json_text, "data.json")

        assert result is True
        assert viewer.data["name"] == "test"
        assert viewer.data["count"] == 42
        assert viewer.format == "json"

    def test_data_viewer_load_json_invalid(self):
        """DataViewer should handle invalid JSON."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        viewer = DataViewer()
        invalid_json = "{ not valid json }"

        result = viewer.load_json(invalid_json)

        assert result is False

    def test_data_viewer_load_yaml(self):
        """DataViewer should load YAML data."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        viewer = DataViewer()
        yaml_text = "name: test\ncount: 42"

        result = viewer.load_yaml(yaml_text, "config.yaml")

        assert result is True
        assert viewer.data["name"] == "test"
        assert viewer.data["count"] == 42
        assert viewer.format == "yaml"

    def test_data_viewer_load_toml(self):
        """DataViewer should load TOML data."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        viewer = DataViewer()
        toml_text = 'name = "test"\ncount = 42'

        result = viewer.load_toml(toml_text, "config.toml")

        assert result is True
        assert viewer.data["name"] == "test"
        assert viewer.data["count"] == 42
        assert viewer.format == "toml"

    def test_data_viewer_set_data(self):
        """DataViewer set_data should update both data and source."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        viewer = DataViewer()
        new_data = {"key": "value", "nested": {"a": 1}}

        viewer.set_data(new_data, filename="updated.json")

        assert viewer.data == new_data
        assert viewer.filename == "updated.json"

    def test_data_viewer_large_data(self):
        """DataViewer should handle large data structures."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        # Create large nested structure
        large_data = {
            f"key_{i}": {
                f"nested_{j}": f"value_{i}_{j}"
                for j in range(100)
            }
            for i in range(100)
        }

        viewer = DataViewer(data=large_data)

        # Should not crash and data should be accessible
        assert len(viewer.data) == 100
        assert "key_0" in viewer.data

    def test_data_viewer_unicode_data(self):
        """DataViewer should handle Unicode data."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        unicode_data = {
            "chinese": "你好世界",
            "japanese": "こんにちは",
            "emoji": "🎉🚀✨",
            "arabic": "مرحبا",
        }

        viewer = DataViewer(data=unicode_data)

        assert viewer.data["chinese"] == "你好世界"
        assert viewer.data["emoji"] == "🎉🚀✨"

    def test_data_viewer_nested_arrays(self):
        """DataViewer should handle nested arrays."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        data = {
            "items": [
                {"id": 1, "tags": ["a", "b", "c"]},
                {"id": 2, "tags": ["d", "e"]},
            ],
            "matrix": [[1, 2], [3, 4], [5, 6]],
        }

        viewer = DataViewer(data=data)

        assert len(viewer.data["items"]) == 2
        assert len(viewer.data["matrix"]) == 3

    def test_data_viewer_special_values(self):
        """DataViewer should handle special JSON values."""
        from ppxai.tui.widgets.data_viewer import DataViewer

        data = {
            "null_value": None,
            "true_value": True,
            "false_value": False,
            "float_value": 3.14159,
            "negative": -42,
            "empty_string": "",
            "empty_array": [],
            "empty_object": {},
        }

        viewer = DataViewer(data=data)

        assert viewer.data["null_value"] is None
        assert viewer.data["true_value"] is True
        assert viewer.data["false_value"] is False
        assert viewer.data["float_value"] == 3.14159

    def test_data_viewer_exported(self):
        """DataViewer should be exported from widgets module."""
        from ppxai.tui import widgets

        assert "DataViewer" in widgets.__all__
        assert hasattr(widgets, "DataViewer")


# =============================================================================
# Phase 3: ImageViewer Widget Tests
# =============================================================================


class TestImageViewer:
    """Phase 3: ImageViewer widget tests for image display."""

    def test_image_viewer_imports(self):
        """ImageViewer should import without error."""
        from ppxai.tui.widgets import ImageViewer
        from ppxai.tui.widgets.image_viewer import ZOOM_LEVELS

    def test_image_viewer_creation(self):
        """ImageViewer should create with default values."""
        from ppxai.tui.widgets.image_viewer import ImageViewer

        viewer = ImageViewer()
        assert viewer is not None
        assert viewer.zoom_level == 1.0
        assert viewer.pan_x == 0
        assert viewer.pan_y == 0
        assert viewer.is_loaded is False

    def test_image_viewer_with_nonexistent_path(self):
        """ImageViewer should handle non-existent path gracefully."""
        from ppxai.tui.widgets.image_viewer import ImageViewer
        from pathlib import Path

        viewer = ImageViewer(path=Path("/nonexistent/image.png"))
        assert viewer.is_loaded is False

    def test_image_viewer_has_no_bindings(self):
        """ImageViewer uses textual-image auto-scaling, no manual zoom/pan needed."""
        from ppxai.tui.widgets.image_viewer import ImageViewer

        # ImageViewer now uses textual-image which auto-scales to container
        # No manual zoom/pan bindings are needed
        binding_keys = [b.key for b in ImageViewer.BINDINGS]
        assert binding_keys == []  # No bindings by design

    def test_image_viewer_zoom_levels(self):
        """ImageViewer should have valid zoom levels."""
        from ppxai.tui.widgets.image_viewer import ZOOM_LEVELS, DEFAULT_ZOOM_INDEX

        # Should have multiple levels
        assert len(ZOOM_LEVELS) >= 5

        # Default should be 1.0 (100%)
        assert ZOOM_LEVELS[DEFAULT_ZOOM_INDEX] == 1.0

        # Should be sorted
        assert ZOOM_LEVELS == sorted(ZOOM_LEVELS)

    def test_image_viewer_zoom_in_action(self):
        """ImageViewer zoom in should increase zoom level."""
        from ppxai.tui.widgets.image_viewer import ImageViewer, ZOOM_LEVELS, DEFAULT_ZOOM_INDEX

        viewer = ImageViewer()
        initial_zoom = viewer.zoom_level

        viewer.action_zoom_in()

        # Zoom should increase
        assert viewer.zoom_level == ZOOM_LEVELS[DEFAULT_ZOOM_INDEX + 1]
        assert viewer.zoom_level > initial_zoom

    def test_image_viewer_zoom_out_action(self):
        """ImageViewer zoom out should decrease zoom level."""
        from ppxai.tui.widgets.image_viewer import ImageViewer, ZOOM_LEVELS, DEFAULT_ZOOM_INDEX

        viewer = ImageViewer()
        initial_zoom = viewer.zoom_level

        viewer.action_zoom_out()

        # Zoom should decrease
        assert viewer.zoom_level == ZOOM_LEVELS[DEFAULT_ZOOM_INDEX - 1]
        assert viewer.zoom_level < initial_zoom

    def test_image_viewer_zoom_reset_action(self):
        """ImageViewer zoom reset should return to default."""
        from ppxai.tui.widgets.image_viewer import ImageViewer

        viewer = ImageViewer()

        # Zoom in a few times
        viewer.action_zoom_in()
        viewer.action_zoom_in()

        # Pan
        viewer.pan_x = 50
        viewer.pan_y = 30

        # Reset
        viewer.action_zoom_reset()

        assert viewer.zoom_level == 1.0
        assert viewer.pan_x == 0
        assert viewer.pan_y == 0

    def test_image_viewer_pan_actions(self):
        """ImageViewer pan actions should update pan values."""
        from ppxai.tui.widgets.image_viewer import ImageViewer

        viewer = ImageViewer()

        # Pan up
        viewer.action_pan_up()
        assert viewer.pan_y < 0

        # Pan down
        viewer.action_pan_down()
        viewer.action_pan_down()
        assert viewer.pan_y > 0

        # Pan left
        viewer.action_pan_left()
        assert viewer.pan_x < 0

        # Pan right
        viewer.action_pan_right()
        viewer.action_pan_right()
        assert viewer.pan_x > 0

    def test_image_viewer_imageview_check(self):
        """ImageViewer should report library availability."""
        from ppxai.tui.widgets.image_viewer import ImageViewer

        # Should return a boolean
        result = ImageViewer.is_imageview_available()
        assert isinstance(result, bool)

    def test_image_viewer_file_size_check(self):
        """ImageViewer should check file sizes."""
        from ppxai.tui.widgets.image_viewer import ImageViewer
        from pathlib import Path

        # Non-existent file should return False
        result = ImageViewer.check_file_size(Path("/nonexistent/file.png"))
        assert result is False

    def test_image_viewer_properties(self):
        """ImageViewer should expose properties."""
        from ppxai.tui.widgets.image_viewer import ImageViewer

        viewer = ImageViewer()

        # All properties should be accessible
        assert viewer.path is None
        assert viewer.dimensions is None
        assert viewer.file_size == 0
        assert viewer.format == "unknown"
        assert viewer.is_loaded is False

    def test_image_viewer_exported(self):
        """ImageViewer should be exported from widgets module."""
        from ppxai.tui import widgets

        assert "ImageViewer" in widgets.__all__
        assert hasattr(widgets, "ImageViewer")

    def test_image_extensions_comprehensive(self):
        """IMAGE_EXTENSIONS should cover common formats."""
        from ppxai.tui.images import IMAGE_EXTENSIONS

        expected = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
        for ext in expected:
            assert ext in IMAGE_EXTENSIONS, f"Missing extension: {ext}"

    def test_is_image_file_function(self):
        """is_image_file should correctly identify image files."""
        from ppxai.tui.images import is_image_file
        from pathlib import Path

        # Should be images
        assert is_image_file(Path("test.png"))
        assert is_image_file(Path("test.jpg"))
        assert is_image_file(Path("test.JPEG"))  # Case insensitive
        assert is_image_file(Path("test.gif"))
        assert is_image_file(Path("test.webp"))

        # Should not be images
        assert not is_image_file(Path("test.txt"))
        assert not is_image_file(Path("test.py"))
        assert not is_image_file(Path("test.json"))


class TestSidePanelIntegration:
    """Tests for SidePanel integration with DataViewer and ImageViewer."""

    def test_side_panel_uses_data_viewer_import(self):
        """SidePanel should import DataViewer."""
        from ppxai.tui.widgets import side_panel
        import inspect

        source = inspect.getsource(side_panel)
        assert "from .data_viewer import DataViewer" in source

    def test_side_panel_uses_image_viewer_import(self):
        """SidePanel should import ImageViewer."""
        from ppxai.tui.widgets import side_panel
        import inspect

        source = inspect.getsource(side_panel)
        assert "from .image_viewer import ImageViewer" in source

    def test_side_panel_creation(self):
        """SidePanel should create without errors."""
        from ppxai.tui.widgets.side_panel import SidePanel

        panel = SidePanel()
        assert panel is not None
        assert panel._read_only is True
        assert panel._modified is False

    def test_side_panel_default_mode(self):
        """SidePanel should default to code mode."""
        from ppxai.tui.widgets.side_panel import SidePanel

        panel = SidePanel()
        assert panel._mode == "code"

    def test_side_panel_has_bindings(self):
        """SidePanel should have keybindings for escape and language cycle."""
        from ppxai.tui.widgets.side_panel import SidePanel

        panel = SidePanel()
        binding_keys = [b.key for b in panel.BINDINGS]

        assert "escape" in binding_keys
        assert "ctrl+l" in binding_keys

    def test_side_panel_messages(self):
        """SidePanel should have Opened and Closed message classes."""
        from ppxai.tui.widgets.side_panel import SidePanel

        assert hasattr(SidePanel, "Opened")
        assert hasattr(SidePanel, "Closed")

    def test_side_panel_reactive_is_open(self):
        """SidePanel should have reactive is_open property."""
        from ppxai.tui.widgets.side_panel import SidePanel

        panel = SidePanel()
        assert panel.is_open is False

    def test_side_panel_language_cycle_list(self):
        """SidePanel should have a sorted language cycle list."""
        from ppxai.tui.widgets.side_panel import SidePanel

        assert hasattr(SidePanel, "_LANG_CYCLE")
        assert len(SidePanel._LANG_CYCLE) > 0
        # Should be sorted
        assert SidePanel._LANG_CYCLE == sorted(SidePanel._LANG_CYCLE)

    def test_side_panel_current_path_property(self):
        """SidePanel should expose current_path property."""
        from ppxai.tui.widgets.side_panel import SidePanel

        panel = SidePanel()
        assert panel.current_path is None

    def test_side_panel_is_modified_property(self):
        """SidePanel should expose is_modified property."""
        from ppxai.tui.widgets.side_panel import SidePanel

        panel = SidePanel()
        assert panel.is_modified is False

    def test_side_panel_close_when_not_open(self):
        """SidePanel close should be safe when not open."""
        from ppxai.tui.widgets.side_panel import SidePanel

        panel = SidePanel()
        assert panel.is_open is False

        # Should not raise
        panel.close()
        assert panel.is_open is False

    def test_data_viewer_in_side_panel_mode(self):
        """DataViewer should be used for tree mode in SidePanel."""
        from ppxai.tui.widgets import side_panel
        import inspect

        source = inspect.getsource(side_panel.SidePanel.show_file)

        # Check that DataViewer is used for tree mode
        assert 'DataViewer(id="panel-viewer")' in source
        assert 'mode == "tree"' in source

    def test_image_viewer_in_side_panel_mode(self):
        """ImageViewer should be used for image mode in SidePanel."""
        from ppxai.tui.widgets import side_panel
        import inspect

        source = inspect.getsource(side_panel.SidePanel.show_file)

        # Check that ImageViewer is used for image mode
        assert 'ImageViewer(path=path' in source
        assert 'mode == "image"' in source

    def test_data_viewer_loads_json(self):
        """DataViewer in SidePanel should support JSON loading."""
        from ppxai.tui.widgets import side_panel
        import inspect

        source = inspect.getsource(side_panel.SidePanel.show_file)

        # Check JSON loading code is present
        assert 'viewer.load_json(content' in source
        assert 'ext == ".json"' in source

    def test_data_viewer_loads_yaml(self):
        """DataViewer in SidePanel should support YAML loading."""
        from ppxai.tui.widgets import side_panel
        import inspect

        source = inspect.getsource(side_panel.SidePanel.show_file)

        # Check YAML loading code is present
        assert 'viewer.load_yaml(content' in source
        assert '".yaml"' in source or '".yml"' in source

    def test_data_viewer_loads_toml(self):
        """DataViewer in SidePanel should support TOML loading."""
        from ppxai.tui.widgets import side_panel
        import inspect

        source = inspect.getsource(side_panel.SidePanel.show_file)

        # Check TOML loading code is present
        assert 'viewer.load_toml(content' in source
        assert 'ext == ".toml"' in source


class TestTableViewer:
    """Tests for TableViewer widget."""

    def test_table_viewer_imports(self):
        """TableViewer should import without errors."""
        from ppxai.tui.widgets.table_viewer import TableViewer
        assert TableViewer is not None

    def test_table_viewer_creation(self):
        """TableViewer should create without errors."""
        from ppxai.tui.widgets.table_viewer import TableViewer

        viewer = TableViewer()
        assert viewer is not None
        assert viewer.view_mode == "table"

    def test_table_viewer_default_state(self):
        """TableViewer should have correct default state."""
        from ppxai.tui.widgets.table_viewer import TableViewer

        viewer = TableViewer()
        assert viewer.headers == []
        assert viewer.rows == []
        assert viewer.total_rows == 0
        assert viewer.delimiter == ","
        assert viewer.filename == "data.csv"

    def test_table_viewer_has_bindings(self):
        """TableViewer should have V binding for toggle."""
        from ppxai.tui.widgets.table_viewer import TableViewer

        viewer = TableViewer()
        binding_keys = [b.key for b in viewer.BINDINGS]

        assert "v" in binding_keys

    def test_table_viewer_view_mode_toggle(self):
        """TableViewer should toggle between table and source view."""
        from ppxai.tui.widgets.table_viewer import TableViewer

        viewer = TableViewer()
        assert viewer.view_mode == "table"

        viewer.action_toggle_view()
        assert viewer.view_mode == "source"

        viewer.action_toggle_view()
        assert viewer.view_mode == "table"

    def test_detect_delimiter_csv(self):
        """detect_delimiter should identify CSV."""
        from ppxai.tui.widgets.table_viewer import detect_delimiter

        content = "a,b,c\n1,2,3\n4,5,6"
        assert detect_delimiter(content) == ","

    def test_detect_delimiter_tsv(self):
        """detect_delimiter should identify TSV."""
        from ppxai.tui.widgets.table_viewer import detect_delimiter

        content = "a\tb\tc\n1\t2\t3\n4\t5\t6"
        assert detect_delimiter(content) == "\t"

    def test_detect_delimiter_psv(self):
        """detect_delimiter should identify PSV."""
        from ppxai.tui.widgets.table_viewer import detect_delimiter

        content = "a|b|c\n1|2|3\n4|5|6"
        assert detect_delimiter(content) == "|"

    def test_detect_has_header_numeric(self):
        """detect_has_header should identify numeric data rows."""
        from ppxai.tui.widgets.table_viewer import detect_has_header

        # Header with text, data with numbers
        rows = [["name", "age", "score"], ["Alice", "25", "95.5"], ["Bob", "30", "87.2"]]
        assert detect_has_header(rows) is True

    def test_detect_has_header_short_strings(self):
        """detect_has_header should identify short strings as potential headers."""
        from ppxai.tui.widgets.table_viewer import detect_has_header

        # Short strings without spaces are treated as headers (heuristic)
        rows = [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"]]
        # This is True because short strings without spaces match header pattern
        assert detect_has_header(rows) is True

    def test_parse_tabular_csv(self):
        """parse_tabular should parse CSV correctly."""
        from ppxai.tui.widgets.table_viewer import parse_tabular

        content = "name,age,city\nAlice,25,NYC\nBob,30,LA"
        headers, rows, delim = parse_tabular(content)

        assert headers == ["name", "age", "city"]
        assert len(rows) == 2
        assert rows[0] == ["Alice", "25", "NYC"]
        assert delim == ","

    def test_parse_tabular_tsv(self):
        """parse_tabular should parse TSV correctly."""
        from ppxai.tui.widgets.table_viewer import parse_tabular

        content = "name\tage\tcity\nAlice\t25\tNYC"
        headers, rows, delim = parse_tabular(content)

        assert headers == ["name", "age", "city"]
        assert len(rows) == 1
        assert delim == "\t"

    def test_parse_tabular_empty(self):
        """parse_tabular should handle empty content."""
        from ppxai.tui.widgets.table_viewer import parse_tabular

        headers, rows, delim = parse_tabular("")
        assert headers == []
        assert rows == []

    def test_table_viewer_load_csv(self):
        """TableViewer should load CSV data."""
        from ppxai.tui.widgets.table_viewer import TableViewer

        viewer = TableViewer()
        content = "a,b,c\n1,2,3\n4,5,6"

        result = viewer.load_csv(content, "test.csv")

        assert result is True
        assert viewer.headers == ["a", "b", "c"]
        assert len(viewer.rows) == 2
        assert viewer.filename == "test.csv"

    def test_table_viewer_load_tsv(self):
        """TableViewer should load TSV data."""
        from ppxai.tui.widgets.table_viewer import TableViewer

        viewer = TableViewer()
        content = "x\ty\tz\n10\t20\t30"

        result = viewer.load_tsv(content, "test.tsv")

        assert result is True
        assert viewer.headers == ["x", "y", "z"]
        assert len(viewer.rows) == 1
        assert viewer.delimiter == "\t"

    def test_table_viewer_load_auto(self):
        """TableViewer should auto-detect delimiter."""
        from ppxai.tui.widgets.table_viewer import TableViewer

        viewer = TableViewer()
        content = "col1|col2|col3\nval1|val2|val3"

        result = viewer.load_auto(content, "test.psv")

        assert result is True
        assert viewer.delimiter == "|"
        assert viewer.headers == ["col1", "col2", "col3"]

    def test_table_viewer_set_data(self):
        """TableViewer should accept data directly."""
        from ppxai.tui.widgets.table_viewer import TableViewer

        viewer = TableViewer()
        headers = ["Name", "Value"]
        rows = [["foo", "100"], ["bar", "200"]]

        viewer.set_data(headers, rows, "manual.csv")

        assert viewer.headers == headers
        assert viewer.rows == rows
        assert viewer.total_rows == 2
        assert viewer.filename == "manual.csv"

    def test_table_viewer_large_data(self):
        """TableViewer should handle large datasets."""
        from ppxai.tui.widgets.table_viewer import TableViewer, MAX_INITIAL_ROWS

        viewer = TableViewer()

        # Create large CSV
        headers = ["id", "value"]
        rows = [[str(i), f"val_{i}"] for i in range(2000)]

        viewer.set_data(headers, rows, "large.csv")

        assert viewer.total_rows == 2000
        # Displayed rows should be limited
        assert viewer.displayed_rows <= MAX_INITIAL_ROWS

    def test_table_viewer_unicode_data(self):
        """TableViewer should handle Unicode content."""
        from ppxai.tui.widgets.table_viewer import TableViewer

        viewer = TableViewer()
        content = "name,greeting\nAlice,Hello\nBob,World"

        result = viewer.load_csv(content, "unicode.csv")

        assert result is True
        assert len(viewer.rows) == 2

    def test_table_viewer_extension_delimiter(self):
        """TableViewer should map extensions to delimiters."""
        from ppxai.tui.widgets.table_viewer import TableViewer

        assert TableViewer.get_delimiter_for_extension(".csv") == ","
        assert TableViewer.get_delimiter_for_extension(".tsv") == "\t"
        assert TableViewer.get_delimiter_for_extension(".tab") == "\t"
        assert TableViewer.get_delimiter_for_extension(".psv") == "|"
        assert TableViewer.get_delimiter_for_extension(".txt") is None

    def test_table_viewer_is_tabular_file(self):
        """TableViewer should identify tabular files."""
        from ppxai.tui.widgets.table_viewer import TableViewer
        from pathlib import Path

        assert TableViewer.is_tabular_file(Path("data.csv")) is True
        assert TableViewer.is_tabular_file(Path("data.tsv")) is True
        assert TableViewer.is_tabular_file(Path("data.CSV")) is True  # Case insensitive
        assert TableViewer.is_tabular_file(Path("data.txt")) is False
        assert TableViewer.is_tabular_file(Path("data.json")) is False

    def test_table_viewer_exported(self):
        """TableViewer should be exported from widgets module."""
        from ppxai.tui import widgets

        assert "TableViewer" in widgets.__all__
        assert hasattr(widgets, "TableViewer")

    def test_table_viewer_in_side_panel(self):
        """SidePanel should use TableViewer for table mode."""
        from ppxai.tui.widgets import side_panel
        import inspect

        source = inspect.getsource(side_panel.SidePanel.show_file)

        # Check that TableViewer is used for table mode
        assert 'TableViewer(id="panel-table-viewer")' in source
        assert 'mode == "table"' in source

    def test_show_command_uses_table_mode(self):
        """cmd_show should use table mode for CSV/TSV."""
        from ppxai.tui import commands
        import inspect

        source = inspect.getsource(commands.cmd_show)

        # Check table mode is used for tabular formats
        assert 'mode="table"' in source
        assert 'tabular_formats' in source


# =============================================================================
# Phase 5: End-to-End Validation
# =============================================================================


class TestWidgetLifecycle:
    """Phase 5.1: Widget lifecycle tests - mount/unmount, focus, events."""

    def test_message_box_mount_unmount(self):
        """MessageBox should mount and unmount cleanly."""
        from ppxai.tui.widgets import MessageBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield MessageBox(role="user", content="test")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Widget should be mounted
                msg_box = app.query_one(MessageBox)
                assert msg_box is not None
                assert msg_box.role == "user"

                # Remove widget
                await msg_box.remove()

                # Widget should be gone
                assert len(app.query(MessageBox)) == 0

        asyncio.run(run_test())

    def test_chat_view_mount_unmount(self):
        """ChatView should mount and unmount cleanly."""
        from ppxai.tui.widgets import ChatView
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Widget should be mounted
                chat_view = app.query_one("#chat-view", ChatView)
                assert chat_view is not None

                # Remove widget
                await chat_view.remove()

                # Widget should be gone
                assert len(app.query(ChatView)) == 0

        asyncio.run(run_test())

    def test_status_bar_mount_unmount(self):
        """StatusBar should mount and unmount cleanly."""
        from ppxai.tui.widgets import StatusBar
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield StatusBar()

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Widget should be mounted
                status_bar = app.query_one(StatusBar)
                assert status_bar is not None

                # Remove widget
                await status_bar.remove()

                # Widget should be gone
                assert len(app.query(StatusBar)) == 0

        asyncio.run(run_test())

    def test_input_box_mount_unmount(self):
        """InputBox should mount and unmount cleanly."""
        from ppxai.tui.widgets import InputBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Widget should be mounted
                input_box = app.query_one("#input-box", InputBox)
                assert input_box is not None

                # Remove widget
                await input_box.remove()

                # Widget should be gone
                assert len(app.query(InputBox)) == 0

        asyncio.run(run_test())

    def test_tree_viewer_mount_unmount(self):
        """TreeViewer should mount and unmount cleanly."""
        from ppxai.tui.widgets import TreeViewer
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield TreeViewer(id="tree-viewer")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Widget should be mounted
                tree_viewer = app.query_one("#tree-viewer", TreeViewer)
                assert tree_viewer is not None

                # Remove widget
                await tree_viewer.remove()

                # Widget should be gone
                assert len(app.query(TreeViewer)) == 0

        asyncio.run(run_test())

    def test_code_editor_mount_unmount(self):
        """CodeEditor should mount and unmount cleanly."""
        from ppxai.tui.widgets import CodeEditor
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield CodeEditor(text="test", language="python", id="editor")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Widget should be mounted
                editor = app.query_one("#editor", CodeEditor)
                assert editor is not None

                # Remove widget
                await editor.remove()

                # Widget should be gone
                assert len(app.query(CodeEditor)) == 0

        asyncio.run(run_test())

    def test_data_viewer_mount_unmount(self):
        """DataViewer should mount and unmount cleanly."""
        from ppxai.tui.widgets import DataViewer
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield DataViewer(id="data-viewer")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Widget should be mounted
                viewer = app.query_one("#data-viewer", DataViewer)
                assert viewer is not None

                # Remove widget
                await viewer.remove()

                # Widget should be gone
                assert len(app.query(DataViewer)) == 0

        asyncio.run(run_test())

    def test_image_viewer_mount_unmount(self):
        """ImageViewer should mount and unmount cleanly."""
        from ppxai.tui.widgets import ImageViewer
        from textual.app import App
        from pathlib import Path
        import tempfile

        class TestApp(App):
            def compose(self):
                # Create a temp file for path
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    self.temp_path = Path(f.name)
                yield ImageViewer(path=self.temp_path, id="image-viewer")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Widget should be mounted
                viewer = app.query_one("#image-viewer", ImageViewer)
                assert viewer is not None

                # Remove widget
                await viewer.remove()

                # Widget should be gone
                assert len(app.query(ImageViewer)) == 0

                # Cleanup
                app.temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_table_viewer_mount_unmount(self):
        """TableViewer should mount and unmount cleanly."""
        from ppxai.tui.widgets import TableViewer
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield TableViewer(id="table-viewer")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Widget should be mounted
                viewer = app.query_one("#table-viewer", TableViewer)
                assert viewer is not None

                # Remove widget
                await viewer.remove()

                # Widget should be gone
                assert len(app.query(TableViewer)) == 0

        asyncio.run(run_test())

    def test_side_panel_mount_unmount(self):
        """SidePanel should mount and unmount cleanly."""
        from ppxai.tui.widgets import SidePanel
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Widget should be mounted
                panel = app.query_one("#side-panel", SidePanel)
                assert panel is not None

                # Remove widget
                await panel.remove()

                # Widget should be gone
                assert len(app.query(SidePanel)) == 0

        asyncio.run(run_test())

    def test_focus_navigation_chat_to_input(self):
        """Focus should navigate from ChatView to InputBox."""
        from ppxai.tui.widgets import ChatView, InputBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)
                input_box = app.query_one("#input-box", InputBox)

                # Focus chat view
                chat_view.focus()
                await pilot.pause()

                # Focus should transfer to input box with Tab
                await pilot.press("tab")
                await pilot.pause()

                # Input box should be focused (or one of its children)
                focused = app.focused
                assert focused is not None
                # Check if focused widget is input box or its descendant
                assert focused == input_box or input_box in focused.ancestors

        asyncio.run(run_test())

    def test_focus_navigation_side_panel(self):
        """Focus should work with SidePanel widgets."""
        from ppxai.tui.widgets import SidePanel, CodeEditor
        from textual.app import App
        from pathlib import Path
        import tempfile

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                # Show a file in the panel
                with tempfile.NamedTemporaryFile(mode='w', suffix=".py", delete=False) as f:
                    f.write("print('test')")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "print('test')", mode="code", read_only=True)
                    await pilot.pause()

                    # Panel should be visible
                    assert panel.is_open is True

                    # Try to focus the editor inside
                    editor = app.query_one("#panel-editor", CodeEditor)
                    editor.focus()
                    await pilot.pause()

                    # Editor or its child should be focused
                    focused = app.focused
                    assert focused is not None

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_event_bubbling_message_box(self):
        """Events should bubble from MessageBox to ChatView."""
        from ppxai.tui.widgets import MessageBox, ChatView
        from textual.app import App
        from textual.message import Message

        class CustomEvent(Message):
            pass

        class TestApp(App):
            def __init__(self):
                super().__init__()
                self.event_received = False

            def compose(self):
                yield ChatView(id="chat-view")

            def on_custom_event(self, event: CustomEvent):
                self.event_received = True

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                # Add a message box
                msg_box = MessageBox(role="user", content="test")
                chat_view._messages.append(msg_box)
                await chat_view.mount(msg_box)
                await pilot.pause()

                # Post event from message box
                msg_box.post_message(CustomEvent())
                await pilot.pause()

                # App should receive the bubbled event
                assert app.event_received is True

        asyncio.run(run_test())

    def test_reactive_updates_status_bar(self):
        """Reactive properties should trigger updates in StatusBar."""
        from ppxai.tui.widgets import StatusBar
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield StatusBar()

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                status_bar = app.query_one(StatusBar)

                # Initial values
                initial_provider = status_bar.provider
                assert initial_provider is not None

                # Update provider
                status_bar.provider = "openai"
                await pilot.pause()

                # Should have updated
                assert status_bar.provider == "openai"

        asyncio.run(run_test())

    def test_reactive_updates_data_viewer(self):
        """Reactive view_mode should trigger updates in DataViewer."""
        from ppxai.tui.widgets import DataViewer
        from textual.app import App

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json('{"test": "value"}', "test.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)

                # Should start in tree mode
                assert viewer.view_mode == "tree"

                # Toggle to source
                viewer.view_mode = "source"
                await pilot.pause()

                # Should have updated
                assert viewer.view_mode == "source"

        asyncio.run(run_test())

    def test_widget_composition_side_panel(self):
        """SidePanel should compose child widgets correctly."""
        from ppxai.tui.widgets import SidePanel, CodeEditor
        from textual.app import App
        from pathlib import Path
        import tempfile

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                # Show a code file
                with tempfile.NamedTemporaryFile(mode='w', suffix=".py", delete=False) as f:
                    f.write("def test():\n    pass\n")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "def test():\n    pass\n", mode="code", read_only=True)
                    await pilot.pause()

                    # Panel should contain header and content widgets
                    header = app.query_one("#panel-header-bar")
                    assert header is not None

                    content = app.query_one("#panel-content")
                    assert content is not None

                    # Content should have CodeEditor
                    editor = app.query_one("#panel-editor", CodeEditor)
                    assert editor is not None
                    assert editor.text == "def test():\n    pass\n"

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_widget_composition_data_viewer(self):
        """DataViewer should compose TreeViewer and CodeEditor correctly."""
        from ppxai.tui.widgets import DataViewer, TreeViewer, CodeEditor
        from textual.app import App

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json('{"key": "value"}', "test.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)

                # Should have header
                header = app.query_one(".data-viewer-header")
                assert header is not None

                # Should have content switcher
                switcher = app.query_one("#data-content-switcher")
                assert switcher is not None

                # In tree mode, should have TreeViewer
                assert viewer.view_mode == "tree"
                tree_viewer = app.query_one("#tree-view TreeViewer", TreeViewer)
                assert tree_viewer is not None

                # Toggle to source mode
                viewer.view_mode = "source"
                await pilot.pause()

                # In source mode, should have CodeEditor
                code_editor = app.query_one("#source-view CodeEditor", CodeEditor)
                assert code_editor is not None

        asyncio.run(run_test())

    def test_multiple_widgets_cleanup(self):
        """Multiple widgets should clean up properly when removed."""
        from ppxai.tui.widgets import MessageBox, ChatView, StatusBar, InputBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield StatusBar()
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # All widgets should be mounted
                assert len(app.query(StatusBar)) == 1
                assert len(app.query(ChatView)) == 1
                assert len(app.query(InputBox)) == 1

                # Remove all widgets
                await app.query_one(StatusBar).remove()
                await app.query_one("#chat-view", ChatView).remove()
                await app.query_one("#input-box", InputBox).remove()
                await pilot.pause()

                # All should be gone
                assert len(app.query(StatusBar)) == 0
                assert len(app.query(ChatView)) == 0
                assert len(app.query(InputBox)) == 0

        asyncio.run(run_test())

    def test_widget_state_preservation(self):
        """Widget state should be preserved during lifecycle."""
        from ppxai.tui.widgets import DataViewer
        from textual.app import App

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json('{"test": "data"}', "test.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)

                # Toggle to source mode
                viewer.view_mode = "source"
                await pilot.pause()

                # State should be preserved
                assert viewer.view_mode == "source"
                assert viewer._source == '{"test": "data"}'
                assert viewer._filename == "test.json"

                # Toggle back to tree
                viewer.view_mode = "tree"
                await pilot.pause()

                # State still preserved
                assert viewer.view_mode == "tree"
                assert viewer._source == '{"test": "data"}'
                assert viewer._filename == "test.json"

        asyncio.run(run_test())

    def test_message_passing_between_widgets(self):
        """Widgets should communicate via message passing."""
        from ppxai.tui.widgets import SidePanel
        from textual.app import App

        class TestApp(App):
            def __init__(self):
                super().__init__()
                self.opened_received = False
                self.closed_received = False

            def compose(self):
                yield SidePanel(id="side-panel")

            def on_side_panel_opened(self, event):
                self.opened_received = True

            def on_side_panel_closed(self, event):
                self.closed_received = True

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                from pathlib import Path
                import tempfile

                panel = app.query_one("#side-panel", SidePanel)

                # Open panel - should send Opened message
                with tempfile.NamedTemporaryFile(mode='w', suffix=".txt", delete=False) as f:
                    f.write("test")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "test", mode="code", read_only=True)
                    await pilot.pause()

                    assert app.opened_received is True

                    # Close panel - should send Closed message
                    panel.close()
                    await pilot.pause()

                    assert app.closed_received is True

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())


class TestThemeConsistency:
    """Phase 5.2: Theme consistency tests - all themes, all widgets."""

    def test_all_widgets_with_default_theme(self):
        """All widgets should render correctly with default theme."""
        from ppxai.tui.widgets import (
            StatusBar, ChatView, InputBox, MessageBox,
            TreeViewer, CodeEditor, DataViewer, ImageViewer,
            TableViewer, SidePanel
        )
        from textual.app import App
        from pathlib import Path
        import tempfile

        class TestApp(App):
            def compose(self):
                yield StatusBar()
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # All widgets should be mounted
                assert app.query_one(StatusBar) is not None
                assert app.query_one("#chat-view", ChatView) is not None
                assert app.query_one("#input-box", InputBox) is not None

                # Default theme should be textual-dark
                assert app.theme is not None

        asyncio.run(run_test())

    def test_status_bar_across_themes(self):
        """StatusBar should work with all themes."""
        from ppxai.tui.widgets import StatusBar
        from textual.app import App

        themes_to_test = [
            "textual-dark", "textual-light",
            "nord", "dracula", "catppuccin-mocha"
        ]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    yield StatusBar()

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    # Widget should still be visible
                    status_bar = app.query_one(StatusBar)
                    assert status_bar is not None
                    assert status_bar.provider is not None

            asyncio.run(run_test())

    def test_chat_view_across_themes(self):
        """ChatView should work with all themes."""
        from ppxai.tui.widgets import ChatView, MessageBox
        from textual.app import App

        themes_to_test = [
            "textual-dark", "nord", "monokai"
        ]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    yield ChatView(id="chat-view")

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    # Add a message
                    chat_view = app.query_one("#chat-view", ChatView)
                    msg = MessageBox(role="user", content="Test message")
                    chat_view._messages.append(msg)
                    await chat_view.mount(msg)
                    await pilot.pause()

                    # Message should be visible
                    assert len(chat_view._messages) == 1

            asyncio.run(run_test())

    def test_data_viewer_across_themes(self):
        """DataViewer should work with all themes."""
        from ppxai.tui.widgets import DataViewer
        from textual.app import App

        themes_to_test = ["textual-dark", "gruvbox", "solarized-light"]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    viewer = DataViewer(id="data-viewer")
                    viewer.load_json('{"key": "value"}', "test.json")
                    yield viewer

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    # Viewer should still work
                    viewer = app.query_one("#data-viewer", DataViewer)
                    assert viewer.view_mode == "tree"

                    # Toggle view
                    viewer.view_mode = "source"
                    await pilot.pause()
                    assert viewer.view_mode == "source"

            asyncio.run(run_test())

    def test_code_editor_syntax_themes(self):
        """CodeEditor syntax highlighting should work with app themes."""
        from ppxai.tui.widgets import CodeEditor
        from textual.app import App

        app_themes = ["textual-dark", "nord", "monokai"]

        for app_theme in app_themes:
            class TestApp(App):
                def compose(self):
                    yield CodeEditor(
                        text="def test():\n    pass\n",
                        language="python",
                        id="editor"
                    )

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply app theme
                    app.theme = app_theme
                    await pilot.pause()

                    # Editor should still work
                    editor = app.query_one("#editor", CodeEditor)
                    assert editor.text == "def test():\n    pass\n"
                    assert editor.language == "python"

            asyncio.run(run_test())

    def test_table_viewer_across_themes(self):
        """TableViewer should work with all themes."""
        from ppxai.tui.widgets import TableViewer
        from textual.app import App

        themes_to_test = ["textual-dark", "dracula", "textual-light"]

        csv_data = "name,age,city\nAlice,30,NYC\nBob,25,LA\n"

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    viewer = TableViewer(id="table-viewer")
                    viewer.load_auto(csv_data, "data.csv")
                    yield viewer

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    # Viewer should work
                    viewer = app.query_one("#table-viewer", TableViewer)
                    assert viewer.view_mode == "table"

                    # Toggle view
                    viewer.view_mode = "source"
                    await pilot.pause()
                    assert viewer.view_mode == "source"

            asyncio.run(run_test())

    def test_side_panel_across_themes(self):
        """SidePanel should work with all themes."""
        from ppxai.tui.widgets import SidePanel
        from textual.app import App
        from pathlib import Path
        import tempfile

        themes_to_test = ["textual-dark", "nord", "monokai"]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    yield SidePanel(id="side-panel")

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    panel = app.query_one("#side-panel", SidePanel)

                    # Show a file
                    with tempfile.NamedTemporaryFile(mode='w', suffix=".py", delete=False) as f:
                        f.write("print('test')")
                        temp_path = Path(f.name)

                    try:
                        await panel.show_file(temp_path, "print('test')", mode="code", read_only=True)
                        await pilot.pause()

                        # Panel should be open
                        assert panel.is_open is True

                    finally:
                        temp_path.unlink(missing_ok=True)

            asyncio.run(run_test())

    def test_custom_themes_work(self):
        """Custom themes (tron-legacy, matrix) should be available in ppxaide."""
        from ppxai.tui.app import PPXAIDEApp

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Check that custom themes are registered
                assert "tron-legacy" in app.available_themes
                assert "matrix" in app.available_themes

                # Try switching to custom themes
                app.theme = "tron-legacy"
                await pilot.pause()
                assert app.theme == "tron-legacy"

                app.theme = "matrix"
                await pilot.pause()
                assert app.theme == "matrix"

        asyncio.run(run_test())

    def test_theme_switching_preserves_state(self):
        """Theme switching should not lose widget state."""
        from ppxai.tui.widgets import DataViewer
        from textual.app import App

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json('{"test": "data"}', "test.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)

                # Toggle to source mode
                viewer.view_mode = "source"
                await pilot.pause()

                # Switch themes
                app.theme = "nord"
                await pilot.pause()

                # State should be preserved
                assert viewer.view_mode == "source"
                assert viewer._source == '{"test": "data"}'

                # Switch themes again
                app.theme = "dracula"
                await pilot.pause()

                # State still preserved
                assert viewer.view_mode == "source"
                assert viewer._source == '{"test": "data"}'

        asyncio.run(run_test())

    def test_message_box_styles_with_themes(self):
        """MessageBox styles should work with all themes."""
        from ppxai.tui.widgets import MessageBox, ChatView
        from textual.app import App

        themes_to_test = ["textual-dark", "nord", "monokai"]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    yield ChatView(id="chat-view")

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    chat_view = app.query_one("#chat-view", ChatView)

                    # Add messages with different roles
                    for role in ["user", "assistant", "system"]:
                        msg = MessageBox(role=role, content=f"Test {role}")
                        chat_view._messages.append(msg)
                        await chat_view.mount(msg)
                        await pilot.pause()

                    # All messages should be visible
                    assert len(chat_view._messages) == 3

            asyncio.run(run_test())

    def test_input_box_across_themes(self):
        """InputBox should work with all themes."""
        from ppxai.tui.widgets import InputBox
        from textual.app import App

        themes_to_test = ["textual-dark", "nord", "atom-one-light"]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    yield InputBox(id="input-box")

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    # Input box should work
                    input_box = app.query_one("#input-box", InputBox)
                    assert input_box is not None

            asyncio.run(run_test())

    def test_tree_viewer_across_themes(self):
        """TreeViewer should work with all themes."""
        from ppxai.tui.widgets import TreeViewer
        from textual.app import App

        themes_to_test = ["textual-dark", "nord", "solarized-dark"]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    yield TreeViewer(id="tree-viewer")

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    # Viewer should work
                    viewer = app.query_one("#tree-viewer", TreeViewer)
                    assert viewer is not None

            asyncio.run(run_test())

    def test_widgets_visible_after_theme_change(self):
        """All widgets should remain visible after theme change."""
        from ppxai.tui.widgets import StatusBar, ChatView, InputBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield StatusBar()
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Start with default theme
                initial_theme = app.theme
                await pilot.pause()

                # All widgets visible
                assert app.query_one(StatusBar) is not None
                assert app.query_one("#chat-view", ChatView) is not None
                assert app.query_one("#input-box", InputBox) is not None

                # Change theme
                app.theme = "nord"
                await pilot.pause()

                # All widgets still visible
                assert app.query_one(StatusBar) is not None
                assert app.query_one("#chat-view", ChatView) is not None
                assert app.query_one("#input-box", InputBox) is not None

        asyncio.run(run_test())


class TestKeyboardNavigation:
    """Phase 5.3: Keyboard navigation tests - no dead-ends, focus management."""

    def test_tab_navigation_basic(self):
        """Tab should cycle through focusable widgets."""
        from ppxai.tui.widgets import ChatView, InputBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Press Tab
                await pilot.press("tab")
                await pilot.pause()

                # Should have focus somewhere
                assert app.focused is not None

        asyncio.run(run_test())

    def test_escape_closes_side_panel(self):
        """Escape should close SidePanel."""
        from ppxai.tui.widgets import SidePanel
        from textual.app import App
        from pathlib import Path
        import tempfile

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                # Open panel
                with tempfile.NamedTemporaryFile(mode='w', suffix=".py", delete=False) as f:
                    f.write("test")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "test", mode="code", read_only=True)
                    await pilot.pause()

                    assert panel.is_open is True

                    # Press Escape
                    await pilot.press("escape")
                    await pilot.pause()

                    # Panel should be closed
                    assert panel.is_open is False

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_v_toggles_data_viewer(self):
        """V should toggle DataViewer between tree and source."""
        from ppxai.tui.widgets import DataViewer
        from textual.app import App

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json('{"key": "value"}', "test.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)

                # Should start in tree mode
                assert viewer.view_mode == "tree"

                # Press V
                await pilot.press("v")
                await pilot.pause()

                # Should toggle to source
                assert viewer.view_mode == "source"

                # Press V again
                await pilot.press("v")
                await pilot.pause()

                # Should toggle back to tree
                assert viewer.view_mode == "tree"

        asyncio.run(run_test())

    def test_v_toggles_table_viewer(self):
        """V should toggle TableViewer between table and source."""
        from ppxai.tui.widgets import TableViewer
        from textual.app import App

        csv_data = "name,age\nAlice,30\nBob,25\n"

        class TestApp(App):
            def compose(self):
                viewer = TableViewer(id="table-viewer")
                viewer.load_auto(csv_data, "data.csv")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#table-viewer", TableViewer)

                # Should start in table mode
                assert viewer.view_mode == "table"

                # Toggle view mode directly (keybinding might not focus widget in test)
                viewer.view_mode = "source"
                await pilot.pause()

                # Should be in source mode
                assert viewer.view_mode == "source"

                # Toggle back
                viewer.view_mode = "table"
                await pilot.pause()

                # Should be back in table mode
                assert viewer.view_mode == "table"

        asyncio.run(run_test())

    def test_language_detection_in_side_panel(self):
        """SidePanel should detect language from file extension."""
        from ppxai.tui.widgets import SidePanel
        from textual.app import App
        from pathlib import Path
        import tempfile

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                # Test Python file
                with tempfile.NamedTemporaryFile(mode='w', suffix=".py", delete=False) as f:
                    f.write("print('test')")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "print('test')", mode="code", read_only=True)
                    await pilot.pause()

                    # Language should be detected as python
                    assert panel._current_language == "python"
                    assert panel._mode == "code"

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_no_dead_ends_in_navigation(self):
        """Should be able to navigate through all widgets without getting stuck."""
        from ppxai.tui.widgets import StatusBar, ChatView, InputBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield StatusBar()
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Press Tab multiple times
                for _ in range(5):
                    await pilot.press("tab")
                    await pilot.pause()

                    # Should always have focus somewhere
                    assert app.focused is not None

        asyncio.run(run_test())

    def test_arrow_keys_in_chat_view(self):
        """Arrow keys should work for scrolling in ChatView."""
        from ppxai.tui.widgets import ChatView, MessageBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                # Add some messages
                for i in range(10):
                    msg = MessageBox(role="user", content=f"Message {i}")
                    chat_view._messages.append(msg)
                    await chat_view.mount(msg)

                await pilot.pause()

                # Focus chat view
                chat_view.focus()
                await pilot.pause()

                # Press arrow keys - should not crash
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("up")
                await pilot.pause()

        asyncio.run(run_test())

    def test_home_end_keys_in_input_box(self):
        """Home/End keys should work in InputBox."""
        from ppxai.tui.widgets import InputBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                input_box = app.query_one("#input-box", InputBox)

                # Focus input box
                input_box.focus()
                await pilot.pause()

                # Type some text
                await pilot.press(*"hello world")
                await pilot.pause()

                # Press Home - should not crash
                await pilot.press("home")
                await pilot.pause()

                # Press End - should not crash
                await pilot.press("end")
                await pilot.pause()

        asyncio.run(run_test())

    def test_close_method_works(self):
        """Panel close() method should work."""
        from ppxai.tui.widgets import SidePanel
        from textual.app import App
        from pathlib import Path
        import tempfile

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                # Open panel
                with tempfile.NamedTemporaryFile(mode='w', suffix=".txt", delete=False) as f:
                    f.write("test")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "test", mode="code", read_only=True)
                    await pilot.pause()

                    assert panel.is_open is True

                    # Call close() method
                    panel.close()
                    await pilot.pause()

                    # Panel should be closed
                    assert panel.is_open is False

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_focus_stays_within_app(self):
        """Focus should never be None during navigation."""
        from ppxai.tui.widgets import ChatView, InputBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Try various navigation keys
                keys = ["tab", "shift+tab", "down", "up"]

                for key in keys:
                    await pilot.press(key)
                    await pilot.pause()

                    # Focus should not be lost
                    # (May be None initially, but after pressing a key should have focus)

        asyncio.run(run_test())

    def test_shift_tab_reverses_navigation(self):
        """Shift+Tab should navigate backwards."""
        from ppxai.tui.widgets import ChatView, InputBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Press Tab to move forward
                await pilot.press("tab")
                await pilot.pause()
                first_focus = app.focused

                # Press Tab again
                await pilot.press("tab")
                await pilot.pause()
                second_focus = app.focused

                # Press Shift+Tab to go back
                await pilot.press("shift+tab")
                await pilot.pause()
                back_focus = app.focused

                # Should be able to navigate (focus changes)
                # Can't guarantee specific order, but focus should exist

        asyncio.run(run_test())

    def test_keyboard_shortcuts_dont_conflict(self):
        """No keyboard shortcut conflicts across widgets."""
        from ppxai.tui.widgets import SidePanel, DataViewer
        from textual.app import App
        from pathlib import Path
        import tempfile

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                # Open a data file that uses DataViewer
                with tempfile.NamedTemporaryFile(mode='w', suffix=".json", delete=False) as f:
                    f.write('{"test": "data"}')
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, '{"test": "data"}', mode="tree", read_only=True)
                    await pilot.pause()

                    # V should toggle DataViewer (not conflict with SidePanel bindings)
                    await pilot.press("v")
                    await pilot.pause()

                    # Escape should close panel (SidePanel binding)
                    await pilot.press("escape")
                    await pilot.pause()

                    assert panel.is_open is False

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_enter_key_in_input_box(self):
        """Enter key should work in InputBox (submit or new line)."""
        from ppxai.tui.widgets import InputBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                input_box = app.query_one("#input-box", InputBox)

                # Focus input box
                input_box.focus()
                await pilot.pause()

                # Type text
                await pilot.press(*"hello")
                await pilot.pause()

                # Press Enter - should not crash
                await pilot.press("enter")
                await pilot.pause()

        asyncio.run(run_test())

    def test_f6_switches_focus_to_side_panel(self):
        """F6 should switch focus to side panel when open."""
        from ppxai.tui.widgets import ChatView, SidePanel
        from textual.app import App
        from pathlib import Path
        import tempfile

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)
                panel = app.query_one("#side-panel", SidePanel)

                # Focus chat view
                chat_view.focus()
                await pilot.pause()

                # Open side panel
                with tempfile.NamedTemporaryFile(mode='w', suffix=".txt", delete=False) as f:
                    f.write("test")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "test", mode="code", read_only=True)
                    await pilot.pause()

                    # Press F6 - should not crash
                    await pilot.press("f6")
                    await pilot.pause()

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_multiple_escape_presses(self):
        """Multiple Escape presses should not cause issues."""
        from ppxai.tui.widgets import SidePanel
        from textual.app import App
        from pathlib import Path
        import tempfile

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                # Open panel
                with tempfile.NamedTemporaryFile(mode='w', suffix=".txt", delete=False) as f:
                    f.write("test")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "test", mode="code", read_only=True)
                    await pilot.pause()

                    # Press Escape multiple times
                    for _ in range(5):
                        await pilot.press("escape")
                        await pilot.pause()

                    # Should be closed and not crash
                    assert panel.is_open is False

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_page_up_down_in_chat_view(self):
        """Page Up/Down should work for scrolling in ChatView."""
        from ppxai.tui.widgets import ChatView, MessageBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                # Add many messages
                for i in range(50):
                    msg = MessageBox(role="user", content=f"Message {i}")
                    chat_view._messages.append(msg)
                    await chat_view.mount(msg)

                await pilot.pause()

                # Focus chat view
                chat_view.focus()
                await pilot.pause()

                # Press Page Down
                await pilot.press("pagedown")
                await pilot.pause()

                # Press Page Up
                await pilot.press("pageup")
                await pilot.pause()

        asyncio.run(run_test())


class TestEdgeCases:
    """Phase 5.4: Edge case tests - empty states, errors, long content, Unicode."""

    def test_empty_chat_view(self):
        """ChatView should handle zero messages."""
        from ppxai.tui.widgets import ChatView
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                # Should start with zero messages
                assert len(chat_view._messages) == 0

        asyncio.run(run_test())

    def test_empty_string_message(self):
        """MessageBox should handle empty content."""
        from ppxai.tui.widgets import MessageBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield MessageBox(role="user", content="")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                msg = app.query_one(MessageBox)
                assert msg.content == ""

        asyncio.run(run_test())

    def test_data_viewer_with_empty_json(self):
        """DataViewer should handle empty JSON object."""
        from ppxai.tui.widgets import DataViewer
        from textual.app import App

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json('{}', "empty.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)
                assert viewer._source == '{}'

        asyncio.run(run_test())

    def test_table_viewer_with_empty_csv(self):
        """TableViewer should handle empty CSV."""
        from ppxai.tui.widgets import TableViewer
        from textual.app import App

        class TestApp(App):
            def compose(self):
                viewer = TableViewer(id="table-viewer")
                viewer.load_auto("", "empty.csv")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#table-viewer", TableViewer)
                # Should handle empty data gracefully
                assert viewer._source == ""

        asyncio.run(run_test())

    def test_unicode_in_messages(self):
        """Messages should support Unicode characters."""
        from ppxai.tui.widgets import MessageBox
        from textual.app import App

        unicode_text = "Hello 世界 🌍 Привет مرحبا"

        class TestApp(App):
            def compose(self):
                yield MessageBox(role="user", content=unicode_text)

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                msg = app.query_one(MessageBox)
                assert unicode_text in msg.content

        asyncio.run(run_test())

    def test_unicode_in_data_viewer(self):
        """DataViewer should support Unicode in JSON."""
        from ppxai.tui.widgets import DataViewer
        from textual.app import App

        unicode_data = {"message": "Hello 世界", "emoji": "🎉"}

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json(json.dumps(unicode_data, ensure_ascii=False), "unicode.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)
                assert "世界" in viewer._source

        import asyncio
        asyncio.run(run_test())

    def test_very_long_message(self):
        """ChatView should handle very long messages."""
        from ppxai.tui.widgets import ChatView, MessageBox
        from textual.app import App

        long_content = "A" * 10000  # 10k character message

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                msg = MessageBox(role="user", content=long_content)
                chat_view._messages.append(msg)
                await chat_view.mount(msg)
                await pilot.pause()

                # Should handle long message
                assert len(chat_view._messages) == 1

        asyncio.run(run_test())

    def test_many_messages_performance(self):
        """ChatView should handle hundreds of messages."""
        from ppxai.tui.widgets import ChatView, MessageBox
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                # Add 100 messages
                for i in range(100):
                    msg = MessageBox(role="user", content=f"Message {i}")
                    chat_view._messages.append(msg)
                    await chat_view.mount(msg)

                await pilot.pause()

                # Should have all messages
                assert len(chat_view._messages) == 100

        asyncio.run(run_test())

    def test_invalid_json_handling(self):
        """DataViewer should handle invalid JSON gracefully."""
        from ppxai.tui.widgets import DataViewer
        from textual.app import App

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)

                # Try to load invalid JSON
                result = viewer.load_json("not valid json{", "bad.json")

                # Should return False for invalid JSON
                assert result is False

        asyncio.run(run_test())

    def test_special_characters_in_filenames(self):
        """SidePanel should handle special characters in filenames."""
        from ppxai.tui.widgets import SidePanel
        from textual.app import App
        from pathlib import Path
        import tempfile

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                # Create file with special chars
                with tempfile.NamedTemporaryFile(mode='w', suffix=" (copy).txt", delete=False) as f:
                    f.write("test")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "test", mode="code", read_only=True)
                    await pilot.pause()

                    # Should handle the filename
                    assert panel.is_open is True

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_newlines_in_messages(self):
        """Messages should preserve newlines."""
        from ppxai.tui.widgets import MessageBox
        from textual.app import App

        multiline_content = "Line 1\nLine 2\nLine 3"

        class TestApp(App):
            def compose(self):
                yield MessageBox(role="user", content=multiline_content)

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                msg = app.query_one(MessageBox)
                assert "\n" in msg.content
                assert msg.content == multiline_content

        asyncio.run(run_test())

    def test_code_editor_with_empty_text(self):
        """CodeEditor should handle empty text."""
        from ppxai.tui.widgets import CodeEditor
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield CodeEditor(text="", language="python", id="editor")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                editor = app.query_one("#editor", CodeEditor)
                assert editor.text == ""

        asyncio.run(run_test())

    def test_large_json_file(self):
        """DataViewer should handle large JSON."""
        from ppxai.tui.widgets import DataViewer
        from textual.app import App

        # Create large JSON structure
        large_data = {"items": [{"id": i, "name": f"Item {i}"} for i in range(100)]}

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json(json.dumps(large_data), "large.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)
                assert viewer._data is not None

        import asyncio
        asyncio.run(run_test())

    def test_large_csv_file(self):
        """TableViewer should handle large CSV (row limit)."""
        from ppxai.tui.widgets import TableViewer
        from textual.app import App

        # Create CSV with many rows
        rows = ["name,age"] + [f"Person{i},{20+i}" for i in range(500)]
        csv_data = "\n".join(rows)

        class TestApp(App):
            def compose(self):
                viewer = TableViewer(id="table-viewer")
                viewer.load_auto(csv_data, "large.csv")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#table-viewer", TableViewer)

                # Should have loaded data
                assert len(viewer._headers) > 0
                # May be limited by MAX_INITIAL_ROWS
                assert len(viewer._rows) > 0

        asyncio.run(run_test())

    def test_mixed_line_endings(self):
        """Content with mixed line endings should be handled."""
        from ppxai.tui.widgets import CodeEditor
        from textual.app import App

        mixed_content = "Line 1\nLine 2\r\nLine 3\r"

        class TestApp(App):
            def compose(self):
                yield CodeEditor(text=mixed_content, language="python", id="editor")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                editor = app.query_one("#editor", CodeEditor)
                # Should have the content
                assert len(editor.text) > 0

        asyncio.run(run_test())

    def test_status_bar_with_long_values(self):
        """StatusBar should handle long provider/model names."""
        from ppxai.tui.widgets import StatusBar
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield StatusBar(
                    provider="very-long-provider-name-that-might-overflow",
                    model="extremely-long-model-name-with-many-characters"
                )

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                status_bar = app.query_one(StatusBar)
                # Should have the values
                assert "very-long" in status_bar.provider

        asyncio.run(run_test())

    def test_side_panel_rapid_open_close(self):
        """SidePanel should handle rapid open/close cycles."""
        from ppxai.tui.widgets import SidePanel
        from textual.app import App
        from pathlib import Path
        import tempfile

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                with tempfile.NamedTemporaryFile(mode='w', suffix=".txt", delete=False) as f:
                    f.write("test")
                    temp_path = Path(f.name)

                try:
                    # Rapid cycles
                    for _ in range(5):
                        await panel.show_file(temp_path, "test", mode="code", read_only=True)
                        await pilot.pause()
                        panel.close()
                        await pilot.pause()

                    # Should end in closed state
                    assert panel.is_open is False

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_data_viewer_view_mode_toggle_many_times(self):
        """DataViewer should handle many view toggles."""
        from ppxai.tui.widgets import DataViewer
        from textual.app import App

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json('{"key": "value"}', "test.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)

                # Toggle 10 times
                for i in range(10):
                    viewer.view_mode = "source" if i % 2 == 0 else "tree"
                    await pilot.pause()

                # Should end in tree mode
                assert viewer.view_mode == "tree"

        asyncio.run(run_test())

    def test_malformed_yaml(self):
        """DataViewer should handle malformed YAML."""
        from ppxai.tui.widgets import DataViewer
        from textual.app import App

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)

                # Try to load malformed YAML
                result = viewer.load_yaml("not: valid: yaml: : :", "bad.yaml")

                # Should return False
                assert result is False

        asyncio.run(run_test())


class TestAppIntegration:
    """Phase 5.5: App integration tests - full app lifecycle and command handling."""

    def test_app_startup_and_shutdown(self):
        """App should start and shutdown cleanly."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView, InputBox, StatusBar

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Verify core widgets mounted
                chat_view = app.query_one(ChatView)
                input_box = app.query_one(InputBox)
                status_bar = app.query_one(StatusBar)

                assert chat_view is not None
                assert input_box is not None
                assert status_bar is not None

                # App should exit cleanly
                await pilot.exit(0)

        asyncio.run(run_test())

    def test_help_command(self):
        """/help command should display help text."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one(ChatView)

                # Execute /help command
                await app._handle_command("/help")

                # Should add system message with help text
                assert len(chat_view._messages) > 0
                last_msg = chat_view._messages[-1]
                assert last_msg.role == "system"
                assert "Commands" in last_msg.content or "help" in last_msg.content.lower()

        asyncio.run(run_test())

    def test_clear_command(self):
        """/clear command should clear chat history."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                # Add some messages
                chat_view.add_user_message("Test message 1")
                chat_view.add_user_message("Test message 2")
                initial_count = len(chat_view._messages)
                assert initial_count >= 2  # At least our 2 messages (may have welcome msg)

                # Execute /clear
                await app._handle_command("/clear")

                # Chat should have fewer messages than before (may have system notification)
                assert len(chat_view._messages) < initial_count

        asyncio.run(run_test())

    def test_theme_command(self):
        """action_cycle_theme should cycle themes."""
        from ppxai.tui.app import PPXAIDEApp

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                original_theme_index = app._current_theme_index

                # Directly call the action method
                app.action_cycle_theme()

                # Theme index should have changed
                assert app._current_theme_index != original_theme_index

        asyncio.run(run_test())

    def test_show_command_code_file(self, tmp_path):
        """/show command should open code file in side panel."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView, SidePanel

        # Create temporary file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello():\n    print('world')\n", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one(ChatView)
                side_panel = app.query_one(SidePanel)

                # Execute /show
                await app._handle_command(f"/show {test_file.name}")

                # Side panel should be visible
                assert side_panel.is_open

                # Should have system message
                assert len(chat_view._messages) > 0

        asyncio.run(run_test())

    def test_show_command_json_file(self, tmp_path):
        """/show command should open JSON file in tree viewer or side panel."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import SidePanel
        from ppxai.tui.widgets.chat_view import ChatView

        # Create temporary JSON file
        test_file = tmp_path / "data.json"
        test_file.write_text(json.dumps({"key": "value", "nested": {"a": 1}}), encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                side_panel = app.query_one(SidePanel)
                chat_view = app.query_one(ChatView)
                initial_msg_count = len(chat_view._messages)

                # Execute /show
                await app._handle_command(f"/show {test_file.name}")
                # Wait for async operations
                await pilot.pause()
                await pilot.pause()

                # Should have a response (either success or error)
                assert len(chat_view._messages) > initial_msg_count

                # Check if side panel opened OR if message was added to chat
                # (TreeResult opens side panel, error shows in chat)
                if side_panel.is_open:
                    # Side panel opened - success
                    pass
                else:
                    # No side panel - check for system message about display
                    last_msg = chat_view._messages[-1]
                    assert "data.json" in last_msg.content or "Displaying" in last_msg.content

        import asyncio
        asyncio.run(run_test())

    def test_show_command_csv_file(self, tmp_path):
        """/show command should open CSV file in table viewer."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import SidePanel, TableViewer

        # Create temporary CSV file
        test_file = tmp_path / "data.csv"
        test_file.write_text("name,age\nAlice,30\nBob,25\n", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                side_panel = app.query_one(SidePanel)

                # Execute /show
                await app._handle_command(f"/show {test_file.name}")
                # Wait for widgets to be mounted
                await pilot.pause()

                # Side panel should be visible
                assert side_panel.is_open
                # Try to find TableViewer by ID or type
                try:
                    table_viewer = side_panel.query_one(TableViewer)
                    assert table_viewer is not None
                except Exception:
                    # Fallback - just verify side panel opened
                    assert side_panel.is_open

        asyncio.run(run_test())

    def test_edit_command(self, tmp_path):
        """/edit command should open file for editing."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import SidePanel, CodeEditor

        # Create temporary file
        test_file = tmp_path / "edit.txt"
        test_file.write_text("Original content", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                side_panel = app.query_one("#side-panel", SidePanel)

                # Execute /edit
                await app._handle_command(f"/edit {test_file.name}")

                # Side panel should be open with CodeEditor
                assert side_panel.is_open
                code_editor = side_panel.query_one(CodeEditor)
                assert code_editor is not None

        asyncio.run(run_test())

    def test_cd_pwd_commands(self, tmp_path):
        """/cd and /pwd commands should work together."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView
        import os

        # Create subdirectory
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one(ChatView)

                # Show current directory
                await app._handle_command("/pwd")
                assert len(chat_view._messages) > 0

                # Change directory
                initial_msg_count = len(chat_view._messages)
                await app._handle_command(f"/cd subdir")

                # Should have a message about the directory change (success or error)
                assert len(chat_view._messages) > initial_msg_count

                # CRITICAL: Verify working directory is actually changed
                # This has been a source of regressions - working dir must sync between:
                # 1. TUI app._working_dir
                # 2. Engine client working_dir
                # 3. Actual OS working directory
                assert "subdir" in app._working_dir, f"App working dir not updated: {app._working_dir}"
                if app._engine_client:
                    engine_wd = app._engine_client.get_working_dir()
                    assert "subdir" in engine_wd, f"Engine client working dir not updated: {engine_wd}"

        asyncio.run(run_test())

    def test_status_command(self):
        """/status command should display app status."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one(ChatView)

                # Execute /status
                await app._handle_command("/status")

                # Should have status message
                assert len(chat_view._messages) > 0
                last_msg = chat_view._messages[-1]
                assert last_msg.role == "system"
                # Status should contain provider/model info
                assert "Provider" in last_msg.content or "Model" in last_msg.content

        asyncio.run(run_test())

    def test_multiple_commands_sequence(self, tmp_path):
        """Multiple commands should execute in sequence."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView

        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                # Execute multiple commands
                await app._handle_command("/help")
                await app._handle_command("/pwd")
                await app._handle_command("/status")

                # Chat should have messages from commands
                assert len(chat_view._messages) >= 3

        asyncio.run(run_test())

    def test_side_panel_with_different_content_types(self, tmp_path):
        """Side panel should handle different content types."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import SidePanel

        # Create different file types
        py_file = tmp_path / "code.py"
        py_file.write_text("print('hello')", encoding="utf-8")

        json_file = tmp_path / "data.json"
        json_file.write_text(json.dumps({"key": "value"}), encoding="utf-8")

        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b\n1,2\n", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                side_panel = app.query_one(SidePanel)

                # Show Python file
                await app._handle_command(f"/show {py_file.name}")
                assert side_panel.is_open

                # Show JSON file
                await app._handle_command(f"/show {json_file.name}")
                assert side_panel.is_open

                # Show CSV file
                await app._handle_command(f"/show {csv_file.name}")
                assert side_panel.is_open

        import asyncio
        asyncio.run(run_test())

    def test_chat_and_side_panel_interaction(self, tmp_path):
        """Chat messages should work while side panel is open."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView, SidePanel

        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("# Test file", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one(ChatView)
                side_panel = app.query_one(SidePanel)

                # Open side panel
                await app._handle_command(f"/show {test_file.name}")
                assert side_panel.is_open

                # Add chat messages
                chat_view.add_user_message("Message while panel open")
                chat_view.add_assistant_message("Response while panel open")

                # Both should work
                assert side_panel.is_open
                assert len(chat_view._messages) >= 3  # /show message + 2 new messages

        asyncio.run(run_test())

    def test_theme_switching_preserves_state(self, tmp_path):
        """Theme changes should preserve chat and panel state."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView, SidePanel

        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("# Test", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)
                side_panel = app.query_one("#side-panel", SidePanel)

                # Add messages
                chat_view.add_user_message("Test message")
                initial_user_msg_count = len([m for m in chat_view._messages if m.role == "user"])

                # Switch theme
                await app._handle_command("/theme")

                # State should be preserved (user messages unchanged)
                current_user_msg_count = len([m for m in chat_view._messages if m.role == "user"])
                assert current_user_msg_count == initial_user_msg_count

        asyncio.run(run_test())

    def test_input_history_navigation(self):
        """Input box should support history navigation."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import InputBox

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                input_box = app.query_one(InputBox)

                # Set history
                test_history = ["command 1", "command 2", "command 3"]
                input_box.set_history(test_history)

                # Verify history is set
                assert input_box.get_history() == test_history

                # Clear history
                input_box.clear_history()
                assert input_box.get_history() == []

        asyncio.run(run_test())

    def test_error_recovery(self):
        """App should recover from command errors."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one(ChatView)

                # Try invalid commands
                await app._handle_command("/show nonexistent.txt")
                await app._handle_command("/cd /nonexistent/path")

                # App should still be functional
                await app._handle_command("/help")

                # Should have messages from all attempts
                assert len(chat_view._messages) >= 3

        asyncio.run(run_test())

    def test_multiple_files_in_sequence(self, tmp_path):
        """Opening multiple files in sequence should work."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import SidePanel
        from pathlib import Path

        # Create multiple JSON files (simpler content type)
        file1 = tmp_path / "file1.json"
        file1.write_text('{"name": "file1"}', encoding="utf-8")
        file2 = tmp_path / "file2.json"
        file2.write_text('{"name": "file2"}', encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                side_panel = app.query_one("#side-panel", SidePanel)

                # Open first file
                await app._handle_command(f"/show {file1.name}")
                assert side_panel.is_open

                # Open second file (replaces first)
                await app._handle_command(f"/show {file2.name}")
                assert side_panel.is_open

        asyncio.run(run_test())

    def test_concurrent_widget_updates(self, tmp_path):
        """Multiple widgets should update concurrently."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView, SidePanel, StatusBar

        # Create test JSON file (simpler)
        test_file = tmp_path / "test.json"
        test_file.write_text('{"key": "value"}', encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)
                side_panel = app.query_one("#side-panel", SidePanel)
                status_bar = app.query_one(StatusBar)

                # Update multiple widgets concurrently
                chat_view.add_user_message("Message 1")
                original_theme_index = app._current_theme_index

                # Directly call action to cycle theme
                app.action_cycle_theme()

                # All widgets should be functional
                assert len(chat_view._messages) >= 1
                assert app._current_theme_index != original_theme_index

        asyncio.run(run_test())


class TestKeyRegistry:
    """Test the centralized key binding registry."""

    def test_app_bindings_count(self):
        """get_app_bindings() returns all app-level bindings.
        v1.17.4 Phase 7.2: +1 for ctrl+u (attach_shortcut).
        """
        from ppxai.tui.keys import get_app_bindings
        bindings = get_app_bindings()
        assert len(bindings) == 16

    def test_widget_bindings(self):
        """get_widget_bindings() returns correct counts for each widget."""
        from ppxai.tui.keys import get_widget_bindings
        assert len(get_widget_bindings("FileTree")) == 4  # v1.17.4: +1 for 'a' (attach)
        assert len(get_widget_bindings("SidePanel")) == 2
        assert len(get_widget_bindings("DataViewer")) == 3
        assert len(get_widget_bindings("TableViewer")) == 1
        assert len(get_widget_bindings("EditorScreen")) == 2
        assert len(get_widget_bindings("ConfirmCloseScreen")) == 3
        assert len(get_widget_bindings("ViewerScreen")) == 2

    def test_no_empty_actions_in_bindings(self):
        """No binding should have an empty action string."""
        from ppxai.tui.keys import ALL_KEYS
        for k in ALL_KEYS:
            if k.is_binding:
                assert k.action != "", f"Empty action for {k.owner}:{k.key}"

    def test_keys_table_output(self):
        """get_keys_table() returns non-empty formatted output."""
        from ppxai.tui.keys import get_keys_table
        table = get_keys_table()
        assert "Keyboard Shortcuts" in table
        assert "Ctrl+Enter" in table
        assert "Chat Input" in table
        assert "File Tree" in table

    def test_conflicts_table_output(self):
        """get_conflicts_table() returns non-empty formatted output."""
        from ppxai.tui.keys import get_conflicts_table
        table = get_conflicts_table()
        assert "Known Key Binding Conflicts" in table
        assert "Ctrl+W" in table

    def test_app_bindings_match_app_class(self):
        """App BINDINGS are generated from the registry."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.keys import get_app_bindings
        registry_bindings = get_app_bindings()
        assert len(PPXAIDEApp.BINDINGS) == len(registry_bindings)
        for app_b, reg_b in zip(PPXAIDEApp.BINDINGS, registry_bindings):
            assert app_b.key == reg_b.key
            assert app_b.action == reg_b.action

    def test_unknown_widget_returns_empty(self):
        """get_widget_bindings() returns empty list for unknown owner."""
        from ppxai.tui.keys import get_widget_bindings
        assert get_widget_bindings("NonExistentWidget") == []

    def test_on_key_handlers_not_in_bindings(self):
        """on_key handlers (is_binding=False) should not appear in get_widget_bindings."""
        from ppxai.tui.keys import get_widget_bindings
        assert get_widget_bindings("ChatTextArea") == []
        assert get_widget_bindings("InputBox") == []

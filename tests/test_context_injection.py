"""
Tests for context injection and @file reference handling.

These tests cover:
1. Engine layer ContextInjector (ppxai/engine/context.py)
2. TUI layer process_file_references (ppxai/commands.py)
3. Integration between both layers
"""

import pytest
import tempfile
from pathlib import Path
from ppxai.engine.context import ContextInjector


class TestContextInjector:
    """Test the engine layer ContextInjector."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("# Test File\n\nThis is test content.\n")
            temp_path = Path(f.name)
        yield temp_path
        if temp_path.exists():
            temp_path.unlink()

    @pytest.fixture
    def injector(self, temp_file):
        """Create a ContextInjector with temp directory."""
        return ContextInjector(working_dir=str(temp_file.parent))

    def test_detect_at_file_references(self, injector, temp_file):
        """Test that @ file references are detected."""
        message = f"Please edit @{temp_file}"
        files = injector.detect_file_references(message)
        assert str(temp_file) in files

    def test_detect_relative_file_references(self, injector):
        """Test that relative file references are detected."""
        message = "Please read ./test.py"
        files = injector.detect_file_references(message)
        assert './test.py' in files

    def test_detect_absolute_file_references(self, injector):
        """Test that absolute file references are detected."""
        message = "Please read /tmp/test.py"
        files = injector.detect_file_references(message)
        assert '/tmp/test.py' in files

    def test_detect_home_file_references(self, injector):
        """Test that home directory file references are detected."""
        message = "Please read ~/test.py"
        files = injector.detect_file_references(message)
        assert '~/test.py' in files

    def test_detect_quoted_file_references(self, injector):
        """Test that quoted file paths are detected."""
        message = 'Please read "test.py"'
        files = injector.detect_file_references(message)
        assert 'test.py' in files

    def test_should_inject_with_at_symbol(self, injector, temp_file):
        """Test that @ symbol triggers injection."""
        message = f"Please edit @{temp_file}"
        files = [str(temp_file)]
        assert injector.should_inject(message, files) is True

    def test_should_inject_with_keywords(self, injector):
        """Test that keywords trigger injection."""
        for keyword in ['read', 'show', 'display', 'explain', 'review']:
            message = f"Please {keyword} test.py"
            files = ['test.py']
            assert injector.should_inject(message, files) is True, f"Keyword '{keyword}' should trigger injection"

    def test_should_inject_short_message(self, injector):
        """Test that short messages with files trigger injection."""
        message = "test.py"
        files = ['test.py']
        assert injector.should_inject(message, files) is True

    def test_should_not_inject_long_message_without_keywords(self, injector):
        """Test that long messages without keywords don't trigger injection."""
        message = "This is a very long message that mentions test.py but doesn't use any keywords"
        files = ['test.py']
        # Should not inject because no keywords and message is long
        assert injector.should_inject(message, files) is False

    def test_inject_context_with_at_reference(self, injector, temp_file):
        """Test that @ references are injected and cleaned from message."""
        message = f"Please edit the title in @{temp_file}"
        enhanced, contexts = injector.inject_context(message)

        # File content should be injected
        assert len(contexts) == 1
        # Use resolve() to handle symlinks like /var -> /private/var on macOS
        assert Path(contexts[0].source).resolve() == temp_file.resolve()
        assert "# Test File" in contexts[0].content

        # Enhanced message should have file content
        assert "**Attached file contents:**" in enhanced
        assert "# Test File" in enhanced

        # @ reference should be replaced with filename
        assert f"@{temp_file}" not in enhanced
        assert temp_file.name in enhanced

    def test_inject_context_preserves_non_at_files(self, injector, temp_file):
        """Test that non-@ file references are not cleaned."""
        message = f"Please read the file at {temp_file}"
        enhanced, contexts = injector.inject_context(message)

        # Should still inject (short message)
        assert len(contexts) == 1

        # But original path should remain (no @ to remove)
        assert str(temp_file) in enhanced

    def test_inject_context_multiple_files(self, injector, temp_file):
        """Test injecting multiple files."""
        # Create second temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, dir=temp_file.parent) as f:
            f.write("def test():\n    pass\n")
            temp_file2 = Path(f.name)

        try:
            message = f"Compare @{temp_file} and @{temp_file2}"
            enhanced, contexts = injector.inject_context(message)

            # Both files should be injected
            assert len(contexts) == 2
            # Use resolve() to handle symlinks
            sources = [Path(ctx.source).resolve() for ctx in contexts]
            assert temp_file.resolve() in sources
            assert temp_file2.resolve() in sources

            # Both should appear in enhanced message
            assert "# Test File" in enhanced
            assert "def test():" in enhanced
        finally:
            if temp_file2.exists():
                temp_file2.unlink()

    def test_inject_context_nonexistent_file(self, injector):
        """Test that nonexistent files don't cause injection."""
        message = "Please read @/nonexistent/file.txt"
        enhanced, contexts = injector.inject_context(message)

        # Should not inject (file doesn't exist)
        assert len(contexts) == 0
        assert enhanced == message  # Unchanged

    def test_detect_language_from_extension(self, injector):
        """Test language detection from file extensions."""
        assert injector._detect_language('.py') == 'python'
        assert injector._detect_language('.js') == 'javascript'
        assert injector._detect_language('.md') == 'markdown'
        assert injector._detect_language('.txt') == 'text'
        assert injector._detect_language('.unknown') == ''

    def test_large_file_truncation(self, injector):
        """Test that large files are truncated."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, dir=injector.working_dir) as f:
            # Write content larger than MAX_FILE_SIZE
            large_content = "x" * (ContextInjector.MAX_FILE_SIZE + 1000)
            f.write(large_content)
            temp_path = Path(f.name)

        try:
            ctx = injector.read_file(str(temp_path))
            assert ctx is not None
            assert ctx.truncated is True
            assert len(ctx.content) <= ContextInjector.MAX_FILE_SIZE
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_very_large_file_not_read(self, injector):
        """Test that very large files show error message."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, dir=injector.working_dir) as f:
            # Actually write content larger than MAX_FILE_SIZE * 2
            # (sparse files don't work for text files)
            large_content = "x" * (ContextInjector.MAX_FILE_SIZE * 2 + 1000)
            f.write(large_content)
            temp_path = Path(f.name)

        try:
            ctx = injector.read_file(str(temp_path))
            assert ctx is not None
            assert "[File too large:" in ctx.content
            assert ctx.truncated is True
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_binary_file_not_read(self, injector):
        """Test that binary files are not read."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.png', delete=False, dir=injector.working_dir) as f:
            f.write(b'\x89PNG\r\n\x1a\n')
            temp_path = Path(f.name)

        try:
            ctx = injector.read_file(str(temp_path))
            assert ctx is None  # Binary file should not be read
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_resolve_relative_path(self, injector, temp_file):
        """Test that relative paths are resolved."""
        filename = temp_file.name
        resolved = injector.resolve_path(filename)
        assert resolved is not None
        assert resolved.exists()
        assert resolved.name == filename

    def test_resolve_absolute_path(self, injector, temp_file):
        """Test that absolute paths are resolved."""
        resolved = injector.resolve_path(str(temp_file))
        assert resolved is not None
        # Use resolve() to handle symlinks like /var -> /private/var on macOS
        assert resolved.resolve() == temp_file.resolve()

    def test_resolve_home_path(self, injector):
        """Test that home directory paths are resolved."""
        import os
        # Create a file in home directory for testing
        home_file = Path.home() / f".ppxai_test_{os.getpid()}.txt"
        try:
            home_file.write_text("test")
            resolved = injector.resolve_path(f"~/{home_file.name}")
            assert resolved is not None
            assert resolved.resolve() == home_file.resolve()
        finally:
            if home_file.exists():
                home_file.unlink()


class TestTUIFileReferences:
    """Test TUI layer @file reference processing."""

    @pytest.fixture
    def handler(self):
        """Create a CommandHandler for testing."""
        from ppxai.commands import CommandHandler
        from ppxai.client import AIClient

        # Create a mock client
        client = AIClient(api_key="test")
        handler = CommandHandler(
            client=client,
            api_key="test",
            current_model="test-model",
            base_url="https://test.com",
            provider="test"
        )
        return handler

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("# Test File\n\nThis is test content.\n")
            temp_path = Path(f.name)
        yield temp_path
        if temp_path.exists():
            temp_path.unlink()

    def test_process_file_references_with_at_symbol(self, handler, temp_file):
        """Test that TUI processes @ file references."""
        message = f"Please edit @{temp_file.name}"

        # Set working directory to temp file's directory
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_file.parent)
            augmented, resolved = handler.process_file_references(message)

            # File should be resolved
            assert len(resolved) == 1
            assert resolved[0]['name'] == temp_file.name
            # Use resolve() to handle symlinks like /var -> /private/var on macOS
            assert Path(resolved[0]['path']).resolve() == temp_file.resolve()

            # Message should be augmented with file content
            assert "**Referenced Files:**" in augmented
            assert temp_file.name in augmented
            assert "# Test File" in augmented  # File content should be in augmented message
        finally:
            os.chdir(old_cwd)

    def test_process_file_references_no_matches(self, handler):
        """Test that messages without @ references are unchanged."""
        message = "This is a regular message"
        augmented, resolved = handler.process_file_references(message)

        assert augmented == message
        assert len(resolved) == 0

    def test_process_file_references_nonexistent_file(self, handler):
        """Test that nonexistent files are handled gracefully."""
        message = "Please edit @nonexistent_file_12345.txt"
        augmented, resolved = handler.process_file_references(message)

        # Should not find file
        assert len(resolved) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

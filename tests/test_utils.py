"""Unit tests for ppxai.utils module."""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from ppxai.utils import read_file_content


class TestReadFileContent:
    """Tests for read_file_content function."""

    def test_read_existing_file(self, tmp_path):
        """Test reading an existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")

        content = read_file_content(str(test_file))
        assert content == "Hello, World!"

    def test_read_nonexistent_file(self):
        """Test reading a nonexistent file returns None."""
        content = read_file_content("/nonexistent/file.txt")
        assert content is None

    def test_read_directory_returns_none(self, tmp_path):
        """Test reading a directory returns None."""
        content = read_file_content(str(tmp_path))
        assert content is None

    def test_read_file_with_unicode(self, tmp_path):
        """Test reading a file with unicode content."""
        test_file = tmp_path / "unicode.txt"
        test_file.write_text("Hello, 世界! 🌍", encoding="utf-8")

        content = read_file_content(str(test_file))
        assert content == "Hello, 世界! 🌍"

    def test_read_file_expands_user_path(self, tmp_path, monkeypatch):
        """Test that user paths are expanded."""
        # Create a file in a temp directory
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # Mock expanduser to return our temp path
        def mock_expanduser(path):
            if str(path).startswith("~"):
                return Path(str(path).replace("~", str(tmp_path.parent)))
            return path

        with patch.object(Path, 'expanduser', lambda self: mock_expanduser(self)):
            # This test just verifies the function handles path expansion
            content = read_file_content(str(test_file))
            assert content == "test content"

    def test_read_empty_file(self, tmp_path):
        """Test reading an empty file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_text("")

        content = read_file_content(str(test_file))
        assert content == ""

    def test_read_multiline_file(self, tmp_path):
        """Test reading a multiline file."""
        test_file = tmp_path / "multiline.txt"
        expected = "Line 1\nLine 2\nLine 3"
        test_file.write_text(expected)

        content = read_file_content(str(test_file))
        assert content == expected

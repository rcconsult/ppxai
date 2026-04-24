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
from ppxai.engine.context import ContextInjector, MAX_FILE_SIZE


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
        # Use just the filename (users type @filename.ext, not full paths)
        filename = temp_file.name
        message = f"Please edit @{filename}"
        files = injector.detect_file_references(message)
        assert filename in files

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
        # Use just the filename (users type @filename.ext, not full paths)
        filename = temp_file.name
        message = f"Please edit the title in @{filename}"
        enhanced, contexts = injector.inject_context(message)

        # File content should be injected
        assert len(contexts) == 1
        # Use resolve() to handle symlinks like /var -> /private/var on macOS
        assert Path(contexts[0].source).resolve() == temp_file.resolve()
        assert "# Test File" in contexts[0].content

        # Enhanced message should have file content
        assert "**Attached context:**" in enhanced
        assert "# Test File" in enhanced

        # @ reference should be replaced with filename
        assert f"@{filename}" not in enhanced
        assert filename in enhanced

    def test_inject_context_preserves_non_at_files(self, injector, temp_file):
        """Test that non-@ file references are not cleaned."""
        # Use quoted filename (users type "filename.ext" for file references)
        filename = temp_file.name
        message = f'Please read the file "{filename}"'
        enhanced, contexts = injector.inject_context(message)

        # Should still inject (quoted file reference)
        assert len(contexts) == 1

        # But original quoted path should remain (no @ to remove)
        assert filename in enhanced

    def test_inject_context_multiple_files(self, injector, temp_file):
        """Test injecting multiple files."""
        # Create second temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, dir=temp_file.parent) as f:
            f.write("def test():\n    pass\n")
            temp_file2 = Path(f.name)

        try:
            # Use just filenames (users type @filename.ext, not full paths)
            filename1 = temp_file.name
            filename2 = temp_file2.name
            message = f"Compare @{filename1} and @{filename2}"
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
            large_content = "x" * (MAX_FILE_SIZE + 1000)
            f.write(large_content)
            temp_path = Path(f.name)

        try:
            ctx = injector.read_file(str(temp_path))
            assert ctx is not None
            assert ctx.truncated is True
            assert len(ctx.content) <= MAX_FILE_SIZE
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_very_large_file_not_read(self, injector):
        """Test that very large files show error message."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, dir=injector.working_dir) as f:
            # Actually write content larger than MAX_FILE_SIZE * 2
            # (sparse files don't work for text files)
            large_content = "x" * (MAX_FILE_SIZE * 2 + 1000)
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
            home_file.write_text("test", encoding="utf-8")
            resolved = injector.resolve_path(f"~/{home_file.name}")
            assert resolved is not None
            assert resolved.resolve() == home_file.resolve()
        finally:
            if home_file.exists():
                home_file.unlink()

    def test_inject_git_context_with_changes(self, injector):
        """Test @git context injection when there are git changes."""
        import subprocess
        import tempfile
        import os

        # Create a temporary git repo
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize git repo
            subprocess.run(['git', 'init'], cwd=tmpdir, capture_output=True)
            subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=tmpdir, capture_output=True)
            subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=tmpdir, capture_output=True)

            # Create and commit a file
            test_file = Path(tmpdir) / 'test.txt'
            test_file.write_text("original content\n", encoding="utf-8")
            subprocess.run(['git', 'add', 'test.txt'], cwd=tmpdir, capture_output=True)
            subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=tmpdir, capture_output=True)

            # Make unstaged changes
            test_file.write_text("modified content\n", encoding="utf-8")

            # Create another file and stage it
            new_file = Path(tmpdir) / 'new.txt'
            new_file.write_text("new file\n", encoding="utf-8")
            subprocess.run(['git', 'add', 'new.txt'], cwd=tmpdir, capture_output=True)

            # Test git context injection
            git_injector = ContextInjector(working_dir=tmpdir)
            ctx = git_injector.inject_git_context()

            assert ctx is not None
            assert ctx.source == "@git"
            assert ctx.language == "diff"
            assert "=== Staged Changes ===" in ctx.content
            assert "=== Unstaged Changes ===" in ctx.content
            assert "new.txt" in ctx.content  # Staged file
            assert "test.txt" in ctx.content  # Modified file

    def test_inject_git_context_no_changes(self, injector):
        """Test @git context when there are no changes."""
        import subprocess
        import tempfile

        # Create a temporary git repo with no changes
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(['git', 'init'], cwd=tmpdir, capture_output=True)
            subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=tmpdir, capture_output=True)
            subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=tmpdir, capture_output=True)

            # Create and commit a file
            test_file = Path(tmpdir) / 'test.txt'
            test_file.write_text("content\n", encoding="utf-8")
            subprocess.run(['git', 'add', 'test.txt'], cwd=tmpdir, capture_output=True)
            subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=tmpdir, capture_output=True)

            # Test git context injection with no changes
            git_injector = ContextInjector(working_dir=tmpdir)
            ctx = git_injector.inject_git_context()

            assert ctx is not None
            assert ctx.source == "@git"
            assert "No changes in working directory" in ctx.content

    def test_inject_git_context_not_a_repo(self, injector):
        """Test @git context when not in a git repository."""
        import tempfile

        # Use a non-git directory
        with tempfile.TemporaryDirectory() as tmpdir:
            non_git_injector = ContextInjector(working_dir=tmpdir)
            ctx = non_git_injector.inject_git_context()

            # Should return None when not in a git repo
            assert ctx is None

    def test_inject_tree_context(self, injector):
        """Test @tree context injection."""
        import tempfile
        import os

        # Create a temporary directory structure
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some files and directories
            (Path(tmpdir) / 'file1.txt').write_text("content", encoding="utf-8")
            (Path(tmpdir) / 'file2.py').write_text("print('hello')", encoding="utf-8")
            (Path(tmpdir) / 'subdir').mkdir()
            (Path(tmpdir) / 'subdir' / 'nested.md').write_text("# Nested", encoding="utf-8")
            (Path(tmpdir) / '.git').mkdir()  # Should be ignored

            tree_injector = ContextInjector(working_dir=tmpdir)
            ctx = tree_injector.inject_tree_context()

            assert ctx is not None
            assert ctx.source == "@tree"
            assert ctx.language == "text"
            assert "file1.txt" in ctx.content
            assert "file2.py" in ctx.content
            assert "subdir/" in ctx.content
            assert "nested.md" in ctx.content
            assert ".git" not in ctx.content  # Should be filtered out
            assert "Directories:" in ctx.content
            assert "Files:" in ctx.content

    def test_inject_tree_context_max_depth(self, injector):
        """Test @tree context respects max_depth."""
        import tempfile

        # Create deep directory structure
        with tempfile.TemporaryDirectory() as tmpdir:
            current = Path(tmpdir)
            for i in range(5):
                current = current / f'level{i}'
                current.mkdir()
                (current / f'file{i}.txt').write_text(f"level {i}", encoding="utf-8")

            tree_injector = ContextInjector(working_dir=tmpdir)

            # Test with max_depth=2
            ctx = tree_injector.inject_tree_context(max_depth=2)

            assert ctx is not None
            assert "level0" in ctx.content
            assert "level1" in ctx.content
            assert "level2" in ctx.content
            # level3 and level4 should not appear (beyond max_depth)
            assert "level3" not in ctx.content
            assert "level4" not in ctx.content

    def test_inject_context_with_git_pattern(self, injector):
        """Test that @git pattern triggers git context injection."""
        import subprocess
        import tempfile

        # Create a temporary git repo with changes
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(['git', 'init'], cwd=tmpdir, capture_output=True)
            subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=tmpdir, capture_output=True)
            subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=tmpdir, capture_output=True)

            test_file = Path(tmpdir) / 'test.txt'
            test_file.write_text("original\n", encoding="utf-8")
            subprocess.run(['git', 'add', 'test.txt'], cwd=tmpdir, capture_output=True)
            subprocess.run(['git', 'commit', '-m', 'Initial'], cwd=tmpdir, capture_output=True)
            test_file.write_text("modified\n", encoding="utf-8")

            git_injector = ContextInjector(working_dir=tmpdir)
            message = "Review the changes in @git and suggest improvements"
            enhanced, contexts = git_injector.inject_context(message)

            # Should inject git context
            assert len(contexts) == 1
            assert contexts[0].source == "@git"
            assert "=== Unstaged Changes ===" in contexts[0].content

            # Enhanced message should contain git diff
            assert "**Attached context:**" in enhanced
            assert "```diff" in enhanced
            # @git should be replaced in message body
            assert "Review the changes in `git diff`" in enhanced
            # But @git still appears as source in context header (which is correct)
            assert "**`@git`**" in enhanced

    def test_inject_context_with_tree_pattern(self, injector):
        """Test that @tree pattern triggers tree context injection."""
        import tempfile

        # Create a temporary directory with files
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / 'file1.txt').write_text("content", encoding="utf-8")
            (Path(tmpdir) / 'file2.py').write_text("code", encoding="utf-8")

            tree_injector = ContextInjector(working_dir=tmpdir)
            message = "Here's the project structure: @tree"
            enhanced, contexts = tree_injector.inject_context(message)

            # Should inject tree context
            assert len(contexts) == 1
            assert contexts[0].source == "@tree"
            assert "file1.txt" in contexts[0].content
            assert "file2.py" in contexts[0].content

            # Enhanced message should contain tree
            assert "**Attached context:**" in enhanced
            assert "```text" in enhanced
            # @tree should be replaced in message body
            assert "Here's the project structure: `project tree`" in enhanced
            # But @tree still appears as source in context header (which is correct)
            assert "**`@tree`**" in enhanced

    def test_inject_context_combined_git_tree_file(self, injector, temp_file):
        """Test using @git, @tree, and @file together."""
        import subprocess
        import tempfile
        import shutil

        # Create a temporary git repo
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(['git', 'init'], cwd=tmpdir, capture_output=True)
            subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=tmpdir, capture_output=True)
            subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=tmpdir, capture_output=True)

            # Copy temp_file to git repo
            test_file = Path(tmpdir) / temp_file.name
            shutil.copy(temp_file, test_file)
            subprocess.run(['git', 'add', temp_file.name], cwd=tmpdir, capture_output=True)
            subprocess.run(['git', 'commit', '-m', 'Initial'], cwd=tmpdir, capture_output=True)

            # Make a change
            test_file.write_text("modified content\n", encoding="utf-8")

            # Create another file for @file reference
            another_file = Path(tmpdir) / 'another.txt'
            another_file.write_text("another file content\n", encoding="utf-8")

            combined_injector = ContextInjector(working_dir=tmpdir)
            message = f"Review @git changes, check @tree structure, and edit @{another_file.name}"
            enhanced, contexts = combined_injector.inject_context(message)

            # Should inject all three types
            assert len(contexts) == 3
            sources = [ctx.source for ctx in contexts]
            assert "@git" in sources
            assert "@tree" in sources
            # Check file is in sources (use resolve for symlink handling)
            file_sources = [s for s in sources if s not in ["@git", "@tree"]]
            assert len(file_sources) == 1
            assert Path(file_sources[0]).resolve() == another_file.resolve()

            # Enhanced message should contain all contexts
            assert "**Attached context:**" in enhanced
            assert "`git diff`" in enhanced
            assert "`project tree`" in enhanced
            assert another_file.name in enhanced


class TestTUIFileReferences:
    """Test TUI layer @file reference processing."""

    @pytest.fixture
    def handler(self):
        """Create a CommandHandler for testing.

        v1.12.0: Updated to use new CommandHandler signature (no client).
        """
        from ppxai.commands import CommandHandler

        # v1.12.0: No longer need AIClient - CommandHandler creates EngineClient
        handler = CommandHandler(
            "test",  # api_key
            "test-model",  # current_model
            "https://test.com",  # base_url
            "test"  # provider
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
        # v1.13.9: Need to set both OS cwd and engine client's working directory
        import os
        old_cwd = os.getcwd()
        old_engine_cwd = handler.engine_client.get_working_dir()
        try:
            os.chdir(temp_file.parent)
            # Also set the engine client's working directory (used by _search_files)
            handler.engine_client.set_working_dir(str(temp_file.parent))
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
            if old_engine_cwd:
                handler.engine_client.set_working_dir(old_engine_cwd)

    def test_process_file_references_no_matches(self, handler):
        """Test that messages without @ references are unchanged."""
        message = "This is a regular message"
        augmented, resolved = handler.process_file_references(message)

        assert augmented == message
        assert len(resolved) == 0

    def test_process_file_references_nonexistent_file(self, handler):
        """Test that nonexistent files are handled gracefully.

        Note: We mock _search_files to avoid expensive directory scans on WSL/Windows
        which can take 170+ seconds due to filesystem I/O overhead.
        """
        from unittest.mock import patch

        message = "Please edit @nonexistent_file_12345.txt"

        # Mock _search_files to return empty list (file not found) immediately
        with patch.object(handler, '_search_files', return_value=[]):
            augmented, resolved = handler.process_file_references(message)

        # Should not find file
        assert len(resolved) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

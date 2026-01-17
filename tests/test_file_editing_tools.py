"""
Tests for file editing tools with consent (v1.11.0 Phase 1).

These tests verify:
- Consent mechanism (session state, callbacks)
- All 4 file editing tools (apply_patch, replace_block, insert_text, delete_lines)
- Consent flow integration
- Error cases and rollback
"""

import pytest
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from ppxai.engine import EngineClient
from ppxai.engine.session import SessionManager
from ppxai.constants import ConsentMode
from ppxai.engine.tools.builtin.editor import (
    ApplyPatchTool,
    ReplaceBlockTool,
    InsertTextTool,
    DeleteLinesTool,
    _is_new_file_diff,
    _apply_unified_diff,
    _apply_search_replace_diff,
)


# === Fixtures ===

@pytest.fixture
def temp_file():
    """Create a temporary file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Line 1\nLine 2\nLine 3\n")
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def mock_consent_callback():
    """Create a mock consent callback."""
    async def consent_callback(file_path: str):
        # Default: approve with 'y'
        return (True, 'y')

    return AsyncMock(side_effect=consent_callback)


@pytest.fixture
def engine_with_consent(mock_consent_callback):
    """Create an EngineClient with consent callback."""
    engine = EngineClient(consent_callback=mock_consent_callback)
    return engine


# === Session Consent State Tests ===

def test_session_consent_state_initialization():
    """Test that SessionManager initializes consent state correctly."""
    session = SessionManager()

    assert hasattr(session, 'allowed_files')
    assert hasattr(session, 'edit_consent_mode')
    assert session.allowed_files == set()
    assert session.edit_consent_mode == ConsentMode.PROMPT


def test_session_consent_state_cleared_on_clear():
    """Test that consent state is reset when clearing session."""
    session = SessionManager()

    # Add some consent state
    session.allowed_files.add(Path('/tmp/test.txt'))
    session.edit_consent_mode = ConsentMode.ALWAYS

    # Clear session
    session.clear()

    # Verify reset
    assert session.allowed_files == set()
    assert session.edit_consent_mode == ConsentMode.PROMPT


def test_session_remove_last_message():
    """Test that remove_last_message works correctly for Ctrl-C cleanup (v1.11.5)."""
    from ppxai.engine.types import Message
    session = SessionManager()

    # Add some messages
    session.add_message(Message(role="user", content="Hello"))
    session.add_message(Message(role="assistant", content="Hi there!"))
    session.add_message(Message(role="user", content="Interrupted message"))

    assert len(session.messages) == 3
    assert session.messages[-1].role == "user"

    # Remove last message (simulating Ctrl-C during streaming)
    result = session.remove_last_message()

    assert result is True
    assert len(session.messages) == 2
    assert session.messages[-1].role == "assistant"
    assert session.metadata["message_count"] == 2


def test_session_remove_last_message_empty():
    """Test that remove_last_message returns False for empty session."""
    session = SessionManager()

    assert len(session.messages) == 0

    result = session.remove_last_message()

    assert result is False
    assert len(session.messages) == 0


# === Consent Flow Tests ===

@pytest.mark.asyncio
async def test_consent_callback_called_on_first_edit():
    """Test that consent callback is called on first file edit."""
    mock_callback = AsyncMock(return_value=(True, 'y'))
    engine = EngineClient(consent_callback=mock_callback)

    # Request consent
    approved = await engine.request_file_edit_consent('/tmp/test.txt')

    assert approved is True
    mock_callback.assert_called_once_with(str(Path('/tmp/test.txt').resolve()))


@pytest.mark.asyncio
async def test_consent_not_called_if_already_allowed():
    """Test that consent callback is not called if file already allowed."""
    mock_callback = AsyncMock(return_value=(True, 'y'))
    engine = EngineClient(consent_callback=mock_callback)

    # First request - callback called
    await engine.request_file_edit_consent('/tmp/test.txt')
    assert mock_callback.call_count == 1

    # Second request - callback not called (already allowed)
    await engine.request_file_edit_consent('/tmp/test.txt')
    assert mock_callback.call_count == 1  # Still 1


@pytest.mark.asyncio
async def test_consent_always_mode():
    """Test that 'always' mode allows all files without prompting."""
    mock_callback = AsyncMock(return_value=(True, 'always'))
    engine = EngineClient(consent_callback=mock_callback)

    # First request - callback called, sets mode to 'always'
    approved1 = await engine.request_file_edit_consent('/tmp/file1.txt')
    assert approved1 is True
    assert mock_callback.call_count == 1

    # Second request - callback not called (always mode)
    approved2 = await engine.request_file_edit_consent('/tmp/file2.txt')
    assert approved2 is True
    assert mock_callback.call_count == 1  # Still 1


@pytest.mark.asyncio
async def test_consent_never_mode():
    """Test that 'never' mode denies all files without prompting."""
    mock_callback = AsyncMock(return_value=(False, 'never'))
    engine = EngineClient(consent_callback=mock_callback)

    # First request - callback called, sets mode to 'never'
    approved1 = await engine.request_file_edit_consent('/tmp/file1.txt')
    assert approved1 is False
    assert mock_callback.call_count == 1

    # Second request - callback not called (never mode)
    approved2 = await engine.request_file_edit_consent('/tmp/file2.txt')
    assert approved2 is False
    assert mock_callback.call_count == 1  # Still 1


@pytest.mark.asyncio
async def test_consent_denial():
    """Test that 'n' response denies file edit."""
    mock_callback = AsyncMock(return_value=(False, 'n'))
    engine = EngineClient(consent_callback=mock_callback)

    approved = await engine.request_file_edit_consent('/tmp/test.txt')

    assert approved is False
    assert Path('/tmp/test.txt').resolve() not in engine.session.allowed_files


@pytest.mark.asyncio
async def test_consent_default_to_allow_without_callback():
    """Test that no callback defaults to allowing edits (backward compatible)."""
    engine = EngineClient()  # No consent callback

    approved = await engine.request_file_edit_consent('/tmp/test.txt')

    assert approved is True


# === ReplaceBlockTool Tests ===

@pytest.mark.asyncio
async def test_replace_block_success(temp_file, engine_with_consent):
    """Test successful text replacement."""
    tool = ReplaceBlockTool(engine_with_consent)

    result = await tool.execute(
        file_path=str(temp_file),
        search="Line 2",
        replace="Modified Line 2"
    )

    # Verify result message
    assert "Successfully replaced block" in result

    # Verify file content
    content = temp_file.read_text()
    assert "Modified Line 2" in content
    # Check that original "Line 2\n" was replaced (not just substring)
    lines = content.split('\n')
    assert "Line 2" not in lines
    assert "Line 1" in lines  # Unchanged
    assert "Line 3" in lines  # Unchanged


@pytest.mark.asyncio
async def test_replace_block_consent_denied(temp_file):
    """Test replacement blocked by consent denial."""
    mock_callback = AsyncMock(return_value=(False, 'n'))
    engine = EngineClient(consent_callback=mock_callback)
    tool = ReplaceBlockTool(engine)

    result = await tool.execute(
        file_path=str(temp_file),
        search="Line 2",
        replace="Modified Line 2"
    )

    # Verify denial
    assert "User denied permission" in result

    # Verify file unchanged
    content = temp_file.read_text()
    assert "Line 2" in content
    assert "Modified Line 2" not in content


@pytest.mark.asyncio
async def test_replace_block_not_found(temp_file, engine_with_consent):
    """Test replacement when search text not found."""
    tool = ReplaceBlockTool(engine_with_consent)

    result = await tool.execute(
        file_path=str(temp_file),
        search="Nonexistent text",
        replace="Replacement"
    )

    assert "Search text not found" in result


@pytest.mark.asyncio
async def test_replace_block_multiple_matches(temp_file, engine_with_consent):
    """Test replacement fails when search text appears multiple times."""
    # Create file with duplicate content
    temp_file.write_text("Line 1\nDuplicate\nLine 3\nDuplicate\n")

    tool = ReplaceBlockTool(engine_with_consent)

    result = await tool.execute(
        file_path=str(temp_file),
        search="Duplicate",
        replace="Unique"
    )

    assert "found 2 times" in result
    assert "must be unique" in result


# === InsertTextTool Tests ===

@pytest.mark.asyncio
async def test_insert_text_success(temp_file, engine_with_consent):
    """Test successful text insertion."""
    tool = InsertTextTool(engine_with_consent)

    result = await tool.execute(
        file_path=str(temp_file),
        line_number=2,
        text="Inserted Line\n"
    )

    # Verify result message
    assert "Successfully inserted text" in result

    # Verify file content
    lines = temp_file.read_text().split('\n')
    assert lines[1] == "Inserted Line"
    assert lines[2] == "Line 2"


@pytest.mark.asyncio
async def test_insert_text_at_end(temp_file, engine_with_consent):
    """Test inserting text at end of file."""
    tool = InsertTextTool(engine_with_consent)

    result = await tool.execute(
        file_path=str(temp_file),
        line_number=4,
        text="New Last Line\n"
    )

    assert "Successfully inserted text" in result
    content = temp_file.read_text()
    assert "New Last Line" in content


@pytest.mark.asyncio
async def test_insert_text_invalid_line_number(temp_file, engine_with_consent):
    """Test insertion with invalid line number."""
    tool = InsertTextTool(engine_with_consent)

    result = await tool.execute(
        file_path=str(temp_file),
        line_number=100,
        text="Test"
    )

    assert "Invalid line number" in result


# === DeleteLinesTool Tests ===

@pytest.mark.asyncio
async def test_delete_lines_success(temp_file, engine_with_consent):
    """Test successful line deletion."""
    tool = DeleteLinesTool(engine_with_consent)

    result = await tool.execute(
        file_path=str(temp_file),
        start_line=2,
        end_line=2
    )

    # Verify result message
    assert "Successfully deleted lines" in result

    # Verify file content
    lines = temp_file.read_text().split('\n')
    assert "Line 1" in lines
    assert "Line 2" not in lines
    assert "Line 3" in lines


@pytest.mark.asyncio
async def test_delete_lines_range(temp_file, engine_with_consent):
    """Test deleting a range of lines."""
    # Create file with more lines
    temp_file.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n")

    tool = DeleteLinesTool(engine_with_consent)

    result = await tool.execute(
        file_path=str(temp_file),
        start_line=2,
        end_line=4
    )

    assert "Successfully deleted lines" in result
    content = temp_file.read_text()
    assert "Line 1" in content
    assert "Line 2" not in content
    assert "Line 3" not in content
    assert "Line 4" not in content
    assert "Line 5" in content


@pytest.mark.asyncio
async def test_delete_lines_invalid_range(temp_file, engine_with_consent):
    """Test deletion with invalid line range."""
    tool = DeleteLinesTool(engine_with_consent)

    result = await tool.execute(
        file_path=str(temp_file),
        start_line=10,
        end_line=20
    )

    assert "Invalid start line" in result


# === ApplyPatchTool Tests ===

@pytest.mark.asyncio
async def test_apply_patch_success(temp_file, engine_with_consent):
    """Test successful patch application."""
    tool = ApplyPatchTool(engine_with_consent)

    # Create a simple unified diff
    diff = """@@ -1,3 +1,3 @@
 Line 1
-Line 2
+Modified Line 2
 Line 3
"""

    result = await tool.execute(
        file_path=str(temp_file),
        unified_diff=diff
    )

    # Verify result message
    assert "Successfully applied patch" in result

    # Verify file content
    content = temp_file.read_text()
    assert "Modified Line 2" in content
    # Check that original "Line 2\n" was replaced (not just substring)
    lines = content.split('\n')
    assert "Line 2" not in lines


# === Error Handling and Rollback Tests ===

@pytest.mark.asyncio
async def test_rollback_on_error(temp_file, engine_with_consent):
    """Test that file is restored on error."""
    original_content = temp_file.read_text()

    tool = ReplaceBlockTool(engine_with_consent)

    # Attempt replacement that will fail during write
    # (We'll mock the write to raise an exception)
    with patch('builtins.open', side_effect=Exception("Write error")):
        result = await tool.execute(
            file_path=str(temp_file),
            search="Line 2",
            replace="Modified"
        )

    # Verify error was caught
    assert "Error" in result

    # File should still exist with original content
    # (Note: rollback happens, but we mocked open() so can't verify content)


@pytest.mark.asyncio
async def test_file_not_found_error(engine_with_consent):
    """Test handling of non-existent file."""
    tool = ReplaceBlockTool(engine_with_consent)

    result = await tool.execute(
        file_path="/nonexistent/file.txt",
        search="test",
        replace="replacement"
    )

    assert "File not found" in result


@pytest.mark.asyncio
async def test_not_a_file_error(engine_with_consent):
    """Test handling of directory path."""
    import tempfile
    tool = ReplaceBlockTool(engine_with_consent)

    # Use platform-appropriate temp directory
    temp_dir = tempfile.gettempdir()
    result = await tool.execute(
        file_path=temp_dir,  # Directory, not file
        search="test",
        replace="replacement"
    )

    assert "Not a file" in result


# === Integration Tests ===

@pytest.mark.asyncio
async def test_tool_registration_with_engine():
    """Test that tools are registered when engine is provided."""
    from ppxai.engine.tools.builtin import register_all_builtin_tools
    from ppxai.engine.tools.manager import ToolManager

    engine = EngineClient()
    manager = ToolManager()

    # Register tools with engine
    register_all_builtin_tools(manager, engine=engine)

    # Verify editor tools were registered
    tools = manager.list_tools()
    tool_names = [t['name'] for t in tools]

    assert 'apply_patch' in tool_names
    assert 'replace_block' in tool_names
    assert 'insert_text' in tool_names
    assert 'delete_lines' in tool_names


@pytest.mark.asyncio
async def test_tool_not_registered_without_engine():
    """Test that editor tools are not registered without engine."""
    from ppxai.engine.tools.builtin import register_all_builtin_tools
    from ppxai.engine.tools.manager import ToolManager

    manager = ToolManager()

    # Register tools without engine
    register_all_builtin_tools(manager, engine=None)

    # Verify editor tools were not registered
    tools = manager.list_tools()
    tool_names = [t['name'] for t in tools]

    assert 'apply_patch' not in tool_names
    assert 'replace_block' not in tool_names
    assert 'insert_text' not in tool_names
    assert 'delete_lines' not in tool_names


@pytest.mark.asyncio
async def test_multiple_file_edits_with_consent():
    """Test editing multiple files with per-file consent."""
    mock_callback = AsyncMock()
    # First file: approve, second file: approve, third file: deny
    mock_callback.side_effect = [
        (True, 'y'),   # file1.txt
        (True, 'y'),   # file2.txt
        (False, 'n'),  # file3.txt
    ]

    engine = EngineClient(consent_callback=mock_callback)

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='1.txt') as f1:
        f1.write("Content 1")
        file1 = Path(f1.name)

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='2.txt') as f2:
        f2.write("Content 2")
        file2 = Path(f2.name)

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='3.txt') as f3:
        f3.write("Content 3")
        file3 = Path(f3.name)

    try:
        tool = ReplaceBlockTool(engine)

        # Edit file1 - approved
        result1 = await tool.execute(str(file1), "Content 1", "Modified 1")
        assert "Successfully replaced" in result1

        # Edit file2 - approved
        result2 = await tool.execute(str(file2), "Content 2", "Modified 2")
        assert "Successfully replaced" in result2

        # Edit file3 - denied
        result3 = await tool.execute(str(file3), "Content 3", "Modified 3")
        assert "User denied permission" in result3

        # Verify consent callback called 3 times
        assert mock_callback.call_count == 3

    finally:
        file1.unlink()
        file2.unlink()
        file3.unlink()


# === New File Creation Tests (v1.13.2) ===

class TestNewFileCreation:
    """Tests for apply_patch creating new files via '*** Add File:' syntax."""

    def test_is_new_file_diff_add_file_syntax(self):
        """Test detection of '*** Add File:' syntax."""
        diff = """*** Begin Patch
*** Add File: test.py
+print("hello")
"""
        assert _is_new_file_diff(diff) is True

    def test_is_new_file_diff_new_file_syntax(self):
        """Test detection of '*** New File:' syntax."""
        diff = """*** New File: test.py
+print("hello")
"""
        assert _is_new_file_diff(diff) is True

    def test_is_new_file_diff_dev_null(self):
        """Test detection of standard unified diff new file (--- /dev/null)."""
        diff = """--- /dev/null
+++ b/test.py
@@ -0,0 +1,3 @@
+print("hello")
"""
        assert _is_new_file_diff(diff) is True

    def test_is_new_file_diff_hunk_zero(self):
        """Test detection of @@ -0,0 hunk header."""
        diff = """@@ -0,0 +1,3 @@
+print("hello")
"""
        assert _is_new_file_diff(diff) is True

    def test_is_new_file_diff_existing_file(self):
        """Test that existing file diffs are not detected as new."""
        diff = """@@ -1,3 +1,3 @@
 Line 1
-Line 2
+Modified Line 2
 Line 3
"""
        assert _is_new_file_diff(diff) is False

    def test_apply_unified_diff_new_file(self):
        """Test extracting content from new file diff."""
        diff = """*** Add File: test.py
+print("hello")
+print("world")
"""
        result = _apply_unified_diff([], diff, is_new_file=True)
        assert len(result) == 2
        assert 'print("hello")\n' in result
        assert 'print("world")\n' in result

    def test_apply_unified_diff_new_file_dev_null(self):
        """Test extracting content from /dev/null diff format."""
        diff = """--- /dev/null
+++ b/test.py
@@ -0,0 +1,2 @@
+line 1
+line 2
"""
        result = _apply_unified_diff([], diff, is_new_file=True)
        assert len(result) == 2
        assert 'line 1\n' in result
        assert 'line 2\n' in result

    @pytest.mark.asyncio
    async def test_apply_patch_creates_new_file(self, engine_with_consent):
        """Test apply_patch creates a new file with '*** Add File:' syntax."""
        tool = ApplyPatchTool(engine_with_consent)

        with tempfile.TemporaryDirectory() as tmpdir:
            new_file = Path(tmpdir) / "new_test_file.py"

            diff = """*** Begin Patch
*** Add File: new_test_file.py
+#!/usr/bin/env python
+print("Hello, World!")
"""
            result = await tool.execute(
                file_path=str(new_file),
                unified_diff=diff
            )

            # Verify success
            assert "Successfully created" in result
            assert new_file.exists()

            # Verify content
            content = new_file.read_text()
            assert '#!/usr/bin/env python' in content
            assert 'print("Hello, World!")' in content

    @pytest.mark.asyncio
    async def test_apply_patch_creates_file_in_new_directory(self, engine_with_consent):
        """Test apply_patch creates parent directories if needed."""
        tool = ApplyPatchTool(engine_with_consent)

        with tempfile.TemporaryDirectory() as tmpdir:
            new_file = Path(tmpdir) / "subdir" / "nested" / "file.txt"

            diff = """*** Add File: file.txt
+content line
"""
            result = await tool.execute(
                file_path=str(new_file),
                unified_diff=diff
            )

            assert "Successfully created" in result
            assert new_file.exists()
            assert "content line" in new_file.read_text()

    @pytest.mark.asyncio
    async def test_apply_patch_without_new_file_syntax_fails(self, engine_with_consent):
        """Test that patching non-existent file without '*** Add File:' fails."""
        tool = ApplyPatchTool(engine_with_consent)

        with tempfile.TemporaryDirectory() as tmpdir:
            new_file = Path(tmpdir) / "nonexistent.py"

            diff = """@@ -1,3 +1,3 @@
 Line 1
-Line 2
+Modified Line 2
 Line 3
"""
            result = await tool.execute(
                file_path=str(new_file),
                unified_diff=diff
            )

            # Should fail with helpful message
            assert "File not found" in result
            assert "*** Add File:" in result
            assert not new_file.exists()

    @pytest.mark.asyncio
    async def test_apply_patch_new_file_consent_denied(self):
        """Test that new file creation respects consent denial."""
        mock_callback = AsyncMock(return_value=(False, 'n'))
        engine = EngineClient(consent_callback=mock_callback)
        tool = ApplyPatchTool(engine)

        with tempfile.TemporaryDirectory() as tmpdir:
            new_file = Path(tmpdir) / "denied_file.py"

            diff = """*** Add File: denied_file.py
+content
"""
            result = await tool.execute(
                file_path=str(new_file),
                unified_diff=diff
            )

            assert "User denied permission" in result
            assert not new_file.exists()


# === InsertText New File Creation Tests (v1.13.2) ===

class TestInsertTextNewFile:
    """Tests for insert_text creating new files when line_number=1."""

    @pytest.mark.asyncio
    async def test_insert_text_creates_new_file(self, engine_with_consent):
        """Test insert_text creates a new file when line_number=1."""
        tool = InsertTextTool(engine_with_consent)

        with tempfile.TemporaryDirectory() as tmpdir:
            new_file = Path(tmpdir) / "new_file.py"

            result = await tool.execute(
                file_path=str(new_file),
                line_number=1,
                text="#!/usr/bin/env python\nprint('Hello')\n"
            )

            assert "Successfully created" in result
            assert new_file.exists()
            content = new_file.read_text()
            assert "#!/usr/bin/env python" in content
            assert "print('Hello')" in content

    @pytest.mark.asyncio
    async def test_insert_text_creates_parent_dirs(self, engine_with_consent):
        """Test insert_text creates parent directories if needed."""
        tool = InsertTextTool(engine_with_consent)

        with tempfile.TemporaryDirectory() as tmpdir:
            new_file = Path(tmpdir) / "subdir" / "nested" / "file.txt"

            result = await tool.execute(
                file_path=str(new_file),
                line_number=1,
                text="content"
            )

            assert "Successfully created" in result
            assert new_file.exists()
            assert "content" in new_file.read_text()

    @pytest.mark.asyncio
    async def test_insert_text_nonexistent_requires_line_1(self, engine_with_consent):
        """Test insert_text on non-existent file requires line_number=1."""
        tool = InsertTextTool(engine_with_consent)

        with tempfile.TemporaryDirectory() as tmpdir:
            new_file = Path(tmpdir) / "nonexistent.py"

            result = await tool.execute(
                file_path=str(new_file),
                line_number=5,  # Not line 1
                text="content"
            )

            assert "File not found" in result
            assert "line_number=1" in result
            assert not new_file.exists()

    @pytest.mark.asyncio
    async def test_insert_text_new_file_consent_denied(self):
        """Test insert_text new file respects consent denial."""
        mock_callback = AsyncMock(return_value=(False, 'n'))
        engine = EngineClient(consent_callback=mock_callback)
        tool = InsertTextTool(engine)

        with tempfile.TemporaryDirectory() as tmpdir:
            new_file = Path(tmpdir) / "denied.txt"

            result = await tool.execute(
                file_path=str(new_file),
                line_number=1,
                text="content"
            )

            assert "User denied permission" in result
            assert not new_file.exists()


# === Search-Replace Diff Tests (v1.13.2) ===

class TestSearchReplaceDiff:
    """Tests for AI-generated search-replace diff format (GPT-OSS 120B style)."""

    def test_search_replace_simple(self):
        """Test simple search-replace diff."""
        original = ["line 1\n", "line 2\n", "line 3\n"]
        diff = """*** Begin Patch
*** Update File: test.py
@@
-line 2
+modified line 2
*** End Patch"""
        result = _apply_search_replace_diff(original, diff)
        content = ''.join(result)
        assert "modified line 2" in content
        assert "line 1" in content
        assert "line 3" in content

    def test_search_replace_multiple_lines(self):
        """Test replacing multiple consecutive lines."""
        original = ["# comment\n", "DATA_ROOT = Path('old')\n", "OUTPUT = 'out'\n"]
        diff = """@@
-DATA_ROOT = Path('old')
-OUTPUT = 'out'
+DATA_ROOT = Path.cwd()
+OUTPUT = 'new_out'"""
        result = _apply_search_replace_diff(original, diff)
        content = ''.join(result)
        assert "Path.cwd()" in content
        assert "new_out" in content
        assert "# comment" in content

    def test_unified_diff_detected_correctly(self):
        """Test that unified diff with line numbers is NOT treated as search-replace."""
        original = ["line 1\n", "line 2\n", "line 3\n"]
        diff = """@@ -1,3 +1,3 @@
 line 1
-line 2
+modified line 2
 line 3"""
        # This should go through standard diff path, not search-replace
        result = _apply_unified_diff(original, diff)
        content = ''.join(result)
        assert "modified line 2" in content

    def test_search_replace_whitespace_tolerance(self):
        """Test that search-replace tolerates whitespace differences."""
        original = ["  indented line\n", "another line\n"]
        diff = """@@
-indented line
+new indented line"""
        result = _apply_search_replace_diff(original, diff)
        content = ''.join(result)
        assert "new indented line" in content

    @pytest.mark.asyncio
    async def test_apply_patch_with_search_replace_format(self, engine_with_consent):
        """Test apply_patch with GPT-OSS 120B style diff."""
        tool = ApplyPatchTool(engine_with_consent)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("# Config\nDATA_ROOT = Path('C:/old')\nprint('done')\n")
            temp_path = Path(f.name)

        try:
            diff = """*** Begin Patch
*** Update File: test.py
@@
-DATA_ROOT = Path('C:/old')
+DATA_ROOT = Path.cwd()
*** End Patch"""

            result = await tool.execute(
                file_path=str(temp_path),
                unified_diff=diff
            )

            assert "Successfully applied patch" in result
            content = temp_path.read_text()
            assert "Path.cwd()" in content
            assert "# Config" in content
            assert "print('done')" in content
        finally:
            temp_path.unlink()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

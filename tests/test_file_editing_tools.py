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
    _normalize_whitespace,
    _collapse_whitespace,
    _replace_hunk,
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


# === Unicode Whitespace Normalization Tests (v1.15.2) ===

class TestUnicodeWhitespaceNormalization:
    """Tests for Unicode whitespace normalization in patch matching (v1.15.2).

    GPT-OSS and other models often output Unicode whitespace characters like:
    - \\xa0 (Non-Breaking Space / NBSP)
    - \\u202f (Narrow No-Break Space / NNBSP)
    - \\u2009 (Thin Space)
    - \\u00a0 (NBSP variant)

    These should match regular ASCII spaces when applying patches.
    """

    def test_normalize_whitespace_nbsp(self):
        """Test normalization of Non-Breaking Space (NBSP)."""
        text = "Price:\xa0100\xa0CHF"  # NBSP characters
        normalized = _normalize_whitespace(text)
        assert normalized == "Price: 100 CHF"

    def test_normalize_whitespace_narrow_nbsp(self):
        """Test normalization of Narrow No-Break Space (NNBSP)."""
        text = "Page\u202f2\u202fTable"  # NNBSP characters
        normalized = _normalize_whitespace(text)
        assert normalized == "Page 2 Table"

    def test_normalize_whitespace_mixed(self):
        """Test normalization of mixed Unicode whitespace."""
        text = "A\xa0B\u202fC\u2009D E"  # NBSP, NNBSP, Thin Space, regular space
        normalized = _normalize_whitespace(text)
        assert normalized == "A B C D E"

    def test_normalize_whitespace_preserves_non_space(self):
        """Test that non-space characters are preserved."""
        text = "Hello\nWorld\tTab"
        normalized = _normalize_whitespace(text)
        assert normalized == "Hello\nWorld\tTab"

    def test_collapse_whitespace_multiple_spaces(self):
        """Test collapsing multiple spaces."""
        text = "too   many    spaces"
        collapsed = _collapse_whitespace(text)
        assert collapsed == "too many spaces"

    def test_collapse_whitespace_with_unicode(self):
        """Test collapsing mixed Unicode whitespace."""
        text = "A\xa0\xa0B\u202f\u202fC"  # Multiple NBSPs and NNBSPs
        collapsed = _collapse_whitespace(text)
        assert collapsed == "A B C"

    def test_replace_hunk_with_nbsp_in_diff(self):
        """Test that diff with NBSP matches file with regular space."""
        # File has regular spaces
        content = "Price: 100 CHF\nTotal: 200 CHF\n"
        # Diff has NBSP (model hallucinated NBSP)
        old_lines = ["Price:\xa0100\xa0CHF"]  # NBSP
        new_lines = ["Price: 150 CHF"]
        result = _replace_hunk(content, old_lines, new_lines)
        assert "Price: 150 CHF" in result
        assert "Total: 200 CHF" in result

    def test_replace_hunk_with_nnbsp_in_diff(self):
        """Test that diff with NNBSP matches file with regular space."""
        # File has regular spaces
        content = "Page 2 Table 1\nSome content\n"
        # Diff has NNBSP (common in GPT-OSS outputs)
        old_lines = ["Page\u202f2\u202fTable\u202f1"]  # NNBSP
        new_lines = ["Page 2 - Table 1 (Updated)"]
        result = _replace_hunk(content, old_lines, new_lines)
        assert "Page 2 - Table 1 (Updated)" in result
        assert "Some content" in result

    def test_replace_hunk_with_mixed_unicode_whitespace(self):
        """Test matching with various Unicode whitespace variants."""
        # File has regular spaces
        content = "A B C D\nE F G H\n"
        # Diff has mixed Unicode whitespace
        old_lines = ["A\xa0B\u202fC\u2009D"]  # NBSP, NNBSP, Thin Space
        new_lines = ["A-B-C-D"]
        result = _replace_hunk(content, old_lines, new_lines)
        assert "A-B-C-D" in result
        assert "E F G H" in result

    def test_replace_hunk_exact_match_preferred(self):
        """Test that exact match is used when available."""
        content = "exact match here\n"
        old_lines = ["exact match here"]
        new_lines = ["replaced"]
        result = _replace_hunk(content, old_lines, new_lines)
        assert result == "replaced\n"

    def test_replace_hunk_crlf_handling(self):
        """Test handling of CRLF line endings."""
        content = "line 1\r\nline 2\r\n"
        old_lines = ["line 1", "line 2"]
        new_lines = ["modified 1", "modified 2"]
        result = _replace_hunk(content, old_lines, new_lines)
        assert "modified 1" in result
        assert "modified 2" in result

    def test_replace_hunk_collapsed_whitespace_fallback(self):
        """Test aggressive collapsed whitespace matching as last resort."""
        content = "too   many    spaces\n"
        old_lines = ["too many spaces"]  # Diff has single spaces
        new_lines = ["fixed spacing"]
        result = _replace_hunk(content, old_lines, new_lines)
        assert "fixed spacing" in result

    @pytest.mark.asyncio
    async def test_apply_patch_with_unicode_whitespace(self, engine_with_consent):
        """Integration test: apply_patch with Unicode whitespace in diff."""
        tool = ApplyPatchTool(engine_with_consent)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
            # File with regular spaces
            f.write("# Report\n\nPage 2 Table 1\n\n| Col A | Col B |\n")
            temp_path = Path(f.name)

        try:
            # Diff with NNBSP (common GPT-OSS output)
            diff = """*** Begin Patch
*** Update File: report.md
@@
-Page\u202f2\u202fTable\u202f1
+**Page 2 Table 1** - Updated
*** End Patch"""

            result = await tool.execute(
                file_path=str(temp_path),
                unified_diff=diff
            )

            assert "Successfully applied patch" in result
            content = temp_path.read_text()
            assert "**Page 2 Table 1** - Updated" in content
            assert "# Report" in content
            assert "| Col A | Col B |" in content
        finally:
            temp_path.unlink()


class TestAtomicReplaceRetry:
    """Tests for _atomic_replace retry logic on Windows file lock errors."""

    def test_succeeds_on_first_attempt(self, tmp_path):
        """Normal case: replace succeeds on first try."""
        from ppxai.engine.tools.builtin.editor import _atomic_replace

        target = tmp_path / "target.txt"
        target.write_text("old content")

        temp = tmp_path / "target.txt.tmp"
        temp.write_text("new content")

        _atomic_replace(temp, target)

        assert target.read_text() == "new content"
        assert not temp.exists()

    def test_retries_on_permission_error(self, tmp_path):
        """Retries on PermissionError and succeeds on subsequent attempt."""
        from ppxai.engine.tools.builtin.editor import _atomic_replace

        target = tmp_path / "target.txt"
        target.write_text("old content")

        temp = tmp_path / "target.txt.tmp"
        temp.write_text("new content")

        call_count = 0
        original_replace = Path.replace

        def mock_replace(self_path, target_path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PermissionError("[WinError 5] Access is denied")
            return original_replace(self_path, target_path)

        with patch.object(Path, 'replace', mock_replace):
            with patch('ppxai.engine.tools.builtin.editor.sys') as mock_sys:
                mock_sys.platform = 'win32'
                _atomic_replace(temp, target)

        assert target.read_text() == "new content"
        assert call_count == 2

    def test_raises_after_max_retries(self, tmp_path):
        """Raises PermissionError after exhausting all retries."""
        from ppxai.engine.tools.builtin.editor import _atomic_replace

        target = tmp_path / "target.txt"
        target.write_text("old content")

        temp = tmp_path / "target.txt.tmp"
        temp.write_text("new content")

        def always_fail(self_path, target_path):
            raise PermissionError("[WinError 5] Access is denied")

        with patch.object(Path, 'replace', always_fail):
            with patch('ppxai.engine.tools.builtin.editor.sys') as mock_sys:
                mock_sys.platform = 'win32'
                with pytest.raises(PermissionError):
                    _atomic_replace(temp, target)

        # Temp file should be cleaned up on failure
        assert not temp.exists()

    def test_no_retry_on_non_windows(self, tmp_path):
        """On non-Windows, PermissionError is raised immediately without retry."""
        from ppxai.engine.tools.builtin.editor import _atomic_replace

        target = tmp_path / "target.txt"
        target.write_text("old content")

        temp = tmp_path / "target.txt.tmp"
        temp.write_text("new content")

        call_count = 0

        def always_fail(self_path, target_path):
            nonlocal call_count
            call_count += 1
            raise PermissionError("Permission denied")

        with patch.object(Path, 'replace', always_fail):
            with patch('ppxai.engine.tools.builtin.editor.sys') as mock_sys:
                mock_sys.platform = 'linux'
                with pytest.raises(PermissionError):
                    _atomic_replace(temp, target)

        assert call_count == 1  # No retry on Linux


class TestBOMHandling:
    """Tests for BOM (Byte Order Mark) handling in editor tools (v1.16.0).

    PowerShell's Set-Content -Encoding UTF8 adds a BOM (\\ufeff) prefix.
    Editor tools must strip BOM when reading so that search/replace
    operations work without models having to account for invisible characters.
    """

    @pytest.fixture
    def bom_file(self, tmp_path):
        """Create a file with UTF-8 BOM prefix."""
        path = tmp_path / "bom_test.css"
        # Write with explicit BOM byte
        path.write_bytes(b'\xef\xbb\xbf/* Spider-Man Theme */\nbody { color: red; }\n')
        return path

    @pytest.fixture
    def engine(self):
        """Create engine with auto-consent."""
        engine = EngineClient(consent_callback=AsyncMock(return_value=(True, 'y')))
        return engine

    @pytest.mark.asyncio
    async def test_replace_block_ignores_bom(self, bom_file, engine):
        """replace_block should find text even when file has BOM prefix."""
        engine._working_dir = str(bom_file.parent)
        tool = ReplaceBlockTool(engine)
        result = await tool.execute(
            file_path=str(bom_file),
            search="/* Spider-Man Theme */",
            replace="/* Maverick Theme */",
        )
        assert "Successfully replaced" in result
        # Verify BOM is NOT reintroduced in the output
        content = bom_file.read_bytes()
        assert not content.startswith(b'\xef\xbb\xbf')
        assert b"Maverick Theme" in content

    @pytest.mark.asyncio
    async def test_apply_patch_ignores_bom(self, bom_file, engine):
        """apply_patch should work on files with BOM prefix."""
        engine._working_dir = str(bom_file.parent)
        tool = ApplyPatchTool(engine)
        diff = (
            "*** Begin Patch ***\n"
            "--- a/bom_test.css\n"
            "+++ b/bom_test.css\n"
            "@@ -1,2 +1,2 @@\n"
            "-/* Spider-Man Theme */\n"
            "+/* Top Gun Theme */\n"
            " body { color: red; }\n"
            "*** End Patch ***\n"
        )
        result = await tool.execute(file_path=str(bom_file), unified_diff=diff)
        assert "Successfully applied" in result
        content = bom_file.read_text(encoding='utf-8')
        assert "Top Gun Theme" in content

    @pytest.mark.asyncio
    async def test_insert_text_ignores_bom(self, bom_file, engine):
        """insert_text should work on files with BOM prefix."""
        engine._working_dir = str(bom_file.parent)
        tool = InsertTextTool(engine)
        result = await tool.execute(
            file_path=str(bom_file),
            line_number=1,
            text="/* Added line */\n",
        )
        assert "Successfully inserted" in result

    @pytest.mark.asyncio
    async def test_delete_lines_ignores_bom(self, bom_file, engine):
        """delete_lines should work on files with BOM prefix."""
        engine._working_dir = str(bom_file.parent)
        tool = DeleteLinesTool(engine)
        result = await tool.execute(
            file_path=str(bom_file),
            start_line=1,
            end_line=1,
        )
        assert "Successfully deleted" in result
        content = bom_file.read_text(encoding='utf-8')
        assert "Spider-Man" not in content

    @pytest.mark.asyncio
    async def test_read_file_strips_bom(self, bom_file):
        """read_file should return content without BOM character."""
        from ppxai.engine.tools.builtin.filesystem import ReadFileTool
        engine = EngineClient(consent_callback=AsyncMock(return_value=(True, 'y')))
        engine._working_dir = str(bom_file.parent)
        tool = ReadFileTool(engine)
        result = await tool.execute(filepath=str(bom_file))
        # BOM should NOT appear in returned content
        assert not result.startswith('\ufeff')
        assert result.startswith("/* Spider-Man Theme */")


class TestCheckpointRegistration:
    """Tests for checkpoint file registration from editor tools (v1.16.0).

    Editor tools should call register_file() on the checkpoint manager
    before writing, so file-based checkpoints capture original content.
    """

    @pytest.fixture
    def engine_with_checkpoint(self, tmp_path):
        """Create engine with a mock checkpoint manager."""
        engine = EngineClient(consent_callback=AsyncMock(return_value=(True, 'y')))
        engine._working_dir = str(tmp_path)

        # Create mock checkpoint manager
        mock_mgr = MagicMock()
        mock_mgr.register_file = MagicMock()
        engine._checkpoint_manager = mock_mgr
        return engine, mock_mgr

    @pytest.mark.asyncio
    async def test_replace_block_registers_file(self, tmp_path, engine_with_checkpoint):
        """replace_block calls register_file before writing."""
        engine, mock_mgr = engine_with_checkpoint
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world\n")

        tool = ReplaceBlockTool(engine)
        await tool.execute(file_path=str(test_file), search="hello", replace="goodbye")
        mock_mgr.register_file.assert_called_once_with(test_file)

    @pytest.mark.asyncio
    async def test_apply_patch_registers_file(self, tmp_path, engine_with_checkpoint):
        """apply_patch calls register_file before writing."""
        engine, mock_mgr = engine_with_checkpoint
        test_file = tmp_path / "test.txt"
        test_file.write_text("line 1\n")

        tool = ApplyPatchTool(engine)
        diff = (
            "*** Begin Patch ***\n"
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1 +1 @@\n"
            "-line 1\n"
            "+line 2\n"
            "*** End Patch ***\n"
        )
        await tool.execute(file_path=str(test_file), unified_diff=diff)
        mock_mgr.register_file.assert_called_once_with(test_file)

    @pytest.mark.asyncio
    async def test_insert_text_registers_file(self, tmp_path, engine_with_checkpoint):
        """insert_text calls register_file before writing."""
        engine, mock_mgr = engine_with_checkpoint
        test_file = tmp_path / "test.txt"
        test_file.write_text("existing\n")

        tool = InsertTextTool(engine)
        await tool.execute(file_path=str(test_file), line_number=1, text="new line\n")
        mock_mgr.register_file.assert_called_once_with(test_file)

    @pytest.mark.asyncio
    async def test_delete_lines_registers_file(self, tmp_path, engine_with_checkpoint):
        """delete_lines calls register_file before writing."""
        engine, mock_mgr = engine_with_checkpoint
        test_file = tmp_path / "test.txt"
        test_file.write_text("line 1\nline 2\n")

        tool = DeleteLinesTool(engine)
        await tool.execute(file_path=str(test_file), start_line=1, end_line=1)
        mock_mgr.register_file.assert_called_once_with(test_file)

    @pytest.mark.asyncio
    async def test_no_checkpoint_manager_no_error(self, tmp_path):
        """Editor tools work fine when checkpoint manager is None."""
        engine = EngineClient(consent_callback=AsyncMock(return_value=(True, 'y')))
        engine._working_dir = str(tmp_path)
        engine._checkpoint_manager = None

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world\n")

        tool = ReplaceBlockTool(engine)
        result = await tool.execute(
            file_path=str(test_file), search="hello", replace="goodbye"
        )
        assert "Successfully replaced" in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

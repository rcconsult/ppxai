"""Regression tests for /ls command file-path support.

Interactive Phase 2.1a testing surfaced a UX gap: `/ls <file>` returned
an error `Not a directory` instead of showing the file's entry the way
shell `ls file.txt` does. Users hit this when pasting paths from /save
output or tab completion.

v1.17.4: `/ls <file>` now shows a single-row listing for the file,
matching shell semantics. `/ls <missing>` reports "No such file or
directory" instead of the less precise "Not a directory".
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ppxai.commands.results import ResultStatus
from ppxai.commands.utility import handle_ls


@pytest.fixture
def context(tmp_path) -> Any:
    """Minimal CommandContext stub anchored at tmp_path."""
    class _FakeEngine:
        def __init__(self, wd: str) -> None:
            self._wd = wd

        def get_working_dir(self) -> str:
            return self._wd

    return SimpleNamespace(engine_client=_FakeEngine(str(tmp_path)))


@pytest.fixture
def populated_dir(tmp_path):
    """A tmp dir with a few predictable entries."""
    (tmp_path / "file1.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "file2.md").write_text("# hi", encoding="utf-8")
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.py").write_text("print(1)", encoding="utf-8")
    return tmp_path


class TestLsDirectory:
    def test_ls_current_dir_lists_all_entries(self, context, populated_dir):
        result = handle_ls(context, "")
        assert result.status == ResultStatus.SUCCESS
        names = {row[0] for row in result.rows}
        assert "file1.txt" in names
        assert "file2.md" in names
        # Directory rows get a trailing slash.
        assert "subdir/" in names

    def test_ls_absolute_directory(self, context, populated_dir):
        result = handle_ls(context, str(populated_dir / "subdir"))
        assert result.status == ResultStatus.SUCCESS
        names = {row[0] for row in result.rows}
        assert "nested.py" in names


class TestLsFile:
    """v1.17.4: /ls <file> shows a single-row entry (shell ls semantics)."""

    def test_ls_single_file_shows_entry(self, context, populated_dir):
        target = populated_dir / "file1.txt"
        result = handle_ls(context, str(target))

        assert result.status == ResultStatus.SUCCESS
        assert "1 file" in result.message
        assert str(target) in result.message
        # Exactly one row for the target file.
        assert len(result.rows) == 1
        row = result.rows[0]
        assert row[0] == "file1.txt"
        # Size column is human-readable bytes, not "-".
        assert row[1] != "-"
        assert row[2]  # modified column populated

    def test_ls_relative_file_path_resolves_against_working_dir(
        self, context, populated_dir
    ):
        # Relative to working_dir (tmp_path) — should find file2.md.
        result = handle_ls(context, "file2.md")
        assert result.status == ResultStatus.SUCCESS
        assert len(result.rows) == 1
        assert result.rows[0][0] == "file2.md"

    def test_ls_nested_file_via_subdir(self, context, populated_dir):
        result = handle_ls(context, "subdir/nested.py")
        assert result.status == ResultStatus.SUCCESS
        assert len(result.rows) == 1
        assert result.rows[0][0] == "nested.py"


class TestLsErrorCases:
    def test_ls_missing_path_says_no_such_file(self, context, tmp_path):
        result = handle_ls(context, str(tmp_path / "ghost.txt"))
        assert result.status == ResultStatus.ERROR
        # New error message distinguishes missing paths from non-directory paths.
        assert "No such file or directory" in result.message
        # Suggestion still present.
        assert result.suggestions

    def test_ls_absolute_missing_path(self, context):
        result = handle_ls(context, "/definitely/does/not/exist/anywhere")
        assert result.status == ResultStatus.ERROR
        assert "No such file or directory" in result.message


class TestLsFlags:
    def test_hidden_flag_skipped_by_default(self, context, populated_dir):
        (populated_dir / ".hidden").write_text("secret", encoding="utf-8")
        result = handle_ls(context, "")
        names = {row[0] for row in result.rows}
        assert ".hidden" not in names

    def test_hidden_flag_shows_dotfiles(self, context, populated_dir):
        (populated_dir / ".hidden").write_text("secret", encoding="utf-8")
        result = handle_ls(context, "-a")
        names = {row[0] for row in result.rows}
        assert ".hidden" in names

    def test_hidden_flag_with_file_target(self, context, populated_dir):
        # -a should still work even when the target is a file — no-op
        # in that case because the single-file path doesn't do filtering,
        # but it shouldn't error.
        target = populated_dir / "file1.txt"
        result = handle_ls(context, f"-a {target}")
        assert result.status == ResultStatus.SUCCESS
        assert len(result.rows) == 1

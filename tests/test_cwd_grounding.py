"""Tests pinning the v1.18.4 cwd-grounding contract.

Background: v1.18.x put significant work into AppState/UI/client sync
of `working_dir` (state-sync determinism). Despite that, the LLM kept
hallucinating the working directory in summaries because:

  1. The system prompt DOES include `**Current Working Directory:** /path`
     (manager.py:357), but the LLM doesn't always obey it.
  2. Tool outputs themselves had no cwd header, so the LLM had to
     paraphrase from memory and confabulated paths.

Defense-in-depth: every cwd-relevant tool now emits its resolved path
in the output, so the model summarizes from observable facts instead
of guessing. These tests pin the headers so a refactor can't silently
remove them.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ppxai.engine.tools.builtin.display import DisplayFileTool
from ppxai.engine.tools.builtin.editor import (
    ApplyPatchTool,
    DeleteLinesTool,
    InsertTextTool,
    ReplaceBlockTool,
)
from ppxai.engine.tools.builtin.filesystem import (
    ListDirectoryTool,
    SearchFilesTool,
)
from ppxai.engine.tools.builtin.shell import ShellExecuteTool


@pytest.fixture
def stub_engine(tmp_path):
    eng = MagicMock()
    eng.get_working_dir = MagicMock(return_value=str(tmp_path))
    eng.set_working_dir = MagicMock()
    eng.request_shell_consent = AsyncMock(return_value=True)
    eng.register_subprocess = MagicMock()
    eng.unregister_subprocess = MagicMock()
    eng._agent_edited_files = set()
    return eng


# ---------------------------------------------------------------------------
# list_directory — pinned by ee90bff4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_directory_header_grounds_in_resolved_path(
    stub_engine, tmp_path
):
    (tmp_path / "x.txt").write_text("")
    out = await ListDirectoryTool(stub_engine).execute()
    assert out.startswith(f"Listing of {tmp_path}:")


# ---------------------------------------------------------------------------
# search_files — both zero-match and match paths must include the
# searched directory in the output header.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_files_zero_match_includes_searched_dir(
    stub_engine, tmp_path
):
    out = await SearchFilesTool(stub_engine).execute(pattern="*.nonexistent")
    assert str(tmp_path) in out
    assert "no matches" in out.lower()


@pytest.mark.asyncio
async def test_search_files_match_includes_searched_dir(
    stub_engine, tmp_path
):
    (tmp_path / "match.py").write_text("")
    out = await SearchFilesTool(stub_engine).execute(pattern="*.py")
    assert str(tmp_path) in out
    assert "match.py" in out


# ---------------------------------------------------------------------------
# execute_shell_command — the v1.18.4 [cwd: /path] header.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shell_output_starts_with_cwd_header(stub_engine, tmp_path):
    out = await ShellExecuteTool(stub_engine).execute(command="echo hello")
    assert out.startswith(f"[cwd: {tmp_path}]\n"), (
        f"Shell output must start with cwd header. Got first 80 chars:\n"
        f"{out[:80]!r}"
    )
    assert "hello" in out


@pytest.mark.asyncio
async def test_shell_nonzero_exit_includes_exit_code_in_header(
    stub_engine, tmp_path
):
    out = await ShellExecuteTool(stub_engine).execute(command="false")
    assert out.startswith(f"[cwd: {tmp_path}, exit: 1]\n"), (
        f"Non-zero exit header missing exit code. Got: {out[:100]!r}"
    )


@pytest.mark.asyncio
async def test_shell_stderr_only_command_has_separator(
    stub_engine, tmp_path
):
    out = await ShellExecuteTool(stub_engine).execute(
        command="echo 'oops' 1>&2"
    )
    assert "--- stderr ---" in out
    assert "oops" in out


# ---------------------------------------------------------------------------
# display_file — resolved path in message, not basename.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_display_file_message_uses_resolved_path(
    stub_engine, tmp_path
):
    (tmp_path / "doc.md").write_text("# hi\n")
    out = await DisplayFileTool(stub_engine).execute(filepath="doc.md")
    expected_path = (tmp_path / "doc.md").resolve()
    assert str(expected_path) in out


# ---------------------------------------------------------------------------
# editor tools — success messages reference the resolved absolute
# path, not the input relpath.
# ---------------------------------------------------------------------------


def _consent_engine(tmp_path):
    eng = MagicMock()
    eng.get_working_dir = MagicMock(return_value=str(tmp_path))
    eng.request_file_edit_consent = AsyncMock(return_value=True)
    eng._agent_edited_files = set()
    eng._auto_commit_enabled = False
    return eng


@pytest.mark.asyncio
async def test_apply_patch_success_message_uses_resolved_path(tmp_path):
    eng = _consent_engine(tmp_path)
    # Pre-create the file so apply_patch (unified diff) can hunk-edit it.
    target = tmp_path / "f.txt"
    target.write_text("alpha\nbeta\ngamma\n")
    diff = (
        "--- a/f.txt\n"
        "+++ b/f.txt\n"
        "@@ -1,3 +1,3 @@\n"
        " alpha\n"
        "-beta\n"
        "+BETA\n"
        " gamma\n"
    )
    out = await ApplyPatchTool(eng).execute(
        file_path="f.txt",
        unified_diff=diff,
    )
    assert str(target.resolve()) in out, (
        f"apply_patch must report resolved path. Got: {out!r}"
    )


@pytest.mark.asyncio
async def test_replace_block_success_message_uses_resolved_path(tmp_path):
    eng = _consent_engine(tmp_path)
    target = tmp_path / "f.txt"
    target.write_text("alpha\nbeta\ngamma\n")
    out = await ReplaceBlockTool(eng).execute(
        file_path="f.txt",
        search="beta",
        replace="BETA",
    )
    assert str(target.resolve()) in out


@pytest.mark.asyncio
async def test_insert_text_success_message_uses_resolved_path(tmp_path):
    eng = _consent_engine(tmp_path)
    target = tmp_path / "g.txt"
    target.write_text("line1\nline2\n")
    out = await InsertTextTool(eng).execute(
        file_path="g.txt",
        line_number=2,
        text="inserted\n",
    )
    assert str(target.resolve()) in out


@pytest.mark.asyncio
async def test_delete_lines_success_message_uses_resolved_path(tmp_path):
    eng = _consent_engine(tmp_path)
    target = tmp_path / "h.txt"
    target.write_text("a\nb\nc\nd\n")
    out = await DeleteLinesTool(eng).execute(
        file_path="h.txt",
        start_line=2,
        end_line=3,
    )
    assert str(target.resolve()) in out


# ---------------------------------------------------------------------------
# System prompt sentinel — verifies the v1.18.x AppState→prompt sync
# invariant programmatically.
# ---------------------------------------------------------------------------


def test_tools_prompt_includes_current_working_directory():
    from ppxai.engine.tools.base import BaseTool
    from ppxai.engine.tools.manager import ToolManager

    class _Stub(BaseTool):
        def __init__(self):
            self.name = "stub"
            self.description = "stub"
            self.parameters = {"type": "object", "properties": {}, "required": []}
        async def execute(self, **kwargs):
            return "ok"

    tm = ToolManager()
    tm.register_tool(_Stub())
    prompt = tm.get_tools_prompt(working_dir="/some/path/after/cd")

    assert "/some/path/after/cd" in prompt
    assert "**Current Working Directory:**" in prompt
    # Strengthened instruction added v1.18.4.
    assert "ONLY source of truth" in prompt


def test_tools_prompt_omits_cwd_when_none():
    from ppxai.engine.tools.base import BaseTool
    from ppxai.engine.tools.manager import ToolManager

    class _Stub(BaseTool):
        def __init__(self):
            self.name = "stub"
            self.description = "stub"
            self.parameters = {"type": "object", "properties": {}, "required": []}
        async def execute(self, **kwargs):
            return "ok"

    tm = ToolManager()
    tm.register_tool(_Stub())
    prompt = tm.get_tools_prompt(working_dir=None)
    assert "**Current Working Directory:**" not in prompt

"""Tests for ppxai.commands.display.handle_edit (v1.18.1).

Covers the three branches of the /edit handler:

1. **Existing file** → emits `open_editor` side-effect with line/col.
2. **Missing file, no flag** → returns `prompt_quick_pick` so the
   client can confirm creation.
3. **Missing file with `--create`** → mkdir + touch + emit
   `open_editor`. The `--create` flag is what the user's quick-pick
   "Create new file" choice maps to (Approach 1 from the ADR Q3
   discussion: quick-pick choices ARE the resolved next args).

The handler is invoked directly through `CommandFactory` with a
mock engine, not through HTTP — the envelope shape is covered by
`test_command_envelope.py`. This file exercises the handler logic.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ppxai.commands.context import ServerCommandContext
from ppxai.commands.display import handle_edit
from ppxai.commands.factory import CommandFactory
from ppxai.commands.results import (
    ErrorResult,
    FileViewResult,
    NotificationResult,
    ResultStatus,
    SideEffectKind,
)

# ---------------------------------------------------------------------------
# Handler — branches
# ---------------------------------------------------------------------------

@pytest.fixture
def engine_with_cwd(tmp_path):
    """Mock engine_client that returns tmp_path as working_dir."""
    engine = MagicMock()
    engine.get_working_dir.return_value = str(tmp_path)
    return engine


@pytest.fixture
def context(engine_with_cwd):
    return ServerCommandContext(engine_with_cwd)


class TestHandleEditExisting:
    """The file exists — handler emits open_editor."""

    def test_returns_fileviewresult(self, context, tmp_path):
        target = tmp_path / "hello.py"
        target.write_text("print('hi')\n", encoding="utf-8")
        result = handle_edit(context, "hello.py")
        assert isinstance(result, FileViewResult)
        assert result.success
        assert result.read_only is False

    def test_emits_open_editor_side_effect(self, context, tmp_path):
        target = tmp_path / "hello.py"
        target.write_text("print('hi')\n", encoding="utf-8")
        result = handle_edit(context, "hello.py")
        kinds = [se.kind for se in result.side_effects]
        assert SideEffectKind.OPEN_EDITOR in kinds
        se = next(s for s in result.side_effects if s.kind == SideEffectKind.OPEN_EDITOR)
        assert se.payload["filepath"] == str(target.resolve())
        # No line/col when not specified.
        assert "line" not in se.payload
        assert "column" not in se.payload

    def test_passes_through_line_and_column(self, context, tmp_path):
        target = tmp_path / "hello.py"
        target.write_text("print('hi')\n", encoding="utf-8")
        result = handle_edit(context, "hello.py:10:5")
        se = next(s for s in result.side_effects if s.kind == SideEffectKind.OPEN_EDITOR)
        assert se.payload["line"] == 10
        assert se.payload["column"] == 5

    def test_rejects_directory(self, context, tmp_path):
        result = handle_edit(context, ".")
        assert isinstance(result, ErrorResult)
        assert result.failed


class TestHandleEditMissingNoFlag:
    """The file is missing AND no --create flag — handler emits
    prompt_quick_pick so the client can confirm creation."""

    def test_returns_notification_result(self, context):
        result = handle_edit(context, "nonexistent.py")
        assert isinstance(result, NotificationResult)
        assert result.status == ResultStatus.INFO

    def test_emits_prompt_quick_pick(self, context):
        result = handle_edit(context, "nonexistent.py")
        kinds = [se.kind for se in result.side_effects]
        assert SideEffectKind.PROMPT_QUICK_PICK in kinds

    def test_quick_pick_resume_targets_edit_with_create_flag(self, context):
        """The first item's value is `--create <args>` — re-issuing
        POST /command/edit with that string takes the create branch
        on the second pass. Per ADR Q3 (b): no server-side state."""
        result = handle_edit(context, "nonexistent.py")
        se = next(s for s in result.side_effects
                  if s.kind == SideEffectKind.PROMPT_QUICK_PICK)
        assert se.payload["command_to_resume"] == "edit"
        items = se.payload["items"]
        assert len(items) == 2
        # First item: create
        assert "Create" in items[0]["label"]
        assert items[0]["value"] == "--create nonexistent.py"
        # Second item: cancel
        assert items[1]["label"] == "Cancel"

    def test_quick_pick_preserves_line_col_in_resume_value(self, context):
        """If the user typed `/edit foo.py:42:5` and confirms create,
        the resume value must keep the location — opening the new file
        AT line 42 col 5 is what the user asked for."""
        result = handle_edit(context, "foo.py:42:5")
        se = next(s for s in result.side_effects
                  if s.kind == SideEffectKind.PROMPT_QUICK_PICK)
        assert se.payload["items"][0]["value"] == "--create foo.py:42:5"


class TestHandleEditCreate:
    """The user passed --create (typically via the quick-pick resume).
    Handler creates parent dirs + empty file, then emits open_editor."""

    def test_creates_file(self, context, tmp_path):
        result = handle_edit(context, "--create newfile.py")
        target = tmp_path / "newfile.py"
        assert target.exists()
        assert target.is_file()
        assert target.read_text() == ""
        # Returns FileViewResult, not NotificationResult.
        assert isinstance(result, FileViewResult)
        assert result.success

    def test_creates_parent_dirs(self, context, tmp_path):
        handle_edit(context, "--create deeply/nested/dir/new.py")
        target = tmp_path / "deeply" / "nested" / "dir" / "new.py"
        assert target.exists()
        assert target.parent.is_dir()

    def test_emits_open_editor_after_create(self, context, tmp_path):
        result = handle_edit(context, "--create new.py")
        kinds = [se.kind for se in result.side_effects]
        assert SideEffectKind.OPEN_EDITOR in kinds

    def test_create_with_line_col(self, context, tmp_path):
        result = handle_edit(context, "--create new.py:10:5")
        target = tmp_path / "new.py"
        assert target.exists()
        se = next(s for s in result.side_effects
                  if s.kind == SideEffectKind.OPEN_EDITOR)
        assert se.payload["line"] == 10
        assert se.payload["column"] == 5

    def test_create_alone_is_an_error(self, context):
        """`--create` with no path is malformed."""
        result = handle_edit(context, "--create")
        assert isinstance(result, ErrorResult)


# ---------------------------------------------------------------------------
# Factory registration
# ---------------------------------------------------------------------------

class TestEditCommandRegistered:
    def test_edit_in_factory(self):
        spec = CommandFactory.get("edit")
        assert spec is not None
        assert spec.name == "edit"
        assert spec.handler is handle_edit


# ---------------------------------------------------------------------------
# Empty / usage
# ---------------------------------------------------------------------------

class TestHandleEditUsage:
    def test_empty_args_returns_usage(self, context):
        result = handle_edit(context, "")
        assert isinstance(result, ErrorResult)
        assert "Usage" in result.message


# ---------------------------------------------------------------------------
# @query fuzzy search
# ---------------------------------------------------------------------------

class TestHandleEditAtQuery:
    def test_zero_matches_returns_error(self, context, tmp_path):
        result = handle_edit(context, "@nonexistent")
        assert isinstance(result, ErrorResult)

    def test_single_match_proceeds_to_edit(self, context, tmp_path):
        target = tmp_path / "config.py"
        target.write_text("x = 1\n", encoding="utf-8")
        result = handle_edit(context, "@config")
        # Single match → handler edits that file
        from ppxai.commands.results import FileViewResult
        assert isinstance(result, FileViewResult)
        kinds = [se.kind for se in result.side_effects]
        assert SideEffectKind.OPEN_EDITOR in kinds

    def test_multiple_matches_emit_quick_pick_for_edit(self, context, tmp_path):
        (tmp_path / "config.py").write_text("a", encoding="utf-8")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        result = handle_edit(context, "@config")
        kinds = [se.kind for se in result.side_effects]
        assert SideEffectKind.PROMPT_QUICK_PICK in kinds
        se = next(s for s in result.side_effects
                  if s.kind == SideEffectKind.PROMPT_QUICK_PICK)
        # Resume target is /edit, not /show
        assert se.payload["command_to_resume"] == "edit"

    def test_at_query_with_create_flag_is_an_error(self, context, tmp_path):
        """@search and --create are incompatible: a search finds an
        existing file; --create assumes a literal new path."""
        result = handle_edit(context, "--create @config")
        assert isinstance(result, ErrorResult)
        assert "@search" in result.message or "combine" in result.message.lower()

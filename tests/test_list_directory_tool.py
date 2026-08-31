"""Tests for ListDirectoryTool — particularly the v1.18.4 path-header fix.

Reported 2026-05-04 from the web UI: after `/cd ppxai_demo`, asking
the model "ls" produced "/Users/rado/git/exps contains the files and
folders listed above" — the PARENT of the actual working dir. Root
cause: the tool returned only item names (e.g. `DIR foo\nFILE bar`),
no path header. The model called the tool with `path="."` (default)
and had no way to know which directory it just listed, so it
confabulated a path in its response.

Fix: prefix the resolved path in the tool's output. The model now
sees `Listing of /Users/rado/git/exps/ppxai_demo:\nDIR foo\n...` and
its summary can quote the actual path verbatim instead of guessing.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ppxai.engine.tools.builtin.filesystem import ListDirectoryTool


@pytest.fixture
def stub_engine(tmp_path):
    """Stub engine whose working_dir is a freshly-created tmp dir."""
    eng = MagicMock()
    eng.get_working_dir = MagicMock(return_value=str(tmp_path))
    return eng


# ---------------------------------------------------------------------------
# Path header — the v1.18.4 fix.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_path_uses_engine_working_dir_with_header(
    stub_engine, tmp_path
):
    """When path is omitted, the tool uses engine.get_working_dir()
    AND echoes that path in the output header."""
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta").mkdir()

    tool = ListDirectoryTool(stub_engine)
    out = await tool.execute()

    assert out.startswith(f"Listing of {tmp_path}:"), (
        f"Output must start with path header. Got:\n{out}"
    )
    # Items follow the header. (Directory marker is "DIR " — note
    # trailing space — to align column widths against "FILE".)
    assert "FILE alpha.txt" in out
    assert "DIR  beta" in out


@pytest.mark.asyncio
async def test_long_format_header(stub_engine, tmp_path):
    """`format='long'` gets a long-listing-specific header so the
    model can quote it accurately."""
    (tmp_path / "x.txt").write_text("x")

    tool = ListDirectoryTool(stub_engine)
    out = await tool.execute(format="long")

    assert out.startswith(f"Long-format listing of {tmp_path}:")
    # Long format includes permissions like '-rw-r--r--'
    assert "x.txt" in out


@pytest.mark.asyncio
async def test_explicit_relative_path_resolved_against_working_dir(
    stub_engine, tmp_path
):
    """A relative path is resolved against engine.get_working_dir(),
    and the resolved (absolute) path appears in the header."""
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "inner.txt").write_text("i")

    tool = ListDirectoryTool(stub_engine)
    out = await tool.execute(path="subdir")

    # Header carries the resolved absolute path, not the relpath.
    assert str(sub.resolve()) in out
    assert out.startswith(f"Listing of {sub.resolve()}:")
    assert "FILE inner.txt" in out


@pytest.mark.asyncio
async def test_absolute_path_used_as_is(stub_engine, tmp_path):
    sub = tmp_path / "abs_sub"
    sub.mkdir()
    (sub / "file.txt").write_text("ok")

    tool = ListDirectoryTool(stub_engine)
    out = await tool.execute(path=str(sub))

    assert out.startswith(f"Listing of {sub.resolve()}:")
    assert "FILE file.txt" in out


@pytest.mark.asyncio
async def test_empty_directory_includes_header_and_marker(
    stub_engine, tmp_path
):
    """An empty directory still emits the path header so the model
    can name the location it just listed; followed by '(empty)'."""
    tool = ListDirectoryTool(stub_engine)
    out = await tool.execute()

    assert out.startswith(f"Listing of {tmp_path}:")
    assert "(empty)" in out


# ---------------------------------------------------------------------------
# Truncation behavior — preserved from pre-v1.18.4.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_more_than_100_items_truncated_with_marker(
    stub_engine, tmp_path
):
    for i in range(120):
        (tmp_path / f"f{i:03d}.txt").write_text("")

    tool = ListDirectoryTool(stub_engine)
    out = await tool.execute()

    assert out.startswith(f"Listing of {tmp_path}:")
    assert "... (20 more items)" in out


# ---------------------------------------------------------------------------
# Error paths — header NOT emitted when the directory doesn't exist.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nonexistent_path_returns_error(stub_engine, tmp_path):
    tool = ListDirectoryTool(stub_engine)
    out = await tool.execute(path="this/path/does/not/exist")

    assert out.startswith("Error:")
    assert "not found" in out.lower() or "no such" in out.lower()


@pytest.mark.asyncio
async def test_path_pointing_at_a_file_returns_error(
    stub_engine, tmp_path
):
    f = tmp_path / "regular.txt"
    f.write_text("content")

    tool = ListDirectoryTool(stub_engine)
    out = await tool.execute(path=str(f))

    assert out.startswith("Error:")
    assert "not a directory" in out.lower() or "Not a directory" in out

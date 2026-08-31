"""Web/VSCode renderers must dispatch DirectoryListingResult and
DirectoryTreeResult to their TableResult / TreeResult handlers.

The Python side (`ppxai/commands/results.py`) defines these as
subclasses of TableResult / TreeResult, with a docstring claiming
"Renderers that handle TableResult automatically handle this." That's
true for Rich/Textual (which dispatch by class), but the HTTP
renderers (web/VSCode) dispatch by the wire `type` string — which
carries the concrete subclass name (`"DirectoryListingResult"`) and
therefore bypasses the TableResult handler.

The bug surfaced in production at v1.18.3 (web `/ls` returned only
"N items in <path>" — the result.message — instead of the listing
rows). Fixed in v1.18.4 by adding explicit handler entries for the
subclass type names. These tests pin that fix so a refactor to the
renderer can't silently regress.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def web_renderer_src() -> str:
    return (
        PROJECT_ROOT / "ppxai" / "web" / "shared" / "result-renderer.js"
    ).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def vscode_renderer_src() -> str:
    return (
        PROJECT_ROOT / "vscode-extension" / "src" / "commandRenderer.ts"
    ).read_text(encoding="utf-8")


class TestPythonSubclassesDispatchAsTableTree:
    """Python-side: DirectoryListingResult IS a TableResult subclass.

    Ensures the wire-format `type` field carries the subclass name
    (which is what the renderer dispatches on), and the subclass
    relationship holds so future renderers can rely on it.
    """

    def test_directory_listing_subclasses_table(self):
        from ppxai.commands.results import DirectoryListingResult, TableResult
        assert issubclass(DirectoryListingResult, TableResult)

    def test_directory_tree_subclasses_tree(self):
        from ppxai.commands.results import DirectoryTreeResult, TreeResult
        assert issubclass(DirectoryTreeResult, TreeResult)

    def test_directory_listing_serializes_with_subclass_type(self):
        """The wire `type` field uses the concrete subclass name —
        which is why renderers need explicit handlers for it."""
        from ppxai.commands.results import (
            DirectoryListingResult,
            ResultStatus,
        )
        result = DirectoryListingResult(
            status=ResultStatus.SUCCESS,
            message="3 items in /tmp",
            columns=["Name", "Size", "Modified"],
            rows=[["a.txt", "1KB", "now"], ["b/", "-", "1m ago"]],
        )
        d = result.to_dict()
        assert d["type"] == "DirectoryListingResult"
        # Sanity: rows + columns survive the round-trip — the bug was
        # that they were emitted server-side but the client renderer
        # ignored them.
        assert d["columns"] == ["Name", "Size", "Modified"]
        assert len(d["rows"]) == 2

    def test_directory_tree_serializes_with_subclass_type(self):
        from ppxai.commands.results import (
            DirectoryTreeResult,
            ResultStatus,
        )
        result = DirectoryTreeResult(
            status=ResultStatus.SUCCESS,
            message="2 dirs, 3 files",
            root={"label": "/tmp/", "children": []},
        )
        d = result.to_dict()
        assert d["type"] == "DirectoryTreeResult"
        assert d["root"] == {"label": "/tmp/", "children": []}


class TestWebRendererHandlesSubclasses:
    """Web's ResultRenderer._handlers must contain entries for the
    subclass type names. Without these, dispatch falls through to
    the unknown-type fallback (`result.message` only)."""

    def test_directory_listing_handler_present(self, web_renderer_src):
        # The handler is registered via the `_handlers` object literal
        # as a method shorthand `DirectoryListingResult(result) {...}`.
        assert re.search(
            r"\bDirectoryListingResult\s*\(result\)\s*\{",
            web_renderer_src,
        ), "ResultRenderer._handlers missing DirectoryListingResult"

    def test_directory_tree_handler_present(self, web_renderer_src):
        assert re.search(
            r"\bDirectoryTreeResult\s*\(result\)\s*\{",
            web_renderer_src,
        ), "ResultRenderer._handlers missing DirectoryTreeResult"

    def test_directory_listing_aliases_table_handler(self, web_renderer_src):
        """DirectoryListingResult must delegate to the TableResult
        handler. Otherwise we'd diverge in rendering — e.g. a
        TableResult column-rendering improvement wouldn't apply to
        directory listings."""
        match = re.search(
            r"DirectoryListingResult\s*\(result\)\s*\{([^}]*)\}",
            web_renderer_src,
            re.DOTALL,
        )
        assert match, "DirectoryListingResult handler not found"
        body = match.group(1)
        assert "TableResult" in body, (
            "DirectoryListingResult handler must delegate to "
            "ResultRenderer._handlers.TableResult"
        )

    def test_directory_tree_aliases_tree_handler(self, web_renderer_src):
        match = re.search(
            r"DirectoryTreeResult\s*\(result\)\s*\{([^}]*)\}",
            web_renderer_src,
            re.DOTALL,
        )
        assert match
        body = match.group(1)
        assert "TreeResult" in body, (
            "DirectoryTreeResult handler must delegate to TreeResult"
        )


class TestVscodeRendererHandlesSubclasses:
    """VSCode's CommandRenderer.render() switch statement must include
    cases for the subclass type names alongside their parents."""

    def test_directory_listing_case_present(self, vscode_renderer_src):
        assert "case 'DirectoryListingResult'" in vscode_renderer_src, (
            "VSCode CommandRenderer.render() switch missing case for "
            "DirectoryListingResult"
        )

    def test_directory_tree_case_present(self, vscode_renderer_src):
        assert "case 'DirectoryTreeResult'" in vscode_renderer_src

    def test_directory_listing_falls_through_to_table_format(
        self, vscode_renderer_src
    ):
        """The `case 'DirectoryListingResult':` block must immediately
        precede or merge with `case 'TableResult':` so both call
        `_formatTable`. Pin the merge by checking they share the same
        following statement."""
        # Both cases should be back-to-back, falling through to the
        # same _formatTable / postSystemMessage line. We allow whitespace
        # but no other case between them.
        pattern = (
            r"case 'TableResult':\s*case 'DirectoryListingResult':"
            r"|case 'DirectoryListingResult':\s*case 'TableResult':"
            r"|case 'TableResult':[^c]*?case 'DirectoryListingResult':"
            r"[^c]*?_formatTable"
            r"|case 'DirectoryListingResult':[^c]*?case 'TableResult':"
            r"[^c]*?_formatTable"
        )
        assert re.search(pattern, vscode_renderer_src, re.DOTALL), (
            "DirectoryListingResult must share the TableResult case "
            "branch (both call _formatTable)"
        )

    def test_directory_tree_falls_through_to_tree_format(
        self, vscode_renderer_src
    ):
        pattern = (
            r"case 'TreeResult':\s*case 'DirectoryTreeResult':"
            r"|case 'DirectoryTreeResult':\s*case 'TreeResult':"
            r"|case 'TreeResult':[^c]*?case 'DirectoryTreeResult':"
            r"[^c]*?_formatTree"
            r"|case 'DirectoryTreeResult':[^c]*?case 'TreeResult':"
            r"[^c]*?_formatTree"
        )
        assert re.search(pattern, vscode_renderer_src, re.DOTALL), (
            "DirectoryTreeResult must share the TreeResult case branch"
        )

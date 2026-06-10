"""Tests for PDF tools (Phase 2.8, v1.17.4).

Exercises ReadPdfTool and GetPdfPageImageTool end-to-end against a real
pypdf-generated PDF. Tests create the PDF in a tmp_path, register it
with a SessionFileStore, and invoke the tools through their `execute()`
coroutines — the same path the engine uses at runtime.

Scope:
    - read_pdf extracts text from single pages, ranges, comma-lists, "all"
    - read_pdf truncation on oversized output
    - read_pdf error cases: missing file_id, non-PDF, empty PDF,
      out-of-range pages, malformed page specs
    - get_pdf_page_image returns a data URI (if poppler is installed)
    - get_pdf_page_image error cases: missing file_id, invalid page,
      poppler missing (skipped if not installed)
    - _parse_pages_spec helper edge cases
    - register_tools skips gracefully when pypdf is missing (patched)
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ppxai.engine.session_store import SessionFileStore

# Import pypdf at module level so tests that need it skip cleanly on
# installs without the [data] extras group.
pypdf = pytest.importorskip("pypdf")

from ppxai.engine.tools.builtin.pdf_tools import (  # noqa: E402
    GetPdfPageImageTool,
    ReadPdfTool,
    _parse_pages_spec,
    register_tools,
)


# -----------------------------------------------------------------------------
# Test fixtures — real PDFs generated with pypdf
# -----------------------------------------------------------------------------


def _make_pdf(pages: list[str]) -> bytes:
    """Build a minimal multi-page PDF with the given text per page.

    Hand-constructs the PDF byte layout directly rather than going
    through pypdf's writer — the writer API for attaching custom
    content streams varies by version and we only need a known-good
    artifact for tool testing. The resulting PDFs parse cleanly with
    `pypdf.PdfReader.extract_text` and contain exactly the text we
    pass in, so assertions can match on known strings.

    An empty `pages` list produces a valid 0-page PDF for testing the
    empty-document error path.
    """
    if not pages:
        # Minimal 0-page PDF — Catalog + empty Pages.
        return (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
            b"xref\n0 3\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"trailer\n<< /Size 3 /Root 1 0 R >>\n"
            b"startxref\n104\n%%EOF\n"
        )

    # Multi-page PDF: Catalog (1), Pages (2), then each page has
    # a Page object (3,5,7,...) and a Contents stream (4,6,8,...).
    # Font object comes last.
    font_obj_id = 3 + 2 * len(pages)

    objects: list[str] = []

    # 1: Catalog
    objects.append("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")

    # 2: Pages — Kids array references all page objects
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(
        f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>\nendobj\n"
    )

    # Page + content stream pairs
    for i, text in enumerate(pages):
        page_id = 3 + 2 * i
        content_id = 4 + 2 * i
        objects.append(
            f"{page_id} 0 obj\n"
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_obj_id} 0 R >> >> >>\n"
            f"endobj\n"
        )
        # Escape special chars so the content stream stays valid
        # (parens delimit PDF string literals).
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET"
        objects.append(
            f"{content_id} 0 obj\n"
            f"<< /Length {len(stream)} >>\n"
            f"stream\n{stream}\nendstream\n"
            f"endobj\n"
        )

    # Font object (single Helvetica used by every page)
    objects.append(
        f"{font_obj_id} 0 obj\n"
        f"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
        f"endobj\n"
    )

    # Assemble with correct xref offsets
    header = "%PDF-1.4\n"
    body = header
    offsets = [0]  # object 0 is the free marker
    for obj_str in objects:
        offsets.append(len(body))
        body += obj_str

    xref_pos = len(body)
    xref = f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for off in offsets[1:]:
        xref += f"{off:010d} 00000 n \n"
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    )
    return (body + xref + trailer).encode("latin-1")


@pytest.fixture
def store(tmp_path) -> SessionFileStore:
    return SessionFileStore(base_dir=tmp_path / "uploads")


@pytest.fixture
def fake_engine(store):
    """Minimal engine stub exposing only `.file_store`."""
    return SimpleNamespace(file_store=store)


@pytest.fixture
def three_page_pdf_meta(store):
    """Save a 3-page PDF in the store and return its metadata."""
    pdf_bytes = _make_pdf([
        "Introduction to the test document",
        "Middle page with different content",
        "Final page conclusion text",
    ])
    return store.save("test.pdf", pdf_bytes, media_type="application/pdf")


# -----------------------------------------------------------------------------
# _parse_pages_spec — page selector parsing
# -----------------------------------------------------------------------------


class TestParsePagesSpec:
    def test_all_returns_every_page(self):
        assert _parse_pages_spec("all", 5) == [0, 1, 2, 3, 4]

    def test_empty_string_returns_all(self):
        assert _parse_pages_spec("", 3) == [0, 1, 2]

    def test_single_page(self):
        assert _parse_pages_spec("3", 5) == [2]

    def test_range(self):
        assert _parse_pages_spec("2-4", 5) == [1, 2, 3]

    def test_comma_list(self):
        assert _parse_pages_spec("1,3,5", 5) == [0, 2, 4]

    def test_mixed_singles_and_ranges(self):
        assert _parse_pages_spec("1,3-5,7", 10) == [0, 2, 3, 4, 6]

    def test_dedups_overlapping_selections(self):
        # "2-4,3-5" overlaps on page 3, 4 — result must be sorted + unique.
        assert _parse_pages_spec("2-4,3-5", 10) == [1, 2, 3, 4]

    def test_page_out_of_range_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            _parse_pages_spec("10", 5)

    def test_range_out_of_range_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            _parse_pages_spec("3-15", 10)

    def test_inverted_range_raises(self):
        with pytest.raises(ValueError, match="invalid page range"):
            _parse_pages_spec("5-2", 10)

    def test_zero_page_raises(self):
        with pytest.raises(ValueError):
            _parse_pages_spec("0", 5)

    def test_empty_selection_raises(self):
        with pytest.raises(ValueError, match="empty page selection"):
            _parse_pages_spec(",,", 5)


# -----------------------------------------------------------------------------
# ReadPdfTool
# -----------------------------------------------------------------------------


class TestReadPdfTool:
    def test_read_all_pages(self, fake_engine, three_page_pdf_meta):
        tool = ReadPdfTool(fake_engine)
        result = asyncio.run(tool.execute(file_id=three_page_pdf_meta.file_id))
        assert "test.pdf" in result
        assert "3 pages total" in result
        # All three page markers present.
        assert "## Page 1" in result
        assert "## Page 2" in result
        assert "## Page 3" in result
        # pypdf text extraction should recover the content strings we
        # wrote via the BT/ET operators.
        assert "Introduction" in result
        assert "Middle page" in result
        assert "Final page" in result

    def test_read_single_page(self, fake_engine, three_page_pdf_meta):
        tool = ReadPdfTool(fake_engine)
        result = asyncio.run(
            tool.execute(file_id=three_page_pdf_meta.file_id, pages="2")
        )
        assert "Middle page" in result
        # Other pages should not appear.
        assert "Introduction" not in result
        assert "Final page" not in result

    def test_read_page_range(self, fake_engine, three_page_pdf_meta):
        tool = ReadPdfTool(fake_engine)
        result = asyncio.run(
            tool.execute(file_id=three_page_pdf_meta.file_id, pages="2-3")
        )
        assert "Middle page" in result
        assert "Final page" in result
        assert "Introduction" not in result

    def test_comma_list(self, fake_engine, three_page_pdf_meta):
        tool = ReadPdfTool(fake_engine)
        result = asyncio.run(
            tool.execute(file_id=three_page_pdf_meta.file_id, pages="1,3")
        )
        assert "Introduction" in result
        assert "Final page" in result
        # Page 2 excluded.
        assert "Middle page" not in result

    def test_missing_file_id_error(self, fake_engine):
        tool = ReadPdfTool(fake_engine)
        result = asyncio.run(tool.execute(file_id="nonexistent_id"))
        assert "Error" in result
        assert "Unknown file_id" in result

    def test_non_pdf_file_rejected(self, store):
        # Save a PNG in the store and ask read_pdf to read it.
        png_meta = store.save("image.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
                              media_type="image/png")
        tool = ReadPdfTool(SimpleNamespace(file_store=store))
        result = asyncio.run(tool.execute(file_id=png_meta.file_id))
        assert "Error" in result
        assert "not a PDF" in result
        assert "image/png" in result

    def test_empty_pdf(self, store):
        empty_pdf = _make_pdf([])
        meta = store.save("empty.pdf", empty_pdf, media_type="application/pdf")
        tool = ReadPdfTool(SimpleNamespace(file_store=store))
        result = asyncio.run(tool.execute(file_id=meta.file_id))
        assert "empty PDF" in result
        assert "0 pages" in result

    def test_out_of_range_page(self, fake_engine, three_page_pdf_meta):
        tool = ReadPdfTool(fake_engine)
        result = asyncio.run(
            tool.execute(file_id=three_page_pdf_meta.file_id, pages="99")
        )
        assert "Error" in result
        assert "out of range" in result

    def test_malformed_pages_spec(self, fake_engine, three_page_pdf_meta):
        tool = ReadPdfTool(fake_engine)
        result = asyncio.run(
            tool.execute(file_id=three_page_pdf_meta.file_id, pages="not-a-number")
        )
        assert "Error" in result

    def test_no_file_store_on_engine(self):
        # Engine without a file_store attribute — tool must fail cleanly.
        engine = SimpleNamespace()  # no file_store
        tool = ReadPdfTool(engine)
        result = asyncio.run(tool.execute(file_id="any_id"))
        assert "Error" in result
        assert "SessionFileStore" in result

    def test_file_missing_on_disk(self, fake_engine, three_page_pdf_meta):
        # Delete the backing file after registration.
        three_page_pdf_meta.path.unlink()
        tool = ReadPdfTool(fake_engine)
        result = asyncio.run(tool.execute(file_id=three_page_pdf_meta.file_id))
        assert "Error" in result
        assert "missing on disk" in result


# -----------------------------------------------------------------------------
# GetPdfPageImageTool — page rasterization via pypdfium2 (v1.18.1)
# -----------------------------------------------------------------------------
#
# Pre-v1.18.1 the rasterizer used pdf2image+poppler, which required
# the poppler system binary. Tests were guarded with `skipif(not
# _poppler_available())` so the suite stayed green on dev machines
# without it. v1.18.1 swapped the backend to pypdfium2 — pure-wheel,
# bundled via the [data] extras — so the guards are gone and the
# tests run unconditionally.


class TestGetPdfPageImageTool:
    def test_rasterize_single_page(self, fake_engine, three_page_pdf_meta):
        # v1.18.7: tool saves the PNG to SessionFileStore and returns a
        # compact reference (file_id), NOT inline base64. The huge
        # data-URI used to bloat context by ~100K tokens per call.
        tool = GetPdfPageImageTool(fake_engine)
        result = asyncio.run(
            tool.execute(file_id=three_page_pdf_meta.file_id, page=1, dpi=72)
        )
        assert "Rasterized page 1" in result
        assert "Dimensions:" in result
        assert "KB PNG" in result
        # The result must NOT contain inline base64 — that was the bug.
        assert "data:image/png;base64," not in result
        # The result must contain a file_id reference into SessionFileStore.
        assert "file_id=" in result
        # The bytes were actually saved to the store.
        store_meta_list = fake_engine.file_store.list_all()
        png_entries = [m for m in store_meta_list if m.media_type == "image/png"]
        assert len(png_entries) >= 1
        assert any(m.name.endswith("_page_1.png") for m in png_entries)

    def test_rasterize_falls_back_to_data_uri_without_store(self, three_page_pdf_meta, store):
        # Engine stub WITHOUT file_store: compat path keeps the inline
        # data URI. Test fixtures that don't wire a store still see
        # output, just at the legacy cost.
        engine_no_store = SimpleNamespace()  # no file_store attribute
        # Need to manually look up the file because the no-store engine
        # can't resolve a file_id — pass the path directly via tmp.
        tool = GetPdfPageImageTool(engine_no_store)
        # We have to provide path, since file_id requires a store.
        result = asyncio.run(
            tool.execute(path=str(three_page_pdf_meta.path), page=1, dpi=72)
        )
        # Without a store, the tool falls back to inline data URI.
        assert "data:image/png;base64," in result

    def test_dpi_capped(self, fake_engine, three_page_pdf_meta):
        tool = GetPdfPageImageTool(fake_engine)
        # Request absurdly high DPI — should be clamped silently.
        result = asyncio.run(
            tool.execute(file_id=three_page_pdf_meta.file_id, page=1, dpi=10000)
        )
        assert "Rasterized page 1" in result
        # DPI in the summary should be the clamped value, not the input.
        assert "DPI: 300" in result  # _MAX_DPI

    def test_missing_file_id_error(self, fake_engine):
        tool = GetPdfPageImageTool(fake_engine)
        result = asyncio.run(
            tool.execute(file_id="nonexistent", page=1)
        )
        assert "Error" in result
        assert "Unknown file_id" in result

    def test_non_pdf_rejected(self, store):
        png_meta = store.save(
            "img.png",
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
            media_type="image/png",
        )
        tool = GetPdfPageImageTool(SimpleNamespace(file_store=store))
        result = asyncio.run(tool.execute(file_id=png_meta.file_id, page=1))
        assert "Error" in result
        assert "not a PDF" in result

    def test_invalid_page_number(self, fake_engine, three_page_pdf_meta):
        tool = GetPdfPageImageTool(fake_engine)
        result = asyncio.run(
            tool.execute(file_id=three_page_pdf_meta.file_id, page=0)
        )
        assert "Error" in result
        assert "page must be >= 1" in result


# -----------------------------------------------------------------------------
# Registration
# -----------------------------------------------------------------------------


class _FakeManager:
    """Minimal ToolManager substitute that records registered tools."""

    def __init__(self):
        self.tools = []

    def register_tool(self, tool):
        self.tools.append(tool)

    def register_function(self, **kwargs):
        # Not used by pdf_tools, but needed for protocol compatibility.
        pass


class TestRegisterTools:
    def test_registers_both_tools_with_engine(self, fake_engine):
        manager = _FakeManager()
        ok = register_tools(manager, fake_engine)
        assert ok is True
        names = {tool.name for tool in manager.tools}
        assert "read_pdf" in names
        assert "get_pdf_page_image" in names

    def test_returns_false_without_engine(self):
        manager = _FakeManager()
        ok = register_tools(manager, None)
        assert ok is False
        assert manager.tools == []

    def test_returns_false_when_pypdf_missing(self, fake_engine, monkeypatch):
        # Simulate an install without pypdf by temporarily removing it
        # from sys.modules and blocking re-import.
        import builtins
        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "pypdf":
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        # Pre-emptively remove pypdf so the import inside register_tools
        # triggers our patched __import__.
        monkeypatch.setitem(sys.modules, "pypdf", None)
        monkeypatch.setattr(builtins, "__import__", blocked_import)

        # Re-import pdf_tools under the patch — the import inside
        # register_tools will see our blocker.
        import ppxai.engine.tools.builtin.pdf_tools as mod
        importlib.reload(mod)

        manager = _FakeManager()
        ok = mod.register_tools(manager, fake_engine)
        assert ok is False
        assert manager.tools == []

        # Restore for subsequent tests — reload once more with the real
        # import so the rest of the suite sees a working pypdf.
        monkeypatch.undo()
        importlib.reload(mod)


# -----------------------------------------------------------------------------
# Workspace-path resolution (v1.18.7) — read_pdf and get_pdf_page_image
# must accept `path=` for files dropped into the workspace via
# /files/upload or the file tree (no SessionFileStore entry exists for
# those). Engine layer is covered exhaustively in test_file_ref.py;
# these are smoke tests through the tool boundary.
# -----------------------------------------------------------------------------


@pytest.fixture
def workspace_engine(tmp_path, store):
    """Engine stub with both a SessionFileStore and a working_dir."""
    wd = tmp_path / "workspace"
    wd.mkdir()
    return SimpleNamespace(file_store=store, get_working_dir=lambda: str(wd))


class TestPdfPathResolution:
    def test_read_pdf_via_path(self, workspace_engine, tmp_path):
        pdf = _make_pdf(["Workspace PDF content"])
        (tmp_path / "workspace" / "doc.pdf").write_bytes(pdf)
        tool = ReadPdfTool(workspace_engine)
        result = asyncio.run(tool.execute(path="doc.pdf"))
        assert "Error" not in result
        assert "Workspace PDF content" in result

    def test_get_pdf_page_image_via_path(self, workspace_engine, tmp_path):
        pdf = _make_pdf(["Page one"])
        (tmp_path / "workspace" / "doc.pdf").write_bytes(pdf)
        tool = GetPdfPageImageTool(workspace_engine)
        result = asyncio.run(tool.execute(page=1, path="doc.pdf"))
        # pypdfium2 missing produces a clear error; otherwise the result
        # contains a file_id reference (v1.18.7 fixed the 100K-token
        # data-URI bloat by saving the PNG to SessionFileStore).
        assert "file_id=" in result or "pypdfium2" in result
        # And no inline base64 should leak through.
        assert "data:image/png;base64," not in result

    def test_read_pdf_path_outside_workspace_rejected(self, workspace_engine, tmp_path):
        pdf = _make_pdf(["Secret"])
        (tmp_path / "outside.pdf").write_bytes(pdf)
        tool = ReadPdfTool(workspace_engine)
        result = asyncio.run(tool.execute(path="../outside.pdf"))
        assert "Error" in result
        assert "outside the working directory" in result

    def test_read_pdf_no_args_rejected(self, workspace_engine):
        tool = ReadPdfTool(workspace_engine)
        result = asyncio.run(tool.execute())
        assert "Error" in result
        assert "file_id" in result or "path" in result

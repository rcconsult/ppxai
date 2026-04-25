"""Tests for the side-effect emission rules of /show (v1.18.1).

Covers which `/show` branches emit which kind:

  - Image       → SHOW_IMAGE
  - PDF         → SHOW_PDF
  - Code/text   → OPEN_VIEWER
  - --source    → OPEN_VIEWER (forces code view)
  - JSON/YAML/TOML/HCL parse-success → no side-effect (TreeResult is
    rendered inline by clients)
  - JSON/YAML parse-failure          → OPEN_VIEWER (falls back to
    code view)
  - CSV/TSV parse-success → no side-effect (TableResult inline)
  - CSV/TSV parse-failure → OPEN_VIEWER
  - Markdown   → no side-effect (MarkdownResult inline)
  - Binary (non-image, non-PDF) → ErrorResult, no side-effect

The rule: emit OPEN_VIEWER iff the result is a FileViewResult.
TypedData results (Tree/Table/Markdown) ARE the viewer, rendered
inline — no separate viewer needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ppxai.commands.context import ServerCommandContext
from ppxai.commands.display import handle_show
from ppxai.commands.results import (
    ErrorResult,
    FileViewResult,
    ImageResult,
    MarkdownResult,
    NotificationResult,
    SideEffectKind,
    TableResult,
    TreeResult,
)


@pytest.fixture
def context(tmp_path):
    engine = MagicMock()
    engine.get_working_dir.return_value = str(tmp_path)
    return ServerCommandContext(engine)


def _kinds(result):
    return [se.kind for se in result.side_effects]


# ---------------------------------------------------------------------------
# Code / text — OPEN_VIEWER
# ---------------------------------------------------------------------------

class TestShowCodeText:
    def test_python_file_emits_open_viewer(self, context, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("print('hi')\n", encoding="utf-8")
        result = handle_show(context, "main.py")
        assert isinstance(result, FileViewResult)
        assert SideEffectKind.OPEN_VIEWER in _kinds(result)

    def test_plain_text_emits_open_viewer(self, context, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello\n", encoding="utf-8")
        result = handle_show(context, "notes.txt")
        assert isinstance(result, FileViewResult)
        assert SideEffectKind.OPEN_VIEWER in _kinds(result)

    def test_open_viewer_payload_has_filepath(self, context, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("x = 1\n", encoding="utf-8")
        result = handle_show(context, "main.py")
        se = next(s for s in result.side_effects
                  if s.kind == SideEffectKind.OPEN_VIEWER)
        assert se.payload["filepath"] == str(f.resolve())


# ---------------------------------------------------------------------------
# --source flag — forces code view AND OPEN_VIEWER
# ---------------------------------------------------------------------------

class TestShowSourceFlag:
    def test_source_flag_forces_open_viewer_on_csv(self, context, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n", encoding="utf-8")
        result = handle_show(context, "data.csv --source")
        # --source overrides CSV → FileViewResult, not TableResult
        assert isinstance(result, FileViewResult)
        assert SideEffectKind.OPEN_VIEWER in _kinds(result)

    def test_source_flag_forces_open_viewer_on_json(self, context, tmp_path):
        f = tmp_path / "config.json"
        f.write_text('{"a": 1}\n', encoding="utf-8")
        result = handle_show(context, "config.json --source")
        assert isinstance(result, FileViewResult)
        assert SideEffectKind.OPEN_VIEWER in _kinds(result)


# ---------------------------------------------------------------------------
# Typed-data results — NO side-effect (rendered inline)
# ---------------------------------------------------------------------------

class TestShowTypedDataNoSideEffect:
    def test_json_emits_tree_no_side_effect(self, context, tmp_path):
        f = tmp_path / "config.json"
        f.write_text('{"a": 1, "b": [2, 3]}\n', encoding="utf-8")
        result = handle_show(context, "config.json")
        assert isinstance(result, TreeResult)
        assert result.side_effects == []

    def test_csv_emits_table_no_side_effect(self, context, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
        result = handle_show(context, "data.csv")
        assert isinstance(result, TableResult)
        assert result.side_effects == []

    def test_markdown_emits_markdown_no_side_effect(self, context, tmp_path):
        f = tmp_path / "README.md"
        f.write_text("# Hello\n\nSome text.\n", encoding="utf-8")
        result = handle_show(context, "README.md")
        assert isinstance(result, MarkdownResult)
        assert result.side_effects == []


# ---------------------------------------------------------------------------
# Parse-failure fallbacks → OPEN_VIEWER
# ---------------------------------------------------------------------------

class TestShowParseFailureFallback:
    def test_invalid_json_falls_back_to_open_viewer(self, context, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{this is not json", encoding="utf-8")
        result = handle_show(context, "bad.json")
        # Parse failed → FileViewResult with WARNING status
        assert isinstance(result, FileViewResult)
        assert SideEffectKind.OPEN_VIEWER in _kinds(result)


# ---------------------------------------------------------------------------
# Image / PDF — existing behaviour preserved
# ---------------------------------------------------------------------------

class TestShowImageAndPdf:
    def test_image_still_emits_show_image(self, context, tmp_path):
        # Minimal valid PNG (1x1 transparent pixel)
        png_bytes = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000d49444154789c626001000000ffff03000006000557bff8730000"
            "00004945" + "4e44ae426082"
        )
        f = tmp_path / "pixel.png"
        f.write_bytes(png_bytes)
        result = handle_show(context, "pixel.png")
        assert isinstance(result, ImageResult)
        assert SideEffectKind.SHOW_IMAGE in _kinds(result)
        # Must NOT emit OPEN_VIEWER (different kind for binary media)
        assert SideEffectKind.OPEN_VIEWER not in _kinds(result)

    def test_pdf_still_emits_show_pdf(self, context, tmp_path):
        f = tmp_path / "doc.pdf"
        # Minimal PDF header so file-type detection sees a PDF
        f.write_bytes(b"%PDF-1.4\n%fake\n")
        result = handle_show(context, "doc.pdf")
        assert isinstance(result, NotificationResult)
        assert SideEffectKind.SHOW_PDF in _kinds(result)
        assert SideEffectKind.OPEN_VIEWER not in _kinds(result)


# ---------------------------------------------------------------------------
# Error paths — no side-effect
# ---------------------------------------------------------------------------

class TestShowErrorsNoSideEffect:
    def test_missing_file_no_side_effect(self, context):
        result = handle_show(context, "no-such-file.py")
        assert isinstance(result, ErrorResult)
        assert result.side_effects == []

    def test_directory_no_side_effect(self, context, tmp_path):
        result = handle_show(context, ".")
        assert isinstance(result, ErrorResult)
        assert result.side_effects == []

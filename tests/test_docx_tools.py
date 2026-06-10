"""Tests for the Word-document tool (`read_docx`).

Covers both reference paths: SessionFileStore file_id (chat attachment)
and workspace path (file-tree / drag-drop). The docx tool ships with no
optional dependencies (stdlib zipfile + xml.etree).

v1.18.7 — added alongside the path-resolution fix that lets office tools
address workspace files that have no SessionFileStore entry.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from types import SimpleNamespace

import pytest

from ppxai.engine.session_store import SessionFileStore
from ppxai.engine.tools.builtin.docx_tools import ReadDocxTool


_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _make_docx(paragraphs: list[str]) -> bytes:
    """Build a minimal .docx file containing the given paragraphs.

    A .docx is a zip with `word/document.xml` carrying the wordprocessingml
    payload. The other files (`[Content_Types].xml`, `_rels/.rels`) are
    not strictly required for our extractor — it only reads document.xml —
    so we keep the fixture tight.
    """
    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body_parts = []
    for p in paragraphs:
        body_parts.append(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>')
    document_xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{w_ns}"><w:body>'
        f'{"".join(body_parts)}'
        f'</w:body></w:document>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


@pytest.fixture
def store(tmp_path) -> SessionFileStore:
    return SessionFileStore(base_dir=tmp_path / "uploads")


@pytest.fixture
def workspace_engine(tmp_path, store):
    """Engine stub with both a SessionFileStore AND a workspace dir."""
    wd = tmp_path / "workspace"
    wd.mkdir()
    return SimpleNamespace(file_store=store, get_working_dir=lambda: str(wd))


class TestReadDocx:
    def test_reads_via_file_id(self, workspace_engine, store):
        meta = store.save(
            "memo.docx",
            _make_docx(["Hello world.", "Second paragraph."]),
            media_type=_DOCX_MIME,
        )
        tool = ReadDocxTool(workspace_engine)
        result = asyncio.run(tool.execute(file_id=meta.file_id))
        assert "memo.docx" in result
        assert "Hello world." in result
        assert "Second paragraph." in result

    def test_reads_via_workspace_path(self, workspace_engine, tmp_path):
        (tmp_path / "workspace" / "memo.docx").write_bytes(
            _make_docx(["Workspace doc.", "Second line."])
        )
        tool = ReadDocxTool(workspace_engine)
        result = asyncio.run(tool.execute(path="memo.docx"))
        assert "memo.docx" in result
        assert "Workspace doc." in result
        assert "Second line." in result

    def test_neither_arg_rejected(self, workspace_engine):
        tool = ReadDocxTool(workspace_engine)
        result = asyncio.run(tool.execute())
        assert "Error" in result

    def test_both_args_rejected(self, workspace_engine, store, tmp_path):
        meta = store.save(
            "a.docx", _make_docx(["x"]), media_type=_DOCX_MIME
        )
        (tmp_path / "workspace" / "b.docx").write_bytes(_make_docx(["y"]))
        tool = ReadDocxTool(workspace_engine)
        result = asyncio.run(tool.execute(file_id=meta.file_id, path="b.docx"))
        assert "Error" in result
        assert "not both" in result.lower()

    def test_path_escape_rejected(self, workspace_engine, tmp_path):
        (tmp_path / "outside.docx").write_bytes(_make_docx(["secret"]))
        tool = ReadDocxTool(workspace_engine)
        result = asyncio.run(tool.execute(path="../outside.docx"))
        assert "Error" in result
        assert "outside the working directory" in result

    def test_non_docx_rejected_via_file_id(self, workspace_engine, store):
        meta = store.save("image.png", b"\x89PNG\r\n\x1a\n", media_type="image/png")
        tool = ReadDocxTool(workspace_engine)
        result = asyncio.run(tool.execute(file_id=meta.file_id))
        assert "Error" in result
        assert "not a Word document" in result

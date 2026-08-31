"""
Word document tools for multimodal attachments.

v1.17.4. Lets the model read .docx files the user has attached.
Uses stdlib zipfile + xml.etree to extract text — no python-docx
dependency required.

    read_docx(file_id, pages="all")
        → extracted text from the document

Resolves `file_id` through the engine's SessionFileStore.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from typing import Any, List, Optional, Tuple

from ...types import ToolEngineProtocol, ToolManagerProtocol
from ..base import BaseTool
from ...file_ref import resolve_file_reference
from ...file_ref import FILE_REF_PROPERTIES


_MAX_TEXT_CHARS = 100_000

# Word XML namespace
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _resolve_file(
    engine: Any,
    file_id: Optional[str] = None,
    path: Optional[str] = None,
) -> Tuple[Optional[Any], Optional[str]]:
    """Resolve a file reference via the unified engine resolver.

    Accepts EITHER `file_id` (SessionFileStore chat attachment) or
    `path` (workspace file). v1.18.7 — see `engine.file_ref`.
    """
    return resolve_file_reference(engine, file_id=file_id, path=path)


def _is_docx(meta: Any) -> bool:
    """Check if a file is a Word document."""
    mt = (meta.media_type or "").lower()
    if "wordprocessingml" in mt or mt == "application/msword":
        return True
    name = (meta.name or "").lower()
    return name.endswith((".docx", ".doc"))


def _extract_docx_text(path) -> str:
    """Extract plain text from a .docx file using stdlib zipfile + XML.

    Reads word/document.xml from the zip archive and extracts text
    from all <w:t> elements, preserving paragraph breaks.
    """
    try:
        with zipfile.ZipFile(str(path), "r") as zf:
            if "word/document.xml" not in zf.namelist():
                return "(Could not find document.xml in the archive)"
            xml_data = zf.read("word/document.xml")
    except (zipfile.BadZipFile, OSError) as exc:
        return f"(Could not read .docx file: {exc})"

    root = ET.fromstring(xml_data)
    paragraphs: List[str] = []

    for para in root.iter(f"{_W_NS}p"):
        texts: List[str] = []
        for t_elem in para.iter(f"{_W_NS}t"):
            if t_elem.text:
                texts.append(t_elem.text)
        if texts:
            paragraphs.append("".join(texts))

    return "\n\n".join(paragraphs)


class ReadDocxTool(BaseTool):
    """Read text content from an attached Word document."""

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "read_docx"
        self.description = (
            "Read text content from a Word document (.docx). Returns the "
            "extracted text with paragraph breaks preserved. Pass either "
            "'file_id' (chat attachment) or 'path' (workspace file) — "
            "exactly one is required."
        )
        self.parameters = {
            "type": "object",
            "properties": dict(FILE_REF_PROPERTIES),
            "required": [],
        }

    async def execute(
        self,
        file_id: Optional[str] = None,
        path: Optional[str] = None,
        **kwargs,
    ) -> str:
        meta, err = _resolve_file(self.engine, file_id=file_id, path=path)
        if err:
            return f"Error: {err}"
        if not _is_docx(meta):
            return f"Error: {meta.name!r} is not a Word document (type={meta.media_type!r})."

        text = _extract_docx_text(meta.path)

        if len(text) > _MAX_TEXT_CHARS:
            text = text[:_MAX_TEXT_CHARS] + f"\n\n[Truncated at {_MAX_TEXT_CHARS:,} chars]"

        if not text.strip():
            return f"{meta.name}: no text content found."

        size_kb = meta.path.stat().st_size / 1024
        header = f"# {meta.name} ({size_kb:.1f} KB)\n\n"
        return header + text


# =============================================================================
# Registration
# =============================================================================


def register_tools(manager: ToolManagerProtocol, engine: ToolEngineProtocol) -> bool:
    """Register Word document tools. Always succeeds (no optional deps)."""
    if engine is None:
        return False
    manager.register_tool(ReadDocxTool(engine))
    return True


__all__ = [
    "ReadDocxTool",
    "register_tools",
]

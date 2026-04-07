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


_MAX_TEXT_CHARS = 100_000

# Word XML namespace
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _resolve_file(engine: Any, file_id: str) -> Tuple[Optional[Any], Optional[str]]:
    """Look up a file_id in the engine's SessionFileStore."""
    file_store = getattr(engine, "file_store", None)
    if file_store is None:
        return None, "No SessionFileStore available."
    meta = file_store.get_metadata(file_id)
    if meta is None:
        return None, f"Unknown file_id: {file_id!r}. The attachment may have been removed."
    if not meta.path.exists():
        return None, f"File for {file_id!r} is missing on disk."
    return meta, None


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
            "Read text content from an attached Word document (.docx). "
            "Returns the extracted text with paragraph breaks preserved. "
            "Pass the 'file_id' from the <uploaded_file> reference."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "The file_id from the <uploaded_file> reference.",
                },
            },
            "required": ["file_id"],
        }

    async def execute(self, file_id: str, **kwargs) -> str:
        meta, err = _resolve_file(self.engine, file_id)
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

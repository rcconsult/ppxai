"""
PDF tools for multimodal attachments.

Phase 2.8 (v1.17.4). First consumer of SessionFileStore's `get(file_id)`
API. Two tools that let the model read PDFs the user has attached via
`/attach doc.pdf` or the web/VSCode file picker:

    read_pdf(file_id, pages="all")
        → extract text from one or all pages, return as plain text

    get_pdf_page_image(file_id, page, dpi=150)
        → rasterize a single page to a base64 PNG, returned as a data
          URI the model can consume via a follow-up vision turn

Both tools resolve `file_id` through the engine's SessionFileStore:
`engine.file_store.get(file_id) -> Path`, then read the bytes off disk.
This keeps the tools stateless — they never hold on to file bytes, and
they fail cleanly when the user removes an attachment via /attach remove
(future Phase 2.1b) or clears the session.

The module is guarded by `try: import pypdf` at registration time — on
installs without the `[data]` extras group, the tools simply don't
register and the model doesn't see them, matching the pattern used by
container tools and other optional capabilities.
"""

from __future__ import annotations

import base64
import io
from typing import Any, List, Optional, Tuple

from ...types import ToolEngineProtocol, ToolManagerProtocol
from ..base import BaseTool


# Maximum characters to return from read_pdf per call. PDFs with thousands
# of pages would otherwise blow past provider context windows and/or
# produce unreadable walls of text. The limit matches the default
# `max_injection_kb=100` used elsewhere in the engine.
_MAX_TEXT_CHARS = 100_000

# Default DPI for page rasterization. 150 is a good balance between
# readability and base64 payload size — a typical 8.5x11 page at 150 DPI
# is ~1275x1650 pixels, which encodes to ~300 KB as PNG.
_DEFAULT_DPI = 150
_MAX_DPI = 300  # Cap to prevent runaway memory use on huge pages


def _parse_pages_spec(spec: str, total_pages: int) -> List[int]:
    """Parse a pages selector into a sorted list of 0-based page indices.

    Accepts:
        "all"           → every page
        "3"             → single page (1-indexed in input, 0-indexed out)
        "2-5"           → inclusive range
        "1,3,5-7"       → comma-separated mix of singles and ranges

    Raises:
        ValueError: on malformed input or out-of-range page numbers.
                    The tool wrapper catches this and returns a friendly
                    error message to the model instead of raising.
    """
    if not spec or spec.lower() == "all":
        return list(range(total_pages))

    indices: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_str, end_str = chunk.split("-", 1)
            start = int(start_str.strip())
            end = int(end_str.strip())
            if start < 1 or end < 1 or start > end:
                raise ValueError(f"invalid page range: {chunk!r}")
            for page in range(start, end + 1):
                if page > total_pages:
                    raise ValueError(
                        f"page {page} out of range (document has {total_pages} pages)"
                    )
                indices.add(page - 1)
        else:
            page = int(chunk)
            if page < 1 or page > total_pages:
                raise ValueError(
                    f"page {page} out of range (document has {total_pages} pages)"
                )
            indices.add(page - 1)

    if not indices:
        raise ValueError(f"empty page selection: {spec!r}")
    return sorted(indices)


def _resolve_file(engine: Any, file_id: str) -> Tuple[Optional[Any], Optional[str]]:
    """Look up a file_id in the engine's SessionFileStore.

    Returns (FileMetadata, None) on success or (None, error_message) on
    failure. Handles missing file_store (engine doesn't have one),
    unknown file_id (user cleared the session), and on-disk path
    disappearing between registration and tool invocation.
    """
    file_store = getattr(engine, "file_store", None)
    if file_store is None:
        return None, (
            "No SessionFileStore available on the engine. PDF tools require "
            "the file store to resolve file_id references."
        )

    meta = file_store.get_metadata(file_id)
    if meta is None:
        return None, (
            f"Unknown file_id: {file_id!r}. The attachment may have been "
            "removed or the session cleared. Ask the user to re-attach."
        )

    if not meta.path.exists():
        return None, (
            f"File for {file_id!r} is missing on disk at {meta.path}. "
            "The session may be in an inconsistent state."
        )

    return meta, None


# =============================================================================
# ReadPdfTool — text extraction
# =============================================================================


class ReadPdfTool(BaseTool):
    """Extract text from one or more pages of a user-attached PDF.

    Resolves the `file_id` through SessionFileStore, opens the PDF with
    pypdf, and returns extracted text for the requested pages. The tool
    is read-only and safe — no consent gate is required because the user
    already explicitly attached the file.
    """

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "read_pdf"
        self.description = (
            "Extract text from a PDF the user has attached to the conversation. "
            "Use this to read the content of PDF files the user has sent you via "
            "/attach or file upload. Pass the 'file_id' from the <uploaded_file> "
            "reference in the conversation context. Optionally restrict to specific "
            "pages with the 'pages' parameter (e.g., '1', '2-5', '1,3,5-7', or 'all')."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": (
                        "The file_id from the <uploaded_file file_id=\"...\"> "
                        "reference block in the conversation context."
                    ),
                },
                "pages": {
                    "type": "string",
                    "description": (
                        "Pages to extract. Accepts 'all' (default), a single "
                        "page like '3', a range like '2-5', or a comma-separated "
                        "mix like '1,3,5-7'. Page numbers are 1-indexed."
                    ),
                    "default": "all",
                },
            },
            "required": ["file_id"],
        }

    async def execute(self, file_id: str, pages: str = "all", **kwargs) -> str:
        # Resolve file_id via the engine's SessionFileStore.
        meta, err = _resolve_file(self.engine, file_id)
        if err:
            return f"Error: {err}"

        if meta.media_type != "application/pdf":
            return (
                f"Error: file_id {file_id!r} is not a PDF "
                f"(media_type={meta.media_type!r}). Use the correct extraction "
                f"tool for this file type."
            )

        # Import pypdf lazily — it's in the [data] extras group.
        try:
            import pypdf  # noqa: PLC0415
        except ImportError:
            return (
                "Error: pypdf is not installed. PDF extraction requires the "
                "[data] extras group: pip install 'ppxai[data]'"
            )

        try:
            reader = pypdf.PdfReader(str(meta.path))
        except Exception as exc:
            return f"Error opening PDF {meta.name!r}: {exc}"

        total_pages = len(reader.pages)
        if total_pages == 0:
            return f"{meta.name}: empty PDF (0 pages)."

        try:
            page_indices = _parse_pages_spec(pages, total_pages)
        except ValueError as exc:
            return f"Error parsing pages={pages!r}: {exc}"

        chunks: List[str] = [f"# {meta.name} ({total_pages} pages total)"]
        total_chars = len(chunks[0])
        truncated = False

        for idx in page_indices:
            try:
                text = reader.pages[idx].extract_text() or ""
            except Exception as exc:
                # A single bad page shouldn't abort the whole read.
                text = f"[Error extracting page {idx + 1}: {exc}]"

            header = f"\n\n## Page {idx + 1}\n\n"
            page_block = header + text.strip()

            if total_chars + len(page_block) > _MAX_TEXT_CHARS:
                # Truncate gracefully — keep what we have, signal the cap.
                remaining = _MAX_TEXT_CHARS - total_chars
                if remaining > len(header) + 100:
                    chunks.append(header + text[: remaining - len(header) - 20].rstrip())
                truncated = True
                break

            chunks.append(page_block)
            total_chars += len(page_block)

        result = "\n".join(chunks)
        if truncated:
            result += (
                f"\n\n[Output truncated at {_MAX_TEXT_CHARS:,} chars. "
                f"Use pages=<range> to read more specific sections.]"
            )
        return result


# =============================================================================
# GetPdfPageImageTool — page rasterization
# =============================================================================


class GetPdfPageImageTool(BaseTool):
    """Rasterize a single PDF page to a base64 PNG data URI.

    Used when a page contains diagrams, tables, or visual content that
    doesn't survive text extraction. The returned data URI can be
    embedded in a follow-up vision turn, letting a vision-capable model
    "see" the page.

    Requires pdf2image + poppler (system binary). On installs without
    poppler, the tool returns a clear error pointing at the install
    instructions rather than crashing with an obscure subprocess error.
    """

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "get_pdf_page_image"
        self.description = (
            "Rasterize a single page of an attached PDF to a PNG image. Use this "
            "when text extraction loses important visual information — diagrams, "
            "charts, tables, or formatted layouts. Returns a base64-encoded data "
            "URI the vision-capable model can see on the next turn. Pass the "
            "'file_id' from the <uploaded_file> reference and the 1-indexed page "
            "number."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": (
                        "The file_id from the <uploaded_file file_id=\"...\"> "
                        "reference block in the conversation context."
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "1-indexed page number to rasterize.",
                },
                "dpi": {
                    "type": "integer",
                    "description": (
                        f"Resolution in dots per inch. Default {_DEFAULT_DPI}. "
                        f"Higher values give sharper images at the cost of "
                        f"larger base64 payloads; capped at {_MAX_DPI}."
                    ),
                    "default": _DEFAULT_DPI,
                },
            },
            "required": ["file_id", "page"],
        }

    async def execute(
        self,
        file_id: str,
        page: int,
        dpi: int = _DEFAULT_DPI,
        **kwargs,
    ) -> str:
        meta, err = _resolve_file(self.engine, file_id)
        if err:
            return f"Error: {err}"

        if meta.media_type != "application/pdf":
            return (
                f"Error: file_id {file_id!r} is not a PDF "
                f"(media_type={meta.media_type!r})."
            )

        if page < 1:
            return f"Error: page must be >= 1 (got {page})"

        # Clamp dpi to the allowed range and coerce type defensively —
        # model-supplied values may be strings.
        try:
            dpi_int = max(50, min(_MAX_DPI, int(dpi)))
        except (TypeError, ValueError):
            dpi_int = _DEFAULT_DPI

        # pdf2image requires poppler at runtime — a system dependency we
        # can't install via pip. If the import works but conversion
        # fails, the error message below tells the user how to recover.
        try:
            from pdf2image import convert_from_path  # noqa: PLC0415
            from pdf2image.exceptions import (  # noqa: PLC0415
                PDFInfoNotInstalledError,
                PDFPageCountError,
                PDFSyntaxError,
            )
        except ImportError:
            return (
                "Error: pdf2image is not installed. Page rasterization requires "
                "the [data] extras group: pip install 'ppxai[data]'"
            )

        try:
            images = convert_from_path(
                str(meta.path),
                dpi=dpi_int,
                first_page=page,
                last_page=page,
            )
        except PDFInfoNotInstalledError:
            return (
                "Error: poppler is not installed. pdf2image requires poppler as "
                "a system dependency:\n"
                "  macOS:   brew install poppler\n"
                "  Debian:  apt install poppler-utils\n"
                "  Windows: download from https://github.com/oschwartz10612/poppler-windows"
            )
        except PDFPageCountError as exc:
            return f"Error: {exc}. Check that page {page} is in range."
        except PDFSyntaxError as exc:
            return f"Error: PDF {meta.name!r} has invalid syntax: {exc}"
        except Exception as exc:  # pragma: no cover — defensive
            return f"Error rasterizing page {page} of {meta.name!r}: {exc}"

        if not images:
            return f"Error: pdf2image returned no images for page {page}."

        img = images[0]
        width, height = img.size

        # Encode the PIL image to PNG bytes in-memory, then base64 for
        # data URI embedding. PNG is lossless and universally supported
        # by every vision-capable provider.
        buf = io.BytesIO()
        try:
            img.save(buf, format="PNG")
        except Exception as exc:
            return f"Error encoding page {page} as PNG: {exc}"
        png_bytes = buf.getvalue()
        b64 = base64.b64encode(png_bytes).decode("ascii")

        # Return a structured summary plus the data URI. Including both
        # lets the model know the dimensions + size without having to
        # decode the image, and gives it a clear hint to include the
        # data URI in its next message as an image_url content part.
        size_kb = len(png_bytes) / 1024
        return (
            f"Rasterized page {page} of {meta.name}:\n"
            f"- Dimensions: {width}x{height} pixels\n"
            f"- DPI: {dpi_int}\n"
            f"- Size: {size_kb:.1f} KB PNG\n"
            f"- Data URI: data:image/png;base64,{b64}\n\n"
            f"Include this data URI as an image_url content part in your next "
            f"response if you want to analyze the page visually."
        )


# =============================================================================
# Registration
# =============================================================================


def register_tools(manager: ToolManagerProtocol, engine: ToolEngineProtocol) -> bool:
    """Register PDF tools with the manager.

    Guarded by a pypdf import check — if the [data] extras group is not
    installed, PDF tools silently don't register and the model simply
    doesn't see them. pdf2image is checked inside the tool handler so
    partial installs (pypdf without poppler) still allow text extraction.

    Args:
        manager: ToolManager instance.
        engine: EngineClient — required because the tools resolve
                `file_id` through `engine.file_store`.

    Returns:
        True if tools were registered, False if dependencies missing.
    """
    try:
        import pypdf  # noqa: F401, PLC0415
    except ImportError:
        return False

    if engine is None:
        return False

    manager.register_tool(ReadPdfTool(engine))
    manager.register_tool(GetPdfPageImageTool(engine))
    return True


__all__ = [
    "ReadPdfTool",
    "GetPdfPageImageTool",
    "register_tools",
]

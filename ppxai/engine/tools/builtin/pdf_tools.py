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


def _resolve_file(
    engine: Any,
    file_id: Optional[str] = None,
    path: Optional[str] = None,
) -> Tuple[Optional[Any], Optional[str]]:
    """Resolve a file reference via the unified engine resolver.

    Accepts EITHER `file_id` (SessionFileStore chat attachment) or
    `path` (workspace file). v1.18.7 — see `engine.file_ref` for the
    full resolution rules. Kept as a thin module-level shim so existing
    test fixtures using `SimpleNamespace(file_store=store)` keep
    working unchanged.
    """
    from ...file_ref import resolve_file_reference
    return resolve_file_reference(engine, file_id=file_id, path=path)


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
            "Extract text from a PDF. Use this for PDF files attached to the "
            "conversation OR for workspace PDFs visible in the file tree. "
            "Pass either 'file_id' (chat attachment from /attach or upload — "
            "revived from the session cache on reload) or 'path' (workspace "
            "file, addressable from any session) — exactly one is required. "
            "Optionally restrict to specific pages with 'pages' "
            "(e.g., '1', '2-5', '1,3,5-7', or 'all')."
        )
        from ...file_ref import FILE_REF_PROPERTIES
        self.parameters = {
            "type": "object",
            "properties": {
                **FILE_REF_PROPERTIES,
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
            "required": [],
        }

    async def execute(
        self,
        file_id: Optional[str] = None,
        path: Optional[str] = None,
        pages: str = "all",
        **kwargs,
    ) -> str:
        # Resolve either reference via the unified resolver.
        meta, err = _resolve_file(self.engine, file_id=file_id, path=path)
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

    Uses pypdfium2 — pure-wheel bindings to Google's PDFium, bundled
    via the [data] extras. No system binary required (replaces the
    pre-v1.18.1 pdf2image + poppler stack), so PyInstaller binaries
    work out-of-the-box on every platform.
    """

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "get_pdf_page_image"
        self.description = (
            "Rasterize a single page of a PDF to a PNG image. Use this when "
            "text extraction loses important visual information — diagrams, "
            "charts, tables, or formatted layouts. Returns a base64-encoded "
            "data URI the vision-capable model can see on the next turn. "
            "Pass either 'file_id' (chat attachment) or 'path' (workspace "
            "file) — exactly one is required — plus the 1-indexed page number."
        )
        from ...file_ref import FILE_REF_PROPERTIES
        self.parameters = {
            "type": "object",
            "properties": {
                **FILE_REF_PROPERTIES,
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
            "required": ["page"],
        }

    async def execute(
        self,
        page: int,
        file_id: Optional[str] = None,
        path: Optional[str] = None,
        dpi: int = _DEFAULT_DPI,
        **kwargs,
    ) -> str:
        meta, err = _resolve_file(self.engine, file_id=file_id, path=path)
        if err:
            return f"Error: {err}"

        if meta.media_type != "application/pdf":
            return (
                f"Error: {meta.name!r} is not a PDF "
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

        # v1.18.1: pypdfium2 replaces pdf2image + poppler. Pure wheel,
        # no system binary, so PyInstaller binaries are self-contained.
        try:
            import pypdfium2 as pdfium  # noqa: PLC0415
        except ImportError:
            return (
                "Error: pypdfium2 is not installed. Page rasterization "
                "requires the [data] extras group: pip install 'ppxai[data]'"
            )

        pdf = None
        pdf_page = None
        bitmap = None
        try:
            try:
                pdf = pdfium.PdfDocument(str(meta.path))
            except pdfium.PdfiumError as exc:
                return f"Error: could not open PDF {meta.name!r}: {exc}"

            page_count = len(pdf)
            if page > page_count:
                return (
                    f"Error: page {page} out of range "
                    f"(PDF has {page_count} page{'s' if page_count != 1 else ''})."
                )

            try:
                pdf_page = pdf[page - 1]  # pypdfium2 is 0-indexed
                # `scale` in pypdfium2 is relative to 72 DPI (PDF's
                # internal resolution). dpi=150 → scale=150/72.
                bitmap = pdf_page.render(scale=dpi_int / 72)
                img = bitmap.to_pil()
            except pdfium.PdfiumError as exc:
                return f"Error: PDF {meta.name!r} has invalid syntax: {exc}"
            except Exception as exc:  # pragma: no cover — defensive
                return f"Error rasterizing page {page} of {meta.name!r}: {exc}"

            width, height = img.size
        finally:
            # Order matters: bitmap → page → document. pypdfium2's
            # context isn't reference-counted across these objects.
            if bitmap is not None:
                bitmap.close()
            if pdf_page is not None:
                pdf_page.close()
            if pdf is not None:
                pdf.close()

        # Encode the PIL image to PNG bytes in-memory.
        buf = io.BytesIO()
        try:
            img.save(buf, format="PNG")
        except Exception as exc:
            return f"Error encoding page {page} as PNG: {exc}"
        png_bytes = buf.getvalue()
        size_kb = len(png_bytes) / 1024

        # v1.18.7: tool-produced multimodal artifacts go through the
        # SessionFileStore — same lifecycle as user-uploaded chat
        # attachments (revived from cache on session reload). Returning
        # the inline base64 data URI used to cost ~80-110K tokens per
        # call (rasterized pages at 150 DPI), enough to blow the
        # context window on a single iteration. Now we save the PNG
        # and return a compact reference; visual analysis is a
        # follow-up tool call.
        file_store = getattr(self.engine, "file_store", None)
        if file_store is None:
            # No store (some test fixtures) — fall back to inline data
            # URI for compat.
            b64 = base64.b64encode(png_bytes).decode("ascii")
            return (
                f"Rasterized page {page} of {meta.name}:\n"
                f"- Dimensions: {width}x{height} pixels\n"
                f"- DPI: {dpi_int}\n"
                f"- Size: {size_kb:.1f} KB PNG\n"
                f"- Data URI: data:image/png;base64,{b64}\n"
            )

        from pathlib import Path
        artifact_name = f"{Path(meta.name).stem}_page_{page}.png"
        try:
            saved = file_store.save(
                artifact_name, png_bytes, media_type="image/png"
            )
        except OSError as exc:
            return f"Error: failed to save rasterized page: {exc}"

        return (
            f"Rasterized page {page} of {meta.name}:\n"
            f"- Dimensions: {width}x{height} pixels\n"
            f"- DPI: {dpi_int}\n"
            f"- Size: {size_kb:.1f} KB PNG\n"
            f"- Saved to session attachments: file_id={saved.file_id}\n\n"
            f"The PNG is now in the session file store (same lifecycle as "
            f"chat-uploaded files, revived on session reload). For visual "
            f"analysis, use a tool that accepts a file_id rather than "
            f"re-rasterizing — the bytes are kept once."
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

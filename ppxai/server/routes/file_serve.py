"""
Raw file serving endpoint for SessionFileStore files.

Serves binary file bytes with correct Content-Type so browsers can
render images, PDFs, and other media inline. Used by:
- Web app image thumbnails in chat messages
- Web app file preview panel for attached images
- VSCode webview image rendering

    GET /files/serve/{file_id}
    → 200 with Content-Type: image/png (or whatever the stored type is)
    → 404 if file_id unknown or bytes missing from disk

    GET /files/preview/{file_id}?slide=N&total=true
    → 200 PNG for PPTX slide N (rendered via LibreOffice headless)
    → 200 PDF for Word documents (.docx/.doc, converted via LibreOffice)
    → JSON {"total": N, "name": "...", "type": "pdf"} when total=true (Word)
    → JSON {"total": N, "name": "..."} when total=true (PPTX)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ..state import Session, get_session_or_query
from .files import OFFICE_PREVIEWABLE_EXTENSIONS, render_office_preview

router = APIRouter()


@router.get("/files/serve/{file_id}")
async def serve_file(
    file_id: str,
    s: Session = Depends(get_session_or_query),
):
    """Serve raw bytes of a SessionFileStore file by file_id.

    Returns the file with its canonical Content-Type so browsers can
    render images inline as `<img src="/files/serve/<file_id>">`.
    """
    file_store = getattr(s.engine, "file_store", None)
    if file_store is None:
        raise HTTPException(status_code=503, detail="File store not available")

    meta = file_store.get_metadata(file_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown file_id: {file_id}")

    if not meta.path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File bytes missing for {file_id}",
        )

    try:
        data = meta.path.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {exc}")

    return Response(
        content=data,
        media_type=meta.media_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{meta.name}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


_WORD_MIMES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}
_WORD_EXTENSIONS = {".docx", ".doc"}


def is_word_document(meta) -> bool:
    """Return True if the file metadata indicates a Word document.

    Pure predicate — reads `meta.media_type` and `meta.name` only.
    Public (v1.18.0 Phase 5g) so mimetype-vs-extension fallback
    logic can be unit-tested directly.
    """
    if meta.media_type and meta.media_type in _WORD_MIMES:
        return True
    if meta.name:
        from pathlib import PurePosixPath
        ext = PurePosixPath(meta.name).suffix.lower()
        if ext in _WORD_EXTENSIONS:
            return True
    return False


# convert_docx_to_pdf moved to ppxai.common.docx_to_pdf in v1.18.0
# Phase 5g so the Word-preview route can test against a documented
# public contract rather than reaching into a route-private helper.


@router.get("/files/preview/{file_id}")
async def preview_file(
    file_id: str,
    slide: int = Query(1, ge=1, description="Slide number (1-based)"),
    total: bool = Query(False, description="Return only the total slide count"),
    s: Session = Depends(get_session_or_query),
):
    """Office preview — file_id-based variant. Resolves the file_id to a
    stored file, then delegates to the shared `render_office_preview` helper
    so this route and the path-based `/files/preview` (files.py) return one
    identical contract — including graceful 200 text_fallback when LibreOffice
    is missing (was a hard 503 here before item 26).

    - GET /files/preview/{file_id}?total=true
        → {"total": N, "name": "...", "type": "...", "kind": "...", "libreoffice_available": bool}
    - GET /files/preview/{file_id}?slide=3 → PNG bytes for slide N (PPTX)
    - GET /files/preview/{file_id}?slide=1 → PDF bytes (Word)
    - LibreOffice missing → 200 {"type": "text_fallback", ...}
    """
    file_store = getattr(s.engine, "file_store", None)
    if file_store is None:
        raise HTTPException(status_code=503, detail="File store not available")

    meta = file_store.get_metadata(file_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown file_id: {file_id}")
    if not meta.path.exists():
        raise HTTPException(status_code=404, detail="File bytes missing")

    # meta.path is content-addressed and may lack an extension, so derive the
    # authoritative office extension from meta.name / media_type (the same
    # signals is_word_document uses) before handing off to the shared helper.
    from pathlib import PurePosixPath
    ext = PurePosixPath(meta.name or "").suffix.lower()
    if ext not in OFFICE_PREVIEWABLE_EXTENSIONS:
        ext = ".docx" if is_word_document(meta) else ".pptx"

    return render_office_preview(
        meta.path, meta.name, ext, meta.path.parent / "preview",
        slide=slide, total=total,
    )

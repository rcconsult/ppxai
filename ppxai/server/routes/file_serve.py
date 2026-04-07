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
    → JSON {"total": N} when total=true
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from ..state import Session, get_session

router = APIRouter()


@router.get("/files/serve/{file_id}")
async def serve_file(
    file_id: str,
    s: Session = Depends(get_session),
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


@router.get("/files/preview/{file_id}")
async def preview_file(
    file_id: str,
    slide: int = Query(1, ge=1, description="Slide number (1-based)"),
    total: bool = Query(False, description="Return only the total slide count"),
    s: Session = Depends(get_session),
):
    """Render a PPTX slide as PNG via LibreOffice headless.

    Used by the web app split panel slide viewer. Slides are rendered
    once and cached alongside the source file in SessionFileStore.

    - GET /files/preview/{file_id}?total=true → {"total": N, "name": "..."}
    - GET /files/preview/{file_id}?slide=3 → PNG bytes for slide 3
    """
    file_store = getattr(s.engine, "file_store", None)
    if file_store is None:
        raise HTTPException(status_code=503, detail="File store not available")

    meta = file_store.get_metadata(file_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown file_id: {file_id}")
    if not meta.path.exists():
        raise HTTPException(status_code=404, detail="File bytes missing")

    from ...engine.tools.builtin.pptx_tools import render_pptx_slides, _libreoffice_available

    if not _libreoffice_available():
        raise HTTPException(status_code=503, detail="LibreOffice not installed")

    cache_dir = meta.path.parent / "slides"
    try:
        pngs = render_pptx_slides(meta.path, cache_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Render failed: {exc}")

    if not pngs:
        raise HTTPException(status_code=500, detail="No slides rendered")

    if total:
        return JSONResponse({"total": len(pngs), "name": meta.name})

    if slide < 1 or slide > len(pngs):
        raise HTTPException(status_code=404, detail=f"Slide {slide} out of range (1-{len(pngs)})")

    png_bytes = pngs[slide - 1].read_bytes()
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )

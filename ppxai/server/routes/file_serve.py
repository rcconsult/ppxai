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
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

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

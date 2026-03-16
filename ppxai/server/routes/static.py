"""
Web UI static file serving endpoints.

Must be registered after all API routes to avoid path conflicts.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

# Web UI directory (installed by ppxai-desktop or manually)
WEB_UI_DIR = Path.home() / '.ppxai' / 'web'

router = APIRouter()


@router.get("/")
async def serve_index():
    """Serve the web UI index.html."""
    index_file = WEB_UI_DIR / 'index.html'
    if index_file.exists():
        return FileResponse(index_file, media_type='text/html')
    return HTMLResponse(
        content="<h1>ppxai Web UI not found</h1><p>Install web UI to ~/.ppxai/web/</p>",
        status_code=404
    )


@router.get("/app.js")
async def serve_app_js():
    """Serve app.js with no-cache headers to ensure fresh content."""
    return FileResponse(
        WEB_UI_DIR / 'app.js',
        media_type='application/javascript',
        headers={"Cache-Control": "no-cache, must-revalidate"}
    )


@router.get("/styles.css")
async def serve_styles_css():
    """Serve styles.css with no-cache headers."""
    return FileResponse(
        WEB_UI_DIR / 'styles.css',
        media_type='text/css',
        headers={"Cache-Control": "no-cache, must-revalidate"}
    )


@router.get("/lib/{filename:path}")
async def serve_lib(filename: str):
    """Serve library files."""
    file_path = WEB_UI_DIR / 'lib' / filename
    if file_path.exists() and file_path.is_file():
        suffix = file_path.suffix.lower()
        content_types = {
            '.js': 'application/javascript',
            '.css': 'text/css',
            '.json': 'application/json',
        }
        media_type = content_types.get(suffix, 'application/octet-stream')
        return FileResponse(file_path, media_type=media_type)
    raise HTTPException(status_code=404, detail=f"Library file not found: {filename}")


@router.get("/shared/{filename:path}")
async def serve_shared(filename: str):
    """Serve shared module files (v1.13.10)."""
    file_path = WEB_UI_DIR / 'shared' / filename
    if file_path.exists() and file_path.is_file():
        suffix = file_path.suffix.lower()
        content_types = {
            '.js': 'application/javascript',
            '.css': 'text/css',
            '.json': 'application/json',
        }
        media_type = content_types.get(suffix, 'application/octet-stream')
        return FileResponse(
            file_path, media_type=media_type,
            headers={"Cache-Control": "no-cache, must-revalidate"}
        )
    raise HTTPException(status_code=404, detail=f"Shared file not found: {filename}")


@router.get("/components/{filename:path}")
async def serve_components(filename: str):
    """Serve component files (v1.13.8 data viewers)."""
    file_path = WEB_UI_DIR / 'components' / filename
    if file_path.exists() and file_path.is_file():
        suffix = file_path.suffix.lower()
        content_types = {
            '.js': 'application/javascript',
            '.css': 'text/css',
            '.json': 'application/json',
        }
        media_type = content_types.get(suffix, 'application/octet-stream')
        return FileResponse(file_path, media_type=media_type)
    raise HTTPException(status_code=404, detail=f"Component file not found: {filename}")


@router.get("/styles/{filename:path}")
async def serve_styles(filename: str):
    """Serve additional style files (v1.13.8 data viewers)."""
    file_path = WEB_UI_DIR / 'styles' / filename
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path, media_type='text/css')
    raise HTTPException(status_code=404, detail=f"Style file not found: {filename}")


@router.get("/favicon.ico")
async def serve_favicon_ico():
    """Serve favicon.ico (redirect to favicon.png)."""
    file_path = WEB_UI_DIR / 'favicon.png'
    if file_path.exists():
        return FileResponse(file_path, media_type='image/png')
    raise HTTPException(status_code=404, detail="Favicon not found")


@router.get("/favicon.png")
async def serve_favicon_png():
    """Serve favicon.png."""
    file_path = WEB_UI_DIR / 'favicon.png'
    if file_path.exists():
        return FileResponse(file_path, media_type='image/png')
    raise HTTPException(status_code=404, detail="Favicon not found")

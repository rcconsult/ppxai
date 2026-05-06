"""
Web UI static file serving endpoints.

Must be registered after all API routes to avoid path conflicts.
"""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from ...engine.app_state import SCHEMA as _APP_STATE_SCHEMA

# Web UI directory (installed by ppxai-desktop or manually)
WEB_UI_DIR = Path.home() / '.ppxai' / 'web'

# Canonical AppState schema serialized once at module import. The
# serve_index handler injects this into every `index.html` response
# so `shared/app-state.js` can read `window.APP_STATE_SCHEMA`
# synchronously at module load — no extra fetch round-trip, no async
# bootstrap, no schema-before-clients race condition.
_APP_STATE_SCHEMA_JSON = json.dumps(_APP_STATE_SCHEMA, separators=(',', ':'))
_APP_STATE_SCHEMA_SCRIPT = (
    '<script id="app-state-schema">'
    f'window.APP_STATE_SCHEMA = {_APP_STATE_SCHEMA_JSON};'
    '</script>'
)

router = APIRouter()


@router.get("/")
async def serve_index():
    """Serve the web UI index.html with the canonical AppState schema
    injected into `<head>` before any script that consumes it.

    The injection makes the schema available at
    `window.APP_STATE_SCHEMA` before `shared/app-state.js` runs, so
    the `AppState` class can build its Python→JS field map and
    default values synchronously at module load. No fetch, no async
    bootstrap, no drift — the schema the browser sees is byte-for-byte
    the same object Python loaded from
    `ppxai/engine/app_state_schema.json` at startup.
    """
    index_file = WEB_UI_DIR / 'index.html'
    if not index_file.exists():
        return HTMLResponse(
            content="<h1>ppxai Web UI not found</h1><p>Install web UI to ~/.ppxai/web/</p>",
            status_code=404,
        )

    html = index_file.read_text(encoding='utf-8')

    # Inject the schema script just before </head>. Use replace with
    # count=1 so a web UI that already contains <head> for some reason
    # doesn't get multiple injections.
    injected = f'    {_APP_STATE_SCHEMA_SCRIPT}\n</head>'
    if '</head>' in html:
        html = html.replace('</head>', injected, 1)
    else:
        # Fallback: prepend to body if the HTML doesn't have a proper head.
        html = _APP_STATE_SCHEMA_SCRIPT + html

    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@router.get("/app.js")
async def serve_app_js():
    """Serve app.js with no-cache headers to ensure fresh content.

    Returns 404 with a clear message when the web UI isn't installed
    (matches the behavior of `/`). Without this guard, FileResponse
    raised at send-time and the route returned 500 — surfaced by
    test_server_smoke_e2e on Linux CI where ~/.ppxai/web/ doesn't
    exist.
    """
    file_path = WEB_UI_DIR / 'app.js'
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="app.js not found — install web UI to ~/.ppxai/web/"
        )
    return FileResponse(
        file_path,
        media_type='application/javascript',
        headers={"Cache-Control": "no-cache, must-revalidate"}
    )


@router.get("/styles.css")
async def serve_styles_css():
    """Serve styles.css with no-cache headers.

    Returns 404 when missing — see serve_app_js() for the rationale.
    """
    file_path = WEB_UI_DIR / 'styles.css'
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="styles.css not found — install web UI to ~/.ppxai/web/"
        )
    return FileResponse(
        file_path,
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
    """Serve favicon.ico — multi-resolution ICO when present, else fall
    back to the legacy PNG. Browsers prefer ICO for tabs/bookmarks/
    taskbar pinning because it carries multiple resolutions in one
    file; we keep the PNG fallback so older deployments that haven't
    re-synced ~/.ppxai/web/ still get *something*."""
    ico_path = WEB_UI_DIR / 'favicon.ico'
    if ico_path.exists():
        return FileResponse(ico_path, media_type='image/x-icon')
    png_path = WEB_UI_DIR / 'favicon.png'
    if png_path.exists():
        return FileResponse(png_path, media_type='image/png')
    raise HTTPException(status_code=404, detail="Favicon not found")


@router.get("/favicon.png")
async def serve_favicon_png():
    """Serve favicon.png."""
    file_path = WEB_UI_DIR / 'favicon.png'
    if file_path.exists():
        return FileResponse(file_path, media_type='image/png')
    raise HTTPException(status_code=404, detail="Favicon not found")

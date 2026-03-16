"""
HTML preview endpoints (v1.15.4).

Route order matters: poll and static must be defined BEFORE the catch-all.
"""

import os
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from typing import Optional

from ...common.preview import inject_reload_script, resolve_preview_path, rewrite_asset_paths
from ..state import get_or_create_session

router = APIRouter()


def _extract_session_from_referer(request: Request) -> Optional[str]:
    """Extract session ID from the Referer header's query string.

    When JS inside a preview iframe does fetch('recipes.json'), the browser
    resolves it to /preview/recipes.json with no session param.  But the
    Referer header still points to the parent page URL which *does* contain
    ?session=xxx.  This lets us recover the correct working directory.
    """
    referer = request.headers.get('referer', '')
    if 'session=' in referer:
        qs = parse_qs(urlparse(referer).query)
        ids = qs.get('session', [])
        if ids:
            return ids[0]
    return None


@router.get("/preview/poll/{filepath:path}")
async def preview_poll(
    request: Request,
    filepath: str,
    x_session_id: Optional[str] = Header(None),
    session: Optional[str] = None
):
    """Return file modification time for preview reload polling.

    v1.15.4: Used by the injected reload script to detect file changes.
    Accepts session ID via header (X-Session-Id) or query param (?session=).

    Returns:
        JSON: {"mtime": float}
    """
    sid = x_session_id or session or _extract_session_from_referer(request)
    session_id, engine, _ = await get_or_create_session(sid)
    working_dir = engine.get_working_dir() or os.getcwd()

    try:
        path = resolve_preview_path(filepath, working_dir)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="File not found")

    # Return the newest mtime of HTML file + sibling assets (CSS/JS/images)
    # so that changes to linked stylesheets/scripts also trigger a reload
    mtime = path.stat().st_mtime
    try:
        for sibling in path.parent.iterdir():
            if sibling.is_file() and sibling.suffix.lower() in (
                '.css', '.js', '.html', '.htm', '.json', '.svg', '.png', '.jpg'
            ):
                sib_mtime = sibling.stat().st_mtime
                if sib_mtime > mtime:
                    mtime = sib_mtime
    except OSError:
        pass  # Network/permission errors — fall back to HTML mtime only
    return {"mtime": mtime}


@router.get("/preview/static/{filepath:path}")
async def preview_static(
    request: Request,
    filepath: str,
    x_session_id: Optional[str] = Header(None),
    session: Optional[str] = None
):
    """Serve static assets (CSS/JS/images) referenced by preview HTML.

    v1.15.4: Resolves paths relative to the working directory.
    Accepts session ID via header (X-Session-Id), query param (?session=),
    or extracted from Referer header.

    Returns:
        FileResponse for the static asset with no-cache headers
    """
    sid = x_session_id or session or _extract_session_from_referer(request)
    session_id, engine, _ = await get_or_create_session(sid)
    working_dir = engine.get_working_dir() or os.getcwd()

    try:
        # No extension restriction for static assets
        path = resolve_preview_path(filepath, working_dir, restrict_extension=False)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    # no-cache ensures browser revalidates on every request so live-reload
    # picks up CSS/JS changes immediately instead of serving stale cache
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.get("/preview/{filepath:path}")
async def preview_html(
    request: Request,
    filepath: str,
    x_session_id: Optional[str] = Header(None),
    session: Optional[str] = None
):
    """Serve HTML file with injected reload script, or static assets.

    v1.15.4: The reload script polls /preview/poll/{filepath} for mtime
    changes and triggers a page reload when the file is modified.

    Non-HTML files (e.g., recipes.json fetched by JS in the page) are
    served as static assets so that fetch() calls with relative URLs work
    inside the preview iframe.

    Accepts session ID via header (X-Session-Id), query param (?session=),
    or extracted from Referer header (for JS fetch() calls inside iframe).

    Returns:
        HTMLResponse with injected reload script, or FileResponse for non-HTML
    """
    sid = x_session_id or session or _extract_session_from_referer(request)
    session_id, engine, _ = await get_or_create_session(sid)
    working_dir = engine.get_working_dir() or os.getcwd()

    # First resolve without extension restriction to check if file exists
    try:
        path = resolve_preview_path(filepath, working_dir, restrict_extension=False)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filepath}")
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    # Non-HTML files: serve as static assets (supports JS fetch() calls)
    if path.suffix.lower() not in ('.html', '.htm'):
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    content = path.read_text(encoding='utf-8')
    # Include session in poll URL so reload script uses the right working dir
    # Use relative URLs so preview works behind reverse-proxy path prefixes
    # (e.g. /s/<user>/preview/file.html → relative "poll/file.html" resolves correctly)
    poll_url = f'poll/{filepath}?session={session_id}' if session_id else f'poll/{filepath}'

    # Compute cache buster from newest sibling mtime so browser re-fetches
    # changed CSS/JS instead of using stale cached versions
    cache_ts = str(int(path.stat().st_mtime))
    try:
        for sibling in path.parent.iterdir():
            if sibling.is_file() and sibling.suffix.lower() in (
                '.css', '.js', '.json', '.svg', '.png', '.jpg'
            ):
                sib_ts = str(int(sibling.stat().st_mtime))
                if sib_ts > cache_ts:
                    cache_ts = sib_ts
    except OSError:
        pass

    # Rewrite relative CSS/JS/image paths to use preview/static/ endpoint
    # Uses relative URLs so it works behind reverse-proxy path prefixes
    file_dir = str(PurePosixPath(filepath).parent)
    if file_dir == '.':
        static_base = 'static/'
    else:
        static_base = f'static/{file_dir}/'
    if session_id:
        static_base = f'{static_base}?session={session_id}'
    content = rewrite_asset_paths(content, static_base, cache_buster=cache_ts)

    html = inject_reload_script(content, poll_url)
    return HTMLResponse(content=html)

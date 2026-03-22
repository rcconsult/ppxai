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
    """Extract session ID from the Referer header's query string."""
    referer = request.headers.get('referer', '')
    if 'session=' in referer:
        qs = parse_qs(urlparse(referer).query)
        ids = qs.get('session', [])
        if ids:
            return ids[0]
    return None


async def _resolve_session(request: Request, x_session_id: Optional[str], session: Optional[str]):
    """Resolve session from header, query param, or referer."""
    sid = x_session_id or session or _extract_session_from_referer(request)
    session_id, engine, _ = await get_or_create_session(sid)
    return session_id, engine


@router.get("/preview/poll/{filepath:path}")
async def preview_poll(
    request: Request,
    filepath: str,
    x_session_id: Optional[str] = Header(None),
    session: Optional[str] = None
):
    """Return file modification time for preview reload polling."""
    session_id, engine = await _resolve_session(request, x_session_id, session)
    working_dir = engine.get_working_dir() or os.getcwd()

    try:
        path = resolve_preview_path(filepath, working_dir)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="File not found")

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
        pass
    return {"mtime": mtime}


@router.get("/preview/__assets__/{filepath:path}")
async def preview_static(
    request: Request,
    filepath: str,
    x_session_id: Optional[str] = Header(None),
    session: Optional[str] = None
):
    """Serve static assets (CSS/JS/images) referenced by preview HTML."""
    session_id, engine = await _resolve_session(request, x_session_id, session)
    working_dir = engine.get_working_dir() or os.getcwd()

    try:
        path = resolve_preview_path(filepath, working_dir, restrict_extension=False)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.get("/preview/{filepath:path}")
async def preview_html(
    request: Request,
    filepath: str,
    x_session_id: Optional[str] = Header(None),
    session: Optional[str] = None
):
    """Serve HTML file with injected reload script, or static assets."""
    session_id, engine = await _resolve_session(request, x_session_id, session)
    working_dir = engine.get_working_dir() or os.getcwd()

    try:
        path = resolve_preview_path(filepath, working_dir, restrict_extension=False)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filepath}")
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if path.suffix.lower() not in ('.html', '.htm'):
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    content = path.read_text(encoding='utf-8')
    poll_url = f'/preview/poll/{filepath}?session={session_id}' if session_id else f'/preview/poll/{filepath}'

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

    file_dir = str(PurePosixPath(filepath).parent)
    if file_dir == '.':
        static_base = '/preview/__assets__/'
    else:
        static_base = f'/preview/__assets__/{file_dir}/'
    if session_id:
        static_base = f'{static_base}?session={session_id}'
    content = rewrite_asset_paths(content, static_base, cache_buster=cache_ts)

    html = inject_reload_script(content, poll_url)
    return HTMLResponse(content=html)

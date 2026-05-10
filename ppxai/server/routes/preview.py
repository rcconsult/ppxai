"""
HTML preview endpoints (v1.15.4, v1.17.1 --serve flag).

Route order matters: poll and static must be defined BEFORE the catch-all.

v1.18.5: spawn-and-drain logic for `--serve` lives in
`ppxai/engine/preview_backend.py` (transport-agnostic) so TUI clients
share the same code path. This route is now a thin HTTP wrapper.
"""

import os
import time
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from typing import Optional

from ...common.logger import get_logger
from ...common.preview import inject_reload_script, resolve_preview_path, rewrite_asset_paths
from ...engine.preview_backend import (
    PreviewBackendError,
    start_proxied_backend,
    start_served_backend,
    wait_for_port,
)
from ..models import PreviewServeRequest
from ..state import (
    Session, get_or_create_session, get_session,
    PreviewBackend, get_preview_backend, set_preview_backend,
    remove_preview_backend, kill_preview_backend,
)

logger = get_logger("server")

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


# === Preview --serve: full-stack backend management (v1.17.1) ===
# v1.18.5: spawn/drain/port-detection helpers moved to
# `ppxai/engine/preview_backend.py` so TUI clients share the path.

@router.post("/preview/serve")
async def start_preview_serve(
    request: PreviewServeRequest,
    s: Session = Depends(get_session),
):
    """Start a backend process for full-stack preview.

    Thin HTTP wrapper around `engine.preview_backend.start_served_backend`.
    The actual spawn-and-drain logic lives in the engine helper so TUI
    clients (Rich `ppxai`, Textual `ppxaide`) share the path.
    """
    working_dir = s.engine.get_working_dir() or os.getcwd()

    # Kill any existing backend for this session.
    existing = get_preview_backend(s.id)
    if existing:
        await kill_preview_backend(existing)
        remove_preview_backend(s.id)

    try:
        backend = await start_served_backend(
            command=request.command,
            port=request.port,
            working_dir=working_dir,
        )
    except PreviewBackendError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    set_preview_backend(s.id, backend)

    return {
        "url": backend.url,
        "port": backend.port,
        "command": backend.command,
        "pid": backend.process.pid if backend.process else None,
    }


@router.post("/preview/serve/stop")
async def stop_preview_serve(s: Session = Depends(get_session)):
    """Stop the backend process for this session's preview."""
    backend = remove_preview_backend(s.id)
    if not backend:
        return {"stopped": False, "reason": "no backend running"}

    logger.info(f"Preview serve: stopping pid {backend.process.pid} ({backend.command})")
    await kill_preview_backend(backend)

    return {"stopped": True, "port": backend.port, "command": backend.command}


@router.get("/preview/serve/status")
async def preview_serve_status(s: Session = Depends(get_session)):
    """Get the status of the preview backend for this session."""
    backend = get_preview_backend(s.id)
    if not backend:
        return {"running": False}

    # Check if process is still alive
    alive = backend.process.returncode is None
    if not alive:
        remove_preview_backend(s.id)

    # Update last_seen for orphan watchdog
    backend.last_seen = time.time()

    return {
        "running": alive,
        "url": backend.url,
        "port": backend.port,
        "command": backend.command,
        "pid": backend.process.pid,
    }


# === Preview --proxy: reverse proxy to local port (v1.17.1) ===
# Used in K8s where user starts backend from /terminal, ppxai proxies to it.

# Module-level dict tracking active proxy ports per session
_proxy_ports: dict[str, int] = {}


@router.post("/preview/proxy/start")
async def start_preview_proxy(
    request: Request,
    s: Session = Depends(get_session),
):
    """Start proxying to a local port (no process management).

    The user starts their backend separately (e.g., from /terminal).
    This just verifies the port is reachable and enables proxying.
    """
    body = await request.json()
    port = int(body.get("port", 8000))

    # Check if port is reachable.
    if not await wait_for_port(port, timeout=3.0):
        raise HTTPException(
            status_code=400,
            detail=f"Port {port} is not reachable. Start your backend first (e.g., from /terminal).",
        )

    _proxy_ports[s.id] = port
    url = f"http://localhost:{port}"
    logger.info(f"Preview proxy: proxying to {url} (session={s.id})")

    return {"url": url, "port": port}


@router.post("/preview/proxy/stop")
async def stop_preview_proxy(s: Session = Depends(get_session)):
    """Stop proxying (does not kill any process)."""
    port = _proxy_ports.pop(s.id, None)
    if port is None:
        return {"stopped": False, "reason": "no proxy active"}
    logger.info(f"Preview proxy: stopped proxying to port {port} (session={s.id})")
    return {"stopped": True, "port": port}


@router.api_route("/preview/proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def preview_proxy_passthrough(
    request: Request,
    path: str,
    x_session_id: Optional[str] = Header(None),
    session: Optional[str] = None,
):
    """Reverse proxy requests to the user's backend.

    Routes /preview/proxy/* to localhost:{port}/* for the active session.
    Supports all HTTP methods so the previewed app's API calls work.
    """
    sid = x_session_id or session or _extract_session_from_referer(request)
    port = _proxy_ports.get(sid)
    if port is None:
        raise HTTPException(status_code=404, detail="No proxy active for this session")

    target_url = f"http://localhost:{port}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # Forward the request
    body = await request.body()
    headers = dict(request.headers)
    # Remove hop-by-hop headers
    for h in ("host", "connection", "transfer-encoding"):
        headers.pop(h, None)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Backend on port {port} is not reachable")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Backend on port {port} timed out")

    # Return the proxied response
    from starlette.responses import Response
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=dict(response.headers),
    )


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

    # Use relative URLs so they resolve correctly behind any reverse proxy
    # (e.g., browser at /s/user/preview/file.html → "poll/file.html" resolves
    # to /s/user/preview/poll/file.html through the ingress automatically).
    poll_url = f'poll/{filepath}?session={session_id}' if session_id else f'poll/{filepath}'

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
        static_base = '__assets__/'
    else:
        static_base = f'__assets__/{file_dir}/'
    if session_id:
        static_base = f'{static_base}?session={session_id}'
    content = rewrite_asset_paths(content, static_base, cache_buster=cache_ts)

    html = inject_reload_script(content, poll_url)
    return HTMLResponse(content=html)

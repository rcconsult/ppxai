"""
HTML preview endpoints (v1.15.4, v1.17.1 --serve flag).

Route order matters: poll and static must be defined BEFORE the catch-all.
"""

import asyncio
import json
import os
import re
import shlex
import time
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from typing import Optional

from ...common.logger import get_logger
from ...common.preview import inject_reload_script, resolve_preview_path, rewrite_asset_paths
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

# Port detection patterns for common frameworks
_PORT_PATTERNS = [
    re.compile(r'https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d+)'),
    re.compile(r'(?:listening|running|started|serving)\s+(?:on\s+)?(?:port\s+)?(\d+)', re.IGNORECASE),
    re.compile(r'port\s*[:=]\s*(\d+)', re.IGNORECASE),
]

_FRAMEWORK_DEFAULTS = {
    'uvicorn': 8000, 'fastapi': 8000, 'gunicorn': 8000,
    'flask': 5000, 'django': 8000,
    'express': 3000, 'next': 3000, 'node': 3000,
    'vite': 5173, 'webpack': 8080, 'http-server': 8080,
}


def _detect_command(working_dir: str) -> Optional[str]:
    """Auto-detect the backend start command from project files."""
    wd = Path(working_dir)

    # package.json with start script
    pkg = wd / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            if data.get("scripts", {}).get("start"):
                return "npm start"
        except (json.JSONDecodeError, OSError):
            pass

    # Python files — prefer venv python if available, else python3
    if os.name == "nt":
        venv_python = wd / "venv" / "Scripts" / "python.exe"
        fallback_python = "python"
    else:
        venv_python = wd / "venv" / "bin" / "python"
        fallback_python = "python3"
    # Also check .venv (common convention)
    if not venv_python.exists():
        venv_python = wd / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python = str(venv_python) if venv_python.exists() else fallback_python
    for name in ("main.py", "app.py", "server.py"):
        if (wd / name).exists():
            return f"{python} {name}"

    # Makefile with run target
    makefile = wd / "Makefile"
    if makefile.exists():
        try:
            content = makefile.read_text(encoding="utf-8")
            if re.search(r'^run\s*:', content, re.MULTILINE):
                return "make run"
        except OSError:
            pass

    return None


def _guess_port_from_command(command: str) -> int:
    """Guess default port from the command string."""
    cmd_lower = command.lower()
    for framework, port in _FRAMEWORK_DEFAULTS.items():
        if framework in cmd_lower:
            return port
    # Check for explicit --port or -p flags
    port_match = re.search(r'(?:--port|-p)\s+(\d+)', command)
    if port_match:
        return int(port_match.group(1))
    return 8000  # safe default


async def _detect_port_from_output(process: asyncio.subprocess.Process, collected_output: list, timeout: float = 5.0) -> Optional[int]:
    """Read process stdout/stderr for port announcements.

    Args:
        process: The subprocess to read from
        collected_output: List to append output lines to (for error reporting)
        timeout: Max seconds to wait for port detection
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.returncode is not None:
            return None
        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=0.5)
            if not line:
                continue
            text = line.decode("utf-8", errors="replace")
            collected_output.append(text)
            for pattern in _PORT_PATTERNS:
                m = pattern.search(text)
                if m:
                    return int(m.group(1))
        except asyncio.TimeoutError:
            continue
    return None


async def _wait_for_port(port: int, timeout: float = 10.0) -> bool:
    """Poll localhost:port until it responds or timeout."""
    deadline = time.time() + timeout
    url = f"http://localhost:{port}/"
    while time.time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                await client.get(url)
                return True
        except Exception:
            await asyncio.sleep(0.2)
    return False


@router.post("/preview/serve")
async def start_preview_serve(
    request: PreviewServeRequest,
    s: Session = Depends(get_session),
):
    """Start a backend process for full-stack preview.

    Detects or uses the given command, starts the process, waits for the
    port to become reachable, and returns the backend URL.
    """
    working_dir = s.engine.get_working_dir() or os.getcwd()

    # Kill any existing backend for this session
    existing = get_preview_backend(s.id)
    if existing:
        await kill_preview_backend(existing)
        remove_preview_backend(s.id)

    # Resolve command — normalize python → python3 on macOS/Linux
    command = request.command or _detect_command(working_dir)
    if command and os.name != "nt":
        command = re.sub(r'^python(\s)', r'python3\1', command)
    if not command:
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not auto-detect backend command. "
                "No main.py, app.py, server.py, or package.json with start script found. "
                "Specify the command explicitly: /preview index.html --serve \"python main.py\""
            ),
        )

    # Resolve port
    port = request.port or _guess_port_from_command(command)

    logger.info(f"Preview serve: starting '{command}' in {working_dir} (expected port {port})")

    # Start the process with its own process group for clean cleanup
    try:
        process = await asyncio.create_subprocess_exec(
            *shlex.split(command),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=working_dir,
            preexec_fn=os.setsid,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"Command not found: {e}")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to start process: {e}")

    # Try to detect port from stdout first, fall back to guessed port
    collected_output = []
    detected_port = await _detect_port_from_output(process, collected_output, timeout=5.0)
    if detected_port:
        port = detected_port
        logger.info(f"Preview serve: detected port {port} from stdout")

    # Check if process died during startup
    if process.returncode is not None:
        remaining = await process.stdout.read(2000)
        error_text = remaining.decode("utf-8", errors="replace")
        all_output = "".join(collected_output) + error_text
        error_msg = all_output.strip()[-500:]  # Last 500 chars
        raise HTTPException(
            status_code=500,
            detail=f"Backend exited with code {process.returncode}:\n{error_msg}",
        )

    # Wait for port to become reachable
    url = f"http://localhost:{port}"
    if not await _wait_for_port(port, timeout=10.0):
        # Check if process is still alive
        if process.returncode is not None:
            remaining = await process.stdout.read(2000)
            error_text = remaining.decode("utf-8", errors="replace")
            all_output = "".join(collected_output) + error_text
            error_msg = all_output.strip()[-500:]
            raise HTTPException(
                status_code=500,
                detail=f"Backend died during startup (exit {process.returncode}):\n{error_msg}",
            )
        # Process alive but port not reachable — it might use a different port
        raise HTTPException(
            status_code=408,
            detail=(
                f"Backend started (pid {process.pid}) but port {port} not reachable after 10s. "
                f"Try specifying the correct port: /preview index.html --serve \"{command}\" --port NNNN"
            ),
        )

    # Store the backend
    backend = PreviewBackend(
        process=process,
        port=port,
        command=command,
        url=url,
        working_dir=working_dir,
    )
    set_preview_backend(s.id, backend)

    logger.info(f"Preview serve: backend running at {url} (pid {process.pid})")

    return {
        "url": url,
        "port": port,
        "command": command,
        "pid": process.pid,
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

    # Check if port is reachable
    if not await _wait_for_port(port, timeout=3.0):
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

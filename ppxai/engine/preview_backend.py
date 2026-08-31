"""Transport-agnostic preview backend manager (v1.18.5).

Extracted from `ppxai/server/routes/preview.py` so TUI clients
(Rich `ppxai`, Textual `ppxaide`) can spawn `/preview --serve`
backends through the same code path the Web/VSCode flow uses. Pre-
v1.18.5 (later same day): the `--serve` flag was parsed by
`commands/display.py::handle_preview` and packaged into the
`PreviewResult` metadata, then silently dropped by the Rich and
Textual renderers — both unconditionally ran static-only
`preview_server.py::PreviewServer` regardless of mode. Slash help
text advertised "autostart backend" but TUI sessions did nothing of
the sort.

This module provides stateless async helpers + a `PreviewBackend`
dataclass that the HTTP route AND TUI renderers both call into. The
single source of truth is the spawn/drain logic here; the caller is
responsible for tracking the resulting backend (HTTP route uses
`server/state.py`'s session-keyed dict; TUI renderers use a
module-level singleton).

Public API:
- `PreviewBackend` — dataclass holding the spawned process + drain task
- `PreviewBackendError` — raised on spawn / port-detection / proxy-validation failures
- `start_served_backend(...)` — spawn user backend, drain stdout to JSONL, wait for port
- `start_proxied_backend(...)` — verify a port reachable, return a synthetic backend for tracking
- `stop_backend(backend)` — cancel drain, kill process group, wait + SIGKILL fallback
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import shlex
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class PreviewBackendError(Exception):
    """Raised when starting or stopping a preview backend fails.

    `status_code` mirrors the HTTP semantic the caller might want to
    surface (400 for bad input, 500 for spawn / process-died errors,
    408 for port-unreachable timeout). TUI callers can ignore the field
    and just use `str(exc)`.
    """

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class PreviewBackend:
    """A running preview backend (subprocess for `served`, virtual for `proxied`).

    `drain_task` (v1.18.5) is the asyncio Task that continuously reads
    the backend's stdout/stderr after port detection completes. Without
    it, the OS PIPE buffer (~64 KB) fills and the backend blocks. For
    `proxied` mode there's no subprocess — `drain_task` and `process`
    are None and the dataclass exists solely to track the proxied port
    in the caller's session map.
    """

    process: asyncio.subprocess.Process | None
    port: int
    command: str
    url: str
    working_dir: str
    log_path: Path | None = None
    last_seen: float = field(default_factory=time.time)
    drain_task: asyncio.Task | None = None
    mode: str = "served"  # "served" | "proxied"


# ---------------------------------------------------------------------------
# Auto-detect: command + port
# ---------------------------------------------------------------------------


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


def detect_command(working_dir: str) -> str | None:
    """Auto-detect the backend start command from project files.

    Tries (in order): npm start (if package.json declares it), then
    main.py / app.py / server.py (preferring `<wd>/venv/bin/python`
    if present, falling back to `python3`/`python`), then
    `make run` (if Makefile has a `run` target).

    Returns:
        A shell-quoted command string, or None if nothing detected.
    """
    wd = Path(working_dir)

    pkg = wd / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            if data.get("scripts", {}).get("start"):
                return "npm start"
        except (json.JSONDecodeError, OSError):
            pass

    if os.name == "nt":
        venv_python = wd / "venv" / "Scripts" / "python.exe"
        fallback_python = "python"
    else:
        venv_python = wd / "venv" / "bin" / "python"
        fallback_python = "python3"
    if not venv_python.exists():
        venv_python = wd / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python = str(venv_python) if venv_python.exists() else fallback_python
    for name in ("main.py", "app.py", "server.py"):
        if (wd / name).exists():
            return f"{python} {name}"

    makefile = wd / "Makefile"
    if makefile.exists():
        try:
            content = makefile.read_text(encoding="utf-8")
            if re.search(r'^run\s*:', content, re.MULTILINE):
                return "make run"
        except OSError:
            pass

    return None


def guess_port_from_command(command: str) -> int:
    """Guess default port from the command string.

    Looks at known framework names, then `--port` / `-p` flags. Falls
    back to 8000.
    """
    cmd_lower = command.lower()
    for framework, port in _FRAMEWORK_DEFAULTS.items():
        if framework in cmd_lower:
            return port
    port_match = re.search(r'(?:--port|-p)\s+(\d+)', command)
    if port_match:
        return int(port_match.group(1))
    return 8000


async def detect_port_from_output(
    process: asyncio.subprocess.Process,
    collected_output: list,
    timeout: float = 5.0,
) -> int | None:
    """Read the process's stdout for port announcements over a deadline.

    Frameworks like uvicorn / flask print `Running on http://localhost:8000`
    on startup. Read up to `timeout` seconds; whatever lines we collect
    are appended to `collected_output` so the caller can use them in
    error messages if the process dies.
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


async def wait_for_port(port: int, timeout: float = 10.0) -> bool:
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


# ---------------------------------------------------------------------------
# Drain task — JSONL events.jsonl per Inspection Triplet (ADR 0005)
# ---------------------------------------------------------------------------


async def drain_backend_output(
    process: asyncio.subprocess.Process,
    log_path: Path | None = None,
) -> None:
    """Continuously read the backend's stdout/stderr until it exits.

    Without this active reader, the OS PIPE buffer (~64 KB) fills and
    the backend blocks on its next write — preview hangs. Same bug
    class as v1.18.3 commit a746a7c6 fixed for the shell tool.

    Output is written as JSONL (one JSON object per line) so the
    `read_preview_log` tool and other Inspection-Triplet-aware
    consumers can parse it programmatically:

        {"ts": "...", "type": "drain_start", "pid": 12345}
        {"ts": "...", "type": "stdout", "pid": 12345, "line": "..."}
        {"ts": "...", "type": "drain_end", "pid": 12345}

    Plain `tail -f` still works (each line is self-contained JSON);
    jq users get nicer output via `jq -r '.line // .type'`.

    Cancellation: caller cancels this task before terminating the
    process. We swallow CancelledError so the caller can `await` the
    task cleanly without try/except wrapping.
    """
    log_handle = None

    def _emit(record: dict) -> None:
        nonlocal log_handle
        if log_handle is None:
            return
        try:
            log_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            log_handle.flush()
        except OSError:
            log_handle = None

    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("a", encoding="utf-8")
        except OSError as e:
            logger.warning(f"Preview drain: could not open log {log_path}: {e}")
            log_handle = None

    _emit({
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "type": "drain_start",
        "pid": process.pid,
    })

    try:
        while True:
            try:
                line = await process.stdout.readline()
            except (asyncio.CancelledError, ConnectionResetError):
                raise
            if not line:
                break
            _emit({
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "type": "stdout",
                "pid": process.pid,
                "line": line.decode("utf-8", errors="replace").rstrip("\n"),
            })
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning(f"Preview drain: unexpected error pid {process.pid}: {e}")
    finally:
        _emit({
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "type": "drain_end",
            "pid": process.pid,
        })
        if log_handle is not None:
            try:
                log_handle.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Public start/stop helpers
# ---------------------------------------------------------------------------


async def start_served_backend(
    command: str | None,
    port: int | None,
    working_dir: str,
) -> PreviewBackend:
    """Spawn the user's backend subprocess, drain its stdout to JSONL,
    wait for the port to become reachable, and return a tracked
    `PreviewBackend`.

    Args:
        command: Explicit command, or None to auto-detect via
                 `detect_command(working_dir)`.
        port: Explicit port, or None to detect from the process's stdout
              announcements / framework defaults.
        working_dir: Where to spawn the command.

    Raises:
        PreviewBackendError: on auto-detect failure (400), spawn failure
            (500), process-died (500), or port-not-reachable timeout (408).
    """
    resolved_command = command or detect_command(working_dir)
    if resolved_command and os.name != "nt":
        # Normalize python → python3 on macOS/Linux for systems where
        # /usr/bin/python doesn't exist.
        resolved_command = re.sub(r'^python(\s)', r'python3\1', resolved_command)
    if not resolved_command:
        raise PreviewBackendError(
            "Could not auto-detect backend command. "
            "No main.py, app.py, server.py, or package.json with start "
            'script found. Specify the command explicitly: '
            '/preview index.html --serve "python main.py"',
            status_code=400,
        )

    resolved_port = port or guess_port_from_command(resolved_command)

    logger.info(
        f"Preview serve: starting {resolved_command!r} in {working_dir} "
        f"(expected port {resolved_port})"
    )

    spawn_kwargs: dict = dict(
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=working_dir,
    )
    # Process group on POSIX so we can SIGTERM the whole tree on stop.
    # Windows: process.terminate() handles the leader; child cleanup is
    # the user's responsibility (npm spawns child PowerShell etc.).
    if platform.system() != "Windows":
        spawn_kwargs["preexec_fn"] = os.setsid

    try:
        process = await asyncio.create_subprocess_exec(
            *shlex.split(resolved_command), **spawn_kwargs
        )
    except FileNotFoundError as e:
        raise PreviewBackendError(f"Command not found: {e}", status_code=400)
    except OSError as e:
        raise PreviewBackendError(f"Failed to start process: {e}", status_code=500)

    collected_output: list[str] = []
    detected_port = await detect_port_from_output(process, collected_output, timeout=5.0)
    if detected_port:
        resolved_port = detected_port
        logger.info(f"Preview serve: detected port {resolved_port} from stdout")

    if process.returncode is not None:
        remaining = await process.stdout.read(2000) if process.stdout else b""
        error_text = remaining.decode("utf-8", errors="replace")
        all_output = "".join(collected_output) + error_text
        error_msg = all_output.strip()[-500:]
        raise PreviewBackendError(
            f"Backend exited with code {process.returncode}:\n{error_msg}",
            status_code=500,
        )

    url = f"http://localhost:{resolved_port}"
    if not await wait_for_port(resolved_port, timeout=10.0):
        if process.returncode is not None:
            remaining = await process.stdout.read(2000) if process.stdout else b""
            error_text = remaining.decode("utf-8", errors="replace")
            all_output = "".join(collected_output) + error_text
            error_msg = all_output.strip()[-500:]
            raise PreviewBackendError(
                f"Backend died during startup (exit {process.returncode}):\n{error_msg}",
                status_code=500,
            )
        raise PreviewBackendError(
            f"Backend started (pid {process.pid}) but port {resolved_port} not "
            f"reachable after 10s. Try specifying the correct port: "
            f'/preview index.html --serve "{resolved_command}" --port NNNN',
            status_code=408,
        )

    log_path = Path.home() / ".ppxai" / "logs" / f"preview-backend-{process.pid}.log"
    drain_task = asyncio.create_task(
        drain_backend_output(process, log_path),
        name=f"preview-drain-{process.pid}",
    )

    backend = PreviewBackend(
        process=process,
        port=resolved_port,
        command=resolved_command,
        url=url,
        working_dir=working_dir,
        log_path=log_path,
        drain_task=drain_task,
        mode="served",
    )
    logger.info(
        f"Preview serve: backend running at {url} "
        f"(pid {process.pid}, log {log_path})"
    )
    return backend


async def start_proxied_backend(
    port: int,
    working_dir: str,
) -> PreviewBackend:
    """Verify that an existing server is reachable at `port` and
    return a synthetic `PreviewBackend` representing the proxy
    arrangement. No subprocess spawned — the user is responsible for
    starting and stopping their backend separately (e.g. from
    `/terminal` in k8s, or from a separate shell).

    Raises:
        PreviewBackendError: status_code=400 if the port isn't reachable.
    """
    if not await wait_for_port(port, timeout=3.0):
        raise PreviewBackendError(
            f"Port {port} is not reachable. Start your backend first "
            f"(e.g., from /terminal).",
            status_code=400,
        )
    url = f"http://localhost:{port}"
    logger.info(f"Preview proxy: proxying to {url}")
    return PreviewBackend(
        process=None,
        port=port,
        command="(external — proxied)",
        url=url,
        working_dir=working_dir,
        log_path=None,
        drain_task=None,
        mode="proxied",
    )


async def stop_backend(backend: PreviewBackend) -> None:
    """Cancel the drain task, SIGTERM the process group (POSIX) or
    terminate the leader (Windows), wait briefly, then SIGKILL on
    timeout. No-op for `proxied` mode (no subprocess to stop).
    """
    if backend.mode == "proxied":
        return

    if backend.drain_task is not None and not backend.drain_task.done():
        backend.drain_task.cancel()
        try:
            await backend.drain_task
        except (asyncio.CancelledError, Exception):
            pass

    process = backend.process
    if process is None:
        return

    try:
        if platform.system() != "Windows":
            pgid = os.getpgid(process.pid)
            os.killpg(pgid, signal.SIGTERM)
        else:
            process.terminate()
    except (ProcessLookupError, OSError, AttributeError):
        pass

    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except (asyncio.TimeoutError, ProcessLookupError):
        try:
            process.kill()
        except ProcessLookupError:
            pass

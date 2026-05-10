"""Read recent stdout/stderr from /preview --serve backends (v1.18.5).

ppxai-server's `routes/preview.py::start_preview_serve` spawns the
user's web-app backend and streams its stdout/stderr to a per-pid
JSONL log under `~/.ppxai/logs/preview-backend-<pid>.log` (the v1.18.5
PIPE-drain fix). This tool exposes those logs to the LLM so it can
correlate browser-side errors with server-side events when debugging
a web app.

Asymmetry to note: only the ppxai-server-mediated `--serve` path
generates these logs (Web app, VSCode extension, ppxai-desktop). The
TUI clients (Rich `ppxai`, Textual `ppxaide`) use `preview_server.py`'s
in-thread HTTPServer for static-file preview and don't spawn the
backend themselves — so when invoked from a TUI session with no
ppxai-server running in the background, this tool returns
`backend_alive: False, lines: []`. Unifying the TUI's `--serve` to
also spawn backends is a v1.19+ design pass; until then the tool
ships universally and is informative when data exists.

Per Inspection Triplet pattern (ADR 0005):
- The JSONL log file is the `events.jsonl` layer for a preview backend.
- `read_preview_log` is the AI-callable PULL consumer.
- A future SSE channel (caveat C3) is the PUSH consumer for Web/VSCode.
- Both consumers read the same source file.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...types import ToolManagerProtocol

logger = logging.getLogger(__name__)


PREVIEW_LOGS_DIR = Path.home() / ".ppxai" / "logs"
PREVIEW_LOG_PATTERN = "preview-backend-*.log"


def _find_log_file(pid: Optional[int] = None) -> Optional[Path]:
    """Find the relevant preview-backend log file.

    Args:
        pid: If provided, look for the specific backend's log; else the
             most-recent-mtime log under PREVIEW_LOGS_DIR.

    Returns:
        Path to the log file, or None if no match.
    """
    if not PREVIEW_LOGS_DIR.is_dir():
        return None
    if pid is not None:
        candidate = PREVIEW_LOGS_DIR / f"preview-backend-{pid}.log"
        return candidate if candidate.is_file() else None
    candidates = sorted(
        PREVIEW_LOGS_DIR.glob(PREVIEW_LOG_PATTERN),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _parse_pid_from_log_filename(path: Path) -> Optional[int]:
    """Extract the pid from `preview-backend-<pid>.log`."""
    match = re.match(r"^preview-backend-(\d+)\.log$", path.name)
    return int(match.group(1)) if match else None


def _is_pid_alive(pid: int) -> bool:
    """Best-effort check via `os.kill(pid, 0)`. Cross-platform."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        # PermissionError means the process exists but is owned by another user
        return isinstance(_, type)  # noqa — placeholder, see below
    except OSError:
        return False


# `os.kill(pid, 0)` raises OSError on Windows for not-found, ProcessLookupError
# elsewhere. Normalize via a wrapper rather than the placeholder above.
def _is_pid_alive(pid: int) -> bool:  # noqa: F811 (intentional override)
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by another user — treat as alive.
        return True
    except OSError:
        return False


def read_preview_log(
    lines: int = 100,
    since: Optional[str] = None,
    filter: Optional[str] = None,
    pid: Optional[int] = None,
) -> str:
    """Read recent stdout/stderr from the active /preview --serve backend.

    Returns a human-readable summary plus the structured JSON payload
    embedded as a fenced block — gives the model both a quick scan and
    machine-readable cursor data for incremental tailing across turns.

    Args:
        lines: Maximum number of log lines to return (default 100).
        since: Opaque cursor from a prior call's `next_since` field.
               Returns only lines written since that point.
        filter: Optional substring or regex; only matching lines returned.
        pid: Specific backend's pid to read. None = most recent backend.
    """
    log_path = _find_log_file(pid)
    if log_path is None:
        if pid is not None:
            return (
                f"No preview backend log found for pid {pid}. "
                "Either the backend was never started via /preview --serve, "
                "or the log file was rotated/deleted."
            )
        return (
            "No active preview backend log found. "
            "If you're using a TUI client (ppxai/ppxaide), the in-thread "
            "preview server doesn't generate backend logs — the user "
            "would need to run their backend via `/preview --serve` from "
            "Web/VSCode for this tool to have data. "
            "If you're using Web/VSCode/ppxai-desktop, no preview backend "
            "is currently active."
        )

    backend_pid = _parse_pid_from_log_filename(log_path) or 0
    backend_alive = _is_pid_alive(backend_pid) if backend_pid else False

    # Open and seek
    try:
        size = log_path.stat().st_size
    except OSError as e:
        return f"Error: could not stat preview log {log_path}: {e}"

    start_offset = 0
    if since is not None:
        try:
            start_offset = int(since)
            # If the file shrunk (rotated) the cursor is invalid — start
            # from the beginning.
            if start_offset > size:
                start_offset = 0
        except (TypeError, ValueError):
            start_offset = 0

    # Compile filter pattern (lenient: substring fallback if regex invalid)
    pattern = None
    if filter:
        try:
            pattern = re.compile(filter)
        except re.error:
            pattern = None  # use plain substring match below

    parsed_lines: List[Dict[str, Any]] = []
    try:
        # Use readline() in a while loop instead of `for line in f` — Python
        # disables tell() inside the file-iteration protocol because the
        # iterator buffers ahead. We need accurate byte offsets for the
        # `next_since` cursor, so readline() is the right primitive here.
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(start_offset)
            while True:
                raw_line = f.readline()
                if not raw_line:
                    break
                end_offset = f.tell()
                stripped = raw_line.rstrip("\n")
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    record = {"type": "raw", "line": stripped}
                # Apply filter against the raw line content + record values
                searchable = json.dumps(record, ensure_ascii=False)
                if filter:
                    if pattern is not None:
                        if not pattern.search(searchable):
                            continue
                    else:
                        if filter not in searchable:
                            continue
                parsed_lines.append({"_offset": end_offset, **record})
    except OSError as e:
        return f"Error: could not read preview log {log_path}: {e}"

    # Trim to last `lines`
    if len(parsed_lines) > lines:
        parsed_lines = parsed_lines[-lines:]

    next_since = str(parsed_lines[-1]["_offset"]) if parsed_lines else str(size)
    # Strip the internal _offset from the visible payload.
    visible_lines = [{k: v for k, v in r.items() if k != "_offset"} for r in parsed_lines]

    # Human-readable summary
    if not visible_lines:
        body = "(no new lines since cursor)" if since else "(log is empty)"
    else:
        formatted = []
        for r in visible_lines:
            t = r.get("type", "raw")
            ts = r.get("ts", "")
            if t == "stdout":
                formatted.append(f"  {ts}  {r.get('line', '')}")
            elif t in ("drain_start", "drain_end"):
                formatted.append(f"  {ts}  -- {t} pid={r.get('pid')}")
            else:
                formatted.append(f"  {ts}  [{t}] {r.get('line', json.dumps(r))}")
        body = "\n".join(formatted)

    payload = {
        "log_file": str(log_path),
        "backend_pid": backend_pid,
        "backend_alive": backend_alive,
        "lines": visible_lines,
        "next_since": next_since,
        "lines_returned": len(visible_lines),
    }

    header = (
        f"Preview backend log: {log_path.name}  "
        f"(pid={backend_pid}, alive={backend_alive}, "
        f"returned={len(visible_lines)})\n"
        f"{body}\n"
    )
    return (
        header
        + "\n--- structured payload (for tool-call cursor) ---\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def register_tools(manager: ToolManagerProtocol):
    """Register the read_preview_log tool with the manager."""
    manager.register_function(
        name="read_preview_log",
        description=(
            "Read recent stdout/stderr from the most recent /preview --serve "
            "backend. Use this when debugging a web app: correlate browser "
            "console errors (CORS, fetch failures, JS errors) with what the "
            "backend is actually logging. NOTE: only populates for "
            "ppxai-server-mediated --serve flows (Web/VSCode/ppxai-desktop); "
            "TUI sessions running ppxai/ppxaide directly use a different "
            "preview path and don't generate these logs. The tool returns a "
            "human-readable summary plus a structured payload with a "
            "`next_since` cursor for incremental tailing across turns."
        ),
        parameters={
            "type": "object",
            "properties": {
                "lines": {
                    "type": "integer",
                    "description": "Maximum lines to return (default 100).",
                },
                "since": {
                    "type": "string",
                    "description": (
                        "Opaque cursor from a prior call's `next_since` "
                        "field. Returns only lines written since that "
                        "point. Omit on first call."
                    ),
                },
                "filter": {
                    "type": "string",
                    "description": (
                        "Optional substring or regex; only matching lines "
                        "are returned. Use to focus on errors: 'ERROR', "
                        "'500', 'Traceback'."
                    ),
                },
                "pid": {
                    "type": "integer",
                    "description": (
                        "Specific backend pid. Omit to read the most "
                        "recent backend's log."
                    ),
                },
            },
            "required": [],
        },
        handler=read_preview_log,
    )

"""
Shared server state — session manager, shutdown event, and utility functions.

All route modules import from here to access the session manager singleton
and shared utilities. This avoids circular imports since routes depend on
state but the app module depends on routes only at registration time.
"""

import asyncio
import os
import platform
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import Header, HTTPException

from ..engine import EngineClient


@dataclass
class Session:
    """Session context returned by the get_session dependency."""
    id: str
    engine: EngineClient
    lock: asyncio.Lock


from ..engine.preview_backend import PreviewBackend, stop_backend as _stop_backend  # noqa: E402,F401
# `PreviewBackend` is re-exported from this module for backward compatibility
# with existing tests (`from ppxai.server.state import PreviewBackend`).
# Authoritative definition lives in `engine/preview_backend.py` (v1.18.5)
# so TUI renderers can construct/consume the dataclass without importing
# from server-only code.


# Preview backend processes, keyed by session ID (one per session)
_preview_backends: dict[str, PreviewBackend] = {}

# Orphan watchdog TTL (seconds) — kill backends with no health check
PREVIEW_BACKEND_TTL = 300  # 5 minutes


def get_preview_backend(session_id: str) -> Optional[PreviewBackend]:
    """Get the preview backend for a session."""
    return _preview_backends.get(session_id)


def set_preview_backend(session_id: str, backend: PreviewBackend) -> None:
    """Store a preview backend for a session."""
    _preview_backends[session_id] = backend


def remove_preview_backend(session_id: str) -> Optional[PreviewBackend]:
    """Remove and return the preview backend for a session."""
    return _preview_backends.pop(session_id, None)


def all_preview_backends() -> dict[str, PreviewBackend]:
    """Get all active preview backends."""
    return _preview_backends


async def kill_preview_backend(backend: PreviewBackend) -> None:
    """Terminate a preview backend process.

    Backward-compat wrapper: the v1.18.5 implementation lives in
    `engine.preview_backend.stop_backend` and is shared with TUI
    renderers. Existing callers (HTTP routes, tests) keep using
    `kill_preview_backend(backend)`.
    """
    await _stop_backend(backend)


async def get_session(x_session_id: Optional[str] = Header(None)) -> Session:
    """FastAPI dependency — resolves session from X-Session-Id header.

    Usage in routes:
        @router.get("/providers")
        async def get_providers(s: Session = Depends(get_session)):
            providers = s.engine.list_providers()
    """
    sid, engine, lock = await get_or_create_session(x_session_id)
    return Session(id=sid, engine=engine, lock=lock)


async def get_session_or_query(
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id"),
    session: Optional[str] = None,
) -> Session:
    """FastAPI dependency — resolves session from X-Session-Id header
    OR a `?session=<id>` query string. Header takes precedence.

    Use this on any route reachable via a plain HTML attribute
    (`<img src>`, `<iframe src>`, `<a href>`) where the browser
    fetches without sending custom headers. Without query-string
    support, those routes fall back to the default session — wrong
    cwd, wrong file_store, 404s when the user's session pointed
    elsewhere (surfaced by markdown image rendering, where docs/foo.png
    couldn't be found because the default session was at $HOME instead
    of the user's project root).

    Usage in routes:
        @router.get("/files/image/{filepath:path}")
        async def serve_image(filepath: str, s: Session = Depends(get_session_or_query)):
            ...
    """
    sid_arg = x_session_id or session
    sid, engine, lock = await get_or_create_session(sid_arg)
    return Session(id=sid, engine=engine, lock=lock)

# Session manager singleton (v1.13.10)
# Set by http.py lifespan, accessed by route modules
session_manager = None

# Shutdown event for graceful termination (v1.13.10)
_shutdown_event: asyncio.Event = None

# Server start time for uptime tracking (v1.13.10)
_server_start_time: float = 0

# MIME types for binary file serving (images + PDF + office docs).
# Office types added v1.18.7 alongside the path-based preview endpoint
# so the file-tree preview path can resolve Content-Type without
# inspecting the file bytes.
MIME_TYPES = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml',
    '.bmp': 'image/bmp', '.ico': 'image/x-icon', '.pdf': 'application/pdf',
    # Office: spreadsheets (rendered client-side via SheetJS — no LibreOffice needed)
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.xls': 'application/vnd.ms-excel',
    '.csv': 'text/csv',
    # Office: presentations (LibreOffice slide-render server-side, text fallback)
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.ppt': 'application/vnd.ms-powerpoint',
    # Office: word processing (LibreOffice → PDF server-side, text fallback)
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.doc': 'application/msword',
}


def get_session_manager():
    """Get the session manager singleton."""
    return session_manager


def get_shutdown_event():
    """Get the shutdown event."""
    return _shutdown_event


def set_session_manager(manager):
    """Set the session manager singleton (called by lifespan)."""
    global session_manager
    session_manager = manager


def set_shutdown_event(event):
    """Set the shutdown event (called by lifespan)."""
    global _shutdown_event
    _shutdown_event = event


def set_server_start_time(t: float):
    """Set the server start time (called by lifespan)."""
    global _server_start_time
    _server_start_time = t


def get_server_start_time() -> float:
    """Get the server start time."""
    return _server_start_time


# Agent run registry singleton (v1.19.0, ADR 0003 Stage 2 — Inc 1).
# Lazy: built on first access, backed by ~/.ppxai/runs/. Routes reach it
# via get_agent_run_registry() (same accessor pattern as the session
# manager). Mirrors the FilesystemAgentRunStore behind the AgentRunStore
# Protocol so a future Item 35 backend swaps in here, not at call sites.
_agent_run_registry = None


def get_agent_run_registry():
    """Get (lazily construct) the agent run registry singleton."""
    global _agent_run_registry
    if _agent_run_registry is None:
        from ..config.loader import PPXAI_HOME
        from ..engine.agent_runs import AgentRunRegistry, FilesystemAgentRunStore
        store = FilesystemAgentRunStore(PPXAI_HOME / "runs")
        _agent_run_registry = AgentRunRegistry(store)
    return _agent_run_registry


def is_path_allowed(target: Path, base: Path) -> bool:
    """Check if target is within base's tree (parent or child)."""
    try:
        target.relative_to(base)
        return True
    except ValueError:
        pass
    try:
        base.relative_to(target)
        return True
    except ValueError:
        pass
    return False


async def get_or_create_session(session_id: Optional[str]) -> tuple[str, EngineClient, asyncio.Lock]:
    """Get existing session or create new one (v1.13.10, v1.13.10 refactored).

    Automatically reloads config on each call so routes don't need to
    call engine.reload_config() individually (v1.17.1 consolidation).

    Args:
        session_id: Session ID from X-Session-Id header, or None for default

    Returns:
        tuple: (session_id, engine, lock)

    Note: v1.13.10 - Now delegates to SessionManager for thread-safe operation.
    """
    if session_manager is None or not session_manager.is_initialized:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    try:
        sid, engine, lock = await session_manager.get_or_create_session(session_id)
        # Reload config to pick up external changes (new providers, models, etc.)
        engine.reload_config()
        return sid, engine, lock
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


async def cleanup_expired_sessions():
    """Remove sessions that haven't been used recently (v1.13.10).

    Note: v1.13.10 - Now delegates to SessionManager.
    """
    if session_manager:
        await session_manager.cleanup_expired_sessions()


def update_activity():
    """Update last activity timestamp (v1.13.10).

    Note: v1.13.10 - Now delegates to SessionManager.
    """
    if session_manager:
        session_manager.update_activity()


# ---------------------------------------------------------------------------
# REST response piggyback (v1.18.1 — state-sync determinism Phase B)
# ---------------------------------------------------------------------------

def with_drained_events(payload: dict, engine: EngineClient) -> dict:
    """Attach the engine's drained side-channel events to a REST response.

    State-mutating REST endpoints (POST /context/working_dir, POST /providers,
    POST /tools, etc.) ALWAYS produce `state_sync` and command-specific
    events into `engine._event_queue`. Without this helper, those events
    sit in the queue until the next /chat opens an SSE generator to drain
    them — which means non-chat REST mutations are invisible to clients
    until a chat happens.

    Wrapping the response with `events: [...]` lets the client feed the
    events through the same dispatcher that handles live SSE. Same
    semantics as if the mutation had happened during a chat stream.

    Wire shape:
        {
            ...original_payload,
            "events": [
                {"type": "state_sync", "data": {"working_dir": "/x"}},
                {"type": "working_dir_changed", "data": {"path": "/x"}},
                ...
            ]
        }

    Empty list when nothing was queued (cheaper than skipping the field —
    keeps the wire shape stable for consumers).

    Args:
        payload: The route's existing response dict. Mutated in place
            (also returned for fluent style).
        engine: The session's EngineClient — supplies drain_events().

    Returns:
        The same payload dict with `events` populated.
    """
    payload["events"] = [
        {
            "type": ev.type.value,
            "data": ev.data,
            **({"metadata": ev.metadata} if ev.metadata else {}),
        }
        for ev in engine.drain_events()
    ]
    return payload

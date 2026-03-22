"""
Shared server state — session manager, shutdown event, and utility functions.

All route modules import from here to access the session manager singleton
and shared utilities. This avoids circular imports since routes depend on
state but the app module depends on routes only at registration time.
"""

import asyncio
from dataclasses import dataclass
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


async def get_session(x_session_id: Optional[str] = Header(None)) -> Session:
    """FastAPI dependency — resolves session from X-Session-Id header.

    Usage in routes:
        @router.get("/providers")
        async def get_providers(s: Session = Depends(get_session)):
            providers = s.engine.list_providers()
    """
    sid, engine, lock = await get_or_create_session(x_session_id)
    return Session(id=sid, engine=engine, lock=lock)

# Session manager singleton (v1.13.10)
# Set by http.py lifespan, accessed by route modules
session_manager = None

# Shutdown event for graceful termination (v1.13.10)
_shutdown_event: asyncio.Event = None

# Server start time for uptime tracking (v1.13.10)
_server_start_time: float = 0

# MIME types for binary file serving (images + PDF)
MIME_TYPES = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml',
    '.bmp': 'image/bmp', '.ico': 'image/x-icon', '.pdf': 'application/pdf',
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

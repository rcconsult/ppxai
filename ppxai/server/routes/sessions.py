"""
Session management endpoints (save, load, clear, restore).
"""

from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from typing import Optional

from ...engine.session import SessionManager as EngineSessionManager
from ..state import get_or_create_session

router = APIRouter()


@router.get("/sessions")
async def get_sessions(x_session_id: Optional[str] = Header(None)):
    """Get list of saved sessions.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    sessions_list = engine.session.list_sessions()
    return {
        "sessions": [
            {
                "name": s.name,
                "created_at": s.created_at,
                "saved_at": s.saved_at,
                "provider": s.provider,
                "model": s.model,
                "message_count": s.message_count,
            }
            for s in sessions_list
        ]
    }


@router.post("/sessions/save")
async def save_session(
    name: Optional[str] = None,
    x_session_id: Optional[str] = Header(None)
):
    """Save current session.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    saved_name = engine.session.save(name)
    return {"name": saved_name}


@router.post("/export")
async def export_answer(
    request: Request,
    x_session_id: Optional[str] = Header(None)
):
    """Export last answer to markdown.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    try:
        body = await request.json()
        filename = body.get("filename")
    except Exception:
        filename = None

    try:
        filepath = engine.export_answer(filename)
        return {"filepath": str(filepath)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/load/{name}")
async def load_session(
    name: str,
    x_session_id: Optional[str] = Header(None)
):
    """Load a saved session.

    v1.13.10: Supports X-Session-Id header for session isolation.
    v1.15.3: Now restores provider and model from session metadata.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    result = engine.restore_session(name)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error", f"Session not found: {name}"))

    return {
        "name": name,
        "loaded": True,
        "provider": result["provider"],
        "model": result["model"],
        "working_dir": result["working_dir"],
        "tools_enabled": result["tools_enabled"],
        "message_count": result["message_count"],
    }


@router.post("/sessions/clear")
async def clear_session(x_session_id: Optional[str] = Header(None)):
    """Clear current session.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    engine.session.clear()
    return {"cleared": True}


@router.get("/sessions/last")
async def get_last_session(x_session_id: Optional[str] = Header(None)):
    """Get last session state from state file.

    v1.13.9: Returns info about the last session for auto-restore prompts.

    Returns:
        JSON with last session info or null if no state file exists
    """
    state = EngineSessionManager.get_last_session_state()
    if not state:
        return {"last_session": None}

    # Verify the session file still exists; clear stale pointer if not.
    session_name = state.get("name")
    if session_name:
        sessions_dir = Path.home() / ".ppxai" / "sessions"
        if not (sessions_dir / f"{session_name}.json").exists():
            EngineSessionManager.clear_state_file()
            return {"last_session": None}

    return {
        "last_session": {
            "name": state.get("name"),
            "dirty": state.get("dirty", False),
            "provider": state.get("provider"),
            "model": state.get("model"),
            "working_dir": state.get("working_dir"),
            "tools_enabled": state.get("tools_enabled", False),
            "message_count": state.get("message_count", 0)
        }
    }


@router.post("/sessions/restore")
async def restore_last_session(x_session_id: Optional[str] = Header(None)):
    """Restore the last session automatically.

    v1.13.9: Auto-restore last session including working_dir and tools state.
    v1.15.3: Now restores provider and model from session metadata.

    Returns:
        JSON with restored session info
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    state = EngineSessionManager.get_last_session_state()
    if not state or not state.get("name"):
        raise HTTPException(status_code=404, detail="No last session found")

    session_name = state["name"]

    result = engine.restore_session(session_name)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error", f"Session not found: {session_name}"))

    return {
        "name": session_name,
        "restored": True,
        "provider": result["provider"],
        "model": result["model"],
        "working_dir": result["working_dir"],
        "tools_enabled": result["tools_enabled"],
        "message_count": result["message_count"],
    }

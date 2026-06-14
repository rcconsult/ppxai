"""
Session management endpoints (save, load, clear, restore).
"""

from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from typing import Optional

from ...engine.session import SessionManager as EngineSessionManager
from ..state import Session, get_session, with_drained_events

router = APIRouter()


@router.get("/sessions")
async def get_sessions(s: Session = Depends(get_session)):
    """Get list of saved sessions.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    sessions_list = s.engine.session.list_sessions()
    return {
        "sessions": [
            {
                "name": sess.name,
                "created_at": sess.created_at,
                "saved_at": sess.saved_at,
                "provider": sess.provider,
                "model": sess.model,
                "message_count": sess.message_count,
            }
            for sess in sessions_list
        ]
    }


@router.post("/sessions/save")
async def save_session(
    name: Optional[str] = Body(None, embed=True),
    s: Session = Depends(get_session)
):
    """Save current session.

    v1.13.10: Supports X-Session-Id header for session isolation.
    v1.18.8: `name` is read from the JSON body (`{"name": "..."}`) — web and
    VSCode send it there. It was previously a query parameter, so a named save
    from those clients was silently ignored (saved under the auto-name).
    """

    try:
        saved_name = s.engine.session.save(name)
    except ValueError as e:
        # Unsafe session name (path traversal) — reject cleanly (finding #1).
        raise HTTPException(status_code=400, detail=str(e))
    return with_drained_events({"name": saved_name}, s.engine)


@router.post("/export")
async def export_answer(
    request: Request,
    s: Session = Depends(get_session)
):
    """Export last answer to markdown.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    try:
        body = await request.json()
        filename = body.get("filename")
    except Exception:
        filename = None

    try:
        filepath = s.engine.export_answer(filename)
        return {"filepath": str(filepath)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/load/{name}")
async def load_session(
    name: str,
    s: Session = Depends(get_session)
):
    """Load a saved session.

    v1.13.10: Supports X-Session-Id header for session isolation.
    v1.15.3: Now restores provider and model from session metadata.
    """

    result = s.engine.restore_session(name)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error", f"Session not found: {name}"))

    return with_drained_events(
        {
            "name": name,
            "loaded": True,
            "provider": result["provider"],
            "model": result["model"],
            "working_dir": result["working_dir"],
            "tools_enabled": result["tools_enabled"],
            "message_count": result["message_count"],
        },
        s.engine,
    )


@router.post("/sessions/clear")
async def clear_session(s: Session = Depends(get_session)):
    """Clear current session.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    s.engine.session.clear()
    return with_drained_events({"cleared": True}, s.engine)


@router.get("/sessions/last")
async def get_last_session(s: Session = Depends(get_session)):
    """Get last session state from state file.

    v1.13.9: Returns info about the last session for auto-restore prompts.

    Returns:
        JSON with last session info or null if no state file exists
    """
    # Disk-scan fallback: if the state pointer is missing but the
    # sessions directory has content, recover the most recent session
    # so the UI still offers a restore prompt.
    state = EngineSessionManager.get_last_session_state_or_scan()
    if not state:
        return {"last_session": None}

    # Verify the session file still exists; clear stale pointer if not.
    # v1.17.4: Check both flat (.json) and directory (dir/session.json)
    # formats — multimodal sessions save in directory format. Skip this
    # check when the state came from a disk scan — by construction the
    # file must exist, we literally just read it.
    session_name = state.get("name")
    if (session_name and not state.get("recovered_from_disk")
            and not EngineSessionManager.session_file_exists(session_name)):
        # Stale pointer — neither flat nor directory format exists.
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
            "message_count": state.get("message_count", 0),
            # Lets web/VSCode render a "State pointer missing — recover
            # most recent session?" prompt instead of the normal
            # "Restore last session?" text.
            "recovered_from_disk": state.get("recovered_from_disk", False),
        }
    }


@router.post("/sessions/restore")
async def restore_last_session(s: Session = Depends(get_session)):
    """Restore the last session automatically.

    v1.13.9: Auto-restore last session including working_dir and tools state.
    v1.15.3: Now restores provider and model from session metadata.

    Returns:
        JSON with restored session info
    """

    # Same disk-scan fallback as GET /sessions/last — lets a client
    # issue a direct restore even when the state pointer was cleared.
    state = EngineSessionManager.get_last_session_state_or_scan()
    if not state or not state.get("name"):
        raise HTTPException(status_code=404, detail="No last session found")

    session_name = state["name"]

    result = s.engine.restore_session(session_name)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error", f"Session not found: {session_name}"))

    return with_drained_events(
        {
            "name": session_name,
            "restored": True,
            "provider": result["provider"],
            "model": result["model"],
            "working_dir": result["working_dir"],
            "tools_enabled": result["tools_enabled"],
            "message_count": result["message_count"],
        },
        s.engine,
    )

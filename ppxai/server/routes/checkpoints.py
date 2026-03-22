"""
Checkpoint management endpoints (v1.12.0).
"""

import subprocess

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from ...common.logger import get_logger
from ..state import Session, get_session

logger = get_logger("server")

router = APIRouter()


@router.get("/checkpoint/status")
async def get_checkpoint_status(s: Session = Depends(get_session)):
    """Get checkpoint system status (v1.12.0).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    return s.engine.get_checkpoint_status()


@router.post("/checkpoint/undo")
async def undo_last_checkpoint(s: Session = Depends(get_session)):
    """Undo the last checkpoint (revert agent task changes) (v1.12.0).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    # Allow undo regardless of agent mode - checkpoints from previous sessions should be undoable
    # Check if checkpoints are enabled
    status = s.engine.get_checkpoint_status()
    if not status.get("enabled"):
        raise HTTPException(
            status_code=400,
            detail="Checkpoints are not enabled (no git repo or checkpoint backend disabled)"
        )

    # Check if there's a checkpoint to undo
    if not status.get("last_checkpoint"):
        raise HTTPException(
            status_code=400,
            detail="No checkpoint to undo (run an agent task first)"
        )

    # Check if checkpoint is still valid (not stale)
    # CRITICAL: Prevents reverting wrong commit when newer commits exist
    if not status.get("is_valid", True):  # Default to True for backward compat
        validity_reason = status.get("validity_reason", "Checkpoint is stale")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot undo: {validity_reason}. New commits have been made since the agent task. "
                   f"Use 'git revert {status.get('last_checkpoint', '')[:8]}' manually if you still want to revert."
        )

    # Check for uncommitted changes before undo (git revert requires clean working tree)
    if status.get("backend") == "git":
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=s.engine.context_injector.working_dir,
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                raise HTTPException(
                    status_code=400,
                    detail="Cannot undo: uncommitted changes in working directory. Commit or stash changes first."
                )
        except subprocess.CalledProcessError:
            pass  # If git status fails, let the undo attempt proceed

    # Perform undo
    success = s.engine.undo_last_checkpoint()
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to undo checkpoint (git revert may have failed)"
        )

    logger.info(f"Checkpoint undo successful via API for session {s.id}")

    return {
        "success": True,
        "message": f"Checkpoint {status.get('last_checkpoint', '')[:8]} reverted successfully",
        "backend": status.get("backend"),
        "checkpoint_id": status.get("last_checkpoint"),
    }


@router.get("/checkpoint/list")
async def list_checkpoints(
    limit: int = 10,
    s: Session = Depends(get_session)
):
    """List recent checkpoints (v1.12.4).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    checkpoints = s.engine.list_checkpoints(limit=limit)
    return {
        "checkpoints": checkpoints,
        "count": len(checkpoints),
    }


@router.post("/checkpoint/backend")
async def set_checkpoint_backend(
    request: dict,
    s: Session = Depends(get_session)
):
    """Set the checkpoint backend (v1.12.4).

    Body: {"backend": "git" | "file" | "auto" | "none"}

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    backend = request.get("backend")
    if not backend:
        raise HTTPException(status_code=400, detail="Missing 'backend' field")

    valid_backends = ('git', 'file', 'auto', 'none')
    if backend not in valid_backends:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid backend: {backend}. Valid options: {', '.join(valid_backends)}"
        )

    success = s.engine.set_checkpoint_backend(backend)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to set checkpoint backend")

    # Return the new status
    status = s.engine.get_checkpoint_status()
    return {
        "success": True,
        "backend": status.get("backend"),
        "enabled": status.get("enabled"),
    }


@router.post("/checkpoint/clear")
async def clear_file_checkpoints(
    request: dict = None,
    s: Session = Depends(get_session)
):
    """Clear old file-based checkpoint snapshots (v1.12.4).

    Body (optional): {"keep_last": 0}

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    keep_last = 0
    if request:
        keep_last = request.get("keep_last", 0)

    status = s.engine.get_checkpoint_status()
    if status.get("backend") != "file":
        raise HTTPException(
            status_code=400,
            detail=f"Clear only applies to file-based checkpoints. Current backend: {status.get('backend', 'none')}"
        )

    removed = s.engine.clear_file_checkpoints(keep_last=keep_last)
    return {
        "success": True,
        "removed": removed,
        "message": f"Cleared {removed} checkpoint(s)",
    }


@router.get("/checkpoint/info/{checkpoint_id}")
async def get_checkpoint_info(
    checkpoint_id: str,
    s: Session = Depends(get_session)
):
    """Get details about a specific checkpoint.

    Supports prefix matching - e.g., "abc123" matches "abc123def456".

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    checkpoints = s.engine.list_checkpoints(limit=20)

    # Find matching checkpoint (prefix match)
    matching = [cp for cp in checkpoints if cp.get("id", "").startswith(checkpoint_id)]

    if not matching:
        raise HTTPException(
            status_code=404,
            detail=f"Checkpoint not found: {checkpoint_id}"
        )

    cp = matching[0]

    # Check if this is the current checkpoint
    status = s.engine.get_checkpoint_status()
    is_current = status.get("last_checkpoint", "").startswith(checkpoint_id)

    return {
        "id": cp.get("id", ""),
        "description": cp.get("description", ""),
        "timestamp": cp.get("timestamp", ""),
        "is_current": is_current,
        "is_valid": status.get("is_valid") if is_current else False,
        "status": "current" if is_current else "historical",
    }

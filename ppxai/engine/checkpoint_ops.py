"""
Checkpoint operations — create, undo, commit, status, cleanup.

Extracted from engine/client.py (v1.17.1) to reduce EngineClient size.
All functions take an engine reference as first parameter.
"""

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import Event, EventType
from ..checkpoint import FileCheckpointBackend


def create_checkpoint(engine, description: str) -> Optional[str]:
    """Create a checkpoint before agent task execution.

    Args:
        description: Description of the task (for commit message)

    Returns:
        Checkpoint ID if successful, None otherwise
    """
    if not engine._checkpoint_manager or not engine._agent_mode:
        return None

    checkpoint_id = engine._checkpoint_manager.create_checkpoint(description)
    if checkpoint_id:
        engine._last_checkpoint_id = checkpoint_id

        backend = engine._checkpoint_manager.get_backend_name()
        if backend == "git":
            msg = f"✓ Checkpoint created: {checkpoint_id[:8]} ({description})"
        else:
            msg = f"✓ Snapshot saved: {checkpoint_id} ({description})"

        engine._consent_event_queue.append(Event(
            type=EventType.STATUS,
            data=msg
        ))

    return checkpoint_id


def undo_last_checkpoint(engine) -> bool:
    """Undo the last checkpoint (revert changes).

    Returns:
        True if undo was successful, False otherwise
    """
    if not engine._checkpoint_manager or not engine._last_checkpoint_id:
        return False

    success = engine._checkpoint_manager.restore_checkpoint(engine._last_checkpoint_id)
    if success:
        backend = engine._checkpoint_manager.get_backend_name()
        checkpoint_id = engine._last_checkpoint_id

        if backend == "git":
            msg = f"✓ Changes reverted using git revert (checkpoint: {checkpoint_id[:8]})"
        else:
            msg = f"✓ Files restored from snapshot: {checkpoint_id}"

        engine._consent_event_queue.append(Event(
            type=EventType.STATUS,
            data=msg
        ))

        engine._last_checkpoint_id = None
        return True

    return False


def commit_agent_changes(engine, description: str) -> Optional[str]:
    """Commit changes made during agent task.

    Only git backend supports this. Stages all changes and commits.

    Args:
        description: Description of the changes (for commit message)

    Returns:
        Commit hash if successful, None otherwise
    """
    if not engine._checkpoint_manager or not engine._agent_mode:
        return None

    if engine._checkpoint_manager.get_backend_name() != "git":
        return None

    try:
        working_dir = engine.context_injector.working_dir

        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=working_dir,
            capture_output=True,
            text=True
        )
        if not result.stdout.strip():
            return None

        subprocess.run(
            ["git", "add", "-A"],
            cwd=working_dir,
            check=True
        )

        commit_msg = f"ppxai agent: {description}"
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=working_dir,
            check=True
        )

        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            check=True
        )
        commit_hash = result.stdout.strip()
        engine._last_checkpoint_id = commit_hash
        return commit_hash

    except subprocess.CalledProcessError:
        return None


def get_checkpoint_status(engine) -> Dict[str, Any]:
    """Get checkpoint system status.

    Returns:
        Dictionary with checkpoint status including validity.
    """
    if not engine._checkpoint_manager:
        return {
            "enabled": False,
            "backend": "none",
            "last_checkpoint": None,
            "is_valid": False,
            "validity_reason": "Checkpointing is disabled",
        }

    is_valid = False
    validity_reason = "No checkpoint available"
    checkpoint_id = engine._last_checkpoint_id

    if checkpoint_id:
        is_valid, validity_reason = engine._checkpoint_manager.is_checkpoint_valid(
            checkpoint_id
        )
        if not is_valid:
            engine._last_checkpoint_id = None

    return {
        "enabled": engine._checkpoint_manager.is_enabled(),
        "backend": engine._checkpoint_manager.get_backend_name(),
        "last_checkpoint": checkpoint_id,
        "is_valid": is_valid,
        "validity_reason": validity_reason,
        "status_description": engine._checkpoint_manager.get_status_description(),
    }


def list_checkpoints(engine, limit: int = 10) -> List[Dict[str, str]]:
    """List recent checkpoints.

    Returns:
        List of checkpoint info dicts with keys: id, description, timestamp
    """
    if not engine._checkpoint_manager:
        return []

    checkpoints = engine._checkpoint_manager.list_checkpoints()
    return [
        {"id": cp[0], "description": cp[1], "timestamp": cp[2]}
        for cp in checkpoints[:limit]
    ]


def set_checkpoint_backend(engine, backend: str) -> bool:
    """Set the checkpoint backend mode.

    Args:
        backend: One of 'git', 'file', 'auto', 'none'

    Returns:
        True if backend was set successfully
    """
    from ..checkpoint import CheckpointManager

    valid_backends = ('git', 'file', 'auto', 'none')
    if backend not in valid_backends:
        return False

    working_dir = str(Path.cwd())
    session_id = engine.session.session_name if engine.session else "default"

    engine._checkpoint_manager = CheckpointManager(
        working_dir=working_dir,
        session_id=session_id,
        backend=backend
    )
    return True


def clear_file_checkpoints(engine, keep_last: int = 0) -> int:
    """Clear old file-based checkpoint snapshots.

    Args:
        keep_last: Number of recent checkpoints to keep (0 = clear all)

    Returns:
        Number of checkpoints removed
    """
    if not engine._checkpoint_manager:
        return 0

    if isinstance(engine._checkpoint_manager.backend, FileCheckpointBackend):
        before_count = len(engine._checkpoint_manager.list_checkpoints())
        engine._checkpoint_manager.backend.cleanup_old_checkpoints(keep_last=keep_last)
        after_count = len(engine._checkpoint_manager.list_checkpoints())
        return before_count - after_count

    return 0

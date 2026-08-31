"""
Context, working directory, and bootstrap context endpoints.
"""

import os

from fastapi import APIRouter, Depends, HTTPException

from ...common.logger import get_logger
from ..models import AutoInjectRequest, WorkingDirRequest
from ..state import Session, get_session, with_drained_events

logger = get_logger("server")

router = APIRouter()


@router.get("/context/working_dir")
async def get_working_dir(s: Session = Depends(get_session)):
    """Get the current working directory.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    path = s.engine.get_working_dir() or os.getcwd()
    return {"path": path, "session_id": s.id}


@router.post("/context/working_dir")
async def set_working_dir(
    request: WorkingDirRequest,
    s: Session = Depends(get_session)
):
    """Set the working directory for file path resolution.

    v1.13.10: Supports X-Session-Id header for session isolation.
    Each session maintains its own working directory.
    """

    # Expand tilde and resolve to absolute path
    path = os.path.expanduser(request.path)

    # If relative path, resolve relative to session's current working dir (not server cwd)
    if not os.path.isabs(path):
        current_wd = s.engine.get_working_dir() or os.getcwd()
        path = os.path.normpath(os.path.join(current_wd, path))

    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=f"Not a valid directory: {path}")

    s.engine.set_working_dir(path)
    logger.info(f"Session {s.id} working directory set to: {path}")
    return with_drained_events(
        {"path": path, "success": True, "session_id": s.id},
        s.engine,
    )


@router.post("/context/auto_inject")
async def set_auto_inject(
    request: AutoInjectRequest,
    s: Session = Depends(get_session)
):
    """Enable or disable automatic context injection.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    s.engine.set_auto_inject(request.enabled)
    return with_drained_events(
        {"enabled": request.enabled, "success": True},
        s.engine,
    )


@router.get("/context/auto_inject")
async def get_auto_inject(s: Session = Depends(get_session)):
    """Get auto-inject context status.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    return {"enabled": s.engine.get_auto_inject()}


@router.get("/context/info")
async def get_context_info(s: Session = Depends(get_session)):
    """Get context usage information.

    v1.13.9: Returns token usage, context limit, and injected files.

    Returns:
        - estimated_tokens: Estimated total tokens in conversation
        - context_limit: Model's context window limit
        - usage_percent: Percentage of context used
        - injected_contexts: List of injected @file/@git/@tree references
        - injected_tokens: Tokens used by injections
        - message_count: Number of messages in history
    """

    info = s.engine.get_context_info()
    return {**info, "session_id": s.id}


@router.post("/context/clear")
async def clear_context_injections(s: Session = Depends(get_session)):
    """Clear injected @file/@git/@tree content from conversation history.

    v1.13.9: Removes injection blocks from messages to free context space.
    The conversation flow is preserved, only the injected content is removed.

    Returns:
        - removed_count: Number of injections removed
        - success: True if operation completed
    """

    removed_count = s.engine.clear_injected_contexts()
    return with_drained_events(
        {
            "removed_count": removed_count,
            "success": True,
            "session_id": s.id
        },
        s.engine,
    )


@router.get("/context/hints")
async def get_active_hints(s: Session = Depends(get_session)):
    """Get active bootstrap hints for current provider/model.

    v1.14.0: Returns detailed breakdown of which hints from AGENTS.md/CLAUDE.md
    are currently active based on the provider and model.

    Returns:
        - loaded: bool - whether bootstrap context is loaded
        - source: str - path to bootstrap file
        - provider: str - current provider
        - model: str - current model
        - provider_hints: List of [source, hint] tuples
        - model_hints: List of [pattern, hint] tuples
        - inherited_local: bool - whether 'local' hints were inherited
        - matched_patterns: List of matched model patterns
        - all_provider_keys: List of all provider hint keys in file
        - all_model_patterns: List of all model patterns in file
    """

    hints_info = s.engine.get_active_hints()
    return {
        **hints_info,
        "session_id": s.id
    }


@router.get("/context/bootstrap")
async def get_bootstrap_status(s: Session = Depends(get_session)):
    """Get bootstrap context hierarchy with scope information (v1.14.2).

    Returns detailed information about loaded bootstrap files including
    their scopes (global, project, subdir).

    Returns:
        - loaded: bool - whether bootstrap context is loaded
        - sources: List[Dict] - scoped sources with path, scope, size
        - source_paths: List[str] - simple list of paths (backwards compat)
        - char_count: int - total characters
        - has_hints: bool - whether hints are defined
        - provider_hints: List[str] - providers with hints
        - model_hints: List[str] - model patterns with hints
        - total_size: int - total size in bytes
    """

    status = s.engine.get_bootstrap_status()
    return {
        **status,
        "session_id": s.id
    }


@router.post("/context/reload")
async def reload_bootstrap_context(s: Session = Depends(get_session)):
    """Reload bootstrap context from disk (v1.14.1, v1.14.2 scopes).

    Reloads bootstrap context files from all scopes (global, project, subdir).
    Useful after editing bootstrap files to pick up changes without restarting.

    Returns:
        JSON: {"success", "loaded", "sources": [...], "char_count", ...}

    v1.14.1: Added for VSCode /context reload command.
    v1.14.2: Returns full scoped source info.
    """

    logger.info(f"HTTP POST /context/reload - session: {s.id}")

    success = s.engine.reload_bootstrap_context()
    status = s.engine.get_bootstrap_status()

    return with_drained_events(
        {
            "success": success,
            **status,
            "session_id": s.id
        },
        s.engine,
    )

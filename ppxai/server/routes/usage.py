"""
Usage statistics endpoints.
"""

from fastapi import APIRouter, Header, HTTPException
from typing import Optional

from ..models import UsageDisplayModeRequest
from ..state import get_or_create_session
from ...usage import get_usage_report as get_report, get_usage_storage

router = APIRouter()


@router.get("/usage")
async def get_usage(x_session_id: Optional[str] = Header(None)):
    """Get token usage statistics for current session.

    Returns full usage including per-model breakdown (v1.12.2).
    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    return engine.get_usage()


@router.post("/usage/display")
async def set_usage_display_mode(
    request: UsageDisplayModeRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Set usage display mode for status line (v1.12.2).

    Args:
        mode: One of "session", "provider", "model", "off"
            - session: Show session totals
            - provider: Show current provider totals
            - model: Show current model totals
            - off: Hide usage from status line

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    valid_modes = {"session", "provider", "model", "off"}
    if request.mode not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {request.mode}. Valid modes: {', '.join(valid_modes)}"
        )

    success = engine.session.set_usage_display_mode(request.mode)
    return {"mode": request.mode, "success": success}


@router.get("/usage/display")
async def get_usage_display_mode(x_session_id: Optional[str] = Header(None)):
    """Get current usage display mode (v1.12.2).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    return {"mode": engine.session.usage_display_mode}


@router.post("/usage/reset")
async def reset_usage(x_session_id: Optional[str] = Header(None)):
    """Reset all usage statistics to zero (v1.12.2).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    engine.session.reset_usage()
    return {"success": True}


@router.get("/usage/report")
async def get_usage_report(period: str = "all"):
    """Get aggregated usage report for a time period (v1.12.3).

    Query params:
        period: One of "24h", "week", "month", "year", "all" (default: "all")

    Returns aggregated usage stats across all sessions:
        - total_tokens: Total tokens used
        - total_cost: Estimated total cost
        - session_count: Number of sessions
        - by_provider: Usage breakdown by provider
        - by_model: Usage breakdown by model
        - sessions: Recent session summaries
    """
    valid_periods = {"24h", "week", "month", "year", "all"}
    if period not in valid_periods:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period: {period}. Valid periods: {', '.join(valid_periods)}"
        )

    return get_report(period)


@router.get("/usage/sessions")
async def get_usage_sessions(limit: int = 20, offset: int = 0):
    """Get list of recorded sessions with usage data (v1.12.3).

    Query params:
        limit: Maximum sessions to return (default: 20, max: 100)
        offset: Number of sessions to skip (default: 0)

    Returns:
        sessions: List of session records (newest first)
        total: Total number of recorded sessions
    """
    # Clamp limit to reasonable range
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    storage = get_usage_storage()
    sessions = storage.get_sessions(limit=limit, offset=offset)
    total = storage.get_session_count()

    return {
        "sessions": sessions,
        "total": total,
        "limit": limit,
        "offset": offset,
    }

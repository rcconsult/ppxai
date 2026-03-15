"""
Agent mode endpoints (v1.11.8).
"""

from fastapi import APIRouter, Header
from typing import Optional

from ...common.logger import get_logger
from ..state import get_or_create_session

logger = get_logger("server")

router = APIRouter()


@router.get("/agent/status")
async def get_agent_status(x_session_id: Optional[str] = Header(None)):
    """Get agent mode status (v1.11.8, v1.12.0).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    # Include checkpoint status in v1.12.0+
    checkpoint_status = engine.get_checkpoint_status()

    return {
        "agent_mode": engine.agent_mode,
        "tools_enabled": engine.tools_enabled,
        "checkpoint": checkpoint_status,
    }


@router.get("/agent/config")
async def get_agent_config(x_session_id: Optional[str] = Header(None)):
    """Get agent configuration (v1.11.9).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    return engine.get_agent_config()


@router.post("/agent/enable")
async def enable_agent_mode(x_session_id: Optional[str] = Header(None)):
    """Enable agent mode for autonomous task execution (v1.11.8).

    Agent mode automatically enables tools if not already enabled.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    engine.enable_agent_mode()
    logger.info(f"Agent mode enabled via API for session {session_id}")

    return {
        "ok": True,
        "agent_mode": True,
        "tools_enabled": engine.tools_enabled,
    }


@router.post("/agent/disable")
async def disable_agent_mode(x_session_id: Optional[str] = Header(None)):
    """Disable agent mode (v1.11.8).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    engine.disable_agent_mode()
    logger.info(f"Agent mode disabled via API for session {session_id}")

    return {
        "ok": True,
        "agent_mode": False,
    }

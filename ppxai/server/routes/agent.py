"""
Agent mode endpoints (v1.11.8).
"""

from fastapi import APIRouter, Depends
from typing import Optional

from ...common.logger import get_logger
from ..state import Session, get_session

logger = get_logger("server")

router = APIRouter()


@router.get("/agent/status")
async def get_agent_status(s: Session = Depends(get_session)):
    """Get agent mode status (v1.11.8, v1.12.0).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    # Include checkpoint status in v1.12.0+
    checkpoint_status = s.engine.get_checkpoint_status()

    return {
        "agent_mode": s.engine.agent_mode,
        "tools_enabled": s.engine.tools_enabled,
        "checkpoint": checkpoint_status,
    }


@router.get("/agent/config")
async def get_agent_config(s: Session = Depends(get_session)):
    """Get agent configuration (v1.11.9).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    return s.engine.get_agent_config()


@router.post("/agent/enable")
async def enable_agent_mode(s: Session = Depends(get_session)):
    """Enable agent mode for autonomous task execution (v1.11.8).

    Agent mode automatically enables tools if not already enabled.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    s.engine.enable_agent_mode()
    logger.info(f"Agent mode enabled via API for session {s.id}")

    return {
        "ok": True,
        "agent_mode": True,
        "tools_enabled": s.engine.tools_enabled,
    }


@router.post("/agent/disable")
async def disable_agent_mode(s: Session = Depends(get_session)):
    """Disable agent mode (v1.11.8).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    s.engine.disable_agent_mode()
    logger.info(f"Agent mode disabled via API for session {s.id}")

    return {
        "ok": True,
        "agent_mode": False,
    }

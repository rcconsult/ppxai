"""
Server health, status, and configuration endpoints.
"""

import asyncio
import os
import signal
import time

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from ...common.logger import get_logger
from ...config import (
    find_config_file,
    get_auto_restore_mode,
    get_available_providers,
    get_idle_timeout,
    get_paths_config as _get_paths_config,
    reload_config,
)
from ...version import __version__
from ..state import Session, get_session, get_session_manager, get_shutdown_event

logger = get_logger("server")

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint for container orchestration.

    Returns basic server status. Use /ready for detailed readiness checks.

    v1.13.10: Updated to use SessionManager and enhanced for Kubernetes.
    """
    session_manager = get_session_manager()
    idle_timeout = get_idle_timeout()

    last_activity = session_manager.last_activity if session_manager else 0

    return {
        "status": "healthy",
        "version": __version__,
        "engine": session_manager.is_initialized if session_manager else False,
        "sessions": session_manager.session_count if session_manager else 0,
        "idle_timeout": idle_timeout,
        "idle_since": int(time.time() - last_activity) if last_activity > 0 else 0,
    }


@router.get("/ready")
async def readiness_check():
    """Readiness check endpoint for container orchestration (v1.13.10).

    Returns detailed readiness status. Use for Kubernetes readiness probes.
    Returns 503 if server is not ready to accept traffic.

    Checks:
    - SessionManager initialized
    - Default engine available
    - Provider configured
    """
    session_manager = get_session_manager()

    # Check if session manager is ready
    if session_manager is None or not session_manager.is_initialized:
        raise HTTPException(
            status_code=503,
            detail="Server not ready: SessionManager not initialized"
        )

    default_engine = session_manager.default_engine
    if default_engine is None:
        raise HTTPException(
            status_code=503,
            detail="Server not ready: Default engine not available"
        )

    # Get available providers
    providers = get_available_providers()

    return {
        "status": "ready",
        "version": __version__,
        "provider": default_engine.provider_name,
        "model": default_engine.model,
        "providers_available": len(providers),
        "sessions_active": session_manager.session_count,
        "shutdown_requested": session_manager.shutdown_requested,
    }


@router.post("/shutdown")
async def shutdown_server():
    """Gracefully shutdown the server (v1.13.6).

    This endpoint allows clients to request server shutdown.
    Useful for web app UI to stop the server via a button.

    Returns:
        JSON: {"shutdown": true, "message": "Server shutting down..."}

    Note: v1.13.10 - Uses graceful shutdown via asyncio event instead of os._exit().
    This allows cleanup handlers (atexit) to run properly.
    """
    session_manager = get_session_manager()
    _shutdown_event = get_shutdown_event()

    logger.info("Shutdown requested via /shutdown endpoint")

    # Mark shutdown as requested via SessionManager
    if session_manager:
        session_manager.request_shutdown("api_request")

    # Schedule graceful shutdown after response is sent (v1.13.10)
    async def delayed_shutdown():
        await asyncio.sleep(0.5)  # Give time for response to be sent
        logger.info("Initiating graceful shutdown")
        if _shutdown_event:
            _shutdown_event.set()
        else:
            # Fallback for edge cases where event wasn't initialized
            os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(delayed_shutdown())

    return {
        "shutdown": True,
        "message": "Server shutting down...",
    }


@router.get("/status")
async def get_status(s: Session = Depends(get_session)):
    """Get current engine status.

    v1.13.10: Supports X-Session-Id header for session isolation.
    v1.14.0: Added bootstrap context status.
    """

    state = s.engine.state.snapshot()
    return {
        **state,
        "session_id": s.id,
        "auto_inject_context": s.engine.auto_inject_context,
        # v1.18.8: expose the session auto-restore mode so clients can honor
        # "always"/"prompt"/"never" instead of always popping a confirm().
        "auto_restore": get_auto_restore_mode(),
        "bootstrap": s.engine.get_bootstrap_status(),  # v1.14.0
    }


@router.get("/sessions/list")
async def list_active_sessions():
    """List all active sessions (v1.13.10).

    Returns information about currently active sessions for debugging/monitoring.

    Note: v1.13.10 - Now uses SessionManager.list_sessions().
    """
    session_manager = get_session_manager()

    # Get sessions via SessionManager (includes cleanup)
    session_list = await session_manager.list_sessions()

    return {
        "sessions": session_list,
        "count": len(session_list),
        "default_engine_active": session_manager.is_initialized,
    }


@router.get("/config/paths")
async def get_paths_config():
    """Get paths configuration for binary and data locations (v1.13.2).

    Returns:
        bin_search_paths: List of directories to search for binaries
        data_dir: Directory for sessions, exports, usage data
    """
    return _get_paths_config()


@router.get("/config/path")
async def get_config_path():
    """Get the current config file path (v1.15.2).

    Returns:
        path: Path to the config file, or null if not found
    """
    config_path = find_config_file()
    return {"path": str(config_path) if config_path else None}


@router.post("/config/reload")
async def reload_config_endpoint():
    """Reload configuration from file without restarting server.

    This allows hot-reloading of provider prompts, settings, and other
    configuration changes from ppxai-config.json.

    Note: This updates PROVIDERS/MODELS module-level dicts in-place (v1.15.3),
    so all engine clients will see fresh provider data immediately via the
    providers_config property. Individual sessions' shell/agent configs remain
    cached until the session explicitly calls engine.reload_config().

    Returns:
        success: Whether reload succeeded
        message: Status message
        config_path: Path to loaded config file
    """
    try:
        reload_config()  # Updates PROVIDERS/MODELS in place via initialize()
        config_path = find_config_file()
        logger.info(f"Configuration reloaded from {config_path}")
        return {
            "success": True,
            "message": "Configuration reloaded successfully",
            "config_path": str(config_path) if config_path else None
        }
    except Exception as e:
        logger.error(f"Failed to reload config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reload config: {e}")


# === Debug Logging (v1.11.2) ===

@router.get("/debug-log")
async def get_debug_log_status():
    """Get server debug logging status."""
    return {
        "enabled": logger.enabled,
        "log_file": str(logger.log_file) if logger.log_file else None,
    }


@router.post("/debug-log")
async def set_debug_log(request: dict):
    """Enable or disable server debug logging.

    Body: {"enabled": true/false}
    """
    enabled = request.get("enabled", False)

    if enabled:
        logger.enable()
        logger.info("Debug logging enabled via API")
    else:
        logger.info("Debug logging disabled via API")
        logger.disable()

    # Persist so next startup restores state before session recovery
    from ...config import set_tui_config
    set_tui_config("debug_log", enabled)

    return {
        "enabled": logger.enabled,
        "log_file": str(logger.log_file) if logger.log_file else None,
    }


@router.post("/client-log")
async def client_log(request: dict):
    """Receive log entries from web/IDE clients.

    Body: {"level": "info|warning|error", "message": "...", "client": "web"}
    """
    level = request.get("level", "info")
    message = request.get("message", "")
    client = request.get("client", "web")
    if message:
        logger.log_client_event(client, level, message)
    return {"ok": True}

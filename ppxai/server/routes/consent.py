"""
File edit and shell command consent endpoints.
"""

from fastapi import APIRouter, Header, HTTPException
from typing import Optional

from ...common.consent import normalize_consent_response
from ...common.logger import get_logger
from ..models import ConsentRequest, ShellConsentRequest
from ..state import get_or_create_session, get_session_manager

logger = get_logger("server")

router = APIRouter()


@router.post("/interrupt")
async def interrupt_stream(x_session_id: Optional[str] = Header(None)):
    """Interrupt the current streaming response.

    This sets a flag that the engine will check during streaming.
    The stream will stop at the next chunk and return partial results.

    Returns:
        JSON: {"interrupted": true}

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    engine.interrupt_stream()
    return {"interrupted": True}


@router.post("/consent")
async def respond_to_consent(
    request: ConsentRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Respond to a file edit consent request (Phase 1C: v1.11.0).

    This endpoint is called by the VSCode extension when the user
    responds to a consent dialog. It resolves the pending Future
    that the consent callback is waiting on.

    Args:
        request: ConsentRequest with file_path and response

    Returns:
        JSON: {"file_path": str, "response": str, "resolved": bool}

    v1.13.10: Supports X-Session-Id header for session isolation.
    v1.13.10: Now uses SessionManager.resolve_consent().
    """
    session_manager = get_session_manager()

    # Determine session ID (use default if not provided)
    session_id = x_session_id or "default"

    file_path = request.file_path

    # Normalize response to standard enum value (handles yes/Yes/YES/y/etc.)
    response = normalize_consent_response(request.response)
    logger.debug(f"Consent: POST /consent session={session_id} file={file_path} response={request.response} -> {response}")

    # Resolve via SessionManager (v1.13.10)
    resolved = await session_manager.resolve_consent(session_id, file_path, response)
    if resolved:
        logger.debug(f"Consent: resolved OK for {file_path}")
        return {
            "file_path": file_path,
            "response": response,
            "resolved": True
        }

    # No pending request found
    logger.debug(f"Consent: NO PENDING REQUEST for session={session_id} file={file_path}")
    raise HTTPException(status_code=404, detail=f"No pending consent request for: {file_path}")


@router.post("/shell-consent")
async def respond_to_shell_consent(
    request: ShellConsentRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Respond to a shell command consent request (v1.11.2).

    This endpoint is called by the VSCode extension when the user
    responds to a shell consent dialog. It resolves the pending Future
    that the shell consent callback is waiting on.

    Args:
        request: ShellConsentRequest with command, working_dir, and response

    Returns:
        JSON: {"command": str, "response": str, "resolved": bool}

    v1.13.10: Supports X-Session-Id header for session isolation.
    v1.13.10: Now uses SessionManager.resolve_shell_consent().
    """
    session_manager = get_session_manager()

    # Determine session ID (use default if not provided)
    session_id = x_session_id or "default"

    command = request.command

    # Normalize response to standard enum value (handles yes/Yes/YES/y/etc.)
    response = normalize_consent_response(request.response)

    # Resolve via SessionManager (v1.13.10)
    resolved = await session_manager.resolve_shell_consent(session_id, command, response)
    if resolved:
        return {
            "command": command,
            "response": response,
            "resolved": True
        }

    # No pending request found
    raise HTTPException(status_code=404, detail=f"No pending shell consent request for: {command}")

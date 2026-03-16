"""
Command execution endpoint (v1.16.1).

Generic endpoint that dispatches commands through CommandFactory.
All clients (web app, VSCode) call this instead of bespoke endpoints.
"""

from fastapi import APIRouter, Header, HTTPException
from typing import Optional

from ...commands.context import ServerCommandContext
from ...commands.factory import CommandFactory
from ..models import CommandRequest
from ..state import get_or_create_session

router = APIRouter()


@router.post("/command/{name}")
async def execute_command(
    name: str,
    request: CommandRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Execute a slash command server-side via CommandFactory.

    Returns the CommandResult as JSON. No per-command logic here —
    the factory does the lookup, the handler does the work.

    v1.16.1: POC with /usage, generalizable to all commands.
    """
    spec = CommandFactory.get(name)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Unknown command: /{name}")

    session_id, engine, _ = await get_or_create_session(x_session_id)
    context = ServerCommandContext(engine)
    result = spec.handler(context, request.args)
    return result.to_dict()

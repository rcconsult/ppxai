"""
Completion endpoint — autocomplete suggestions for web/VSCode clients.

Exposes the engine's `CompletionProvider` over HTTP so browser-based
clients can offer slash-command, path-argument, and @file-reference
completion without reimplementing the logic in JavaScript/TypeScript.

    POST /complete
    Body: {"buffer": "/att", "cursor": 4}
    Response: {"items": [{"text": "/attach", "display": "/attach", ...}]}
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from ...engine.completion import complete
from ..state import Session, get_session

router = APIRouter()


class CompleteRequest(BaseModel):
    """Autocomplete request body."""
    buffer: str
    cursor: int = -1  # -1 = end of buffer


class CompleteResponse(BaseModel):
    """Autocomplete response body."""
    items: List[Dict[str, Any]]


@router.post("/complete", response_model=CompleteResponse)
async def complete_endpoint(
    request: CompleteRequest,
    s: Session = Depends(get_session),
):
    """Return autocomplete suggestions for the given input buffer.

    Uses the session's engine working directory for path completions,
    so results match what the user would see if they ran the same
    command in their terminal.
    """
    working_dir = None
    if s.engine:
        working_dir = s.engine.get_working_dir()

    items = complete(
        request.buffer,
        request.cursor,
        working_dir=working_dir,
    )

    return CompleteResponse(items=items)

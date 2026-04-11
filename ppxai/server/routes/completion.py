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
from typing import Any, Dict, List, Optional, Tuple

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

    Uses the session's engine working directory, current provider, and
    live tool list so Web/VSCode get the same `/tools help <tab>`,
    `/model <tab>`, and `/provider <tab>` behaviour that Rich/Textual
    already enjoy via in-process calls.
    """
    working_dir: Optional[str] = None
    current_provider: Optional[str] = None
    tool_names: List[Tuple[str, str]] = []

    if s.engine:
        working_dir = s.engine.get_working_dir()
        current_provider = s.engine.provider_name or None
        if s.engine.tool_manager is not None:
            try:
                tool_names = [
                    (t["name"], t.get("description", ""))
                    for t in s.engine.tool_manager.list_tools()
                ]
            except Exception:
                tool_names = []

    items = complete(
        request.buffer,
        request.cursor,
        working_dir=working_dir,
        current_provider=current_provider,
        tool_names=tool_names,
    )

    return CompleteResponse(items=items)

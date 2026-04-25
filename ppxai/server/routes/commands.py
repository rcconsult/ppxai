"""
Command execution endpoint.

Generic endpoint that dispatches commands through CommandFactory.
All clients (web app, VSCode) call this instead of bespoke endpoints.

v1.18.1 — Wire envelope.
The route returns a structured envelope:

    {
      "ok": bool,                  # mirrors result.success
      "result": { ... },           # CommandResult.to_dict()
      "side_effects": [...],       # UI directives orthogonal to payload
      "events": [...],             # drained engine side-channel events
      "version": 1
    }

Side-effects are orthogonal to the rendered payload — clients
pattern-match on `kind` and ignore unknown kinds, so adding a new
kind is non-breaking. In-process TUI callers go through
`CommandFactory.get(name).handler(...)` directly and read
`result.side_effects` from the result; this envelope shape exists
solely for the HTTP wire.

`events` carry any state_sync / working_dir_changed / etc. that
the handler caused via `state.set(...)`. Without piggybacking
them here, the events sit in `engine._event_queue` until the next
/chat opens an SSE generator to drain them — which makes
non-chat command mutations (e.g. POST /command/cd) invisible to
the web/VSCode AppState mirror until a chat happens. State-sync
determinism Phase B (v1.18.1).
"""

from fastapi import APIRouter, Depends, HTTPException

from ...commands.context import ServerCommandContext
from ...commands.factory import CommandFactory
from ..models import CommandRequest
from ..state import Session, get_session, with_drained_events

router = APIRouter()

ENVELOPE_VERSION = 1


@router.post("/command/{name}")
async def execute_command(
    name: str,
    request: CommandRequest,
    s: Session = Depends(get_session)
):
    """Execute a slash command server-side via CommandFactory.

    Returns the v1 envelope:
        {ok, result: CommandResult.to_dict(), side_effects: [...], version: 1}

    The factory does the lookup; the handler does the work; this
    route only wraps the result for the wire.
    """
    spec = CommandFactory.get(name)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Unknown command: /{name}")

    context = ServerCommandContext(s.engine)
    result = spec.handler(context, request.args)

    envelope = {
        "ok": result.success,
        "result": result.to_dict(),
        "side_effects": [se.to_dict() for se in result.side_effects],
        "version": ENVELOPE_VERSION,
    }
    # Phase B: drain any engine events the handler enqueued
    # (state_sync, working_dir_changed, etc.) into the envelope so
    # web/VSCode see them without waiting for the next /chat.
    return with_drained_events(envelope, s.engine)

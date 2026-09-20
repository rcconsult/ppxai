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

A registered spec with no `handler` is CLIENT-HANDLED (ADR 0007 step
1b — `/token`, `/quit`): the route refuses it in the same envelope,
with `metadata.client_handled` set, and neither runs nor logs
anything derived from `args`.

`events` carry any state_sync / working_dir_changed / etc. that
the handler caused via `state.set(...)`. Without piggybacking
them here, the events sit in `engine._event_queue` until the next
/chat opens an SSE generator to drain them — which makes
non-chat command mutations (e.g. POST /command/cd) invisible to
the web/VSCode AppState mirror until a chat happens. State-sync
determinism Phase B (v1.18.1).
"""

from fastapi import APIRouter, Depends, HTTPException

from ...commands.client_handled import client_handled_result
from ...commands.context import ServerCommandContext
from ...commands.factory import CommandFactory
from ...common.logger import get_logger
from ..models import CommandRequest
from ..state import Session, get_session, with_drained_events

logger = get_logger("server")

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
        # Nothing of the body is logged for an unknown name either: a
        # typo'd /token is still a typo'd secret.
        logger.warning(f"HTTP POST /command/{name} from session={s.id}: Unknown command")
        raise HTTPException(status_code=404, detail=f"Unknown command: /{name}")

    if spec.handler is None:
        # ADR 0007 step 1b: a registered, client-handled spec (/token,
        # /quit). It must not execute, must not 404 (it exists), and its
        # ARGS MUST NOT BE LOGGED OR ECHOED — `/token set <value>` carries
        # a bearer token, and a client reaching here already has a routing
        # bug. The envelope carries `metadata.client_handled` + the
        # `client_action` it should have dispatched to instead.
        logger.warning(
            f"HTTP POST /command/{name} from session={s.id}: client-handled "
            f"(client_action={spec.client_action}), refusing to dispatch"
        )
        result = client_handled_result(spec)
        return with_drained_events({
            "ok": False,
            "result": result.to_dict(),
            "side_effects": [],
            "version": ENVELOPE_VERSION,
        }, s.engine)

    # Logged only once the command is known to be server-dispatched, so a
    # client-handled command's arguments never reach the log at all.
    args_preview = (request.args or "")[:120]
    logger.info(f"HTTP POST /command/{name} from session={s.id} args={args_preview!r}")

    context = ServerCommandContext(s.engine)
    result = spec.handler(context, request.args)
    logger.debug(f"  /{name} ok={result.success} side_effects={len(result.side_effects)}")

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

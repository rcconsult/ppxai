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

ADR 0007 step 2 adds the READ half of the same resource:
``GET /commands`` serves the roster snapshot
(`CommandFactory.roster()`) so web/VSCode stop hand-maintaining
`web/shared/commands.js`. Same module on purpose — one resource, one
route file, and no new entry for the PyInstaller hiddenimport lists.

`events` carry any state_sync / working_dir_changed / etc. that
the handler caused via `state.set(...)`. Without piggybacking
them here, the events sit in `engine._event_queue` until the next
/chat opens an SSE generator to drain them — which makes
non-chat command mutations (e.g. POST /command/cd) invisible to
the web/VSCode AppState mirror until a chat happens. State-sync
determinism Phase B (v1.18.1).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ...commands.client_handled import client_handled_result
from ...commands.context import ServerCommandContext
from ...commands.factory import KNOWN_CLIENTS, SERVER_CLIENTS, CommandFactory
from ...common.logger import get_logger
from ..models import CommandRequest
from ..state import Session, get_session, with_drained_events

logger = get_logger("server")

router = APIRouter()

ENVELOPE_VERSION = 1


def _validated_client(client: str | None) -> str | None:
    """Return `client` if it names a known client, else raise 400.

    Shared by both routes so the request-shape error reads the same
    whether the id arrives as a query param (`GET /commands?client=web`)
    or as a body field (`POST /command/{name}`). `None` (the legacy
    caller that sends no id) is valid and means "unspecified".
    """
    if client is None or client in KNOWN_CLIENTS:
        return client
    # Echo the rejected value back TRUNCATED. It is a client id, not
    # `args`, but this is a field a confused caller could stuff
    # anything into and the detail reaches logs via the client.
    raise HTTPException(
        status_code=400,
        detail=(
            f"Unknown client {client[:40]!r}. Expected one of: "
            f"{', '.join(sorted(KNOWN_CLIENTS))}"
        ),
    )


def _roster_etag(version: int, client: str | None) -> str:
    """Weak ETag for a roster response.

    The payload is a pure function of (registry version, audience), so
    those two are the whole cache key. Weak because the bytes are not
    promised byte-identical across processes — only semantically equal.
    """
    return f'W/"commands-{version}-{client or "server"}"'


@router.get("/commands")
async def get_command_roster(request: Request, client: str | None = None):
    """Serve the command roster snapshot (ADR 0007 step 2).

    The read half of this resource: web/VSCode fetch it once at startup
    instead of restating every command in `web/shared/commands.js`.
    `CommandFactory.roster()` is the ONE serializer — the in-process
    TUIs call the same method directly.

    Args:
        client: Optional client id (`rich` | `textual` | `web` |
            `vscode`). Absent, the audience is the `SERVER_CLIENTS`
            candidate set — the same fallback `commands/system.py::
            _help_client` uses, because this one HTTP surface serves
            both web and VSCode.

    Returns:
        `{"version": int, "commands": [...]}`, with a weak `ETag` so a
        client can revalidate cheaply; `If-None-Match` gets a 304.
    """
    client = _validated_client(client)
    payload = CommandFactory.roster(client if client is not None else SERVER_CLIENTS)
    etag = _roster_etag(payload["version"], client)
    headers = {"ETag": etag, "Cache-Control": "no-cache"}

    inbound = request.headers.get("if-none-match", "")
    if etag in {tag.strip() for tag in inbound.split(",") if tag.strip()}:
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)


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

    ADR 0007 step 2: the body may carry an optional `client` id. It is
    validated FIRST — a request-shape error, and its message quotes only
    the id, never `args`. Absent (which is what every client sends
    today), behaviour is unchanged.
    """
    client = _validated_client(request.client)
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
    # ADR 0007 step 3a-sec: a SERVER-dispatched command may still declare
    # a sensitive subcommand, so the line is redacted through the same
    # one helper before it is truncated. No such command exists today
    # (/token is client-handled), which is exactly why the guard belongs
    # here rather than being remembered later.
    args_preview = (
        CommandFactory.redact_sensitive(f"/{name} {request.args}")
        .removeprefix(f"/{name} ")[:120]
        if request.args else ""
    )
    logger.info(f"HTTP POST /command/{name} from session={s.id} args={args_preview!r}")

    context = ServerCommandContext(s.engine, client=client)
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

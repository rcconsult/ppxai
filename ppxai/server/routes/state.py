"""State endpoint — serves the current AppState snapshot for reconnect.

SSE `state_sync` events flow on the `/chat` stream as fields change.
That works for connected clients but leaves a gap for disconnect /
reconnect: when a web or VSCode client temporarily loses its SSE
connection (network blip, server restart, tab sleep), reconnecting
only restores future events — any `state_sync` that fired during the
gap is lost, and the client's mirror of AppState drifts.

This endpoint returns the current values of every field the engine
pushes via `state_sync` (the `SSE_SYNC_FIELDS` whitelist in
`ppxai.engine.client`). Clients call it on reconnect and feed the
response to `appState.updateFromPython(payload)` to re-synchronise.

    GET /state
    → {"provider": "openai", "model": "gpt-5.2", "agent_mode": false,
       "working_dir": "/home/user/proj", "context_attachments": [...],
       "agent_beat": {}, ...}

Only fields in `SSE_SYNC_FIELDS` are returned — the frequently-
changing ones (is_streaming, usage tokens) are deliberately excluded
so the payload stays small and clients rely on STREAM_END metadata
for those (same contract as live `state_sync` events).
"""

from fastapi import APIRouter, Depends

from ...common.logger import get_logger
from ...engine.client import SSE_SYNC_FIELDS
from ..state import Session, get_session

logger = get_logger("server")

router = APIRouter()


@router.get("/state")
async def get_app_state(s: Session = Depends(get_session)) -> dict:
    """Return the current values of all SSE-synced AppState fields.

    Shape matches the accumulated payload of live `state_sync` events
    — the client can feed the response directly to its own
    `updateFromPython()` facade to re-sync after a disconnect.

    Excludes high-frequency fields (is_streaming, usage tokens) per
    the same contract as live `state_sync` — clients get those from
    STREAM_END metadata, not from reconnect snapshots.
    """
    logger.info(f"HTTP GET /state from session={s.id}")
    snapshot = s.engine.state.snapshot()
    payload = {field: snapshot.get(field) for field in SSE_SYNC_FIELDS}
    # Inc 9: recompute background_agents live from the server-global registry
    # so a reconnecting client gets the authoritative active-run set even if a
    # state_sync push was missed during the disconnect.
    from ..state import get_agent_run_registry

    payload["background_agents"] = get_agent_run_registry().active_summary()
    return payload

"""
Route modules for the ppxai HTTP server.

Each module defines an APIRouter with endpoints for a specific domain.
"""

from fastapi import APIRouter

from . import (
    agent,
    agent_v1,
    chat,
    checkpoints,
    commands,
    completion,
    config,
    consent,
    context,
    file_serve,
    files,
    oneshot,
    preview,
    providers,
    schema,
    sessions,
    state,
    static,
    terminal,
    usage,
)

# Collect all routers for registration
all_routers: list[APIRouter] = [
    config.router,
    chat.router,
    providers.router,
    usage.router,
    commands.router,
    context.router,
    sessions.router,
    files.router,
    file_serve.router,  # v1.17.4: GET /files/serve/<file_id> for raw binary serving
    preview.router,
    consent.router,
    agent.router,
    checkpoints.router,
    terminal.router,
    completion.router,  # v1.17.4: POST /complete for cross-client autocomplete
    schema.router,      # v1.17.4: GET /schema/app-state — canonical DTO
    state.router,       # v1.18.0: GET /state — snapshot for SSE reconnect sync
    oneshot.router,     # v1.18.3: POST /v1/oneshot — stateless gateway primitive
    agent_v1.router,    # v1.19.0: /v1/agent/* — agent run registry (ADR 0003 Stage 2, Inc 1)
    static.router,
]

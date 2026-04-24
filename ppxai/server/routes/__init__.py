"""
Route modules for the ppxai HTTP server.

Each module defines an APIRouter with endpoints for a specific domain.
"""

from fastapi import APIRouter

from . import (
    agent,
    chat,
    checkpoints,
    commands,
    completion,
    config,
    consent,
    context,
    file_serve,
    files,
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
    static.router,
]

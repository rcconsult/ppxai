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
    files,
    preview,
    providers,
    sessions,
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
    preview.router,
    consent.router,
    agent.router,
    checkpoints.router,
    terminal.router,
    completion.router,  # v1.17.4: POST /complete for cross-client autocomplete
    static.router,
]

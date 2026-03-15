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
    config,
    consent,
    context,
    files,
    preview,
    providers,
    sessions,
    static,
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
    static.router,
]

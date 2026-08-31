"""
ppxai Engine - Core business logic layer.

This module provides the engine layer that powers all frontends (TUI, VSCode, Web).
It has no UI dependencies and communicates via events and data structures.
"""

# ADR 0006 Step 7a: import for side effect — registers per-kind
# projection handlers with the ArtifactProjector subclasses
# (ContextAttachmentProjector, TextMarkerProjector, MessageBoxProjector)
# at engine-import time. Consumers can then dispatch via
# `<Projector>.project(ref)` without knowing about specific kinds.
from . import artifact_projections  # noqa: F401
from .client import EngineClient
from .types import (
    ChatResponse,
    Event,
    EventType,
    Message,
    ProviderCapabilities,
    ToolDefinition,
    UsageStats,
)

__all__ = [
    "EventType",
    "Event",
    "Message",
    "UsageStats",
    "ChatResponse",
    "ProviderCapabilities",
    "ToolDefinition",
    "EngineClient",
]

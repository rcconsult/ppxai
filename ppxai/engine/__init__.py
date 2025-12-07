"""
ppxai Engine - Core business logic layer.

This module provides the engine layer that powers all frontends (TUI, VSCode, Web).
It has no UI dependencies and communicates via events and data structures.
"""

from .types import (
    EventType,
    Event,
    Message,
    UsageStats,
    ChatResponse,
    ProviderCapabilities,
    ToolDefinition,
)
from .client import EngineClient

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

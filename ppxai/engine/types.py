"""
Shared types and data classes for the ppxai engine.

These types are used across all layers (engine, server, clients) and have no UI dependencies.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum


class EventType(Enum):
    """Types of events emitted by the engine."""
    STREAM_START = "stream_start"
    STREAM_CHUNK = "stream_chunk"
    STREAM_END = "stream_end"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    CONTEXT_INJECTED = "context_injected"  # File content was auto-injected
    ERROR = "error"
    INFO = "info"


@dataclass
class Event:
    """An event emitted by the engine.

    Events are the primary communication mechanism between engine and clients.
    Clients (TUI, VSCode, Web) consume these events and render them appropriately.
    """
    type: EventType
    data: Any = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class Message:
    """A conversation message."""
    role: str  # 'user', 'assistant', 'system'
    content: str


@dataclass
class UsageStats:
    """Token usage and cost statistics."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0


@dataclass
class ChatResponse:
    """Response from a chat request."""
    content: str
    citations: List[str] = field(default_factory=list)
    usage: Optional[UsageStats] = None


@dataclass
class ProviderCapabilities:
    """Capabilities that a provider has natively (no tool needed)."""
    web_search: bool = False
    web_fetch: bool = False
    weather: bool = False
    citations: bool = False
    streaming: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, bool]) -> 'ProviderCapabilities':
        """Create from dictionary."""
        return cls(
            web_search=data.get('web_search', False),
            web_fetch=data.get('web_fetch', False),
            weather=data.get('weather', False),
            citations=data.get('citations', False),
            streaming=data.get('streaming', True),
        )


@dataclass
class ToolDefinition:
    """Definition of a tool."""
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Optional[Callable] = None
    provider_specific: Optional[List[str]] = None  # If set, only for these providers
    provider_excluded: Optional[List[str]] = None  # If set, excluded for these providers


@dataclass
class ProviderInfo:
    """Information about a provider."""
    id: str
    name: str
    base_url: str
    api_key_env: str
    has_api_key: bool
    capabilities: ProviderCapabilities
    default_model: str
    coding_model: Optional[str] = None


@dataclass
class ModelInfo:
    """Information about a model."""
    id: str
    name: str
    description: str = ""
    context_length: Optional[int] = None


@dataclass
class SessionInfo:
    """Information about a saved session."""
    name: str
    created_at: str
    provider: str
    model: str
    message_count: int


@dataclass
class ToolCallInfo:
    """Information about a tool call."""
    tool_name: str
    arguments: Dict[str, Any]
    result: Optional[str] = None
    error: Optional[str] = None

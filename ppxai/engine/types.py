"""
Shared types and data classes for the ppxai engine.

These types are used across all layers (engine, server, clients) and have no UI dependencies.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Protocol, Set, Union, runtime_checkable
from enum import Enum


# Type alias for multimodal message content.
#
# Messages carry either plain text (the historical format) or a list of
# OpenAI-style content parts for multimodal inputs:
#
#   [{"type": "text", "text": "..."},
#    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]
#
# All str-consuming code paths (logging, token estimation, markdown export,
# clipboard copy, widget rendering) must go through Message.text_content().
MessageContent = Union[str, List[Dict[str, Any]]]


# =============================================================================
# Protocols — structural typing for dependency inversion
#
# These protocols define the interfaces that tool modules type against,
# breaking the circular dependency: client.py → builtin/ → client.py.
# EngineClient and ToolManager satisfy these protocols without inheriting them.
#
# This is the recommended pattern for all cross-module type dependencies
# where a direct import would create a cycle. Define the protocol here
# (leaf module), import it where needed, and let the concrete class
# satisfy it structurally.
# =============================================================================


@runtime_checkable
class ToolEngineProtocol(Protocol):
    """Interface that tools use to interact with the engine.

    Satisfied by EngineClient. Tools import this protocol instead of the
    concrete class, avoiding the client → tools → client circular dependency.
    """

    _agent_edited_files: Set[str]

    def get_working_dir(self) -> Optional[str]: ...
    def set_working_dir(self, path: str) -> None: ...
    async def request_file_edit_consent(self, file_path: str) -> bool: ...
    async def request_shell_consent(self, command: str, working_dir: str = ".") -> bool: ...


@runtime_checkable
class ToolManagerProtocol(Protocol):
    """Interface that tool registration functions use.

    Satisfied by ToolManager. Tool modules import this protocol instead of
    the concrete class, avoiding the manager → builtin → manager cycle.
    """

    def register_tool(self, tool: Any) -> None: ...
    def register_function(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable,
        provider_specific: Optional[List[str]] = None,
        provider_excluded: Optional[List[str]] = None,
    ) -> None: ...


class EventType(Enum):
    """Types of events emitted by the engine."""
    STREAM_START = "stream_start"
    STREAM_CHUNK = "stream_chunk"
    REASONING_CHUNK = "reasoning_chunk"  # Reasoning tokens (DeepSeek R1, GPT-OSS 120B)
    STREAM_END = "stream_end"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    CONTEXT_INJECTED = "context_injected"  # File content was auto-injected
    CONSENT_REQUEST = "consent_request"  # Request user consent for file edit (v1.11.0)
    AGENT_ITERATION = "agent_iteration"  # Start of agent iteration (v1.11.8)
    AGENT_COMPLETE = "agent_complete"  # Agent task completed (v1.11.8)
    AGENT_MAX_ITERATIONS = "agent_max_iterations"  # Max iterations reached (v1.11.8)
    STATUS = "status"  # Status/notification messages (v1.12.0 - checkpoints, etc.)
    WORKING_DIR_CHANGED = "working_dir_changed"  # Working directory changed (v1.13.2)
    DISPLAY_FILE = "display_file"  # Display file in viewer (v1.15.1)
    TOOL_GROUP_START = "tool_group_start"  # Start of tool calls in one iteration (v1.16.0)
    TOOL_GROUP_END = "tool_group_end"  # End of tool calls in one iteration (v1.16.0)
    STATE_SYNC = "state_sync"  # AppState field changed — push to connected clients (v1.17.1)
    AGENT_INTERMEDIATE_PROSE = "agent_intermediate_prose"  # R12 Opt 1 (v1.17.5): model prose between tool iterations
    AGENT_BEAT = "agent_beat"  # P0 (v1.18.0): structured per-iteration heartbeat — iteration/tool/ok/failures/elapsed_s
    AGENT_RUN_START = "agent_run_start"  # P0 (v1.18.0): whole-run start (fires once per chat_with_tools invocation)
    AGENT_RUN_ERROR = "agent_run_error"  # P0 (v1.18.0): whole-run errored — payload includes reason + last iteration
    AGENT_ZOMBIE = "agent_zombie"  # P0 (v1.18.0): circuit breaker — consecutive tool failures exceeded threshold
    WARNING = "warning"  # Validation warning (v1.15.2 - hallucination detection)
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
    """A conversation message.

    `content` is either a plain string (historical single-modal format) or a
    list of OpenAI-style content parts for multimodal messages (text + images,
    uploaded file references). Code that needs plain text for logging,
    serialization, or widget rendering must use `text_content()` rather than
    reading `content` directly.
    """
    role: str  # 'user', 'assistant', 'system', 'tool'
    content: MessageContent
    tool_calls: Optional[List[Dict[str, Any]]] = None   # For assistant messages with native calls
    tool_call_id: Optional[str] = None                    # For tool role messages

    def text_content(self) -> str:
        """Extract plain text from the message content.

        For string content, returns it as-is. For list content (multimodal),
        joins the text of all `{"type": "text", ...}` parts with newlines and
        adds `[Image: name]` / `[File: name]` placeholders for non-text parts
        so logs, token estimates, and markdown exports remain human-readable.
        """
        if isinstance(self.content, str):
            return self.content
        if not isinstance(self.content, list):
            return str(self.content)
        parts: List[str] = []
        for block in self.content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "image_url":
                # Surface a placeholder so callers that slice/len the result
                # still see something meaningful (e.g. logger previews).
                url = (block.get("image_url") or {}).get("url", "")
                name = block.get("name") or _guess_name_from_url(url) or "image"
                parts.append(f"[Image: {name}]")
            elif btype == "input_file" or btype == "file":
                name = block.get("name") or block.get("filename") or "file"
                parts.append(f"[File: {name}]")
            elif btype == "uploaded_file":
                # R5 (v1.17.6): first-class uploaded-file block. For
                # human-readable display (logs, token estimates, markdown
                # exports) render `[File: name (media_type)]` so the
                # output matches what `input_file` / `file` blocks look
                # like. Providers never see this branch because they
                # flatten uploaded_file to text before calling this.
                name = block.get("name") or "file"
                media = block.get("media_type") or ""
                parts.append(f"[File: {name} ({media})]" if media else f"[File: {name}]")
            else:
                # Unknown part type — include a marker but don't crash.
                parts.append(f"[{btype or 'part'}]")
        return "\n".join(parts)


def _guess_name_from_url(url: str) -> str:
    """Best-effort filename extraction from an image_url (data: or http)."""
    if not url or url.startswith("data:"):
        return ""
    # Strip query string, take basename.
    tail = url.split("?", 1)[0].rstrip("/")
    return tail.rsplit("/", 1)[-1] if "/" in tail else tail


@dataclass
class ToolUsage:
    """Usage tracking for a specific tool.

    Tracks both per-token pricing (Perplexity) and per-query pricing (Gemini).
    """
    call_count: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    estimated_cost: float = 0.0
    provider: str = ""  # "perplexity", "gemini", "duckduckgo"

    def add_usage(self, tokens_in: int = 0, tokens_out: int = 0, cost: float = 0.0):
        """Add usage from a single tool call."""
        self.call_count += 1
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.estimated_cost += cost


@dataclass
class UsageStats:
    """Token usage and cost statistics."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0
    tool_calls: Dict[str, 'ToolUsage'] = field(default_factory=dict)


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
    native_tool_calling: bool = False  # OpenAI-style function calling

    @classmethod
    def from_dict(cls, data: Dict[str, bool]) -> 'ProviderCapabilities':
        """Create from dictionary."""
        return cls(
            web_search=data.get('web_search', False),
            web_fetch=data.get('web_fetch', False),
            weather=data.get('weather', False),
            citations=data.get('citations', False),
            streaming=data.get('streaming', True),
            native_tool_calling=data.get('native_tool_calling', False),
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
    saved_at: str = ""  # When session was last saved


@dataclass
class ToolCallInfo:
    """Information about a tool call."""
    tool_name: str
    arguments: Dict[str, Any]
    result: Optional[str] = None
    error: Optional[str] = None


@dataclass
class AgentBeatState:
    """Structured per-iteration heartbeat state for the agent tool loop (P0, v1.18.0).

    Emitted on every `chat_with_tools` iteration as `EventType.AGENT_BEAT`
    data payload. Clients render progress bars, elapsed timers, and tool
    counters from these fields instead of parsing free-form text.

    Also the building block for zombie detection: when
    `consecutive_failures` crosses the configured threshold the engine
    emits `EventType.AGENT_ZOMBIE` and breaks the loop.

    Design note: shape mirrors ppxai-sre-core's AgentBeatState so that
    both standalone ppxai agent mode AND ppxai-sre scheduled agents
    surface identical data to clients — one widget for both.
    """
    iteration: int = 0
    beat_sequence: int = 0
    last_beat_time: float = 0.0
    last_tool: str = ""
    last_run_ok: bool = True
    consecutive_failures: int = 0
    start_time: float = 0.0

    @property
    def elapsed_s(self) -> float:
        """Wall time since run start in seconds (0.0 if not yet started)."""
        import time
        if not self.start_time:
            return 0.0
        return time.monotonic() - self.start_time

    def as_event_data(self) -> Dict[str, Any]:
        """Serialize to the AGENT_BEAT event payload (stable wire shape).

        The keys here are the canonical schema — web/VSCode/TUI
        renderers depend on these names. Don't rename without updating
        every client.
        """
        return {
            "iteration": self.iteration,
            "beat": self.beat_sequence,
            "tool": self.last_tool,
            "ok": self.last_run_ok,
            "failures": self.consecutive_failures,
            "elapsed_s": round(self.elapsed_s, 1),
        }

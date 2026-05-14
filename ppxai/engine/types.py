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
    def register_subprocess(self, proc: Any) -> None: ...
    def unregister_subprocess(self, proc: Any) -> None: ...


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


@runtime_checkable
class EngineClientProtocol(Protocol):
    """Interface that the commands layer uses to drive the engine.

    Satisfied by `ppxai.engine.client.EngineClient`. Commands import this
    protocol instead of the concrete class so the commands→engine
    boundary stays nominally decoupled (Item 10, v1.18.2). Following
    the same pattern as `ToolEngineProtocol` and `ToolManagerProtocol`
    above — leaf-module Protocol, structural satisfaction, no inheritance.

    Surface enumerated by walking every `engine_client.<X>` and
    `self._engine.<X>` reference in `ppxai/commands/*.py` on 2026-04-28
    (commit `909db8f3`). Adding a new method here means commands now
    depend on it; removing one means at least one command path breaks.

    Order below mirrors the rough functional grouping:
      1. AppState + session access (read-mostly)
      2. Provider/model switching
      3. Working directory
      4. Tool + agent management
      5. Bootstrap + context injection
      6. Checkpoint backends
      7. Conversation flow (chat, restore_session)
      8. Misc (config reload, logger, etc.)
    """

    # --- 1. AppState + session access --------------------------------
    @property
    def session(self) -> Any: ...
    @property
    def state(self) -> Any: ...
    @property
    def model(self) -> str: ...
    @property
    def tools_enabled(self) -> bool: ...
    @property
    def agent_mode(self) -> bool: ...
    @property
    def tool_manager(self) -> Any: ...
    @property
    def last_model_switch_reset(self) -> int: ...
    @property
    def context_injector(self) -> Any: ...

    # --- 2. Provider / model switching -------------------------------
    def set_model(self, model: str, reset_context: bool = True) -> None: ...
    def set_provider(self, provider: str) -> None: ...

    # --- 3. Working directory ----------------------------------------
    def get_working_dir(self) -> Optional[str]: ...
    def set_working_dir(self, path: str) -> None: ...

    # --- 4. Tool + agent management ----------------------------------
    def enable_tools(self) -> None: ...
    def disable_tools(self) -> None: ...
    def enable_agent_mode(self) -> None: ...
    def disable_agent_mode(self) -> None: ...
    def get_agent_config(self) -> Any: ...
    def get_tools_status(self) -> Dict[str, Any]: ...
    def set_tool_config(self, key: str, value: Any) -> None: ...

    # --- 5. Bootstrap + context injection ----------------------------
    def get_bootstrap_status(self) -> Any: ...
    def get_active_hints(self) -> Any: ...
    def reload_bootstrap_context(self) -> bool: ...
    def reload_config(self) -> None: ...
    def clear_injected_contexts(self) -> Any: ...
    def get_context_info(self) -> Any: ...
    def get_context_attachments(self) -> List[Dict[str, Any]]: ...
    def remove_context_attachment(self, target: str) -> Any: ...

    # --- 6. Checkpoints ----------------------------------------------
    def create_checkpoint(self, label: str) -> Any: ...
    def undo_last_checkpoint(self) -> bool: ...
    def get_checkpoint_status(self) -> Any: ...
    def list_checkpoints(self, limit: int = 20) -> List[Any]: ...
    def set_checkpoint_backend(self, backend: str) -> bool: ...
    def clear_file_checkpoints(self, keep_last: int = 0) -> int: ...

    # --- 7. Conversation flow ----------------------------------------
    def chat(self, message: str, stream: bool = True) -> Any: ...
    def restore_session(self, name: str) -> Any: ...


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
    AGENT_RUN_COMPLETE = "agent_run_complete"  # P0 (v1.18.0): whole-run finished successfully (always fires; unlike AGENT_COMPLETE it's not agent_mode-gated)
    AGENT_RUN_ERROR = "agent_run_error"  # P0 (v1.18.0): whole-run errored — payload includes reason + last iteration
    AGENT_ZOMBIE = "agent_zombie"  # P0 (v1.18.0): circuit breaker — consecutive tool failures exceeded threshold
    WARNING = "warning"  # Validation warning (v1.15.2 - hallucination detection)
    ERROR = "error"
    PROVIDER_THROTTLED = "provider_throttled"  # v1.18.3: provider-side rate-limit / quota block (HTTP 429 / 403). Distinct from ERROR so callers can skip-not-fail (benchmarks) or render differently (UI toast vs banner). Payload: {"status_code": int, "provider": str, "model": str, "message": str, "retry_after": Optional[float]}
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
class ImageAttachmentRef:
    """Per-attachment metadata living alongside Message.content (ADR 0006, Phase 1).

    Engine-internal bookkeeping that documents an attachment without
    polluting the wire-format content block. `block_index` is the join
    key — `message.attachments[i]` describes
    `message.content[message.attachments[i].block_index]`.

    Today (Phase 1, v1.18.6): populated alongside the legacy in-block
    `name` + `file_id` keys at message-construction time. Existing
    readers continue to use the in-block keys; this field is purely
    additive. The field exists so Phase 2 can switch readers over and
    Phase 3 can drop the in-block keys without churning every call site
    in one pass.

    Attributes:
        block_index: Position in `message.content` of the block this
            attachment annotates. Stable across serialize/deserialize
            because content list ordering is preserved.
        name: Canonical filename (basename only). Comes from the
            preprocessing pipeline (`engine.session_store` canonicalizes).
        file_id: SessionFileStore identifier (sha256 prefix). Empty
            string when the attachment wasn't persisted (rare —
            test fixtures, in-memory previews, file_store unavailable).
        media_type: Canonical MIME type. May differ from what the
            caller declared because magic-byte sniffing wins.
    """
    block_index: int
    name: str
    file_id: str = ""
    media_type: str = ""


def extract_attachment_refs(content: Any) -> List["ImageAttachmentRef"]:
    """Walk a multimodal content list and pull out attachment metadata.

    Reads the legacy in-block `name` + `file_id` keys that producers
    (`file_preprocessing._preprocess_image`) and the session
    serialize/deserialize round-trip embed inside `image_url` blocks
    today. Returns an `ImageAttachmentRef` for each block that carries either
    `name` or `file_id`.

    This is the bridge between today's "metadata inside content blocks"
    state and Phase 2's "metadata in `Message.attachments`" target. Both
    can coexist during the migration without behavioral change.

    Returns an empty list when `content` is a string or has no
    attachment-bearing blocks. Never raises — defensive against
    malformed content (caller-supplied dicts may be missing keys).
    """
    if not isinstance(content, list):
        return []
    refs: List[ImageAttachmentRef] = []
    for idx, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype != "image_url":
            # Phase 1 scope: only image_url carries the entangled
            # name/file_id keys. uploaded_file is its own engine-internal
            # block type with its own metadata fields (`name`,
            # `media_type`, `file_id`) but those are intrinsic to the
            # block type, not bookkeeping pollution — leave them alone.
            # Phase 4 may revisit if uploaded_file readers benefit from
            # the same projection.
            continue
        name = block.get("name") or ""
        file_id = block.get("file_id") or ""
        if not name and not file_id:
            # No metadata to extract — block was constructed without
            # going through the preprocessing pipeline (manual API
            # caller, test fixture). Skip silently.
            continue
        refs.append(ImageAttachmentRef(
            block_index=idx,
            name=name,
            file_id=file_id,
            media_type="",  # producers don't set media_type inside the block today
        ))
    return refs


@dataclass
class Message:
    """A conversation message.

    `content` is either a plain string (historical single-modal format) or a
    list of OpenAI-style content parts for multimodal messages (text + images,
    uploaded file references). Code that needs plain text for logging,
    serialization, or widget rendering must use `text_content()` rather than
    reading `content` directly.

    `attachments` (ADR 0006 Phase 1, v1.18.6) is engine-internal
    bookkeeping that runs alongside `content`. It is NOT sent on the
    wire — provider adapters serialize `content` only. Today it
    duplicates information that also lives inside content blocks
    (`image_url.name`, `image_url.file_id`); Phase 2 switches readers
    over to walk `attachments`, Phase 3 drops the in-block keys, Phase
    4 versions the on-disk session JSON to carry both fields side by
    side. See `docs/decisions/0006-content-block-schema-separation.md`.
    """
    role: str  # 'user', 'assistant', 'system', 'tool'
    content: MessageContent
    tool_calls: Optional[List[Dict[str, Any]]] = None   # For assistant messages with native calls
    tool_call_id: Optional[str] = None                    # For tool role messages
    attachments: List["ImageAttachmentRef"] = field(default_factory=list)  # ADR 0006 Phase 1

    def attachment_for_block(self, block_index: int) -> Optional["ImageAttachmentRef"]:
        """Return the ImageAttachmentRef whose block_index == `block_index`, or None.

        ADR 0006 Phase 2a low-level lookup. Most readers should use the
        higher-level `resolve_attachment(idx)` instead — that one handles
        the ImageAttachmentRef-first-with-in-block-fallback pattern in one
        place. Direct `attachment_for_block` is for callers that
        deliberately want to know whether ImageAttachmentRef is present or
        absent (e.g. tests asserting Phase 1 invariants).

        Linear scan is fine — `attachments` is bounded by the number of
        image_url blocks in a single message, which in practice is 1-5.
        Don't index it; the call cost is dwarfed by the surrounding
        block-walk anyway.
        """
        for ref in self.attachments:
            if ref.block_index == block_index:
                return ref
        return None

    def resolve_attachment(self, block_index: int) -> "ImageAttachmentRef":
        """Get the effective ImageAttachmentRef for a content block, deriving
        from in-block keys when no explicit ImageAttachmentRef exists.

        ADR 0006 Phase 2a/2b shared helper. Single source of truth for
        the ImageAttachmentRef-first-with-fallback lookup pattern that ADR
        0006 readers use during the migration:

          1. Look up self.attachments by block_index (fast path —
             every Message constructed via the producer pipeline OR
             loaded via _deserialize_message satisfies this)
          2. Synthesize an ImageAttachmentRef from the in-block `name` and
             `file_id` keys (fallback for messages built outside the
             producer pipeline — test fixtures, manual API callers,
             pre-Phase-1 sessions loaded by old builds)
          3. Return an empty ImageAttachmentRef as last resort (block isn't
             image_url, or block_index is out of range, or block has
             no attachable metadata)

        ALWAYS returns an ImageAttachmentRef — never None. Callers can read
        `.name` / `.file_id` without None-handling. Empty values are
        the empty string, not None, so existing code paths that do
        `name = ref.name or "image"` work unchanged.

        Phase 3 simplifies this to just step 1 + step 3 (drop step 2)
        once producers stop emitting in-block keys. Callers don't
        change — only the helper internals do.
        """
        ref = self.attachment_for_block(block_index)
        if ref is not None:
            return ref
        # Synthesize from in-block keys for messages built outside the
        # producer pipeline. Phase 3 drops this branch.
        if isinstance(self.content, list) and 0 <= block_index < len(self.content):
            block = self.content[block_index]
            if isinstance(block, dict) and block.get("type") == "image_url":
                return ImageAttachmentRef(
                    block_index=block_index,
                    name=block.get("name") or "",
                    file_id=block.get("file_id") or "",
                    media_type="",
                )
        return ImageAttachmentRef(block_index=block_index, name="", file_id="", media_type="")

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
        for idx, block in enumerate(self.content):
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "image_url":
                # ADR 0006 Phase 2a/2b: get the effective ImageAttachmentRef
                # via resolve_attachment (handles ImageAttachmentRef-first
                # lookup with in-block-key fallback in one place — see
                # docstring). Falls back to URL-derived guessing only
                # when both ImageAttachmentRef and in-block name are empty,
                # which only happens for remote-URL image_url blocks
                # built outside any preprocessing pipeline.
                ref = self.resolve_attachment(idx)
                if ref.name:
                    name = ref.name
                else:
                    url = (block.get("image_url") or {}).get("url", "")
                    name = _guess_name_from_url(url) or "image"
                parts.append(f"[Image: {name}]")
            elif btype == "input_file" or btype == "file":
                # Intentionally NOT migrated to ImageAttachmentRef — these
                # block types' name is intrinsic to the block schema,
                # not bookkeeping pollution. Phase 1's
                # extract_attachment_refs scope was image_url only.
                name = block.get("name") or block.get("filename") or "file"
                parts.append(f"[File: {name}]")
            elif btype == "uploaded_file":
                # R5 (v1.17.6): first-class uploaded-file block. For
                # human-readable display (logs, token estimates, markdown
                # exports) render `[File: name (media_type)]` so the
                # output matches what `input_file` / `file` blocks look
                # like. Providers never see this branch because they
                # flatten uploaded_file to text before calling this.
                # Same intrinsic-metadata rationale as input_file/file —
                # not migrated to ImageAttachmentRef.
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

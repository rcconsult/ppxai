"""
Engine Client - Main facade for the ppxai engine.

This is the primary interface for all frontends (TUI, VSCode, Web).
It has no UI dependencies and communicates via events.
"""

import asyncio
import base64
import os
import threading
from datetime import datetime
from typing import List, AsyncIterator, Optional, Dict, Any
from pathlib import Path

from .types import (
    Message, MessageContent, Event, EventType, UsageStats,
    ProviderInfo, ModelInfo, ProviderCapabilities
)
from ..prompts import CODING_PROMPTS
from .providers import create_provider
from .providers.base import BaseProvider
from .tools.manager import ToolManager
from .tools.builtin import register_all_builtin_tools
from .tools.parser import parse_tool_call
from .chat import chat_simple, chat_with_tools
from .providers.openai_compat import OpenAICompatibleProvider
from .session import SessionManager
from .session_store import SessionFileStore
from .context import ContextInjector, ScopedBootstrapSource
from .bootstrap import BootstrapContext
from ..checkpoint import CheckpointManager
from ..config import (
    get_api_key,
    get_base_url,
    get_shell_config,
    get_agent_config,
    get_vision_model_config,
    reload_config as _reload_config,
    PROVIDERS,
)
from ..common.logger import get_logger
from ..constants import Default
from .app_state import AppState
from . import bootstrap_ops, checkpoint_ops, consent_ops, session_ops

logger = get_logger("tui")


class EngineClient:
    """Main engine client - the facade for all engine functionality.

    This is the primary interface for all frontends (TUI, VSCode, Web).
    All communication is via events and data structures, never direct console output.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        consent_callback: Optional[callable] = None,
        shell_consent_callback: Optional[callable] = None
    ):
        """Initialize the engine client.

        Args:
            config: Optional configuration dictionary
            consent_callback: Optional callback for file edit consent (v1.11.0)
                             Signature: async (file_path: str) -> tuple[bool, str]
                             Returns: (approved: bool, response: str)
                             response can be: "y", "n", "always", "never"
            shell_consent_callback: Optional callback for shell command consent (v1.11.2)
                             Signature: async (command: str, working_dir: str, risk_level: str) -> tuple[bool, str]
                             Returns: (approved: bool, response: str)
                             response can be: "y", "n", "always", "never"
        """
        self.config = config or {}
        self.provider: Optional[BaseProvider] = None
        self.provider_name: str = ""
        self.model: str = ""

        self.tool_manager = ToolManager()
        self.session = SessionManager()
        self.tools_enabled: bool = False

        # Binary file store for multimodal attachments (v1.17.4 Phase 2.1a).
        # Owned by the engine and shared with the session manager, which
        # uses it during serialize/deserialize to rewrite inline base64
        # into compact file_id references. Tools (ReadPdfTool,
        # GetPdfPageImageTool, future Excel/PPTX tools) resolve file_ids
        # through `engine.file_store.get(file_id)`. Web/VSCode clients
        # will fetch thumbnails via a server endpoint keyed on file_id.
        self.file_store = SessionFileStore()
        self.session.file_store = self.file_store

        # Canonical observable state — single source of truth shared across
        # all clients. Mutators below keep this in sync with instance fields.
        self.state = AppState()

        # Wire session → AppState sync callbacks
        self.session.on_usage_updated = self._sync_usage_to_state
        self.session.on_name_changed = lambda name: self.state.update(
            session_id=name, session_name=name
        )
        # Every time session.messages mutates (add_message, remove_last_message,
        # clear, load, strip_to_user_messages, validate_and_fix_alternation)
        # recompute the multimodal-attachments summary in AppState. That is
        # the single source of truth every client reads for its attachment
        # badge/chip UI — Rich status bar today, Textual/Web/VSCode in later
        # phases — so hoisting it into AppState here means zero per-client
        # scanning of session.messages and automatic state_sync propagation
        # over SSE for remote clients.
        self.session.on_messages_changed = self._refresh_context_attachments
        # Sync initial session name
        self.state.set("session_name", self.session.session_name)
        # Initial attachments snapshot (empty list, but sets the field so
        # any early subscriber sees a consistent shape).
        self._refresh_context_attachments()

        # Context injection for automatic file content inclusion
        self.context_injector = ContextInjector()
        self.auto_inject_context: bool = True  # Enabled by default

        # Track injected contexts for /context command
        self._injected_contexts: List[Dict[str, Any]] = []

        # Bootstrap context from AGENTS.md/CLAUDE.md (v1.14.0, v1.14.2 scopes)
        self._bootstrap_context: Optional[BootstrapContext] = None
        self._bootstrap_sources: List[ScopedBootstrapSource] = []

        # Interrupt handling for graceful stream cancellation
        self._interrupted: bool = False

        # File edit consent callback (Phase 1: v1.11.0)
        self.consent_callback = consent_callback

        # Shell command consent callback (v1.11.2)
        self.shell_consent_callback = shell_consent_callback

        # Agent mode for autonomous task execution (v1.11.8)
        self._agent_mode: bool = False

        # Checkpoint manager for atomic multi-file rollback (v1.12.0)
        self._checkpoint_manager: Optional[CheckpointManager] = None
        self._last_checkpoint_id: Optional[str] = None
        # Track files edited by agent during current task (v1.12.0)
        self._agent_edited_files: set = set()

        # Verbose mode for tool output display (matches TUI behavior)
        self._tools_verbose: bool = False

        # Track last model switch context reset (v1.16.0, A3)
        # Set by set_model() when reset_context strips messages
        self.last_model_switch_reset: int = 0

        # Suppress hint logging during internal set_model calls from set_provider()
        # Initialized here so the flag always exists on the instance (not just on first
        # set_provider call).  _log_model_hints_transition reads it via getattr so a
        # missing attribute would fall back to False (unsuppressed), but explicit
        # initialization makes the intent clear and avoids any early-call edge cases.
        self._suppress_hint_log: bool = False

        # Event side-channel for SSE streaming (consent requests, state sync).
        # Protected by a lock — SSE drain loop pops while listeners/callbacks append.
        self._event_queue: List[Event] = []
        self._event_queue_lock = threading.Lock()

        # Push AppState changes to SSE side-channel so connected web/VSCode
        # clients stay in sync. Fields that change frequently during streaming
        # (is_streaming, cancel_requested, usage tokens) are excluded to avoid
        # flooding the SSE channel — clients read those from STREAM_END metadata.
        _SSE_SYNC_FIELDS = {
            "provider", "model", "tools_enabled", "tools_verbose",
            "agent_mode", "auto_route", "working_dir",
            "session_name", "debug_log",
            "context_attachments",  # v1.17.4 Phase 3.3
        }
        for _field in _SSE_SYNC_FIELDS:
            self.state.on(_field, lambda v, k=_field: self.enqueue_event(
                Event(type=EventType.STATE_SYNC, data={k: v})
            ))

        # Load configuration (including shell command patterns)
        self._load_config()

        # Initialize checkpoint manager with default working directory
        # This ensures TUI has checkpoints available without explicit set_working_dir call
        self._init_checkpoint_manager(self.context_injector.working_dir)

        # Load bootstrap context from AGENTS.md/CLAUDE.md (v1.14.0)
        self.load_bootstrap_context()

    def _load_config(self):
        """Load configuration from ppxai-config.json and .env."""
        # Store references to config functions for provider management
        self._get_api_key = get_api_key
        self._get_base_url = get_base_url

        # Use centralized config functions with defaults from config/defaults.py
        self._shell_config = get_shell_config()
        self._agent_config = get_agent_config()

    def reload_config(self):
        """Reload configuration from disk and refresh engine state.

        Reloads the ConfigStore from disk, which also updates module-level
        PROVIDERS/MODELS in-place. Then refreshes shell and agent configs.
        """
        _reload_config()  # Updates PROVIDERS/MODELS in place via initialize()
        self._shell_config = get_shell_config()
        self._agent_config = get_agent_config()

    @property
    def providers_config(self) -> dict:
        """Always returns current providers from config module.

        No caching - reads fresh PROVIDERS dict which is updated in-place
        by config.reload_config() -> initialize().
        """
        return PROVIDERS

    # === Context Injection ===

    def _init_checkpoint_manager(self, path: str):
        """Initialize checkpoint manager for a working directory (v1.12.0).

        Args:
            path: Working directory path
        """
        checkpoint_backend = self.config.get("tools", {}).get("agent", {}).get("checkpoint_backend", "auto")
        session_id = self.session.session_name or "default"
        self._checkpoint_manager = CheckpointManager(
            working_dir=path,
            session_id=session_id,
            backend=checkpoint_backend
        )

        # Restore last checkpoint ID from existing checkpoints (persistence across restarts)
        try:
            checkpoints = self._checkpoint_manager.list_checkpoints()
            if checkpoints:
                # list_checkpoints returns [(id, description, timestamp), ...] sorted by recency
                self._last_checkpoint_id = checkpoints[0][0]
        except Exception as e:
            logger.debug(f"Failed to restore checkpoint ID: {e}")
            # Checkpoint ID will be None until first checkpoint is created

    # === Thread-safe event queue ===

    def enqueue_event(self, event: Event) -> None:
        """Thread-safe append to the SSE event side-channel."""
        with self._event_queue_lock:
            self._event_queue.append(event)

    def drain_events(self) -> List[Event]:
        """Atomically drain all pending events. Returns the list (may be empty)."""
        with self._event_queue_lock:
            events = self._event_queue
            self._event_queue = []
        return events

    def _sync_usage_to_state(self, usage: 'UsageStats') -> None:
        """Callback from session.update_usage() — sync totals to AppState."""
        # Context percentage — derived from session message history
        try:
            context_info = self.get_context_info()
            context_pct = context_info.get('usage_percent', 0.0)
        except Exception:
            context_pct = 0.0

        self.state.update(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            total_cost=usage.estimated_cost,
            context_percentage=context_pct,
        )

    def _refresh_context_attachments(self) -> None:
        """Recompute the `context_attachments` AppState field from session history.

        Called from `session.on_messages_changed` after every mutation of
        `session.messages`. Walks the history once, extracts one dict per
        unique multimodal content part, and writes the full list to
        AppState. The write is a no-op (no listener fire, no SSE push) if
        the computed list is equal to the previous value — so this is safe
        to call on every mutation, including assistant turns that never
        contain attachments.

        **Role filter (important invariant for Phase 2.8+):** only
        `role == "user"` turns contribute to `context_attachments`.
        Tool-generated images (e.g. `GetPdfPageImageTool` returning a
        rasterized PDF page, Phase 2.8; `RenderExcelChartTool`, Phase 4)
        land in `role == "tool"` or `role == "assistant"` messages and
        are deliberately excluded. Rationale: the badge represents "what
        the user attached to this conversation," not "every multimodal
        artifact in the history." A user who reads 20 PDF pages via tools
        should not see 20 entries in their badge — that would bury real
        user uploads and conflate intent (deliberate attach) with side
        effects (tool exploration). If we later want to surface tool
        artifacts as a separate badge, Phase 4 can add a `kind="tool_output"`
        variant and a second AppState field or a grouped display.

        Entry schema matches the contract documented on AppState.FIELDS:
        `{"name", "kind", "media_type", "turn_index", "file_id"}`. Keys
        are stable and JSON-serializable so web/VSCode clients can consume
        this via SSE `state_sync` without any translation. `file_id` is
        the empty string for legacy entries (Phase 1 sessions predating
        SessionFileStore); clients use it to request thumbnails from a
        future server endpoint.
        """
        attachments: List[Dict[str, Any]] = []
        seen_keys: set = set()
        for turn_index, msg in enumerate(self.session.messages):
            # Role filter — see docstring. Tool/assistant multimodal content
            # is invisible to this scanner by design.
            if getattr(msg, "role", None) != "user":
                continue
            content = getattr(msg, "content", None)
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "image_url":
                    name = block.get("name") or "image"
                    file_id = block.get("file_id") or ""
                    # Dedup key prefers file_id (stable content-addressed
                    # identity) and falls back to name for legacy blocks.
                    dedup_key = file_id or name
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)

                    # Prefer authoritative metadata from the file store
                    # (populated in Phase 2.1a). Falls back to parsing the
                    # data URI for pure-Phase-1 content blocks.
                    media_type = ""
                    if file_id and self.file_store is not None:
                        meta = self.file_store.get_metadata(file_id)
                        if meta is not None:
                            media_type = meta.media_type
                            # Keep the filename from the store canonical
                            # — it survives save→load round trips.
                            name = meta.name
                    if not media_type:
                        url = (block.get("image_url") or {}).get("url", "")
                        if url.startswith("data:"):
                            try:
                                media_type = url[5:].split(";", 1)[0] or ""
                            except Exception:
                                media_type = ""

                    attachments.append({
                        "name": name,
                        "kind": "image",
                        "media_type": media_type,
                        "turn_index": turn_index,
                        "file_id": file_id,
                    })
                elif btype in ("input_file", "file"):
                    name = block.get("name") or block.get("filename") or "file"
                    file_id = block.get("file_id") or ""
                    dedup_key = file_id or name
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)
                    attachments.append({
                        "name": name,
                        "kind": "file",
                        "media_type": block.get("media_type") or "",
                        "turn_index": turn_index,
                        "file_id": file_id,
                    })
                # text parts intentionally ignored — text-file attachments
                # merge into the prompt at send time and leave nothing
                # distinguishable in session history.

        # AppState.set() short-circuits on equality so unchanged lists don't
        # fire listeners or SSE events.
        self.state.set("context_attachments", attachments)

    def get_context_attachments(self) -> List[Dict[str, Any]]:
        """Return the current multimodal attachments in conversation context.

        Reads from AppState — the canonical source maintained by
        `_refresh_context_attachments`. Clients should prefer this method
        (or subscribing to the `context_attachments` AppState field
        directly) over scanning `session.messages` themselves, so all
        four clients render identical data.
        """
        return list(self.state.get("context_attachments") or [])

    def remove_context_attachment(self, name: str) -> int:
        """Drop all user-turn multimodal parts matching `name` from history.

        Walks `session.messages`, rewrites any user message containing an
        `image_url` or file content part whose `name` field (or file_id)
        matches the argument, and drops those parts. Messages whose
        content list becomes empty after removal get a `[Attachment
        removed: name]` text placeholder so conversation alternation stays
        valid — dropping the whole message would leave consecutive
        assistant turns and violate provider API rules.

        The SessionFileStore file_id → path mapping is intentionally NOT
        touched: other turns may still reference the same file_id, and
        cleaning up orphaned bytes is the job of `cleanup_all` at session
        teardown. Clients that want to reclaim disk space immediately can
        call `file_store.cleanup(file_id)` themselves after confirming no
        remaining message references the id.

        Fires `on_messages_changed` at the end, which refreshes the
        `context_attachments` AppState field and cascades to every
        subscribed client (Rich status bar, Textual footer, web chips,
        VSCode chips).

        Args:
            name: Attachment display name as reported by
                  `get_context_attachments()`, OR the literal string
                  "all" to remove every attachment in one call. Matches
                  are case-insensitive for "all"; exact for names so
                  files that legitimately share a prefix aren't grouped.

        Returns:
            Number of content parts removed across all messages. Zero
            indicates no matches — the caller should surface a "no
            such attachment" message rather than pretending success.
        """
        if not name:
            return 0

        remove_all = name.lower() == "all"
        removed_count = 0
        mutated = False

        for msg in self.session.messages:
            if getattr(msg, "role", None) != "user":
                continue
            content = getattr(msg, "content", None)
            if not isinstance(content, list):
                continue

            kept: List[Dict[str, Any]] = []
            had_attachment = False
            for block in content:
                if not isinstance(block, dict):
                    kept.append(block)
                    continue
                btype = block.get("type")
                if btype not in ("image_url", "input_file", "file"):
                    kept.append(block)
                    continue
                block_name = (
                    block.get("name")
                    or block.get("filename")
                    or block.get("file_id")
                    or ""
                )
                if remove_all or block_name == name:
                    removed_count += 1
                    had_attachment = True
                    continue
                kept.append(block)

            if not had_attachment:
                continue

            # If the message now has no content parts left (a rare case
            # where a user turn was nothing but attachments), inject a
            # text placeholder so alternation stays valid.
            if not kept:
                kept.append({
                    "type": "text",
                    "text": f"[Attachment removed: {name}]",
                })

            msg.content = kept
            mutated = True

        if mutated:
            self.session._notify_messages_changed()

        return removed_count

    # ------------------------------------------------------------------
    # Vision-language sidecar (v1.17.4 Phase 2.7)
    # ------------------------------------------------------------------

    def has_vision_model(self) -> bool:
        """Return True if a vision-language sidecar is configured and usable.

        Checks the `tools.vision_model` config section: the sidecar is
        "available" when `enabled=True`, endpoint and model are both
        non-empty, and (by default) `auto_caption=True` so file
        preprocessing calls it automatically. Callers with their own
        use policy can read `get_vision_model_config()` directly.
        """
        try:
            cfg = get_vision_model_config()
        except Exception as exc:
            logger.debug(f"has_vision_model: config read failed: {exc}")
            return False
        return (
            bool(cfg.get("enabled"))
            and bool(cfg.get("endpoint"))
            and bool(cfg.get("model"))
        )

    def caption_image(
        self,
        name: str,
        media_type: str,
        data: bytes,
    ) -> str:
        """One-shot VL caption call for a single image.

        Used by `file_preprocessing.preprocess_file` when the user
        attaches an image while chatting with a text-only model. Sends
        a single `/chat/completions` request to the configured VL
        endpoint with the image as an `image_url` data URI and a
        concise "describe this" system prompt, and returns the plain
        text caption.

        Any failure (sidecar disabled, network error, malformed
        response, timeout) returns an empty string so
        `file_preprocessing` falls through to its placeholder path
        rather than aborting the whole attachment. Warnings are logged
        for diagnostic purposes.

        Args:
            name: Display name of the image (used only for log messages).
            media_type: MIME type of the image bytes (e.g. "image/png").
            data: Raw image bytes.

        Returns:
            A caption string on success, or "" on any failure.
        """
        cfg = get_vision_model_config()
        if not cfg.get("enabled") or not cfg.get("endpoint") or not cfg.get("model"):
            return ""

        endpoint = cfg["endpoint"].rstrip("/")
        # OpenAI-compatible clients expect the /chat/completions path;
        # strip any trailing /v1 the user may have included.
        if endpoint.endswith("/v1"):
            url = f"{endpoint}/chat/completions"
        else:
            url = f"{endpoint}/v1/chat/completions" if "/v1" not in endpoint else f"{endpoint}/chat/completions"

        # Build the request. We use the OpenAI SDK for consistency with
        # how ppxai talks to every other provider, rather than raw
        # httpx — the SDK handles retries, auth headers, and error
        # translation for us.
        try:
            from openai import OpenAI  # noqa: PLC0415
        except ImportError:
            logger.warning("caption_image: openai SDK not installed")
            return ""

        api_key = ""
        api_key_env = cfg.get("api_key_env") or ""
        if api_key_env:
            api_key = os.environ.get(api_key_env, "")
        # OpenAI SDK requires a non-empty api_key even for no-auth
        # endpoints; use a placeholder for local servers.
        if not api_key:
            api_key = "local-sidecar"

        b64 = base64.b64encode(data).decode("ascii")
        data_uri = f"data:{media_type};base64,{b64}"

        try:
            client = OpenAI(
                base_url=endpoint if endpoint.endswith("/v1") else f"{endpoint}/v1",
                api_key=api_key,
                timeout=float(cfg.get("timeout", 30)),
            )
            response = client.chat.completions.create(
                model=cfg["model"],
                max_tokens=int(cfg.get("max_tokens", 200)),
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": cfg.get("prompt", "Describe this image.")},
                            {"type": "image_url", "image_url": {"url": data_uri}},
                        ],
                    }
                ],
            )
        except Exception as exc:
            logger.warning(f"caption_image: VL call failed for {name}: {exc}")
            return ""

        try:
            caption = response.choices[0].message.content or ""
        except (AttributeError, IndexError):
            logger.warning(
                f"caption_image: unexpected response shape for {name}"
            )
            return ""

        caption = caption.strip()
        logger.debug(
            f"caption_image: {name} → {len(caption)} chars via "
            f"{cfg['endpoint']} ({cfg['model']})"
        )
        return caption

    def set_working_dir(self, path: str):
        """Set working directory for file path resolution.

        Args:
            path: Working directory path
        """
        # Check if directory actually changed to avoid duplicate events (v1.15.3)
        current_dir = self.get_working_dir()
        if current_dir and Path(current_dir).resolve() == Path(path).resolve():
            logger.debug(f"Working directory unchanged: {path}")
            return

        self.context_injector.set_working_dir(path)
        self.state.set("working_dir", path)
        self.session.set_working_dir(path)  # Also update session for persistence
        self._init_checkpoint_manager(path)

        # Emit working directory change event only if directory actually changed (v1.13.2, v1.15.3)
        # This event will be picked up by SSE stream and sent to clients
        self.enqueue_event(Event(
            type=EventType.WORKING_DIR_CHANGED,
            data={"path": path}
        ))

        # Reload bootstrap context for new working directory (v1.14.0)
        self.load_bootstrap_context()

    def get_working_dir(self) -> str | None:
        """Get current working directory.

        Returns:
            Working directory path or None if not set
        """
        return self.context_injector.working_dir

    def set_auto_inject(self, enabled: bool) -> bool:
        """Enable or disable automatic context injection.

        Args:
            enabled: Whether to enable auto-injection

        Returns:
            True (always succeeds)
        """
        self.auto_inject_context = enabled
        return True

    def get_auto_inject(self) -> bool:
        """Check if auto-injection is enabled.

        Returns:
            True if enabled
        """
        return self.auto_inject_context

    # === Bootstrap Context (v1.14.0) ===

    # === Bootstrap Context (delegated to bootstrap_ops.py) ===

    def load_bootstrap_context(self) -> bool:
        """Load bootstrap context from AGENTS.md/CLAUDE.md across all scopes."""
        return bootstrap_ops.load_bootstrap_context(self)

    def reload_bootstrap_context(self) -> bool:
        """Reload bootstrap context from disk."""
        return bootstrap_ops.load_bootstrap_context(self)

    def get_bootstrap_status(self) -> Dict[str, Any]:
        """Get status of loaded bootstrap context."""
        return bootstrap_ops.get_bootstrap_status(self)

    def get_bootstrap_prompt(self) -> str:
        """Get the bootstrap prompt for the current provider/model."""
        return bootstrap_ops.get_bootstrap_prompt(self)

    def get_active_hints(self) -> Dict[str, Any]:
        """Get detailed breakdown of active hints for current provider/model."""
        return bootstrap_ops.get_active_hints(self)

    # === Interrupt Handling ===

    def interrupt_stream(self) -> None:
        """Interrupt the current streaming response gracefully.

        This sets a flag that the chat() method will check during streaming.
        The stream will stop at the next chunk and return partial results.
        """
        self._interrupted = True
        self.state.set("cancel_requested", True)

    # === Provider Management ===

    def set_provider(self, provider_name: str) -> bool:
        """Switch to a different provider.

        Args:
            provider_name: Provider ID (e.g., 'perplexity', 'openai')

        Returns:
            True if provider was set successfully
        """
        if provider_name not in self.providers_config:
            return False

        api_key = self._get_api_key(provider_name)
        if not api_key:
            return False

        base_url = self._get_base_url(provider_name)
        provider_config = self.providers_config[provider_name]

        # Parse capabilities from config
        caps_dict = provider_config.get("capabilities", {})
        capabilities = ProviderCapabilities.from_dict(caps_dict)

        # Create provider instance with optional provider-specific options
        provider_options = provider_config.get("options", {})
        self.provider = create_provider(
            provider_name,
            api_key=api_key,
            base_url=base_url,
            models=provider_config.get("models", {}),
            capabilities=capabilities,
            **provider_options  # Pass provider-specific options (e.g., enable_grounding for Gemini)
        )

        if self.provider is None:
            # Fallback to generic OpenAI-compatible provider
            self.provider = OpenAICompatibleProvider(
                api_key=api_key,
                base_url=base_url,
                models=provider_config.get("models", {}),
                capabilities=capabilities,
                provider_id=provider_name  # For config lookup (generation_params, max_tokens)
            )

        self.provider_name = provider_name
        self.state.set("provider", provider_name)
        self.tool_manager.set_provider(provider_name)
        self.session.set_provider(provider_name)

        # Set default model for this provider (no context reset — provider switch
        # resets via the user's explicit set_model call, not this internal default).
        # Suppress hint logging here — the caller's set_model() will log the final model.
        default_model = provider_config.get("default_model")
        if default_model:
            self._suppress_hint_log = True
            self.set_model(default_model, reset_context=False)
            self._suppress_hint_log = False

        # Re-register tools when switching providers if tools are enabled
        # This ensures provider-aware tools (like web_search) are correctly filtered
        # for the new provider. Without this, switching from perplexity to custom
        # would keep web_search excluded even though custom providers need it.
        if self.tools_enabled:
            self.tool_manager.clear()
            register_all_builtin_tools(self.tool_manager, provider_name, engine=self)
            self.tool_manager.max_iterations = self._agent_config.get("max_tool_iterations", Default.MAX_TOOL_ITERATIONS)
            self.tool_manager.max_same_tool_calls = self._agent_config.get("max_same_tool_calls", Default.MAX_SAME_TOOL_CALLS)

        # Log hints transition for debugging (v1.14.0)
        if self._bootstrap_context:
            hints_info = self.get_active_hints()
            provider_count = len(hints_info["provider_hints"])
            model_count = len(hints_info["model_hints"])
            inherited = " (inherited local)" if hints_info["inherited_local"] else ""
            patterns = hints_info["matched_patterns"]
            logger.debug(
                f"Provider switch to '{provider_name}': "
                f"{provider_count} provider hints{inherited}, "
                f"{model_count} model hints (patterns: {patterns})"
            )

        return True

    def list_providers(self) -> List[ProviderInfo]:
        """List available providers with their status.

        Returns:
            List of ProviderInfo objects
        """
        providers = []
        for provider_id, config in self.providers_config.items():
            has_key = bool(self._get_api_key(provider_id))
            caps_dict = config.get("capabilities", {})

            providers.append(ProviderInfo(
                id=provider_id,
                name=config.get("name", provider_id),
                base_url=config.get("base_url", ""),
                api_key_env=config.get("api_key_env", ""),
                has_api_key=has_key,
                capabilities=ProviderCapabilities.from_dict(caps_dict),
                default_model=config.get("default_model", ""),
                coding_model=config.get("coding_model")
            ))

        return providers

    def get_current_provider(self) -> Optional[str]:
        """Get the current provider name.

        Returns:
            Provider name or None
        """
        return self.provider_name if self.provider else None

    # === Model Management ===

    def set_model(self, model_id: str, strict: bool = False, reset_context: bool = True) -> bool:
        """Set the current model.

        Args:
            model_id: Model ID to use
            strict: If True, reject models not in provider's configured list (v1.13.10)
            reset_context: If True, strip assistant/tool messages on model switch (v1.16.0)

        Returns:
            True if model was set successfully
        """
        if not self.provider:
            return False

        self.last_model_switch_reset = 0

        models = self.provider.list_models()
        model_exists = any(m.id == model_id for m in models)

        if model_exists:
            return self._apply_model_switch(model_id, reset_context)

        if strict:
            # Strict mode - reject unavailable models (used for session restore)
            return False

        # Allow setting model even if not in list (for flexibility with custom endpoints)
        return self._apply_model_switch(model_id, reset_context)

    def _apply_model_switch(self, model_id: str, reset_context: bool) -> bool:
        """Apply a confirmed model switch: update state, optionally reset context."""
        self.model = model_id
        self.state.set("model", model_id)
        self.session.set_model(model_id)
        if reset_context and self.session.messages:
            removed = self.session.reset_for_model_switch()
            self.last_model_switch_reset = removed
            if removed:
                logger.info(f"Reset context for model switch to {model_id}: removed {removed} messages")
        self._log_model_hints_transition(model_id)
        return True

    def _log_model_hints_transition(self, model_id: str) -> None:
        """Log hints transition when model changes (v1.14.0)."""
        if not self._bootstrap_context or getattr(self, '_suppress_hint_log', False):
            return

        hints_info = self.get_active_hints()
        model_count = len(hints_info["model_hints"])
        patterns = hints_info["matched_patterns"]

        if patterns:
            logger.debug(
                f"Model switch to '{model_id}': "
                f"{model_count} model hints (matched: {patterns})"
            )
        # No logging when no hints matched - reduces noise in logs
        # Available patterns can be seen via /context show command

    def list_models(self) -> List[ModelInfo]:
        """List available models for current provider.

        Returns:
            List of ModelInfo objects
        """
        if not self.provider:
            return []
        return self.provider.list_models()

    def get_current_model(self) -> Optional[str]:
        """Get the current model.

        Returns:
            Model ID or None
        """
        return self.model if self.model else None

    # === Tool Management ===

    def enable_tools(self) -> bool:
        """Enable tool support.

        Returns:
            True if tools were enabled
        """
        if not self.tools_enabled:
            # Register all built-in tools (including file editing tools v1.11.0)
            register_all_builtin_tools(self.tool_manager, self.provider_name, engine=self)
            # Apply configurable max_tool_iterations
            self.tool_manager.max_iterations = self._agent_config.get("max_tool_iterations", Default.MAX_TOOL_ITERATIONS)
            # Apply configurable loop detection threshold
            self.tool_manager.max_same_tool_calls = self._agent_config.get("max_same_tool_calls", Default.MAX_SAME_TOOL_CALLS)
            self.tools_enabled = True
            self.state.set("tools_enabled", True)
            self.session.tools_enabled = True  # Sync for session persistence
        return True

    def disable_tools(self) -> bool:
        """Disable tool support.

        Returns:
            True if tools were disabled
        """
        self.tools_enabled = False
        self.state.set("tools_enabled", False)
        self.session.tools_enabled = False  # Sync for session persistence
        self.tool_manager.clear()
        return True

    @property
    def agent_mode(self) -> bool:
        """Whether agent mode is enabled (v1.11.8)."""
        return self._agent_mode

    def enable_agent_mode(self) -> bool:
        """Enable agent mode for autonomous task execution (v1.11.8, v1.12.0).

        Agent mode automatically enables tools if not already enabled.
        In v1.12.0+, also enables checkpointing for atomic rollback.

        Returns:
            True if agent mode was enabled
        """
        self._agent_mode = True
        self.state.set("agent_mode", True)
        if not self.tools_enabled:
            self.enable_tools()

        # Emit notification about checkpoint status (v1.12.0)
        if self._checkpoint_manager:
            backend = self._checkpoint_manager.get_backend_name()
            if backend == "git":
                notification = (
                    "🔒 Agent Mode enabled with Git checkpoints\n"
                    "   • Changes will be auto-committed before each task\n"
                    "   • Use /undo to revert the last agent task atomically"
                )
            elif backend == "file":
                checkpoint_path = f"~/.ppxai/checkpoints/{self.session.session_name}"
                notification = (
                    f"🔒 Agent Mode enabled with file snapshots\n"
                    f"   • File snapshots saved to {checkpoint_path}\n"
                    "   • Use /undo to restore from last snapshot\n"
                    "   ⚠️  Tip: Initialize git repo for atomic commits"
                )
            else:
                notification = (
                    "⚠️  Agent Mode enabled WITHOUT checkpoints\n"
                    "   • File edits cannot be undone automatically\n"
                    "   • Initialize git repo for checkpoint support"
                )

            # Queue notification event
            self.enqueue_event(Event(
                type=EventType.STATUS,
                data=notification
            ))

        return True

    def disable_agent_mode(self) -> bool:
        """Disable agent mode (v1.11.8).

        Returns:
            True if agent mode was disabled
        """
        self._agent_mode = False
        self.state.set("agent_mode", False)
        return True

    def get_agent_config(self) -> dict:
        """Get agent configuration (v1.11.9).

        Returns:
            Dict with max_iterations, context_char_limit, min_task_words
        """
        return self._agent_config

    # === Checkpoint Management (delegated to checkpoint_ops.py) ===

    def create_checkpoint(self, description: str) -> Optional[str]:
        """Create a checkpoint before agent task execution."""
        return checkpoint_ops.create_checkpoint(self, description)

    def undo_last_checkpoint(self) -> bool:
        """Undo the last checkpoint (revert changes)."""
        return checkpoint_ops.undo_last_checkpoint(self)

    def commit_agent_changes(self, description: str) -> Optional[str]:
        """Commit changes made during agent task."""
        return checkpoint_ops.commit_agent_changes(self, description)

    def get_checkpoint_status(self) -> Dict[str, Any]:
        """Get checkpoint system status."""
        return checkpoint_ops.get_checkpoint_status(self)

    def list_checkpoints(self, limit: int = 10) -> List[Dict[str, str]]:
        """List recent checkpoints."""
        return checkpoint_ops.list_checkpoints(self, limit)

    def set_checkpoint_backend(self, backend: str) -> bool:
        """Set the checkpoint backend mode."""
        return checkpoint_ops.set_checkpoint_backend(self, backend)

    def clear_file_checkpoints(self, keep_last: int = 0) -> int:
        """Clear old file-based checkpoint snapshots."""
        return checkpoint_ops.clear_file_checkpoints(self, keep_last)

    # === Consent Management (delegated to consent_ops.py) ===

    async def request_file_edit_consent(self, file_path: str) -> bool:
        """Request user consent for editing a file."""
        return await consent_ops.request_file_edit_consent(self, file_path)

    def _classify_shell_command(self, command: str) -> str:
        """Classify shell command risk level."""
        return consent_ops.classify_command(self, command)

    async def request_shell_consent(self, command: str, working_dir: str = ".") -> bool:
        """Request user consent for shell command execution."""
        return await consent_ops.request_shell_consent(self, command, working_dir)

    def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools for current provider.

        Returns:
            List of tool info dicts
        """
        return self.tool_manager.list_tools()

    def set_tool_config(self, setting: str, value: Any) -> bool:
        """Configure tool settings.

        Args:
            setting: Setting name (e.g., 'max_iterations', 'verbose', 'auto_retry_empty', 'max_same_tool_calls')
            value: Setting value

        Returns:
            True if setting was applied
        """
        if setting == "max_iterations":
            self.tool_manager.max_iterations = int(value)
            return True
        elif setting == "verbose":
            # Store verbose setting for tool output display
            self._tools_verbose = value in [True, "on", "true", "1", "yes"]
            self.state.set("tools_verbose", self._tools_verbose)
            return True
        elif setting == "auto_retry_empty":
            # Auto-retry on empty responses (0=disabled)
            self.tool_manager.auto_retry_empty = int(value)
            return True
        elif setting == "max_same_tool_calls":
            # Loop detection threshold (0=disabled)
            self.tool_manager.max_same_tool_calls = int(value)
            return True
        return False

    def get_tools_status(self) -> Dict[str, Any]:
        """Get tools status.

        Returns:
            Dictionary with tools status
        """
        return {
            "enabled": self.tools_enabled,
            "tool_count": len(self.tool_manager.list_tools()) if self.tools_enabled else 0,
            "max_iterations": self.tool_manager.max_iterations,
            "auto_retry_empty": self.tool_manager.auto_retry_empty,
            "max_same_tool_calls": self.tool_manager.max_same_tool_calls,
            "verbose": self._tools_verbose  # Include verbose setting
        }

    # === ChatContext Interface ===

    @property
    def is_interrupted(self) -> bool:
        """Whether the current operation is interrupted (ChatContext interface)."""
        return self._interrupted

    def get_consent_events(self) -> List[Event]:
        """Get and clear queued consent events (ChatContext interface)."""
        return self.drain_events()

    def track_tool_usage(self, tool_name: str, usage: Dict[str, Any]) -> None:
        """Track tool usage for cost calculation (ChatContext interface)."""
        if not hasattr(self, '_current_tool_usage'):
            self._current_tool_usage = {}
        self._current_tool_usage[tool_name] = usage

    def commit_agent_changes_if_needed(self, message: str) -> Optional[str]:
        """Commit agent changes if in agent mode (ChatContext interface).

        Returns:
            Commit hash if changes were committed, None otherwise.
        """
        if self._agent_mode and self._checkpoint_manager and self._agent_edited_files:
            commit_hash = self.commit_agent_changes(message)
            if commit_hash:
                self._agent_edited_files.clear()
                return commit_hash
        return None

    # === Chat ===

    async def chat(
        self,
        message: MessageContent,
        stream: bool = True
    ) -> AsyncIterator[Event]:
        """Send a chat message, yielding events.

        Accepts either a plain text string (historical format) or a list of
        OpenAI-style multimodal content parts for messages with attachments:

            [{"type": "text", "text": "describe this"},
             {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]

        When `message` is a string, `@file` / `@git` / `@tree` context
        injection runs as before. For list content the caller is responsible
        for attachment preprocessing (see `/attach`), so auto-injection is
        skipped — we do not try to rewrite binary content parts.

        Events include:
        - STREAM_START: Chat started
        - STREAM_CHUNK: Partial response (for streaming)
        - CONTEXT_INJECTED: File content was auto-injected (string only)
        - TOOL_CALL / TOOL_RESULT / STREAM_END / ERROR

        Args:
            message: User message (string or multimodal content list)
            stream: Whether to stream the response

        Yields:
            Event objects
        """
        if not self.provider:
            yield Event(EventType.ERROR, "No provider configured")
            return

        if not self.model:
            yield Event(EventType.ERROR, "No model selected")
            return

        # Reset interrupt flag at start of chat
        self._interrupted = False
        self.state.update(is_streaming=True, cancel_requested=False)

        # Auto-inject file context if enabled — only applies to plain-text
        # messages. Multimodal list content carries explicit attachments from
        # the client; we leave it untouched.
        injected_contexts = []

        if self.auto_inject_context and isinstance(message, str):
            # Pass existing hashes to skip duplicate content at injection time
            existing_hashes = {c.get('hash') for c in self._injected_contexts if c.get('hash')}
            message, injected_contexts = self.context_injector.inject_context(
                message, skip_hashes=existing_hashes
            )

            # Emit events for each injected file and track them
            for ctx in injected_contexts:
                yield Event(EventType.CONTEXT_INJECTED, {
                    'source': ctx.source,
                    'language': ctx.language,
                    'truncated': ctx.truncated,
                    'size': ctx.size
                })
                # Track for /context command
                # Hash computed in inject_context, track here
                # Check if same source exists with different content
                existing_idx = next(
                    (i for i, c in enumerate(self._injected_contexts) if c['source'] == ctx.source),
                    None
                )
                injection_entry = {
                    'source': ctx.source,
                    'size': ctx.size,
                    'truncated': ctx.truncated,
                    'timestamp': datetime.now().isoformat(),
                    'hash': ctx.hash
                }
                if existing_idx is not None:
                    # Replace - same source, different content (e.g., @git updated)
                    self._injected_contexts[existing_idx] = injection_entry
                else:
                    self._injected_contexts.append(injection_entry)

        # Add message to history (with injected content if applicable)
        self.session.add_message(Message("user", message))

        try:
            if self.tools_enabled:
                async for event in self._chat_with_tools(stream):
                    yield event
            else:
                async for event in self._chat_simple(stream):
                    yield event
        finally:
            self.state.update(is_streaming=False, cancel_requested=False)

    async def _chat_simple(self, stream: bool) -> AsyncIterator[Event]:
        """Simple chat without tools.

        Delegates to chat.chat_simple() with self as ChatContext.
        """
        async for event in chat_simple(self, stream):
            yield event

    async def _chat_with_tools(self, stream: bool) -> AsyncIterator[Event]:
        """Chat with tool support.

        Delegates to chat.chat_with_tools() with self as ChatContext.
        """
        async for event in chat_with_tools(self, stream):
            yield event

    def _parse_tool_call(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse a tool call from model response.

        Delegates to tools/parser.py for the actual parsing logic.

        Args:
            text: Model response text

        Returns:
            Tool call dict with 'tool' and 'arguments' keys, or None
        """
        return parse_tool_call(text, self.tool_manager.get_tool)

    def chat_sync(self, message: str, stream: bool = False) -> str:
        """Synchronous chat that returns just the content.

        Args:
            message: User message
            stream: Whether to stream (ignored, always non-streaming)

        Returns:
            Assistant response content
        """
        result = ""

        async def run():
            nonlocal result
            async for event in self.chat(message, stream=False):
                if event.type == EventType.STREAM_END:
                    result = event.data
                elif event.type == EventType.ERROR:
                    result = f"Error: {event.data}"

        asyncio.run(run())
        return result

    # === Coding Tasks ===

    async def coding_task(
        self,
        content: str,
        task_type: str,
        language: Optional[str] = None,
        filename: Optional[str] = None,
        stream: bool = True
    ) -> AsyncIterator[Event]:
        """Execute a coding task (explain, test, docs, debug, implement, generate).

        Args:
            content: Code or content to process
            task_type: Task type (explain, test, docs, debug, implement, generate)
            language: Programming language
            filename: Source filename
            stream: Whether to stream the response

        Yields:
            Event objects
        """
        if task_type not in CODING_PROMPTS:
            yield Event(EventType.ERROR, f"Unknown task type: {task_type}")
            return

        # Build the prompt
        system_prompt = CODING_PROMPTS[task_type]

        # Build user message based on task type
        if task_type == "explain":
            user_message = f"Explain this code:\n\n```{language or ''}\n{content}\n```"
        elif task_type == "test":
            user_message = f"Generate unit tests for this code:\n\n```{language or ''}\n{content}\n```"
        elif task_type == "docs":
            user_message = f"Generate documentation for this code:\n\n```{language or ''}\n{content}\n```"
        elif task_type == "debug":
            user_message = f"Debug this error:\n\n{content}"
        elif task_type == "implement":
            user_message = f"Implement the following in {language or 'Python'}:\n\n{content}"
        elif task_type == "generate":
            user_message = f"Generate code for the following in {language or 'Python'}:\n\n{content}"
        else:
            user_message = content

        if filename:
            user_message = f"File: {filename}\n\n{user_message}"

        # Combine with system prompt
        full_message = f"{system_prompt}\n\n{user_message}"

        # Use regular chat to process
        async for event in self.chat(full_message, stream=stream):
            yield event

    # === Session Management ===

    # === Session & Export (delegated to session_ops.py) ===

    def restore_session(self, name: str) -> dict:
        """Load session file and restore all engine state."""
        return session_ops.restore_session(self, name)

    def get_history(self) -> List[Dict[str, str]]:
        """Get conversation history as dicts."""
        return session_ops.get_history(self)

    def export_conversation(self, filename: Optional[str] = None) -> Path:
        """Export conversation to markdown."""
        return session_ops.export_conversation(self, filename)

    def export_answer(self, filename: Optional[str] = None) -> Path:
        """Export last assistant answer to markdown."""
        return session_ops.export_answer(self, filename)

    def get_usage(self) -> Dict[str, Any]:
        """Get usage statistics."""
        return session_ops.get_usage(self)

    # === Status & Context (delegated to session_ops.py) ===

    def get_status(self) -> Dict[str, Any]:
        """Get current engine status."""
        return session_ops.get_status(self)

    def get_context_info(self) -> Dict[str, Any]:
        """Get context usage information for /context command."""
        return session_ops.get_context_info(self)

    def clear_injected_contexts(self) -> int:
        """Clear tracked injected contexts and remove from message history."""
        return session_ops.clear_injected_contexts(self)

    # === Cleanup ===

    async def cleanup(self):
        """Clean up resources."""
        await self.tool_manager.cleanup()

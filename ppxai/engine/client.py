"""
Engine Client - Main facade for the ppxai engine.

This is the primary interface for all frontends (TUI, VSCode, Web).
It has no UI dependencies and communicates via events.
"""

import asyncio
import hashlib
import json
import os
from datetime import datetime
from typing import List, AsyncIterator, Optional, Dict, Any
from pathlib import Path

from .types import (
    Message, Event, EventType, UsageStats,
    ProviderInfo, ModelInfo, SessionInfo, ProviderCapabilities
)
from ..prompts import CODING_PROMPTS
from .providers import create_provider, list_registered_providers
from .providers.base import BaseProvider
from .tools.manager import ToolManager
from .tools.builtin import register_all_builtin_tools
from .tools.parser import parse_tool_call
from .chat import chat_simple, chat_with_tools
from .providers.openai_compat import OpenAICompatibleProvider
from .session import SessionManager
from .context import ContextInjector, ScopedBootstrapSource
from .bootstrap import BootstrapContext
from ..checkpoint import CheckpointManager
from ..config import (
    calculate_cost,
    get_api_key,
    get_base_url,
    get_default_model,
    get_default_provider,
    get_system_prompt,
    get_system_prompt_mode,
    get_shell_config,
    get_agent_config,
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

        # Canonical observable state — single source of truth shared across
        # all clients. Mutators below keep this in sync with instance fields.
        self.state = AppState()

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

        # Event emitter for consent requests (Phase 1C: HTTP/SSE support)
        # This allows emitting events from within consent callback
        self._consent_event_queue: List[Event] = []

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
        self._consent_event_queue.append(Event(
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
            self._consent_event_queue.append(Event(
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
        events = list(self._consent_event_queue)
        self._consent_event_queue.clear()
        return events

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
        message: str,
        stream: bool = True
    ) -> AsyncIterator[Event]:
        """Send a chat message, yielding events.

        Events include:
        - STREAM_START: Chat started
        - STREAM_CHUNK: Partial response (for streaming)
        - CONTEXT_INJECTED: File content was auto-injected
        - TOOL_CALL: Tool being called
        - TOOL_RESULT: Tool result
        - STREAM_END: Final response
        - ERROR: Error occurred

        Args:
            message: User message
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

        # Auto-inject file context if enabled
        injected_contexts = []

        if self.auto_inject_context:
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

        # Add message to history (with injected content)
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

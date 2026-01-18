"""
Engine Client - Main facade for the ppxai engine.

This is the primary interface for all frontends (TUI, VSCode, Web).
It has no UI dependencies and communicates via events.
"""

import asyncio
import hashlib
import json
import re
from dataclasses import asdict
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
from .session import SessionManager
from .context import ContextInjector
from ..checkpoint import CheckpointManager, FileCheckpointBackend
from ..config import (
    calculate_cost,
    get_api_key,
    get_base_url,
    get_default_model,
    get_default_provider,
    get_system_prompt,
    get_system_prompt_mode,
    get_model_context_limit,
    get_shell_config,
    get_agent_config,
    PROVIDERS,
    EXPORTS_DIR,
)
from ..common.logger import get_logger
from ..common.consent import classify_shell_command
from ..constants import ConsentMode, ConsentResponse, ShellRiskLevel

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

        # Context injection for automatic file content inclusion
        self.context_injector = ContextInjector()
        self.auto_inject_context: bool = True  # Enabled by default

        # Track injected contexts for /context command
        self._injected_contexts: List[Dict[str, Any]] = []

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

        # Event emitter for consent requests (Phase 1C: HTTP/SSE support)
        # This allows emitting events from within consent callback
        self._consent_event_queue: List[Event] = []

        # Load configuration (including shell command patterns)
        self._load_config()

        # Initialize checkpoint manager with default working directory
        # This ensures TUI has checkpoints available without explicit set_working_dir call
        self._init_checkpoint_manager(self.context_injector.working_dir)

    def _load_config(self):
        """Load configuration from ppxai-config.json and .env."""
        # Store references to config functions for provider management
        self._providers_config = PROVIDERS
        self._get_api_key = get_api_key
        self._get_base_url = get_base_url
        self._get_default_model = get_default_model
        self._default_provider = get_default_provider()

        # Use centralized config functions with defaults from config/defaults.py
        self._shell_config = get_shell_config()
        self._agent_config = get_agent_config()

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
        self.context_injector.set_working_dir(path)
        self.session.set_working_dir(path)  # Also update session for persistence
        self._init_checkpoint_manager(path)

        # Initialize checkpoint manager for this working directory (v1.12.0)
        checkpoint_backend = self.config.get("tools", {}).get("agent", {}).get("checkpoint_backend", "auto")
        session_id = self.session.session_name or "default"
        self._checkpoint_manager = CheckpointManager(
            working_dir=path,
            session_id=session_id,
            backend=checkpoint_backend
        )

        # Emit working directory change event (v1.13.2)
        # This event will be picked up by SSE stream and sent to clients
        self._consent_event_queue.append(Event(
            type=EventType.WORKING_DIR_CHANGED,
            data={"path": path}
        ))

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

    # === Interrupt Handling ===

    def interrupt_stream(self) -> None:
        """Interrupt the current streaming response gracefully.

        This sets a flag that the chat() method will check during streaming.
        The stream will stop at the next chunk and return partial results.
        """
        self._interrupted = True

    # === Provider Management ===

    def set_provider(self, provider_name: str) -> bool:
        """Switch to a different provider.

        Args:
            provider_name: Provider ID (e.g., 'perplexity', 'openai')

        Returns:
            True if provider was set successfully
        """
        if provider_name not in self._providers_config:
            return False

        api_key = self._get_api_key(provider_name)
        if not api_key:
            return False

        base_url = self._get_base_url(provider_name)
        provider_config = self._providers_config[provider_name]

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
            from .providers.openai_compat import OpenAICompatibleProvider
            self.provider = OpenAICompatibleProvider(
                api_key=api_key,
                base_url=base_url,
                models=provider_config.get("models", {}),
                capabilities=capabilities
            )

        self.provider_name = provider_name
        self.tool_manager.set_provider(provider_name)
        self.session.set_provider(provider_name)

        # Set default model for this provider
        default_model = provider_config.get("default_model")
        if default_model:
            self.set_model(default_model)

        # Re-register tools when switching providers if tools are enabled
        # This ensures provider-aware tools (like web_search) are correctly filtered
        # for the new provider. Without this, switching from perplexity to custom
        # would keep web_search excluded even though custom providers need it.
        if self.tools_enabled:
            self.tool_manager.clear()
            register_all_builtin_tools(self.tool_manager, provider_name, engine=self)
            self.tool_manager.max_iterations = self._agent_config.get("max_tool_iterations", 15)
            self.tool_manager.max_same_tool_calls = self._agent_config.get("max_same_tool_calls", 3)

        return True

    def list_providers(self) -> List[ProviderInfo]:
        """List available providers with their status.

        Returns:
            List of ProviderInfo objects
        """
        providers = []
        for provider_id, config in self._providers_config.items():
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

    def set_model(self, model_id: str, strict: bool = False) -> bool:
        """Set the current model.

        Args:
            model_id: Model ID to use
            strict: If True, reject models not in provider's configured list (v1.13.10)

        Returns:
            True if model was set successfully
        """
        if not self.provider:
            return False

        models = self.provider.list_models()
        model_exists = any(m.id == model_id for m in models)

        if model_exists:
            self.model = model_id
            self.session.set_model(model_id)
            return True

        if strict:
            # Strict mode - reject unavailable models (used for session restore)
            return False

        # Allow setting model even if not in list (for flexibility with custom endpoints)
        self.model = model_id
        self.session.set_model(model_id)
        return True

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
            self.tool_manager.max_iterations = self._agent_config.get("max_tool_iterations", 15)
            # Apply configurable loop detection threshold
            self.tool_manager.max_same_tool_calls = self._agent_config.get("max_same_tool_calls", 3)
            self.tools_enabled = True
            self.session.tools_enabled = True  # Sync for session persistence
        return True

    def disable_tools(self) -> bool:
        """Disable tool support.

        Returns:
            True if tools were disabled
        """
        self.tools_enabled = False
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
        return True

    def get_agent_config(self) -> dict:
        """Get agent configuration (v1.11.9).

        Returns:
            Dict with max_iterations, context_char_limit, min_task_words
        """
        return self._agent_config

    # === Checkpoint Management (v1.12.0) ===

    def create_checkpoint(self, description: str) -> Optional[str]:
        """Create a checkpoint before agent task execution (v1.12.0).

        Args:
            description: Description of the task (for commit message)

        Returns:
            Checkpoint ID if successful, None otherwise
        """
        if not self._checkpoint_manager or not self._agent_mode:
            return None

        checkpoint_id = self._checkpoint_manager.create_checkpoint(description)
        if checkpoint_id:
            self._last_checkpoint_id = checkpoint_id

            # Emit notification
            backend = self._checkpoint_manager.get_backend_name()
            if backend == "git":
                msg = f"✓ Checkpoint created: {checkpoint_id[:8]} ({description})"
            else:
                msg = f"✓ Snapshot saved: {checkpoint_id} ({description})"

            self._consent_event_queue.append(Event(
                type=EventType.STATUS,
                data=msg
            ))

        return checkpoint_id

    def undo_last_checkpoint(self) -> bool:
        """Undo the last checkpoint (revert changes) (v1.12.0).

        Returns:
            True if undo was successful, False otherwise
        """
        if not self._checkpoint_manager or not self._last_checkpoint_id:
            return False

        success = self._checkpoint_manager.restore_checkpoint(self._last_checkpoint_id)
        if success:
            backend = self._checkpoint_manager.get_backend_name()
            checkpoint_id = self._last_checkpoint_id

            if backend == "git":
                msg = f"✓ Changes reverted using git revert (checkpoint: {checkpoint_id[:8]})"
            else:
                msg = f"✓ Files restored from snapshot: {checkpoint_id}"

            self._consent_event_queue.append(Event(
                type=EventType.STATUS,
                data=msg
            ))

            self._last_checkpoint_id = None
            return True

        return False

    def commit_agent_changes(self, description: str) -> Optional[str]:
        """Commit changes made during agent task (v1.12.0).

        This commits any uncommitted changes after a successful agent task,
        allowing undo to work via git revert.

        Args:
            description: Description of the changes (for commit message)

        Returns:
            Commit hash if successful, None otherwise
        """
        if not self._checkpoint_manager or not self._agent_mode:
            return None

        # Only git backend supports this
        if self._checkpoint_manager.get_backend_name() != "git":
            return None

        try:
            import subprocess
            working_dir = self.context_injector.working_dir

            # Check if there are changes to commit
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=working_dir,
                capture_output=True,
                text=True
            )
            if not result.stdout.strip():
                return None  # No changes to commit

            # Stage all changes
            subprocess.run(
                ["git", "add", "-A"],
                cwd=working_dir,
                check=True
            )

            # Commit with descriptive message
            commit_msg = f"ppxai agent: {description}"
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=working_dir,
                check=True
            )

            # Get the commit hash
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=working_dir,
                capture_output=True,
                text=True,
                check=True
            )
            commit_hash = result.stdout.strip()

            # Update last checkpoint to the new commit (so undo reverts this)
            self._last_checkpoint_id = commit_hash

            return commit_hash
        except subprocess.CalledProcessError:
            return None

    def get_checkpoint_status(self) -> Dict[str, Any]:
        """Get checkpoint system status (v1.12.0, updated v1.12.1).

        Returns:
            Dictionary with checkpoint status information including validity.
        """
        if not self._checkpoint_manager:
            return {
                "enabled": False,
                "backend": "none",
                "last_checkpoint": None,
                "is_valid": False,
                "validity_reason": "Checkpointing is disabled",
            }

        # Check if checkpoint is still valid (not stale)
        is_valid = False
        validity_reason = "No checkpoint available"
        checkpoint_id = self._last_checkpoint_id  # Capture before potential clearing

        if checkpoint_id:
            is_valid, validity_reason = self._checkpoint_manager.is_checkpoint_valid(
                checkpoint_id
            )

            # Auto-invalidate stale checkpoints (clear internal reference)
            # But keep returning the ID so users can manually revert if needed
            if not is_valid:
                self._last_checkpoint_id = None

        return {
            "enabled": self._checkpoint_manager.is_enabled(),
            "backend": self._checkpoint_manager.get_backend_name(),
            "last_checkpoint": checkpoint_id,  # Return even if stale
            "is_valid": is_valid,
            "validity_reason": validity_reason,
            "status_description": self._checkpoint_manager.get_status_description(),
        }

    def list_checkpoints(self, limit: int = 10) -> List[Dict[str, str]]:
        """List recent checkpoints (v1.12.4).

        Returns:
            List of checkpoint info dicts with keys: id, description, timestamp
        """
        if not self._checkpoint_manager:
            return []

        checkpoints = self._checkpoint_manager.list_checkpoints()
        return [
            {"id": cp[0], "description": cp[1], "timestamp": cp[2]}
            for cp in checkpoints[:limit]
        ]

    def set_checkpoint_backend(self, backend: str) -> bool:
        """Set the checkpoint backend mode (v1.12.4).

        Args:
            backend: One of 'git', 'file', 'auto', 'none'

        Returns:
            True if backend was set successfully
        """
        valid_backends = ('git', 'file', 'auto', 'none')
        if backend not in valid_backends:
            return False

        # Reinitialize checkpoint manager with new backend
        working_dir = str(Path.cwd())
        session_id = self.session.session_name if self.session else "default"

        self._checkpoint_manager = CheckpointManager(
            working_dir=working_dir,
            session_id=session_id,
            backend=backend
        )
        return True

    def clear_file_checkpoints(self, keep_last: int = 0) -> int:
        """Clear old file-based checkpoint snapshots (v1.12.4).

        Args:
            keep_last: Number of recent checkpoints to keep (0 = clear all)

        Returns:
            Number of checkpoints removed
        """
        if not self._checkpoint_manager:
            return 0

        if isinstance(self._checkpoint_manager.backend, FileCheckpointBackend):
            before_count = len(self._checkpoint_manager.list_checkpoints())
            self._checkpoint_manager.backend.cleanup_old_checkpoints(keep_last=keep_last)
            after_count = len(self._checkpoint_manager.list_checkpoints())
            return before_count - after_count

        return 0

    async def request_file_edit_consent(self, file_path: str) -> bool:
        """Request user consent for editing a file (v1.11.0).

        This method manages the consent flow:
        1. Check if consent mode is "always" or "never"
        2. Check if file already allowed
        3. If needed, call consent_callback to ask user
        4. Update session state based on response
        5. v1.12.0: Create checkpoint before first file edit in agent mode

        Args:
            file_path: Path to file that needs editing

        Returns:
            True if edit is allowed, False otherwise
        """
        from pathlib import Path

        path = Path(file_path).resolve()

        # Create checkpoint before first file edit in agent mode
        # Only create once per chat turn (when no files have been edited yet)
        # create_checkpoint() already emits STATUS event - don't duplicate
        if self._agent_mode and self._checkpoint_manager and not self.session.allowed_files:
            # Extract filename for checkpoint description
            filename = path.name
            self.create_checkpoint(f"Before editing {filename}")

        # Check global consent mode
        if self.session.edit_consent_mode == ConsentMode.ALWAYS:
            return True
        if self.session.edit_consent_mode == ConsentMode.NEVER:
            return False

        # Check if already consented for this file
        if path in self.session.allowed_files:
            return True

        # If no callback, default to allow (backward compatible)
        if self.consent_callback is None:
            return True

        # Request consent from user via callback
        try:
            # Emit consent request event (Phase 1C: for HTTP/SSE support)
            consent_event = Event(
                type=EventType.CONSENT_REQUEST,
                data={"file_path": str(path)},
                metadata={"file_path": str(path)}
            )
            self._consent_event_queue.append(consent_event)

            # Call consent callback and wait for response
            approved, response = await self.consent_callback(str(path))

            if response == ConsentResponse.YES:
                self.session.allowed_files.add(path)
                return True
            elif response == ConsentResponse.ALWAYS:
                self.session.edit_consent_mode = ConsentMode.ALWAYS
                return True
            elif response == ConsentResponse.NEVER:
                self.session.edit_consent_mode = ConsentMode.NEVER
                return False
            else:  # "n" or anything else
                return False

        except Exception as e:
            # If consent callback fails, deny for safety
            print(f"Consent callback error: {e}")
            return False

    def _classify_shell_command(self, command: str) -> str:
        """Classify shell command risk level.

        Delegates to common.consent.classify_shell_command().

        Args:
            command: Shell command to classify

        Returns:
            Risk level: ShellRiskLevel value (NEVER, DANGEROUS, or SAFE)
        """
        return classify_shell_command(command, self._shell_config)

    async def request_shell_consent(self, command: str, working_dir: str = ".") -> bool:
        """Request user consent for shell command execution (v1.11.2).

        This method manages the shell consent flow:
        1. Classify command risk level (never/dangerous/safe)
        2. Block "never" commands immediately
        3. Allow "safe" commands without consent
        4. Request consent for "dangerous" commands
        5. Check session state (always/never modes)

        Args:
            command: Shell command to execute
            working_dir: Working directory for the command

        Returns:
            True if execution is allowed, False otherwise
        """
        # Classify command risk
        risk_level = self._classify_shell_command(command)

        # Debug logging
        logger.debug(f"Shell consent: command='{command[:50]}...' risk={risk_level} callback={self.shell_consent_callback is not None}")

        # Never-allow commands are always blocked
        if risk_level == ShellRiskLevel.NEVER:
            return False

        # Safe commands are always allowed (no consent needed)
        if risk_level == ShellRiskLevel.SAFE:
            return True

        # Check global shell consent mode
        if self.session.shell_consent_mode == ConsentMode.ALWAYS:
            return True
        if self.session.shell_consent_mode == ConsentMode.NEVER:
            return False

        # Check if already consented for this specific command
        if command in self.session.allowed_commands:
            return True

        # If no callback, default to deny (fail-safe)
        if self.shell_consent_callback is None:
            return False

        # Request consent from user via callback
        try:
            # Debug logging
            logger.debug(f"Requesting shell consent for: {command[:50]}...")

            # Emit consent request event (for HTTP/SSE support)
            consent_event = Event(
                type=EventType.CONSENT_REQUEST,
                data={
                    "command": command,
                    "working_dir": working_dir,
                    "risk_level": risk_level,
                    "type": "shell"
                },
                metadata={"command": command, "type": "shell"}
            )
            self._consent_event_queue.append(consent_event)

            # Call shell consent callback and wait for response
            approved, response = await self.shell_consent_callback(command, working_dir, risk_level)

            # Debug logging
            logger.debug(f"Shell consent response: approved={approved} response={response}")

            if response == ConsentResponse.YES:
                self.session.allowed_commands.add(command)
                return True
            elif response == ConsentResponse.ALWAYS:
                self.session.shell_consent_mode = ConsentMode.ALWAYS
                return True
            elif response == ConsentResponse.NEVER:
                self.session.shell_consent_mode = ConsentMode.NEVER
                return False
            else:  # "n" or anything else
                return False

        except Exception as e:
            # If consent callback fails, deny for safety
            print(f"Shell consent callback error: {e}")
            return False

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

        if self.tools_enabled:
            async for event in self._chat_with_tools(stream):
                yield event
        else:
            async for event in self._chat_simple(stream):
                yield event

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
        import asyncio

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
    # Note: For session operations, use engine.session directly:
    # - engine.session.save(name)
    # - engine.session.load(name)
    # - engine.session.list_sessions()
    # - engine.session.clear()

    def get_history(self) -> List[Dict[str, str]]:
        """Get conversation history as dicts.

        Returns:
            List of message dicts
        """
        return self.session.get_messages_as_dicts()

    def export_conversation(self, filename: Optional[str] = None) -> Path:
        """Export conversation to markdown.

        Args:
            filename: Optional filename

        Returns:
            Path to exported file
        """
        return self.session.export(filename)

    def export_answer(self, filename: Optional[str] = None) -> Path:
        """Export last assistant answer to markdown.

        Args:
            filename: Optional filename

        Returns:
            Path to exported file

        Raises:
            ValueError: If no assistant message found
        """
        # Find last assistant message
        last_assistant_msg = None
        for msg in reversed(self.session.messages):
            if msg.role == 'assistant':
                last_assistant_msg = msg.content
                break

        if not last_assistant_msg:
            raise ValueError("No assistant response to export yet")

        # Generate filename with timestamp
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"answer_{timestamp}.md"

        if not filename.endswith('.md'):
            filename += '.md'

        filepath = EXPORTS_DIR / filename

        # Write content
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(last_assistant_msg)

        return filepath

    def get_usage(self) -> Dict[str, Any]:
        """Get usage statistics.

        Returns:
            Usage stats dict
        """
        return self.session.get_usage()

    # === Status ===

    def get_status(self) -> Dict[str, Any]:
        """Get current engine status.

        Returns:
            Status dictionary
        """
        return {
            "provider": self.provider_name,
            "model": self.model,
            "tools_enabled": self.tools_enabled,
            "tool_count": len(self.tool_manager.list_tools()) if self.tools_enabled else 0,
            "auto_inject_context": self.auto_inject_context,
            "has_api_key": self.provider is not None,
            "message_count": len(self.session.messages)
        }

    # === Context Management (v1.13.9) ===

    def get_context_info(self) -> Dict[str, Any]:
        """Get context usage information for /context command.

        Returns:
            Dict with context usage info:
            - estimated_tokens: Estimated total tokens
            - context_limit: Model context limit
            - usage_percent: Usage percentage
            - injected_contexts: List of injected @file/@git/@tree
            - message_count: Number of messages in history
            - total_chars: Total characters in history
        """
        # Calculate total characters in message history
        total_chars = sum(len(m.content) for m in self.session.messages)

        # Estimate tokens (~4 chars per token)
        estimated_tokens = total_chars // 4

        # Get context limit for current model
        context_limit = get_model_context_limit(self.provider_name, self.model)

        usage_percent = (estimated_tokens / context_limit) * 100 if context_limit > 0 else 0

        # Calculate injected context size
        injected_size = sum(ctx.get('size', 0) for ctx in self._injected_contexts)
        injected_tokens = injected_size // 4

        return {
            "estimated_tokens": estimated_tokens,
            "context_limit": context_limit,
            "usage_percent": usage_percent,
            "injected_contexts": self._injected_contexts.copy(),
            "injected_tokens": injected_tokens,
            "message_count": len(self.session.messages),
            "total_chars": total_chars,
            "provider": self.provider_name,
            "model": self.model
        }

    def clear_injected_contexts(self) -> int:
        """Clear tracked injected contexts and remove from message history.

        This removes the injected file content from messages but keeps
        the conversation flow intact.

        Returns:
            Number of injections removed
        """
        removed_count = len(self._injected_contexts)

        if removed_count == 0:
            return 0

        # Pattern to match injected context blocks
        import re
        injection_pattern = re.compile(
            r'\n---\n\*\*`@[^`]+`\*\*[^\n]*:\n```[^\n]*\n.*?```\n',
            re.DOTALL
        )

        # Remove injected blocks from all user messages
        for msg in self.session.messages:
            if msg.role == "user":
                msg.content = injection_pattern.sub('', msg.content)

        # Clear the tracking list
        self._injected_contexts.clear()

        return removed_count

    # === Cleanup ===

    async def cleanup(self):
        """Clean up resources."""
        await self.tool_manager.cleanup()

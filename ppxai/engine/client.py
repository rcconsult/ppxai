"""
Engine Client - Main facade for the ppxai engine.

This is the primary interface for all frontends (TUI, VSCode, Web).
It has no UI dependencies and communicates via events.
"""

import asyncio
import json
import re
from dataclasses import asdict
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
from .session import SessionManager
from .context import ContextInjector
from ..checkpoint import CheckpointManager
from ..config import calculate_cost


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

        # v1.12.0: Verbose mode for tool output display (matches TUI behavior)
        self._tools_verbose: bool = False

        # Event emitter for consent requests (Phase 1C: HTTP/SSE support)
        # This allows emitting events from within consent callback
        self._consent_event_queue: List[Event] = []

        # Load configuration (including shell command patterns)
        self._load_config()

        # v1.12.0: Initialize checkpoint manager with default working directory
        # This ensures TUI has checkpoints available without explicit set_working_dir call
        self._init_checkpoint_manager(self.context_injector.working_dir)

    def _load_config(self):
        """Load configuration from ppxai-config.json and .env."""
        # Import from existing config module to reuse configuration loading
        try:
            from ..config import (
                PROVIDERS,
                get_api_key,
                get_base_url,
                get_default_model,
                MODEL_PROVIDER,
                load_config,
            )
            self._providers_config = PROVIDERS
            self._get_api_key = get_api_key
            self._get_base_url = get_base_url
            self._get_default_model = get_default_model
            self._default_provider = MODEL_PROVIDER

            # Load shell tool configuration (v1.11.2)
            # v1.11.9: Add default dangerous patterns for safety
            full_config = load_config()
            user_shell_config = full_config.get("tools", {}).get("shell", {})

            # Built-in defaults merged with user config
            default_dangerous = [
                r"^rm\s+", r"^mv\s+", r"^dd\s+", r"^chmod\s+", r"^chown\s+",
                r"^sudo\s+", r"^curl.*\|.*bash", r"^wget.*\|.*bash",
                r">\s*/dev/", r"^kill\s+", r"^pkill\s+", r"^killall\s+"
            ]
            default_never = [
                r"rm\s+-rf\s+/", r"dd\s+.*of=/dev/", r":\(\)\{\s*:\|:&\s*\};:",
                r"mkfs\.", r"^\s*>\s*/dev/sda"
            ]
            default_allowed = [
                r"^ls\s+", r"^cat\s+(?!.*[><])", r"^grep\s+",
                r"^echo\s+(?!.*>)", r"^pwd$", r"^which\s+",
                r"^whoami$", r"^date$", r"^uname\s+"
            ]

            self._shell_config = {
                "dangerous_commands": user_shell_config.get("dangerous_commands", default_dangerous),
                "never_allow": user_shell_config.get("never_allow", default_never),
                "allowed_commands": user_shell_config.get("allowed_commands", default_allowed),
            }

            # v1.11.9: Load agent configuration
            # v1.12.0: Added max_tool_iterations for inner tool loop
            agent_config = full_config.get("tools", {}).get("agent", {})
            self._agent_config = {
                "max_iterations": agent_config.get("max_iterations", 10),
                "max_tool_iterations": agent_config.get("max_tool_iterations", 15),
                "context_char_limit": agent_config.get("context_char_limit", 2000),
                "min_task_words": agent_config.get("min_task_words", 3),
            }
        except ImportError:
            # Fallback if old config not available
            self._providers_config = {}
            self._get_api_key = lambda p: None
            self._get_base_url = lambda p: None
            self._get_default_model = lambda: None
            self._default_provider = "perplexity"
            # v1.11.9: Built-in shell safety defaults
            self._shell_config = {
                "dangerous_commands": [
                    r"^rm\s+", r"^mv\s+", r"^dd\s+", r"^chmod\s+", r"^chown\s+",
                    r"^sudo\s+", r"^curl.*\|.*bash", r"^wget.*\|.*bash",
                    r">\s*/dev/", r"^kill\s+", r"^pkill\s+", r"^killall\s+"
                ],
                "never_allow": [
                    r"rm\s+-rf\s+/", r"dd\s+.*of=/dev/", r":\(\)\{\s*:\|:&\s*\};:",
                    r"mkfs\.", r"^\s*>\s*/dev/sda"
                ],
                "allowed_commands": [
                    r"^ls\s+", r"^cat\s+(?!.*[><])", r"^grep\s+",
                    r"^echo\s+(?!.*>)", r"^pwd$", r"^which\s+",
                    r"^whoami$", r"^date$", r"^uname\s+"
                ],
            }
            # v1.11.9: Default agent configuration
            # v1.12.0: Added max_tool_iterations
            self._agent_config = {
                "max_iterations": 10,
                "max_tool_iterations": 15,
                "context_char_limit": 2000,
                "min_task_words": 3,
            }

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
        except Exception:
            pass  # Ignore errors - checkpoint ID will be None until first checkpoint is created

    def set_working_dir(self, path: str):
        """Set working directory for file path resolution.

        Args:
            path: Working directory path
        """
        self.context_injector.set_working_dir(path)
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

        # Create provider instance
        self.provider = create_provider(
            provider_name,
            api_key=api_key,
            base_url=base_url,
            models=provider_config.get("models", {}),
            capabilities=capabilities
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

        # v1.13.2: Re-register tools when switching providers if tools are enabled
        # This ensures provider-aware tools (like web_search) are correctly filtered
        # for the new provider. Without this, switching from perplexity to custom
        # would keep web_search excluded even though custom providers need it.
        if self.tools_enabled:
            self.tool_manager.clear()
            register_all_builtin_tools(self.tool_manager, provider_name, engine=self)
            self.tool_manager.max_iterations = self._agent_config.get("max_tool_iterations", 15)

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

    def set_model(self, model_id: str) -> bool:
        """Set the current model.

        Args:
            model_id: Model ID to use

        Returns:
            True if model was set successfully
        """
        if not self.provider:
            return False

        models = self.provider.list_models()
        if any(m.id == model_id for m in models):
            self.model = model_id
            self.session.set_model(model_id)
            return True

        # Allow setting model even if not in list (for flexibility)
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
            # v1.12.0: Apply configurable max_tool_iterations
            self.tool_manager.max_iterations = self._agent_config.get("max_tool_iterations", 15)
            self.tools_enabled = True
        return True

    def disable_tools(self) -> bool:
        """Disable tool support.

        Returns:
            True if tools were disabled
        """
        self.tools_enabled = False
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

        # v1.12.1: Check if checkpoint is still valid (not stale)
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

        from ..checkpoint import FileCheckpointBackend

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

        # v1.12.0: Create checkpoint before first file edit in agent mode
        # Only create once per chat turn (when no files have been edited yet)
        if self._agent_mode and self._checkpoint_manager and not self.session.allowed_files:
            # Extract filename for checkpoint description
            filename = path.name
            checkpoint_id = self.create_checkpoint(f"Before editing {filename}")
            if checkpoint_id:
                # Emit checkpoint notification via STATUS event
                self._consent_event_queue.append(Event(
                    type=EventType.STATUS,
                    data=f"✓ Checkpoint created: {checkpoint_id[:8]} (Before editing {filename})"
                ))

        # Check global consent mode
        if self.session.edit_consent_mode == "always":
            return True
        if self.session.edit_consent_mode == "never":
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

            if response == "y":
                self.session.allowed_files.add(path)
                return True
            elif response == "always":
                self.session.edit_consent_mode = "always"
                return True
            elif response == "never":
                self.session.edit_consent_mode = "never"
                return False
            else:  # "n" or anything else
                return False

        except Exception as e:
            # If consent callback fails, deny for safety
            print(f"Consent callback error: {e}")
            return False

    def _classify_shell_command(self, command: str) -> str:
        """Classify shell command risk level (v1.11.2).

        Args:
            command: Shell command to classify

        Returns:
            Risk level: "never", "dangerous", or "safe"
        """
        import re

        # Check never-allow patterns (catastrophic commands)
        never_allow = self._shell_config.get("never_allow", [])
        for pattern in never_allow:
            try:
                if re.search(pattern, command):
                    return "never"
            except re.error:
                pass

        # Check dangerous patterns (require consent)
        dangerous = self._shell_config.get("dangerous_commands", [])
        for pattern in dangerous:
            try:
                if re.search(pattern, command):
                    return "dangerous"
            except re.error:
                pass

        # Check allowed patterns (safe)
        allowed = self._shell_config.get("allowed_commands", [])
        for pattern in allowed:
            try:
                if re.search(pattern, command):
                    return "safe"
            except re.error:
                pass

        # Unknown commands are treated as dangerous for safety
        return "dangerous"

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

        # Debug logging (v1.11.2, v1.12.1: use common logger)
        try:
            from ppxai.common.logger import get_logger
            logger = get_logger("tui")
            logger.debug(f"Shell consent: command='{command[:50]}...' risk={risk_level} callback={self.shell_consent_callback is not None}")
        except:
            pass

        # Never-allow commands are always blocked
        if risk_level == "never":
            return False

        # Safe commands are always allowed (no consent needed)
        if risk_level == "safe":
            return True

        # Check global shell consent mode
        if self.session.shell_consent_mode == "always":
            return True
        if self.session.shell_consent_mode == "never":
            return False

        # Check if already consented for this specific command
        if command in self.session.allowed_commands:
            return True

        # If no callback, default to deny (fail-safe)
        if self.shell_consent_callback is None:
            return False

        # Request consent from user via callback
        try:
            # Debug logging (v1.12.1: use common logger)
            try:
                from ppxai.common.logger import get_logger
                logger = get_logger("tui")
                logger.debug(f"Requesting shell consent for: {command[:50]}...")
            except:
                pass

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
            try:
                logger.debug(f"Shell consent response: approved={approved} response={response}")
            except:
                pass

            if response == "y":
                self.session.allowed_commands.add(command)
                return True
            elif response == "always":
                self.session.shell_consent_mode = "always"
                return True
            elif response == "never":
                self.session.shell_consent_mode = "never"
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
            setting: Setting name (e.g., 'max_iterations', 'verbose')
            value: Setting value

        Returns:
            True if setting was applied
        """
        if setting == "max_iterations":
            self.tool_manager.max_iterations = int(value)
            return True
        elif setting == "verbose":
            # v1.12.0: Store verbose setting for tool output display
            self._tools_verbose = value in [True, "on", "true", "1", "yes"]
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
            "verbose": self._tools_verbose  # v1.12.0: Include verbose setting
        }

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
            message, injected_contexts = self.context_injector.inject_context(message)

            # Emit events for each injected file
            for ctx in injected_contexts:
                yield Event(EventType.CONTEXT_INJECTED, {
                    'source': ctx.source,
                    'language': ctx.language,
                    'truncated': ctx.truncated,
                    'size': ctx.size
                })

        # Add message to history (with injected content)
        self.session.add_message(Message("user", message))

        if self.tools_enabled:
            async for event in self._chat_with_tools(stream):
                yield event
        else:
            async for event in self._chat_simple(stream):
                yield event

    async def _chat_simple(self, stream: bool) -> AsyncIterator[Event]:
        """Simple chat without tools."""
        messages = self.session.get_messages()

        # Add system prompt for inline citation URLs if provider has web search/citations
        if self.provider and (self.provider.capabilities.citations or self.provider.capabilities.web_search):
            citation_prompt = Message(
                "system",
                "When citing sources, always include the full URL in parentheses after "
                "the citation number, like [1](https://example.com). This helps users "
                "click through to the sources directly."
            )
            messages = [citation_prompt] + messages

        async for event in self.provider.chat(messages, self.model, stream):
            # Check for interrupt
            if self._interrupted:
                yield Event(EventType.ERROR, "Interrupted by user")
                break

            # CRITICAL FIX: Add assistant message to session BEFORE yielding STREAM_END
            # because the caller (TUI main loop) may break out of the loop after receiving it
            if event.type == EventType.STREAM_END:
                self.session.add_message(Message("assistant", event.data))
                if event.metadata and event.metadata.get("usage"):
                    usage = event.metadata["usage"]
                    # Calculate cost based on model and provider
                    usage.estimated_cost = calculate_cost(
                        usage.prompt_tokens,
                        usage.completion_tokens,
                        self.model,
                        self.provider_name  # Fixed: was provider_id
                    )
                    # v1.13.4: Add tool usage from this response
                    if hasattr(self, '_current_tool_usage'):
                        usage.tool_calls = self._current_tool_usage
                        self._current_tool_usage = {}  # Reset for next response
                    # v1.12.2: Pass provider and model for per-model tracking
                    self.session.update_usage(usage, self.provider_name, self.model)
                    # Convert UsageStats to dict for JSON serialization
                    event.metadata["usage"] = asdict(usage)

            # Now yield the event to caller (TUI may break after this)
            yield event

    async def _chat_with_tools(self, stream: bool) -> AsyncIterator[Event]:
        """Chat with tool support.

        Supports two modes:
        1. Native tool calling (vLLM with --enable-auto-tool-choice): Provider returns TOOL_CALL events
        2. Prompt-based (fallback): Parse tool calls from model's text response
        """
        iteration = 0
        max_iterations = self.tool_manager.max_iterations

        # Track accumulated usage across all provider calls (v1.12.0)
        accumulated_usage = UsageStats()

        # Check if provider supports native tool calling (v1.13.x)
        use_native_tools = (
            self.provider and
            hasattr(self.provider, 'capabilities') and
            self.provider.capabilities.native_tool_calling
        )

        # Get tools in OpenAI format for native tool calling
        openai_tools = None
        if use_native_tools:
            openai_tools = self.tool_manager.get_tools_openai_format()

        # Emit stream start at beginning
        yield Event(EventType.STREAM_START, {"model": self.model})

        while iteration < max_iterations:
            # Check for interrupt
            if self._interrupted:
                yield Event(EventType.ERROR, "Interrupted by user")
                return

            iteration += 1

            # Emit progress for tool iterations (after first)
            if iteration > 1:
                yield Event(EventType.INFO, f"Processing... (iteration {iteration})")

            # Build messages with tool prompt (only for prompt-based mode)
            messages = self.session.get_messages()

            if not use_native_tools:
                # Prompt-based tool calling: add system message with tool instructions
                tool_prompt = self.tool_manager.get_tools_prompt()
                if tool_prompt:
                    # Add citation URL instruction if provider has web search/citations OR web_search tool is available
                    has_native_search = self.provider and (self.provider.capabilities.citations or self.provider.capabilities.web_search)
                    has_search_tool = self.tool_manager.get_tool("web_search") is not None
                    if has_native_search or has_search_tool:
                        tool_prompt += (
                            "\n\nWhen citing sources or URLs from search results, format them as markdown links "
                            "like [Source Name](https://example.com) so they are clickable."
                        )
                    messages = [Message("system", tool_prompt)] + messages

            # Get response from provider
            full_response = ""
            native_tool_calls = []  # Collect native tool calls from provider
            async for event in self.provider.chat(messages, self.model, stream=False, tools=openai_tools):
                if event.type == EventType.ERROR:
                    yield event
                    return
                elif event.type == EventType.TOOL_CALL:
                    # Native tool call from provider (vLLM with --enable-auto-tool-choice)
                    native_tool_calls.append(event.data)
                elif event.type == EventType.STREAM_END:
                    full_response = event.data
                    # Accumulate usage from this provider call (v1.12.0)
                    if event.metadata and event.metadata.get("usage"):
                        usage = event.metadata["usage"]
                        accumulated_usage.prompt_tokens += usage.prompt_tokens
                        accumulated_usage.completion_tokens += usage.completion_tokens
                        accumulated_usage.total_tokens += usage.total_tokens

            # Determine tool call: native takes precedence, then parse from text
            tool_call = None
            if native_tool_calls:
                # Use first native tool call (models typically call one at a time)
                tc = native_tool_calls[0]
                tool_call = {"tool": tc["tool"], "arguments": tc.get("arguments", {})}
            else:
                # Fallback: parse tool call from text response
                tool_call = self._parse_tool_call(full_response)

            if tool_call:
                tool_name = tool_call["tool"]
                tool_args = tool_call.get("arguments", {})

                yield Event(EventType.TOOL_CALL, {
                    "tool": tool_name,
                    "arguments": tool_args
                })

                # Execute tool
                try:
                    # Execute tool in background to allow consent events to be yielded
                    tool_task = asyncio.create_task(self.tool_manager.execute_tool(tool_name, **tool_args))

                    # Poll consent event queue while tool is running
                    # (file editing tools will add consent requests to queue during execution)
                    while not tool_task.done():
                        while self._consent_event_queue:
                            consent_event = self._consent_event_queue.pop(0)
                            yield consent_event
                        await asyncio.sleep(0.05)  # Poll every 50ms

                    # Drain any remaining consent events
                    while self._consent_event_queue:
                        consent_event = self._consent_event_queue.pop(0)
                        yield consent_event

                    # Get tool result
                    result = await tool_task

                    # v1.13.4: Track tool usage for premium search
                    if tool_name == "web_search":
                        try:
                            from .tools.builtin import web_premium
                            tool_usage = web_premium.get_last_tool_usage()

                            if tool_usage:
                                if not hasattr(self, '_current_tool_usage'):
                                    self._current_tool_usage = {}
                                self._current_tool_usage[tool_name] = tool_usage
                        except Exception:
                            pass  # Ignore if tracking fails

                    yield Event(EventType.TOOL_RESULT, {
                        "tool": tool_name,
                        "result": result[:2000] + "..." if len(result) > 2000 else result
                    })

                    # Add to conversation history
                    self.session.add_message(Message(
                        "assistant",
                        f"I'll use the {tool_name} tool.\n```json\n{json.dumps(tool_call, indent=2)}\n```"
                    ))
                    self.session.add_message(Message(
                        "user",
                        f"The {tool_name} tool returned:\n\n{result}\n\nNow use this information to answer my original question. Do NOT just repeat or echo the tool output - synthesize it into a helpful response. If you need more information, call another tool."
                    ))

                except Exception as e:
                    error_msg = str(e)
                    yield Event(EventType.TOOL_ERROR, {
                        "tool": tool_name,
                        "error": error_msg
                    })

                    self.session.add_message(Message(
                        "assistant",
                        f"I'll use the {tool_name} tool.\n```json\n{json.dumps(tool_call, indent=2)}\n```"
                    ))
                    self.session.add_message(Message(
                        "user",
                        f"The {tool_name} tool failed with error: {error_msg}\n\nPlease provide an answer without using that tool, or try a different approach."
                    ))

                # Continue loop for next iteration
                continue

            else:
                # No tool call - this is the final response
                # v1.11.7 FIX: Don't re-request with streaming - use the response we already have.
                # Re-requesting caused bugs where the model would output a tool call on the
                # second request, which would then be sent as the final response without
                # being parsed as a tool call.
                #
                # The response was already fetched with stream=False during tool iterations.
                # Just emit it as the final response.
                self.session.add_message(Message("assistant", full_response))

                # v1.12.0: Commit agent changes after successful task completion
                # NOTE: Only commit if agent made file edits (tracked via _agent_edited_files)
                # This prevents committing unrelated changes from other tools (e.g., Claude Code)
                if self._agent_mode and self._checkpoint_manager and self._agent_edited_files:
                    commit_hash = self.commit_agent_changes("Task completed")
                    if commit_hash:
                        yield Event(EventType.STATUS, f"✓ Changes committed: {commit_hash[:8]}")
                    # Reset edited files tracking for next task
                    self._agent_edited_files.clear()

                # v1.12.0: Calculate cost and update session with accumulated usage
                metadata = None
                if accumulated_usage.total_tokens > 0:
                    accumulated_usage.estimated_cost = calculate_cost(
                        accumulated_usage.prompt_tokens,
                        accumulated_usage.completion_tokens,
                        self.model,
                        self.provider_name
                    )
                    # v1.13.4: Add tool usage from tools executed during this request
                    if hasattr(self, '_current_tool_usage'):
                        accumulated_usage.tool_calls = self._current_tool_usage
                        self._current_tool_usage = {}  # Reset for next request
                    # v1.12.2: Pass provider and model for per-model tracking
                    self.session.update_usage(accumulated_usage, self.provider_name, self.model)
                    metadata = {"usage": asdict(accumulated_usage)}

                yield Event(EventType.STREAM_END, full_response, metadata)
                return

        # Max iterations reached
        yield Event(EventType.INFO, "Maximum tool iterations reached")
        self.session.add_message(Message(
            "assistant",
            "[Tool iterations limit reached. Please try again with a simpler query.]"
        ))

    def _parse_tool_call(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse a tool call from model response.

        Args:
            text: Model response text

        Returns:
            Tool call dict with 'tool' and 'arguments' keys, or None
        """
        def normalize_tool_call(data: dict) -> Optional[dict]:
            if "tool" not in data:
                return None
            tool_name = data["tool"]

            tool = self.tool_manager.get_tool(tool_name)
            if not tool:
                return None

            if "arguments" in data:
                args = data["arguments"]
                # v1.13.2: Handle nested tool call structure from some models (e.g., GPT-OSS 120B via vLLM)
                # Model sometimes outputs: {"tool": "apply_patch", "arguments": {"tool": "apply_patch", "arguments": {...}}}
                # Unwrap the nested structure to get the actual arguments
                if isinstance(args, dict) and "tool" in args and "arguments" in args:
                    # Nested tool call - unwrap it
                    args = args["arguments"]
                return {"tool": tool_name, "arguments": args}

            # Model put parameters at top level
            expected_params = set(tool.parameters.get("properties", {}).keys())
            arguments = {}
            for key, value in data.items():
                if key != "tool" and key in expected_params:
                    arguments[key] = value

            # v1.13.2: Handle tools with no required arguments (e.g., get_working_directory)
            required_params = tool.parameters.get("required", [])
            if arguments or not required_params:
                return {"tool": tool_name, "arguments": arguments}

            return None

        def infer_tool_from_arguments(data: dict) -> Optional[dict]:
            """Infer which tool based on argument patterns when 'tool' key is missing.

            This handles models (like vLLM-served models) that output raw JSON arguments
            without the required 'tool' wrapper.

            Uses a configuration-driven dispatcher pattern for maintainability.
            """
            if "tool" in data:
                return None  # Already has tool key, use normalize_tool_call instead

            keys = set(data.keys())

            # Tool inference rules: each rule defines how to detect and normalize a tool call
            # Format: {
            #   "tool": tool name,
            #   "required": keys that MUST be present (any one of list items),
            #   "allowed": all keys that can be present (superset check),
            #   "aliases": {canonical_param: [alias1, alias2, ...]} for normalization
            # }
            tool_rules = [
                {
                    "tool": "web_search",
                    "required": ["query"],
                    "allowed": {"query", "num_results", "top_n", "count", "limit", "max_results", "recency_days"},
                    "aliases": {
                        "num_results": ["top_n", "count", "limit", "max_results"],
                    }
                },
                {
                    "tool": "read_file",
                    "required": ["path", "filepath"],  # Either one satisfies
                    "allowed": {"path", "filepath", "line_start", "line_end", "max_lines"},
                    "aliases": {
                        "filepath": ["path"],  # Normalize path -> filepath
                    }
                },
                {
                    "tool": "list_directory",
                    "required": [],  # No required keys, but must have at least one allowed key
                    "allowed": {"path", "format"},
                    "aliases": {}
                },
                {
                    "tool": "execute_shell_command",
                    "required": ["command"],
                    "allowed": {"command", "working_dir"},
                    "aliases": {}
                },
                {
                    "tool": "fetch_url",
                    "required": ["url"],
                    "allowed": {"url", "max_length"},
                    "aliases": {}
                },
                {
                    "tool": "get_weather",
                    "required": ["location"],
                    "allowed": {"location", "format"},
                    "aliases": {}
                },
                {
                    "tool": "calculator",
                    "required": ["expression"],
                    "allowed": {"expression"},
                    "aliases": {}
                },
            ]

            def match_rule(rule: dict) -> Optional[dict]:
                """Check if data matches a tool rule and return normalized arguments."""
                tool_name = rule["tool"]
                required = rule["required"]
                allowed = rule["allowed"]
                aliases = rule["aliases"]

                # Check required keys (any one from list must be present)
                if required:
                    if not any(req in keys for req in required):
                        return None
                elif not keys:
                    # No required keys defined, but data must have at least one allowed key
                    return None

                # Check that all keys are in allowed set
                if not keys <= allowed:
                    return None

                # Normalize arguments using aliases
                args = {}
                for key, value in data.items():
                    # Check if this key should be mapped to a canonical name
                    canonical = key
                    for canon, alias_list in aliases.items():
                        if key in alias_list:
                            canonical = canon
                            break
                    args[canonical] = value

                return {"tool": tool_name, "arguments": args}

            # Try each rule in order (first match wins)
            for rule in tool_rules:
                result = match_rule(rule)
                if result:
                    return result

            return None

        def try_parse_json(json_str: str) -> Optional[dict]:
            """Try to parse JSON, including handling single quotes."""
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                # Try converting single quotes to double quotes (Python dict style)
                # This handles cases where models output {'tool': 'name'} instead of {"tool": "name"}
                try:
                    fixed = json_str.replace("'", '"')
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    return None

        # Try entire response as JSON first (most common case for tool calls)
        text_stripped = text.strip()
        if text_stripped.startswith('{') and text_stripped.endswith('}'):
            data = try_parse_json(text_stripped)
            if data:
                normalized = normalize_tool_call(data)
                if normalized:
                    return normalized
                # Fallback: try to infer tool from arguments (for models like vLLM)
                inferred = infer_tool_from_arguments(data)
                if inferred:
                    return inferred

        # Try extracting JSON from markdown code blocks
        # Match ```json ... ``` or ``` ... ``` blocks
        code_block_pattern = r'```(?:json)?\s*([\s\S]*?)```'
        matches = re.findall(code_block_pattern, text)

        for match in matches:
            match_stripped = match.strip()
            if match_stripped.startswith('{') and match_stripped.endswith('}'):
                data = try_parse_json(match_stripped)
                if data:
                    normalized = normalize_tool_call(data)
                    if normalized:
                        return normalized
                    # Fallback: try to infer tool from arguments
                    inferred = infer_tool_from_arguments(data)
                    if inferred:
                        return inferred

        # Try JSON in code blocks - use greedy match for nested braces (fallback)
        code_block_pattern2 = r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'
        matches = re.findall(code_block_pattern2, text)

        for match in matches:
            data = try_parse_json(match)
            if data:
                normalized = normalize_tool_call(data)
                if normalized:
                    return normalized
                # Fallback: try to infer tool from arguments
                inferred = infer_tool_from_arguments(data)
                if inferred:
                    return inferred

        # Try to find JSON objects with "tool" key using a more robust approach
        # Look for complete JSON objects by counting braces
        # Also try single-quote style: {'tool'
        for pattern in ['{"tool"', "{'tool'"]:
            start_idx = 0
            while True:
                start = text.find(pattern, start_idx)
                if start == -1:
                    break

                # Find matching closing brace
                depth = 0
                end = start
                for i, char in enumerate(text[start:], start):
                    if char == '{':
                        depth += 1
                    elif char == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break

                if depth == 0 and end > start:
                    json_str = text[start:end]
                    data = try_parse_json(json_str)
                    if data:
                        normalized = normalize_tool_call(data)
                        if normalized:
                            return normalized

                start_idx = end if end > start else start + 1

        return None

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

    def save_session(self, name: Optional[str] = None) -> str:
        """Save current session.

        Args:
            name: Optional session name

        Returns:
            Session name
        """
        return self.session.save(name)

    def load_session(self, name: str) -> bool:
        """Load a saved session.

        Args:
            name: Session name

        Returns:
            True if loaded successfully
        """
        return self.session.load(name)

    def list_sessions(self) -> List[SessionInfo]:
        """List saved sessions.

        Returns:
            List of SessionInfo objects
        """
        return self.session.list_sessions()

    def clear_history(self):
        """Clear conversation history."""
        self.session.clear()

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
        from datetime import datetime
        from ..config import EXPORTS_DIR

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

    # === Cleanup ===

    async def cleanup(self):
        """Clean up resources."""
        await self.tool_manager.cleanup()

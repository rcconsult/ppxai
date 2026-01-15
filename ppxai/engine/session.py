"""
Session management for the ppxai engine.

Handles conversation history, session persistence, and usage tracking.

v1.13.9: Added session state file for auto-recovery and command history persistence.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from .types import Message, UsageStats, SessionInfo
from ..common.logger import get_logger

logger = get_logger("tui")


# Session state file location
SESSION_STATE_FILE = Path.home() / ".ppxai" / "session-state.json"


class SessionManager:
    """Manages conversation sessions, history, and persistence."""

    def __init__(self, sessions_dir: Optional[Path] = None, exports_dir: Optional[Path] = None):
        """Initialize the session manager.

        Args:
            sessions_dir: Directory for session files
            exports_dir: Directory for exported conversations
        """
        # Default directories
        if sessions_dir is None:
            sessions_dir = Path.home() / ".ppxai" / "sessions"
        if exports_dir is None:
            exports_dir = Path.home() / ".ppxai" / "exports"

        self.sessions_dir = Path(sessions_dir)
        self.exports_dir = Path(exports_dir)

        # Ensure directories exist
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

        # Current session state
        self.session_name = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.messages: List[Message] = []
        self.metadata: Dict[str, Any] = {
            "created_at": datetime.now().isoformat(),
            "provider": None,
            "model": None,
            "message_count": 0
        }
        self.usage = UsageStats()

        # v1.12.2: Per-model usage tracking
        # Keys are "provider/model" strings, e.g., "perplexity/sonar-pro"
        self.usage_by_model: Dict[str, UsageStats] = {}

        # v1.12.2: Usage display mode for status line
        # "session" = total session usage (default)
        # "provider" = current provider usage only
        # "model" = current model usage only
        # "off" = hide usage from status line
        self.usage_display_mode: str = "session"

        # File editing consent state (Phase 1: v1.11.0)
        self.allowed_files: set[Path] = set()  # Files user consented to edit
        self.edit_consent_mode: str = "ask"  # "ask", "always", "never"

        # Shell command consent state (v1.11.2)
        self.allowed_commands: set[str] = set()  # Commands user consented to run
        self.shell_consent_mode: str = "ask"  # "ask", "always", "never"

        # v1.13.9: Session persistence and recovery
        self.command_history: List[str] = []  # User input history for this session
        self.working_dir: str = os.getcwd()  # Working directory for this session
        self.tools_enabled: bool = False  # Whether tools were enabled
        self._dirty: bool = False  # True if session has unsaved changes

    def add_message(self, message: Message):
        """Add a message to the conversation history.

        Args:
            message: Message to add
        """
        self.messages.append(message)
        self.metadata["message_count"] = len(self.messages)

    def get_messages(self) -> List[Message]:
        """Get conversation history.

        Returns:
            List of Message objects
        """
        return self.messages.copy()

    def get_messages_as_dicts(self) -> List[Dict[str, str]]:
        """Get conversation history as dictionaries.

        Returns:
            List of dicts with 'role' and 'content' keys
        """
        return [{"role": m.role, "content": m.content} for m in self.messages]

    def remove_last_message(self) -> bool:
        """Remove the last message from conversation history.

        Used to cleanup interrupted messages (e.g., Ctrl-C during streaming)
        to maintain proper user/assistant message alternation.

        Returns:
            True if a message was removed, False if history was empty
        """
        if self.messages:
            self.messages.pop()
            self.metadata["message_count"] = len(self.messages)
            return True
        return False

    def clear(self):
        """Clear conversation history and reset consent state."""
        self.messages = []
        self.metadata["message_count"] = 0
        # Reset file editing consent state
        self.allowed_files.clear()
        self.edit_consent_mode = "ask"

    def set_provider(self, provider: str):
        """Set the current provider.

        Args:
            provider: Provider name
        """
        self.metadata["provider"] = provider

    def set_model(self, model: str):
        """Set the current model.

        Args:
            model: Model ID
        """
        self.metadata["model"] = model

    def update_usage(self, usage: UsageStats, provider: str = None, model: str = None):
        """Update usage statistics.

        Args:
            usage: UsageStats to add
            provider: Provider name (for per-model tracking)
            model: Model ID (for per-model tracking)
        """
        # Update session totals
        self.usage.prompt_tokens += usage.prompt_tokens
        self.usage.completion_tokens += usage.completion_tokens
        self.usage.total_tokens += usage.total_tokens
        self.usage.estimated_cost += usage.estimated_cost

        # v1.12.2: Update per-model tracking
        if provider and model:
            key = f"{provider}/{model}"
            if key not in self.usage_by_model:
                self.usage_by_model[key] = UsageStats()

            model_usage = self.usage_by_model[key]
            model_usage.prompt_tokens += usage.prompt_tokens
            model_usage.completion_tokens += usage.completion_tokens
            model_usage.total_tokens += usage.total_tokens
            model_usage.estimated_cost += usage.estimated_cost

        # v1.13.4: Merge tool usage
        for tool_name, tool_usage in usage.tool_calls.items():
            if tool_name not in self.usage.tool_calls:
                from .types import ToolUsage
                self.usage.tool_calls[tool_name] = ToolUsage(provider=tool_usage.provider)
            self.usage.tool_calls[tool_name].call_count += tool_usage.call_count
            self.usage.tool_calls[tool_name].tokens_in += tool_usage.tokens_in
            self.usage.tool_calls[tool_name].tokens_out += tool_usage.tokens_out
            self.usage.tool_calls[tool_name].estimated_cost += tool_usage.estimated_cost

    def get_usage(self) -> Dict[str, Any]:
        """Get usage statistics.

        Returns:
            Dictionary with usage stats including per-model breakdown and tool usage
        """
        return {
            "total_tokens": self.usage.total_tokens,
            "prompt_tokens": self.usage.prompt_tokens,
            "completion_tokens": self.usage.completion_tokens,
            "estimated_cost": self.usage.estimated_cost,
            # v1.12.2: Add per-model breakdown
            "by_model": {
                key: {
                    "total_tokens": stats.total_tokens,
                    "prompt_tokens": stats.prompt_tokens,
                    "completion_tokens": stats.completion_tokens,
                    "estimated_cost": stats.estimated_cost
                }
                for key, stats in self.usage_by_model.items()
            },
            # v1.13.4: Add tool usage breakdown
            "tool_calls": {
                tool_name: {
                    "call_count": tool_usage.call_count,
                    "tokens_in": tool_usage.tokens_in,
                    "tokens_out": tool_usage.tokens_out,
                    "estimated_cost": tool_usage.estimated_cost,
                    "provider": tool_usage.provider
                }
                for tool_name, tool_usage in self.usage.tool_calls.items()
            },
            "display_mode": self.usage_display_mode
        }

    def get_usage_for_display(self, current_provider: str = None, current_model: str = None) -> Optional[Dict[str, Any]]:
        """Get usage statistics for status line display based on display mode.

        Args:
            current_provider: Current provider name
            current_model: Current model ID

        Returns:
            Dictionary with usage stats for display, or None if display_mode is "off"
        """
        if self.usage_display_mode == "off":
            return None

        if self.usage_display_mode == "session":
            return {
                "label": None,  # No label for session totals
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "estimated_cost": self.usage.estimated_cost
            }

        if self.usage_display_mode == "provider" and current_provider:
            # Aggregate all models for current provider
            prompt_tokens = 0
            completion_tokens = 0
            estimated_cost = 0.0
            for key, stats in self.usage_by_model.items():
                if key.startswith(f"{current_provider}/"):
                    prompt_tokens += stats.prompt_tokens
                    completion_tokens += stats.completion_tokens
                    estimated_cost += stats.estimated_cost
            return {
                "label": current_provider[:4],  # Short provider label
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "estimated_cost": estimated_cost
            }

        if self.usage_display_mode == "model" and current_provider and current_model:
            key = f"{current_provider}/{current_model}"
            if key in self.usage_by_model:
                stats = self.usage_by_model[key]
                # Use short model name (last part after any /)
                short_model = current_model.split("/")[-1][:12]
                return {
                    "label": short_model,
                    "prompt_tokens": stats.prompt_tokens,
                    "completion_tokens": stats.completion_tokens,
                    "estimated_cost": stats.estimated_cost
                }
            return {
                "label": current_model.split("/")[-1][:12],
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "estimated_cost": 0.0
            }

        # Fallback to session totals
        return {
            "label": None,
            "prompt_tokens": self.usage.prompt_tokens,
            "completion_tokens": self.usage.completion_tokens,
            "estimated_cost": self.usage.estimated_cost
        }

    def set_usage_display_mode(self, mode: str) -> bool:
        """Set the usage display mode for status line.

        Args:
            mode: One of "session", "provider", "model", "off"

        Returns:
            True if mode was set successfully
        """
        valid_modes = {"session", "provider", "model", "off"}
        if mode in valid_modes:
            self.usage_display_mode = mode
            return True
        return False

    def reset_usage(self):
        """Reset all usage statistics to zero."""
        self.usage = UsageStats()
        self.usage_by_model.clear()

    def get_usage_by_provider(self) -> Dict[str, Dict[str, Any]]:
        """Get usage aggregated by provider.

        Returns:
            Dictionary with provider as key and aggregated stats as value
        """
        by_provider: Dict[str, UsageStats] = {}
        for key, stats in self.usage_by_model.items():
            provider = key.split("/")[0]
            if provider not in by_provider:
                by_provider[provider] = UsageStats()
            by_provider[provider].prompt_tokens += stats.prompt_tokens
            by_provider[provider].completion_tokens += stats.completion_tokens
            by_provider[provider].total_tokens += stats.total_tokens
            by_provider[provider].estimated_cost += stats.estimated_cost

        return {
            provider: {
                "total_tokens": stats.total_tokens,
                "prompt_tokens": stats.prompt_tokens,
                "completion_tokens": stats.completion_tokens,
                "estimated_cost": stats.estimated_cost
            }
            for provider, stats in by_provider.items()
        }

    def save(self, name: Optional[str] = None) -> str:
        """Save current session to file.

        Args:
            name: Optional session name (uses auto-generated if not provided)

        Returns:
            Session name

        v1.13.9: Now includes working_dir and tools_enabled for session persistence.
        """
        if name:
            self.session_name = name

        filepath = self.sessions_dir / f"{self.session_name}.json"

        session_data = {
            "session_name": self.session_name,
            "metadata": self.metadata,
            "messages": [{"role": m.role, "content": m.content} for m in self.messages],
            "usage": self.get_usage(),
            "saved_at": datetime.now().isoformat(),
            # v1.13.9: Include persistence fields
            "command_history": self.command_history,
            "working_dir": self.working_dir,
            "tools_enabled": self.tools_enabled
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2)

        return self.session_name

    def load(self, name: str) -> bool:
        """Load a saved session.

        Args:
            name: Session name to load

        Returns:
            True if loaded successfully
        """
        filepath = self.sessions_dir / f"{name}.json"

        if not filepath.exists():
            return False

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.session_name = data.get("session_name", name)
            self.metadata = data.get("metadata", {})
            self.messages = [
                Message(role=m["role"], content=m["content"])
                for m in data.get("messages", [])
            ]

            usage_data = data.get("usage", {})
            self.usage = UsageStats(
                total_tokens=usage_data.get("total_tokens", 0),
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                estimated_cost=usage_data.get("estimated_cost", 0.0)
            )

            # v1.13.9: Load persistence fields (same as load_with_extras)
            self.command_history = data.get("command_history", [])
            self.working_dir = data.get("working_dir", os.getcwd())
            self.tools_enabled = data.get("tools_enabled", False)

            return True

        except Exception:
            return False

    def list_sessions(self) -> List[SessionInfo]:
        """List all saved sessions.

        Returns:
            List of SessionInfo objects
        """
        sessions = []

        for filepath in sorted(self.sessions_dir.glob("*.json"), reverse=True):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                metadata = data.get("metadata", {})
                sessions.append(SessionInfo(
                    name=data.get("session_name", filepath.stem),
                    created_at=metadata.get("created_at", ""),
                    provider=metadata.get("provider", "unknown"),
                    model=metadata.get("model", "unknown"),
                    message_count=len(data.get("messages", [])),
                    saved_at=data.get("saved_at", "")
                ))
            except Exception as e:
                logger.warning(f"Skipping corrupted session file '{filepath.name}': {e}")
                continue

        return sessions

    def export(self, filename: Optional[str] = None) -> Path:
        """Export conversation to a markdown file.

        Args:
            filename: Optional filename (auto-generated if not provided)

        Returns:
            Path to exported file
        """
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"conversation_{timestamp}.md"

        filepath = self.exports_dir / filename

        # Build markdown content
        content = f"# Conversation Export\n\n"
        content += f"**Exported:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        content += f"**Session:** {self.session_name}\n"
        if self.metadata.get("model"):
            content += f"**Model:** {self.metadata['model']}\n"
        content += f"**Messages:** {len(self.messages)}\n\n"

        # Add usage stats
        usage = self.get_usage()
        content += f"## Usage Statistics\n\n"
        content += f"- Total Tokens: {usage['total_tokens']:,}\n"
        content += f"- Prompt Tokens: {usage['prompt_tokens']:,}\n"
        content += f"- Completion Tokens: {usage['completion_tokens']:,}\n"
        content += f"- Estimated Cost: ${usage['estimated_cost']:.4f}\n\n"

        content += "---\n\n"

        # Add conversation
        content += "## Conversation\n\n"
        for msg in self.messages:
            role = msg.role.capitalize()
            content += f"### {role}\n\n{msg.content}\n\n"

        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        return filepath

    def delete_session(self, name: str) -> bool:
        """Delete a saved session.

        Args:
            name: Session name to delete

        Returns:
            True if deleted successfully
        """
        filepath = self.sessions_dir / f"{name}.json"

        if filepath.exists():
            filepath.unlink()
            return True
        return False

    def save_usage_to_persistent_storage(self):
        """Save session usage to persistent storage (v1.12.3).

        Called when session ends (exit, /clear, etc.) to persist usage data
        across sessions for time-based analytics.
        """
        from datetime import datetime
        from ..usage import save_session_usage

        # Skip if no usage
        if self.usage.total_tokens == 0 and self.usage.estimated_cost == 0.0:
            return

        # Convert UsageStats to dict format for persistence
        usage_by_model = {
            key: {
                "prompt_tokens": stats.prompt_tokens,
                "completion_tokens": stats.completion_tokens,
                "estimated_cost": stats.estimated_cost
            }
            for key, stats in self.usage_by_model.items()
        }

        # Parse created_at from metadata or use current time
        try:
            started_at = datetime.fromisoformat(self.metadata.get("created_at", datetime.now().isoformat()))
        except ValueError:
            started_at = datetime.now()

        save_session_usage(
            session_id=self.session_name,
            started_at=started_at,
            ended_at=datetime.now(),
            usage_by_model=usage_by_model,
            total_cost=self.usage.estimated_cost,
            total_tokens=self.usage.total_tokens,
            message_count=len(self.messages)
        )

    # =========================================================================
    # v1.13.9: Session State File Management
    # =========================================================================

    def add_to_history(self, command: str):
        """Add a command to the session's command history.

        Args:
            command: User input to add to history
        """
        if command and command.strip():
            self.command_history.append(command.strip())

    def set_working_dir(self, path: str):
        """Set the working directory for this session.

        Args:
            path: Working directory path
        """
        self.working_dir = path

    def save_dirty(self) -> str:
        """Save session and mark it as dirty (unsaved changes).

        This is called after each roundtrip to keep the session file synced.

        Returns:
            Session name
        """
        # Save the session file
        self._save_with_extras()

        # Update state file to mark session as dirty
        self._update_state_file(dirty=True)

        self._dirty = True
        return self.session_name

    def mark_clean(self):
        """Mark session as clean (graceful exit).

        Called when the application exits gracefully to indicate
        the session was properly saved.
        """
        self._update_state_file(dirty=False)
        self._dirty = False

    def _save_with_extras(self) -> str:
        """Save session with command history and working directory.

        Internal method that saves the full session data including
        the new v1.13.9 fields.

        Returns:
            Session name
        """
        filepath = self.sessions_dir / f"{self.session_name}.json"

        session_data = {
            "session_name": self.session_name,
            "metadata": self.metadata,
            "messages": [{"role": m.role, "content": m.content} for m in self.messages],
            "usage": self.get_usage(),
            "saved_at": datetime.now().isoformat(),
            # v1.13.9: New fields
            "command_history": self.command_history,
            "working_dir": self.working_dir,
            "tools_enabled": self.tools_enabled
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2)

        return self.session_name

    def _update_state_file(self, dirty: bool):
        """Update the session state file.

        Args:
            dirty: Whether the session has unsaved changes
        """
        # Ensure parent directory exists
        SESSION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        state_data = {
            "version": 1,
            "last_session": {
                "name": self.session_name,
                "dirty": dirty,
                "provider": self.metadata.get("provider"),
                "model": self.metadata.get("model"),
                "working_dir": self.working_dir,
                "tools_enabled": self.tools_enabled,
                "message_count": len(self.messages)
            },
            "updated_at": datetime.now().isoformat()
        }

        with open(SESSION_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state_data, f, indent=2)

    @staticmethod
    def get_last_session_state() -> Optional[Dict[str, Any]]:
        """Get the last session state from the state file.

        Returns:
            Dictionary with last session info, or None if no state file exists
        """
        if not SESSION_STATE_FILE.exists():
            return None

        try:
            with open(SESSION_STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get("last_session")
        except Exception:
            return None

    @staticmethod
    def clear_state_file():
        """Clear the session state file.

        Called when starting a fresh session to prevent auto-restore.
        """
        if SESSION_STATE_FILE.exists():
            SESSION_STATE_FILE.unlink()

    def load_with_extras(self, name: str) -> bool:
        """Load a saved session including command history and working directory.

        Args:
            name: Session name to load

        Returns:
            True if loaded successfully
        """
        filepath = self.sessions_dir / f"{name}.json"

        if not filepath.exists():
            return False

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.session_name = data.get("session_name", name)
            self.metadata = data.get("metadata", {})
            self.messages = [
                Message(role=m["role"], content=m["content"])
                for m in data.get("messages", [])
            ]

            usage_data = data.get("usage", {})
            self.usage = UsageStats(
                total_tokens=usage_data.get("total_tokens", 0),
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                estimated_cost=usage_data.get("estimated_cost", 0.0)
            )

            # v1.13.9: Load new fields
            self.command_history = data.get("command_history", [])
            self.working_dir = data.get("working_dir", os.getcwd())
            self.tools_enabled = data.get("tools_enabled", False)

            return True

        except Exception:
            return False

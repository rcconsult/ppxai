"""
Session management for the ppxai engine.

Handles conversation history, session persistence, and usage tracking.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from .types import Message, UsageStats, SessionInfo


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

    def clear(self):
        """Clear conversation history."""
        self.messages = []
        self.metadata["message_count"] = 0

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

    def update_usage(self, usage: UsageStats):
        """Update usage statistics.

        Args:
            usage: UsageStats to add
        """
        self.usage.prompt_tokens += usage.prompt_tokens
        self.usage.completion_tokens += usage.completion_tokens
        self.usage.total_tokens += usage.total_tokens
        self.usage.estimated_cost += usage.estimated_cost

    def get_usage(self) -> Dict[str, Any]:
        """Get usage statistics.

        Returns:
            Dictionary with usage stats
        """
        return {
            "total_tokens": self.usage.total_tokens,
            "prompt_tokens": self.usage.prompt_tokens,
            "completion_tokens": self.usage.completion_tokens,
            "estimated_cost": self.usage.estimated_cost
        }

    def save(self, name: Optional[str] = None) -> str:
        """Save current session to file.

        Args:
            name: Optional session name (uses auto-generated if not provided)

        Returns:
            Session name
        """
        if name:
            self.session_name = name

        filepath = self.sessions_dir / f"{self.session_name}.json"

        session_data = {
            "session_name": self.session_name,
            "metadata": self.metadata,
            "messages": [{"role": m.role, "content": m.content} for m in self.messages],
            "usage": self.get_usage(),
            "saved_at": datetime.now().isoformat()
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
                    message_count=len(data.get("messages", []))
                ))
            except Exception:
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

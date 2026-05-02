"""
Persistent usage storage for ppxai.

Stores usage data across sessions for time-based analytics.
Data is stored in ~/.ppxai/usage/usage.json

v1.12.3: Initial implementation
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict, field
import uuid

from .common.logger import get_logger

logger = get_logger("tui")


@dataclass
class SessionUsageRecord:
    """A single session's usage record for persistent storage."""
    session_id: str
    started_at: str  # ISO format
    ended_at: str  # ISO format
    usage_by_model: Dict[str, Dict[str, Any]]  # "provider/model" -> {prompt_tokens, completion_tokens, estimated_cost}
    total_cost: float
    total_tokens: int
    message_count: int
    tool_calls: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # Tool usage tracking


class UsageStorage:
    """Persistent storage for usage data across sessions.

    Stores usage history in ~/.ppxai/usage/usage.json with the format:
    {
        "version": 1,
        "sessions": [
            {
                "session_id": "abc123",
                "started_at": "2026-01-02T14:30:00Z",
                "ended_at": "2026-01-02T15:45:00Z",
                "usage_by_model": {
                    "perplexity/sonar-pro": {"prompt_tokens": 1143, "completion_tokens": 155, "estimated_cost": 0.0058}
                },
                "total_cost": 0.0058,
                "total_tokens": 1298,
                "message_count": 5
            }
        ]
    }
    """

    STORAGE_VERSION = 1

    def __init__(self, usage_dir: Optional[Path] = None):
        """Initialize usage storage.

        Args:
            usage_dir: Directory for usage files (defaults to ~/.ppxai/usage/)
        """
        if usage_dir is None:
            usage_dir = Path.home() / ".ppxai" / "usage"

        self.usage_dir = Path(usage_dir)
        self.usage_file = self.usage_dir / "usage.json"

        # Ensure directory exists
        self.usage_dir.mkdir(parents=True, exist_ok=True)

        # Load existing data or initialize empty
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load usage data from disk."""
        if self.usage_file.exists():
            try:
                with open(self.usage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Validate version
                    if data.get("version", 0) == self.STORAGE_VERSION:
                        return data
                    # Future: handle version migrations
                    return data
            except (json.JSONDecodeError, IOError) as e:
                logger.debug(f"Failed to load usage data from {self.usage_file}: {e}")

        # Return empty structure
        return {
            "version": self.STORAGE_VERSION,
            "sessions": [],
            "provider_errors": {},
        }

    def _save(self):
        """Save usage data to disk."""
        try:
            with open(self.usage_file, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2)
        except IOError as e:
            # Log but don't crash - usage tracking is non-critical
            logging.getLogger(__name__).warning(f"Failed to save usage data: {e}")

    def save_session_usage(
        self,
        session_id: str,
        started_at: datetime,
        ended_at: datetime,
        usage_by_model: Dict[str, Dict[str, Any]],
        total_cost: float,
        total_tokens: int,
        message_count: int,
        tool_calls: Dict[str, Dict[str, Any]] = None  # Tool usage tracking
    ):
        """Save a session's usage data.

        Called after each chat or when session ends to persist usage data.
        If a session with the same session_id exists, it updates that entry
        instead of creating a duplicate.

        Args:
            session_id: Unique session identifier
            started_at: Session start time
            ended_at: Session end time
            usage_by_model: Dict mapping "provider/model" to usage stats
            total_cost: Total estimated cost
            total_tokens: Total tokens used
            message_count: Number of messages in session
            tool_calls: Dict mapping tool names to usage stats (v1.13.4)
        """
        # Skip if no usage
        if total_tokens == 0 and total_cost == 0.0:
            return

        record = SessionUsageRecord(
            session_id=session_id,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            usage_by_model=usage_by_model,
            total_cost=total_cost,
            total_tokens=total_tokens,
            message_count=message_count,
            tool_calls=tool_calls or {}  # Store tool usage
        )

        # Update existing session or append new one (v1.12.3)
        # This allows auto-save after each chat without creating duplicates
        existing_idx = None
        for idx, session in enumerate(self._data["sessions"]):
            if session.get("session_id") == session_id:
                existing_idx = idx
                break

        if existing_idx is not None:
            self._data["sessions"][existing_idx] = asdict(record)
        else:
            self._data["sessions"].append(asdict(record))

        self._save()

    def get_usage_report(self, period: str = "all") -> Dict[str, Any]:
        """Get aggregated usage report for a time period.

        Args:
            period: One of "24h", "week", "month", "year", "all"

        Returns:
            Dict with aggregated usage stats:
            {
                "period": "week",
                "start_date": "2025-12-26",
                "end_date": "2026-01-02",
                "total_tokens": 15000,
                "total_cost": 0.45,
                "session_count": 12,
                "by_provider": {"perplexity": {...}, "gemini": {...}},
                "by_model": {"perplexity/sonar-pro": {...}, ...},
                "sessions": [...]  # Individual session summaries
            }
        """
        now = datetime.now()

        # Calculate cutoff date based on period
        if period == "24h":
            cutoff = now - timedelta(hours=24)
        elif period == "week":
            cutoff = now - timedelta(days=7)
        elif period == "month":
            cutoff = now - timedelta(days=30)
        elif period == "year":
            cutoff = now - timedelta(days=365)
        else:  # "all"
            cutoff = datetime.min

        # Filter sessions by period
        filtered_sessions = []
        for session in self._data.get("sessions", []):
            try:
                ended_at = datetime.fromisoformat(session["ended_at"].replace('Z', '+00:00').replace('+00:00', ''))
                if ended_at >= cutoff:
                    filtered_sessions.append(session)
            except (ValueError, KeyError):
                continue

        # Aggregate totals
        total_tokens = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = 0.0
        by_provider: Dict[str, Dict[str, Any]] = {}
        by_model: Dict[str, Dict[str, Any]] = {}
        by_tool: Dict[str, Dict[str, Any]] = {}  # Tool usage aggregation

        for session in filtered_sessions:
            total_tokens += session.get("total_tokens", 0)
            total_cost += session.get("total_cost", 0.0)

            for model_key, usage in session.get("usage_by_model", {}).items():
                # Aggregate by model
                if model_key not in by_model:
                    by_model[model_key] = {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "estimated_cost": 0.0,
                        "session_count": 0
                    }
                prompt = usage.get("prompt_tokens", 0)
                completion = usage.get("completion_tokens", 0)
                by_model[model_key]["prompt_tokens"] += prompt
                by_model[model_key]["completion_tokens"] += completion
                by_model[model_key]["total_tokens"] += prompt + completion
                by_model[model_key]["estimated_cost"] += usage.get("estimated_cost", 0.0)
                by_model[model_key]["session_count"] += 1
                total_prompt_tokens += prompt
                total_completion_tokens += completion

                # Aggregate by provider
                provider = model_key.split("/")[0] if "/" in model_key else model_key
                if provider not in by_provider:
                    by_provider[provider] = {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "estimated_cost": 0.0,
                        "session_count": 0
                    }
                by_provider[provider]["prompt_tokens"] += usage.get("prompt_tokens", 0)
                by_provider[provider]["completion_tokens"] += usage.get("completion_tokens", 0)
                by_provider[provider]["total_tokens"] += usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
                by_provider[provider]["estimated_cost"] += usage.get("estimated_cost", 0.0)
                by_provider[provider]["session_count"] += 1

            # Aggregate by tool
            for tool_name, tool_usage in session.get("tool_calls", {}).items():
                if tool_name not in by_tool:
                    by_tool[tool_name] = {
                        "call_count": 0,
                        "tokens_in": 0,
                        "tokens_out": 0,
                        "estimated_cost": 0.0,
                        "provider": tool_usage.get("provider", "unknown")
                    }
                by_tool[tool_name]["call_count"] += tool_usage.get("call_count", 0)
                by_tool[tool_name]["tokens_in"] += tool_usage.get("tokens_in", 0)
                by_tool[tool_name]["tokens_out"] += tool_usage.get("tokens_out", 0)
                by_tool[tool_name]["estimated_cost"] += tool_usage.get("estimated_cost", 0.0)

        # Build session summaries
        session_summaries = [
            {
                "session_id": s.get("session_id", "unknown"),
                "started_at": s.get("started_at"),
                "ended_at": s.get("ended_at"),
                "total_tokens": s.get("total_tokens", 0),
                "total_cost": s.get("total_cost", 0.0),
                "message_count": s.get("message_count", 0)
            }
            for s in sorted(filtered_sessions, key=lambda x: x.get("ended_at", ""), reverse=True)
        ]

        return {
            "period": period,
            "start_date": cutoff.strftime("%Y-%m-%d") if cutoff != datetime.min else None,
            "end_date": now.strftime("%Y-%m-%d"),
            "total_tokens": total_tokens,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_cost": total_cost,
            "estimated_cost": total_cost,  # Alias for web app compatibility
            "session_count": len(filtered_sessions),
            "by_provider": by_provider,
            "by_model": by_model,
            "by_tool": by_tool,  # Tool usage aggregation
            "sessions": session_summaries
        }

    def get_sessions(self, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Get list of recorded sessions.

        Args:
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip

        Returns:
            List of session records (newest first)
        """
        sessions = sorted(
            self._data.get("sessions", []),
            key=lambda x: x.get("ended_at", ""),
            reverse=True
        )
        return sessions[offset:offset + limit]

    def get_session_count(self) -> int:
        """Get total number of recorded sessions."""
        return len(self._data.get("sessions", []))

    def clear_old_sessions(self, days: int = 365):
        """Remove sessions older than specified days.

        Args:
            days: Remove sessions older than this many days
        """
        cutoff = datetime.now() - timedelta(days=days)

        self._data["sessions"] = [
            s for s in self._data.get("sessions", [])
            if datetime.fromisoformat(s.get("ended_at", "").replace('Z', '+00:00').replace('+00:00', '')) >= cutoff
        ]
        self._save()

    def record_provider_error(
        self,
        provider: str,
        status_code: int,
        model: Optional[str] = None,
    ) -> None:
        """Increment a counter for a provider-side error (e.g. 403, 429).

        v1.18.3: surfaces NIM free-tier quota exhaustion (and similar
        provider-side throttle / permission blocks) in the persistent
        usage report so users can see "NVIDIA returned 12 quota errors
        today" without re-running benchmarks.

        Storage shape::

            "provider_errors": {
                "nvidia:403": {
                    "count": 12,
                    "last_seen": "2026-05-02T14:32:00",
                    "models": ["qwen/qwen3-coder-480b-a35b-instruct"]
                }
            }

        Non-critical: failures to persist are logged at DEBUG level and
        ignored — telemetry must not break chat. Best-effort save on
        every record so the data survives crashes.
        """
        # Defensive: if storage was loaded from a pre-v1.18.3 file, the
        # key may be missing.
        errors = self._data.setdefault("provider_errors", {})
        key = f"{provider}:{status_code}"
        entry = errors.setdefault(key, {"count": 0, "last_seen": None, "models": []})
        entry["count"] += 1
        entry["last_seen"] = datetime.now().isoformat()
        if model and model not in entry["models"]:
            entry["models"].append(model)
        try:
            self._save()
        except Exception as e:
            logger.debug(f"record_provider_error failed to persist: {e}")

    def get_provider_errors(self) -> Dict[str, Dict[str, Any]]:
        """Return the provider_errors counter dict (read-only view)."""
        return dict(self._data.get("provider_errors", {}))


# Module-level singleton for convenience
_storage: Optional[UsageStorage] = None


def get_usage_storage() -> UsageStorage:
    """Get the global usage storage instance."""
    global _storage
    if _storage is None:
        _storage = UsageStorage()
    return _storage


def save_session_usage(
    session_id: str,
    started_at: datetime,
    ended_at: datetime,
    usage_by_model: Dict[str, Dict[str, Any]],
    total_cost: float,
    total_tokens: int,
    message_count: int,
    tool_calls: Dict[str, Dict[str, Any]] = None
):
    """Convenience function to save session usage."""
    get_usage_storage().save_session_usage(
        session_id=session_id,
        started_at=started_at,
        ended_at=ended_at,
        usage_by_model=usage_by_model,
        total_cost=total_cost,
        total_tokens=total_tokens,
        message_count=message_count,
        tool_calls=tool_calls,
    )


def record_provider_error(
    provider: str,
    status_code: int,
    model: Optional[str] = None,
) -> None:
    """Module-level convenience: record a provider-side error (403/429)."""
    try:
        get_usage_storage().record_provider_error(provider, status_code, model)
    except Exception as e:  # noqa: BLE001 — telemetry must not break chat
        logger.debug(f"record_provider_error noop: {e}")


def get_provider_errors() -> Dict[str, Dict[str, Any]]:
    """Module-level convenience: read provider_errors counter dict."""
    try:
        return get_usage_storage().get_provider_errors()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"get_provider_errors noop: {e}")
        return {}


def get_usage_report(period: str = "all") -> Dict[str, Any]:
    """Convenience function to get usage report."""
    return get_usage_storage().get_usage_report(period)

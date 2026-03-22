"""
AppState — canonical observable application state for ppxai.

All mutable application state lives here. Provides:
- No-op deduplication on writes (skip if value unchanged)
- Observer pattern: subscribe to individual field changes
- Thread-safe: RLock protects reads/writes and listener dispatch
- Batch updates: set multiple fields atomically, fire listeners once

This is the Python canonical implementation. The same field names and
semantics must be used in:
- ppxai/web/shared/app-state.js (JavaScript, Proxy-based)
- vscode-extension/src/appState.ts (TypeScript, to be created)

Usage:
    state = AppState()
    state.on("provider", lambda v: print(f"Provider: {v}"))
    state.set("provider", "perplexity")  # triggers listener
    state.set("provider", "perplexity")  # no-op (same value)
    state.get("provider")                # "perplexity"

    # Batch update (listeners fire after all fields set):
    state.update(provider="openai", model="gpt-4.1-mini")
"""

import threading
from typing import Any, Callable, Dict, List, Optional


# Type alias for listener callbacks: fn(new_value) -> None
Listener = Callable[[Any], None]


class AppState:
    """Centralized observable application state.

    Thread-safe. All field access goes through get()/set() which
    hold the lock and dispatch listeners synchronously.

    Fields are divided into:
    - Core: provider, model, working directory, session identity
    - Features: tools, agent mode, auto-route, verbose
    - Streaming: is_streaming, cancel_requested
    - Usage: token counts, cost, context percentage
    """

    # Canonical field definitions with types and defaults.
    # This is the single source of truth for all clients.
    #
    # Cross-language naming convention:
    #   Python: snake_case  (provider, tools_enabled, is_streaming)
    #   JS/TS:  camelCase   (provider, toolsEnabled, isStreaming)
    #
    # The semantic fields are identical — only casing differs per language
    # convention. The v1.18.x schema generator will auto-convert.
    FIELDS: Dict[str, Any] = {
        # --- Core identity ---
        "provider": "",                # Current provider name (e.g., "perplexity")
        "model": "",                   # Current model ID (e.g., "sonar-pro")
        "working_dir": "",             # Current working directory path
        "session_id": "",              # Session identifier
        "session_name": "",            # Human-readable session name

        # --- Feature toggles ---
        "tools_enabled": False,        # AI tools available
        "tools_verbose": False,        # Show detailed tool output
        "agent_mode": False,           # Autonomous task execution
        "auto_route": False,           # Auto-route coding tasks to coding model

        # --- Streaming / flow control ---
        "is_streaming": False,         # Response stream in progress
        "cancel_requested": False,     # User requested stream cancellation

        # --- Usage statistics ---
        "total_tokens": 0,             # Total tokens (prompt + completion)
        "prompt_tokens": 0,            # Prompt/input tokens
        "completion_tokens": 0,        # Completion/output tokens
        "total_cost": 0.0,            # Cumulative cost in USD
        "context_percentage": 0.0,     # Context window usage (0.0-100.0)

        # --- Debug ---
        "debug_log": False,            # Debug logging enabled
    }

    def __init__(self, initial: Optional[Dict[str, Any]] = None) -> None:
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = dict(self.FIELDS)
        self._listeners: Dict[str, List[Listener]] = {}

        if initial:
            for key, value in initial.items():
                if key in self._data:
                    self._data[key] = value

    def get(self, key: str) -> Any:
        """Get a state field value. Returns default if key unknown."""
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value: Any) -> bool:
        """Set a state field value. Returns True if value changed.

        No-op if value is identical (prevents redundant listener calls).
        Listeners are called synchronously under the lock.
        """
        with self._lock:
            if key not in self._data:
                return False
            old = self._data[key]
            if old == value:
                return False
            self._data[key] = value
            self._dispatch(key, value)
            return True

    def update(self, **kwargs: Any) -> None:
        """Set multiple fields atomically. Listeners fire after all fields are set.

        Usage: state.update(provider="openai", model="gpt-4.1-mini")
        """
        with self._lock:
            changed: List[tuple] = []
            for key, value in kwargs.items():
                if key not in self._data:
                    continue
                if self._data[key] != value:
                    self._data[key] = value
                    changed.append((key, value))
            # Dispatch after all mutations complete
            for key, value in changed:
                self._dispatch(key, value)

    def on(self, key: str, fn: Listener) -> "AppState":
        """Subscribe to changes on a field. Returns self for chaining.

        The callback receives the new value: fn(new_value).
        Called synchronously when set() changes the value.
        """
        with self._lock:
            if key not in self._listeners:
                self._listeners[key] = []
            self._listeners[key].append(fn)
        return self

    def off(self, key: str, fn: Listener) -> "AppState":
        """Unsubscribe a listener. Returns self for chaining."""
        with self._lock:
            fns = self._listeners.get(key)
            if fns and fn in fns:
                fns.remove(fn)
        return self

    def snapshot(self) -> Dict[str, Any]:
        """Return a plain dict copy of current state (for debugging/serialization)."""
        with self._lock:
            return dict(self._data)

    def _dispatch(self, key: str, value: Any) -> None:
        """Notify listeners for a field. Called under lock."""
        fns = self._listeners.get(key)
        if not fns:
            return
        for fn in fns:
            fn(value)

"""
AppState — canonical observable application state for ppxai.

All mutable application state lives here. Provides:
- No-op deduplication on writes (skip if value unchanged)
- Observer pattern: subscribe to individual field changes
- Thread-safe: Lock protects data, listeners dispatched OUTSIDE the lock
- Batch updates: set multiple fields atomically, fire listeners once

This is the Python canonical implementation. The **same JSON schema**
file (`ppxai/engine/app_state_schema.json`) is loaded by:
- ppxai/engine/app_state.py    — this file, at module import
- ppxai/web/shared/app-state.js — via `window.APP_STATE_SCHEMA`
                                   injected into index.html by the
                                   FastAPI static-file route
- vscode-extension/src/appState.ts — via a bundled copy at
                                   vscode-extension/resources/
                                   app-state-schema.json (kept in sync
                                   by the pre-compile script)

The schema file is the **golden source of truth**. The server exposes
it at `GET /schema/app-state` so any client (including diagnostic
tooling) can fetch it at runtime.

Usage:
    state = AppState()
    state.on("provider", lambda v: print(f"Provider: {v}"))
    state.set("provider", "perplexity")  # triggers listener
    state.set("provider", "perplexity")  # no-op (same value)
    state.get("provider")                # "perplexity"

    # Batch update (listeners fire after all fields set):
    state.update(provider="openai", model="gpt-4.1-mini")

Thread-safety design:
- Lock protects _data and _listeners mutations only
- Listener callbacks execute OUTSIDE the lock to prevent:
  (a) Deadlock if a listener calls state.set() on another field
  (b) Blocking other threads waiting to read state while a slow listener runs
  (c) Priority inversion where a high-priority reader waits on a listener
- Listeners see a consistent snapshot: the value passed is the committed value
- Listener list is copied before dispatch to allow on()/off() during iteration
"""

import json
import logging
import threading
from importlib.resources import files
from typing import Any, Callable, Dict, List, Mapping, Optional

_logger = logging.getLogger(__name__)


# Type alias for listener callbacks: fn(new_value) -> None
Listener = Callable[[Any], None]


def _load_schema() -> Dict[str, Any]:
    """Load the canonical AppState schema from the package resources.

    The JSON file ships inside the `ppxai.engine` package so it is
    available at runtime regardless of how ppxai was installed (pip,
    editable, PyInstaller frozen bundle). `importlib.resources.files`
    handles all three cases uniformly.

    Structure (see `app_state_schema.json` for the full spec):

        {
          "version": "1.0",
          "description": "...",
          "fields": {
            "<python_name>": {
              "client": "<camelCase>",
              "type": "string|boolean|integer|number|array",
              "default": <JSON-compatible default>,
              "group": "core|features|streaming|usage|multimodal|debug",
              "doc": "..."
            },
            ...
          }
        }
    """
    resource = files("ppxai.engine").joinpath("app_state_schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


# Loaded once at module import. Immutable from Python's perspective;
# tests and the server route hand this directly to consumers.
SCHEMA: Dict[str, Any] = _load_schema()


def _default_for(field_spec: Mapping[str, Any]) -> Any:
    """Return a mutable copy of a field's default value.

    Containers (lists, dicts) must be copied on access so two AppState
    instances don't share the same underlying object — otherwise a
    mutation on one instance's `context_attachments` would leak into
    the other.
    """
    default = field_spec["default"]
    if isinstance(default, list):
        return list(default)
    if isinstance(default, dict):
        return dict(default)
    return default


def _build_fields(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Derive the flat {python_name: default_value} FIELDS dict from
    the schema. Preserves insertion order (Python 3.7+ dict ordering)
    so the documented grouping in the schema JSON carries through."""
    return {
        name: _default_for(spec)
        for name, spec in schema["fields"].items()
    }


class AppState:
    """Centralized observable application state.

    Thread-safe. Reads and writes are serialized via Lock.
    Listener callbacks are dispatched outside the lock.

    Schema is loaded from `app_state_schema.json` at module import.
    `FIELDS` is a derived dict of {python_name: default_value} kept
    for backward compatibility with call sites that iterate it.
    """

    # Raw schema (for the server endpoint, tests, and diagnostic tools).
    SCHEMA: Dict[str, Any] = SCHEMA

    # Flat {python_name: default_value} map — derived from SCHEMA.
    # Callers that iterate FIELDS (tests, EngineClient, etc.) keep
    # working unchanged. Mutation-safe containers are copied on init.
    FIELDS: Dict[str, Any] = _build_fields(SCHEMA)

    def __init__(self, initial: Optional[Dict[str, Any]] = None) -> None:
        self._lock = threading.Lock()
        # Start from a per-instance copy of the schema defaults so
        # mutable defaults (lists, dicts) are not shared between
        # AppState instances.
        self._data: Dict[str, Any] = {
            name: _default_for(spec)
            for name, spec in self.SCHEMA["fields"].items()
        }
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
        Listeners are called OUTSIDE the lock.
        """
        with self._lock:
            if key not in self._data:
                return False
            old = self._data[key]
            if old == value:
                return False
            self._data[key] = value
            pending = list(self._listeners.get(key, []))

        # Dispatch outside lock — prevents deadlock and lock contention.
        # Listener isolation: one bad listener MUST NOT wedge the chain.
        # Widgets wired through AppState across four clients can crash
        # for reasons unrelated to the data; swallowing + logging matches
        # SessionManager.on_messages_changed semantics.
        for fn in pending:
            try:
                fn(value)
            except Exception:
                _logger.warning(
                    "AppState listener for %r raised; continuing", key,
                    exc_info=True,
                )
        return True

    def update(self, **kwargs: Any) -> None:
        """Set multiple fields atomically. Listeners fire after all fields are set.

        Usage: state.update(provider="openai", model="gpt-4.1-mini")
        """
        with self._lock:
            pending: List[tuple] = []
            for key, value in kwargs.items():
                if key not in self._data:
                    continue
                if self._data[key] != value:
                    self._data[key] = value
                    fns = list(self._listeners.get(key, []))
                    if fns:
                        pending.append((fns, value))

        # Dispatch outside lock — same listener-isolation policy as set().
        for fns, value in pending:
            for fn in fns:
                try:
                    fn(value)
                except Exception:
                    _logger.warning(
                        "AppState listener raised during update(); continuing",
                        exc_info=True,
                    )

    def on(self, key: str, fn: Listener) -> "AppState":
        """Subscribe to changes on a field. Returns self for chaining.

        The callback receives the new value: fn(new_value).
        Called synchronously after set() changes the value (outside lock).
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

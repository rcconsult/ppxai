"""
Event bus for decoupled component communication in ppxaide.

Uses blinker library for publish/subscribe pattern, enabling:
- EngineClient → EventBus → UI handlers (one-way data flow)
- Event logging for debugging visibility
- Thread-safe communication (prepares for embedded server)
- Testability (mock event bus in tests)

Architecture:
    EngineClient emits events → EventBus → Multiple UI handlers

    Instead of:
        EngineClient → _handle_event() → if/elif chain

    Now:
        EngineClient → bus.emit("stream_chunk") → _on_stream_chunk()
                                                 → _on_log_chunk()
                                                 → _update_status()

Usage:
    # Subscribe to events
    bus = EventBus(log_events=True)
    bus.on(Events.ENGINE_STREAM_CHUNK, self._on_stream_chunk)
    bus.on(Events.ENGINE_CONSENT_FILE, self._on_consent_file_request)

    # Emit events
    bus.emit(Events.ENGINE_STREAM_CHUNK, data="Hello", delta=5)

    # Unsubscribe
    unsubscribe = bus.on(Events.ENGINE_ERROR, handler)
    unsubscribe()  # Remove handler
"""

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

from blinker import Signal

logger = logging.getLogger(__name__)


class EventBus:
    """
    Event bus using blinker library for pub/sub pattern.

    Thread-safe, supports async handlers, logs all events for debugging.
    """

    def __init__(self, log_events: bool = True):
        """
        Initialize event bus.

        Args:
            log_events: Enable debug logging for all events (useful for debugging)
        """
        self._signals: Dict[str, Signal] = {}
        self._log_events = log_events

    def signal(self, name: str) -> Signal:
        """Get or create signal for event name."""
        if name not in self._signals:
            self._signals[name] = Signal(name)
        return self._signals[name]

    def on(self, event: str, handler: Callable) -> Callable:
        """
        Subscribe to event.

        Args:
            event: Event name (e.g., "engine:chunk")
            handler: Handler function (sync or async)

        Returns:
            Unsubscribe function
        """
        signal = self.signal(event)
        signal.connect(handler, weak=False)  # Don't use weak refs (can cause bugs)

        if self._log_events:
            logger.debug(f"[EventBus] Subscribed to '{event}': {handler.__name__}")

        # Return unsubscribe function
        def unsubscribe():
            signal.disconnect(handler)
            if self._log_events:
                logger.debug(f"[EventBus] Unsubscribed from '{event}': {handler.__name__}")

        return unsubscribe

    def emit(self, event: str, **kwargs):
        """
        Emit event to all subscribers.

        Handlers are called based on their type:
        - Async handlers: scheduled as tasks
        - Sync handlers: called immediately

        Errors in handlers are logged but don't stop other handlers.

        Args:
            event: Event name
            **kwargs: Arguments passed to handlers
        """
        if self._log_events:
            # Log event with abbreviated data
            data_preview = self._preview_data(kwargs)
            logger.debug(f"[EventBus] Emit '{event}': {data_preview}")

        signal = self.signal(event)

        # Get all receivers for this signal
        receivers = list(signal.receivers_for(None))

        if not receivers:
            if self._log_events:
                logger.debug(f"[EventBus] No handlers for '{event}'")
            return

        # Call each handler
        for receiver in receivers:
            try:
                if asyncio.iscoroutinefunction(receiver):
                    # Schedule async handler as task (if event loop running)
                    try:
                        loop = asyncio.get_running_loop()
                        asyncio.create_task(
                            self._handle_async(event, receiver, kwargs)
                        )
                    except RuntimeError:
                        # No event loop running - this is expected outside Textual app
                        # In Textual app, there's always an event loop
                        if self._log_events:
                            logger.debug(f"[EventBus] No event loop for async handler '{receiver.__name__}', skipping")
                else:
                    # Call sync handler immediately
                    receiver(sender=self, **kwargs)

            except Exception as e:
                logger.error(f"[EventBus] Error in handler for '{event}': {e}", exc_info=True)

    async def _handle_async(self, event: str, handler: Callable, kwargs: Dict[str, Any]):
        """Handle async event handler with error catching."""
        try:
            await handler(sender=self, **kwargs)
        except Exception as e:
            logger.error(f"[EventBus] Async handler error for '{event}': {e}", exc_info=True)

    def _preview_data(self, kwargs: Dict[str, Any]) -> str:
        """Create abbreviated preview of event data for logging."""
        if not kwargs:
            return "{}"

        preview_parts = []
        for key, value in kwargs.items():
            if isinstance(value, str):
                if len(value) > 50:
                    preview_parts.append(f"{key}='{value[:50]}...'")
                else:
                    preview_parts.append(f"{key}='{value}'")
            elif isinstance(value, dict):
                preview_parts.append(f"{key}={{{len(value)} keys}}")
            elif isinstance(value, list):
                preview_parts.append(f"{key}=[{len(value)} items]")
            else:
                preview_parts.append(f"{key}={type(value).__name__}")

        return ", ".join(preview_parts)

    def clear(self, event: Optional[str] = None):
        """
        Clear handlers.

        Args:
            event: Clear specific event, or all if None
        """
        if event:
            self._signals.pop(event, None)
            if self._log_events:
                logger.debug(f"[EventBus] Cleared handlers for '{event}'")
        else:
            self._signals.clear()
            if self._log_events:
                logger.debug("[EventBus] Cleared all handlers")


# Event name constants (type-safe)
class Events:
    """Event name constants for type safety and IDE autocomplete."""

    # Engine events (from EngineClient)
    ENGINE_STREAM_START = "engine:stream_start"
    ENGINE_STREAM_CHUNK = "engine:stream_chunk"
    ENGINE_REASONING_CHUNK = "engine:reasoning_chunk"  # DeepSeek R1, GPT-OSS thinking
    ENGINE_STREAM_END = "engine:stream_end"
    ENGINE_ERROR = "engine:error"
    ENGINE_WARNING = "engine:warning"  # Validation warnings (v1.15.3)
    ENGINE_INFO = "engine:info"
    ENGINE_TOOL_CALL = "engine:tool_call"
    ENGINE_TOOL_RESULT = "engine:tool_result"
    ENGINE_TOOL_ERROR = "engine:tool_error"
    ENGINE_TOOL_GROUP_START = "engine:tool_group_start"  # v1.16.0
    ENGINE_TOOL_GROUP_END = "engine:tool_group_end"  # v1.16.0
    ENGINE_CONTEXT_INJECTED = "engine:context_injected"
    ENGINE_CONSENT_FILE = "engine:consent_file"
    ENGINE_CONSENT_SHELL = "engine:consent_shell"
    ENGINE_WORKING_DIR_CHANGED = "engine:working_dir_changed"
    ENGINE_DISPLAY_FILE = "engine:display_file"  # Display file in viewer (v1.15.1)

    # Consent responses (from UI)
    CONSENT_FILE_RESPONSE = "consent:file_response"
    CONSENT_SHELL_RESPONSE = "consent:shell_response"

    # UI events
    UI_CLEAR = "ui:clear"
    UI_STATUS_UPDATE = "ui:status_update"
    UI_THEME_CHANGED = "ui:theme_changed"
    UI_DIRECTORY_LISTED = "ui:directory_listed"
    UI_TREE_LOADED = "ui:tree_loaded"

    # Session events
    SESSION_LOADED = "session:loaded"
    SESSION_SAVED = "session:saved"
    SESSION_CLEARED = "session:cleared"

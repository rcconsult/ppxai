"""
Command Context Adapters - Bridge UI Frameworks to CommandContext Protocol

Thin adapters that delegate to public methods on the wrapped client.
Each client owns its full-stack logic; adapters only translate
protocol calls.

Architecture (two patterns coexist by design):

- **Pattern A — proxy-via-__getattr__** (`_CommandContextProxy`):
  the wrapped class implements the full CommandContext protocol;
  the proxy forwards attribute access. Used by:
    - `RichCommandContext` wrapping `CommandHandler` (Rich TUI).
  CommandHandler implements the protocol via property/method
  definitions; the proxy adds `get_config_value` /
  `set_config_value` overrides that fall back when the wrapped
  class doesn't define them.

- **Pattern B — explicit implementation against the engine**:
  the adapter holds a reference to the engine and implements every
  CommandContext member directly against it. Used by:
    - `ServerCommandContext` wrapping `EngineClientProtocol`
      (HTTP server). No wrapped UI object — server commands have
      no Rich/Textual context.

The Textual TUI uses neither adapter — `PPXAIDEApp` implements the
CommandContext protocol directly and is passed to commands as the
context (see `tui/app.py::_handle_command`). A `TextualCommandContext`
wrapper would be Pattern A; it was tracked here as dead code from
v1.17.1 → v1.18.2 and removed on 2026-04-29 (Item 1 narrowing).
If a future Textual variant needs an adapter, restore it as
Pattern A or add an explicit Pattern B class — the docstring above
shows both shapes.

v1.15.0: Type-based renderer dispatch refactoring
v1.16.1: Cleaned up to use only public interfaces (DAG compliance)
v1.17.1: Replaced boilerplate forwarding with __getattr__ proxy
v1.18.2: Removed unused `TextualCommandContext` (Item 1 narrowing).
"""

from typing import Any, Optional

from ..engine.types import EngineClientProtocol


class _CommandContextProxy:
    """Generic proxy that forwards attribute access to the wrapped object.

    Used by RichCommandContext (Pattern A) to eliminate ~80 lines of
    identical property/method forwarding boilerplate. The wrapped
    object must itself implement the CommandContext protocol.

    Overrides get_config_value/set_config_value with hasattr guards
    so callers can use these on wrapped objects that don't define
    them (e.g. an early CommandHandler before config plumbing).
    """

    def __init__(self, wrapped: Any):
        # Use object.__setattr__ to avoid triggering __getattr__
        object.__setattr__(self, '_wrapped', wrapped)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)

    def get_config_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        wrapped = object.__getattribute__(self, '_wrapped')
        if hasattr(wrapped, 'get_config_value'):
            return wrapped.get_config_value(key, default)
        if hasattr(wrapped, 'config'):
            return wrapped.config.get(key, default)
        return default

    def set_config_value(self, key: str, value: str) -> None:
        wrapped = object.__getattribute__(self, '_wrapped')
        if hasattr(wrapped, 'set_config_value'):
            wrapped.set_config_value(key, value)
        elif hasattr(wrapped, 'config'):
            wrapped.config[key] = value


class RichCommandContext(_CommandContextProxy):
    """CommandContext adapter for Rich TUI. Wraps CommandHandler."""
    pass


class ServerCommandContext:
    """CommandContext adapter for HTTP server.

    Wraps an engine satisfying `EngineClientProtocol` — reads state from
    AppState for consistency with TUI clients. Server-specific overrides:
    no auto-route, no verbose, no config values. Typed against the
    Protocol (not the concrete `EngineClient`) so the
    commands→engine boundary stays nominally decoupled (Item 10, v1.18.2).
    """

    def __init__(self, engine: EngineClientProtocol):
        self._engine = engine

    @property
    def engine_client(self) -> Any:
        return self._engine

    @property
    def session(self) -> Any:
        return self._engine.session

    @property
    def working_dir(self) -> str:
        return self._engine.state.get("working_dir") or ""

    @property
    def current_model(self) -> str:
        return self._engine.state.get("model") or ""

    @property
    def provider(self) -> str:
        return self._engine.state.get("provider") or ""

    @property
    def tools_enabled(self) -> bool:
        return self._engine.state.get("tools_enabled")

    @property
    def autoroute_enabled(self) -> bool:
        return False

    def set_model(self, model: str) -> None:
        self._engine.set_model(model)

    def set_provider(self, provider: str) -> None:
        self._engine.set_provider(provider)

    def get_provider(self) -> str:
        return self._engine.state.get("provider") or ""

    def get_model(self) -> str:
        return self._engine.state.get("model") or ""

    def get_auto_route(self) -> bool:
        return False

    def set_auto_route(self, enabled: bool) -> None:
        pass

    def get_tools_available(self) -> bool:
        return self._engine.state.get("tools_enabled")

    def get_tools_verbose(self) -> bool:
        return False

    def set_tools_verbose(self, verbose: bool) -> None:
        pass

    def get_config_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return default

    def set_config_value(self, key: str, value: str) -> None:
        pass


__all__ = [
    "RichCommandContext",
    "ServerCommandContext",
]

"""
Command Context Adapters - Bridge UI Frameworks to CommandContext Protocol

Thin adapters that delegate to public methods on the wrapped client.
Each client (CommandHandler for Rich, PPXAIDEApp for Textual) owns
its full-stack logic; adapters only translate protocol calls.

Architecture:
- RichCommandContext wraps CommandHandler (Rich TUI)
- TextualCommandContext wraps PPXAIDEApp (Textual TUI)
- ServerCommandContext wraps EngineClient (HTTP server)
- All implement CommandContext protocol

v1.15.0: Type-based renderer dispatch refactoring
v1.16.1: Cleaned up to use only public interfaces (DAG compliance)
v1.17.1: Replaced boilerplate forwarding with __getattr__ proxy
"""

from typing import Any, Optional

from ..engine.client import EngineClient


class _CommandContextProxy:
    """Generic proxy that forwards attribute access to the wrapped object.

    Used by RichCommandContext and TextualCommandContext to eliminate
    ~80 lines of identical property/method forwarding boilerplate.
    The wrapped object must satisfy the CommandContext protocol directly.

    Overrides get_config_value/set_config_value with hasattr guards.
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


class TextualCommandContext(_CommandContextProxy):
    """CommandContext adapter for Textual TUI. Wraps PPXAIDEApp."""
    pass


class ServerCommandContext:
    """CommandContext adapter for HTTP server.

    Wraps EngineClient directly — has custom overrides for server context
    (no auto-route, no verbose, no config values).
    """

    def __init__(self, engine: EngineClient):
        self._engine = engine

    @property
    def engine_client(self) -> Any:
        return self._engine

    @property
    def session(self) -> Any:
        return self._engine.session

    @property
    def working_dir(self) -> str:
        return self._engine.get_working_dir() or ""

    @property
    def current_model(self) -> str:
        return self._engine.get_current_model() or ""

    @property
    def provider(self) -> str:
        return self._engine.get_current_provider() or ""

    @property
    def tools_enabled(self) -> bool:
        return self._engine.tools_enabled

    @property
    def autoroute_enabled(self) -> bool:
        return False

    def set_model(self, model: str) -> None:
        self._engine.set_model(model)

    def set_provider(self, provider: str) -> None:
        self._engine.set_provider(provider)

    def get_provider(self) -> str:
        return self._engine.get_current_provider() or ""

    def get_model(self) -> str:
        return self._engine.get_current_model() or ""

    def get_auto_route(self) -> bool:
        return False

    def set_auto_route(self, enabled: bool) -> None:
        pass

    def get_tools_available(self) -> bool:
        return self._engine.tools_enabled

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
    "TextualCommandContext",
    "ServerCommandContext",
]

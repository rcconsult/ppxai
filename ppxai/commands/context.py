"""
Command Context Adapters - Bridge UI Frameworks to CommandContext Protocol

Thin adapters that delegate to public methods on the wrapped client.
Each client (CommandHandler for Rich, PPXAIDEApp for Textual) owns
its full-stack logic; adapters only translate protocol calls.

Architecture:
- RichCommandContext wraps CommandHandler (Rich TUI)
- TextualCommandContext wraps PPXAIDEApp (Textual TUI)
- Both implement CommandContext protocol
- Adapters use ONLY public methods/properties on the wrapped object

v1.15.0: Type-based renderer dispatch refactoring
v1.16.1: Cleaned up to use only public interfaces (DAG compliance)
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..commands.handler import CommandHandler as RichHandler
    from ..tui.app import PPXAIDEApp
    from ..engine.client import EngineClient
    from ..engine.session import Session


class RichCommandContext:
    """CommandContext adapter for Rich TUI.

    Wraps CommandHandler, delegating to its public interface.
    """

    def __init__(self, handler: "RichHandler"):
        self._handler = handler

    # -- Properties (read public attributes) --

    @property
    def engine_client(self) -> "EngineClient":
        return self._handler.engine_client

    @property
    def session(self) -> "Session":
        return self._handler.session

    @property
    def working_dir(self) -> str:
        return self._handler.working_dir

    @property
    def current_model(self) -> str:
        return self._handler.current_model

    @property
    def provider(self) -> str:
        return self._handler.provider

    @property
    def tools_enabled(self) -> bool:
        return self._handler.tools_enabled

    @property
    def autoroute_enabled(self) -> bool:
        return self._handler.autoroute_enabled

    # -- Mutations (delegate to public methods) --

    def set_model(self, model: str) -> None:
        self._handler.switch_model(model)

    def set_provider(self, provider: str) -> None:
        self._handler.switch_provider(provider)

    def get_provider(self) -> str:
        return self._handler.provider

    def get_model(self) -> str:
        return self._handler.current_model

    def get_auto_route(self) -> bool:
        return self._handler.auto_route

    def set_auto_route(self, enabled: bool) -> None:
        self._handler.auto_route = enabled

    def get_tools_available(self) -> bool:
        return self._handler.tools_available

    def get_tools_verbose(self) -> bool:
        return self._handler.tools_verbose

    def set_tools_verbose(self, verbose: bool) -> None:
        self._handler.tools_verbose = verbose

    def get_config_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        if hasattr(self._handler, 'config'):
            return self._handler.config.get(key, default)
        return default

    def set_config_value(self, key: str, value: str) -> None:
        if hasattr(self._handler, 'config'):
            self._handler.config[key] = value


class TextualCommandContext:
    """CommandContext adapter for Textual TUI.

    Wraps PPXAIDEApp, delegating to its public interface.
    PPXAIDEApp implements CommandContext protocol methods directly.
    """

    def __init__(self, app: "PPXAIDEApp"):
        self._app = app

    # -- Properties (delegate to public properties on PPXAIDEApp) --

    @property
    def engine_client(self) -> "EngineClient":
        return self._app.engine_client

    @property
    def session(self) -> "Session":
        return self._app.session

    @property
    def working_dir(self) -> str:
        return self._app.working_dir

    @property
    def current_model(self) -> str:
        return self._app.current_model

    @property
    def provider(self) -> str:
        return self._app.provider

    @property
    def tools_enabled(self) -> bool:
        return self._app.tools_enabled

    @property
    def autoroute_enabled(self) -> bool:
        return self._app.autoroute_enabled

    # -- Mutations (delegate to public methods on PPXAIDEApp) --

    def set_model(self, model: str) -> None:
        self._app.set_model(model)

    def set_provider(self, provider: str) -> None:
        self._app.set_provider(provider)

    def get_provider(self) -> str:
        return self._app.get_provider()

    def get_model(self) -> str:
        return self._app.get_model()

    def get_auto_route(self) -> bool:
        return self._app.get_auto_route()

    def set_auto_route(self, enabled: bool) -> None:
        self._app.set_auto_route(enabled)

    def get_tools_available(self) -> bool:
        return self._app.get_tools_available()

    def get_tools_verbose(self) -> bool:
        return self._app.get_tools_verbose()

    def set_tools_verbose(self, verbose: bool) -> None:
        self._app.set_tools_verbose(verbose)

    def get_config_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        if hasattr(self._app, 'get_config_value'):
            return self._app.get_config_value(key, default)
        return default

    def set_config_value(self, key: str, value: str) -> None:
        if hasattr(self._app, 'set_config_value'):
            self._app.set_config_value(key, value)


# Export context adapters
__all__ = [
    "RichCommandContext",
    "TextualCommandContext",
]

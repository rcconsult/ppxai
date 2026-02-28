"""
Command Context Adapters - Bridge UI Frameworks to CommandContext Protocol

This module provides concrete implementations of CommandContext protocol
for different UI frameworks (Rich TUI, Textual TUI).

Architecture:
- RichCommandContext wraps CommandHandler (Rich TUI)
- TextualCommandContext wraps PPXAIDEApp (Textual TUI)
- Both implement CommandContext protocol
- Commands remain UI-agnostic

v1.15.0: Type-based renderer dispatch refactoring
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..commands.handler import CommandHandler as RichHandler
    from ..tui.app import PPXAIDEApp
    from ..engine.client import EngineClient
    from ..engine.session import Session


class RichCommandContext:
    """CommandContext adapter for Rich TUI.

    Wraps the existing CommandHandler to provide CommandContext protocol.

    Example:
        handler = CommandHandler(...)
        context = RichCommandContext(handler)
        result = handle_save(context, "my-session")
    """

    def __init__(self, handler: "RichHandler"):
        """Initialize Rich command context.

        Args:
            handler: Rich TUI CommandHandler instance
        """
        self._handler = handler

    @property
    def engine_client(self) -> "EngineClient":
        """Access to engine client."""
        return self._handler.engine_client

    @property
    def session(self) -> "Session":
        """Access to current session."""
        return self._handler.engine_client.session

    @property
    def working_dir(self) -> str:
        """Current working directory."""
        return self._handler.working_dir

    @property
    def current_model(self) -> str:
        """Currently selected model."""
        return self._handler.current_model

    @property
    def provider(self) -> str:
        """Currently selected provider."""
        return self._handler.provider

    @property
    def tools_enabled(self) -> bool:
        """Check if tools are enabled."""
        return getattr(self._handler, 'tools_enabled', False)

    @property
    def autoroute_enabled(self) -> bool:
        """Check if auto-routing is enabled."""
        return getattr(self._handler, 'autoroute_enabled', False)

    def set_model(self, model: str) -> None:
        """Switch to specified model (updates both UI state and engine)."""
        self._handler.current_model = model
        self._handler.engine_client.set_model(model)

    def set_provider(self, provider: str) -> None:
        """Switch to specified provider (updates both UI state and engine)."""
        self._handler.provider = provider
        self._handler.engine_client.set_provider(provider)

    def get_provider(self) -> str:
        """Get currently selected provider."""
        return self._handler.provider

    def get_model(self) -> str:
        """Get currently selected model."""
        return self._handler.current_model

    def get_auto_route(self) -> bool:
        """Get auto-routing status."""
        return getattr(self._handler, 'auto_route', False)

    def set_auto_route(self, enabled: bool) -> None:
        """Set auto-routing status."""
        self._handler.auto_route = enabled

    def get_tools_available(self) -> bool:
        """Check if tool support is available."""
        return getattr(self._handler, 'tools_available', False)

    def get_tools_verbose(self) -> bool:
        """Get tool verbose logging status."""
        return getattr(self._handler, 'tools_verbose', False)

    def set_tools_verbose(self, verbose: bool) -> None:
        """Set tool verbose logging status."""
        self._handler.tools_verbose = verbose

    def get_config_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get configuration value.

        Args:
            key: Configuration key
            default: Default value

        Returns:
            Configuration value or default
        """
        if hasattr(self._handler, 'config'):
            return self._handler.config.get(key, default)
        return default

    def set_config_value(self, key: str, value: str) -> None:
        """Set configuration value.

        Args:
            key: Configuration key
            value: Value to set
        """
        if hasattr(self._handler, 'config'):
            self._handler.config[key] = value


class TextualCommandContext:
    """CommandContext adapter for Textual TUI.

    Wraps the PPXAIDEApp to provide CommandContext protocol.

    Example:
        app = PPXAIDEApp()
        context = TextualCommandContext(app)
        result = handle_save(context, "my-session")
    """

    def __init__(self, app: "PPXAIDEApp"):
        """Initialize Textual command context.

        Args:
            app: Textual PPXAIDEApp instance
        """
        self._app = app

    @property
    def engine_client(self) -> "EngineClient":
        """Access to engine client."""
        return self._app._engine_client

    @property
    def session(self) -> "Session":
        """Access to current session."""
        return self._app._engine_client.session

    @property
    def working_dir(self) -> str:
        """Current working directory."""
        return self._app._working_dir or ""

    @property
    def current_model(self) -> str:
        """Currently selected model."""
        return self._app._model

    @property
    def provider(self) -> str:
        """Currently selected provider."""
        return self._app._provider

    @property
    def tools_enabled(self) -> bool:
        """Check if tools are enabled."""
        return self._app._tools_enabled

    @property
    def autoroute_enabled(self) -> bool:
        """Check if auto-routing is enabled."""
        return getattr(self._app, '_autoroute_enabled', False)

    def set_model(self, model: str) -> None:
        """Switch to specified model (updates both UI state and engine)."""
        self._app._model = model
        if self._app._engine_client:
            self._app._engine_client.set_model(model)
        # Update status bar if available
        if hasattr(self._app, '_update_status_bar'):
            self._app._update_status_bar()

    def set_provider(self, provider: str) -> None:
        """Switch to specified provider (updates both UI state and engine)."""
        self._app._provider = provider
        if self._app._engine_client:
            self._app._engine_client.set_provider(provider)
        # Update status bar if available
        if hasattr(self._app, '_update_status_bar'):
            self._app._update_status_bar()

    def get_provider(self) -> str:
        """Get currently selected provider."""
        return self._app._provider

    def get_model(self) -> str:
        """Get currently selected model."""
        return self._app._model

    def get_auto_route(self) -> bool:
        """Get auto-routing status."""
        return getattr(self._app, '_autoroute_enabled', False)

    def set_auto_route(self, enabled: bool) -> None:
        """Set auto-routing status."""
        self._app._autoroute_enabled = enabled

    def get_tools_available(self) -> bool:
        """Check if tool support is available."""
        return getattr(self._app, '_tools_available', False)

    def get_tools_verbose(self) -> bool:
        """Get tool verbose logging status."""
        return getattr(self._app, '_tools_verbose', False)

    def set_tools_verbose(self, verbose: bool) -> None:
        """Set tool verbose logging status."""
        self._app._tools_verbose = verbose

    def get_config_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get configuration value.

        Args:
            key: Configuration key
            default: Default value

        Returns:
            Configuration value or default
        """
        if hasattr(self._app, '_config'):
            return self._app._config.get(key, default)
        return default

    def set_config_value(self, key: str, value: str) -> None:
        """Set configuration value.

        Args:
            key: Configuration key
            value: Value to set
        """
        if hasattr(self._app, '_config'):
            self._app._config[key] = value


# Export context adapters
__all__ = [
    "RichCommandContext",
    "TextualCommandContext",
]

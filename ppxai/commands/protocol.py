"""
Command Context Protocol - Minimal Interface for UI-Agnostic Commands

This module defines the protocol that commands expect from their execution context.
Commands are UI-agnostic and only depend on this minimal interface.

Architecture:
- Commands receive CommandContext (protocol), not concrete Handler/App
- Context provides access to: engine_client, session, working_dir, etc.
- UI frameworks implement this protocol via adapters (RichCommandContext, TextualCommandContext)
- Zero UI framework dependencies in command code

v1.15.0: Type-based renderer dispatch refactoring
"""

from typing import Any, Protocol, runtime_checkable, Callable, Optional

from ..engine.types import EngineClientProtocol
from .results import CommandResult


@runtime_checkable
class CommandContext(Protocol):
    """Context provided to commands - minimal interface.

    Commands receive this protocol, not concrete Handler/App instances.
    This enables UI-agnostic command implementation.

    Example:
        def handle_save(context: CommandContext, args: str) -> NotificationResult:
            session_name = args or context.session.name
            context.session.save(session_name)
            return NotificationResult(
                status=ResultStatus.SUCCESS,
                message=f"Session saved: {session_name}"
            )
    """

    # ========================================================================
    # Core Required Attributes
    # ========================================================================

    @property
    def engine_client(self) -> EngineClientProtocol:
        """Access to engine client for AI operations.

        Returns the engine surface that commands depend on. Typed as the
        Protocol (not the concrete `EngineClient` class) so the
        commands→engine boundary stays nominally decoupled — see
        `EngineClientProtocol` in `ppxai/engine/types.py` for the full
        method/property surface (Item 10, v1.18.2).

        Provides:
        - engine_client.chat(message) - Send chat message
        - engine_client.session - Session management
        - engine_client.tool_manager - Tool registry access
        - engine_client.state - AppState read/write
        """
        ...

    @property
    def session(self) -> Any:
        """Access to current session.

        Provides:
        - session.messages - Conversation history
        - session.save(name) - Save session
        - session.load(name) - Load session
        - session.clear() - Clear history
        """
        ...

    @property
    def working_dir(self) -> str:
        """Current working directory for file operations."""
        ...

    @property
    def current_model(self) -> str:
        """Currently selected model (e.g., 'gpt-4', 'sonar')."""
        ...

    @property
    def provider(self) -> str:
        """Currently selected provider (e.g., 'openai', 'perplexity')."""
        ...

    # ========================================================================
    # Core Required Methods
    # ========================================================================

    def set_model(self, model: str) -> None:
        """Switch to specified model.

        Args:
            model: Model ID (e.g., 'gpt-4', 'claude-3-opus')
        """
        ...

    def set_provider(self, provider: str) -> None:
        """Switch to specified provider.

        Args:
            provider: Provider ID (e.g., 'openai', 'perplexity')
        """
        ...

    def get_provider(self) -> str:
        """Get currently selected provider.

        Returns:
            Provider ID (e.g., 'openai', 'perplexity')
        """
        ...

    def get_model(self) -> str:
        """Get currently selected model.

        Returns:
            Model ID (e.g., 'gpt-4', 'sonar')
        """
        ...

    def get_auto_route(self) -> bool:
        """Get auto-routing status.

        Returns:
            True if auto-routing is enabled, False otherwise
        """
        ...

    def set_auto_route(self, enabled: bool) -> None:
        """Set auto-routing status.

        Args:
            enabled: True to enable auto-routing, False to disable
        """
        ...

    def get_tools_available(self) -> bool:
        """Check if tool support is available (dependencies installed).

        Returns:
            True if tools are available, False otherwise
        """
        ...

    def get_tools_verbose(self) -> bool:
        """Get tool verbose logging status.

        Returns:
            True if verbose logging is enabled, False otherwise
        """
        ...

    def set_tools_verbose(self, verbose: bool) -> None:
        """Set tool verbose logging status.

        Args:
            verbose: True to enable verbose logging, False to disable
        """
        ...

    # ========================================================================
    # Optional Attributes (may not be present in all contexts)
    # ========================================================================

    @property
    def tools_enabled(self) -> bool:
        """Check if tools are currently enabled."""
        ...

    @property
    def autoroute_enabled(self) -> bool:
        """Check if auto-routing to coding model is enabled."""
        ...

    # ========================================================================
    # Optional Methods for Advanced Features
    # ========================================================================

    def get_config_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        ...

    def set_config_value(self, key: str, value: str) -> None:
        """Set configuration value.

        Args:
            key: Configuration key
            value: Value to set
        """
        ...


# Command handler signature - returns typed result
CommandHandler = Callable[[CommandContext, str], CommandResult]
"""
Type alias for command handler functions.

Signature: (context: CommandContext, args: str) -> CommandResult

Example:
    def handle_save(context: CommandContext, args: str) -> NotificationResult:
        session_name = args or context.session.name
        context.session.save(session_name)
        return NotificationResult(
            status=ResultStatus.SUCCESS,
            message=f"Session saved: {session_name}"
        )
"""


# Export protocol and handler type
__all__ = [
    "CommandContext",
    "CommandHandler",
]

"""
Built-in tools for the ppxai engine.

These tools are registered automatically when the engine starts.

Import Pattern:
    Uses TYPE_CHECKING to avoid circular imports. ToolManager and EngineClient
    are only imported for type hints during static analysis, not at runtime.
    This is the standard pattern for all builtin tool modules.
"""

from typing import TYPE_CHECKING, Optional

# TYPE_CHECKING imports: only used for type hints, never at runtime
# This breaks potential circular dependencies with manager.py and client.py
if TYPE_CHECKING:
    from ..manager import ToolManager
    from ...client import EngineClient


def register_all_builtin_tools(manager: 'ToolManager', provider: str = None, engine: Optional['EngineClient'] = None):
    """Register all built-in tools with the manager.

    Args:
        manager: ToolManager instance
        provider: Current provider name (for capability-based filtering)
        engine: Engine client instance (required for file editing and shell tools v1.11.0+)
    """
    from . import filesystem, calculator, datetime_tool, web

    # Register tools from each module
    filesystem.register_tools(manager, engine)
    calculator.register_tools(manager)
    datetime_tool.register_tools(manager)

    # Web search: Try premium first (v1.13.4), fall back to free
    try:
        from . import web_premium
        if web_premium.is_available():
            web_premium.register_tools(manager, provider)
        else:
            web.register_tools(manager, provider)
    except Exception:
        # Fall back to free search if premium module fails
        web.register_tools(manager, provider)

    # Register tools that require engine for consent (v1.11.0+)
    if engine is not None:
        try:
            from . import editor, shell
            editor.register_tools(manager, engine)
            shell.register_tools(manager, engine)
        except Exception:
            # Silently skip if consent-based tools fail to register
            pass

        # Container management tools (v1.13.8)
        try:
            from . import container
            container.register_tools(manager, engine)
        except Exception:
            # Silently skip if container tools fail to register
            pass

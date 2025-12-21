"""
Built-in tools for the ppxai engine.

These tools are registered automatically when the engine starts.
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..manager import ToolManager
    from ...client import EngineClient


def register_all_builtin_tools(manager: 'ToolManager', provider: str = None, engine: Optional['EngineClient'] = None):
    """Register all built-in tools with the manager.

    Args:
        manager: ToolManager instance
        provider: Current provider name (for capability-based filtering)
        engine: Engine client instance (required for file editing tools v1.11.0)
    """
    from . import filesystem, shell, calculator, datetime_tool, web

    # Register tools from each module
    filesystem.register_tools(manager)
    shell.register_tools(manager)
    calculator.register_tools(manager)
    datetime_tool.register_tools(manager)
    web.register_tools(manager, provider)

    # Register file editing tools (v1.11.0) if engine provided
    if engine is not None:
        try:
            from . import editor
            editor.register_tools(manager, engine)
        except Exception:
            # Silently skip if file editing tools fail to register
            pass

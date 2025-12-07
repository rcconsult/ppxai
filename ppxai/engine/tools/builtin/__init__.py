"""
Built-in tools for the ppxai engine.

These tools are registered automatically when the engine starts.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..manager import ToolManager


def register_all_builtin_tools(manager: 'ToolManager', provider: str = None):
    """Register all built-in tools with the manager.

    Args:
        manager: ToolManager instance
        provider: Current provider name (for capability-based filtering)
    """
    from . import filesystem, shell, calculator, datetime_tool, web

    # Register tools from each module
    filesystem.register_tools(manager)
    shell.register_tools(manager)
    calculator.register_tools(manager)
    datetime_tool.register_tools(manager)
    web.register_tools(manager, provider)

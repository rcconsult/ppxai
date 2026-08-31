"""
Rendering Package - Type-Based Renderer Dispatch for UI Frameworks

This package provides the rendering infrastructure for type-based dispatch.
Commands return typed results; renderers handle display mechanically by type.

Architecture:
- Base: Renderer, AsyncRenderer - Registry pattern with type-based dispatch
- Rich: RichRenderer - Rich console rendering (sync)
- Textual: TextualRenderer - Textual widget rendering (async)

Usage:
    # Rich TUI
    from ppxai.rendering import RichRenderer
    result = command_handler(context, args)
    RichRenderer.render(result)  # Mechanical dispatch

    # Textual TUI
    from ppxai.rendering import TextualRenderer
    renderer = TextualRenderer(app)
    result = await command_handler(context, args)
    await renderer.render(result)  # Mechanical async dispatch

v1.15.0: Type-based renderer dispatch refactoring
"""

from .base import AsyncRenderer, Renderer

# Rich and Textual renderers imported lazily to avoid circular imports
# and ensure they're only loaded when needed

__all__ = [
    "Renderer",
    "AsyncRenderer",
    # Rich and Textual renderers available but not exported by default
    # to avoid circular imports - import them directly when needed
]

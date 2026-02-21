"""
Renderer Base Classes - Type-Based Dispatch Registry

This module provides the base renderer pattern with mechanical type-based dispatch.
Each TUI framework subclasses and registers renderers for each result type.

Architecture:
- Renderer: Sync base class (for Rich TUI)
- AsyncRenderer: Async base class (for Textual TUI)
- Registration: Decorator pattern (@Renderer.register(ResultType))
- Dispatch: Mechanical type lookup → call handler (zero conditional logic)

v1.15.0: Type-based renderer dispatch refactoring
"""

from typing import Callable, Dict, Type, Any
from ..commands.results import CommandResult, TextResult


class Renderer:
    """Base renderer with type-based dispatch registry (sync).

    Each TUI framework subclasses this and registers rendering
    functions for each result type. Dispatch is mechanical -
    just type lookup, zero conditional logic.

    Example:
        class RichRenderer(Renderer):
            pass

        @RichRenderer.register(TableResult)
        def render_table(result: TableResult):
            table = Table()
            for col in result.columns:
                table.add_column(col)
            for row in result.rows:
                table.add_row(*row)
            console.print(table)

        # Later, mechanical dispatch
        result = command_handler(context, args)
        RichRenderer.render(result)  # Automatically calls render_table()
    """

    _registry: Dict[Type[CommandResult], Callable] = {}

    @classmethod
    def register(cls, result_type: Type[CommandResult]) -> Callable:
        """Decorator to register renderer for result type.

        Args:
            result_type: Result class to handle (e.g., TableResult)

        Returns:
            Decorator function

        Example:
            @RichRenderer.register(TableResult)
            def render_table(result: TableResult):
                # Rendering logic here
                pass
        """
        def decorator(func: Callable) -> Callable:
            # Store in the specific subclass's registry, not the base class
            if cls not in [Renderer, AsyncRenderer]:
                # Check if this class has its OWN registry (not inherited)
                # Using __dict__ to avoid looking up inherited attributes
                if '_registry' not in cls.__dict__:
                    cls._registry = {}
                cls._registry[result_type] = func
            return func
        return decorator

    @classmethod
    def render(cls, result: CommandResult) -> Any:
        """Dispatch result to appropriate renderer - MECHANICAL.

        No conditional logic - just type lookup and call.

        Args:
            result: Command result to render

        Returns:
            Renderer function return value (usually None)

        Raises:
            KeyError: If no renderer registered for result type
        """
        result_type = type(result)

        # Get the class's own registry (not inherited)
        own_registry = cls.__dict__.get('_registry', {})

        # Get renderer function for this type — walk MRO for subtype support
        if result_type not in own_registry:
            # Walk MRO to find registered parent type (e.g., DirectoryListingResult → TableResult)
            matched = False
            for parent in type(result).__mro__[1:]:
                if parent in own_registry:
                    result_type = parent
                    matched = True
                    break
            if not matched:
                # Fallback to TextResult renderer if available
                if TextResult in own_registry:
                    result_type = TextResult
                else:
                    raise KeyError(
                        f"No renderer registered for {type(result).__name__} "
                        f"in {cls.__name__}. Available types: {list(own_registry.keys())}"
                    )

        renderer_func = own_registry.get(result_type)
        if not renderer_func:
            raise KeyError(
                f"No renderer function found for {result_type.__name__}"
            )

        return renderer_func(result)

    @classmethod
    def has_renderer(cls, result_type: Type[CommandResult]) -> bool:
        """Check if renderer is registered for result type.

        Args:
            result_type: Result class to check

        Returns:
            True if renderer registered, False otherwise
        """
        # Only check the class's own registry, not inherited
        own_registry = cls.__dict__.get('_registry', {})
        return result_type in own_registry

    @classmethod
    def list_registered_types(cls) -> list[Type[CommandResult]]:
        """List all registered result types.

        Returns:
            List of registered result type classes
        """
        # Only return types from the class's own registry
        own_registry = cls.__dict__.get('_registry', {})
        return list(own_registry.keys())


class AsyncRenderer(Renderer):
    """Async variant for Textual TUI.

    Same pattern as Renderer, but renderers are async functions
    and dispatch is async.

    Example:
        class TextualRenderer(AsyncRenderer):
            def __init__(self, app):
                self.app = app

        @TextualRenderer.register(TableResult)
        async def render_table(renderer: TextualRenderer, result: TableResult):
            table = DataTable()
            table.add_columns(*result.columns)
            for row in result.rows:
                table.add_row(*row)
            await renderer.app.show_widget_in_panel(table)

        # Later, mechanical async dispatch
        renderer = TextualRenderer(app)
        result = await command_handler(context, args)
        await renderer.render(result)
    """

    @classmethod
    async def render(cls, result: CommandResult, renderer_instance: Any = None) -> Any:
        """Async dispatch - for Textual widgets.

        Args:
            result: Command result to render
            renderer_instance: Renderer instance (for stateful renderers)

        Returns:
            Renderer function return value (usually None)

        Raises:
            KeyError: If no renderer registered for result type
        """
        result_type = type(result)

        # Get the class's own registry (not inherited)
        own_registry = cls.__dict__.get('_registry', {})

        # Get renderer function for this type — walk MRO for subtype support
        if result_type not in own_registry:
            # Walk MRO to find registered parent type (e.g., DirectoryTreeResult → TreeResult)
            matched = False
            for parent in type(result).__mro__[1:]:
                if parent in own_registry:
                    result_type = parent
                    matched = True
                    break
            if not matched:
                # Fallback to TextResult renderer if available
                if TextResult in own_registry:
                    result_type = TextResult
                else:
                    raise KeyError(
                        f"No renderer registered for {type(result).__name__} "
                        f"in {cls.__name__}. Available types: {list(own_registry.keys())}"
                    )

        renderer_func = own_registry.get(result_type)
        if not renderer_func:
            raise KeyError(
                f"No renderer function found for {result_type.__name__}"
            )

        # Call async renderer function
        # Some renderers may need instance (for app/widget access)
        if renderer_instance:
            return await renderer_func(renderer_instance, result)
        else:
            return await renderer_func(result)


# Export base classes
__all__ = [
    "Renderer",
    "AsyncRenderer",
]

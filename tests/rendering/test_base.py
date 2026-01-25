"""
Test suite for renderer base classes and type-based dispatch.

Tests the core renderer pattern:
- Registry mechanism with @Renderer.register() decorator
- Mechanical type-based dispatch
- Fallback to TextResult
- AsyncRenderer async dispatch
- Renderer introspection methods

v1.15.0: Type-based renderer dispatch refactoring
"""

import pytest
from ppxai.rendering.base import Renderer, AsyncRenderer
from ppxai.commands.results import (
    ResultStatus,
    CommandResult,
    NotificationResult,
    ErrorResult,
    TableResult,
    TextResult,
)


# ============================================================================
# Test Renderer Implementations
# ============================================================================

class TestSyncRenderer(Renderer):
    """Test renderer for sync dispatch."""
    pass


class TestAsyncRenderer(AsyncRenderer):
    """Test renderer for async dispatch."""
    pass


# Track render calls for testing
render_calls = []


@TestSyncRenderer.register(NotificationResult)
def render_notification(result: NotificationResult) -> str:
    """Test notification renderer."""
    render_calls.append(("notification", result))
    return f"Notification: {result.message}"


@TestSyncRenderer.register(ErrorResult)
def render_error(result: ErrorResult) -> str:
    """Test error renderer."""
    render_calls.append(("error", result))
    return f"Error: {result.message}"


@TestSyncRenderer.register(TextResult)
def render_text(result: TextResult) -> str:
    """Test text renderer (fallback)."""
    render_calls.append(("text", result))
    return f"Text: {result.message}"


@TestAsyncRenderer.register(NotificationResult)
async def async_render_notification(result: NotificationResult) -> str:
    """Test async notification renderer."""
    render_calls.append(("async_notification", result))
    return f"Async Notification: {result.message}"


@TestAsyncRenderer.register(TableResult)
async def async_render_table(result: TableResult) -> str:
    """Test async table renderer."""
    render_calls.append(("async_table", result))
    return f"Async Table: {result.message}"


@TestAsyncRenderer.register(TextResult)
async def async_render_text(result: TextResult) -> str:
    """Test async text renderer (fallback)."""
    render_calls.append(("async_text", result))
    return f"Async Text: {result.message}"


# ============================================================================
# Sync Renderer Tests
# ============================================================================

class TestRendererRegistry:
    """Test renderer registry mechanism."""

    def setup_method(self):
        """Clear render calls before each test."""
        render_calls.clear()

    def test_register_decorator(self):
        """Test @Renderer.register() decorator."""
        # Check that handlers were registered
        assert NotificationResult in TestSyncRenderer._registry
        assert ErrorResult in TestSyncRenderer._registry
        assert TextResult in TestSyncRenderer._registry

    def test_has_renderer(self):
        """Test has_renderer() method."""
        assert TestSyncRenderer.has_renderer(NotificationResult) is True
        assert TestSyncRenderer.has_renderer(ErrorResult) is True
        assert TestSyncRenderer.has_renderer(TableResult) is False

    def test_list_registered_types(self):
        """Test list_registered_types() method."""
        types = TestSyncRenderer.list_registered_types()
        assert NotificationResult in types
        assert ErrorResult in types
        assert TextResult in types


class TestRendererDispatch:
    """Test type-based dispatch mechanism."""

    def setup_method(self):
        """Clear render calls before each test."""
        render_calls.clear()

    def test_dispatch_to_correct_handler(self):
        """Test that render() dispatches to correct handler."""
        result = NotificationResult(
            status=ResultStatus.SUCCESS,
            message="Test notification"
        )

        output = TestSyncRenderer.render(result)

        assert output == "Notification: Test notification"
        assert len(render_calls) == 1
        assert render_calls[0][0] == "notification"
        assert render_calls[0][1] is result

    def test_dispatch_multiple_types(self):
        """Test dispatching different result types."""
        notification = NotificationResult(
            status=ResultStatus.SUCCESS,
            message="Success"
        )
        error = ErrorResult(message="Error")

        TestSyncRenderer.render(notification)
        TestSyncRenderer.render(error)

        assert len(render_calls) == 2
        assert render_calls[0][0] == "notification"
        assert render_calls[1][0] == "error"

    def test_fallback_to_text_result(self):
        """Test fallback to TextResult for unregistered types."""
        # TableResult is not registered in TestSyncRenderer
        table = TableResult(
            message="Test table",
            columns=["A", "B"],
            rows=[["1", "2"]]
        )

        output = TestSyncRenderer.render(table)

        # Should fall back to TextResult renderer
        assert output == "Text: Test table"
        assert render_calls[0][0] == "text"

    def test_no_renderer_raises_error(self):
        """Test that missing renderer raises KeyError."""
        # Create a renderer without TextResult fallback
        class NoFallbackRenderer(Renderer):
            pass

        @NoFallbackRenderer.register(NotificationResult)
        def render_notification(result):
            return "OK"

        # This should work
        NoFallbackRenderer.render(
            NotificationResult(status=ResultStatus.SUCCESS, message="OK")
        )

        # This should raise KeyError (no TableResult, no TextResult fallback)
        with pytest.raises(KeyError) as exc_info:
            NoFallbackRenderer.render(
                TableResult(message="Table", columns=[], rows=[])
            )

        assert "No renderer registered for TableResult" in str(exc_info.value)


# ============================================================================
# Async Renderer Tests
# ============================================================================

class TestAsyncRendererRegistry:
    """Test async renderer registry."""

    def test_async_register_decorator(self):
        """Test async renderer registration."""
        assert NotificationResult in TestAsyncRenderer._registry
        assert TableResult in TestAsyncRenderer._registry
        assert TextResult in TestAsyncRenderer._registry

    def test_async_has_renderer(self):
        """Test has_renderer() on async renderer."""
        assert TestAsyncRenderer.has_renderer(NotificationResult) is True
        assert TestAsyncRenderer.has_renderer(TableResult) is True
        assert TestAsyncRenderer.has_renderer(ErrorResult) is False


class TestAsyncRendererDispatch:
    """Test async dispatch mechanism."""

    def setup_method(self):
        """Clear render calls before each test."""
        render_calls.clear()

    @pytest.mark.asyncio
    async def test_async_dispatch(self):
        """Test async render dispatch."""
        result = NotificationResult(
            status=ResultStatus.SUCCESS,
            message="Async test"
        )

        output = await TestAsyncRenderer.render(result)

        assert output == "Async Notification: Async test"
        assert len(render_calls) == 1
        assert render_calls[0][0] == "async_notification"

    @pytest.mark.asyncio
    async def test_async_dispatch_multiple_types(self):
        """Test async dispatch with different types."""
        notification = NotificationResult(
            status=ResultStatus.SUCCESS,
            message="Success"
        )
        table = TableResult(
            message="Table",
            columns=["A"],
            rows=[["1"]]
        )

        await TestAsyncRenderer.render(notification)
        await TestAsyncRenderer.render(table)

        assert len(render_calls) == 2
        assert render_calls[0][0] == "async_notification"
        assert render_calls[1][0] == "async_table"

    @pytest.mark.asyncio
    async def test_async_fallback_to_text(self):
        """Test async fallback to TextResult."""
        # ErrorResult is not registered in TestAsyncRenderer
        error = ErrorResult(message="Error message")

        output = await TestAsyncRenderer.render(error)

        # Should fall back to TextResult renderer
        assert output == "Async Text: Error message"
        assert render_calls[0][0] == "async_text"

    @pytest.mark.asyncio
    async def test_async_with_renderer_instance(self):
        """Test async dispatch with renderer instance parameter."""
        # This tests the renderer_instance parameter used by TextualRenderer

        class StatefulAsyncRenderer(AsyncRenderer):
            def __init__(self, name: str):
                self.name = name

        instance = StatefulAsyncRenderer("test-renderer")

        # Track instance access
        instance_calls = []

        @StatefulAsyncRenderer.register(NotificationResult)
        async def render_with_instance(renderer, result):
            instance_calls.append(renderer.name)
            return f"{renderer.name}: {result.message}"

        result = NotificationResult(
            status=ResultStatus.SUCCESS,
            message="Test"
        )

        output = await StatefulAsyncRenderer.render(
            result,
            renderer_instance=instance
        )

        assert output == "test-renderer: Test"
        assert instance_calls == ["test-renderer"]


# ============================================================================
# Registry Isolation Tests
# ============================================================================

class TestRegistryIsolation:
    """Test that different renderer classes have isolated registries."""

    def test_subclass_registries_are_isolated(self):
        """Test that subclass registries don't pollute base class."""
        # TestSyncRenderer has NotificationResult, ErrorResult, TextResult
        # TestAsyncRenderer has NotificationResult, TableResult, TextResult

        # Base Renderer class should have empty registry
        assert Renderer._registry == {}

        # Subclass registries should be independent
        assert NotificationResult in TestSyncRenderer._registry
        assert ErrorResult in TestSyncRenderer._registry
        assert TableResult not in TestSyncRenderer._registry

        assert NotificationResult in TestAsyncRenderer._registry
        assert TableResult in TestAsyncRenderer._registry
        assert ErrorResult not in TestAsyncRenderer._registry

    def test_multiple_renderer_classes(self):
        """Test creating multiple independent renderer classes."""
        class Renderer1(Renderer):
            pass

        class Renderer2(Renderer):
            pass

        @Renderer1.register(NotificationResult)
        def render1(result):
            return "Renderer1"

        @Renderer2.register(NotificationResult)
        def render2(result):
            return "Renderer2"

        result = NotificationResult(
            status=ResultStatus.SUCCESS,
            message="Test"
        )

        # Each renderer should call its own handler
        assert Renderer1.render(result) == "Renderer1"
        assert Renderer2.render(result) == "Renderer2"


# ============================================================================
# Edge Case Tests
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_render_none_raises_error(self):
        """Test that rendering None raises AttributeError."""
        with pytest.raises(AttributeError):
            TestSyncRenderer.render(None)

    def test_duplicate_registration(self):
        """Test that registering same type twice uses latest handler."""
        class DuplicateRenderer(Renderer):
            pass

        @DuplicateRenderer.register(NotificationResult)
        def first_handler(result):
            return "first"

        @DuplicateRenderer.register(NotificationResult)
        def second_handler(result):
            return "second"

        result = NotificationResult(
            status=ResultStatus.SUCCESS,
            message="Test"
        )

        # Should use the latest registered handler
        assert DuplicateRenderer.render(result) == "second"

    def test_unregistered_type_without_fallback(self):
        """Test error message for unregistered type without fallback."""
        class NoHandlersRenderer(Renderer):
            pass

        result = NotificationResult(
            status=ResultStatus.SUCCESS,
            message="Test"
        )

        with pytest.raises(KeyError) as exc_info:
            NoHandlersRenderer.render(result)

        error_msg = str(exc_info.value)
        assert "No renderer registered for NotificationResult" in error_msg
        assert "NoHandlersRenderer" in error_msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

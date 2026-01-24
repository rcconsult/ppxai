"""
Base classes and mixins for TUI widgets.

Provides common functionality used across multiple widgets.
"""

from typing import TypeVar, Optional, Callable

from textual.css.query import NoMatches
from textual.widget import Widget

T = TypeVar('T', bound=Widget)


class SafeQueryMixin:
    """Mixin providing safe widget query methods.

    Use this mixin in widgets that need to query child widgets
    that may not be composed yet (e.g., in watch_* methods).

    Example:
        class MyWidget(Widget, SafeQueryMixin):
            def watch_value(self, value: str) -> None:
                self.safe_query_one(
                    "#display",
                    Static,
                    action=lambda w: w.update(value)
                )
    """

    def safe_query_one(
        self,
        selector: str,
        widget_type: type[T],
        action: Optional[Callable[[T], None]] = None
    ) -> Optional[T]:
        """Query for widget, optionally execute action, handle missing gracefully.

        Args:
            selector: CSS selector for the widget
            widget_type: Expected widget type
            action: Optional callback to execute if widget found

        Returns:
            The widget if found, None otherwise
        """
        try:
            widget = self.query_one(selector, widget_type)
            if action:
                action(widget)
            return widget
        except NoMatches:
            # Widget not yet composed or selector doesn't match
            if hasattr(self, 'log'):
                self.log.debug(f"Widget not found: {selector}")
            return None

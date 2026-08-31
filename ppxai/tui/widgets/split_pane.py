"""
SplitPane widget - Side-by-side container layouts.

Provides horizontal and vertical split pane layouts
for displaying multiple widgets side-by-side.
"""


from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class Pane(Container):
    """A single pane in a split layout."""

    # Styled via .pane class in layout.tcss

    def __init__(
        self,
        *children: Widget,
        title: str = None,
        id: str = None,
    ):
        """Initialize a pane.

        Args:
            children: Child widgets to add
            title: Optional title for the pane
            id: Widget ID
        """
        super().__init__(*children, id=id)
        self._title = title
        self.add_class("pane")

    def compose(self) -> ComposeResult:
        """Compose the pane contents."""
        if self._title:
            yield Static(f"[bold]{self._title}[/bold]", classes="pane-title")
        # Children are added via __init__


class SplitPane(Container):
    """A container that splits its area between two or more panes."""

    # CSS is in layout.tcss

    orientation = reactive("horizontal")

    def __init__(
        self,
        *panes: Widget,
        orientation: str = "horizontal",
        id: str = None,
    ):
        """Initialize the split pane.

        Args:
            panes: Child panes/widgets
            orientation: "horizontal" (side-by-side) or "vertical" (stacked)
            id: Widget ID
        """
        super().__init__(*panes, id=id)
        self.orientation = orientation
        self._update_orientation()

    def _update_orientation(self) -> None:
        """Update CSS classes based on orientation."""
        self.remove_class("-horizontal")
        self.remove_class("-vertical")
        self.add_class(f"-{self.orientation}")

    def watch_orientation(self, value: str) -> None:
        """React to orientation changes."""
        self._update_orientation()


class HorizontalSplit(Horizontal):
    """Horizontal split pane (side-by-side)."""

    # CSS is in layout.tcss

    def __init__(self, *children: Widget, id: str = None):
        """Initialize horizontal split.

        Args:
            children: Child widgets to display side-by-side
            id: Widget ID
        """
        super().__init__(*children, id=id)


class VerticalSplit(Vertical):
    """Vertical split pane (stacked top-to-bottom)."""

    # CSS is in layout.tcss

    def __init__(self, *children: Widget, id: str = None):
        """Initialize vertical split.

        Args:
            children: Child widgets to stack vertically
            id: Widget ID
        """
        super().__init__(*children, id=id)

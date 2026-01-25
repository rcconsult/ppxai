"""
StatusBar widget - Shows provider, model, tools status, and context info.

Supports dynamic badge management for flexible status display.
"""

from typing import Optional
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static


class StatusBadge(Static):
    """A single status badge with label and value."""

    # CSS is in layout.tcss

    def __init__(self, label: str, value: str, variant: str = "default"):
        super().__init__(f"[bold]{label}:[/bold] {value}")
        self._label = label
        self._value = value
        if variant != "default":
            self.add_class(variant)

    def update_value(self, value: str) -> None:
        """Update the badge value."""
        self._value = value
        self.update(f"[bold]{self._label}:[/bold] {self._value}")


class StatusBar(Static):
    """Status bar showing current session state with dynamic badge management."""

    # CSS is in layout.tcss

    provider = reactive("perplexity")
    model = reactive("sonar")
    tools_enabled = reactive(False)
    context_tokens = reactive(0)
    context_limit = reactive(128000)

    def __init__(
        self,
        provider: str = "perplexity",
        model: str = "sonar",
        tools_enabled: bool = False,
        context_tokens: int = 0,
        context_limit: int = 128000,
    ):
        super().__init__()
        self.provider = provider
        self.model = model
        self.tools_enabled = tools_enabled
        self.context_tokens = context_tokens
        self.context_limit = context_limit
        self._badges: dict[str, StatusBadge] = {}
        self._container: Optional[Horizontal] = None

    def compose(self) -> ComposeResult:
        """Compose the status bar with initial badges."""
        with Horizontal() as container:
            self._container = container
            # Add initial badges
            self.add_badge("provider", "Provider", self.provider, "provider-badge")
            self.add_badge("model", "Model", self.model, "model-badge")
            self.add_badge(
                "tools",
                "Tools",
                "ON" if self.tools_enabled else "OFF",
                "tools-badge",
            )
            if self.context_tokens > 0:
                pct = int(self.context_tokens / self.context_limit * 100)
                self.add_badge("context", "Context", f"{pct}%", "context-badge")

    def add_badge(
        self, badge_id: str, label: str, value: str, variant: str = "default"
    ) -> StatusBadge:
        """Add a new badge to the status bar.

        Args:
            badge_id: Unique identifier for the badge
            label: Display label (e.g., "Provider", "Model")
            value: Current value to display
            variant: CSS class variant for styling

        Returns:
            The created StatusBadge instance
        """
        if badge_id in self._badges:
            # Badge already exists, just update it
            self.update_badge(badge_id, value)
            return self._badges[badge_id]

        badge = StatusBadge(label, value, variant)
        self._badges[badge_id] = badge

        # Mount the badge if container is ready
        if self._container is not None:
            self._container.mount(badge)

        return badge

    def remove_badge(self, badge_id: str) -> None:
        """Remove a badge from the status bar.

        Args:
            badge_id: Unique identifier of the badge to remove
        """
        if badge_id not in self._badges:
            return

        badge = self._badges[badge_id]
        badge.remove()
        del self._badges[badge_id]

    def update_badge(self, badge_id: str, value: str) -> None:
        """Update a badge's value.

        Args:
            badge_id: Unique identifier of the badge to update
            value: New value to display
        """
        if badge_id not in self._badges:
            return

        self._badges[badge_id].update_value(value)

    def hide_badge(self, badge_id: str) -> None:
        """Hide a badge without removing it.

        Args:
            badge_id: Unique identifier of the badge to hide
        """
        if badge_id not in self._badges:
            return

        self._badges[badge_id].display = False

    def show_badge(self, badge_id: str) -> None:
        """Show a previously hidden badge.

        Args:
            badge_id: Unique identifier of the badge to show
        """
        if badge_id not in self._badges:
            return

        self._badges[badge_id].display = True

    def has_badge(self, badge_id: str) -> bool:
        """Check if a badge exists.

        Args:
            badge_id: Unique identifier of the badge to check

        Returns:
            True if the badge exists, False otherwise
        """
        return badge_id in self._badges

    def watch_provider(self, provider: str) -> None:
        """React to provider changes."""
        self.update_badge("provider", provider)

    def watch_model(self, model: str) -> None:
        """React to model changes."""
        self.update_badge("model", model)

    def watch_tools_enabled(self, enabled: bool) -> None:
        """React to tools toggle."""
        self.update_badge("tools", "ON" if enabled else "OFF")

    def watch_context_tokens(self, tokens: int) -> None:
        """React to context token changes."""
        if tokens > 0:
            pct = int(tokens / self.context_limit * 100)
            if self.has_badge("context"):
                self.update_badge("context", f"{pct}%")
            else:
                self.add_badge("context", "Context", f"{pct}%", "context-badge")
        else:
            # Hide context badge when no tokens
            if self.has_badge("context"):
                self.hide_badge("context")

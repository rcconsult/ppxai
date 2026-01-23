"""
StatusBar widget - Shows provider, model, tools status, and context info.
"""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static


class StatusBadge(Static):
    """A single status badge with label and value."""

    # CSS is in layout.tcss

    def __init__(self, label: str, value: str, variant: str = "default"):
        super().__init__()
        self._label = label
        self._value = value
        self._variant = variant

    def compose(self) -> ComposeResult:
        yield Static(f"[bold]{self._label}:[/bold] {self._value}")

    def update_value(self, value: str) -> None:
        """Update the badge value."""
        self._value = value
        self.query_one(Static).update(f"[bold]{self._label}:[/bold] {self._value}")


class StatusBar(Static):
    """Status bar showing current session state."""

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

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield StatusBadge("Provider", self.provider, "provider-badge")
            yield StatusBadge("Model", self.model, "model-badge")
            yield StatusBadge(
                "Tools", "ON" if self.tools_enabled else "OFF", "tools-badge"
            )
            if self.context_tokens > 0:
                pct = int(self.context_tokens / self.context_limit * 100)
                yield StatusBadge("Context", f"{pct}%", "context-badge")

    def watch_provider(self, provider: str) -> None:
        """React to provider changes."""
        try:
            badge = self.query_one(".provider-badge", StatusBadge)
            badge.update_value(provider)
        except Exception:
            pass

    def watch_model(self, model: str) -> None:
        """React to model changes."""
        try:
            badge = self.query_one(".model-badge", StatusBadge)
            badge.update_value(model)
        except Exception:
            pass

    def watch_tools_enabled(self, enabled: bool) -> None:
        """React to tools toggle."""
        try:
            badge = self.query_one(".tools-badge", StatusBadge)
            badge.update_value("ON" if enabled else "OFF")
        except Exception:
            pass

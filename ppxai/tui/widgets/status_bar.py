"""
StatusBar widget - Shows provider, model, tools status, and context info.

Supports dynamic badge management with transactional updates (GitOps-style).
"""

from typing import Optional
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static


class BadgeError(Exception):
    """Exception raised for badge operation errors."""
    pass


class BadgeTransaction:
    """Transaction for atomic badge updates with rollback support.

    GitOps-style API:
    1. Checkpoint current state (automatic on enter)
    2. Stage operations (add, update, remove, hide, show)
    3. Commit changes (atomic - all succeed or all rollback)
    4. Rollback on failure with user-friendly error messages

    Usage:
        with status_bar.transaction() as txn:
            txn.add("tokens", "Tokens", "1234")
            txn.update("provider", "ollama")
            success, error = txn.commit()
            if not success:
                notify_user(error)
    """

    def __init__(self, status_bar: "StatusBar"):
        self._status_bar = status_bar
        self._backup: dict[str, dict] = {}
        self._operations: list[tuple] = []

    def __enter__(self):
        """Checkpoint current state on enter."""
        self.checkpoint()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Auto-rollback on exception."""
        if exc_type is not None:
            self.rollback()
            return False  # Re-raise exception
        return True

    def checkpoint(self) -> None:
        """Backup current badge state."""
        for badge_id, badge in self._status_bar._badges.items():
            self._backup[badge_id] = {
                "label": badge._label,
                "value": badge._value,
                "classes": list(badge.classes),
                "visible": badge.display,
            }

    def add(self, badge_id: str, label: str, value: str, variant: str = "default") -> "BadgeTransaction":
        """Stage badge addition."""
        self._operations.append(("add", badge_id, label, value, variant))
        return self

    def update(self, badge_id: str, value: str) -> "BadgeTransaction":
        """Stage badge update."""
        self._operations.append(("update", badge_id, value))
        return self

    def remove(self, badge_id: str) -> "BadgeTransaction":
        """Stage badge removal."""
        self._operations.append(("remove", badge_id))
        return self

    def hide(self, badge_id: str) -> "BadgeTransaction":
        """Stage badge hide."""
        self._operations.append(("hide", badge_id))
        return self

    def show(self, badge_id: str) -> "BadgeTransaction":
        """Stage badge show."""
        self._operations.append(("show", badge_id))
        return self

    def commit(self) -> tuple[bool, Optional[str]]:
        """Apply staged changes atomically.

        Returns:
            (success, error_message) - error_message is None on success
        """
        try:
            # Validation pass - check all operations before applying
            for op in self._operations:
                action = op[0]

                if action == "add":
                    _, badge_id, label, value, variant = op
                    if not label or not value:
                        raise BadgeError(f"Badge '{badge_id}': label and value are required")
                    if badge_id in self._status_bar._badges:
                        raise BadgeError(f"Badge '{badge_id}' already exists (use update instead)")

                elif action in ("update", "remove", "hide", "show"):
                    badge_id = op[1]
                    if badge_id not in self._status_bar._badges:
                        raise BadgeError(f"Badge '{badge_id}' does not exist")

            # Application pass - all validations passed, apply changes
            for op in self._operations:
                action = op[0]

                if action == "add":
                    _, badge_id, label, value, variant = op
                    self._status_bar.add_badge(badge_id, label, value, variant)

                elif action == "update":
                    _, badge_id, value = op
                    self._status_bar.update_badge(badge_id, value)

                elif action == "remove":
                    _, badge_id = op
                    self._status_bar.remove_badge(badge_id)

                elif action == "hide":
                    _, badge_id = op
                    self._status_bar.hide_badge(badge_id)

                elif action == "show":
                    _, badge_id = op
                    self._status_bar.show_badge(badge_id)

            return (True, None)

        except BadgeError as e:
            # Rollback on validation or application error
            self.rollback()
            return (False, str(e))

        except Exception as e:
            # Unexpected error - rollback and report
            self.rollback()
            return (False, f"Unexpected error: {str(e)}")

    def rollback(self) -> None:
        """Restore badge state from backup."""
        # Remove all current badges
        for badge_id in list(self._status_bar._badges.keys()):
            self._status_bar.remove_badge(badge_id)

        # Restore backup state
        for badge_id, state in self._backup.items():
            badge = StatusBadge(state["label"], state["value"])
            for cls in state["classes"]:
                badge.add_class(cls)
            badge.display = state["visible"]

            # Add to tracking dict
            self._status_bar._badges[badge_id] = badge

            # Mount if container is ready
            if self._status_bar._container is not None:
                self._status_bar._container.mount(badge)


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
        # Initialize state BEFORE setting reactive properties
        # (reactive properties trigger watch_* methods immediately)
        self._badges: dict[str, StatusBadge] = {}
        self._container: Optional[Horizontal] = None
        # Now set reactive properties
        self.provider = provider
        self.model = model
        self.tools_enabled = tools_enabled
        self.context_tokens = context_tokens
        self.context_limit = context_limit

    def compose(self) -> ComposeResult:
        """Compose the status bar with initial badges."""
        with Horizontal() as container:
            self._container = container
            # Create and yield initial badges (can't use add_badge during compose)
            provider_badge = StatusBadge("Provider", self.provider, "provider-badge")
            self._badges["provider"] = provider_badge
            yield provider_badge

            model_badge = StatusBadge("Model", self.model, "model-badge")
            self._badges["model"] = model_badge
            yield model_badge

            tools_badge = StatusBadge(
                "Tools", "ON" if self.tools_enabled else "OFF", "tools-badge"
            )
            self._badges["tools"] = tools_badge
            yield tools_badge

            if self.context_tokens > 0:
                pct = int(self.context_tokens / self.context_limit * 100)
                context_badge = StatusBadge("Context", f"{pct}%", "context-badge")
                self._badges["context"] = context_badge
                yield context_badge

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

    def transaction(self) -> BadgeTransaction:
        """Create a transaction for atomic badge updates (GitOps-style).

        Returns:
            BadgeTransaction context manager for atomic updates

        Usage:
            with status_bar.transaction() as txn:
                txn.add("tokens", "Tokens", "1234")
                txn.update("provider", "ollama")
                txn.remove("cost")
                success, error = txn.commit()
                if not success:
                    notify_user(f"Badge update failed: {error}")
        """
        return BadgeTransaction(self)

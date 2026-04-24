"""Sustained auto-save failure guard.

Auto-save runs after every N messages (or every message when the
interval is 0). Each call is wrapped in a broad try/except so a
single transient failure can't kill the chat loop. Historically the
failure was logged at WARNING and never reached the user, so a
session with a full disk / broken network drive / revoked permission
would silently stop saving for the entire run.

This helper tracks consecutive auto-save failures per client. When
the count crosses a threshold, the caller emits a **user-visible**
warning once — after that the counter resets so the warning doesn't
spam. A successful save resets the counter immediately.

Usage (from Rich / Textual):

    guard = AutosaveFailureGuard()
    ...
    try:
        session.save_dirty()
        guard.on_success()
    except Exception as e:
        should_warn_user = guard.on_failure(e)
        logger.warning("Auto-save failed: %s", e)
        if should_warn_user:
            console.print("[yellow]⚠ Auto-save failed 3 times in a row — "
                          "check disk space / permissions.[/yellow]")

Kept deliberately small: no threading, no async, no config knob. The
threshold is a module-level constant because "how many failures
before we tell the user" is a policy choice, not a user preference.
"""

from __future__ import annotations

from typing import Optional


# When a user-visible warning fires. 3 means: first failure + second
# failure stay silent (transient blips are common on Windows file
# locks, DFS paths), the third triggers the warning. If you need a
# faster alarm, the whole auto-save could be rewired — this guard is
# the conservative middle ground.
AUTOSAVE_WARN_THRESHOLD = 3


class AutosaveFailureGuard:
    """Tracks consecutive auto-save failures and tells the caller
    when the user should be notified.

    One instance per client (Rich TUI and Textual TUI each own one).
    Not thread-safe; both callers run in the main event loop, so
    a simple int counter is sufficient.
    """

    def __init__(self) -> None:
        self._consecutive_failures = 0
        self._warned = False

    def on_success(self) -> None:
        """Call after a successful save. Resets the counter and the
        warned-state so future failure streaks can re-trigger the
        warning."""
        self._consecutive_failures = 0
        self._warned = False

    def on_failure(self, exc: Optional[BaseException] = None) -> bool:
        """Call after a failed save. Returns True exactly once per
        failure streak, on the Nth consecutive failure where N is
        `AUTOSAVE_WARN_THRESHOLD`. Further failures in the same
        streak return False to avoid spamming the user; only a
        successful save (which calls `on_success`) resets.

        The `exc` argument is accepted so callers can log it as they
        see fit — the guard itself doesn't log anything (stays UI-
        agnostic, safe to import from any client).
        """
        self._consecutive_failures += 1
        if (
            not self._warned
            and self._consecutive_failures >= AUTOSAVE_WARN_THRESHOLD
        ):
            self._warned = True
            return True
        return False

    @property
    def consecutive_failures(self) -> int:
        """Read-only view, useful for tests."""
        return self._consecutive_failures

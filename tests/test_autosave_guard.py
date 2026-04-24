"""Tests for AutosaveFailureGuard (v1.18.0 Phase 5f).

Verifies the state machine that decides when auto-save failures
escalate from "log only" to "tell the user":

  - First N-1 failures return False (silent, only logged).
  - Nth failure returns True exactly once (user sees the warning).
  - Further failures in the same streak return False (no spam).
  - A success resets the counter and re-arms the warning.
"""

from __future__ import annotations

from ppxai.common.autosave_guard import (
    AUTOSAVE_WARN_THRESHOLD,
    AutosaveFailureGuard,
)


class TestBelowThreshold:
    def test_single_failure_is_silent(self) -> None:
        guard = AutosaveFailureGuard()
        assert guard.on_failure(OSError("disk full")) is False
        assert guard.consecutive_failures == 1

    def test_below_threshold_all_silent(self) -> None:
        guard = AutosaveFailureGuard()
        for i in range(AUTOSAVE_WARN_THRESHOLD - 1):
            assert guard.on_failure(OSError(f"fail {i}")) is False
        assert guard.consecutive_failures == AUTOSAVE_WARN_THRESHOLD - 1


class TestAtThreshold:
    def test_nth_failure_returns_true(self) -> None:
        guard = AutosaveFailureGuard()
        for _ in range(AUTOSAVE_WARN_THRESHOLD - 1):
            guard.on_failure(OSError("fail"))
        # The Nth call is the one that crosses the threshold.
        assert guard.on_failure(OSError("fail")) is True

    def test_counter_records_exact_number(self) -> None:
        guard = AutosaveFailureGuard()
        for _ in range(AUTOSAVE_WARN_THRESHOLD):
            guard.on_failure(OSError("fail"))
        assert guard.consecutive_failures == AUTOSAVE_WARN_THRESHOLD


class TestNoSpam:
    def test_further_failures_in_same_streak_stay_silent(self) -> None:
        """After the threshold-crossing warning has fired once, every
        subsequent failure in the same streak returns False so the
        user isn't spammed."""
        guard = AutosaveFailureGuard()
        warnings_fired = 0
        for _ in range(AUTOSAVE_WARN_THRESHOLD + 10):
            if guard.on_failure(OSError("fail")):
                warnings_fired += 1
        assert warnings_fired == 1
        assert guard.consecutive_failures == AUTOSAVE_WARN_THRESHOLD + 10


class TestSuccessResets:
    def test_success_after_failure_streak_clears_counter(self) -> None:
        guard = AutosaveFailureGuard()
        for _ in range(AUTOSAVE_WARN_THRESHOLD - 1):
            guard.on_failure(OSError("fail"))
        guard.on_success()
        assert guard.consecutive_failures == 0

    def test_success_rearms_warning_for_next_streak(self) -> None:
        """Two successive failure streaks each trigger one warning."""
        guard = AutosaveFailureGuard()

        # Streak 1 — crosses threshold
        warnings_fired = 0
        for _ in range(AUTOSAVE_WARN_THRESHOLD):
            if guard.on_failure(OSError("first streak")):
                warnings_fired += 1
        assert warnings_fired == 1

        # Success resets
        guard.on_success()

        # Streak 2 — must also trigger a warning (not just stay silent
        # because we already warned the user once this run).
        for _ in range(AUTOSAVE_WARN_THRESHOLD):
            if guard.on_failure(OSError("second streak")):
                warnings_fired += 1
        assert warnings_fired == 2


class TestConstants:
    def test_threshold_is_a_sensible_number(self) -> None:
        """Catches accidental removal / reduction to 1 (which would
        spam the user on every transient Windows file-lock blip)."""
        assert AUTOSAVE_WARN_THRESHOLD >= 2

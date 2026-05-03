"""Regression tests for release.py::wait_for_ci.

The v1.18.3 release tag cycle hit a false-negative: after --redo
deleted the tag and re-pushed, the script polled `gh run list` before
the new CI run was registered, saw only the OLD failed run from the
previous tag-cycle, and returned False — even though the new CI
eventually succeeded.

These tests pin the v1.18.4 contract: never trust a "completed"
status until we have observed the run in queued / in_progress.
Stale completed runs (success or failure) keep us polling.

The runs API is mocked at the `run_gh_command` boundary; tests
exercise the polling state machine, not subprocess behavior.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RELEASE_PY = PROJECT_ROOT / "scripts" / "release.py"


@pytest.fixture(scope="module")
def release_module():
    """Load scripts/release.py without executing main()."""
    spec = importlib.util.spec_from_file_location("release_script", RELEASE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gh_response(runs: list[dict]) -> SimpleNamespace:
    """Mock a successful run_gh_command result with the given runs JSON."""
    return SimpleNamespace(returncode=0, stdout=json.dumps(runs), stderr="")


def _gh_failure(stderr: str = "boom") -> SimpleNamespace:
    return SimpleNamespace(returncode=1, stdout="", stderr=stderr)


# ---------------------------------------------------------------------------
# Stale-completed-run handling — the v1.18.3 → v1.18.4 fix.
# ---------------------------------------------------------------------------


class TestStaleCompletedRunIgnored:
    """When the only run we see is completed but we never observed it
    in_progress, it's a stale run from a prior tag-cycle. Keep waiting."""

    def test_stale_failed_run_does_not_return_false(self, release_module):
        """The exact v1.18.3 bug: stale completed-failure run was
        accepted as authoritative. v1.18.4 must keep polling instead."""
        # Polls 1-3 see only the stale failed run.
        # Poll 4 sees the new in_progress run.
        # Poll 5 sees the new completed-success run.
        stale_failed = [{
            "status": "completed",
            "conclusion": "failure",
            "name": "Build Executables",
            "headBranch": "v9.9.9",
            "createdAt": "2026-05-03T20:48:00Z",
        }]
        new_inprogress = [{
            "status": "in_progress",
            "conclusion": None,
            "name": "Build Executables",
            "headBranch": "v9.9.9",
            "createdAt": "2026-05-03T21:04:15Z",
        }]
        new_success = [{
            "status": "completed",
            "conclusion": "success",
            "name": "Build Executables",
            "headBranch": "v9.9.9",
            "createdAt": "2026-05-03T21:04:15Z",
        }]
        responses = [
            _gh_response(stale_failed),
            _gh_response(stale_failed),
            _gh_response(stale_failed),
            _gh_response(new_inprogress),
            _gh_response(new_success),
        ]
        with patch.object(release_module, "run_gh_command", side_effect=responses), \
             patch.object(release_module.time, "sleep"):  # don't actually sleep
            result = release_module.wait_for_ci("9.9.9", timeout_minutes=10)
        assert result is True, (
            "wait_for_ci must keep polling past stale failed runs and "
            "accept the new run's success — not return False on the "
            "stale conclusion."
        )

    def test_stale_success_also_does_not_return_true(self, release_module):
        """Symmetry: a stale success is just as untrustworthy as a stale
        failure. Both must be ignored until we observe the run going
        through queued/in_progress."""
        stale_success = [{
            "status": "completed",
            "conclusion": "success",
            "name": "Build Executables",
            "headBranch": "v9.9.9",
            "createdAt": "2026-05-03T20:48:00Z",
        }]
        new_inprogress = [{
            "status": "in_progress",
            "conclusion": None,
            "name": "Build Executables",
            "headBranch": "v9.9.9",
            "createdAt": "2026-05-03T21:04:15Z",
        }]
        new_failure = [{
            "status": "completed",
            "conclusion": "failure",
            "name": "Build Executables",
            "headBranch": "v9.9.9",
            "createdAt": "2026-05-03T21:04:15Z",
        }]
        responses = [
            _gh_response(stale_success),
            _gh_response(new_inprogress),
            _gh_response(new_failure),
        ]
        with patch.object(release_module, "run_gh_command", side_effect=responses), \
             patch.object(release_module.time, "sleep"):
            result = release_module.wait_for_ci("9.9.9", timeout_minutes=10)
        assert result is False, (
            "Stale success must NOT be accepted; the new run failed and "
            "that's the authoritative outcome."
        )


# ---------------------------------------------------------------------------
# Happy paths — no regression on normal release flow.
# ---------------------------------------------------------------------------


class TestNormalCIFlow:
    def test_in_progress_then_success_returns_true(self, release_module):
        responses = [
            _gh_response([{
                "status": "in_progress", "conclusion": None,
                "name": "Build Executables", "headBranch": "v1.0.0",
                "createdAt": "2026-05-03T21:04:00Z",
            }]),
            _gh_response([{
                "status": "completed", "conclusion": "success",
                "name": "Build Executables", "headBranch": "v1.0.0",
                "createdAt": "2026-05-03T21:04:00Z",
            }]),
        ]
        with patch.object(release_module, "run_gh_command", side_effect=responses), \
             patch.object(release_module.time, "sleep"):
            assert release_module.wait_for_ci("1.0.0", timeout_minutes=10) is True

    def test_in_progress_then_failure_returns_false(self, release_module):
        responses = [
            _gh_response([{
                "status": "queued", "conclusion": None,
                "name": "Build Executables", "headBranch": "v1.0.0",
                "createdAt": "2026-05-03T21:04:00Z",
            }]),
            _gh_response([{
                "status": "in_progress", "conclusion": None,
                "name": "Build Executables", "headBranch": "v1.0.0",
                "createdAt": "2026-05-03T21:04:00Z",
            }]),
            _gh_response([{
                "status": "completed", "conclusion": "failure",
                "name": "Build Executables", "headBranch": "v1.0.0",
                "createdAt": "2026-05-03T21:04:00Z",
            }]),
        ]
        with patch.object(release_module, "run_gh_command", side_effect=responses), \
             patch.object(release_module.time, "sleep"):
            assert release_module.wait_for_ci("1.0.0", timeout_minutes=10) is False

    def test_no_runs_yet_keeps_polling(self, release_module):
        """When `gh run list` returns nothing for our tag, keep polling
        until one appears."""
        responses = [
            _gh_response([]),
            _gh_response([{  # different tag — filtered out
                "status": "in_progress", "conclusion": None,
                "name": "Build Executables", "headBranch": "v0.0.1",
                "createdAt": "2026-05-03T21:04:00Z",
            }]),
            _gh_response([{
                "status": "in_progress", "conclusion": None,
                "name": "Build Executables", "headBranch": "v1.0.0",
                "createdAt": "2026-05-03T21:04:00Z",
            }]),
            _gh_response([{
                "status": "completed", "conclusion": "success",
                "name": "Build Executables", "headBranch": "v1.0.0",
                "createdAt": "2026-05-03T21:04:00Z",
            }]),
        ]
        with patch.object(release_module, "run_gh_command", side_effect=responses), \
             patch.object(release_module.time, "sleep"):
            assert release_module.wait_for_ci("1.0.0", timeout_minutes=10) is True


# ---------------------------------------------------------------------------
# Robustness against transient gh CLI failures.
# ---------------------------------------------------------------------------


class TestTransientGhFailures:
    def test_gh_command_failure_keeps_polling(self, release_module):
        """A transient `gh` error (auth blip, rate limit) should not
        terminate the wait — we retry."""
        responses = [
            _gh_failure("rate limited"),
            _gh_response([{
                "status": "in_progress", "conclusion": None,
                "name": "Build Executables", "headBranch": "v1.0.0",
                "createdAt": "2026-05-03T21:04:00Z",
            }]),
            _gh_response([{
                "status": "completed", "conclusion": "success",
                "name": "Build Executables", "headBranch": "v1.0.0",
                "createdAt": "2026-05-03T21:04:00Z",
            }]),
        ]
        with patch.object(release_module, "run_gh_command", side_effect=responses), \
             patch.object(release_module.time, "sleep"):
            assert release_module.wait_for_ci("1.0.0", timeout_minutes=10) is True

    def test_malformed_json_keeps_polling(self, release_module):
        """`gh` returns non-JSON sometimes; don't crash, keep polling."""
        responses = [
            SimpleNamespace(returncode=0, stdout="not json", stderr=""),
            _gh_response([{
                "status": "in_progress", "conclusion": None,
                "name": "Build Executables", "headBranch": "v1.0.0",
                "createdAt": "2026-05-03T21:04:00Z",
            }]),
            _gh_response([{
                "status": "completed", "conclusion": "success",
                "name": "Build Executables", "headBranch": "v1.0.0",
                "createdAt": "2026-05-03T21:04:00Z",
            }]),
        ]
        with patch.object(release_module, "run_gh_command", side_effect=responses), \
             patch.object(release_module.time, "sleep"):
            assert release_module.wait_for_ci("1.0.0", timeout_minutes=10) is True

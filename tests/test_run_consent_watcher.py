"""Parked-run consent prompting in the Textual TUI (T8b).

A `/task` run that wants to spawn parks and blocks until answered or until
the TTL denies it. Without a prompt the operator must *notice* `✋ waiting` in
`/task ls`, which only works if they already suspected a problem.

These drive `RunConsentWatcher` against a fake app, because what matters is
the decision logic — which runs prompt, how often, and what an answer does —
not Textual's rendering of the dialog.
"""

from __future__ import annotations

import pytest

from ppxai.tui.run_consent import RunConsentWatcher


class _FakeMeta:
    def __init__(self, run_id, status="waiting", waiting=None):
        self.run_id = run_id
        self.status = status
        self.waiting = waiting


def _parked(run_id="run_0123456789ab", token="tok1", prompt="spawn a child?"):
    return _FakeMeta(run_id, "waiting",
                     {"kind": "consent", "token": token,
                      "prompt": prompt, "ttl_s": 300})


class _FakeApp:
    def __init__(self):
        self.pushed = []
        self.intervals = []

    def push_screen(self, screen, callback):
        self.pushed.append((screen, callback))

    def set_interval(self, interval, fn):
        self.intervals.append((interval, fn))
        return _FakeTimer()


class _FakeTimer:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class _FakeBackend:
    def __init__(self, runs):
        self._runs = runs
        self.responded = []

    def list_runs(self, kind=None):
        return list(self._runs)

    def respond(self, run_id, token, approved, text=None):
        self.responded.append((run_id, token, approved))


@pytest.fixture
def app():
    return _FakeApp()


# ── which runs prompt ───────────────────────────────────────────────────────

def test_parked_run_raises_a_prompt(app):
    w = RunConsentWatcher(app, _FakeBackend([_parked()]))
    w.poll_once()
    assert len(app.pushed) == 1
    screen = app.pushed[0][0]
    assert screen._run_id == "run_0123456789ab"
    assert "spawn a child?" in screen._prompt


@pytest.mark.parametrize("meta", [
    _FakeMeta("run_1", "running", None),
    _FakeMeta("run_2", "completed", None),
    _FakeMeta("run_3", "waiting", {"kind": "input", "token": "t"}),
    _FakeMeta("run_4", "waiting", {"kind": "consent"}),  # no token
    _FakeMeta("run_5", "waiting", None),
])
def test_non_consent_parks_do_not_prompt(app, meta):
    """Only a consent park with a usable token is actionable.

    A waiting run with no token cannot be answered, so prompting for it would
    offer the operator a decision that goes nowhere.
    """
    RunConsentWatcher(app, _FakeBackend([meta])).poll_once()
    assert app.pushed == []


# ── how often ───────────────────────────────────────────────────────────────

def test_one_prompt_per_park_across_polls(app):
    """Polling repeatedly must not stack dialogs for the same park."""
    backend = _FakeBackend([_parked()])
    w = RunConsentWatcher(app, backend)
    for _ in range(5):
        w.poll_once()
    assert len(app.pushed) == 1


def test_a_second_park_of_the_same_run_prompts_again(app):
    """The TOKEN is the identity, not the run — a run can park twice."""
    meta = _parked(token="tok1")
    backend = _FakeBackend([meta])
    w = RunConsentWatcher(app, backend)
    w.poll_once()

    meta.waiting = {"kind": "consent", "token": "tok2", "prompt": "again?"}
    w.poll_once()
    assert len(app.pushed) == 2


def test_deferring_does_not_reprompt(app):
    """Escape means 'later'. Re-asking every 2s would punish the choice."""
    backend = _FakeBackend([_parked()])
    w = RunConsentWatcher(app, backend)
    w.poll_once()
    app.pushed[0][1](None)          # dismissed
    w.poll_once()
    assert len(app.pushed) == 1
    assert backend.responded == []  # and nothing was answered on their behalf


# ── what an answer does ─────────────────────────────────────────────────────

@pytest.mark.parametrize("answer", [True, False])
def test_answer_is_forwarded_with_the_park_token(app, answer):
    backend = _FakeBackend([_parked(token="tok-xyz")])
    w = RunConsentWatcher(app, backend)
    w.poll_once()
    app.pushed[0][1](answer)
    assert backend.responded == [("run_0123456789ab", "tok-xyz", answer)]


def test_respond_failure_does_not_escape(app):
    """A failed respond must not kill the watcher for every later run."""
    class _Boom(_FakeBackend):
        def respond(self, *a, **k):
            raise RuntimeError("registry gone")

    w = RunConsentWatcher(app, _Boom([_parked()]))
    w.poll_once()
    app.pushed[0][1](True)  # must not raise


def test_poll_failure_does_not_escape(app):
    """Same for the poll itself — a dead watcher fails silently forever."""
    class _Boom:
        def list_runs(self, kind=None):
            raise RuntimeError("registry gone")

    RunConsentWatcher(app, _Boom()).poll_once()  # must not raise


# ── auto-merge ──────────────────────────────────────────────────────────────

class _MergeBackend(_FakeBackend):
    """`auto_merge_if_configured` returns (merged, reason, retryable).

    `raise_times` exercises the exception path; `defer_times` exercises the
    RETURNED-failure path, which is the one that looks like success to a
    caller that only guards with try/except.
    """

    def __init__(self, runs, fail_times=0, defer_times=0, decided=False):
        super().__init__(runs)
        self.merged = []
        self.calls = 0
        self._fail_times = fail_times
        self._defer_times = defer_times
        self._decided = decided

    def auto_merge_if_configured(self, run_id):
        self.calls += 1
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError("session not ready")
        if self._decided:
            return False, "not in auto mode", False
        if self._defer_times > 0:
            self._defer_times -= 1
            return False, "no active session", True
        self.merged.append(run_id)
        return True, "merged 42 chars", False


def test_terminal_run_is_merged_once(app):
    b = _MergeBackend([_FakeMeta("run_0123456789ab", "completed")])
    w = RunConsentWatcher(app, b)
    w.poll_once()
    w.poll_once()
    assert b.merged == ["run_0123456789ab"]


def test_a_failed_merge_is_retried_on_the_next_poll(app):
    """Marking merged BEFORE merging made a transient failure permanent.

    The first poll raises (session momentarily unavailable); if the run were
    recorded as merged anyway, every later poll would skip it and the result
    would never reach the conversation.
    """
    b = _MergeBackend([_FakeMeta("run_0123456789ab", "completed")], fail_times=1)
    w = RunConsentWatcher(app, b)
    w.poll_once()
    assert b.merged == []
    w.poll_once()
    assert b.merged == ["run_0123456789ab"]


def test_a_returned_failure_is_retried_not_swallowed(app):
    """`(False, "no active session", retryable=True)` must NOT count as done.

    The contract reports recoverable states by RETURN, not by raising, so a
    watcher guarded only by try/except sails into its success path and marks
    the run merged — dropping the result permanently the moment a poll lands
    while no session is active.
    """
    b = _MergeBackend([_FakeMeta("run_0123456789ab", "completed")], defer_times=1)
    w = RunConsentWatcher(app, b)
    w.poll_once()
    assert b.merged == [], "merge should not have happened yet"
    w.poll_once()
    assert b.merged == ["run_0123456789ab"], "deferred run was never retried"


def test_a_decided_refusal_is_not_retried_forever(app):
    """The mirror image: `retryable=False` must stop the retries.

    "not in auto mode" is the answer under the DEFAULT `collect: "yes"`, so
    treating every False as retryable would re-ask on every poll for the life
    of the process and make the `_merged` guard dead code.
    """
    b = _MergeBackend([_FakeMeta("run_0123456789ab", "completed")], decided=True)
    w = RunConsentWatcher(app, b)
    for _ in range(4):
        w.poll_once()
    assert b.calls == 1, f"decided refusal re-asked {b.calls} times"
    assert b.merged == []


def test_a_failed_merge_does_not_starve_other_runs(app):
    """One bad run must not abort the loop and skip everyone else's prompt."""
    b = _MergeBackend([_FakeMeta("run_bbbbbbbbbbbb", "completed"), _parked()],
                      fail_times=1)
    RunConsentWatcher(app, b).poll_once()
    assert len(app.pushed) == 1, "the parked run still had to prompt"


# ── lifecycle ───────────────────────────────────────────────────────────────

def test_start_is_idempotent(app):
    """`ensure_run_consent_watcher` runs after every /task; no stacked timers."""
    w = RunConsentWatcher(app, _FakeBackend([]))
    w.start()
    w.start()
    w.start()
    assert len(app.intervals) == 1


def test_backend_is_resolved_lazily(app):
    """Constructing a watcher must not build a run registry.

    The TUI should not touch ~/.ppxai/runs for a user who never runs /task.
    """
    w = RunConsentWatcher(app)
    assert w._backend is None

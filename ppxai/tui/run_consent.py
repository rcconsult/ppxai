"""Watch for parked agent runs and raise the Textual consent prompt (T8b).

A `/task` run that wants to spawn a sub-agent parks with
`waiting{kind: "consent", token: ...}` and blocks until answered or until the
TTL denies it. Without a prompt the operator has to *notice* `✋ waiting` in
`/task ls`, which is not an affordance — it is a chore that only works if you
already suspected something was wrong.

Design notes:

- **One watcher, not one per run.** A per-launch watcher would miss runs
  parked by a previous process and picked up by `/task resume`, which is
  exactly when a forgotten park is most likely.
- **One prompt per token.** The resume token identifies the park, so it is
  the natural idempotency key; polling repeatedly must not stack dialogs.
  Same discipline as the VSCode QuickPick watcher.
- **Answering is the only thing that clears a token.** A deferred prompt is
  remembered as prompted, so the operator is not re-interrupted every tick
  for a decision they chose to postpone; `/task respond` and the TTL remain
  the ways it resolves.
- **The poll never raises into the app.** A watcher that dies on a transient
  registry error stops protecting every later run, and its death is silent.
"""

from __future__ import annotations

from typing import Any, Optional

from ..common.logger import get_logger
from ..engine.task_backend import get_task_backend
from .screens.consent import RunConsentScreen

logger = get_logger("tui")

POLL_INTERVAL_S = 2.0

# Statuses that mean the run is done and its result (if any) is final.
_TERMINAL = {"completed", "finalized", "failed", "cancelled"}


class RunConsentWatcher:
    """Polls for parked runs and prompts once per park."""

    def __init__(self, app: Any, backend: Any = None,
                 interval: float = POLL_INTERVAL_S):
        self._app = app
        self._backend = backend
        self._interval = interval
        self._prompted: set[str] = set()
        self._merged: set[str] = set()
        self._timer = None

    @property
    def backend(self):
        # Resolved lazily so constructing a watcher never builds a registry —
        # the TUI should not touch ~/.ppxai/runs until a run surface is used.
        if self._backend is None:
            self._backend = get_task_backend()
        return self._backend

    def start(self) -> None:
        """Begin polling. Idempotent — repeated calls do not stack timers."""
        if self._timer is not None:
            return
        self._timer = self._app.set_interval(self._interval, self.poll_once)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def poll_once(self) -> None:
        """Prompt for newly-parked runs; auto-merge terminal ones. Never raises."""
        try:
            for meta in self.backend.list_runs():
                # U4 "auto": nothing holds the result, so the watcher is the
                # only thing that can put it in the conversation. Mirrors the
                # web client's _autoMergeIfConfigured, which fires on the
                # watcher's terminal render. Once per run.
                if getattr(meta, "status", None) in _TERMINAL \
                        and meta.run_id not in self._merged:
                    # Mark merged only once the outcome is FINAL. This was
                    # wrong twice: marking BEFORE the call made a raised
                    # failure permanent, and then marking on any
                    # non-raising call made a RETURNED failure permanent —
                    # auto_merge_if_configured reports "no active session"
                    # as (False, ..., retryable=True), not an exception.
                    # Either way the result never reached the conversation.
                    # The inner try also keeps one bad run from aborting
                    # the loop and starving the consent prompts for every
                    # OTHER run in this poll.
                    try:
                        merged, why, retryable = \
                            self.backend.auto_merge_if_configured(meta.run_id)
                        # Mark done when it merged, OR when the backend says
                        # the answer is final ("not in auto mode" is the
                        # DEFAULT answer, so retrying it would re-ask every
                        # poll forever). Leave it unmarked only while the
                        # precondition can still arrive — no active session
                        # yet — so the result is not silently dropped.
                        if merged or not retryable:
                            self._merged.add(meta.run_id)
                        else:
                            logger.debug(
                                f"auto-merge deferred for {meta.run_id}: "
                                f"{why}; will retry next poll"
                            )
                    except Exception:  # noqa: BLE001
                        # f-string, NOT printf-style: this logger is
                        # debug(msg, exc_info=False) with no *args, so a
                        # lazy-format call raises TypeError inside the
                        # handler and escapes to the outer except — which
                        # is exactly the starvation this block prevents.
                        logger.debug(
                            f"auto-merge failed for {meta.run_id}; "
                            f"will retry next poll",
                            exc_info=True,
                        )

                token = self._pending_token(meta)
                if token is None or token in self._prompted:
                    continue
                self._prompted.add(token)
                self._prompt(meta, token)
        except Exception:  # noqa: BLE001
            # A watcher that dies takes every future prompt with it, silently,
            # so the traceback matters — but at DEBUG level: this poll runs
            # every couple of seconds and a transient registry error must not
            # become a stream of error-level noise.
            logger.debug("run consent poll failed", exc_info=True)

    @staticmethod
    def _pending_token(meta: Any) -> Optional[str]:
        """The resume token of a run parked for consent, else None."""
        if getattr(meta, "status", None) != "waiting":
            return None
        waiting = getattr(meta, "waiting", None) or {}
        if waiting.get("kind") != "consent":
            return None
        return waiting.get("token") or None

    def _prompt(self, meta: Any, token: str) -> None:

        waiting = getattr(meta, "waiting", None) or {}
        screen = RunConsentScreen(
            run_id=meta.run_id,
            prompt=waiting.get("prompt") or "A run is requesting consent.",
            ttl_s=waiting.get("ttl_s"),
        )

        def _answered(approved: Optional[bool]) -> None:
            if approved is None:
                # Deferred, not refused. Leaving the run parked is correct:
                # the TTL denies it and `/task respond` still works.
                return
            try:
                self.backend.respond(meta.run_id, token=token, approved=approved)
            except Exception:  # noqa: BLE001
                logger.debug("consent respond failed", exc_info=True)

        self._app.push_screen(screen, _answered)

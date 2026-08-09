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

logger = get_logger("tui")

POLL_INTERVAL_S = 2.0


class RunConsentWatcher:
    """Polls for parked runs and prompts once per park."""

    def __init__(self, app: Any, backend: Any = None,
                 interval: float = POLL_INTERVAL_S):
        self._app = app
        self._backend = backend
        self._interval = interval
        self._prompted: set[str] = set()
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
        """Prompt for any newly-parked run. Never raises."""
        try:
            for meta in self.backend.list_runs():
                token = self._pending_token(meta)
                if token is None or token in self._prompted:
                    continue
                self._prompted.add(token)
                self._prompt(meta, token)
        except Exception as e:  # noqa: BLE001
            # A watcher that dies takes every future prompt with it, silently.
            #
            # Logged at debug, with the error in the message: this poll runs
            # every couple of seconds, so a transient registry error must not
            # produce a stream of error-level noise. Note that only
            # `logger.error()` accepts `exc_info` in this project's Logger
            # (common/logger.py:242); debug/info/warning take `msg` alone, so
            # `exc_info=True` here would raise INSIDE the except block and
            # convert a handled failure into an escaping one.
            logger.debug(f"run consent poll failed: {e}")

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
        from .screens.consent import RunConsentScreen

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
            except Exception as e:  # noqa: BLE001
                logger.debug(f"consent respond failed: {e}")

        self._app.push_screen(screen, _answered)

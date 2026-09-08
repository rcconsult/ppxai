"""`/auto` over `POST /command/auto` — debt Item 33.

Item 33 was filed as a `console.print` sweep: three command modules write
user-facing text straight to the Rich console, so anything they print is
invisible to web and VSCode. The audit found the sweep is mostly a non-issue
— and one thing that is worse than the issue.

`ppxai/server/routes/commands.py::execute_command` is an `async def` route
that looks up ANY registered command and calls `spec.handler(...)` directly.
Nothing gates which commands are dispatchable. `handle_agent` ran its loop
with a bare `asyncio.run()`, which raises inside a running event loop — so
`/auto` answered 500 for web and VSCode rather than merely printing to the
wrong place. The Textual TUI hits the same shape, which is why
`commands/coding.py` already carried the guard this now copies.

The print audit itself: of 111 sites, 39 were dead code (removed), 65 are
TUI-only by construction (`handler.py` registers no commands and is reached
only from `rich/main.py`; `_handle_agent_interrupt` blocks on `pt_prompt`),
and the rest restate what the result already carries — the iteration banners
are prefixed into `content`, the completion and max-iteration notices ARE
the returned `message` and status. Exactly one carried information a
non-Rich caller could not otherwise learn, and it is a safety property: the
run has no checkpoint, so `/undo` cannot revert it.
"""

from __future__ import annotations

import asyncio
import gc
from unittest.mock import MagicMock, patch

import pytest

import ppxai.commands  # noqa: F401 — registers the command factory entries
import ppxai.commands.agent as agentmod
from ppxai.commands.context import ServerCommandContext
from ppxai.commands.factory import CommandFactory
from ppxai.commands.results import ResultStatus

TASK = "refactor the parser module carefully"


def _engine(*, checkpoints: bool):
    """An engine whose agent loop terminates immediately."""
    e = MagicMock()
    e.get_agent_config.return_value = {"min_task_words": 2, "max_iterations": 1}
    e.agent_mode = True
    e.create_checkpoint.return_value = "abc123" if checkpoints else None
    e.get_checkpoint_status.return_value = (
        {"enabled": True, "backend": "git"} if checkpoints else {"enabled": False}
    )

    async def chat(prompt, stream=True):  # empty stream → one idle iteration
        return
        yield

    e.chat = chat
    return e


def _run_in_loop(engine):
    """Invoke the handler the way the async HTTP route does."""

    async def route():
        ctx = ServerCommandContext(engine)
        return CommandFactory.get("auto").handler(ctx, TASK)

    return asyncio.run(route())


class TestAutoSurvivesTheServersEventLoop:
    def test_dispatching_from_a_running_loop_does_not_raise(self):
        """The regression: POST /command/auto answered 500, not bad output."""
        result = _run_in_loop(_engine(checkpoints=True))

        assert result.status in (ResultStatus.SUCCESS, ResultStatus.WARNING)
        assert result.message

    @pytest.mark.filterwarnings(
        # Reproducing the bug MEANS leaving `run_agent_loop()` un-awaited:
        # the pre-fix code builds the coroutine and asyncio.run() rejects it
        # before anything can consume it. The leak is the defect being
        # pinned, not a defect in the test, and it is scoped to this case so
        # a real un-awaited coroutine elsewhere still surfaces.
        "ignore:coroutine .*run_agent_loop.* was never awaited:RuntimeWarning"
    )
    def test_without_the_guard_it_raises_the_original_error(self):
        """Pins the mechanism, so a refactor that drops the guard fails here
        rather than in production. Forcing `is_event_loop_running` False
        reproduces the pre-fix code path exactly."""
        with patch.object(agentmod, "is_event_loop_running", lambda: False):
            with pytest.raises(RuntimeError, match="running event loop") as excinfo:
                _run_in_loop(_engine(checkpoints=True))

        # Finalize the orphaned coroutine HERE, while this test's warning
        # filter is in scope. Without this the traceback keeps it alive and
        # its "never awaited" warning surfaces during an unrelated later
        # test's teardown — which is how an unraisable gets blamed on the
        # wrong test.
        del excinfo
        gc.collect()

    def test_the_command_really_is_server_dispatchable(self):
        """If a gate is ever added, this test should be the one to fail and
        say so — the guard above exists BECAUSE nothing filters dispatch."""
        assert CommandFactory.get("auto") is not None


class TestTheCheckpointWarningReachesNonRichClients:
    """The one print carrying information absent from the result."""

    def test_missing_checkpoints_is_reported_in_the_result(self):
        result = _run_in_loop(_engine(checkpoints=False))

        assert "checkpoint" in result.message.lower(), (
            "a web/VSCode caller must learn the run cannot be undone; "
            "before Item 33 this existed only on the server's stdout"
        )
        assert result.metadata.get("checkpoint_warning")
        assert "/undo" in result.metadata["checkpoint_warning"]

    def test_no_warning_when_checkpoints_are_available(self):
        result = _run_in_loop(_engine(checkpoints=True))

        assert "checkpoint" not in result.message.lower()
        assert result.metadata.get("checkpoint_warning") is None


class TestTheDeadRenderersStayGone:
    """39 of the 111 sites were in functions nothing called.

    `_show_active_hints` and `_show_bootstrap_hierarchy` were orphaned by
    `f7ebd004` (v1.15.0), which moved `/context` onto typed results, and sat
    in the tree for four minor versions being counted as debt.
    """

    def test_the_orphaned_context_renderers_are_not_reintroduced(self):
        from ppxai.commands import utility

        for name in ("_show_active_hints", "_show_bootstrap_hierarchy"):
            assert not hasattr(utility, name), (
                f"{name} renders /context output to the Rich console only; "
                "the typed-result path in handle_context replaced it"
            )

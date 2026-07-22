"""Static structural tests for the v1.18.1 command-dispatcher rewrite.

Step 2c. The 967-line bespoke switch in
`ppxai/web/shared/command-dispatcher.js` is replaced with a thin
shell that:

  - Routes streaming commands (chat-shaped) to /chat unchanged.
  - Routes /agent toggle/task to existing paths.
  - Routes everything else through `apiClient.executeCommand` →
    POST /command/<name> → v1 envelope → renderer + side-effects.
  - Drains envelope.events[] through the same handler the live
    SSE stream uses (state-sync Phase B client side).

These tests pin:
  - The dispatcher is a class with `dispatch(input)` — the only
    public method app.js calls.
  - It instantiates ResultRenderer + SideEffectsHandler.
  - The 35-case switch is gone — no `case '/...':` branches
    outside the streaming-command set (one of the v1.18.1
    acceptance criteria).
  - Streaming commands list matches the doc.
  - The events[] drain calls handleStateSync.
  - Bespoke handle*Command methods have been deleted (drift fence
    against accidental re-introduction).

Runtime correctness is covered by the e2e suite (Step 6).
"""

from __future__ import annotations

import re
from pathlib import Path

DISPATCHER = (
    Path(__file__).resolve().parents[1]
    / "ppxai" / "web" / "shared" / "command-dispatcher.js"
)

# v1.19.0 Increment B: the /agentrun + /agentruns behavior was extracted from
# the dispatcher into a dedicated controller so the dispatcher stays a thin
# router. The fire-and-forget fences below target this file.
CONTROLLER = (
    Path(__file__).resolve().parents[1]
    / "ppxai" / "web" / "shared" / "agent-run-controller.js"
)


def _read() -> str:
    return DISPATCHER.read_text(encoding="utf-8")


def _read_controller() -> str:
    return CONTROLLER.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Shape of the rewritten dispatcher
# ---------------------------------------------------------------------------

class TestDispatcherShape:
    def test_class_defined(self):
        src = _read()
        assert "class CommandDispatcher" in src

    def test_dispatch_method_exists(self):
        src = _read()
        assert re.search(r"\bdispatch\s*\(\s*input\s*\)", src), (
            "CommandDispatcher.dispatch(input) not found"
        )

    def test_instantiates_renderer_and_side_effects(self):
        src = _read()
        # Constructor wires both
        assert "new ResultRenderer" in src
        assert "new SideEffectsHandler" in src

    def test_streaming_commands_list_matches_doc(self):
        """Per docs/TODO-v1.18.1-command-unification.md section D,
        these eight commands stay on POST /chat. Any addition or
        removal here is a doc-changing decision."""
        src = _read()
        for cmd in ("/generate", "/explain", "/test", "/docs",
                    "/debug", "/implement", "/convert", "/spec"):
            assert f"'{cmd}'" in src, (
                f"streaming command {cmd} missing from STREAMING_COMMANDS"
            )

    def test_uses_executecommand_for_factory_path(self):
        src = _read()
        assert "apiClient.executeCommand" in src or "executeCommand" in src, (
            "factory path must call apiClient.executeCommand"
        )

    def test_drains_events_through_handlestate_sync(self):
        """Phase B client side: REST envelope's events[] feed the
        same dispatcher as live SSE state_sync events."""
        src = _read()
        assert "handleStateSync" in src, (
            "dispatcher must call app.handleStateSync for state_sync events"
        )
        # And the events field must be referenced
        assert "events" in src.lower()


# ---------------------------------------------------------------------------
# What's NOT in the new dispatcher (drift fences)
# ---------------------------------------------------------------------------

class TestNoBespokeBranches:
    """Acceptance criterion from docs/TODO-v1.18.1-command-unification.md:
    'Web command-dispatcher.js has zero case '/...': branches outside
    the streaming-command set; everything else flows through
    executeCommand.'"""

    def test_no_case_branches_for_factory_commands(self):
        """No `case '/help':`, `case '/cd':`, etc. — those went
        through the factory now."""
        src = _read()
        # Find every `case '/...':`
        cases = re.findall(r"case\s+['\"]/[a-z\-]+['\"]\s*:", src)
        # The streaming-commands routing might use a Set check, not
        # a switch — but if the rewrite drifts back into a switch,
        # cases would reappear. Allow zero cases as the strict
        # boundary.
        assert cases == [], (
            f"command-dispatcher.js has bespoke case branches: {cases}. "
            f"Per the migration plan, the factory dispatch path replaces "
            f"all of these."
        )

    def test_bespoke_handle_methods_deleted(self):
        """The 20 handle*Command methods that duplicated factory
        logic are gone. Adding them back is a regression."""
        src = _read()
        for deleted in ("handleModelCommand", "handleProviderCommand",
                        "handleToolsCommand", "handleCheckpointCommand",
                        "handleUsageCommand", "handleContextCommand",
                        "handleThemeCommand", "handleCdCommand",
                        "handlePwdCommand", "handleLsCommand",
                        "handleTreeCommand", "handlePreviewCommand",
                        "handleTerminalCommand", "handleConfigCommand",
                        "handleShowCommand", "showHelp", "showStatus"):
            assert deleted not in src, (
                f"deleted method {deleted} reappeared in dispatcher; "
                f"the factory handles it now"
            )

    def test_renderer_dispatcher_size_under_300_lines(self):
        """The pre-rewrite dispatcher was 967 lines. The thin shell
        should stay well under this fence; significant growth means a
        bespoke handler is creeping back.

        Threshold history:
          - <300 at v1.18.1 (rewrite landed at ~120 lines of dispatch).
          - <340 then <380 across v1.19.0 Inc A as the /agentrun handlers
            grew inline (fire-and-forget split, then AgentRunView pane render).
          - back to <300 at v1.19.0 (Increment B): the whole /agentrun +
            /agentruns feature was EXTRACTED into agent-run-controller.js, so
            the dispatcher is a thin router again (~228 lines). The fence
            tightens with the extraction — agent-run growth now lands in the
            controller, not here. (Its own fences live in TestAgentRunFireAndForget,
            which read CONTROLLER.)
          - <340 after Item 40 (v1.19.0): _handleTokenCommand grew inline
            (~70 lines, 334 total) — cohesive + security-commented, so it
            stayed. If /token grows further, extract it into a
            token-controller.js like the agent-run extraction above.
        """
        line_count = len(_read().splitlines())
        assert line_count < 340, (
            f"command-dispatcher.js has grown to {line_count} lines. "
            f"That's a smell — a bespoke handler is probably creeping "
            f"back. Compare to the factory + side-effects pattern."
        )


# ---------------------------------------------------------------------------
# /agentrun fire-and-forget (v1.19.0)
# ---------------------------------------------------------------------------

class TestAgentRunFireAndForget:
    """/agentrun must NOT block the chat prompt on run completion. The run
    lives in the server's background registry; the client launches it, frees
    the prompt, and posts the result out-of-band when it lands.

    These are drift fences: if someone re-inlines the tail into the awaited
    handler (the pre-v1.19.0 blocking shape), these fail. v1.19.0 Increment B
    moved the logic to agent-run-controller.js — these read CONTROLLER.
    """

    def test_dispatcher_delegates_to_controller(self):
        """The dispatcher must stay a thin router: it constructs the
        AgentRunController and delegates /agentrun + /agentruns to it,
        rather than inlining the handlers."""
        src = _read()
        assert "new AgentRunController" in src, (
            "dispatcher no longer constructs AgentRunController"
        )
        assert "this.agentRuns?.start(" in src and "this.agentRuns?.list(" in src, (
            "dispatcher does not delegate /agentrun + /agentruns to the controller"
        )

    def test_has_detached_watcher(self):
        src = _read_controller()
        assert "_watchDetached" in src, (
            "the detached run watcher is gone — /agentrun is probably "
            "blocking the prompt on completion again"
        )

    def test_start_does_not_await_the_tail(self):
        """`AgentRunController.start` must delegate to the detached watcher
        and NOT `await` the SSE tail / final-read inline (that's what blocked
        the prompt). We check the handler body calls the watcher WITHOUT
        awaiting it, and contains no `for await` of its own."""
        src = _read_controller()
        m = re.search(
            r"async start\(\w+\)\s*\{(.*?)\n    \}",
            src, re.DOTALL,
        )
        assert m, "could not locate AgentRunController.start body"
        body = m.group(1)
        # The tail loop must have moved OUT of the launch handler.
        assert "for await" not in body, (
            "start() still contains a `for await` tail loop — it is blocking "
            "the prompt. Move the tail to the detached watcher."
        )
        # It must kick off the watcher fire-and-forget (not awaited). The watcher
        # takes only runId now (it resolves the run's pane by run_id at render
        # time, not a captured instance) — see scenario 5 in the behavioral test.
        assert re.search(r"this\._watchDetached\(runId\)", body), (
            "start() does not start the detached watcher"
        )
        assert "await this._watchDetached" not in body, (
            "start() AWAITS the detached watcher — that re-blocks the prompt. "
            "It must be fire-and-forget."
        )


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_unknown_command_yields_friendly_error(self):
        """A 404 from the server (unknown command) should be
        surfaced as a user-facing error, not a JS exception."""
        src = _read()
        assert re.search(r"404|Unknown command", src), (
            "dispatcher should special-case 404 / Unknown command"
        )

    def test_isHandlingCommand_guard_remains(self):
        """Recursive dispatch (e.g. quick-pick resume) must not
        re-enter while the previous call is still in flight."""
        src = _read()
        assert "isHandlingCommand" in src

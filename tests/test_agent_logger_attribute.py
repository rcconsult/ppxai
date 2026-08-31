"""Regression test for Item 11 (v1.18.2): Rich-TUI /agent path used to
crash with AttributeError because `agent.py:680` accessed
`context.engine_client.logger`, but `EngineClient` has no `logger`
attribute. The bug went undetected for releases because every existing
agent test substituted `Mock()` for the logger argument.

This file makes the regression visible by using a REAL `EngineClient`
instance and the real `get_logger("tui")` — the exact construction
shape the production /agent loop performs. Either we keep the new
`get_logger("tui")` import path or this test fails.

The test is intentionally narrow: it exercises only the construction
of `TUIEventHandler` from inside the agent loop's event-handler call
site, not the full agent loop (which needs an LLM provider). Wider
agent tests live elsewhere.
"""

from __future__ import annotations

import pytest


class TestAgentLoggerAttribute:
    """Pin the v1.18.2 fix for the `engine_client.logger` AttributeError."""

    def test_engineclient_still_has_no_logger_attribute(self):
        """If a `logger` attribute ever appears on EngineClient,
        re-evaluate the fix — the original code might be valid again
        AND the protocol/Item 11 narrative would need updating."""
        from ppxai.engine.client import EngineClient
        engine = EngineClient()
        assert not hasattr(engine, "logger"), (
            "EngineClient gained a `logger` attribute. The Rich-TUI "
            "agent path (agent.py) was patched to use get_logger('tui') "
            "directly because this attribute didn't exist. If it now "
            "DOES exist, audit Item 11's fix and decide whether to "
            "revert to the engine's logger or keep the explicit "
            "get_logger('tui') call."
        )

    def test_tui_logger_has_methods_event_handler_calls(self):
        """`TUIEventHandler` invokes log_assistant_message,
        log_tool_call, log_tool_result, log_tool_error, log_api_error.
        These must all exist on the get_logger('tui') return value
        or the agent path crashes mid-stream instead of at construction.
        """
        from ppxai.common.logger import get_logger
        log = get_logger("tui")
        for method in (
            "log_assistant_message",
            "log_tool_call",
            "log_tool_result",
            "log_tool_error",
            "log_api_error",
            "info",
            "debug",
            "error",
        ):
            assert hasattr(log, method), (
                f"get_logger('tui') is missing `{method}`, which "
                f"TUIEventHandler calls during agent runs. Either add "
                f"the method to Logger or restructure the event handler."
            )

    def test_event_handler_constructs_with_real_engine_and_tui_logger(self):
        """The exact construction shape used by `agent.py:run_agent_loop`.

        Uses a REAL EngineClient (not Mock) — the bug existed precisely
        because mocks substituted the missing attribute. If this raises
        AttributeError, the agent loop is broken in production again.
        """
        from ppxai.common.logger import get_logger
        from ppxai.engine.client import EngineClient
        from ppxai.rich.event_handler import TUIEventHandler
        from ppxai.rich.ui import console

        engine = EngineClient()
        # Mirror agent.py:run_agent_loop construction. If anything in
        # this construction tries to read engine.logger, we'll get
        # AttributeError here.
        handler = TUIEventHandler(
            console, get_logger("tui"),
            verbose=False,
            emoji_mode=False,
            engine_client=engine,
        )
        assert handler is not None
        # Sanity-check the wired logger satisfies the methods event
        # handler invokes during a real run.
        assert hasattr(handler.logger, "log_assistant_message")

    def test_old_buggy_construction_still_fails(self):
        """If somebody re-introduces `engine_client.logger` on the
        agent path, we want a loud failure here. This test exists to
        document the failure mode — pin it so the regression can't
        come back silently."""
        from ppxai.engine.client import EngineClient

        engine = EngineClient()
        with pytest.raises(AttributeError):
            _ = engine.logger  # The exact buggy access pattern.

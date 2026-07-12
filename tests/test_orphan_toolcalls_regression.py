"""v1.19.1 regression: orphan assistant.tool_calls handling.

Two defects, both surfaced by a live VSCode trial (2026-07-12) whose tools-
enabled chats 400'd repeatedly with OpenAI's
    "An assistant message with 'tool_calls' must be followed by tool messages
     responding to each 'tool_call_id'. ... call_XXXX did not have response"
and whose user prompts then silently vanished
    ("Session alternation fix: DROPPED UNSENT USER PROMPT ... 'What is the
     capital of France?'").

Bug A — data loss: stripping a tail orphan assistant.tool_calls exposed a
trailing user that the model had already begun answering (via the removed
tool_calls). The trailing-user drop then deleted that *real* prompt as if it
were an unsent draft, emptying the history. Fix: keep an orphan-exposed
trailing user so the next turn re-answers it.

Bug B — no mid-loop re-validation: the alternation pre-flight runs once before
the chat_with_tools loop, so an orphan created mid-turn could reach a strict
provider on a later iteration. Fix: strip orphans from the OUTBOUND message
list before each in-loop provider call (session state untouched).
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from ppxai.engine.session import SessionManager, strip_orphan_tool_calls
from ppxai.engine.types import Message, Event, EventType, ProviderCapabilities
from ppxai.engine.model_profiles import ModelProfile, ToolCallingProfile

from tests.test_tool_messages import (
    MockProvider, MockToolManager, MockChatContext, collect_events,
)


def _a_tc(*call_ids, content=""):
    return Message("assistant", content, tool_calls=[
        {"id": c, "type": "function",
         "function": {"name": "read_file", "arguments": "{}"}}
        for c in call_ids])


def _tool(call_id, content="result"):
    return Message("tool", content, tool_call_id=call_id)


def _orphans(messages):
    """(index, missing_ids) for every assistant.tool_calls whose ids are not all
    answered by the immediately following tool messages — the strict-provider 400."""
    out = []
    for i, m in enumerate(messages):
        if m.role == "assistant" and m.tool_calls:
            expected = {tc.get("id") for tc in m.tool_calls if tc.get("id")}
            seen = set()
            j = i + 1
            while j < len(messages) and messages[j].role == "tool":
                if messages[j].tool_call_id:
                    seen.add(messages[j].tool_call_id)
                j += 1
            if expected - seen:
                out.append((i, sorted(expected - seen)))
    return out


def _new_mgr(messages):
    d = Path(tempfile.mkdtemp())
    mgr = SessionManager(sessions_dir=d, exports_dir=d)
    mgr.messages = list(messages)
    return mgr


# ---------------------------------------------------------------------------
# Bug A — orphan-exposed trailing user is preserved (no data loss)
# ---------------------------------------------------------------------------

class TestBugA_OrphanExposedUserPreserved:

    def test_tail_orphan_keeps_the_only_user_prompt(self):
        """[user, assistant(orphan tool_calls)] must NOT empty the history —
        the user's question was answered-in-progress, not an unsent draft."""
        mgr = _new_mgr([
            Message("user", "What is the capital of France?"),
            _a_tc("call_A"),
        ])
        removed = mgr.validate_and_fix_alternation()

        roles = [m.role for m in mgr.messages]
        assert roles == ["user"], f"user prompt lost; got {roles}"
        assert mgr.messages[0].content == "What is the capital of France?"
        assert _orphans(mgr.messages) == []   # orphan still stripped
        assert removed == 1                    # only the orphan, not the user

    def test_trial_shape_keeps_trailing_user_and_valid_pairs(self):
        """The real trial tail: a valid tool history plus a tool-interrupted
        tail orphan. The trailing user prompt survives, orphan is gone."""
        mgr = _new_mgr([
            Message("user", "start"),
            _a_tc("call_1"), _tool("call_1"),
            _a_tc("call_2"), _tool("call_2"),
            Message("user", "there is an error in the web app"),
            _a_tc("call_X"),      # in-loop orphan added as tail
        ])
        mgr.validate_and_fix_alternation()

        assert mgr.messages[-1].role == "user"
        assert "error in the web app" in mgr.messages[-1].content
        assert _orphans(mgr.messages) == []

    def test_genuine_unsent_trailing_user_still_dropped(self):
        """Guard is narrow: a trailing user NOT exposed by an orphan strip
        (a real mid-turn-saved draft) is still dropped as before."""
        mgr = _new_mgr([
            Message("user", "q1"),
            Message("assistant", "a1"),
            Message("user", "unsent draft"),   # no orphan involved
        ])
        mgr.validate_and_fix_alternation()
        roles = [m.role for m in mgr.messages]
        assert roles == ["user", "assistant"], f"expected draft dropped; got {roles}"


# ---------------------------------------------------------------------------
# Bug B — outbound orphan guard fires inside the tool loop
# ---------------------------------------------------------------------------

class TestBugB_OutboundOrphanGuard:

    def test_helper_strips_orphan_and_is_pure(self):
        msgs = [
            Message("user", "q"),
            _a_tc("call_A"),                 # orphan (no tool reply)
            Message("user", "next"),
        ]
        cleaned, removed = strip_orphan_tool_calls(msgs)
        assert removed == 1
        assert _orphans(cleaned) == []
        assert len(msgs) == 3               # input not mutated

    @pytest.mark.asyncio
    async def test_mid_loop_orphan_never_reaches_provider(self):
        """With the once-per-turn pre-flight neutered, an orphan sitting in the
        session must still not reach the provider — the in-loop outbound guard
        strips it before the send."""
        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[[Event(EventType.STREAM_END, "Done.")]],
        )
        tm = MockToolManager(tools={"read_file": lambda path="": "x"})
        ctx = MockChatContext(provider=provider, model="gpt-5.2", tool_manager=tm)

        # Neuter the pre-flight so ONLY the loop guard can clean the orphan.
        ctx.session.validate_and_fix_alternation = lambda: 0

        ctx.session.add_message(Message("user", "real question"))
        ctx.session.add_message(_a_tc("call_orphan"))        # mid-loop orphan
        ctx.session.add_message(Message("user", "follow up"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native", parallel_tool_calls=True),
            )
            await collect_events(ctx)

        assert provider.chat_calls, "provider was never called"
        sent = provider.chat_calls[0]["messages"]
        assert _orphans(sent) == [], (
            f"orphan reached the provider on the wire: {_orphans(sent)}"
        )

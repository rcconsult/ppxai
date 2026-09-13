"""A discarded parallel tool call says so in the log.

v1.19.3. `chat_with_tools` keeps only the first native tool call when the
model's facts row says `parallel_tool_calls=False`:

    if not facts.parallel_tool_calls:
        parsed_calls = parsed_calls[:1]

That branch throws away output the model already produced, and it was the
only branch in that function which dropped work without logging it — sitting
directly beside the `fallback_on_empty` branch, which does log. The v1.19.2
fact-row sweep then found fifteen shipped rows pinned at the conservative
floor whose models emit several calls per turn. Every one of those turns lost
calls here and left no trace: the operator's only symptom was a tool loop
taking twice the round trips it needed, with nothing in `~/.ppxai/logs` to
explain it. That is how it was eventually found — from the outside, by
comparing the same model id across two providers.

`tests/test_tool_messages.py::test_single_tool_when_parallel_false` already
pins that only one call executes. These tests pin that the drop is VISIBLE,
which is a separate property: that test passes against the silent version.

The log is asserted through a patched module logger rather than `caplog`
because `ppxai.common.logger.Logger` swaps in a no-op logger when debug
logging is off, so a `caplog` assertion would pass or fail depending on host
state rather than on this code.

**The mock is autospec'd on purpose.** The first version of this file used a
bare `MagicMock`, which accepts any call signature — so it swallowed
`logger.warning("...%d...", n, model, kept, dropped)` even though
`common.logger.Logger.warning` is `(msg, exc_info=False)`: this codebase runs
two logger populations side by side, and only the `logging.getLogger` half
takes %-args. The real call raised `TypeError` INSIDE the tool loop, these
tests passed anyway, and an unrelated pre-existing test
(`test_single_tool_when_parallel_false`) is what caught it. A mock that does
not enforce the signature it stands in for is not a test of the call.

`spec=` is not a weaker `autospec` — it answers a DIFFERENT question. It
constrains which attributes exist, not how they may be called, which is
exactly why `MagicMock(spec=Logger)` fooled a correction to this file that
was written to fix the first mistake. A reader who takes "use `spec=`" as
the lesson here will hit this again; the lesson is `create_autospec`.
"""

from unittest.mock import create_autospec, patch

import pytest

import ppxai.engine.chat as chat_mod
from ppxai.common.logger import Logger
from ppxai.engine.model_facts import ModelFacts
from ppxai.engine.types import Event, EventType, Message, ProviderCapabilities
from tests.test_tool_messages import (
    MockChatContext,
    MockProvider,
    MockToolManager,
    collect_events,
)


def _spec_logger():
    """A logger double that enforces `common.logger.Logger`'s real signature.

    `create_autospec`, NOT `MagicMock(spec=Logger)`. Measured against the exact
    call shape that broke (`warning(msg, n, model, kept, dropped)`):

        MagicMock()             -> accepted, bug hidden
        MagicMock(spec=Logger)  -> accepted, bug hidden  (spec checks that the
                                   ATTRIBUTE exists, not how it may be called)
        create_autospec(...)    -> TypeError: too many positional arguments
        the real Logger         -> TypeError: Logger.warning() takes from 2 to 3
                                   positional arguments but 6 were given

    So only autospec stands in for the real object here.
    """
    return create_autospec(Logger, instance=True)


def _two_call_provider(final_text="done"):
    return MockProvider(
        capabilities=ProviderCapabilities(),
        responses=[
            [
                Event(EventType.TOOL_CALL, {
                    "tool": "read_file",
                    "arguments": {"path": "a.py"},
                    "tool_call_id": "call_1",
                }),
                Event(EventType.TOOL_CALL, {
                    "tool": "list_files",
                    "arguments": {"path": "."},
                    "tool_call_id": "call_2",
                }),
                Event(EventType.STREAM_END, ""),
            ],
            [Event(EventType.STREAM_END, final_text)],
        ],
    )


def _ctx(provider, model="test-model"):
    tm = MockToolManager(tools={
        "read_file": lambda path="": f"contents of {path}",
        "list_files": lambda path="": f"listing of {path}",
    })
    ctx = MockChatContext(provider=provider, model=model, tool_manager=tm)
    ctx.session.add_message(Message("user", "read a.py and list files"))
    return ctx


class TestTheDropIsLogged:

    @pytest.mark.asyncio
    async def test_dropping_a_call_emits_a_warning(self):
        provider = _two_call_provider()
        provider.facts = ModelFacts(tool_mode="native", parallel_tool_calls=False)
        ctx = _ctx(provider, model="some-serial-model")

        with patch.object(chat_mod, "logger", _spec_logger()) as log:
            await collect_events(ctx)

        assert log.warning.called, (
            "a parallel tool call was discarded and nothing was logged — the "
            "defect this test exists for"
        )

    @pytest.mark.asyncio
    async def test_the_warning_names_the_model_and_both_tools(self):
        """Assert the CONTENT, not just that something was logged.

        A bare "was it called" test passes against a message that says
        "dropped a call" and nothing else, which would leave the reader with
        the same question they started with: which model, and what was lost.
        """
        provider = _two_call_provider()
        provider.facts = ModelFacts(tool_mode="native", parallel_tool_calls=False)
        ctx = _ctx(provider, model="some-serial-model")

        with patch.object(chat_mod, "logger", _spec_logger()) as log:
            await collect_events(ctx)

        rendered = log.warning.call_args.args[0]

        assert "some-serial-model" in rendered, "the reader must know WHICH model"
        assert "read_file" in rendered, "the kept call"
        assert "list_files" in rendered, "the DROPPED call — the lost work"
        assert "parallel_tool_calls" in rendered, (
            "the message must name the fact row, which is what the reader has "
            "to change; naming only the symptom leaves them nowhere to go"
        )

    @pytest.mark.asyncio
    async def test_a_single_call_logs_nothing(self):
        """No cry-wolf: a serial model emitting one call dropped nothing.

        Without the `if dropped:` guard this fires on every turn of every
        serial model, and a warning that is always present is one nobody
        reads — which would leave the real event as invisible as before.
        """
        provider = MockProvider(
            capabilities=ProviderCapabilities(),
            responses=[
                [
                    Event(EventType.TOOL_CALL, {
                        "tool": "read_file",
                        "arguments": {"path": "a.py"},
                        "tool_call_id": "call_1",
                    }),
                    Event(EventType.STREAM_END, ""),
                ],
                [Event(EventType.STREAM_END, "done")],
            ],
        )
        provider.facts = ModelFacts(tool_mode="native", parallel_tool_calls=False)
        ctx = _ctx(provider)

        with patch.object(chat_mod, "logger", _spec_logger()) as log:
            await collect_events(ctx)

        assert not log.warning.called

    @pytest.mark.asyncio
    async def test_a_parallel_model_logs_nothing_and_keeps_both(self):
        """The happy path stays silent, and the calls still both execute."""
        provider = _two_call_provider()
        provider.facts = ModelFacts(tool_mode="native", parallel_tool_calls=True)
        ctx = _ctx(provider)

        with patch.object(chat_mod, "logger", _spec_logger()) as log:
            events = await collect_events(ctx)

        assert not log.warning.called
        tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(tool_calls) == 2


class TestTheDropItselfIsUnchanged:
    """The fix is observability only — the send path must behave as before."""

    @pytest.mark.asyncio
    async def test_only_the_first_call_still_executes(self):
        provider = _two_call_provider()
        provider.facts = ModelFacts(tool_mode="native", parallel_tool_calls=False)
        ctx = _ctx(provider)

        with patch.object(chat_mod, "logger", _spec_logger()):
            events = await collect_events(ctx)

        tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(tool_calls) == 1
        assert tool_calls[0].data["tool"] == "read_file"

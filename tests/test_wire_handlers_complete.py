"""ADR 0012 W4 — all three wires are handlers; the validator covers all three.

**Closes debt Item 62, both halves.**

(a) `assert_wire_blocks_clean` had exactly ONE call site — inside
`BaseProvider._convert_messages`, the chat-completions emitter — so two of
three wires reached the network unchecked. W2 gave it a second (responses);
W4 gives it the third (generate_content). The fence below asserts it on
*every* registered handler rather than on a list someone has to remember to
extend: a fourth wire that forgets the validator fails here on the day it is
written.

(b) `_convert_messages` was one protocol's emitter installed as the shared
base's default, typed `-> List[Dict[str, Any]]`. `GeminiProvider` had to
override it returning a `tuple` — a Liskov violation the type checker could
not see, because the base's annotation was one wire's shape imposed on all of
them. Each wire now owns its converter and declares its own return type; the
override is deleted, not narrowed.
"""

import inspect

import pytest

from ppxai.engine.providers.base import BaseProvider
from ppxai.engine.providers.gemini import GeminiProvider
from ppxai.engine.providers.wire import HANDLERS, get_handler
from ppxai.engine.providers.wire.chat_completions import ChatCompletionsHandler
from ppxai.engine.providers.wire.generate_content import GenerateContentHandler
from ppxai.engine.providers.wire.responses import ResponsesHandler
from ppxai.engine.types import Message

#: A block that is legal-looking but carries a non-spec top-level key. The
#: validator checks each block's TOP-LEVEL keys against the wire spec — a key
#: nested inside `image_url` is NOT what it looks at, which is how an early
#: probe of this fence reported "not caught" against correctly wired code.
POLLUTED = [{"type": "image_url", "image_url": {"url": "x"}, "name": "leak.png"}]


class TestEveryRegisteredHandlerValidates:
    """Not a hand-maintained list — every handler in the registry."""

    @pytest.mark.parametrize("name", sorted(HANDLERS))
    def test_the_handler_rejects_a_polluted_block(self, name):
        handler = get_handler(name)
        msg = Message(role="user", content=POLLUTED)
        with pytest.raises(AssertionError, match="ADR 0006 wire-format violation"):
            handler.convert_messages([msg])

    @pytest.mark.parametrize("name", sorted(HANDLERS))
    def test_the_handler_accepts_a_clean_block(self, name):
        handler = get_handler(name)
        msg = Message(role="user", content=[{"type": "text", "text": "hi"}])
        handler.convert_messages([msg])  # no raise

    @pytest.mark.parametrize("name", sorted(HANDLERS))
    def test_the_validator_is_called_from_the_converter_source(self, name):
        """Belt and braces: the call is IN the converter, not merely reachable.

        A handler could pass the tests above by validating somewhere
        incidental. Item 62 (a) was precisely a validator that existed and
        was not called on two of three paths, so the fence checks the source
        as well as the behaviour.
        """
        src = inspect.getsource(type(get_handler(name)))
        assert "assert_wire_blocks_clean(" in src, name

    def test_all_three_live_wires_are_registered(self):
        assert sorted(HANDLERS) == [
            "chat_completions",
            "generate_content",
            "responses",
        ]


class TestConversionIsProtocolOwned:
    """(b): no shared method left for two wires to disagree about."""

    def test_gemini_no_longer_overrides_the_base_converter(self):
        """The Liskov violation is DELETED, not narrowed.

        `GeminiProvider._convert_messages` returned `tuple` against a base
        annotated `List[Dict[str, Any]]`. It is gone; Gemini asks its own
        handler, whose return type is honestly its own shape.
        """
        assert "_convert_messages" not in vars(GeminiProvider)

    def test_each_wire_declares_its_own_return_shape(self):
        """Three wires, three shapes — which is why the contract says `Any`."""
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="hi"),
        ]
        cc = ChatCompletionsHandler.convert_messages(msgs)
        assert isinstance(cc, list) and cc[0]["role"] == "system"

        instructions, items = ResponsesHandler.convert_messages(msgs)
        assert instructions == "sys" and items[0]["role"] == "user"

        contents, system_instruction = GenerateContentHandler.convert_messages(msgs)
        assert system_instruction == "sys"
        assert contents[0]["role"] == "user" and "parts" in contents[0]

    def test_the_base_delegates_rather_than_implementing(self):
        """`BaseProvider._convert_messages` is now a delegation, not an emitter.

        It stays reachable because most providers speak this wire, but the
        BODY lives in the handler — one protocol's converter delegated to,
        not one protocol's emitter installed as everyone's default.
        """
        src = inspect.getsource(BaseProvider._convert_messages)
        assert 'get_handler("chat_completions")' in src
        assert "flatten_uploaded_file_blocks" not in src

    def test_base_and_handler_agree_exactly(self):
        """Delegation must not have changed the chat-completions wire."""
        msgs = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="", tool_calls=[{"id": "c1"}]),
            Message(role="tool", content="r", tool_call_id="c1"),
        ]

        class _P(BaseProvider):
            def __init__(self):
                pass

            async def chat(self, *a, **k):  # pragma: no cover - unused
                raise NotImplementedError

            def oneshot(self, *a, **k):  # pragma: no cover - unused
                raise NotImplementedError

        assert _P()._convert_messages(msgs) == ChatCompletionsHandler.convert_messages(
            msgs
        )


class TestGeminiConversionSurvivedTheMove:
    """The pairing hazard is the reason this wire cannot share a converter."""

    def test_tool_results_still_pair_by_function_name(self):
        """Gemini's wire has NO id on a function response — pairing is by NAME.

        The id -> name mapping is resolved from the preceding assistant turn.
        This is the load-bearing quirk the move had to preserve exactly.
        """
        msgs = [
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {"id": "call_1", "function": {"name": "lookup", "arguments": "{}"}}
                ],
            ),
            Message(role="tool", content="result", tool_call_id="call_1"),
        ]
        contents, _ = GenerateContentHandler.convert_messages(msgs)
        response_part = contents[-1]["parts"][0]["function_response"]
        assert response_part["name"] == "lookup"

    def test_an_unpaired_tool_result_degrades_to_a_user_turn(self):
        """Rather than emitting an invalid function_response."""
        msgs = [Message(role="tool", content="orphan", tool_call_id="unknown")]
        contents, _ = GenerateContentHandler.convert_messages(msgs)
        assert contents[-1]["role"] == "user"
        assert "function_response" not in contents[-1]["parts"][0]

"""ADR 0012 W2 — the Responses wire as a handler.

Two fences, for the two halves of the migration:

**Step 1 (extract, no behaviour change).** The outgoing
`client.responses.create(**kwargs)` arguments must be byte-identical to what
`OpenAINativeProvider._chat_responses_api` / `._oneshot_responses` built
before the move. A spy on the client captures them; the expectations here are
the literal kwargs recorded from the pre-move code, so this fails if the
extraction changed the wire even in a key order-independent way.

**Step 2 (make the protocol field load-bearing).** Routing must read
`ModelFacts.wire_protocol` rather than a hardcoded prefix tuple, which means
(a) declared and routed agree for every built-in profile — the check that
would have caught all three measured drifts — and (b) an operator override of
`wire_protocol` actually changes the outgoing request, which `api_path` never
did (debt Item 61).
"""

import asyncio
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.model_facts import ModelFacts, shipped_facts_for_model
from ppxai.engine.model_profiles import BUILTIN_PROFILES
from ppxai.engine.providers.openai_native import (
    OpenAINativeProvider,
    PROMPT_BASED_MODEL_PREFIXES,
    RESPONSES_API_PREFIXES,
    RESPONSES_WIRE_GLOBS,
)
from ppxai.engine.providers.wire import HANDLERS, get_handler
from ppxai.engine.providers.wire.responses import ResponsesHandler
from ppxai.engine.types import Message


@pytest.fixture
def provider():
    with patch("ppxai.engine.providers.openai_native.OpenAI"):
        p = OpenAINativeProvider(api_key="test-key")
    p.client = MagicMock()
    return p


def _spy_kwargs(provider):
    """Return the kwargs of the single responses.create call."""
    assert provider.client.responses.create.call_count == 1, (
        f"expected exactly one responses.create call, got "
        f"{provider.client.responses.create.call_count}"
    )
    return provider.client.responses.create.call_args.kwargs


class TestRequestIsByteIdenticalAfterExtraction:
    """The lifted code must build the same request it built in the provider."""

    MESSAGES = [
        Message(role="system", content="be brief"),
        Message(role="user", content="hello"),
    ]

    def test_oneshot_kwargs_unchanged(self, provider):
        provider.client.responses.create.return_value = MagicMock(
            output=[], output_text="hi", usage=None, model="gpt-5.1-codex"
        )
        get_handler("responses").oneshot(
            provider, self.MESSAGES, "gpt-5.1-codex", max_tokens=256
        )
        kwargs = _spy_kwargs(provider)

        # Recorded from the pre-move `_oneshot_responses`.
        assert kwargs == {
            "model": "gpt-5.1-codex",
            "input": [{"role": "user", "content": "hello"}],
            "instructions": "be brief",
            "max_output_tokens": 256,
            "stream": False,
        }

    def test_chat_kwargs_unchanged_without_tools(self, provider):
        provider.client.responses.create.return_value = iter([])

        async def _drain():
            return [
                ev
                async for ev in get_handler("responses").chat(
                    provider, self.MESSAGES, "gpt-5.1-codex", stream=True, tools=None
                )
            ]

        asyncio.run(_drain())
        kwargs = _spy_kwargs(provider)

        assert kwargs["model"] == "gpt-5.1-codex"
        assert kwargs["input"] == [{"role": "user", "content": "hello"}]
        assert kwargs["instructions"] == "be brief"
        assert kwargs["stream"] is True
        # No tools requested and web search off -> no `tools` key at all,
        # exactly as the pre-move code left it.
        assert "tools" not in kwargs

    def test_web_search_preview_still_attaches(self, provider):
        provider.enable_web_search = True
        provider.client.responses.create.return_value = iter([])

        async def _drain():
            return [
                ev
                async for ev in get_handler("responses").chat(
                    provider, self.MESSAGES, "gpt-5.1-codex", stream=True, tools=None
                )
            ]

        asyncio.run(_drain())
        assert _spy_kwargs(provider)["tools"] == [{"type": "web_search_preview"}]

    def test_oneshot_sends_no_tools_and_no_web_search(self, provider):
        """The oneshot variant never attached tools; keep it that way."""
        provider.enable_web_search = True
        provider.client.responses.create.return_value = MagicMock(
            output=[], output_text="hi", usage=None, model="gpt-5.1-codex"
        )
        get_handler("responses").oneshot(provider, self.MESSAGES, "gpt-5.1-codex", 64)
        assert "tools" not in _spy_kwargs(provider)


class TestRoutingReadsTheFact:
    """Step 2: `wire_protocol` is the router, not the prefix tuple."""

    def test_declared_and_routed_agree_for_every_builtin_profile(self):
        """The check that would have caught all three measured drifts.

        Before W2 the declared table (`api_path` -> `wire_protocol`) and the
        actual router (`RESPONSES_API_PREFIXES`) disagreed on
        `gpt-5.3-codex`, `gpt-5.2-pro` and `gpt-5-pro`. Now there is only one
        source, so the only way to disagree is to add a glob to one table and
        not the other.
        """
        disagreements = []
        for name in sorted(BUILTIN_PROFILES):
            facts = shipped_facts_for_model(name, OpenAINativeProvider.shipped_model_facts)
            declared = facts.wire_protocol
            seeded = name.rstrip("*").lower().startswith(
                tuple(g.rstrip("*") for g in RESPONSES_WIRE_GLOBS)
            )
            routed = "responses" if seeded else "chat_completions"
            if declared != routed and (declared == "responses" or routed == "responses"):
                disagreements.append((name, declared, routed))
        assert disagreements == [], (
            "declared wire_protocol disagrees with the seed globs for: "
            f"{disagreements}"
        )

    @pytest.mark.parametrize(
        "model",
        ["gpt-5.1-codex", "gpt-5.3-codex", "gpt-5-pro", "gpt-5.2-pro", "gpt-5.5-pro"],
    )
    def test_every_responses_model_routes_to_responses(self, provider, model):
        assert provider._wire_for(model) == "responses"

    @pytest.mark.parametrize("model", ["gpt-4o", "gpt-4.1", "o4-mini", "gpt-5.5"])
    def test_chat_models_route_to_chat_completions(self, provider, model):
        assert provider._wire_for(model) == "chat_completions"

    def test_the_three_measured_drifts_are_resolved(self, provider):
        """Each row of the drift table, asserted by name.

        gpt-5.3-codex was declared `responses` and routed to chat — a live
        404 on the oneshot path, which has no auto-fallback. The two pro
        models were declared `chat` and routed to responses; the router was
        right (commit 5e1ace2f added them after a measured "not a chat
        model" 404), so the table now says `responses` for all three.
        """
        assert provider._wire_for("gpt-5.3-codex") == "responses"
        assert provider._wire_for("gpt-5.2-pro") == "responses"
        assert provider._wire_for("gpt-5-pro") == "responses"

    def test_gpt_5_5_pro_reached_neither_mechanism_before(self, provider):
        """Found by the same sweep: a pro model no table sent to Responses.

        The prefix tuple lists `gpt-5-pro` but not `gpt-5.5-pro`, and its
        profile declares `chat`. It was registered (c4b6f431) without either
        table being updated.

        Its row is by ANALOGY with its siblings, not separately probed —
        nothing ever routed it to Chat Completions, so no 404 was ever
        observed for this model specifically. Pinned here so the assumption
        is visible and falsifiable rather than buried in a glob.
        """
        assert not "gpt-5.5-pro".startswith(RESPONSES_API_PREFIXES)
        assert provider._wire_for("gpt-5.5-pro") == "responses"


class TestOperatorOverrideIsLoadBearing:
    """Debt Item 61: the declared field was config-overridable AND inert."""

    def test_override_to_responses_changes_the_outgoing_request(self, provider):
        """A model that ships `chat_completions`, forced onto the other wire."""
        assert provider._wire_for("gpt-4o") == "chat_completions"

        forced = replace(shipped_facts_for_model("gpt-4o"), wire_protocol="responses")
        with patch.object(provider, "get_facts_for_model", return_value=forced):
            assert provider._wire_for("gpt-4o") == "responses"

            provider.client.responses.create.return_value = MagicMock(
                output=[], output_text="ok", usage=None, model="gpt-4o"
            )
            provider.oneshot(prompt="hi", model="gpt-4o", max_tokens=32)

        # The override reached the WIRE, not just the resolver: the request
        # went to responses.create, and chat.completions.create was untouched.
        assert _spy_kwargs(provider)["model"] == "gpt-4o"
        assert provider.client.chat.completions.create.call_count == 0

    def test_override_to_chat_completions_changes_the_outgoing_request(self, provider):
        """And the other direction — a Responses model forced onto chat."""
        assert provider._wire_for("gpt-5.1-codex") == "responses"

        forced = replace(
            shipped_facts_for_model("gpt-5.1-codex"), wire_protocol="chat_completions"
        )
        with patch.object(provider, "get_facts_for_model", return_value=forced):
            msg = MagicMock()
            msg.content = "ok"
            provider.client.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=msg, finish_reason="stop")],
                usage=None,
                model="gpt-5.1-codex",
            )
            provider.oneshot(prompt="hi", model="gpt-5.1-codex", max_tokens=32)

        assert provider.client.chat.completions.create.call_count == 1
        assert provider.client.responses.create.call_count == 0


class TestTheTwoSeedSetsStayDisjoint:
    """`shipped_model_facts` merges two glob sets into one dict.

    Each set states a DIFFERENT fact about a model: `PROMPT_BASED_MODEL_PREFIXES`
    sets `tool_mode`, `RESPONSES_WIRE_GLOBS` sets `wire_protocol`. Because the
    merge is `{**a, **b}`, a model matching both would not get a row stating
    both facts — the second set's row would replace the first's wholesale and
    the prompt-based measurement would be silently lost.

    They are disjoint today. This is the fence that keeps them that way; the
    fix if it ever trips is one row stating both facts, not a merge policy.
    """

    def test_no_model_matches_a_glob_from_both_sets(self):
        collisions = []
        for prefix in PROMPT_BASED_MODEL_PREFIXES:
            for glob in RESPONSES_WIRE_GLOBS:
                stem = glob.rstrip("*")
                if prefix.startswith(stem) or stem.startswith(prefix):
                    collisions.append((prefix, glob))
        assert collisions == [], (
            f"{collisions} match both seed sets. The dict merge would drop the "
            "prompt_based row entirely rather than state both facts. Write one "
            "explicit row carrying tool_mode AND wire_protocol instead."
        )

    def test_every_row_states_exactly_the_fact_its_set_owns(self):
        """A wire row must not silently carry a tool_mode decision, or vice versa.

        The wire rows override ONLY `wire_protocol`, which is why `codex*` and
        `gpt-6-pro*` keep the conservative `prompt_based` floor (they have no
        built-in profile) while still routing to Responses. That asymmetry is
        Q0a: a protocol is knowable from the endpoint, tool support is not.
        """
        table = OpenAINativeProvider.shipped_model_facts
        for glob in RESPONSES_WIRE_GLOBS:
            assert table[glob].wire_protocol == "responses", glob
            floor = shipped_facts_for_model(glob.rstrip("*"))
            assert table[glob].tool_mode == floor.tool_mode, (
                f"{glob} changed tool_mode as a side effect of stating its wire"
            )
        for prefix in PROMPT_BASED_MODEL_PREFIXES:
            row = table[prefix + "*"]
            assert row.tool_mode == "prompt_based", prefix
            assert row.wire_protocol == "chat_completions", prefix


class TestHandlerRegistry:
    def test_unknown_protocol_raises_rather_than_defaulting(self):
        """A silent fallback is how `api_path` stayed inert for three releases."""
        with pytest.raises(KeyError, match="no wire-protocol handler"):
            get_handler("generate_content")

    def test_responses_handler_is_registered_under_its_own_name(self):
        assert get_handler("responses") is HANDLERS["responses"]
        assert ResponsesHandler.name == "responses"


class TestValidatorCoversThisWire:
    """ADR 0006 sentinel, Item 62 fix (a): it had ONE call site before W2."""

    @pytest.mark.parametrize("role", ["user", "assistant", "tool"])
    def test_polluted_block_is_rejected_on_the_responses_wire(self, role):
        bad = [{"type": "image_url", "image_url": {"url": "x"}, "name": "leak.png"}]
        msg = Message(
            role=role,
            content=bad,
            tool_call_id="t1" if role == "tool" else None,
        )
        with pytest.raises(AssertionError, match="ADR 0006 wire-format violation"):
            ResponsesHandler.convert_messages([msg])

    def test_clean_blocks_pass(self):
        msg = Message(role="user", content=[{"type": "text", "text": "hi"}])
        instructions, items = ResponsesHandler.convert_messages([msg])
        assert instructions is None
        assert items == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]

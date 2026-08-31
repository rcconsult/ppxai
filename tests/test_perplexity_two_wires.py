"""ADR 0012 W3 — one Perplexity account, two wires.

Perplexity serves Sonar over Chat Completions and its Agent fleet (Anthropic,
OpenAI, Google, xAI models reached with a Perplexity key) over the OpenAI
*Responses* API. Same key, same bill, same price table, so it stays ONE
provider entry whose models pick a wire per request (ADR 0012 §5).

Everything asserted here was measured live before it was written:

- **2026-08-15** (plan I2) — `anthropic/claude-sonnet-5` answered through
  Perplexity; a `tools=[...]` request produced a real `function_call`; the
  stock OpenAI SDK drove `/v1/responses` unchanged.
- **2026-08-31** (this step) — the probe re-reported NATIVE with the tool
  actually called, and the ADR's canary ran end to end through
  `PerplexityProvider.chat`: `read_file(path="/etc/hostname")`,
  `native=True`, tool_call_id `toolu_bdrk_…`.
- **2026-08-31** — `perplexity/sonar` on the Responses wire **accepted a
  tools array and called the tool**, while bare `sonar` answers HTTP 400
  *"Tool calling is not supported for this model"* on Chat Completions. The
  same model, two wires, two capabilities — the sharpest evidence in the
  tree for why capability cannot live on the provider.

The live trial surfaced two defects that these fences now hold shut, both of
them the ADR's own failure shape (a declared value the wire never sees):
`enable_web_search` was a required host attribute that only one provider had,
and `ModelFacts.max_tokens` could not reach the request at all.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.providers.perplexity import (
    AGENT_FLEET_GLOBS,
    AGENT_FLEET_MAX_TOKENS,
    AGENT_FLEET_TOOL_MODE,
    PerplexityProvider,
    _WireCtx,
)
from ppxai.engine.providers.wire.responses import ResponsesHandler
from ppxai.engine.types import Message


@pytest.fixture
def provider():
    p = PerplexityProvider(api_key="test-key", base_url="https://api.perplexity.ai")
    p.client = MagicMock()
    p._responses_client = MagicMock()
    return p


class TestOneProviderTwoWires:
    @pytest.mark.parametrize(
        "model,wire",
        [
            ("sonar", "chat_completions"),
            ("sonar-pro", "chat_completions"),
            ("sonar-reasoning-pro", "chat_completions"),
            ("anthropic/claude-sonnet-5", "responses"),
            ("openai/gpt-5.5", "responses"),
            ("google/gemini-3.1-pro", "responses"),
            ("xai/grok-5", "responses"),
            ("perplexity/sonar", "responses"),
        ],
    )
    def test_each_model_resolves_its_measured_wire(self, provider, model, wire):
        assert provider._wire_for(model) == wire

    def test_the_same_model_differs_by_wire(self, provider):
        """`sonar` vs `perplexity/sonar` — the ADR's premise, measured.

        Bare `sonar` on Chat Completions answers 400 "Tool calling is not
        supported for this model". The namespaced ID on the Responses wire
        accepted a tools array and called the tool (2026-08-31). One model,
        two wires, two capabilities: this cannot be expressed by a
        provider-level flag, which is the whole argument for per-model facts.
        """
        bare = provider.get_facts_for_model("sonar")
        namespaced = provider.get_facts_for_model("perplexity/sonar")
        assert bare.wire_protocol == "chat_completions"
        assert bare.tool_mode == "prompt_based"
        assert namespaced.wire_protocol == "responses"
        assert namespaced.tool_mode == "auto"

    def test_no_code_branch_names_a_vendor(self):
        """The fleet is table data. Routing must not mention a namespace."""
        import inspect

        src = inspect.getsource(PerplexityProvider)
        for vendor in ("anthropic", "xai", "claude", "grok"):
            in_code = [
                ln
                for ln in src.splitlines()
                if vendor in ln.lower()
                and "#" not in ln.split(vendor.lower())[0]
                and '"""' not in ln
            ]
            assert in_code == [], f"{vendor} appears in executable code: {in_code}"


class TestTheFleetRowsCarryTheirMeasurements:
    def test_every_fleet_glob_states_all_three_facts(self):
        table = PerplexityProvider.shipped_model_facts
        assert set(table) == set(AGENT_FLEET_GLOBS)
        for glob in AGENT_FLEET_GLOBS:
            row = table[glob]
            assert row.wire_protocol == "responses", glob
            assert row.max_tokens == AGENT_FLEET_MAX_TOKENS, glob
            assert row.tool_mode == AGENT_FLEET_TOOL_MODE, glob

    def test_fleet_tool_mode_is_auto_not_the_unmeasured_floor(self):
        """Measured NATIVE twice — the conservative floor would be wrong here.

        Q0a's `prompt_based` default is correct for an UNmeasured model. For
        a model whose native `function_call` we have watched arrive, letting
        the floor win would be the inverse error: a measurement overridden by
        a default. `auto` keeps a prompt-based fallback for a roster that
        changes without notice.
        """
        assert AGENT_FLEET_TOOL_MODE == "auto"
        facts = PerplexityProvider(
            api_key="k", base_url="https://api.perplexity.ai"
        ).get_facts_for_model("anthropic/claude-sonnet-5")
        assert facts.tool_mode == "auto"

    def test_fleet_rows_carry_a_budget_because_the_api_requires_one(self):
        """`anthropic/*` 400s without `max_output_tokens` — measured twice.

        Plan I2 recorded the requirement; the W3 trial hit it live:
        "Invalid request: validation failed: max_output_tokens is required
        when using Anthropic models". A row of 0 would 400 every request.
        """
        assert AGENT_FLEET_MAX_TOKENS > 0
        p = PerplexityProvider(api_key="k", base_url="https://api.perplexity.ai")
        assert p.get_facts_for_model("anthropic/claude-sonnet-5").max_tokens > 0


class TestTheBudgetReachesTheWire:
    """The W3 trial's second defect: a fact the request never saw."""

    def test_shipped_fact_supplies_the_budget_when_config_is_silent(self, provider):
        """`_get_max_tokens` reads CONFIG only; the fleet's budget is a FACT.

        Before this, `build_request` asked config alone, so the fleet rows'
        4096 never reached `max_output_tokens` and the API 400'd — a declared
        value the wire never sees, which is the exact shape ADR 0012 exists
        to remove, reproduced inside its own handler.
        """
        assert provider._get_max_tokens("anthropic/claude-sonnet-5") is None
        assert (
            ResponsesHandler._budget_for(provider._wire_ctx(), "anthropic/claude-sonnet-5")
            == AGENT_FLEET_MAX_TOKENS
        )

    def test_operator_config_still_wins_over_the_shipped_fact(self, provider):
        with patch.object(provider, "_get_max_tokens", return_value=123):
            assert (
                ResponsesHandler._budget_for(
                    provider._wire_ctx(), "anthropic/claude-sonnet-5"
                )
                == 123
            )

    def test_max_output_tokens_is_actually_sent(self, provider):
        kwargs = ResponsesHandler().build_request(
            provider._wire_ctx(),
            [Message(role="user", content="hi")],
            "anthropic/claude-sonnet-5",
        )
        assert kwargs["max_output_tokens"] == AGENT_FLEET_MAX_TOKENS


class TestTheHostContractIsOptionalWhereItShouldBe:
    """The W3 trial's first defect: an implicit host contract."""

    def test_a_host_without_enable_web_search_still_builds_a_request(self, provider):
        """Perplexity has no such attribute — the first live call raised.

        `web_search_preview` is OpenAI's server-side search tool. Perplexity
        has search inside the model and does not define that tool, so the
        flag is genuinely absent rather than False. The handler must read it
        as optional; requiring it made the handler silently OpenAI-only.
        """
        assert not hasattr(provider, "enable_web_search")
        kwargs = ResponsesHandler().build_request(
            provider._wire_ctx(), [Message(role="user", content="hi")], "anthropic/claude-sonnet-5"
        )
        assert "tools" not in kwargs

    def test_every_host_attribute_the_handler_reads_exists_on_this_host(self, provider):
        """Catches the NEXT missing attribute at test time, not on the wire."""
        import re
        import inspect

        src = inspect.getsource(ResponsesHandler)
        reads = sorted(set(re.findall(r"ctx\.([A-Za-z_][A-Za-z0-9_]*)", src)))
        ctx = provider._wire_ctx()
        missing = [
            a
            for a in reads
            if not hasattr(ctx, a) and f'getattr(ctx, "{a}"' not in src
        ]
        assert missing == [], (
            f"the handler reads {missing} which this host does not provide — "
            "either the host supplies it or the handler reads it with a default"
        )


class TestWireCtxIsAViewNotACopy:
    def test_it_swaps_only_the_client(self, provider):
        ctx = provider._wire_ctx()
        assert ctx.client is provider._responses_client
        assert ctx.client is not provider.client

    def test_everything_else_delegates_to_the_one_account(self, provider):
        ctx = provider._wire_ctx()
        assert ctx.provider_id == provider.provider_id
        assert ctx.api_key == provider.api_key
        assert ctx.capabilities is provider.capabilities
        assert ctx.get_facts_for_model("sonar") == provider.get_facts_for_model("sonar")

    def test_it_is_a_view_so_host_changes_are_seen(self, provider):
        """Not a snapshot: a copy would silently serve stale config."""
        ctx = provider._wire_ctx()
        sentinel = object()
        provider.some_late_bound_thing = sentinel
        assert ctx.some_late_bound_thing is sentinel

    def test_the_responses_base_url_appends_v1_once(self):
        for given in (
            "https://api.perplexity.ai",
            "https://api.perplexity.ai/",
            "https://api.perplexity.ai/v1",
        ):
            p = PerplexityProvider(api_key="k", base_url=given)
            assert p._responses_base_url() == "https://api.perplexity.ai/v1"


class TestSonarKeepsItsOwnWire:
    """W3 must not disturb the wire Sonar is on until the 2026-09-27 cutover."""

    def test_sonar_still_goes_through_chat_completions(self, provider):
        provider.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok"), finish_reason="stop")],
            usage=None,
            model="sonar",
        )
        provider.oneshot(prompt="hi", model="sonar", max_tokens=16)
        assert provider.client.chat.completions.create.call_count == 1
        assert provider._responses_client.responses.create.call_count == 0

    def test_a_fleet_model_goes_through_responses(self, provider):
        provider._responses_client.responses.create.return_value = MagicMock(
            output=[], output_text="ok", usage=None, model="anthropic/claude-sonnet-5"
        )
        provider.oneshot(prompt="hi", model="anthropic/claude-sonnet-5", max_tokens=16)
        assert provider._responses_client.responses.create.call_count == 1
        assert provider.client.chat.completions.create.call_count == 0

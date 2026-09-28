"""Perplexity web_search cost: the provider's reported figure, else config.

Checked 2026-09-28. The backend calls Perplexity's Agent (Responses) API
with `perplexity/sonar` plus a `web_search` tool: $0.25 in / $2.50 out per
1M tokens, plus $0.0025 per web_search call (docs.perplexity.ai). The shipped
configs carried 1 / 1, the retired Sonar chat price, and priced tokens only.
A live response carries `usage.cost.total_cost` (0.00408 for one search:
input 0.00014 + cache creation 0.00117 + output 0.00027 + tool 0.0025), so
that figure wins; the per-token config price is the fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ppxai.engine.search import perplexity as pplx

REPO = Path(__file__).resolve().parent.parent

# The usage object exactly as measured live (2026-09-28), trimmed to the keys read.
LIVE_USAGE = {
    "input_tokens": 5204,
    "output_tokens": 108,
    "cost": {"input_cost": 0.00014, "cache_creation_cost": 0.00117,
             "output_cost": 0.00027, "tool_calls_cost": 0.0025,
             "total_cost": 0.00408, "currency": "USD"},
}


class TestReportedCost:
    def test_the_live_shape_as_a_dict(self):
        assert pplx._reported_cost(LIVE_USAGE) == pytest.approx(0.00408)

    def test_the_live_shape_as_sdk_attributes(self):
        usage = SimpleNamespace(input_tokens=5204, output_tokens=108,
                                cost=SimpleNamespace(total_cost=0.00408))
        assert pplx._reported_cost(usage) == pytest.approx(0.00408)

    def test_a_cost_dict_on_an_sdk_object(self):
        """The OpenAI SDK keeps unknown fields as plain dicts."""
        usage = SimpleNamespace(cost={"total_cost": 0.00408})
        assert pplx._reported_cost(usage) == pytest.approx(0.00408)

    @pytest.mark.parametrize("usage", [
        None,
        SimpleNamespace(input_tokens=1),
        {"cost": {}},
        {"cost": {"total_cost": "0.004"}},
        {"cost": {"total_cost": -1}},
        {"cost": {"total_cost": True}},
    ])
    def test_absent_or_bad_is_none(self, usage):
        assert pplx._reported_cost(usage) is None


class TestTheSearchRecordsIt:
    async def _search(self, usage):
        response = MagicMock(output=[], usage=usage)
        client = MagicMock()
        client.responses.create = AsyncMock(return_value=response)
        with patch.dict("os.environ", {"PERPLEXITY_API_KEY": "k"}), \
             patch.object(pplx, "get_tool_config",
                          lambda name: {"perplexity_model": "perplexity/sonar"}), \
             patch.object(pplx, "AsyncOpenAI", return_value=client), \
             patch.object(pplx, "_responses_answer_and_citations",
                          return_value=("answer", ["https://example.com"])):
            _, _, tool_usage = await pplx.search_perplexity("q", num_results=3)
        return tool_usage

    async def test_the_reported_cost_wins(self):
        usage = SimpleNamespace(input_tokens=5204, output_tokens=108,
                                cost={"total_cost": 0.00408})
        with patch.object(pplx, "calculate_tool_cost", return_value=999.0):
            tool_usage = await self._search(usage)
        assert tool_usage.estimated_cost == pytest.approx(0.00408)

    async def test_without_one_the_config_price_is_used(self):
        usage = SimpleNamespace(input_tokens=1000, output_tokens=100)
        with patch.object(pplx, "calculate_tool_cost", return_value=0.123) as calc:
            tool_usage = await self._search(usage)
        calc.assert_called_once_with("perplexity", 1000, 100)
        assert tool_usage.estimated_cost == pytest.approx(0.123)


@pytest.mark.parametrize("name", ["ppxai-config.json", "ppxai-config.example.json"])
def test_shipped_fallback_prices_are_the_agent_api_rates(name):
    pricing = json.loads((REPO / name).read_text(encoding="utf-8"))[
        "tools"]["web_search"]["pricing"]["perplexity"]
    assert (pricing["input"], pricing["output"]) == (0.25, 2.5), (
        f"{name}: perplexity/sonar on the Agent API is $0.25 / $2.50 per 1M "
        "(checked 2026-09-28); 1 / 1 was the retired Sonar chat price")

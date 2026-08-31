"""`tools.web_search.order` — the premium search chain is config DATA.

Before this, `tools.web_search.preferred` chose only the FIRST backend; the
rest of the chain was the hardcoded `AUTO_ORDER = (perplexity, gemini,
duckduckgo)`. An operator could say "try gemini first" but not "and then
DuckDuckGo, and only then Perplexity".

The order is now a config key consumed by the ONE resolver
(`resolve_web_search_backend`) that both the call-time chain and the egress
enumeration already read — deliberately not a second mechanism beside
`preferred`. That shared reader is debt Item 59's seam: when the chain and
the allowlist are derived from different sources they drift, and a run tries
a host it never allowlisted.

The scenario the owner asked for is `TestGeminiFirstThenDuckDuckGoThenPerplexity`:
order `gemini → duckduckgo → perplexity`, gemini failing BOTH ways (no key,
and an API error), asserting DuckDuckGo is contacted next and Perplexity
after it.
"""

import asyncio
from unittest.mock import patch

import pytest

from ppxai.engine.tools import search_backends as sb
from ppxai.engine.tools.builtin import web_premium
from ppxai.engine.tools.search_backends import (
    AUTO_ORDER,
    BACKEND_HOSTS,
    resolve_web_search_backend,
)


@pytest.fixture
def tools_cfg():
    """Drive `tools.web_search` config without touching a real file."""
    cfg = {}

    def _get(name):
        return cfg if name == "web_search" else {}

    with patch.object(sb, "get_tool_config", create=True), patch(
        "ppxai.config.get_tool_config", _get
    ), patch("ppxai.config.get_provider_config", lambda *_a, **_k: {}):
        yield cfg


@pytest.fixture
def all_keys_present():
    with patch.dict(
        "os.environ", {"PERPLEXITY_API_KEY": "p", "GEMINI_API_KEY": "g"}, clear=False
    ):
        yield


class TestTheOrderIsConfigurable:
    def test_default_is_the_historical_chain(self, tools_cfg, all_keys_present):
        assert resolve_web_search_backend().candidates == AUTO_ORDER

    def test_a_configured_order_is_the_chain(self, tools_cfg, all_keys_present):
        tools_cfg["order"] = ["gemini", "duckduckgo", "perplexity"]
        assert resolve_web_search_backend().candidates == (
            "gemini",
            "duckduckgo",
            "perplexity",
        )

    def test_a_partial_order_still_falls_back(self, tools_cfg, all_keys_present):
        """`order: [gemini]` means "gemini first", not "gemini only".

        Narrowing to a single backend is `strict`'s job and stays the only
        way to say it — otherwise a short list would silently become a pin
        and a failure would return an error instead of falling back.
        """
        tools_cfg["order"] = ["gemini"]
        assert resolve_web_search_backend().candidates == (
            "gemini",
            "perplexity",
            "duckduckgo",
        )

    def test_an_unknown_id_is_warned_and_ignored(self, tools_cfg, all_keys_present):
        tools_cfg["order"] = ["bing", "gemini"]
        res = resolve_web_search_backend()
        assert res.candidates[0] == "gemini"
        assert any("bing" in w for w in res.warnings)

    def test_a_non_list_order_is_warned_and_ignored(self, tools_cfg, all_keys_present):
        tools_cfg["order"] = "gemini"
        res = resolve_web_search_backend()
        assert res.candidates == AUTO_ORDER
        assert any("must be a list" in w for w in res.warnings)

    def test_duplicates_collapse(self, tools_cfg, all_keys_present):
        tools_cfg["order"] = ["gemini", "gemini", "duckduckgo"]
        assert resolve_web_search_backend().candidates == (
            "gemini",
            "duckduckgo",
            "perplexity",
        )

    def test_preferred_still_names_the_first_choice(self, tools_cfg, all_keys_present):
        """`order` and `preferred` fold together — not two mechanisms."""
        tools_cfg["order"] = ["gemini", "duckduckgo", "perplexity"]
        tools_cfg["preferred"] = "perplexity"
        assert resolve_web_search_backend().candidates == (
            "perplexity",
            "gemini",
            "duckduckgo",
        )


class TestEgressFollowsTheSameResolvedOrder:
    """Item 59's seam: chain and allowlist must come from ONE source."""

    def test_egress_hosts_are_derived_from_the_configured_order(
        self, tools_cfg, all_keys_present
    ):
        tools_cfg["order"] = ["gemini", "duckduckgo", "perplexity"]
        res = resolve_web_search_backend()
        expected = [h for b in res.candidates for h in BACKEND_HOSTS[b]]
        assert list(res.egress_hosts) == expected

    def test_every_backend_the_chain_may_try_is_in_the_egress_set(
        self, tools_cfg, all_keys_present
    ):
        for order in (
            ["gemini", "duckduckgo", "perplexity"],
            ["duckduckgo"],
            ["perplexity", "gemini"],
        ):
            tools_cfg["order"] = order
            res = resolve_web_search_backend()
            for backend in res.candidates:
                for host in BACKEND_HOSTS[backend]:
                    assert host in res.egress_hosts, (order, backend, host)


class TestGeminiFirstThenDuckDuckGoThenPerplexity:
    """The owner's scenario, offline: gemini → duckduckgo → perplexity."""

    ORDER = ["gemini", "duckduckgo", "perplexity"]

    @staticmethod
    def _drive(calls, gemini_effect):
        """Run the chain with each backend recorded and stubbed."""

        async def _gemini(query, num_results=5):
            calls.append("gemini")
            raise gemini_effect

        def _ddg(query, num_results=5):
            # NB synchronous: the chain calls `web.web_search(...)` without
            # `await` (it is the free, non-async backend). An AsyncMock here
            # returns a coroutine that is never awaited, so the chain would
            # "succeed" with a coroutine object and never reach perplexity.
            calls.append("duckduckgo")
            raise ValueError("DDG unavailable in this test")

        async def _pplx(query, num_results=5):
            calls.append("perplexity")
            return "answer", ["https://p.example"], web_premium.ToolUsage(call_count=1)

        with patch.object(web_premium, "web_search_gemini", _gemini), patch.object(
            web_premium, "web_search_perplexity", _pplx
        ), patch.object(web_premium.web, "web_search", _ddg), patch.object(
            web_premium, "_record_usage", lambda *_a, **_k: None
        ):
            return asyncio.run(web_premium.web_search_premium("q"))

    def test_missing_gemini_key_skips_to_duckduckgo_then_perplexity(self, tools_cfg):
        """Gemini fails by ABSENT KEY — the resolver drops it as unusable."""
        tools_cfg["order"] = self.ORDER
        calls = []
        with patch.dict(
            "os.environ", {"PERPLEXITY_API_KEY": "p"}, clear=False
        ), patch.dict("os.environ", {"GEMINI_API_KEY": ""}, clear=False):
            res = resolve_web_search_backend()
            assert res.candidates == ("duckduckgo", "perplexity"), res.candidates
            out = self._drive(calls, ValueError("unreachable"))
        assert calls == ["duckduckgo", "perplexity"], calls
        assert "answer" in out

    def test_gemini_api_error_falls_through_to_duckduckgo_then_perplexity(
        self, tools_cfg, all_keys_present
    ):
        """Gemini fails at CALL TIME — key present, API errors."""
        tools_cfg["order"] = self.ORDER
        calls = []
        out = self._drive(calls, ValueError("Gemini API error: 503"))
        assert calls == ["gemini", "duckduckgo", "perplexity"], calls
        assert "answer" in out

    def test_the_configured_order_is_what_decides(self, tools_cfg, all_keys_present):
        """Mutation guard: the DEFAULT order would try perplexity first.

        Without this the two tests above could pass on the historical chain
        by coincidence — `AUTO_ORDER` starts with perplexity, so a reversed
        or ignored `order` key changes who is contacted first.
        """
        tools_cfg["order"] = self.ORDER
        assert resolve_web_search_backend().candidates[0] == "gemini"
        assert AUTO_ORDER[0] == "perplexity"

        tools_cfg["order"] = list(reversed(self.ORDER))
        assert resolve_web_search_backend().candidates == (
            "perplexity",
            "duckduckgo",
            "gemini",
        )

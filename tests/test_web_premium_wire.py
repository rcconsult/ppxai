"""ADR 0012 W3 part 2 — the web_search tool rides the shared wire resolution.

`web_search_perplexity` used to build its OWN `AsyncOpenAI` client hardcoded
to `https://api.perplexity.ai` and `/chat/completions`. That is a second path
to the same vendor, and the 2026-09-27 Sonar retirement would have broken it
**independently of the provider** — one fix in `PerplexityProvider` would
have left the tool dead, which is the "patch each call site" shape the
owner's root-cause rule exists to prevent.

It now reads `ModelFacts.wire_protocol` from the same table the provider
uses, so configuring `perplexity/sonar` moves the tool onto the surviving
wire with no code change at all.

The citation migration is **behavioural, not a parse-site move** (measured,
plan W0 (c)): on the Responses wire search is an explicit TOOL — a plain
request runs no search and returns no citations — and the results arrive as a
`search_results` output item while the text block's `annotations` stay empty.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ppxai.engine.model_facts import shipped_facts_for_model
from ppxai.engine.providers.perplexity import PerplexityProvider
from ppxai.engine.tools.builtin import web_premium
from ppxai.engine.tools.builtin.web_premium import (
    PERPLEXITY_CHAT_BASE_URL,
    PERPLEXITY_RESPONSES_BASE_URL,
    _responses_answer_and_citations,
    web_search_perplexity,
)


class TestNoSecondHardcodedClient:
    def test_the_tool_reads_the_same_table_as_the_provider(self):
        """One resolution, two consumers — the root-cause rule."""
        for model in ("sonar", "sonar-pro", "perplexity/sonar"):
            from_table = shipped_facts_for_model(
                model, PerplexityProvider.shipped_model_facts
            ).wire_protocol
            from_provider = PerplexityProvider(
                api_key="k", base_url="https://api.perplexity.ai"
            )._wire_for(model)
            assert from_table == from_provider, model

    def test_no_wire_path_is_hardcoded_in_the_search_function(self):
        """The base URLs are named constants derived from one host.

        A literal `https://api.perplexity.ai` inside the function body is
        what made this a second patch site in the first place.
        """
        import inspect

        src = inspect.getsource(web_search_perplexity)
        assert "https://api.perplexity.ai" not in src
        assert "PERPLEXITY_RESPONSES_BASE_URL" in src
        assert "PERPLEXITY_CHAT_BASE_URL" in src

    def test_the_responses_base_url_is_the_chat_host_plus_v1(self):
        """Measured: the bare host 404s on /responses (plan W0 (f))."""
        assert PERPLEXITY_RESPONSES_BASE_URL == PERPLEXITY_CHAT_BASE_URL + "/v1"


class TestItFollowsTheConfiguredModelOntoItsWire:
    @staticmethod
    def _run(model, capture):
        """Drive the tool with a fake SDK client, capturing construction."""

        def _fake_client(**kwargs):
            capture["base_url"] = kwargs.get("base_url")
            client = MagicMock()
            chat_resp = MagicMock()
            chat_resp.choices = [MagicMock(message=MagicMock(content="chat answer"))]
            chat_resp.citations = ["https://chat.example/1"]
            chat_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
            client.chat.completions.create = AsyncMock(return_value=chat_resp)

            resp_resp = MagicMock()
            resp_resp.output_text = "responses answer"
            resp_resp.usage = MagicMock(input_tokens=11, output_tokens=22)
            resp_resp.model_dump = MagicMock(
                return_value={
                    "output": [
                        {
                            "type": "search_results",
                            "results": [{"url": "https://resp.example/1"}],
                        }
                    ]
                }
            )
            client.responses.create = AsyncMock(return_value=resp_resp)
            capture["client"] = client
            return client

        import asyncio

        with patch.dict("os.environ", {"PERPLEXITY_API_KEY": "k"}), patch.object(
            web_premium, "AsyncOpenAI", _fake_client
        ), patch.object(
            web_premium, "get_tool_config", return_value={"perplexity_model": model}
        ), patch.object(
            web_premium, "calculate_tool_cost", return_value=0.0
        ):
            return asyncio.run(web_search_perplexity("q", num_results=5))

    def test_a_chat_model_uses_the_chat_wire(self):
        cap = {}
        content, citations, usage = self._run("sonar", cap)
        assert cap["base_url"] == PERPLEXITY_CHAT_BASE_URL
        assert cap["client"].chat.completions.create.await_count == 1
        assert cap["client"].responses.create.await_count == 0
        assert content == "chat answer"
        assert citations == ["https://chat.example/1"]
        assert (usage.tokens_in, usage.tokens_out) == (10, 20)

    def test_a_responses_model_uses_the_responses_wire(self):
        cap = {}
        content, citations, usage = self._run("perplexity/sonar", cap)
        assert cap["base_url"] == PERPLEXITY_RESPONSES_BASE_URL
        assert cap["client"].responses.create.await_count == 1
        assert cap["client"].chat.completions.create.await_count == 0
        assert content == "responses answer"
        assert citations == ["https://resp.example/1"]
        assert (usage.tokens_in, usage.tokens_out) == (11, 22)

    def test_the_responses_call_requests_the_search_tool_explicitly(self):
        """Measured (W0 (c)): without this the wire runs NO search at all."""
        cap = {}
        self._run("perplexity/sonar", cap)
        kwargs = cap["client"].responses.create.await_args.kwargs
        assert kwargs["tools"] == [{"type": "web_search"}]
        assert kwargs["input"] == "q"


class TestCitationsComeFromSearchResultItems:
    """Not from `annotations` — measured empty on this wire."""

    def test_urls_are_read_out_of_the_search_results_item(self):
        response = MagicMock()
        response.output_text = "answer"
        response.model_dump = MagicMock(
            return_value={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "answer", "annotations": []}
                        ],
                    },
                    {
                        "type": "search_results",
                        "results": [
                            {"url": "https://a.example", "snippet": "…"},
                            {"url": "https://b.example", "snippet": "…"},
                        ],
                    },
                ]
            }
        )
        content, citations = _responses_answer_and_citations(response, 5)
        assert content == "answer"
        assert citations == ["https://a.example", "https://b.example"]

    def test_num_results_caps_the_citation_list(self):
        response = MagicMock()
        response.output_text = "a"
        response.model_dump = MagicMock(
            return_value={
                "output": [
                    {
                        "type": "search_results",
                        "results": [{"url": f"https://x{i}.example"} for i in range(9)],
                    }
                ]
            }
        )
        _, citations = _responses_answer_and_citations(response, 3)
        assert len(citations) == 3

    def test_text_is_recovered_from_output_items_when_output_text_is_absent(self):
        response = MagicMock()
        response.output_text = None
        response.model_dump = MagicMock(
            return_value={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "pieced "},
                            {"type": "output_text", "text": "together"},
                        ],
                    }
                ]
            }
        )
        content, citations = _responses_answer_and_citations(response, 5)
        assert content == "pieced together"
        assert citations == []

    def test_no_search_results_item_yields_no_citations_rather_than_raising(self):
        response = MagicMock()
        response.output_text = "answer"
        response.model_dump = MagicMock(return_value={"output": []})
        content, citations = _responses_answer_and_citations(response, 5)
        assert content == "answer"
        assert citations == []


class TestCodeDefaultsAreNotDeprecatedModels:
    """A default in CODE outlives every user's config.

    `tools.web_search.gemini_model` defaulted to `gemini-2.5-flash`, whose
    line sunsets from 2026-10-16 — so the web_search fallback backend would
    have died for everyone who never set the key, which is most people. That
    is the same shape as the Perplexity chat wire: a code default quietly
    holding a retiring model.

    Asserted against the deprecation table rather than a literal, so this
    fails the day ANY code default becomes deprecated — including the next
    one, which will not be this one.
    """

    def test_the_gemini_web_search_default_is_not_deprecated(self):
        import inspect
        import re

        from ppxai.engine.model_deprecations import ALL_DEPRECATIONS

        src = inspect.getsource(web_premium.web_search_gemini)
        m = re.search(r'tool_config\.get\("gemini_model",\s*"([^"]+)"\)', src)
        assert m, "the gemini_model default moved — update this fence"
        default = m.group(1)
        dep = ALL_DEPRECATIONS.get(default)
        assert dep is None, (
            f"the web_search Gemini default {default!r} is deprecated "
            f"(shutdown {dep.shutdown_date}, use {dep.replacement!r}). A code "
            "default outlives every user's config — it must not name a model "
            "with a sunset date."
        )

    def test_the_perplexity_web_search_default_is_not_deprecated(self):
        """Same rule, the other backend.

        This one currently NAMES a deprecated model on purpose: `sonar` is
        the chat-wire id, deprecated 2026-09-27 in favour of
        `perplexity/sonar`. It is asserted as a KNOWN exception rather than
        skipped, so the exception has to be re-argued if it survives the
        cutover.
        """
        import inspect
        import re

        from ppxai.engine.model_deprecations import ALL_DEPRECATIONS

        src = inspect.getsource(web_premium.web_search_perplexity)
        m = re.search(r'tool_config\.get\("perplexity_model",\s*"([^"]+)"\)', src)
        assert m, "the perplexity_model default moved — update this fence"
        default = m.group(1)
        dep = ALL_DEPRECATIONS.get(default)
        if dep is not None:
            assert default == "sonar" and dep.shutdown_date == "2026-09-27", (
                f"{default!r} is deprecated and is NOT the known 2026-09-27 "
                "Sonar case — a code default must not name a sunset model"
            )


class TestEgressAllowlistCoversBothWires:
    """Plan W3 fence: "verified in W3, not assumed"."""

    def test_the_allowlist_is_host_level_so_the_v1_path_is_covered(self):
        from ppxai.engine.tools.search_backends import BACKEND_HOSTS

        hosts = BACKEND_HOSTS["perplexity"]
        assert hosts == ["https://api.perplexity.ai/"]
        # Both wires live under that host, so the allowlist needs no change —
        # asserted rather than assumed, because a path-level entry would have
        # silently blocked /v1/responses.
        for url in (PERPLEXITY_CHAT_BASE_URL, PERPLEXITY_RESPONSES_BASE_URL):
            assert any(url.startswith(h.rstrip("/")) for h in hosts), url

    def test_network_policy_targets_the_same_host(self):
        import inspect

        from ppxai.engine.tools import network_policy

        src = inspect.getsource(network_policy)
        assert "https://api.perplexity.ai/" in src

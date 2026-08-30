"""The Perplexity capability probe's classifier and drift logic (plan I4).

`scripts/probe-perplexity-capabilities.py` is the repeatable answer to a
hazard the plan calls out explicitly: **a capability table goes stale
silently.** Perplexity shipped tool calling for `sonar-pro` and nothing told
us for roughly a month — that gap is the whole of debt Item 43.

These tests are OFFLINE. The probe's value is live, but its *judgement* must
be testable without a key or a bill, because that judgement is what decides
whether a real drift is reported or swallowed. Three properties matter:

1. **Wire strings map to the right verdict.** The 400s are not
   interchangeable: `sonar` says the capability is absent, while
   `sonar-deep-research` complains about the parameter SHAPE. Both are
   "not natively tool-capable", but they are different findings and the
   probe must not blur them.
2. **Drift is detected in BOTH directions** — a table claiming NATIVE for a
   model that rejects, and a table claiming not-capable for one that
   accepts. The second direction is the Item 43 shape, the expensive one.
3. **An infrastructure failure is never a capability verdict.** A 401/500
   must surface as ERROR, not as "the model lost tool calling". This
   project has twice misread a provider error as a clean negative result.

The exact wire strings below were measured live against api.perplexity.ai
(2026-08-24, this iteration) — copied from real responses, not invented.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE_PATH = REPO_ROOT / "scripts" / "probe-perplexity-capabilities.py"


def _load_probe():
    """Import the probe script by path (it is a script, not a package)."""
    spec = importlib.util.spec_from_file_location("_pplx_probe", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe_mod = _load_probe()


#: Verbatim from live responses, 2026-08-24. If Perplexity rewords these,
#: the probe silently reclassifies — which is exactly why they are pinned.
WIRE_SONAR_REJECTS = (
    "Error code: 400 - {'error': {'message': 'Tool calling is not supported "
    "for this model', 'type': 'invalid_message', 'code': 400}}"
)
WIRE_DEEP_RESEARCH_SHAPE = (
    "Error code: 400 - {'error': {'message': 'Tool parameters must be a JSON "
    "object.', 'type': 'invalid_parameter', 'code': 400}}"
)
WIRE_INVALID_MODEL = (
    "Error code: 400 - {'error': {'message': 'Invalid model "
    "'anthropic/claude-sonnet-5'. Permitted models can be found in the "
    "documentation', 'type': 'invalid_model', 'code': 400}}"
)
WIRE_BAD_KEY = (
    "Error code: 401 - {'error': {'message': 'Invalid API key provided.', "
    "'type': 'invalid_auth', 'code': 401}}"
)


class TestClassify:
    """Wire outcome -> capability verdict."""

    def test_200_is_native(self):
        assert probe_mod.classify(200, "") == probe_mod.NATIVE

    def test_sonar_400_is_rejects(self):
        assert probe_mod.classify(400, WIRE_SONAR_REJECTS) == probe_mod.REJECTS

    def test_deep_research_400_is_shape_not_rejects(self):
        """The two 400s differ in KIND and must not collapse together.

        `sonar-deep-research` may be usable with a stricter schema; recording
        it as REJECTS would assert a capability finding we have not made.
        """
        verdict = probe_mod.classify(400, WIRE_DEEP_RESEARCH_SHAPE)
        assert verdict == probe_mod.SHAPE
        assert verdict != probe_mod.REJECTS

    def test_invalid_model_is_absent_not_a_capability_claim(self):
        """A model not served here says nothing about its capability."""
        assert probe_mod.classify(400, WIRE_INVALID_MODEL) == probe_mod.ABSENT

    @pytest.mark.parametrize("status", [401, 403, 429, 500, 502, 503])
    def test_non_400_failures_are_error_never_a_verdict(self, status):
        """Infra failure must never read as 'model lacks the capability'."""
        assert probe_mod.classify(status, WIRE_BAD_KEY) == probe_mod.ERROR

    def test_shape_wording_wins_over_generic_tool_wording(self):
        """Ordering fence.

        The shape message contains "Tool parameters", and a naive
        substring check for "tool" + "not supported" could mis-sort a future
        message carrying both. Shape is tested first; pin that.
        """
        both = "Tool parameters must be a JSON object. tool is not supported"
        assert probe_mod.classify(400, both) == probe_mod.SHAPE


class TestExpectedVerdict:
    """The table's claim, including its safe default."""

    def test_native_models_expect_native(self):
        for model in probe_mod.PERPLEXITY_NATIVE_TOOL_MODELS:
            assert probe_mod.expected_verdict(model) == probe_mod.NATIVE

    def test_rejecting_models_expect_rejects(self):
        for model in probe_mod.PERPLEXITY_TOOL_REJECTING_MODELS:
            assert probe_mod.expected_verdict(model) == probe_mod.REJECTS

    def test_unknown_model_defaults_to_not_capable(self):
        """An unmeasured model is assumed non-capable, so it degrades
        rather than 400ing a user's request."""
        assert probe_mod.expected_verdict("sonar-something-new-2027") == probe_mod.REJECTS


class TestDriftLogic:
    """The OK/DRIFT/ERROR decision, in both directions.

    Mirrors the comparison in `main()`: only a NATIVE-vs-not disagreement is
    drift, because the table has two sets and cannot express SHAPE.
    """

    @staticmethod
    def _state(verdict, expected):
        if verdict == probe_mod.ERROR:
            return "ERROR"
        return "OK" if (verdict == probe_mod.NATIVE) == (
            expected == probe_mod.NATIVE
        ) else "DRIFT"

    def test_agreement_is_ok(self):
        assert self._state(probe_mod.NATIVE, probe_mod.NATIVE) == "OK"
        assert self._state(probe_mod.REJECTS, probe_mod.REJECTS) == "OK"

    def test_shape_against_rejects_is_not_drift(self):
        """Both mean not-natively-capable; the table cannot say more."""
        assert self._state(probe_mod.SHAPE, probe_mod.REJECTS) == "OK"

    def test_drift_when_table_overclaims(self):
        """Table says NATIVE, API rejects — we would 400 real user requests."""
        assert self._state(probe_mod.REJECTS, probe_mod.NATIVE) == "DRIFT"

    def test_drift_when_table_underclaims(self):
        """Table says not-capable, API accepts — THE ITEM 43 SHAPE.

        This is the silent, expensive direction: everything keeps working,
        users just get the prompt-based fallback's confabulations instead of
        real tool calls. It went unnoticed for about a month.
        """
        assert self._state(probe_mod.NATIVE, probe_mod.REJECTS) == "DRIFT"

    def test_error_outranks_any_drift_verdict(self):
        """A failed probe judges nothing — not even a mismatching table."""
        assert self._state(probe_mod.ERROR, probe_mod.NATIVE) == "ERROR"
        assert self._state(probe_mod.ERROR, probe_mod.REJECTS) == "ERROR"


class TestRosterFollowsShippedConfig:
    """The probe must track the shipped roster without being edited."""

    def test_roster_read_from_example_config(self):
        roster = probe_mod.shipped_roster()
        assert roster, "probe found no Perplexity models to probe"
        # Every model the table declares native must actually be shipped —
        # a native claim for a model nobody can select is dead data.
        for model in probe_mod.PERPLEXITY_NATIVE_TOOL_MODELS:
            assert model in roster, (
                f"{model} is declared natively tool-capable but is not in the "
                f"shipped roster {roster}"
            )

    def test_dropped_model_is_not_probed_by_default(self):
        """I3 dropped `sonar-deep-research` from the shipped list.

        It stays in the REJECTING set as a recorded 400, but must not be
        probed by default — that would spend money re-measuring a model no
        user can select.
        """
        assert "sonar-deep-research" not in probe_mod.shipped_roster()
        assert "sonar-deep-research" in probe_mod.PERPLEXITY_TOOL_REJECTING_MODELS


class TestProbeToolShape:
    """The probe's own tool must be valid, or every verdict is SHAPE."""

    def test_probe_tool_is_well_formed_openai_function(self):
        tool = probe_mod.PROBE_TOOL
        assert tool["type"] == "function"
        fn = tool["function"]
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"
        assert isinstance(fn["parameters"]["properties"], dict)

    def test_probe_stays_cheap(self):
        """Runs against a real billed key; keep the ceiling low."""
        assert probe_mod.PROBE_MAX_TOKENS <= 128


class TestResponsesToolShape:
    """to_responses_tool: chat tool -> Responses flat shape (plan W0)."""

    def test_flattens_function_wrapper(self):
        t = probe_mod.to_responses_tool(probe_mod.PROBE_TOOL)
        assert t["type"] == "function"
        assert t["name"] == probe_mod.PROBE_TOOL["function"]["name"]
        assert t["parameters"] == probe_mod.PROBE_TOOL["function"]["parameters"]
        # The Responses shape has NO nested "function" key -- sending the
        # chat shape to /v1/responses is a 400, which would read as SHAPE
        # and poison the survey's tool verdicts.
        assert "function" not in t

    def test_source_tool_not_mutated(self):
        # deepcopy, not dict(): a shallow copy SHARES the nested "function"
        # dict, so mutating it would compare equal and pass vacuously.
        before = copy.deepcopy(probe_mod.PROBE_TOOL)
        probe_mod.to_responses_tool(probe_mod.PROBE_TOOL)
        assert probe_mod.PROBE_TOOL == before


class TestCitationPathFinder:
    """find_citation_paths: pure envelope walker for W0 (c)."""

    def test_finds_top_level_citations(self):
        assert probe_mod.find_citation_paths({"citations": ["u1"]}) == ["citations"]

    def test_finds_nested_and_listed_keys(self):
        payload = {
            "output": [
                {"content": [{"annotations": [{"url": "x"}], "text": "hi"}]},
            ],
            "search_results": [{"url": "y"}],
        }
        hits = probe_mod.find_citation_paths(payload)
        assert "search_results" in hits
        assert any(h.endswith("annotations") for h in hits)

    def test_empty_values_are_not_hits(self):
        # An empty citations list proves nothing about where citations live.
        assert probe_mod.find_citation_paths({"citations": []}) == []

    def test_no_false_positives_on_plain_envelope(self):
        payload = {"output": [{"content": [{"text": "hello"}]}], "usage": {}}
        assert probe_mod.find_citation_paths(payload) == []


class TestSurveyStaysCheapAndScoped:
    """The survey runs against a billed key -- its scope is pinned."""

    def test_extra_models_are_exactly_the_planned_pair(self):
        # perplexity/sonar answers W0 (a) (namespaced-vs-bare IDs);
        # anthropic/claude-sonnet-5 is the W3 canary and the measured
        # carrier of the max_output_tokens requirement (W0 (e)).
        assert probe_mod.SURVEY_EXTRA_MODELS == (
            "perplexity/sonar",
            "anthropic/claude-sonnet-5",
        )

    def test_responses_base_url_is_v1(self):
        # Measured 2026-08-15: /v1/responses is live, bare /responses is not.
        # The survey re-verifies at runtime; this pins the default.
        assert probe_mod.RESPONSES_BASE_URL == probe_mod.BASE_URL + "/v1"


class TestResponsesWireWording:
    """The Responses wire words invalid-model differently (measured 2026-08-30)."""

    def test_responses_model_not_supported_is_absent(self):
        wire = (
            "Error code: 400 - {'error': {'message': 'validation failed: "
            "model \"sonar\" is not supported', 'type': 'validation_error'}}"
        )
        assert probe_mod.classify(400, wire) == probe_mod.ABSENT

    def test_tool_not_supported_still_rejects(self):
        # The chat-wire REJECTS wording contains both 'tool' and 'not
        # supported' -- the new ABSENT rule must not swallow it.
        assert probe_mod.classify(400, WIRE_SONAR_REJECTS) == probe_mod.REJECTS


class TestSearchResultsItemIsFound:
    """Citations on the Responses wire live in a search_results OUTPUT ITEM.

    Measured 2026-08-30 (plan W0 (c)): unlike Sonar chat-completions, which
    carries a top-level `citations` list, the Agent-API envelope returns a
    `search_results` item (15 results with id/snippet/date/url) and leaves
    the text block's `annotations` EMPTY. A walker keyed only on dict keys
    would miss it, because here the marker is the item's `type` VALUE.
    """

    def test_search_results_output_item_is_detected(self):
        payload = {
            "output": [
                {"type": "search_results", "results": [{"id": 1, "snippet": "x"}]},
                {"type": "message", "content": [{"type": "output_text",
                                                 "annotations": []}]},
            ]
        }
        hits = probe_mod.find_citation_paths(payload)
        assert any("search_results" in h for h in hits)

    def test_empty_annotations_alone_are_not_citations(self):
        payload = {"output": [{"type": "message",
                               "content": [{"annotations": []}]}]}
        assert probe_mod.find_citation_paths(payload) == []

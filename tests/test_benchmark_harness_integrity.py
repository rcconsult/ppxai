"""The benchmark harness's own fences — offline, no live calls.

`benchmarks/` is excluded from graphify AND from the test suite, so until
this file nothing at all guarded it. That gap had a cost: the harness's
`auto` tool-calling branch read `get_capabilities_for_model()` and
`capabilities.native_tool_calling`, **both deleted by ADR 0012 W1**, and the
breakage went unnoticed for the whole arc — an `hasattr` returning False and
a `getattr(..., False)` swallowed it, so `auto` silently resolved
`prompt_based` for every model. Our own regression, invisible because the
only code that could have caught it was not run.

Three defect classes, measured 2026-08-31 while sizing the Phase C benchmark
(debt Item 55). Each has a test here:

1. **`auto` resolution must read the CURRENT fact system.** A benchmark that
   silently measures prompt-based tool calling for every model produces
   numbers that look fine and mean something else.
2. **Recorded metadata must state what the provider DID, not what was
   requested.** A run recorded `method=native` while the provider used
   prompt-based, because the runner calls `provider.chat()` directly and the
   provider gates its tools array on `ModelFacts.tool_mode` — which the CLI
   flag never reaches. Two runs labelled `native` may have exercised
   different code paths, which makes every historical comparison
   unfalsifiable.
3. **Infrastructure failures must not be scored as quality.** 34 historical
   runs sit at exactly 0 / 8.1 / 10.9 — three discrete floors, not a
   distribution — and identical models spread up to 89 points across
   repeats. Those are 400s and timeouts wearing a score.

Live-API benchmarking stays out of the suite; this slice is pure logic.
"""

import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BENCH = Path(__file__).resolve().parents[1] / "benchmarks" / "llm-eval"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))

pytest.importorskip("engine_runner", reason="benchmark harness not importable here")

from engine_runner import EngineBenchmarkRunner, EngineClientWrapper  # noqa: E402

from ppxai.engine.model_facts import ModelFacts  # noqa: E402


def _provider(tool_mode):
    """A stand-in provider whose only job is to answer the facts question."""
    p = MagicMock()
    p.get_facts_for_model.return_value = replace(ModelFacts(), tool_mode=tool_mode)
    return p


def _wrapper(tool_mode, method="auto"):
    w = EngineClientWrapper.__new__(EngineClientWrapper)
    w.tool_calling_method = method
    w.model = "some-model"
    inner = MagicMock()
    inner.provider = _provider(tool_mode)
    w._client = inner
    return w


class TestAutoResolutionReadsTheCurrentFactSystem:
    """Defect 1 — the branch ADR 0012 W1 silently broke."""

    @pytest.mark.parametrize(
        "tool_mode,expected",
        [("native", True), ("auto", True), ("prompt_based", False)],
    )
    def test_auto_follows_the_model_facts(self, tool_mode, expected):
        assert _wrapper(tool_mode)._use_native_tools() is expected

    def test_it_does_not_read_the_deleted_capability_members(self):
        """Source check: behaviour alone cannot prove WHICH accessor is used.

        The old code degraded silently rather than raising — `hasattr` was
        False and `getattr(..., False)` absorbed the rest — so a behavioural
        test would have passed against the broken version for any
        prompt-based model.
        """
        import inspect

        # Comments stripped before scanning: the fix's own comment NAMES the
        # deleted members while explaining why they are gone, and a raw
        # substring scan cannot tell an explanation from a call. Matching on
        # the call/attribute form rather than the bare name for the same
        # reason.
        src = inspect.getsource(EngineClientWrapper._use_native_tools)
        code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())

        assert "get_capabilities_for_model(" not in code
        assert ".native_tool_calling" not in code
        assert "get_facts_for_model(" in code

    def test_an_explicit_flag_still_overrides(self):
        assert _wrapper("prompt_based", method="native")._use_native_tools() is True
        assert _wrapper("native", method="prompt_based")._use_native_tools() is False

    def test_a_provider_without_facts_is_conservative(self):
        w = _wrapper("native")
        del w._client.provider.get_facts_for_model
        w._client.provider = MagicMock(spec=[])
        assert w._use_native_tools() is False


class TestMetadataRecordsWhatHappened:
    """Defect 2 — the field that made comparisons unfalsifiable."""

    @staticmethod
    def _runner(tool_mode, method):
        r = EngineBenchmarkRunner.__new__(EngineBenchmarkRunner)
        r.model = "some-model"
        r.tool_calling_method = method
        r.client = _wrapper(tool_mode, method)
        return r

    def test_a_disagreement_is_recorded_not_hidden(self):
        """The measured case: asked native, provider used prompt-based."""
        got = self._runner("prompt_based", "native")._detect_tool_calling_method()
        assert got == "prompt_based(requested:native)"

    def test_agreement_records_the_plain_method(self):
        assert self._runner("native", "native")._detect_tool_calling_method() == "native"

    def test_auto_records_what_the_provider_resolved(self):
        assert self._runner("native", "auto")._detect_tool_calling_method() == "native"
        assert (
            self._runner("prompt_based", "auto")._detect_tool_calling_method()
            == "prompt_based"
        )

    def test_an_unresolvable_provider_is_marked_unverified(self):
        """Never present a REQUEST as though it were an outcome."""
        r = self._runner("native", "native")
        r.client._client = None
        assert r._detect_tool_calling_method() == "native(unverified)"

    def test_the_request_is_never_returned_bare_when_it_differs(self):
        """The regression, stated as its own assertion.

        Returning the flag verbatim is what let `method=native` sit on a run
        that never sent a tools array.
        """
        got = self._runner("prompt_based", "native")._detect_tool_calling_method()
        assert got != "native"


class TestInfrastructureFailuresAreNotQuality:
    """Defect 3 — 400s and timeouts wearing a score."""

    @pytest.mark.parametrize(
        "error",
        [
            "Error code: 400 - Function tools with reasoning_effort are not supported",
            "Error code: 429 - rate limit exceeded",
            "Error code: 401 - authentication failed",
            "invalid_request_error",
            "Timeout",
            "Connection error.",
            "The model 'x' has reached its end of life on 2026-08-07",
            "insufficient_quota",
        ],
    )
    def test_api_refusals_are_classified_as_infrastructure(self, error):
        assert EngineBenchmarkRunner.is_infrastructure_failure({"error": error}) is True

    @pytest.mark.parametrize(
        "error",
        [
            "Expected 'foo' in response, got 'bar'",
            "Model did not call the tool",
            "Assertion failed: score below threshold",
            "",
        ],
    )
    def test_quality_failures_are_not_excused(self, error):
        """A false POSITIVE here would HIDE a real regression — worse than a
        false negative, which only mis-scores one test."""
        assert EngineBenchmarkRunner.is_infrastructure_failure({"error": error}) is False

    @pytest.mark.parametrize("details", [None, {}, "not a dict", {"other": "x"}])
    def test_non_error_shapes_are_not_infrastructure(self, details):
        assert EngineBenchmarkRunner.is_infrastructure_failure(details) is False

    def test_the_c1_hazard_message_is_covered(self):
        """The specific 400 that started this — pinned by its real text."""
        real = (
            "Error code: 400 - {'error': {'message': \"Function tools with "
            "reasoning_effort are not supported for gpt-5.6-sol in "
            "/v1/chat/completions.\"}}"
        )
        assert EngineBenchmarkRunner.is_infrastructure_failure({"error": real}) is True

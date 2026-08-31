"""`response_format` on the Gemini provider (v1.19.1).

Every other provider forwards `response_format` to an OpenAI-compatible
endpoint (openai_compat.py, openai_native.py, perplexity.py). Gemini uses
generate_content, so it must map onto `response_mime_type` /
`response_schema` instead — and until v1.19.1 it did not, accepting the
parameter and silently dropping it. A caller pinning a JSON schema got a 200
and unconstrained output, with no error raised anywhere.

Found by the gateway smoke's structured-output step; see
docs/handoff-seam-watcher.md.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.providers.gemini import (
    _GEMINI_SCHEMA_KEYS,
    GeminiProvider,
    is_available,
    response_format_to_gemini,
)

pytestmark = pytest.mark.skipif(
    not is_available(), reason="google-genai not installed"
)

CLASSIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string"},
        "confidence": {"type": "number"},
        "suggested_action": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["intent", "confidence", "suggested_action", "reasoning"],
    "additionalProperties": False,
}


def _make_provider() -> GeminiProvider:
    with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
        mock_genai.Client.return_value = MagicMock()
        return GeminiProvider(api_key="test-key", provider_id="gemini")


# ── the mapper ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [None, {}, {"type": "text"}, "nonsense", 42])
def test_unrecognised_shapes_degrade_to_nothing(value):
    """Anything unknown returns {} rather than raising — old behaviour."""
    assert response_format_to_gemini(value) == {}


def test_json_object_sets_mime_type_only():
    assert response_format_to_gemini({"type": "json_object"}) == {
        "response_mime_type": "application/json"
    }


def test_json_schema_sets_mime_type_and_schema():
    out = response_format_to_gemini(
        {"type": "json_schema", "json_schema": {"name": "c", "schema": CLASSIFIER_SCHEMA}}
    )
    assert out["response_mime_type"] == "application/json"
    assert set(out["response_schema"]["properties"]) == {
        "intent", "confidence", "suggested_action", "reasoning"
    }
    assert out["response_schema"]["required"] == CLASSIFIER_SCHEMA["required"]


def test_reuses_the_existing_tool_schema_sanitizer():
    """One whitelist, not two.

    `response_schema` and a function declaration's `parameters` are the same
    google-genai `Schema` model, so they get the same sanitizer. A second
    whitelist would drift from the one verified against the SDK — and an
    earlier revision of this feature DID define a duplicate
    `_GEMINI_SCHEMA_KEYS`, which shadowed the original and silently narrowed
    tool-schema sanitizing until an existing test caught the stripped
    `minimum`.
    """
    assert "minimum" in _GEMINI_SCHEMA_KEYS, (
        "the tool-schema whitelist has been narrowed or shadowed again"
    )


def test_additional_properties_stripped_for_response_schema_only():
    """The one key where response_schema and function declarations diverge.

    The SDK's pydantic Schema model accepts `additionalProperties` — it is in
    _GEMINI_SCHEMA_KEYS and the tool path needs it — but the REST API rejects
    it under generation_config.response_schema. Verified live, not inferred:

      400 INVALID_ARGUMENT — Unknown name "additional_properties" at
      'generation_config.response_schema': Cannot find field.

    So it must survive the shared sanitizer and be stripped afterwards.
    Passing SDK validation is not evidence the API accepts the payload.
    """
    out = response_format_to_gemini(
        {"type": "json_schema", "json_schema": {"schema": CLASSIFIER_SCHEMA}}
    )
    assert "additionalProperties" not in out["response_schema"]
    # …and the tool path must keep it.
    assert "additionalProperties" in _GEMINI_SCHEMA_KEYS


def test_additional_properties_stripped_recursively():
    out = response_format_to_gemini({
        "type": "json_schema",
        "json_schema": {"schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"inner": {"type": "object",
                                     "additionalProperties": False,
                                     "properties": {"a": {"type": "string"}}}},
        }},
    })
    schema = out["response_schema"]
    assert "additionalProperties" not in schema
    assert "additionalProperties" not in schema["properties"]["inner"]


def test_unsupported_keys_are_dropped_not_fatal():
    """`$schema` is not in the SDK's accepted set; it must not reach it.

    The sanitizer is lossy in the permissive direction on purpose — dropping
    a keyword beats a pydantic extra_forbidden that fails the whole request
    client-side.
    """
    out = response_format_to_gemini({
        "type": "json_schema",
        "json_schema": {"schema": {
            "type": "object",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "properties": {"a": {"type": "string"}},
        }},
    })
    assert "$schema" not in out["response_schema"]
    assert out["response_schema"]["properties"]["a"] == {"type": "string"}


def test_constraint_keywords_survive():
    """These are accepted by the SDK Schema model, so don't over-filter."""
    out = response_format_to_gemini({
        "type": "json_schema",
        "json_schema": {"schema": {
            "type": "object",
            "properties": {"n": {"type": "integer", "minimum": 1, "maximum": 9}},
        }},
    })
    assert out["response_schema"]["properties"]["n"] == {
        "type": "integer", "minimum": 1, "maximum": 9}


# ── wiring into _build_config ───────────────────────────────────────────────

def test_build_config_carries_the_schema():
    provider = _make_provider()
    config = provider._build_config(
        use_grounding=False,
        response_format={"type": "json_schema",
                         "json_schema": {"schema": CLASSIFIER_SCHEMA}},
    )
    assert config is not None
    assert config.response_mime_type == "application/json"
    assert config.response_schema is not None


# `test_schema_suppresses_grounding` lived here and asserted the OPPOSITE of
# what the API does. It was written from an untested generalization of the
# function-declaration conflict, and it passed because it tested the same
# wrong assumption the code encoded — the failure mode a unit test cannot
# catch on its own. Superseded by
# `test_structured_output_does_not_disable_grounding` below, which is backed
# by a live call. Removed rather than left skipped: a test asserting the
# wrong contract is worse than no test.


def test_grounding_still_applied_without_a_schema():
    """Guard the plain case, so grounding can't regress for ordinary calls."""
    provider = _make_provider()
    config = provider._build_config(use_grounding=True)
    assert getattr(config, "tools", None), "grounding regressed for plain calls"


def test_no_response_format_leaves_config_untouched():
    provider = _make_provider()
    config = provider._build_config(use_grounding=False, response_format=None)
    assert config is None or getattr(config, "response_mime_type", None) is None


def test_structured_output_does_not_disable_grounding():
    """Grounding and structured output COEXIST — regression guard.

    A pre-release revision suppressed grounding whenever `response_format`
    was set, generalizing the function-declaration conflict without testing
    it. The cost was silent: a caller combining `response_format` with
    `execution.run.grounding` kept its JSON and quietly lost its search.

    Verified live against gemini-3.1-pro-preview (2026-08-09): both
    `google_search + response_mime_type` and
    `google_search + response_mime_type + response_schema` are ACCEPTED.
    """
    provider = _make_provider()
    for rf in ({"type": "json_object"},
               {"type": "json_schema", "json_schema": {"schema": CLASSIFIER_SCHEMA}}):
        config = provider._build_config(use_grounding=True, response_format=rf)
        assert getattr(config, "tools", None), (
            f"grounding was dropped for {rf['type']} — structured output does "
            f"not conflict with google_search"
        )
        assert config.response_mime_type == "application/json"


def test_function_declarations_still_win_over_grounding():
    """The REAL conflict is unchanged: tools and grounding cannot coexist."""
    provider = _make_provider()
    config = provider._build_config(
        use_grounding=True,
        tools=[{"type": "function",
                "function": {"name": "t", "description": "d",
                             "parameters": {"type": "object", "properties": {}}}}],
    )
    tools = getattr(config, "tools", None) or []
    assert not any(getattr(t, "google_search", None) for t in tools), (
        "grounding must still be suppressed when function declarations exist"
    )

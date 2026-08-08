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
    GeminiProvider,
    is_available,
    response_format_to_gemini,
    _GEMINI_SCHEMA_KEYS,
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


def test_schema_suppresses_grounding():
    """Gemini rejects grounding combined with response_schema.

    A caller who pinned a schema asked for the schema, so it wins — the same
    coexistence rule function declarations already follow.
    """
    provider = _make_provider()
    config = provider._build_config(
        use_grounding=True,
        response_format={"type": "json_schema",
                         "json_schema": {"schema": CLASSIFIER_SCHEMA}},
    )
    assert not getattr(config, "tools", None), (
        "grounding must not be attached alongside a response_schema"
    )


def test_grounding_still_applied_without_a_schema():
    """Guard the negative case, so the suppression can't silently over-reach."""
    provider = _make_provider()
    config = provider._build_config(use_grounding=True)
    assert getattr(config, "tools", None), "grounding regressed for plain calls"


def test_no_response_format_leaves_config_untouched():
    provider = _make_provider()
    config = provider._build_config(use_grounding=False, response_format=None)
    assert config is None or getattr(config, "response_mime_type", None) is None

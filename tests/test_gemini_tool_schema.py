"""Gemini tool-schema sanitization (v1.19.0).

Caught live on the /task T5 trial: `spawn_subagent.allow_outbound` declares
`items.oneOf`, and Gemini's function-declaration `Schema` model rejects any
keyword outside its strict OpenAPI subset with pydantic `extra_forbidden` —
failing the WHOLE request client-side, so the run dies instantly:

    error: Gemini error (ValidationError): 1 validation error for Tool
    function_declarations.1.parameters.properties.allow_outbound.items.oneOf
    Extra inputs are not permitted

OpenAI-compatible providers pass raw JSON Schema through, which is why this
only surfaces on a native-Gemini parent run. The fix sanitizes EVERY tool's
parameters in `_convert_tools_to_gemini` (provider-side, plug-n-play), so a
future tool with a modern JSON-Schema keyword can't reintroduce the failure.
"""

from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.providers.gemini import _sanitize_schema_for_gemini


class TestSanitizeSchemaForGemini:
    def test_simple_schema_passes_through_unchanged(self):
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "file path"},
                "count": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        }
        assert _sanitize_schema_for_gemini(schema) == schema

    def test_non_dict_passes_through(self):
        assert _sanitize_schema_for_gemini(None) is None
        assert _sanitize_schema_for_gemini("string") == "string"

    def test_oneof_becomes_anyof_recursively(self):
        schema = {
            "type": "array",
            "items": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "object", "properties": {"host": {"type": "string"}},
                     "required": ["host"]},
                ]
            },
        }
        result = _sanitize_schema_for_gemini(schema)
        assert "oneOf" not in result["items"]
        variants = result["items"]["anyOf"]
        assert {"type": "string"} in variants
        assert any(v.get("type") == "object" for v in variants)

    def test_oneof_merges_into_existing_anyof(self):
        schema = {
            "anyOf": [{"type": "string"}],
            "oneOf": [{"type": "integer"}],
        }
        result = _sanitize_schema_for_gemini(schema)
        assert {"type": "string"} in result["anyOf"]
        assert {"type": "integer"} in result["anyOf"]

    def test_allof_shallow_merges_variants(self):
        schema = {
            "allOf": [
                {"type": "object", "properties": {"a": {"type": "string"}},
                 "required": ["a"]},
                {"properties": {"b": {"type": "integer"}}, "required": ["b"]},
            ]
        }
        result = _sanitize_schema_for_gemini(schema)
        assert "allOf" not in result
        assert set(result["properties"]) == {"a", "b"}
        assert result["required"] == ["a", "b"]

    def test_list_type_becomes_single_type_plus_nullable(self):
        result = _sanitize_schema_for_gemini({"type": ["string", "null"]})
        assert result == {"type": "string", "nullable": True}

    def test_unsupported_keywords_are_dropped(self):
        schema = {
            "type": "object",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "unevaluatedProperties": False,
            "properties": {"x": {"type": "string", "const": "y"}},
        }
        result = _sanitize_schema_for_gemini(schema)
        assert "$schema" not in result
        assert "unevaluatedProperties" not in result
        assert "const" not in result["properties"]["x"]

    def test_nested_properties_and_items_are_sanitized(self):
        schema = {
            "type": "object",
            "properties": {
                "rules": {
                    "type": "array",
                    "items": {"oneOf": [{"type": "string"}]},
                }
            },
        }
        result = _sanitize_schema_for_gemini(schema)
        assert result["properties"]["rules"]["items"] == {
            "anyOf": [{"type": "string"}]
        }


class TestConvertToolsAppliesSanitizer:
    @pytest.fixture
    def provider(self):
        from ppxai.engine.providers.gemini import GeminiProvider

        with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            provider = GeminiProvider(api_key="test")
        return provider

    def test_convert_tools_sanitizes_parameters(self, provider):
        tools = [{
            "type": "function",
            "function": {
                "name": "spawnish",
                "description": "…",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "allow_outbound": {
                            "type": "array",
                            "items": {"oneOf": [{"type": "string"}]},
                        }
                    },
                },
            },
        }]
        [decl] = provider._convert_tools_to_gemini(tools)
        items = decl["parameters"]["properties"]["allow_outbound"]["items"]
        assert "oneOf" not in items
        assert items["anyOf"] == [{"type": "string"}]


class TestSpawnSubagentSchemaRegression:
    """The exact live failure: the REAL spawn_subagent schema must validate
    against the REAL google-genai Schema model after sanitization."""

    def _sdk_types(self):
        genai = pytest.importorskip("google.genai")
        return genai.types

    def _spawn_parameters(self):
        from ppxai.engine.tools.agent_spawn import SpawnSubagentTool
        return SpawnSubagentTool.parameters

    def test_raw_spawn_schema_is_rejected_by_sdk(self):
        # Documents WHY the sanitizer exists. If this ever starts passing,
        # the SDK grew oneOf support and the downgrade can be revisited.
        types = self._sdk_types()
        with pytest.raises(Exception):
            types.Schema.model_validate(self._spawn_parameters())

    def test_sanitized_spawn_schema_validates_against_sdk(self):
        types = self._sdk_types()
        sanitized = _sanitize_schema_for_gemini(self._spawn_parameters())
        types.Schema.model_validate(sanitized)  # must not raise

    def test_sanitized_spawn_schema_keeps_both_rule_forms(self):
        # The AC-2 contract: egress rules are host strings OR {host, paths}.
        # The downgrade must keep both variants visible to the model.
        sanitized = _sanitize_schema_for_gemini(self._spawn_parameters())
        variants = sanitized["properties"]["allow_outbound"]["items"]["anyOf"]
        assert {"type": "string"} in variants
        obj = next(v for v in variants if v.get("type") == "object")
        assert obj["required"] == ["host"]

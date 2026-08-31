"""`/task` T3 — agent spec loader unit tests (engine/agent_spec.py).

Pure normalization: no filesystem trust decisions here (those live in the route
resolver). Covers md front-matter, json, yaml, jsonl batch, coercion, and errors.
"""

import pytest

from ppxai.engine.agent_spec import (
    AgentSpecError,
    load_batch_lines,
    load_spec_file,
    parse_spec,
    spec_from_mapping,
)


class TestMarkdownFrontMatter:
    def test_front_matter_plus_body(self):
        text = (
            "---\n"
            "tools: [read_file, grep]\n"
            "provider: nim\n"
            "model: qwen\n"
            "budget: {iterations: 5, time_s: 60}\n"
            "network: [example.com]\n"
            "---\n"
            "You are a CI triage agent. Be terse.\n"
        )
        spec = parse_spec(text, "md")
        assert spec.tools == ["read_file", "grep"]
        assert spec.provider == "nim" and spec.model == "qwen"
        assert spec.budget == {"iterations": 5, "time_s": 60}
        assert spec.network == ["example.com"]
        # body -> system (front-matter had no explicit system)
        assert spec.system == "You are a CI triage agent. Be terse."

    def test_explicit_system_in_frontmatter_wins_over_body(self):
        text = "---\nsystem: FM system\ntools: [read_file]\n---\nbody prose\n"
        spec = parse_spec(text, "md")
        assert spec.system == "FM system"  # body does not overwrite

    def test_no_front_matter_whole_doc_is_system(self):
        spec = parse_spec("just prose, no fences\n", "md")
        assert spec.system == "just prose, no fences"
        assert spec.tools is None

    def test_crlf_front_matter(self):
        text = "---\r\ntools: [read_file]\r\n---\r\nbody\r\n"
        spec = parse_spec(text, "md")
        assert spec.tools == ["read_file"]
        assert spec.system == "body"


class TestJsonYaml:
    def test_json(self):
        spec = parse_spec('{"task":"t","tools":["grep"],"model":"m"}', "json")
        assert spec.task == "t" and spec.tools == ["grep"] and spec.model == "m"

    def test_yaml(self):
        spec = parse_spec("task: t\ntools:\n  - grep\n  - read_file\n", "yaml")
        assert spec.tools == ["grep", "read_file"]


class TestCoercion:
    def test_tools_scalar_string_splits(self):
        assert spec_from_mapping({"tools": "read_file, grep write_file"}).tools == [
            "read_file", "grep", "write_file",
        ]

    def test_network_dict_form(self):
        assert spec_from_mapping({"network": {"allow_outbound": ["a.com"]}}).network == ["a.com"]

    def test_budget_partial_and_int_coercion(self):
        assert spec_from_mapping({"budget": {"tokens": "1000"}}).budget == {"tokens": 1000}

    def test_unknown_keys_ignored_with_warning(self):
        spec = spec_from_mapping({"tools": ["grep"], "bogus": 1, "also_bad": 2})
        assert spec.tools == ["grep"]
        assert spec.warnings and "bogus" in spec.warnings[0]

    def test_read_paths_parsed_but_inert(self):
        spec = spec_from_mapping({"read_paths": {"allow": ["~/x"]}})
        assert spec.read_paths == {"allow": ["~/x"]}


class TestErrors:
    def test_non_mapping_rejected(self):
        with pytest.raises(AgentSpecError):
            spec_from_mapping(["not", "a", "mapping"])

    def test_bad_tools_type(self):
        with pytest.raises(AgentSpecError):
            spec_from_mapping({"tools": 123})

    def test_bad_budget_value(self):
        with pytest.raises(AgentSpecError):
            spec_from_mapping({"budget": {"iterations": "notanint"}})

    def test_invalid_yaml(self):
        with pytest.raises(AgentSpecError):
            parse_spec("task: [unclosed\n", "yaml")

    def test_unknown_format(self):
        with pytest.raises(AgentSpecError):
            parse_spec("x", "toml")


class TestLoadSpecFile:
    def test_dispatch_by_suffix(self, tmp_path):
        p = tmp_path / "triage.md"
        p.write_text("---\ntools: [read_file]\n---\nsys\n", encoding="utf-8")
        spec = load_spec_file(p)
        assert spec.tools == ["read_file"] and spec.system == "sys"

    def test_unsupported_extension(self, tmp_path):
        p = tmp_path / "x.txt"
        p.write_text("hi", encoding="utf-8")
        with pytest.raises(AgentSpecError):
            load_spec_file(p)

    def test_oversized_rejected(self, tmp_path):
        from ppxai.engine import agent_spec
        p = tmp_path / "big.md"
        p.write_text("x" * (agent_spec.MAX_SPEC_BYTES + 1), encoding="utf-8")
        with pytest.raises(AgentSpecError):
            load_spec_file(p)


class TestBatch:
    def test_jsonl_lines(self):
        rows = load_batch_lines('{"task":"a"}\n\n{"task":"b","tools":["grep"]}\n')
        assert [r["task"] for r in rows] == ["a", "b"]

    def test_jsonl_bad_line_reports_number(self):
        with pytest.raises(AgentSpecError) as ei:
            load_batch_lines('{"task":"a"}\nnot json\n')
        assert "line 2" in str(ei.value)

    def test_jsonl_non_object_line(self):
        with pytest.raises(AgentSpecError):
            load_batch_lines("[1,2,3]\n")

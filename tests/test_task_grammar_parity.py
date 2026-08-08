"""Parity + behaviour tests for the ported `/task` · `/run` grammar (T8b).

`ppxai/engine/task_grammar.py` is a port of the grammar in
`ppxai/web/shared/task-controller.js`. The web client stays the behavioural
reference, so these tests read BOTH sources and compare them. Hardcoding the
expected verb/flag sets would rot the moment either side changed — the point
is that a change to one without the other fails here.

Same idiom as the other cross-language sentinels in this suite (see
`test_vscode_task_controller.py`, `test_appstate_schema_parity.py`).
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from ppxai.engine import task_grammar as tg
from ppxai.engine.task_grammar import Action, classify, parse_task_args, tokenize

JS = Path(__file__).resolve().parents[1] / "ppxai" / "web" / "shared" / "task-controller.js"


def _js_source() -> str:
    assert JS.exists(), f"web reference missing: {JS}"
    return JS.read_text(encoding="utf-8")


# ── parity sentinels ────────────────────────────────────────────────────────

def test_verb_set_matches_web_client():
    """The Python verb set is exactly the web client's TASK_VERBS."""
    src = _js_source()
    block = re.search(r"const TASK_VERBS = new Set\(\[(.*?)\]\)", src, re.S)
    assert block, "TASK_VERBS not found in task-controller.js"
    js_verbs = set(re.findall(r"'([a-z]+)'", block.group(1)))

    assert js_verbs, "parsed an empty verb set — the sentinel would pass vacuously"
    assert tg.TASK_VERBS == js_verbs, (
        f"verb drift — python-only: {sorted(tg.TASK_VERBS - js_verbs)}, "
        f"js-only: {sorted(js_verbs - tg.TASK_VERBS)}"
    )


def test_run_id_shape_matches_web_client():
    """`run_` + 12 hex, pinned on both sides (agent_runs.py token_hex(6))."""
    src = _js_source()
    js_id = re.search(r"const RUN_ID_RE = /(.+?)/;", src)
    js_ish = re.search(r"const RUN_ID_ISH_RE = /(.+?)/;", src)
    assert js_id and js_ish, "run-id regexes not found in task-controller.js"

    assert tg.RUN_ID_RE.pattern == js_id.group(1)
    assert tg.RUN_ID_ISH_RE.pattern == js_ish.group(1)


def test_flag_set_matches_web_client():
    """Every `--flag` the web parser handles is handled here, and vice versa."""
    js_flags = set(re.findall(r"case '(--[a-z-]+)':", _js_source()))
    py_flags = set(re.findall(r't == "(--[a-z-]+)"', inspect.getsource(parse_task_args)))

    assert js_flags, "parsed an empty JS flag set — sentinel would pass vacuously"
    assert py_flags == js_flags, (
        f"flag drift — python-only: {sorted(py_flags - js_flags)}, "
        f"js-only: {sorted(js_flags - py_flags)}"
    )


# ── U2 dispatch grammar ─────────────────────────────────────────────────────

RUN_ID = "run_0123456789ab"


def test_empty_line_is_help():
    assert classify("   ").action is Action.HELP


@pytest.mark.parametrize("line,verb", [("ls", "ls"), ("help", "help"), ("LIST", "list")])
def test_bare_verb_is_lifecycle(line, verb):
    d = classify(line)
    assert d.action is Action.LIFECYCLE and d.verb == verb


def test_verb_with_run_id_is_lifecycle():
    d = classify(f"get {RUN_ID}")
    assert d.action is Action.LIFECYCLE
    assert d.verb == "get" and d.run_id == RUN_ID


def test_verb_followed_by_prose_launches():
    """The load-bearing U2 rule: a verb only counts when followed by an id."""
    d = classify("get the weather in Geneva --tools web_search")
    assert d.action is Action.LAUNCH
    assert d.rest == "get the weather in Geneva --tools web_search"


def test_near_miss_id_fails_loud_and_never_launches():
    """A truncated/typo'd id must not become a run whose prompt is the typo."""
    d = classify("cancel run_012345")
    assert d.action is Action.NEAR_MISS and d.run_id == "run_012345"


def test_non_verb_first_token_launches():
    assert classify("summarize docs/README.md").action is Action.LAUNCH


def test_id_taking_verb_uses_only_first_token():
    """Multi-line paste degrades to the first id, not one bogus blob id."""
    d = classify(f"get {RUN_ID}\nsome trailing junk")
    assert d.action is Action.LIFECYCLE and d.run_id == RUN_ID


def test_oneshot_cannot_park_verbs_are_declared():
    """`/run` has no respond/resume — a oneshot never parks (U3)."""
    assert tg.RUN_ONLY_EXCLUDED_VERBS < tg.TASK_VERBS


# ── launch-line parsing ─────────────────────────────────────────────────────

def test_quoted_description_and_flags():
    a = parse_task_args('"summarize the docs" --tools read_file,web_search')
    assert a.task == "summarize the docs"
    assert a.tools == ["read_file", "web_search"]
    assert not a.errors


def test_bare_description_runs_until_first_flag():
    a = parse_task_args("summarize the docs --tools read_file")
    assert a.task == "summarize the docs"
    assert a.tools == ["read_file"]


def test_budget_suffixes_and_aliases():
    a = parse_task_args("t --budget iters=5,time=1.5m,tokens=100k")
    assert a.budget == {"iterations": 5, "time_s": 1.5e6, "tokens": 100_000}
    assert not a.errors


def test_egress_entry_scoping():
    a = parse_task_args("t --allow example.com,api.host/v1/x")
    assert a.network["allow_outbound"] == [
        "example.com",
        {"host": "api.host", "paths": ["/v1/x"]},
    ]


def test_skills_compose_and_dedupe():
    a = parse_task_args("t --skill a,b --skill b --skill c")
    assert a.skills == ["a", "b", "c"]


@pytest.mark.parametrize("value,expected", [("on", True), ("off", False)])
def test_enrichment_tristate(value, expected):
    assert parse_task_args(f"t --enrichment {value}").enrichment is expected


def test_enrichment_rejects_other_values():
    a = parse_task_args("t --enrichment maybe")
    assert a.enrichment is None
    assert any("on|off" in e for e in a.errors)


def test_unknown_flag_is_an_error():
    a = parse_task_args("t --nope x")
    assert any("unknown flag: --nope" in e for e in a.errors)


def test_flag_missing_value_is_an_error():
    a = parse_task_args("t --tools --model m")
    assert any("--tools needs a value" in e for e in a.errors)


def test_tokenizer_handles_both_quote_styles():
    assert tokenize("""a "b c" 'd e' f""") == ["a", "b c", "d e", "f"]

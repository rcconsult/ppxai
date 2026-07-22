"""`/agentrun` argument parsing (parseAgentRunArgs).

Regression for the v1.19.1 fix: the web `/agentrun` command used to ignore
`--provider`/`--model` (it passed the whole arg string as the task and used the
UI's current provider), so `/agentrun --provider perplexity "…"` silently ran on
the UI default. The parser now extracts those two flags wherever they appear.

Driven through Node so we test the real shipped parser, not a Python re-impl.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
CONTROLLER = (
    Path(__file__).resolve().parents[1]
    / "ppxai" / "web" / "shared" / "agent-run-controller.js"
)

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _parse(argline: str) -> dict:
    harness = (
        "const { parseAgentRunArgs } = require(%s);\n"
        "process.stdout.write(JSON.stringify(parseAgentRunArgs(process.argv[1])));\n"
        % json.dumps(str(CONTROLLER))
    )
    # `--` ends Node's own option parsing so a leading `--provider` in argline
    # reaches the script as process.argv[1] instead of being read as a node flag.
    out = subprocess.check_output([NODE, "-e", harness, "--", argline], text=True)
    return json.loads(out)


def test_bare_task_no_flags():
    assert _parse("weather in Ornex today") == {
        "task": "weather in Ornex today", "provider": None, "model": None
    }


def test_flags_after_task():
    r = _parse("weather in Ornex today --provider perplexity")
    assert r["task"] == "weather in Ornex today"
    assert r["provider"] == "perplexity"
    assert r["model"] is None


def test_flags_before_task():
    # The exact shape the user typed that used to be swallowed into the prompt.
    r = _parse('--provider perplexity weather in Ornex today')
    assert r["task"] == "weather in Ornex today"
    assert r["provider"] == "perplexity"


def test_provider_and_model_with_quoted_task():
    r = _parse('--provider perplexity --model sonar "hourly weather in Ornex"')
    assert r["task"] == "hourly weather in Ornex"
    assert r["provider"] == "perplexity"
    assert r["model"] == "sonar"


def test_flag_in_the_middle():
    r = _parse("weather --model sonar today")
    assert r["task"] == "weather today"
    assert r["model"] == "sonar"


def test_unknown_flag_stays_in_task():
    # Only --provider/--model are recognized; anything else is free-form prose.
    r = _parse("summarize --verbose the news")
    assert r["task"] == "summarize --verbose the news"
    assert r["provider"] is None and r["model"] is None


def test_dangling_provider_flag_not_eaten():
    # `--provider` with no value (end of line) is left in the task, not consumed.
    r = _parse("weather today --provider")
    assert r["provider"] is None
    assert "--provider" in r["task"]

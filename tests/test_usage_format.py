"""Cross-language parity for format_tokens and format_usage_badge.

v1.18.0 Phase 4 of stabilization. The same user-visible strings are
produced by three different codebases:

    Python:  ppxai/common/format.py                (Rich TUI, server)
    JS:      ppxai/web/shared/formatters.js        (web app)
    TS:      vscode-extension/src/shared/formatters.ts  (VSCode host)
    webview: vscode-extension/media/webview/main.js     (inline copy)

Auto-generating one from the other requires a build step nobody's
going to run consistently, so the three copies are hand-maintained.
These tests invoke the Python functions, then shell out to node to
run the JS/TS versions against the same fixture set, and assert
byte-for-byte equality.

If any of the four copies drifts, this test fails and names which
one disagreed with Python — the canonical source.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ppxai.common.format import format_tokens, format_usage_badge

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Fixture table — representative points across the K-suffix threshold,
#    edge cases (0, exactly 1000, cost = 0), and common real-world values.
TOKEN_FIXTURES = [0, 1, 999, 1000, 1200, 15300, 128000, 1_000_000]

USAGE_FIXTURES = [
    # (prompt, completion, cost)
    (0, 0, 0.0),
    (1, 1, 0.0),
    (1200, 450, 0.0045),
    (15300, 8700, 0.1234),
    (128000, 64000, 12.3456),
]


# ──────────────────────────────────────────────────────────────────
# Python — baseline behaviour of format_tokens + format_usage_badge.
# These tests are the authoritative contract that the JS/TS copies
# must match.
# ──────────────────────────────────────────────────────────────────
class TestFormatTokensPython:
    def test_below_threshold_returns_integer_string(self):
        assert format_tokens(0) == "0"
        assert format_tokens(1) == "1"
        assert format_tokens(999) == "999"

    def test_at_threshold_promotes_to_k_suffix(self):
        assert format_tokens(1000) == "1.0K"

    def test_k_suffix_uses_one_decimal_place(self):
        assert format_tokens(1200) == "1.2K"
        assert format_tokens(15300) == "15.3K"

    def test_very_large_values_still_use_one_decimal(self):
        assert format_tokens(128_000) == "128.0K"
        assert format_tokens(1_000_000) == "1000.0K"


class TestFormatUsageBadgePython:
    def test_zero_case(self):
        assert format_usage_badge(0, 0, 0.0) == "0↓/0↑ $0.0000"

    def test_sub_k_tokens_with_cents(self):
        assert format_usage_badge(1200, 450, 0.0045) == "1.2K↓/450↑ $0.0045"

    def test_both_sides_over_threshold(self):
        assert format_usage_badge(15300, 8700, 0.1234) == "15.3K↓/8.7K↑ $0.1234"

    def test_cost_always_four_decimals(self):
        # Cost pads to four places even when values would round off.
        assert format_usage_badge(100, 100, 12.3) == "100↓/100↑ $12.3000"


# ──────────────────────────────────────────────────────────────────
# JS / TS parity — shell out to node, run the mirrored function, and
# assert the string matches the Python output byte-for-byte.
# ──────────────────────────────────────────────────────────────────

_JS_HARNESS_HEAD = r"""
const fixturesIn = JSON.parse(process.argv[1]);
const outputs = [];
"""

_JS_HARNESS_TAIL = r"""
process.stdout.write(JSON.stringify(outputs));
"""


def _node_available() -> bool:
    try:
        return subprocess.run(
            ["node", "--version"], capture_output=True, timeout=5
        ).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_node(script: str, fixtures: Any) -> list:
    # Force UTF-8 so non-ASCII characters in badge output (↓ ↑) survive
    # the round-trip. Windows default codepage on capture is cp1252
    # otherwise, which mangles the arrow glyphs.
    result = subprocess.run(
        ["node", "-e", script, json.dumps(fixtures)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    if result.returncode != 0:
        pytest.fail(
            f"node harness failed:\nstdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}"
        )
    return json.loads(result.stdout)


def _extract_function(source_path: Path, fn_name: str) -> str:
    """Pull a top-level `function <name>(...)` block from a JS file
    using brace-balancing. Matches the helper in
    `test_agent_beat_cross_client_parity.py`.
    """
    source = source_path.read_text(encoding="utf-8")
    pattern = re.compile(rf"function\s+{re.escape(fn_name)}\s*\([^)]*\)\s*\{{")
    match = pattern.search(source)
    if not match:
        pytest.fail(f"Could not find function {fn_name} in {source_path}")
    start = match.start()
    depth = 0
    i = match.end() - 1
    while i < len(source):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    pytest.fail(f"Unbalanced braces in {fn_name}")


def _extract_ts_function(source_path: Path, fn_name: str) -> str:
    """TS function has `export function name(arg: type): ret { ... }`.

    Same brace-balance extraction. We then strip the leading `export`
    and type annotations are left in place — node ignores them
    because TS syntax is a superset that runs fine as plain JS when
    the file doesn't use types at runtime. Fail if that assumption
    breaks for a given function; we'll transpile for real at that point.
    """
    source = source_path.read_text(encoding="utf-8")
    # Match `export function NAME(...)` with an optional `:` return type
    # before the body's `{`.
    pattern = re.compile(
        rf"export\s+function\s+{re.escape(fn_name)}\s*\([^)]*\)"
        r"(?:\s*:\s*[^{]+)?\s*\{"
    )
    match = pattern.search(source)
    if not match:
        pytest.fail(f"Could not find export function {fn_name} in {source_path}")
    start = match.start()
    depth = 0
    i = match.end() - 1
    while i < len(source):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                # Strip the leading `export ` so node treats it as a
                # plain function declaration.
                fn_body = source[start : i + 1]
                return fn_body.replace("export function", "function", 1)
        i += 1
    pytest.fail(f"Unbalanced braces in {fn_name}")


# ── Web (shared/formatters.js) ──────────────────────────────────────


@pytest.mark.parametrize("n", TOKEN_FIXTURES)
def test_web_format_tokens_matches_python(n: int) -> None:
    if not _node_available():
        pytest.skip("node not available")
    fn_src = _extract_function(
        REPO_ROOT / "ppxai" / "web" / "shared" / "formatters.js",
        "formatTokens",
    )
    script = _JS_HARNESS_HEAD + fn_src + r"""
for (const n of fixturesIn) {
    outputs.push(formatTokens(n));
}
""" + _JS_HARNESS_TAIL
    js_output = _run_node(script, [n])
    assert js_output == [format_tokens(n)]


@pytest.mark.parametrize("fixture", USAGE_FIXTURES)
def test_web_format_usage_badge_matches_python(fixture) -> None:
    if not _node_available():
        pytest.skip("node not available")
    prompt, completion, cost = fixture
    tokens_src = _extract_function(
        REPO_ROOT / "ppxai" / "web" / "shared" / "formatters.js",
        "formatTokens",
    )
    usage_src = _extract_function(
        REPO_ROOT / "ppxai" / "web" / "shared" / "formatters.js",
        "formatUsageBadge",
    )
    script = _JS_HARNESS_HEAD + tokens_src + "\n" + usage_src + r"""
for (const [p, c, cost] of fixturesIn) {
    outputs.push(formatUsageBadge(p, c, cost));
}
""" + _JS_HARNESS_TAIL
    js_output = _run_node(script, [[prompt, completion, cost]])
    assert js_output == [format_usage_badge(prompt, completion, cost)]


# ── VSCode webview inline copy ──────────────────────────────────────


@pytest.mark.parametrize("n", TOKEN_FIXTURES)
def test_vscode_webview_format_tokens_matches_python(n: int) -> None:
    if not _node_available():
        pytest.skip("node not available")
    fn_src = _extract_function(
        REPO_ROOT / "vscode-extension" / "media" / "webview" / "main.js",
        "formatTokens",
    )
    script = _JS_HARNESS_HEAD + fn_src + r"""
for (const n of fixturesIn) {
    outputs.push(formatTokens(n));
}
""" + _JS_HARNESS_TAIL
    js_output = _run_node(script, [n])
    assert js_output == [format_tokens(n)]


# ── VSCode extension-host TS copy ───────────────────────────────────


@pytest.mark.parametrize("n", TOKEN_FIXTURES)
def test_vscode_ts_format_tokens_matches_python(n: int) -> None:
    if not _node_available():
        pytest.skip("node not available")
    fn_src = _extract_ts_function(
        REPO_ROOT / "vscode-extension" / "src" / "shared" / "formatters.ts",
        "formatTokens",
    )
    script = _JS_HARNESS_HEAD + fn_src + r"""
for (const n of fixturesIn) {
    outputs.push(formatTokens(n));
}
""" + _JS_HARNESS_TAIL
    js_output = _run_node(script, [n])
    assert js_output == [format_tokens(n)]


@pytest.mark.parametrize("fixture", USAGE_FIXTURES)
def test_vscode_ts_format_usage_badge_matches_python(fixture) -> None:
    if not _node_available():
        pytest.skip("node not available")
    prompt, completion, cost = fixture
    tokens_src = _extract_ts_function(
        REPO_ROOT / "vscode-extension" / "src" / "shared" / "formatters.ts",
        "formatTokens",
    )
    usage_src = _extract_ts_function(
        REPO_ROOT / "vscode-extension" / "src" / "shared" / "formatters.ts",
        "formatUsageBadge",
    )
    script = _JS_HARNESS_HEAD + tokens_src + "\n" + usage_src + r"""
for (const [p, c, cost] of fixturesIn) {
    outputs.push(formatUsageBadge(p, c, cost));
}
""" + _JS_HARNESS_TAIL
    js_output = _run_node(script, [[prompt, completion, cost]])
    assert js_output == [format_usage_badge(prompt, completion, cost)]

"""Behavioural fence for VSCode `taskController.ts::eventText` (debt Item 82).

Same idiom as `tests/test_vscode_schema_guard_behavior.py`: the real
TypeScript is compiled with the extension's own esbuild and driven under
plain Node — `taskController.ts` imports nothing (no `vscode` module, no
sibling TS files), so it bundles standalone with a one-line re-export entry.

Before commit 59702221, the runner started persisting `turn_degraded` /
`turn_end` audit records to a `/task` run's events.jsonl (`task_runner.py`
TURN_DEGRADED_EVENT / TURN_END_EVENT), but neither client rendered them.
VSCode's `eventText` falls through its `switch` to `default: return null`
for any unrecognised type — silently INVISIBLE (unlike the web pane, whose
`default` branch rendered the bare literal type string). This pins the fix:
both types now render informative text, a missing `degraded` key renders as
explicitly unknown (never silently clean), and `turn_end` is never treated
as one of the tail's stop events.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "vscode-extension"
SRC = EXT / "src"
CONTROLLER = SRC / "taskController.ts"
ESBUILD = EXT / "node_modules" / ".bin" / "esbuild"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    NODE is None or not ESBUILD.exists(),
    reason="node and vscode-extension/node_modules/.bin/esbuild are required",
)

_ENTRY = "export { eventText, TERMINAL_EVENTS } from './taskController';\n"


def _bundle(tmp_path: Path) -> Path:
    """Compile the real `taskController.ts` into a scratch CJS bundle.

    `taskController.ts` has no imports (confirmed: no `import`/`require` in
    the file), so no other module needs copying alongside it — unlike the
    AppState schema-guard harness, which bundles four interdependent files.
    """
    work = tmp_path / "bundle-src"
    work.mkdir(parents=True, exist_ok=True)
    (work / "taskController.ts").write_text(
        CONTROLLER.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (work / "entry.ts").write_text(_ENTRY, encoding="utf-8")

    out = tmp_path / "bundle.js"
    proc = subprocess.run(
        [
            str(ESBUILD), str(work / "entry.ts"), "--bundle", "--format=cjs",
            "--platform=node", "--target=node18", f"--outfile={out}",
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"esbuild failed:\n{proc.stderr}"
    return out


_HARNESS = r"""
const B = require(process.env.PPXAI_BUNDLE);
const { eventText, TERMINAL_EVENTS } = B;

function assert(cond, msg) { if (!cond) throw new Error('FAIL: ' + msg); }

// turn_degraded: reason + tool + budget fields all present.
const deg = eventText({ type: 'turn_degraded', data: {
    reason: 'tool_budget_exhausted', tool: 'web_search', budget: 3, refusal_count: 2,
} });
assert(deg !== null, 'turn_degraded must not be invisible (was: null)');
assert(/turn degraded/.test(deg), 'missing label: ' + deg);
assert(/tool_budget_exhausted/.test(deg), 'dropped reason: ' + deg);
assert(/web_search/.test(deg), 'dropped tool: ' + deg);
assert(/budget 3/.test(deg), 'dropped budget: ' + deg);
assert(/refusal #2/.test(deg), 'dropped refusal_count: ' + deg);

// turn_end: degraded true -> reasons joined.
const endDegraded = eventText({ type: 'turn_end', data: { degraded: true, degradation_reasons: ['tool_repeat_loop'] } });
assert(endDegraded !== null, 'turn_end must not be invisible (was: null)');
assert(/degraded: tool_repeat_loop/.test(endDegraded), 'missing reasons: ' + endDegraded);

// turn_end: degraded false -> exactly "turn ended".
const endClean = eventText({ type: 'turn_end', data: { degraded: false } });
assert(endClean === 'turn ended', "degraded=false must render exactly 'turn ended': " + endClean);

// turn_end: degraded ABSENT -> explicitly unknown, never defaulted to clean.
const endUnknown = eventText({ type: 'turn_end', data: {} });
assert(/unknown/.test(endUnknown), 'missing-degraded must say unknown: ' + endUnknown);
assert(endUnknown !== 'turn ended', 'missing-degraded must NOT render as clean');

// turn_end: engine_event agent_run_error folds its reason in.
const endErr = eventText({ type: 'turn_end', data: { degraded: false, engine_event: 'agent_run_error', reason: 'provider_error' } });
assert(/provider_error/.test(endErr), 'dropped agent_run_error reason: ' + endErr);

// turn_end must never be treated as one of the tail's stop events — the
// runner comment is explicit that a second "ended" name under the run's
// terminal set would end a live watch early.
assert(!TERMINAL_EVENTS.has('turn_end'), 'turn_end must not be a TERMINAL_EVENTS member');
assert(!TERMINAL_EVENTS.has('turn_degraded'), 'turn_degraded must not be a TERMINAL_EVENTS member');

// An unrelated unknown type still renders nothing (unchanged prior behaviour).
assert(eventText({ type: 'some_future_type', data: {} }) === null, 'unrelated unknown types must stay invisible');

console.log('ALL OK');
"""


def test_vscode_event_text_renders_turn_degraded_and_turn_end(tmp_path):
    bundle = _bundle(tmp_path)
    env = {
        "PPXAI_BUNDLE": str(bundle),
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    proc = subprocess.run(
        [NODE, "-e", _HARNESS], capture_output=True, text=True, timeout=30, env=env,
    )
    assert proc.returncode == 0, f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    assert "ALL OK" in proc.stdout, proc.stdout


_ESCAPING_HARNESS = r"""
const B = require(process.env.PPXAI_BUNDLE);
const { eventText } = B;
function assert(cond, msg) { if (!cond) throw new Error('FAIL: ' + msg); }

// eventText returns a plain string — no HTML is ever built here, so a
// malicious reason/tool string (attacker-controlled: the tool name and
// reason come from the model / engine metadata) passes through verbatim
// as TEXT. The caller (runWatch) feeds it to ui.system(), the same
// plain-text sink every other event line already uses (tool_call,
// agent_waiting, path_denied, …) — no new sink, no new escaping burden.
const malicious = '<img src=x onerror=alert(1)>';
const deg = eventText({ type: 'turn_degraded', data: { reason: malicious, tool: malicious } });
assert(typeof deg === 'string' && deg.includes(malicious), 'malicious text must survive as plain text: ' + deg);
console.log('ALL OK');
"""


def test_vscode_event_text_turn_degraded_is_plain_text(tmp_path):
    bundle = _bundle(tmp_path)
    env = {
        "PPXAI_BUNDLE": str(bundle),
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    proc = subprocess.run(
        [NODE, "-e", _ESCAPING_HARNESS], capture_output=True, text=True, timeout=30, env=env,
    )
    assert proc.returncode == 0, f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    assert "ALL OK" in proc.stdout, proc.stdout

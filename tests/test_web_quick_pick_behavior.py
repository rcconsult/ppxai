"""Behavioural test for web's `prompt_quick_pick` consumer.

`/checkpoint clear` reaches the web client as a `NotificationResult` plus
a `prompt_quick_pick` side-effect (2026-09-21) — the confirmation that
let VSCode's last `LEGACY_INTERCEPTS` row migrate. Web needed no new
code for it: `SideEffectsHandler._handlers.prompt_quick_pick` has
existed since v1.18.1 for `/show @x`. "Needed no new code" is exactly
the claim that deserves a test rather than an assertion, so this drives
the REAL `ppxai/web/shared/side-effects.js` under Node with the payload
`_checkpoint_clear` actually emits, and checks the two things the safety
of the feature rests on:

  1. **Cancel renders FIRST.** The order is the engine's and the client
     must not reorder or sort it — a picker that puts the destructive
     row first turns a stray click or Enter into a permanent deletion.
  2. **Clicking Cancel dispatches `/checkpoint clear --no`**, through
     the ordinary command dispatcher, with the value intact across the
     HTML round trip (it contains a space and a `--` flag).

The DOM is stubbed to exactly what the handler touches — `document
.addEventListener` and an element with `closest()` + `dataset` — so the
handler under test is the shipped one, not a copy.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
SHARED = Path(__file__).resolve().parents[1] / "ppxai" / "web" / "shared"
SIDE_EFFECTS = SHARED / "side-effects.js"

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


_HARNESS = r"""
const { SideEffectsHandler } = require(process.env.PPXAI_SIDE_EFFECTS);

function assert(cond, msg) { if (!cond) throw new Error('FAIL: ' + msg); }

// --- the minimum DOM the handler touches ---------------------------------
const listeners = {};
global.document = {
    addEventListener(type, fn) { listeners[type] = fn; },
};
const dispatched = [];
global.window = {
    ppxai: { commandDispatcher: { dispatch(line) { dispatched.push(line); } } },
};

const messages = [];
const app = { addMessage(role, html) { messages.push([role, html]); } };
const handler = new SideEffectsHandler(app);

// --- the payload ppxai/commands/agent.py::_checkpoint_clear emits ---------
const PAYLOAD = {
    kind: 'prompt_quick_pick',
    title: 'Delete all 3 file checkpoint(s)? This cannot be undone.',
    items: [
        {label: 'Cancel — keep all checkpoints', value: 'clear --no'},
        {label: 'Clear all 3 file checkpoints (cannot be undone)',
         value: 'clear --yes'},
    ],
    command_to_resume: 'checkpoint',
};

handler.apply([PAYLOAD]);

// --- 1: it rendered, and Cancel is first ---------------------------------
assert(messages.length === 1, 'the picker rendered no message');
const html = messages[0][1];
assert(/Delete all 3 file checkpoint/.test(html), 'the title is missing');

const buttons = [...html.matchAll(
    /data-cmd="([^"]*)" data-value="([^"]*)">([^<]*)</g)];
assert(buttons.length === 2,
  'expected two buttons, got ' + buttons.length + ' in ' + html);
// matchAll: [0] is the whole match, then cmd, value, label.
const CMD = 1, VALUE = 2, LABEL = 3;
assert(buttons[0][LABEL].indexOf('Cancel') === 0,
  'Cancel is not the FIRST button: ' +
  JSON.stringify(buttons.map((b) => b[LABEL])));
assert(buttons[1][LABEL].indexOf('Clear all') === 0,
  'the engine order was not preserved: ' +
  JSON.stringify(buttons.map((b) => b[LABEL])));
assert(buttons[0][VALUE] === 'clear --no' && buttons[1][VALUE] === 'clear --yes',
  'a value was mangled: ' + JSON.stringify(buttons.map((b) => b[VALUE])));
assert(buttons.every((b) => b[CMD] === 'checkpoint'),
  'command_to_resume did not reach the buttons');

// --- 2: clicking Cancel dispatches `/checkpoint clear --no` --------------
assert(typeof listeners.click === 'function',
  'the click delegation was never wired');

function clickButton(index) {
    const b = buttons[index];
    const el = { dataset: { cmd: b[CMD], value: b[VALUE] } };
    listeners.click({ target: { closest: (sel) =>
        (sel === '.qp-item' ? el : null) } });
}

clickButton(0);
assert(dispatched.length === 1,
  'clicking Cancel dispatched ' + dispatched.length + ' commands');
assert(dispatched[0] === '/checkpoint clear --no',
  'Cancel dispatched the wrong line: ' + JSON.stringify(dispatched[0]));

// --- 3: and the destructive row dispatches the OTHER line ----------------
clickButton(1);
assert(dispatched[1] === '/checkpoint clear --yes',
  'the confirm row dispatched: ' + JSON.stringify(dispatched[1]));

// --- 4: a click on anything else does nothing ----------------------------
listeners.click({ target: { closest: () => null } });
assert(dispatched.length === 2,
  'an unrelated click dispatched a command: ' + JSON.stringify(dispatched));

// --- 5: an empty item list renders nothing (no dead picker) --------------
messages.length = 0;
handler.apply([{kind: 'prompt_quick_pick', items: [],
                command_to_resume: 'checkpoint'}]);
assert(messages.length === 0, 'an empty picker rendered a message');

console.log('ALL OK');
"""


def _run(side_effects: Path = SIDE_EFFECTS) -> subprocess.CompletedProcess:
    env = dict(os.environ, PPXAI_SIDE_EFFECTS=str(side_effects))
    return subprocess.run([NODE, "-e", _HARNESS], capture_output=True,
                          text=True, timeout=60, env=env)


def test_web_renders_cancel_first_and_dispatches_the_picked_value():
    proc = _run()
    assert proc.returncode == 0, (
        f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
    assert "ALL OK" in proc.stdout, proc.stdout


class TestMutationWebQuickPick:
    """The harness must be able to FAIL — otherwise "web needed no new
    code" stays an assertion rather than a test."""

    def _mutant(self, tmp_path: Path, old: str, new: str) -> Path:
        src = SIDE_EFFECTS.read_text(encoding="utf-8")
        assert old in src, (
            "mutation anchor not found in side-effects.js — this mutation "
            "test is stale and is no longer proving anything")
        path = tmp_path / "side-effects.js"
        path.write_text(src.replace(old, new, 1), encoding="utf-8")
        return path

    def test_a_reordered_picker_is_caught(self, tmp_path):
        """A client that sorts the items by label would put "Cancel"
        after "Clear all 3…" — and a default-highlighted first row would
        then be the destructive one."""
        mutant = self._mutant(
            tmp_path,
            "        const buttons = items.map((it, i) => {",
            "        const buttons = items.slice().reverse().map((it, i) => {")
        proc = _run(mutant)
        assert proc.returncode != 0, (
            f"a reversed picker PASSED — the order is not fenced.\n{proc.stdout}")
        assert "FIRST button" in proc.stderr or "engine order" in proc.stderr, \
            proc.stderr

    def test_a_dropped_dispatch_is_caught(self, tmp_path):
        """The dead-end failure mode: the picker renders, the user
        clicks, and nothing happens."""
        mutant = self._mutant(
            tmp_path,
            "                if (window.ppxai?.commandDispatcher?.dispatch) {",
            "                if (false) {")
        proc = _run(mutant)
        assert proc.returncode != 0, (
            f"a picker that dispatches nothing PASSED.\n{proc.stdout}")
        assert "dispatched 0" in proc.stderr, proc.stderr

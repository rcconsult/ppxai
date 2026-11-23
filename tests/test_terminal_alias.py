"""`/terminal [alias] [-- command]` (ADR 0020).

Holds the payload contract tai routes on, the alias rule tai checks too,
and the type-don't-run rule in every client that has terminals:

- the parser and the alias rule (`parse_terminal_args`,
  `is_valid_terminal_name`), which tai mirrors;
- the side effects an HTTP client gets, and that the TUIs refuse an
  alias instead of emitting one;
- VS Code: a named terminal is reused, and both terminal paths type with
  `sendText(..., false)`;
- web: the REAL `side-effects.js` and `terminal-view.js` under Node — a
  named terminal is reused, and `run_shell` types the command without a
  newline, queued until the PTY socket opens.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ppxai.commands.context import ServerCommandContext
from ppxai.commands.results import ErrorResult, MarkdownResult, NotificationResult
from ppxai.commands.system import (
    handle_terminal,
    is_valid_terminal_name,
    parse_terminal_args,
)

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


# ── the alias rule ───────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "1", "2", "10", "build", "a", "web-1", "1a", "a1", "x" * 63, "my-build-2",
])
def test_a_valid_alias(name):
    assert is_valid_terminal_name(name)


@pytest.mark.parametrize("name", [
    "0",          # numbers start at 1 (tai's rule)
    "007",        # no leading zero
    "-build",     # must start with a letter or digit
    "build-",     # ...and end with one
    "Build",      # lowercase only
    "a_b",        # no underscore
    "a.b",        # a label, not a domain
    "x" * 64,     # at most 63
    "1-2",        # a name needs a letter
    "",
])
def test_an_invalid_alias(name):
    assert not is_valid_terminal_name(name)


# ── the parser ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("args, expected", [
    ("", (None, None)),
    ("   ", (None, None)),
    ("build", ("build", None)),
    ("2", ("2", None)),
    ("build -- make test", ("build", "make test")),
    ("-- make test", (None, "make test")),
    # Everything after the first `--` is verbatim: quotes, pipes, a second --.
    ("build -- grep -r 'a b' . | wc -l", ("build", "grep -r 'a b' . | wc -l")),
    ("-- git log -- path", (None, "git log -- path")),
])
def test_parse(args, expected):
    assert parse_terminal_args(args) == expected


@pytest.mark.parametrize("args, fragment", [
    ("Build", "not a terminal alias"),
    ("0 -- ls", "not a terminal alias"),
    ("build ls", "put '--' before the command"),
    ("build --", "no command after '--'"),
    ("--", "no command after '--'"),
    ("-- ", "no command after '--'"),
])
def test_parse_refuses(args, fragment):
    with pytest.raises(ValueError, match=re.escape(fragment)):
        parse_terminal_args(args)


# ── what each context gets ───────────────────────────────────────────────

def _engine(cwd="/work"):
    return SimpleNamespace(get_working_dir=lambda: cwd, session=None, state={})


def _http():
    return ServerCommandContext(_engine(), client="web")


def _tui():
    # Any non-server context is a TUI (Textual passes the app itself).
    return SimpleNamespace(engine_client=_engine())


def _effects(result):
    return [(se.kind, se.payload) for se in result.side_effects]


def test_http_plain_opens_a_terminal_with_a_notification():
    result = handle_terminal(_http(), "")
    assert isinstance(result, NotificationResult)
    assert _effects(result) == [("open_terminal", {"cwd": "/work"})]


def test_http_alias_names_the_terminal():
    result = handle_terminal(_http(), "build")
    assert isinstance(result, NotificationResult)
    assert "build" in result.message
    assert _effects(result) == [("open_terminal", {"cwd": "/work", "name": "build"})]


def test_http_alias_and_command_types_into_that_terminal():
    result = handle_terminal(_http(), "build -- make test")
    assert _effects(result) == [
        ("run_shell", {"command": "make test", "cwd": "/work", "name": "build"}),
    ]
    assert result.message == "Sent to terminal build"


def test_http_command_without_alias_carries_no_name():
    result = handle_terminal(_http(), "-- ls")
    assert _effects(result) == [("run_shell", {"command": "ls", "cwd": "/work"})]


def test_http_does_not_answer_with_the_tui_help():
    """Before ADR 0020 every HTTP client got the TUI image-protocol help."""
    assert not isinstance(handle_terminal(_http(), ""), MarkdownResult)


def test_a_bad_alias_is_an_error_with_no_effect():
    result = handle_terminal(_http(), "Bad_Name")
    assert isinstance(result, ErrorResult)
    assert result.side_effects == []


def test_tui_plain_keeps_the_help():
    result = handle_terminal(_tui(), "")
    assert isinstance(result, MarkdownResult)


@pytest.mark.parametrize("args", ["build", "build -- ls", "-- ls"])
def test_tui_refuses_an_alias_or_command(args):
    result = handle_terminal(_tui(), args)
    assert isinstance(result, ErrorResult)
    assert "no terminals" in result.message
    assert result.side_effects == []


# ── VS Code ──────────────────────────────────────────────────────────────

def _ts(name):
    return (ROOT / "vscode-extension" / "src" / name).read_text(encoding="utf-8")


def test_vscode_reuses_a_named_terminal():
    src = _ts("sideEffectsHandler.ts")
    helper = re.search(r"function _terminalFor\([\s\S]*?\n}\n", src)
    assert helper, "_terminalFor is missing"
    body = helper.group(0)
    assert "vscode.window.terminals" in body
    assert "exitStatus === undefined" in body
    assert "createTerminal" in body


def test_vscode_code_block_run_types_without_enter():
    src = _ts("chatPanel.ts")
    body = re.search(r"private runCommandInTerminal\([\s\S]*?\n    }\n", src).group(0)
    assert "sendText(command, false)" in body
    assert not re.search(r"sendText\(command\)", body)


# ── web, under Node ──────────────────────────────────────────────────────

_HARNESS = r"""
function assert(c, m) { if (!c) throw new Error('FAIL: ' + m); }
const fs = require('fs'), vm = require('vm');

global.window = globalThis;
global.BaseView = class {};
const sockets = [];
global.WebSocket = class {
    static OPEN = 1;
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    send(m) { this.sent.push(JSON.parse(m)); }
    open() { this.readyState = 1; this.onopen && this.onopen(); }
    close() {}
};
vm.runInThisContext(fs.readFileSync(process.env.TERMINAL_VIEW, 'utf8'));
const { SideEffectsHandler } = require(process.env.SIDE_EFFECTS);

// A stack with the RightPanelFrame calls the handler uses; push() mounts
// a terminal by opening its socket, as the real frame does.
const stack = [];
const frame = {
    get activeView() { return stack[stack.length - 1]; },
    get _stack() { return stack; },
    push(v) { stack.push(v); v._connect(); },
    getViewByPath(p) { return stack.find(v => v.getPath() === p) || null; },
    activateByIndex(i) { const [v] = stack.splice(i, 1); stack.push(v); },
};
const errors = [];
const app = {
    rightPanelFrame: frame, serverUrl: 'http://127.0.0.1:1', sessionId: 's',
    showError(m) { errors.push(m); }, showSystemMessage() {},
};
const h = new SideEffectsHandler(app);

h.apply([{kind: 'run_shell', command: 'make test', cwd: '/w', name: 'build'}]);
assert(stack.length === 1, 'run_shell opened no terminal');
assert(stack[0].getTitle().includes('build'), 'the terminal is not titled by its alias');
assert(sockets[0].sent.length === 0, 'typed before the socket opened');
sockets[0].open();
const typed = sockets[0].sent.filter(m => m.type === 'input');
assert(typed.length === 1 && typed[0].data === 'make test',
       'not typed once, verbatim: ' + JSON.stringify(typed));
assert(!typed[0].data.endsWith('\r') && !typed[0].data.endsWith('\n'), 'Enter was sent');

h.apply([{kind: 'open_terminal', cwd: '/w'}]);
assert(stack.length === 2, 'an unnamed open_terminal did not open a new terminal');
h.apply([{kind: 'open_terminal', cwd: '/w', name: 'build'}]);
assert(stack.length === 2, 'the named terminal was not reused');
assert(frame.activeView.getTitle().includes('build'), 'the named terminal was not focused');

h.apply([{kind: 'run_shell', command: 'ls', cwd: '/w', name: 'build'}]);
const again = sockets[0].sent.filter(m => m.type === 'input').map(m => m.data);
assert(again.join('|') === 'make test|ls', 'the open socket did not get the text: ' + again);
assert(errors.length === 0, errors.join('; '));
console.log('OK');
"""


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_web_named_terminal_and_typed_command(tmp_path):
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS, encoding="utf-8")
    env = dict(
        os.environ,
        TERMINAL_VIEW=str(ROOT / "ppxai" / "web" / "components" / "views" / "terminal-view.js"),
        SIDE_EFFECTS=str(ROOT / "ppxai" / "web" / "shared" / "side-effects.js"),
    )
    proc = subprocess.run([NODE, str(harness)], capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stderr or proc.stdout

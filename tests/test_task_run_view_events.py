"""Regression: TaskRunView._eventText renders the EMITTED event fields.

The dense /task pane's live log is one of its main audit signals. The emitter
(`agent_scoped_tools` / `build_task_runner`) sends `target_host`/`target_path`
for network events and `target_path` for path_denied — the renderer must read
those exact names, or the log shows blank destinations (Codex review: it was
reading `d.url || d.host`, which don't exist).

`_eventText` is a static pure function, so we eval the view with stub globals
and exercise it directly (no DOM).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
VIEW = (
    Path(__file__).resolve().parents[1]
    / "ppxai" / "web" / "components" / "views" / "task-run-view.js"
)

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


_HARNESS = r"""
const fs = require('fs');
// Minimal globals so `class TaskRunView extends AgentRunView` loads under Node.
global.BaseView = class {{}};
global.AgentRunView = class extends global.BaseView {{ _statusLabel(s) {{ return s; }} }};
global.escapeHtml = (s) => s;
global.window = {{}};
eval(fs.readFileSync({view}, 'utf8'));   // defines window.TaskRunView
const TRV = global.window.TaskRunView;

function assert(c, m) {{ if (!c) throw new Error("FAIL: " + m); }}
const txt = (type, data) => TRV._eventText({{ type, data }});

// network events carry target_host/target_path (NOT url/host)
const allow = txt('network_policy_allowed', {{ target_host: 'api.github.com', target_path: '/repos' }});
assert(/api\.github\.com/.test(allow), "network_policy_allowed dropped target_host: " + allow);
assert(/\/repos/.test(allow), "network_policy_allowed dropped target_path: " + allow);

const deny = txt('network_policy_denied', {{ target_host: 'evil.example.com', target_path: '/x' }});
assert(/evil\.example\.com/.test(deny), "network_policy_denied dropped target_host: " + deny);

// path_denied carries target_path
const pd = txt('path_denied', {{ mode: 'read', target_path: '/etc/passwd' }});
assert(/\/etc\/passwd/.test(pd), "path_denied dropped target_path: " + pd);

// tool_call carries tool
const tc = txt('tool_call', {{ tool: 'read_file' }});
assert(/read_file/.test(tc), "tool_call dropped tool: " + tc);

// a network event with no fields must not throw (renders a bare label)
txt('network_policy_allowed', {{}});

console.log("ALL OK");
"""


def test_task_run_view_event_text_reads_emitted_fields():
    script = _HARNESS.format(view=json.dumps(str(VIEW)))
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    assert "ALL OK" in proc.stdout, proc.stdout


_DOM_HARNESS = r"""
const fs = require('fs');
global.BaseView = class {{}};
global.AgentRunView = class extends global.BaseView {{ _statusLabel(s) {{ return s; }} }};
global.escapeHtml = (s) => s;
global.window = {{}};
global.document = {{ createElement: () => ({{}}) }};   // each line = a fresh node
eval(fs.readFileSync({view}, 'utf8'));
const TRV = global.window.TaskRunView;
function assert(c, m) {{ if (!c) throw new Error("FAIL: " + m); }}

// a fake events container tracking its child nodes
const el = {{
  nodes: [], scrollTop: 0, scrollHeight: 0,
  appendChild(n) {{ this.nodes.push(n); }},
  removeChild(n) {{ const i = this.nodes.indexOf(n); if (i >= 0) this.nodes.splice(i, 1); }},
  get firstChild() {{ return this.nodes[0] || null; }},
}};

const view = new TRV('r', 't', {{}});
view._eventsEl = el;
const CAP = TRV._MAX_LOG_EVENTS;
for (let i = 0; i < CAP + 50; i++) view.appendEvent({{ type: 'tool_call', data: {{ tool: 'read_file' }} }});

assert(view._events.length === CAP, "backing array not capped: " + view._events.length);
assert(el.nodes.length === CAP, "DOM node count not bounded (leak): " + el.nodes.length);
console.log("ALL OK");
"""


def test_task_run_view_live_log_bounds_dom_not_just_array():
    """appendEvent must prune the DOM in lock-step with the capped array — a long
    live run otherwise grows _eventsEl's node count without bound (Gemini review)."""
    script = _DOM_HARNESS.format(view=json.dumps(str(VIEW)))
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    assert "ALL OK" in proc.stdout, proc.stdout


# Same trusted-source loading pattern as the two harnesses above (the view is
# a window-global browser file with no module exports; the harness evaluates
# THIS REPO's file, never external input).
_PARK_HARNESS = r"""
const fs = require('fs');
global.BaseView = class {{}};
global.AgentRunView = class extends global.BaseView {{ _statusLabel(s) {{ return s; }} }};
global.escapeHtml = (s) => s;
global.window = {{}};
global.document = {{ createElement: () => ({{}}) }};
require('vm').runInThisContext(fs.readFileSync({view}, 'utf8'));
const TRV = global.window.TaskRunView;
function assert(c, m) {{ if (!c) throw new Error("FAIL: " + m); }}

// A run killed WHILE PARKED replays: waiting (dead token) -> interrupted ->
// resume/start -> fresh live waiting (valid token). The card must NOT be
// left holding the dead pre-restart token after the interrupted event —
// clicking it 409s ("run is not awaiting a response"; live 2026-07-12).
const view = new TRV('r', 't', {{}});
view.appendEvent({{ type: 'agent_waiting', data: {{ token: 'dead-token', prompt: 'old park' }} }});
assert(view._waiting && view._waiting.token === 'dead-token', "replayed park did not raise the card");
view.appendEvent({{ type: 'agent_run_interrupted', data: {{ reason: 'server restarted' }} }});
assert(view._waiting === null, "interrupted did NOT drop the dead-token card (stale-consent 409 bug)");
view.appendEvent({{ type: 'agent_run_resume', data: {{}} }});
view.appendEvent({{ type: 'agent_waiting', data: {{ token: 'fresh-token', prompt: 'new park' }} }});
assert(view._waiting && view._waiting.token === 'fresh-token', "fresh live park did not raise the card");

// The other park-killing lifecycle events drop it too.
for (const t of ['agent_run_cancelled', 'agent_run_error']) {{
  view._waiting = {{ token: 'x' }};
  view.appendEvent({{ type: t, data: {{}} }});
  assert(view._waiting === null, t + " did not drop the card");
}}
// agent_resumed (the normal answer path) still drops it.
view._waiting = {{ token: 'y' }};
view.appendEvent({{ type: 'agent_resumed', data: {{ approved: true }} }});
assert(view._waiting === null, "agent_resumed no longer drops the card (regression)");
console.log("ALL OK");
"""


def test_task_run_view_park_invalidated_by_interrupt():
    """A park cannot outlive the run's in-memory future: the replayed
    agent_waiting of a run killed while parked must be dropped by the
    agent_run_interrupted right behind it, so the card never dangles a dead
    pre-restart token (T7 retrial 409, 2026-07-12)."""
    script = _PARK_HARNESS.format(view=json.dumps(str(VIEW)))
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    assert "ALL OK" in proc.stdout, proc.stdout

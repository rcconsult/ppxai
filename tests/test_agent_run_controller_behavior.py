"""Behavioral tests for AgentRunController's detached watcher (v1.19.0).

The other web-client tests are static source reads. These exercise the actual
runtime via Node, because the review findings were *behavior* gaps the
structural tests can't see:

  1. A transient SSE stream failure must NOT permanently detach the UI — the
     watcher polls status until the run is terminal.
  2. When a run's pane is gone (closed/evicted, not on the stack), the final
     result must be mirrored into chat; when the pane is still on the stack it
     must NOT (no duplicate).
  3. The live-events SSE stays open until the client disconnects, so the tail
     must break on ANY terminal run-event — including `agent_run_cancelled` /
     `agent_run_interrupted` — or a cancelled/interrupted run parks the tail
     on an open stream forever. (Scenario 4 below hangs if the fix regresses.)
  4. The watcher must render into the run's CURRENT pane, resolved by run_id —
     NOT the AgentRunView instance captured at launch. A closed-then-reopened
     run creates a fresh instance; the terminal result must land in that visible
     pane, not the stale original, and must not spuriously mirror to chat.
     (Scenario 5.)

Skips cleanly where Node isn't available (same env contract as the VSCode build).
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


_HARNESS = r"""
const {{ AgentRunController }} = require({controller});

function makeView() {{
  return {{
    status: null, result: null, error: null, pinned: true, mounted: true,
    setStatus(s) {{ this.status = s; return true; }},
    setResult(r) {{ this.result = r; return this.mounted; }},
    setError(e) {{ this.error = e; return this.mounted; }},
    pin() {{ this.pinned = true; }},
    unpin() {{ this.pinned = false; }},
  }};
}}

function makeApp(gets, getViewByPath) {{
  const app = {{
    _msgs: [], _added: [], _getCalls: 0,
    state: {{}},
    showSystemMessage(m) {{ app._msgs.push(m); }},
    addMessage(role, c) {{ app._added.push([role, c]); }},
    apiClient: {{
      get: async (_url) => {{ app._getCalls++; return gets.length > 1 ? gets.shift() : gets[0]; }},
    }},
    rightPanelFrame: {{ getViewByPath }},
  }};
  return app;
}}

function assert(cond, msg) {{ if (!cond) throw new Error("FAIL: " + msg); }}

(async () => {{
  // focus()/._openPane guard on `typeof AgentRunView` — define a stub global so
  // the focus() scenarios below run under Node (the real view is browser-only).
  global.AgentRunView = function () {{}};

  // --- Scenario 1: stream fails, run still running, then completes (poll) ---
  {{
    const view = makeView();
    const app = makeApp(
      [ {{status: "running"}}, {{status: "running"}}, {{status: "completed", result: "DONE"}} ],
      () => view,            // on stack
    );
    const c = new AgentRunController(app);
    c._pollIntervalMs = 1;
    c._tailEvents = async function* () {{ throw new Error("stream down"); }};
    await c._watchDetached("run_1");
    assert(view.result === "DONE", "poll did not reach terminal/render result (got " + view.result + ")");
    assert(app._getCalls >= 3, "expected polling (>=3 GETs), got " + app._getCalls);
  }}

  // --- Scenario 2: pane NOT on stack -> result mirrored into chat ---
  {{
    const view = makeView();
    const app = makeApp(
      [ {{status: "completed", result: "R2"}} ],
      () => null,            // pane gone
    );
    const c = new AgentRunController(app);
    c._pollIntervalMs = 1;
    c._tailEvents = async function* () {{ yield {{type: "agent_run_complete"}}; }};
    await c._watchDetached("run_2");
    const mirrored = app._added.some(([role, c2]) => role === "assistant" && c2 === "R2");
    assert(mirrored, "result was NOT mirrored to chat when pane was off-stack");
  }}

  // --- Scenario 3: pane ON stack -> NO chat duplicate ---
  {{
    const view = makeView();
    const app = makeApp(
      [ {{status: "completed", result: "R3"}} ],
      () => view,            // still on stack
    );
    const c = new AgentRunController(app);
    c._pollIntervalMs = 1;
    c._tailEvents = async function* () {{ yield {{type: "agent_run_complete"}}; }};
    await c._watchDetached("run_3");
    const dup = app._added.some(([role, c2]) => role === "assistant" && c2 === "R3");
    assert(!dup, "result was duplicated into chat even though pane is on-stack");
    assert(view.result === "R3", "on-stack pane did not render result");
  }}

  // --- Scenario 4: cancelled run on an OPEN stream -> must break + resolve ---
  // The stub keeps the stream open (heartbeats forever) after the terminal
  // event; if _watchDetached doesn't break on `agent_run_cancelled`, this hangs
  // until the subprocess timeout (test fails).
  {{
    const view = makeView();
    const app = makeApp(
      [ {{status: "cancelled", error: "cancelled by owner"}} ],
      () => view,
    );
    const c = new AgentRunController(app);
    c._pollIntervalMs = 1;
    c._tailEvents = async function* () {{
      yield {{type: "agent_run_cancelled"}};
      while (true) {{ await new Promise((r) => setTimeout(r, 1)); yield {{type: "agent_beat"}}; }}
    }};
    await c._watchDetached("run_4");
    assert(view.status === "cancelled", "cancelled status not rendered (got " + view.status + ")");
    assert(view.error && view.error.length > 0, "cancelled run rendered no error/status body");
  }}

  // --- Scenario 5: run reopened as a NEW instance mid-flight ---
  // The pane visible at terminal (viewB) differs from the one captured at launch
  // (viewA). The result must render into viewB (resolved by run_id), the stale
  // viewA must be untouched, and there must be NO chat mirror (a pane exists).
  {{
    const viewA = makeView();
    const viewB = makeView();
    let current = viewA;
    const gets = [ {{status: "running"}}, {{status: "completed", result: "R5"}} ];
    const app = {{
      _msgs: [], _added: [], _getCalls: 0, state: {{}},
      showSystemMessage(m) {{ app._msgs.push(m); }},
      addMessage(role, c) {{ app._added.push([role, c]); }},
      apiClient: {{ get: async () => {{
        app._getCalls++;
        if (app._getCalls === 1) current = viewB;   // user reopens after first poll
        return gets.length > 1 ? gets.shift() : gets[0];
      }} }},
      rightPanelFrame: {{ getViewByPath: () => current }},
    }};
    const c = new AgentRunController(app);
    c._pollIntervalMs = 1;
    c._tailEvents = async function* () {{ throw new Error("stream down"); }};  // force poll path
    await c._watchDetached("run_5");
    assert(viewB.result === "R5", "reopened pane did NOT receive result (got " + viewB.result + ")");
    assert(viewA.result === null, "stale original instance was written (should be untouched)");
    const dup = app._added.some(([role, c2]) => role === "assistant" && c2 === "R5");
    assert(!dup, "spurious chat mirror even though a live (reopened) pane exists");
  }}

  // --- Scenario 6: focus() re-hydrates an EXISTING (stale) pane ---
  // The degraded path can leave a pane stale; reopening must refresh it from the
  // server, not early-return on the existing instance.
  {{
    const stale = makeView();   // pane exists but never got a result
    const app = {{
      _added: [], _msgs: [], state: {{}},
      showSystemMessage(m) {{ app._msgs.push(m); }},
      addMessage(r, c) {{ app._added.push([r, c]); }},
      apiClient: {{ get: async () => ({{status: "completed", result: "R6"}}) }},
      rightPanelFrame: {{ getViewByPath: () => stale, push: () => {{}} }},
    }};
    const c = new AgentRunController(app);
    c._watchDetached = async () => {{}};   // not under test here
    await c.focus("run_6", "t");
    assert(stale.result === "R6", "focus() did not re-hydrate the existing stale pane (got " + stale.result + ")");
    // Reopening a finished run must NOT re-announce it to chat (no dup breadcrumb).
    assert(!app._msgs.some((m) => /completed/.test(m)), "focus() re-announced a completed run to chat (duplicate breadcrumb)");
  }}

  // --- Scenario 7: focus() restarts the watcher for a running run; dedup holds ---
  {{
    const view = makeView();
    view.pinned = false;   // prove focus() pins it
    const app = {{
      _added: [], _msgs: [], state: {{}},
      showSystemMessage(m) {{}}, addMessage() {{}},
      apiClient: {{ get: async () => ({{status: "running"}}) }},
      rightPanelFrame: {{ getViewByPath: () => view, push: () => {{}} }},
    }};
    const c = new AgentRunController(app);
    const watched = [];
    c._watchDetached = async (rid) => {{ watched.push(rid); }};
    await c.focus("run_7", "t");
    assert(watched.length === 1 && watched[0] === "run_7", "focus() did not restart the watcher for a running run");
    assert(view.pinned === true, "running pane was not pinned on refresh");
    // dedup: a watcher already active for this run -> focus() must NOT start another
    watched.length = 0;
    c._watching.add("run_7b");
    await c.focus("run_7b", "t");
    assert(watched.length === 0, "focus() restarted a watcher despite one already active (dedup broken)");
  }}

  // --- Scenario 8: refresh GET fails (transient) -> still resume the watcher ---
  // The exact recovery case: a run that outlived the poll ceiling, reopened while
  // the metadata GET transiently fails. Must NOT strand in a hard error; must
  // resume the watcher (whose poll-with-retry resolves it) and keep the pane.
  {{
    const view = makeView();
    view.pinned = false;
    const app = {{
      _added: [], _msgs: [], state: {{}},
      showSystemMessage(m) {{}}, addMessage() {{}},
      apiClient: {{ get: async () => {{ throw new Error("net down"); }} }},
      rightPanelFrame: {{ getViewByPath: () => view, push: () => {{}} }},
    }};
    const c = new AgentRunController(app);
    const watched = [];
    c._watchDetached = async (rid) => {{ watched.push(rid); }};
    await c.focus("run_8", "t");
    assert(watched.length === 1 && watched[0] === "run_8", "focus() did not resume the watcher after a failed refresh GET");
    assert(view.pinned === true, "pane not pinned after failed refresh");
    assert(view.error === null, "focus() wrote a hard error instead of resuming the watcher (got " + view.error + ")");
    assert(view.status === "reconnecting", "pane did not show a soft reconnecting status (got " + view.status + ")");
  }}

  // --- Scenario 9: pane closed during the refresh GET, run terminal -> chat ---
  {{
    const app = {{
      _added: [], _msgs: [], state: {{}},
      showSystemMessage(m) {{ app._msgs.push(m); }},
      addMessage(r, c) {{ app._added.push([r, c]); }},
      apiClient: {{ get: async () => ({{status: "completed", result: "R9"}}) }},
      rightPanelFrame: {{ getViewByPath: () => null, push: () => {{}} }},  // no live pane
    }};
    const c = new AgentRunController(app);
    c._watchDetached = async () => {{}};
    await c.focus("run_9", "t");
    const mirrored = app._added.some(([r, c2]) => r === "assistant" && c2 === "R9");
    assert(mirrored, "terminal result not mirrored to chat when pane was gone during refresh");
  }}

  // --- Scenario 10: long run polled MANY times then completes (no ceiling) ---
  // Successful "still running" reads must never trigger give-up — the watcher
  // follows the run to completion however long it takes (resolves finding #1:
  // no arbitrary wall-clock death that strands the pane).
  {{
    const view = makeView();
    const app = makeApp(
      [ {{status: "running"}}, {{status: "running"}}, {{status: "running"}},
        {{status: "running"}}, {{status: "running"}}, {{status: "completed", result: "R10"}} ],
      () => view,
    );
    const c = new AgentRunController(app);
    c._pollIntervalMs = 1; c._pollMaxIntervalMs = 1;
    c._tailEvents = async function* () {{ throw new Error("stream down"); }};
    await c._watchDetached("run_10");
    assert(view.result === "R10", "long-running poll did not resolve to completion (got " + view.result + ")");
    assert(app._getCalls >= 6, "poll gave up early instead of following the run (getCalls=" + app._getCalls + ")");
  }}

  // --- Scenario 11: sustained GET failure -> graceful give-up (no hang) ---
  {{
    const view = makeView();
    const app = {{
      _added: [], _msgs: [], _getCalls: 0, state: {{}},
      showSystemMessage(m) {{ app._msgs.push(m); }},
      addMessage() {{}},
      apiClient: {{ get: async () => {{ app._getCalls++; throw new Error("offline"); }} }},
      rightPanelFrame: {{ getViewByPath: () => view, push: () => {{}} }},
    }};
    const c = new AgentRunController(app);
    c._pollIntervalMs = 1; c._pollMaxIntervalMs = 1; c._pollMaxFailures = 3;
    c._tailEvents = async function* () {{ throw new Error("stream down"); }};
    await c._watchDetached("run_11");   // must resolve (not hang)
    assert(app._getCalls >= 3, "did not retry before giving up (getCalls=" + app._getCalls + ")");
    assert(view.pinned === false, "pane left pinned after give-up");
    assert(app._msgs.some((m) => /lost contact/.test(m)), "no 'lost contact' message after sustained failure");
    // The pane itself must move to a terminal state, not stay stuck on the
    // "reconnecting" status set in focus() (Gemini review — silent-pane fix).
    assert(view.status === "unreachable", "pane not moved to terminal 'unreachable' on give-up (got " + view.status + ")");
    assert(view.error && /unreachable|Monitoring stopped/.test(view.error), "pane shows no error body on give-up (got " + view.error + ")");
  }}

  // --- Scenario 12: stale REPLAYED terminal event must not detach the tail (T7) ---
  // The SSE replays the persisted backlog first, so a RESUMED run's tail sees
  // the historical agent_run_interrupted from before the resume. Old behavior
  // broke there — live events (incl. the consent card's agent_waiting) never
  // reached the pane and the run could only time out (live-trial bug,
  // 2026-07-12). The tail must confirm against the run record (source of
  // truth) and keep tailing; it breaks only on the REAL terminal.
  {{
    const view = makeView();
    view.events = [];
    view.appendEvent = function (ev) {{ this.events.push(ev.type); }};
    const app = makeApp(
      [ {{status: "running"}}, {{status: "completed_pending_ack", result: "R12"}} ],
      () => view,
    );
    const c = new AgentRunController(app);
    c._pollIntervalMs = 1;
    c._tailEvents = async function* () {{
      yield {{type: "agent_run_interrupted"}};   // stale replay from before the resume
      yield {{type: "agent_run_resume"}};
      yield {{type: "tool_call", data: {{tool: "spawn_subagent"}}}};
      yield {{type: "agent_waiting", data: {{kind: "consent"}}}};
      yield {{type: "agent_result_ready"}};      // REAL terminal
    }};
    await c._watchDetached("run_12");
    assert(view.events.includes("agent_waiting"),
      "stale replayed terminal detached the tail — consent park never reached the pane (events=" + view.events.join(",") + ")");
    assert(view.result === "R12", "resumed run's result not rendered (got " + view.result + ")");
    assert(app._getCalls >= 2, "expected confirm-GETs on terminal events (getCalls=" + app._getCalls + ")");
  }}

  console.log("ALL OK");
}})().catch((e) => {{ console.error(e.message || e); process.exit(1); }});
"""


def _run() -> subprocess.CompletedProcess:
    script = _HARNESS.format(controller=json.dumps(str(CONTROLLER)))
    return subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, timeout=30
    )


def test_watcher_resolves_live_pane_polls_mirrors_and_breaks_on_all_terminal_events():
    """All five runtime scenarios pass: poll-on-stream-fail, off-stack chat
    mirror, on-stack no-duplicate, break on cancelled/interrupted, and render
    into a reopened pane (resolved by run_id, not the captured instance)."""
    proc = _run()
    assert proc.returncode == 0, (
        f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    assert "ALL OK" in proc.stdout, proc.stdout

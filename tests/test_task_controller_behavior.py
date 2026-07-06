"""Behavioral tests for TaskController + parseTaskArgs (v1.19.x build plan T1).

Exercises the actual runtime via Node (like test_agent_run_controller_behavior.py):
the flag parser, the /task run launch body (grant/egress/budget + provider/model
fallback), server-rejection surfacing, cancel, and sub-command routing.

TaskController extends AgentRunController; the harness requires task-controller.js,
which in turn requires agent-run-controller.js from the same directory.

Skips cleanly where Node isn't available.
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
    / "ppxai" / "web" / "shared" / "task-controller.js"
)

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


_HARNESS = r"""
const {{ TaskController, parseTaskArgs }} = require({controller});

function assert(cond, msg) {{ if (!cond) throw new Error("FAIL: " + msg); }}
function eq(a, b) {{ return JSON.stringify(a) === JSON.stringify(b); }}

function makeApp(opts) {{
  opts = opts || {{}};
  const app = {{
    _msgs: [], _posts: [], _added: [], _gets: 0,
    state: opts.state || {{}},
    showSystemMessage(m) {{ app._msgs.push(m); }},
    addMessage(role, c) {{ app._added.push([role, c]); return null; }},
    apiClient: {{
      post: async (url, body) => {{
        app._posts.push([url, body]);
        if (opts.postThrows) throw new Error(opts.postThrows);
        return opts.postReturn || {{run_id: "run_x", status: "running"}};
      }},
      get: async (_url) => {{ app._gets++; return opts.getReturn || {{runs: []}}; }},
    }},
    rightPanelFrame: {{ getViewByPath: () => null, push: () => {{}} }},
  }};
  return app;
}}

(async () => {{
  // --- Scenario 1: parseTaskArgs — full flag line, quoted desc ---
  {{
    const p = parseTaskArgs('"read the file" --tools read_file,grep '
      + '--allow api.github.com/repos --budget iters=20,tokens=100k '
      + '--provider openai --model gpt-5.4-mini --system "be terse"');
    assert(p.task === "read the file", "quoted desc: " + p.task);
    assert(eq(p.tools, ["read_file", "grep"]), "tools: " + JSON.stringify(p.tools));
    assert(p.network.allow_outbound.length === 1, "one egress rule");
    assert(p.network.allow_outbound[0].host === "api.github.com", "egress host");
    assert(eq(p.network.allow_outbound[0].paths, ["/repos"]), "egress path");
    assert(p.budget.iterations === 20, "budget iters: " + p.budget.iterations);
    assert(p.budget.tokens === 100000, "budget tokens (k suffix): " + p.budget.tokens);
    assert(p.provider === "openai" && p.model === "gpt-5.4-mini", "provider/model");
    assert(p.system === "be terse", "system: " + p.system);
    assert(p.errors.length === 0, "no errors: " + p.errors);
  }}

  // --- Scenario 2: parseTaskArgs — bare desc, bare-host egress ---
  {{
    const p = parseTaskArgs('triage the ci job --tools read_file --allow api.github.com');
    assert(p.task === "triage the ci job", "bare desc: " + p.task);
    assert(p.network.allow_outbound[0] === "api.github.com", "bare host stays a string");
  }}

  // --- Scenario 3: parseTaskArgs — error paths ---
  {{
    const a = parseTaskArgs('x --tools a --frobnicate');
    assert(a.errors.some((e) => /unknown flag/.test(e)), "unknown flag not flagged");
    const b = parseTaskArgs('x --tools');
    assert(b.errors.some((e) => /needs a value/.test(e)), "missing value not flagged");
    const c = parseTaskArgs('x --tools a --budget iters=notanumber');
    assert(c.errors.some((e) => /bad --budget/.test(e)), "bad budget value not flagged");
  }}

  // --- Scenario 3b: parseTaskArgs — --spec (T3) ---
  {{
    const p = parseTaskArgs('"the ci job is red" --spec triage --model reqmodel');
    assert(p.task === "the ci job is red", "spec desc: " + p.task);
    assert(p.spec === "triage", "spec name: " + p.spec);
    assert(p.model === "reqmodel", "flag overrides spec model client-side");
    assert(eq(p.tools, []), "no --tools is OK when --spec present: " + JSON.stringify(p.tools));
    assert(p.errors.length === 0, "no errors with --spec: " + p.errors);
    const q = parseTaskArgs('x --spec');
    assert(q.errors.some((e) => /needs a value/.test(e)), "--spec missing value not flagged");
  }}

  // --- Scenario 3c: parseTaskArgs — --skill (T4), repeatable + comma-split ---
  {{
    const p = parseTaskArgs('"triage" --skill ci-triage --skill secrets-scan');
    assert(eq(p.skills, ["ci-triage", "secrets-scan"]), "repeated --skill: " + JSON.stringify(p.skills));
    assert(eq(p.tools, []), "no --tools OK when --skill present");
    assert(p.errors.length === 0, "no errors with --skill: " + p.errors);
    const c = parseTaskArgs('x --skill a,b,a');
    assert(eq(c.skills, ["a", "b"]), "comma-split + de-dup: " + JSON.stringify(c.skills));
    const q = parseTaskArgs('x --skill');
    assert(q.errors.some((e) => /needs a value/.test(e)), "--skill missing value not flagged");
  }}

  // --- Scenario 3d: run() sends skills in the body, doesn't force UI provider ---
  {{
    const app = makeApp({{ state: {{ currentProvider: "nvidia", currentModel: "qwen" }} }});
    const c = new TaskController(app);
    c._watchDetached = async () => {{}};
    await c.run('"triage" --skill ci-triage');
    const [url, body] = app._posts[0];
    assert(url === "/v1/agent/task", "wrong url: " + url);
    assert(eq(body.skills, ["ci-triage"]), "skills in body: " + JSON.stringify(body.skills));
    assert(body.provider === undefined, "skill launch must not force UI provider");
    assert(body.model === undefined, "skill launch must not force UI model");
  }}

  // --- Scenario 4: run() builds the POST body + provider/model fallback + watches ---
  {{
    const app = makeApp({{ state: {{ currentProvider: "nvidia", currentModel: "qwen" }} }});
    const c = new TaskController(app);
    let watched = null;
    c._watchDetached = async (rid) => {{ watched = rid; }};
    await c.run('"do it" --tools read_file,grep --allow h.com --budget time=300');
    assert(app._posts.length === 1, "expected exactly one POST, got " + app._posts.length);
    const [url, body] = app._posts[0];
    assert(url === "/v1/agent/task", "wrong url: " + url);
    assert(body.task === "do it", "task: " + body.task);
    assert(eq(body.tools, ["read_file", "grep"]), "tools: " + JSON.stringify(body.tools));
    assert(body.provider === "nvidia" && body.model === "qwen", "provider/model fallback from UI state");
    assert(body.network.allow_outbound[0] === "h.com", "egress");
    assert(body.budget.time_s === 300, "budget: " + JSON.stringify(body.budget));
    assert(watched === "run_x", "watcher not started for the new run (got " + watched + ")");
  }}

  // --- Scenario 5: run() refuses a tool-free grant (no POST) ---
  {{
    const app = makeApp({{}});
    const c = new TaskController(app);
    c._watchDetached = async () => {{ throw new Error("should not watch"); }};
    await c.run('"just text"');
    assert(app._posts.length === 0, "must NOT POST without a tool grant");
    assert(app._msgs.some((m) => /needs a tool grant/.test(m)), "no grant hint shown");
  }}

  // --- Scenario 6: run() surfaces a server rejection verbatim; no watch ---
  {{
    const app = makeApp({{ postThrows: "403: tier disabled — enable task_tier_enabled" }});
    const c = new TaskController(app);
    let watched = false;
    c._watchDetached = async () => {{ watched = true; }};
    await c.run('"x" --tools read_file');
    assert(app._msgs.some((m) => /tier disabled/.test(m)), "server rejection not surfaced");
    assert(!watched, "must NOT watch a rejected run");
  }}

  // --- Scenario 7: cancel() POSTs the cancel endpoint ---
  {{
    const app = makeApp({{}});
    const c = new TaskController(app);
    await c.cancel("run_9");
    assert(app._posts.some(([u]) => u === "/v1/agent/runs/run_9/cancel"), "cancel did not POST the right url");
  }}

  // --- Scenario 8: handle() routes verbs to the right method ---
  {{
    const app = makeApp({{}});
    const c = new TaskController(app);
    const calls = [];
    c.run = async (a) => calls.push(["run", a]);
    c.list = async () => calls.push(["list"]);
    c.show = (id) => calls.push(["show", id]);
    c.cancel = async (id) => calls.push(["cancel", id]);
    c.help = () => calls.push(["help"]);
    await c.handle('run "x" --tools a');
    await c.handle('ls');
    await c.handle('show run_1');
    await c.handle('watch run_2');
    await c.handle('cancel run_3');
    await c.handle('');
    assert(calls[0][0] === "run" && calls[0][1] === '"x" --tools a', "run route");
    assert(calls[1][0] === "list", "ls route");
    assert(calls[2][0] === "show" && calls[2][1] === "run_1", "show route");
    assert(calls[3][0] === "show" && calls[3][1] === "run_2", "watch route -> show");
    assert(calls[4][0] === "cancel" && calls[4][1] === "run_3", "cancel route");
    assert(calls[5][0] === "help", "empty -> help");
  }}

  // --- Scenario 9 (T5): respondCmd — token fetch + answer mapping ---
  {{
    const app = makeApp({{ getReturn: {{ run_id: "run_9", status: "waiting",
      waiting: {{ kind: "consent", prompt: "spawn?", token: "tok123" }} }} }});
    const c = new TaskController(app);
    await c.respondCmd('run_9 approve');
    const responds = () => app._posts.filter(([u]) => u === "/v1/agent/runs/run_9/respond");
    assert(responds().length === 1, "respond did not POST the respond endpoint");
    assert(responds()[0][1].token === "tok123",
      "token from meta.waiting: " + JSON.stringify(responds()[0][1]));
    assert(responds()[0][1].approved === true, "approve maps to approved:true");

    await c.respondCmd('run_9 deny');
    assert(responds()[1][1].approved === false, "deny maps to approved:false");

    await c.respondCmd('run_9 "use the staging env"');
    const free = responds()[2][1];
    assert(free.text === "use the staging env" && free.approved === undefined,
      "free text maps to text: " + JSON.stringify(free));
  }}

  // --- Scenario 9b (T5): respondCmd — not-waiting guard, usage, verb routing ---
  {{
    const app = makeApp({{ getReturn: {{ run_id: "run_9", status: "running", waiting: null }} }});
    const c = new TaskController(app);
    await c.respondCmd('run_9 approve');
    assert(app._posts.length === 0, "must NOT POST when the run is not waiting");
    assert(app._msgs.some((m) => /not waiting/.test(m)), "not-waiting hint shown");
    await c.respondCmd('run_9');
    assert(app._msgs.some((m) => /Usage: \/task respond/.test(m)), "usage shown");
    const calls = [];
    c.respondCmd = async (rest) => calls.push(rest);
    await c.handle('respond run_1 approve');
    assert(calls[0] === "run_1 approve", "respond route: " + calls[0]);
  }}

  console.log("ALL OK");
}})().catch((e) => {{ console.error(e.message || e); process.exit(1); }});
"""


def _run() -> subprocess.CompletedProcess:
    script = _HARNESS.format(controller=json.dumps(str(CONTROLLER)))
    return subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, timeout=30
    )


def test_task_controller_parse_launch_cancel_and_routing():
    """Flag parser, launch body (grant/egress/budget + provider/model fallback),
    tool-free refusal, server-rejection surfacing, cancel, and verb routing."""
    proc = _run()
    assert proc.returncode == 0, (
        f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    assert "ALL OK" in proc.stdout, proc.stdout

"""Behavioral tests for TaskController + parseTaskArgs (v1.19.x; U2 grammar).

Exercises the actual runtime via Node (like test_agent_run_controller_behavior.py):
the flag parser, the direct-launch body (grant/egress/budget + provider/model
fallback), server-rejection surfacing, cancel, and the U2 (ADR 0011)
direct-launch grammar: verb + run-id (or empty) → lifecycle op, anything
else launches; `run` subcommand removed; get/collect canonical with
show/open/ack as aliases.

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

  // --- Scenario 5: tool-free launch POSTs — the SERVER owns the grant rule
  // (U3: the client guard is gone; the server's 400 surfaces via Scenario 6's
  // rejection path; tool-free one-offs belong on /run).
  {{
    const app = makeApp({{}});
    const c = new TaskController(app);
    c._watchDetached = async () => {{}};
    await c.run('"just text"');
    assert(app._posts.length === 1, "tool-free launch must reach the server");
    assert(app._posts[0][0] === "/v1/agent/task", "url: " + app._posts[0][0]);
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

  // --- Scenario 8: handle() — U2 direct-launch grammar (ADR 0011) ---
  // Lifecycle op iff first token is a verb AND the remainder is empty or
  // starts with a run id (run_ + 12 hex); anything else launches.
  {{
    const app = makeApp({{}});
    const c = new TaskController(app);
    const calls = [];
    c.run = async (a) => calls.push(["run", a]);
    c.list = async () => calls.push(["list"]);
    c.get = (id) => calls.push(["get", id]);
    c.cancel = async (id) => calls.push(["cancel", id]);
    c.help = () => calls.push(["help"]);
    const A = "run_aaaaaaaaaaaa", B = "run_bbbbbbbbbbbb";
    await c.handle('get ' + A);                       // verb + id → lifecycle
    await c.handle('ls');                             // verb + empty → lifecycle
    await c.handle('watch ' + B);                     // watch → get
    await c.handle('cancel ' + A);
    await c.handle('show ' + B);                      // alias of get
    await c.handle('');                               // empty → help
    await c.handle('"x" --tools a');                  // bare prompt → launch
    await c.handle('get the weather in Geneva --tools web_search'); // verb + prose → launch
    await c.handle('run "x" --tools a');              // `run` is no verb → launch (whole line)
    assert(calls[0][0] === "get" && calls[0][1] === A, "get route");
    assert(calls[1][0] === "list", "ls route");
    assert(calls[2][0] === "get" && calls[2][1] === B, "watch route -> get");
    assert(calls[3][0] === "cancel" && calls[3][1] === A, "cancel route");
    assert(calls[4][0] === "get" && calls[4][1] === B, "show alias -> get");
    assert(calls[5][0] === "help", "empty -> help");
    assert(calls[6][0] === "run" && calls[6][1] === '"x" --tools a', "bare prompt launches");
    assert(calls[7][0] === "run" && calls[7][1] === 'get the weather in Geneva --tools web_search',
      "verb + prose launches (the plan's edge case)");
    assert(calls[8][0] === "run" && calls[8][1] === 'run "x" --tools a',
      "removed `run` subcommand falls through to launch");
  }}

  // --- Scenario 8a: near-miss run id after a verb fails loud, never launches ---
  {{
    const app = makeApp({{}});
    const c = new TaskController(app);
    let launched = false;
    c.run = async () => {{ launched = true; }};
    await c.handle('get run_123');           // run_-ish but not 12 hex
    await c.handle('collect run_aaaaaaaaaaa'); // 11 hex — truncated paste
    assert(!launched, "a near-miss id must never launch a task");
    assert(app._msgs.filter((m) => /looks like a run id/.test(m)).length === 2,
      "near-miss hint shown for both");
  }}

  // --- Scenario 8b: id verbs trim a pasted blob to the first token ---
  // A multi-line paste of several `/task collect <id>` commands arrives as
  // one argline; the id-taking verbs must act on the FIRST id instead of
  // sending the whole blob as one bogus id (live-trial stumble 2026-07-11).
  {{
    const app = makeApp({{}});
    const c = new TaskController(app);
    const calls = [];
    c.get = (id) => calls.push(["get", id]);
    c.cancel = async (id) => calls.push(["cancel", id]);
    c.ack = async (id) => calls.push(["ack", id]);
    c.resume = async (id) => calls.push(["resume", id]);
    const I = (ch) => "run_" + ch.repeat(12);
    await c.handle('collect ' + I("1") + ' /task collect ' + I("2"));
    await c.handle('get ' + I("4") + ' trailing junk');
    await c.handle('cancel ' + I("5") + '\t/task cancel ' + I("6"));
    await c.handle('resume ' + I("7") + ' ' + I("8"));
    assert(calls[0][0] === "ack" && calls[0][1] === I("1"),
      "pasted collect blob trims to first id: " + JSON.stringify(calls[0]));
    assert(calls[1][1] === I("4"), "get trims trailing junk");
    assert(calls[2][1] === I("5"), "cancel trims at tab");
    assert(calls[3][1] === I("7"), "resume trims to first id");
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
    assert(app._msgs.some((m) => /Usage: `\/task respond/.test(m)), "usage shown");
    const calls = [];
    c.respondCmd = async (rest) => calls.push(rest);
    await c.handle('respond run_111111111111 approve');
    assert(calls[0] === "run_111111111111 approve", "respond route: " + calls[0]);
  }}

  // --- Scenario 10 (T6): collect (ack alias) — POST + verb routing ---
  {{
    const app = makeApp({{}});
    const c = new TaskController(app);
    await c.ack("run_7");
    assert(app._posts.some(([u]) => u === "/v1/agent/runs/run_7/ack"),
      "ack did not POST the ack endpoint");
    assert(app._msgs.some((m) => /collected/.test(m)), "collect confirmation shown");
    await c.ack("");
    assert(app._msgs.some((m) => /Usage: `\/task collect/.test(m)), "collect usage shown");
    const calls = [];
    c.ack = async (id) => calls.push(id);
    await c.handle('collect run_888888888888');   // canonical U2 verb
    await c.handle('ack run_999999999999');       // alias kept
    assert(calls[0] === "run_888888888888", "collect route: " + calls[0]);
    assert(calls[1] === "run_999999999999", "ack alias route: " + calls[1]);
  }}

  // --- Scenario 11 (T7): resume — POST, watcher restart, routing, refusal ---
  {{
    const app = makeApp({{}});
    const c = new TaskController(app);
    let watched = null;
    c._watchDetached = async (rid) => {{ watched = rid; }};
    await c.resume("run_5");
    assert(app._posts.some(([u]) => u === "/v1/agent/runs/run_5/resume"),
      "resume did not POST the resume endpoint");
    assert(app._msgs.some((m) => /resumed/.test(m)), "resume confirmation shown");
    assert(watched === "run_5", "resume must restart the detached watcher");
    const calls = [];
    c.resume = async (id) => calls.push(id);
    await c.handle('resume run_666666666666');
    assert(calls[0] === "run_666666666666", "resume route: " + calls[0]);
  }}
  {{
    const app = makeApp({{ postThrows: "409: cannot be resumed: work already captured" }});
    const c = new TaskController(app);
    c._watchDetached = async () => {{ throw new Error("must not watch a refused resume"); }};
    await c.resume("run_5");
    assert(app._msgs.some((m) => /work already captured/.test(m)),
      "server refusal reason not surfaced verbatim");
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

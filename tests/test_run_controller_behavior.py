"""Behavioral tests for RunController (U3, ADR 0011) via Node.

The /run one-off family: direct launch with NO flags (grant is
server-config-decided), POST /v1/agent/run, kind-filtered ls, and the
inherited U2 grammar (verb + run id or empty → lifecycle; anything else
launches). Mirrors test_task_controller_behavior.py's harness.

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
    / "ppxai" / "web" / "shared" / "run-controller.js"
)

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


_HARNESS = r"""
const {{ RunController }} = require({controller});

function assert(cond, msg) {{ if (!cond) throw new Error("FAIL: " + msg); }}

function makeApp(opts) {{
  opts = opts || {{}};
  const app = {{
    _msgs: [], _posts: [], _added: [], _getUrls: [],
    state: opts.state || {{}},
    showSystemMessage(m) {{ app._msgs.push(m); }},
    addMessage(role, c) {{ app._added.push([role, c]); return null; }},
    apiClient: {{
      post: async (url, body) => {{
        app._posts.push([url, body]);
        if (opts.postThrows) throw new Error(opts.postThrows);
        return opts.postReturn || {{run_id: "run_x", status: "running"}};
      }},
      get: async (url) => {{ app._getUrls.push(url); return opts.getReturn || {{runs: []}}; }},
    }},
    rightPanelFrame: {{ getViewByPath: () => null, push: () => {{}} }},
  }};
  return app;
}}

(async () => {{
  // --- Scenario 1: launch — whole line is the prompt, UI provider/model ride ---
  {{
    const app = makeApp({{ state: {{ currentProvider: "gemini", currentModel: "g-flash" }} }});
    const c = new RunController(app);
    let watched = null;
    c._watchDetached = async (rid) => {{ watched = rid; }};
    await c.handle('what happened today in rust');
    assert(app._posts.length === 1, "expected one POST, got " + app._posts.length);
    const [url, body] = app._posts[0];
    assert(url === "/v1/agent/run", "wrong url: " + url);
    assert(body.task === "what happened today in rust", "task: " + body.task);
    assert(body.tools === undefined, "client must NOT send a grant");
    assert(body.provider === "gemini" && body.model === "g-flash", "UI provider/model ride along");
    assert(watched === "run_x", "watcher not started");
  }}

  // --- Scenario 2: quoted prompt strips one outer quote layer ---
  {{
    const app = makeApp({{}});
    const c = new RunController(app);
    c._watchDetached = async () => {{}};
    await c.handle('"cancel run_abcdef123456 subscription cleanup notes"');
    assert(app._posts.length === 1, "quoted prompt must launch");
    assert(app._posts[0][1].task === "cancel run_abcdef123456 subscription cleanup notes",
      "quotes stripped: " + app._posts[0][1].task);
  }}

  // --- Scenario 3: no flags by design — reject, never fold into prompt ---
  {{
    const app = makeApp({{}});
    const c = new RunController(app);
    c._watchDetached = async () => {{ throw new Error("must not watch"); }};
    await c.handle('search the web --tools web_search');
    assert(app._posts.length === 0, "flagged launch must NOT POST");
    assert(app._msgs.some((m) => /takes no flags/.test(m)), "no-flags hint shown");
  }}

  // --- Scenario 4: inherited U2 grammar — verbs, prose edge, near-miss ---
  {{
    const app = makeApp({{}});
    const c = new RunController(app);
    const calls = [];
    c.run = async (a) => calls.push(["run", a]);
    c.list = async () => calls.push(["list"]);
    c.get = (id) => calls.push(["get", id]);
    c.ack = async (id) => calls.push(["ack", id]);
    const ID = "run_aaaaaaaaaaaa";
    await c.handle('ls');
    await c.handle('get ' + ID);
    await c.handle('collect ' + ID);
    await c.handle('get the weather in Geneva');   // verb + prose → launch
    assert(calls[0][0] === "list", "ls route");
    assert(calls[1][0] === "get" && calls[1][1] === ID, "get route");
    assert(calls[2][0] === "ack" && calls[2][1] === ID, "collect route -> ack");
    assert(calls[3][0] === "run" && calls[3][1] === "get the weather in Geneva",
      "verb + prose launches");
  }}
  {{
    const app = makeApp({{}});
    const c = new RunController(app);
    let launched = false;
    c.run = async () => {{ launched = true; }};
    await c.handle('get run_123');   // near-miss id (inherited guard)
    assert(!launched, "near-miss id must not launch");
    assert(app._msgs.some((m) => /looks like a run id/.test(m)), "near-miss hint");
  }}

  // --- Scenario 5: ls is kind-filtered to oneshot runs ---
  {{
    const app = makeApp({{}});
    const c = new RunController(app);
    await c.list();
    assert(app._getUrls[0] === "/v1/agent/runs?kind=oneshot",
      "kind filter missing: " + app._getUrls[0]);
    assert(app._msgs.some((m) => /No runs yet/.test(m)), "empty hint shown");
  }}

  // --- Scenario 6: server rejection surfaces verbatim; no watch ---
  {{
    const app = makeApp({{ postThrows: "400: no provider for the agent run" }});
    const c = new RunController(app);
    let watched = false;
    c._watchDetached = async () => {{ watched = true; }};
    await c.handle('just do it');
    assert(app._msgs.some((m) => /no provider/.test(m)), "rejection not surfaced");
    assert(!watched, "must NOT watch a rejected run");
  }}

  console.log("ALL OK");
}})().catch((e) => {{ console.error(e.message || e); process.exit(1); }});
"""


def _run() -> subprocess.CompletedProcess:
    script = _HARNESS.format(controller=json.dumps(str(CONTROLLER)))
    return subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, timeout=30
    )


def test_run_controller_launch_grammar_and_kind_filter():
    """Direct launch (no flags), inherited U2 grammar, kind-filtered ls,
    rejection surfacing."""
    proc = _run()
    assert proc.returncode == 0, (
        f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    assert "ALL OK" in proc.stdout, proc.stdout

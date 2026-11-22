"""`/task ls` and `/run ls` list the CURRENT conversation's runs (2026-11-22).

Owner decision: no flags = the runs whose recorded conversation
(`RunMeta.session_id`, ADR 0018) is the client's active one; `--all` lifts the
scope (runs with no recorded conversation appear ONLY then, marked `(none)`);
`--status <s>` filters; sub-agents nest under their parent (a child whose
parent is not in the listed set stays at top level — it is never lost).

Four clients, one rule, so this file drives all of them:

* the Python grammar + the in-process TUI path (Rich and Textual both call
  `ppxai/commands/task.py`),
* the web controller under plain Node (`task-controller.js`),
* the VSCode controller (`taskController.ts`), bundled with the extension's
  esbuild and driven under Node.

The grammar table is declared once here and fed to all three implementations,
so Python and both JS twins are held to identical routing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ppxai.commands import task as task_cmd
from ppxai.commands.results import ErrorResult, NotificationResult, TableResult
from ppxai.engine.agent_runs import (
    RUN_STATUSES,
    AgentRunRegistry,
    FilesystemAgentRunStore,
)
from ppxai.engine.run_scope import scope_and_nest
from ppxai.engine.task_backend import InProcessTaskBackend
from ppxai.engine.task_grammar import Action, classify, parse_ls_flags
from tests.conftest import ESBUILD, minimal_subprocess_env

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
WEB_SHARED = ROOT / "ppxai" / "web" / "shared"
TS_CONTROLLER = ROOT / "vscode-extension" / "src" / "taskController.ts"

needs_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")
needs_esbuild = pytest.mark.skipif(
    NODE is None or not ESBUILD.exists(),
    reason="node and vscode-extension/node_modules/.bin/esbuild are required",
)

# line -> expected outcome. ("list", all, status) | "error" | "launch" | "near_miss"
GRAMMAR = {
    "ls": ("list", False, None),
    "list": ("list", False, None),
    "ls --all": ("list", True, None),
    "ls --status running": ("list", False, "running"),
    "ls --all --status failed": ("list", True, "failed"),
    "ls --status failed --all": ("list", True, "failed"),
    "ls --status": "error",
    "ls --status bogus": "error",
    "ls --tools x": "launch",
    "ls foo": "launch",
    "ls --all foo": "launch",
    "ls --status running foo": "launch",
    "ls run_abc": "near_miss",
    "ls run_aaaaaaaaaaaa": ("list", False, None),  # unchanged: the id is ignored
}

A = "run_a00000000001"
CHILD = "run_a00000000002"
B = "run_b00000000001"
NULL = "run_n00000000001"
ONESHOT = "run_o00000000001"


def python_outcome(line: str):
    d = classify(line)
    if d.action is Action.LAUNCH:
        return "launch"
    if d.action is Action.NEAR_MISS:
        return "near_miss"
    if d.verb in ("ls", "list"):
        f = parse_ls_flags("" if d.run_id else d.rest)
        return "error" if f.errors else ("list", f.all, f.status)
    return ("other", d.verb)


# ── grammar ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("line", list(GRAMMAR))
def test_python_grammar(line):
    assert python_outcome(line) == GRAMMAR[line]


def test_status_validation_names_the_valid_set():
    f = parse_ls_flags("--status bogus")
    assert f.errors and all(s in f.errors[0] for s in RUN_STATUSES)
    assert parse_ls_flags("--status").errors


def _routing_harness_web() -> str:
    return r"""
const { TaskController } = require(process.env.WEB + '/task-controller.js');
const GRAMMAR = JSON.parse(process.env.GRAMMAR);
(async () => {
  const res = {};
  for (const line of Object.keys(GRAMMAR)) {
    let outcome = null;
    const app = { _msgs: [], showSystemMessage(m) { app._msgs.push(m); }, state: {}, apiClient: {} };
    const c = new TaskController(app);
    c.list = async (o) => { outcome = ['list', !!o.all, o.status || null]; };
    c.run = async () => { outcome = 'launch'; };
    c.get = () => { outcome = ['other', 'get']; };
    await c.handle(line);
    if (outcome === null) {
      outcome = app._msgs.some((m) => /looks like a run id/.test(m)) ? 'near_miss'
              : app._msgs.some((m) => /ls`: /.test(m)) ? 'error' : 'nothing';
    }
    res[line] = outcome;
  }
  console.log(JSON.stringify(res));
})();
"""


def _routing_harness_ts() -> str:
    return r"""
const B = require(process.env.BUNDLE);
const GRAMMAR = JSON.parse(process.env.GRAMMAR);
(async () => {
  const res = {};
  for (const line of Object.keys(GRAMMAR)) {
    let outcome = null;
    const msgs = [];
    const c = new B.TaskController({}, { system: (m) => msgs.push(m), result() {}, askConsent: async () => undefined });
    c.list = async (o) => { outcome = ['list', !!o.all, o.status || null]; };
    c.run = async () => { outcome = 'launch'; };
    c.get = async () => { outcome = ['other', 'get']; };
    await c.handle(line);
    if (outcome === null) {
      outcome = msgs.some((m) => /looks like a run id/.test(m)) ? 'near_miss'
              : msgs.some((m) => /ls`: /.test(m)) ? 'error' : 'nothing';
    }
    res[line] = outcome;
  }
  console.log(JSON.stringify(res));
})();
"""


def _normalise(expected):
    return list(expected) if isinstance(expected, tuple) else expected


def _node(script: str, **env) -> str:
    proc = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, encoding="utf-8",
        timeout=60,
        env=minimal_subprocess_env(PATH=os.environ.get("PATH", ""), **env),
    )
    assert proc.returncode == 0, f"node failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    return proc.stdout.strip().splitlines()[-1]


@needs_node
def test_web_grammar_matches_python():
    res = json.loads(_node(_routing_harness_web(), WEB=str(WEB_SHARED),
                           GRAMMAR=json.dumps(GRAMMAR)))
    for line, expected in GRAMMAR.items():
        assert res[line] == _normalise(expected), (line, res[line])


def _bundle(tmp_path: Path) -> Path:
    work = tmp_path / "src"
    work.mkdir()
    (work / "taskController.ts").write_text(
        TS_CONTROLLER.read_text(encoding="utf-8"), encoding="utf-8")
    (work / "entry.ts").write_text(
        "export { TaskController, RunController, parseLsFlags, scopeAndNest }"
        " from './taskController';\n", encoding="utf-8")
    out = tmp_path / "bundle.js"
    proc = subprocess.run(
        [str(ESBUILD), str(work / "entry.ts"), "--bundle", "--format=cjs",
         "--platform=node", "--target=node18", f"--outfile={out}"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return out


@needs_esbuild
def test_vscode_grammar_matches_python(tmp_path):
    res = json.loads(_node(_routing_harness_ts(), BUNDLE=str(_bundle(tmp_path)),
                           GRAMMAR=json.dumps(GRAMMAR)))
    for line, expected in GRAMMAR.items():
        assert res[line] == _normalise(expected), (line, res[line])


# ── scope: in-process TUI path ──────────────────────────────────────────────

class _Conversation:
    def __init__(self, name):
        self.session_name = name


class _Ctx:
    provider = "p"
    current_model = "m"


def _seeded_backend(tmp_path, monkeypatch, active="conv-a"):
    b = InProcessTaskBackend(
        AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs")),
        session_provider=lambda: _Conversation(active),
    )
    monkeypatch.setattr(task_cmd, "get_task_backend", lambda: b)
    reg = b.registry

    def mk(task, session, parent=None, kind="task", status=None):
        m = reg.start_run(task=task, kind=kind, tools=[], provider="p", model="m",
                          session_id=session, parent_run_id=parent)
        if status:
            m.status = status
            reg._store.persist_meta(m)
        return m

    a = mk("task in A", "conv-a", status="running")
    mk("child of A", "conv-a", parent=a.run_id, status="failed")
    mk("task in B", "conv-b")
    mk("legacy no conversation", None)
    mk("oneshot in A", "conv-a", kind="oneshot")
    return b, a


def _tasks(table):
    return [r[2] for r in table.rows]


def test_default_ls_shows_only_the_active_conversation_with_child_nested(tmp_path, monkeypatch):
    _seeded_backend(tmp_path, monkeypatch)
    out = task_cmd.handle_task(_Ctx(), "ls")
    assert isinstance(out, TableResult)
    assert _tasks(out) == ["task in A", "└ child of A"]
    assert "Conversation" not in out.columns


def test_ls_all_lists_every_conversation_and_marks_the_null_one(tmp_path, monkeypatch):
    _seeded_backend(tmp_path, monkeypatch)
    out = task_cmd.handle_task(_Ctx(), "ls --all")
    assert "Conversation" in out.columns
    col = out.columns.index("Conversation")
    by_task = {r[2]: r[col] for r in out.rows}
    assert set(by_task) == {"task in A", "└ child of A", "task in B", "legacy no conversation"}
    assert by_task["legacy no conversation"] == "(none)"
    assert by_task["task in B"] == "conv-b"
    # the child still nests when everything is listed
    flat = _tasks(out)
    assert flat.index("└ child of A") == flat.index("task in A") + 1


def test_ls_status_filters_and_an_orphaned_child_stays_visible(tmp_path, monkeypatch):
    _seeded_backend(tmp_path, monkeypatch)
    # parent is `running`, so a failed-only listing has the child without its parent
    out = task_cmd.handle_task(_Ctx(), "ls --status failed")
    assert _tasks(out) == ["child of A"]  # top level, no nesting marker, not lost
    both = task_cmd.handle_task(_Ctx(), "ls --all --status running")
    assert _tasks(both) == ["task in A"]


def test_unknown_status_is_an_actionable_error(tmp_path, monkeypatch):
    _seeded_backend(tmp_path, monkeypatch)
    out = task_cmd.handle_task(_Ctx(), "ls --status bogus")
    assert isinstance(out, ErrorResult)
    assert "bogus" in out.message and "running" in out.message


def test_run_ls_uses_the_same_scope_for_oneshots(tmp_path, monkeypatch):
    _seeded_backend(tmp_path, monkeypatch)
    assert _tasks(task_cmd.handle_run(_Ctx(), "ls")) == ["oneshot in A"]
    other = task_cmd.handle_run(_Ctx(), "ls --status failed")
    assert isinstance(other, NotificationResult)


def test_another_conversation_sees_its_own_runs(tmp_path, monkeypatch):
    _seeded_backend(tmp_path, monkeypatch, active="conv-b")
    assert _tasks(task_cmd.handle_task(_Ctx(), "ls")) == ["task in B"]


def test_no_active_conversation_matches_nothing_by_default():
    class R:
        def __init__(self, i, s, p=None, st="running"):
            self.run_id, self.session_id, self.parent_run_id, self.status = i, s, p, st
    runs = [R("1", None), R("2", "c")]
    assert scope_and_nest(runs, session_id=None, all_sessions=False) == []
    assert [r.run_id for r, _ in scope_and_nest(runs, session_id=None, all_sessions=True)] == ["1", "2"]


# ── scope: web and VSCode (server-side filtering simulated) ─────────────────

_MASTER = [
    # newest first, as the registry lists them
    dict(run_id=ONESHOT, task="oneshot in A", status="finalized", kind="oneshot", session_id="conv-a", parent_run_id=None),
    dict(run_id=NULL, task="legacy no conversation", status="finalized", kind="task", session_id=None, parent_run_id=None),
    dict(run_id=B, task="task in B", status="finalized", kind="task", session_id="conv-b", parent_run_id=None),
    dict(run_id=CHILD, task="child of A", status="failed", kind="task", session_id="conv-a", parent_run_id=A),
    dict(run_id=A, task="task in A", status="running", kind="task", session_id="conv-a", parent_run_id=None),
]

_SERVER = r"""
const MASTER = JSON.parse(process.env.MASTER);
function serve(url) {
  if (url === '/status') return { session_name: 'conv-a' };
  const q = new URLSearchParams(url.split('?')[1] || '');
  return { runs: MASTER.filter((r) =>
    (!q.get('kind') || r.kind === q.get('kind'))
    && (!q.get('session') || r.session_id === q.get('session'))
    && (!q.get('status') || r.status === q.get('status'))) };
}
"""

_WEB_LIST = _SERVER + r"""
const { TaskController } = require(process.env.WEB + '/task-controller.js');
const { RunController } = require(process.env.WEB + '/run-controller.js');
async function lines(Ctl, line) {
  const urls = []; const msgs = [];
  global.document = { createElement: () => ({ style: {}, kids: [], appendChild(c) { this.kids.push(c); }, addEventListener() {} }) };
  const content = { kids: [], appendChild(c) { this.kids.push(c); } };
  const app = {
    showSystemMessage: (m) => msgs.push(m), state: {},
    addMessage: () => ({ querySelector: () => content }),
    apiClient: { get: async (u) => { urls.push(u); return serve(u); } },
  };
  await new Ctl(app).handle(line);
  const box = content.kids[0] ? content.kids[0].kids : [];
  return { urls: urls.filter((u) => u !== '/status'), msgs, rows: box.map((k) => k.textContent) };
}
(async () => {
  const out = {};
  out.def = await lines(TaskController, 'ls');
  out.all = await lines(TaskController, 'ls --all');
  out.failed = await lines(TaskController, 'ls --status failed');
  out.bad = await lines(TaskController, 'ls --status bogus');
  out.run = await lines(RunController, 'ls');
  console.log(JSON.stringify(out));
})();
"""

_TS_LIST = _SERVER + r"""
const B = require(process.env.BUNDLE);
async function lines(Ctl, line) {
  const urls = []; const msgs = [];
  const backend = {
    getStatus: async () => serve('/status'),
    agentRuns: async (kind, f) => {
      const q = [];
      if (kind) q.push('kind=' + kind);
      if (f && f.session) q.push('session=' + encodeURIComponent(f.session));
      if (f && f.status) q.push('status=' + encodeURIComponent(f.status));
      const u = '/v1/agent/runs' + (q.length ? '?' + q.join('&') : '');
      urls.push(u); return serve(u);
    },
  };
  const ui = { system: (m) => msgs.push(m), result() {}, askConsent: async () => undefined };
  await new Ctl(backend, ui).handle(line);
  return { urls, msgs, rows: (msgs[0] || '').split('\n').slice(1) };
}
(async () => {
  const out = {};
  out.def = await lines(B.TaskController, 'ls');
  out.all = await lines(B.TaskController, 'ls --all');
  out.failed = await lines(B.TaskController, 'ls --status failed');
  out.bad = await lines(B.TaskController, 'ls --status bogus');
  out.run = await lines(B.RunController, 'ls');
  console.log(JSON.stringify(out));
})();
"""


def _check_client(out):
    # default: only conversation A (server asked with ?session=), child nested
    assert out["def"]["urls"] == ["/v1/agent/runs?kind=task&session=conv-a"]
    rows = out["def"]["rows"]
    assert len(rows) == 2 and A in rows[0] and CHILD in rows[1] and "└" in rows[1]
    assert not any(B in r or NULL in r for r in rows)
    # --all: no session filter; the null run is marked; the child still nests
    assert out["all"]["urls"] == ["/v1/agent/runs?kind=task"]
    rows = out["all"]["rows"]
    assert len(rows) == 4
    null_row = next(r for r in rows if NULL in r)
    assert "(none)" in null_row
    assert next(r for r in rows if B in r).count("conv-b") == 1
    assert any(CHILD in r and "└" in r for r in rows)
    # --status: the server is asked; a child without its parent is top level
    assert out["failed"]["urls"] == ["/v1/agent/runs?kind=task&session=conv-a&status=failed"]
    rows = out["failed"]["rows"]
    assert len(rows) == 1 and CHILD in rows[0] and "└" not in rows[0]
    # unknown status: actionable, no request
    assert out["bad"]["urls"] == []
    assert "bogus" in out["bad"]["msgs"][0] and "running" in out["bad"]["msgs"][0]
    # /run ls: same scope, oneshot kind
    assert out["run"]["urls"] == ["/v1/agent/runs?kind=oneshot&session=conv-a"]
    assert len(out["run"]["rows"]) == 1 and ONESHOT in out["run"]["rows"][0]


@needs_node
def test_web_ls_scope_nesting_and_flags():
    out = json.loads(_node(_WEB_LIST, WEB=str(WEB_SHARED), MASTER=json.dumps(_MASTER)))
    _check_client(out)


@needs_esbuild
def test_vscode_ls_scope_nesting_and_flags(tmp_path):
    out = json.loads(_node(_TS_LIST, BUNDLE=str(_bundle(tmp_path)),
                           MASTER=json.dumps(_MASTER)))
    _check_client(out)

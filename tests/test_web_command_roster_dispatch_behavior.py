"""Behavioral tests for the roster-driven web dispatcher (ADR 0007 step 3a).

The other web-dispatcher tests read source text. These drive the REAL
`ppxai/web/shared/command-dispatcher.js` and
`ppxai/web/shared/command-roster.js` under Node against a fake
`ApiClient` that logs every call, because step 3a's guarantees are
*runtime* guarantees a structural read cannot see:

  1. **Routing is data.** Each of the four `client_action` names the
     server declares for web — `token.manage`, `task.controller`,
     `run.controller`, `auto.loop` — reaches its bundled implementation
     because the ROSTER says `dispatch === "client"`, not because a name
     is hardcoded. Flip the roster and the routing flips.
  2. **Aliases resolve client-side.** `/cat` reaches `show`'s entry from
     the `aliases` FIELD — no standalone alias rows (the `commands.js`
     duplication this record deletes).
  3. **Server dispatch carries `client: "web"`**, which is what lets the
     server stop over-listing `/help` for the web+vscode union.
  4. **An action the roster names that this client does not implement is
     an ERROR, never a silent forward.**
  5. **FAIL CLOSED.** With NO roster, `/token set <secret>` results in
     zero requests other than the roster retry, and the secret appears in
     no outgoing payload. This is the security property: the web assets
     are served from `~/.ppxai/web` and can be NEWER than the running
     server (docs/lessons/web-assets-served-from-ppxai-home.md), so a
     404 on `GET /commands` is a realistic production state — and the old
     guarantee (hardcoded branch order) no longer exists to cover it.
  6. **The `refresh_command_roster` side effect refetches**, and a failed
     refetch keeps the working roster rather than downgrading the client
     into the fail-closed state.

Both of the security-shaped scenarios (5 and the never-POST half of 1)
are MUTATION-VERIFIED below: a scratch copy of the dispatcher with the
behaviour removed is written to `tmp_path` and the same harness must
FAIL against it. Nothing is left behind — the mutants live and die in
pytest's tmp dir, the repo copy is never touched.

Skips cleanly where Node isn't available (same env contract as
tests/test_agent_run_controller_behavior.py).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
SHARED = Path(__file__).resolve().parents[1] / "ppxai" / "web" / "shared"
DISPATCHER = SHARED / "command-dispatcher.js"
ROSTER = SHARED / "command-roster.js"
SIDE_EFFECTS = SHARED / "side-effects.js"

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


# Paths arrive through the environment rather than string formatting, so the
# harness below is plain readable JS (no doubled braces).
_HARNESS = r"""
const { CommandRoster } = require(process.env.PPXAI_ROSTER);
const { SideEffectsHandler } = require(process.env.PPXAI_SIDE_EFFECTS);

// The dispatcher constructs these as browser globals.
global.SideEffectsHandler = SideEffectsHandler;
global.ResultRenderer = function ResultRenderer() { this.render = () => {}; };
global.TaskController = function TaskController(app) {
    this.handle = async (args) => { app._actions.push(['task.controller', args]); };
};
global.RunController = function RunController(app) {
    this.handle = async (args) => { app._actions.push(['run.controller', args]); };
};

const { CommandDispatcher } = require(process.env.PPXAI_DISPATCHER);

function entry(name, over) {
    return Object.assign({
        name, aliases: [], description: name, usage: '/' + name,
        category: 'tools', hidden: false, subcommands: [],
        clients: null, client_action: null, client_action_clients: null,
        client_handled: false, dispatch: 'server',
    }, over || {});
}

// Shaped exactly like CommandFactory.roster('web'): aliases are a FIELD,
// dispatch is precomputed for this client.
const ROSTER_PAYLOAD = {
    version: 7,
    commands: [
        entry('auto',  {dispatch: 'client', client_action: 'auto.loop'}),
        entry('run',   {dispatch: 'client', client_action: 'run.controller'}),
        entry('task',  {dispatch: 'client', client_action: 'task.controller'}),
        entry('token', {dispatch: 'client', client_action: 'token.manage',
                        client_handled: true}),
        entry('future', {dispatch: 'client', client_action: 'future.thing'}),
        entry('show',  {aliases: ['cat']}),
        entry('status'),
        entry('help',  {aliases: ['?', 'h'], client_action: 'help.augment'}),
    ],
};

function makeApi(opts) {
    opts = opts || {};
    const api = {
        calls: [],
        apiToken: null,
        rosterFails: !!opts.rosterFails,
        payload: opts.payload || ROSTER_PAYLOAD,
        setApiToken(t) { api.apiToken = t || null; },
        async getCommandRoster(client) {
            api.calls.push({kind: 'roster', method: 'GET', url: '/commands', client});
            if (api.rosterFails) { const e = new Error('HTTP 404 Not Found'); e.status = 404; throw e; }
            return api.payload;
        },
        async executeCommand(name, args, client) {
            api.calls.push({kind: 'command', method: 'POST',
                            url: '/command/' + name, body: {args, client}});
            return {ok: true, result: {type: 'text', content: 'ok'},
                    side_effects: [], events: []};
        },
        async post(url, body) {
            api.calls.push({kind: 'post', method: 'POST', url, body});
            return {token: 'minted', meta: {token_id: 'tid', owner: 'web-local'}};
        },
        async get(url) { api.calls.push({kind: 'get', method: 'GET', url}); return {}; },
    };
    return api;
}

function makeApp(api) {
    const app = {
        _msgs: [], _errors: [], _actions: [], _chat: [],
        state: {isHandlingCommand: false, agentMode: false},
        apiClient: api,
        showSystemMessage(m) { app._msgs.push(String(m)); },
        showError(m) { app._errors.push(String(m)); },
        addMessage(role, c) { app._msgs.push(role + ':' + c); },
        async streamChat(t) { app._chat.push(t); },
        async toggleAgent() {
            app._actions.push(['toggleAgent']);
            app.state.agentMode = !app.state.agentMode;
        },
        handleStateSync() {},
        processSseEvent() {},
    };
    app.commandRoster = new CommandRoster(api, 'web');
    app.commandDispatcher = new CommandDispatcher(app);
    app.sideEffects = new SideEffectsHandler(app);
    return app;
}

function assert(cond, msg) { if (!cond) throw new Error('FAIL: ' + msg); }
function posts(api) { return api.calls.filter((c) => c.method === 'POST'); }
function leaks(api, needle) { return api.calls.some((c) => JSON.stringify(c).includes(needle)); }

(async () => {
  // --- Scenario 1: the roster routes all four web client actions ---
  {
    const api = makeApi();
    const app = makeApp(api);
    await app.commandRoster.load();
    const before = api.calls.length;

    await app.commandDispatcher.dispatch('/token status');
    await app.commandDispatcher.dispatch('/task ls --json');
    await app.commandDispatcher.dispatch('/run ls');
    await app.commandDispatcher.dispatch('/auto on');

    const after = api.calls.slice(before);
    assert(after.length === 0,
      'a dispatch==="client" command hit the network: ' + JSON.stringify(after));
    const names = app._actions.map((a) => a[0]);
    assert(names.includes('task.controller'), 'task.controller impl not reached');
    assert(names.includes('run.controller'), 'run.controller impl not reached');
    assert(names.includes('toggleAgent'), 'auto.loop impl not reached');
    assert(app._msgs.some((m) => /No API token stored/.test(m)),
      'token.manage impl not reached (msgs=' + JSON.stringify(app._msgs) + ')');
    const taskArgs = app._actions.find((a) => a[0] === 'task.controller')[1];
    assert(taskArgs === 'ls --json', 'arg string not forwarded verbatim: ' + taskArgs);
  }

  // --- Scenario 1b: routing follows the DATA, not the name ---
  // Same client, same command name, roster says "server" -> it is POSTed.
  {
    const flipped = JSON.parse(JSON.stringify(ROSTER_PAYLOAD));
    for (const c of flipped.commands) {
      if (c.name === 'task') { c.dispatch = 'server'; c.client_action = null; }
    }
    const api = makeApi({payload: flipped});
    const app = makeApp(api);
    await app.commandRoster.load();
    await app.commandDispatcher.dispatch('/task ls');
    const cmds = api.calls.filter((c) => c.kind === 'command');
    assert(cmds.length === 1 && cmds[0].url === '/command/task',
      'flipping the roster did not flip routing: ' + JSON.stringify(api.calls));
    assert(app._actions.length === 0, 'client impl ran despite dispatch==="server"');
  }

  // --- Scenario 2: /token set <secret> is never POSTed (roster present) ---
  {
    const api = makeApi();
    const app = makeApp(api);
    await app.commandRoster.load();
    await app.commandDispatcher.dispatch('/token set S3CRET-VALUE-A');
    assert(posts(api).length === 0,
      'a POST was issued for a client-dispatched command: ' + JSON.stringify(posts(api)));
    assert(!leaks(api, 'S3CRET-VALUE-A'), 'the secret appeared in an outgoing request');
    assert(api.apiToken === 'S3CRET-VALUE-A', 'the token was not stored client-side');
  }

  // --- Scenario 3: alias resolution + canonical name + client:"web" body ---
  {
    const api = makeApi();
    const app = makeApp(api);
    await app.commandRoster.load();
    await app.commandDispatcher.dispatch('/cat /tmp/x.txt');
    const cmds = api.calls.filter((c) => c.kind === 'command');
    assert(cmds.length === 1, 'expected exactly one command POST, got ' + cmds.length);
    assert(cmds[0].url === '/command/show',
      'alias /cat did not resolve to canonical show: ' + cmds[0].url);
    assert(cmds[0].body.args === '/tmp/x.txt', 'args mangled: ' + cmds[0].body.args);
    assert(cmds[0].body.client === 'web', 'POST body is missing client:"web"');
  }

  // --- Scenario 4: a plain server command ---
  {
    const api = makeApi();
    const app = makeApp(api);
    await app.commandRoster.load();
    await app.commandDispatcher.dispatch('/status');
    const cmds = api.calls.filter((c) => c.kind === 'command');
    assert(cmds.length === 1 && cmds[0].url === '/command/status',
      'server command not dispatched: ' + JSON.stringify(api.calls));
    assert(cmds[0].body.client === 'web', 'POST body is missing client:"web"');
    // /help has no client-side intercept any more: it is server-dispatched
    // once, so the catalog can no longer list /token, /run, /task twice.
    await app.commandDispatcher.dispatch('/help');
    const helps = api.calls.filter((c) => c.url === '/command/help');
    assert(helps.length === 1, '/help did not go to the server exactly once');
    assert(!app._msgs.some((m) => /Experimental \(web-only\)/.test(m)),
      'the deleted _appendExperimentalHelp shim still runs');
  }

  // --- Scenario 5: an action the roster names but web does not implement ---
  {
    const api = makeApi();
    const app = makeApp(api);
    await app.commandRoster.load();
    await app.commandDispatcher.dispatch('/future whatever');
    assert(posts(api).length === 0,
      'an unimplemented client action was silently forwarded: ' + JSON.stringify(posts(api)));
    assert(app._errors.some((m) => /future\.thing/.test(m)),
      'no clear error naming the unimplemented action (errors=' + JSON.stringify(app._errors) + ')');
  }

  // --- Scenario 6: NO ROSTER -> fail closed, zero leakage ---
  {
    const api = makeApi({rosterFails: true});
    const app = makeApp(api);
    const ok = await app.commandRoster.load();
    assert(ok === false, 'load() reported success despite a failing fetch');
    api.calls.length = 0;   // discard the startup attempt

    await app.commandDispatcher.dispatch('/token set TOP-SECRET-42');

    assert(posts(api).length === 0,
      'FAIL-OPEN: a POST was issued with no roster: ' + JSON.stringify(posts(api)));
    assert(!leaks(api, 'TOP-SECRET-42'),
      'the secret appeared in an outgoing request with no roster');
    const nonRoster = api.calls.filter((c) => c.kind !== 'roster');
    assert(nonRoster.length === 0,
      'with no roster the only permitted call is the roster retry; got ' + JSON.stringify(nonRoster));
    assert(api.calls.filter((c) => c.kind === 'roster').length === 1,
      'the dispatcher did not retry the roster fetch');
    assert(api.apiToken === null, 'the secret was stored despite the refusal');

    const err = app._errors.join('\n');
    assert(/skew/i.test(err), 'the refusal does not name the version-skew possibility');
    assert(err.includes('~/.ppxai/web'),
      'the refusal does not name where the web assets are served from');

    // A plain server command is refused too — fail closed means closed.
    await app.commandDispatcher.dispatch('/status');
    assert(posts(api).length === 0, 'a server command was forwarded with no roster');
    // ...and a chat-shaped slash command does not slip past the gate either.
    await app.commandDispatcher.dispatch('/explain this code');
    assert(app._chat.length === 0, 'a streaming command bypassed the fail-closed gate');
  }

  // --- Scenario 7: self-heal once the server comes back ---
  {
    const api = makeApi({rosterFails: true});
    const app = makeApp(api);
    await app.commandRoster.load();
    api.rosterFails = false;
    await app.commandDispatcher.dispatch('/status');
    const cmds = api.calls.filter((c) => c.kind === 'command');
    assert(cmds.length === 1 && cmds[0].url === '/command/status',
      'the dispatcher did not self-heal once the roster became reachable');
  }

  // --- Scenario 8: refresh_command_roster refetches ---
  {
    const api = makeApi();
    const app = makeApp(api);
    await app.commandRoster.load();
    const before = api.calls.filter((c) => c.kind === 'roster').length;

    const grown = JSON.parse(JSON.stringify(ROSTER_PAYLOAD));
    grown.version = 8;
    grown.commands.push(entry('brandnew'));
    api.payload = grown;

    app.sideEffects.apply([{kind: 'refresh_command_roster', version: 8}]);
    await new Promise((r) => setTimeout(r, 20));

    const after = api.calls.filter((c) => c.kind === 'roster').length;
    assert(after === before + 1, 'refresh_command_roster did not trigger a refetch');
    assert(app.commandRoster.version === 8,
      'roster version not updated (got ' + app.commandRoster.version + ')');
    assert(app.commandRoster.resolve('/brandnew'),
      'the refetched roster does not carry the newly registered command');

    // The same version again is a no-op (the signal is idempotent).
    app.sideEffects.apply([{kind: 'refresh_command_roster', version: 8}]);
    await new Promise((r) => setTimeout(r, 20));
    assert(api.calls.filter((c) => c.kind === 'roster').length === after,
      'a same-version signal caused a needless refetch');
  }

  // --- Scenario 9: a failed REFRESH keeps the working roster ---
  {
    const api = makeApi();
    const app = makeApp(api);
    await app.commandRoster.load();
    api.rosterFails = true;
    const ok = await app.commandRoster.load();
    assert(ok === true, 'a failed refresh un-loaded a working roster');
    assert(app.commandRoster.isLoaded(), 'roster reported unloaded after a failed refresh');
    api.calls.length = 0;
    await app.commandDispatcher.dispatch('/token status');
    assert(posts(api).length === 0, 'routing broke after a failed refresh');
    assert(app._msgs.some((m) => /API token/.test(m)), 'token.manage not reached after a failed refresh');
  }

  console.log("ALL OK");
})().catch((e) => { console.error(e.message || e); process.exit(1); });
"""


def _run(dispatcher: Path = DISPATCHER) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PPXAI_DISPATCHER"] = str(dispatcher)
    env["PPXAI_ROSTER"] = str(ROSTER)
    env["PPXAI_SIDE_EFFECTS"] = str(SIDE_EFFECTS)
    return subprocess.run(
        [NODE, "-e", _HARNESS], capture_output=True, text=True, timeout=60, env=env
    )


def _mutant(tmp_path: Path, old: str, new: str) -> Path:
    """Write a scratch copy of the dispatcher with `old` replaced.

    The repo copy is never touched; the mutant lives in pytest's tmp dir
    and is discarded with it.
    """
    src = DISPATCHER.read_text(encoding="utf-8")
    assert old in src, (
        "mutation anchor not found in command-dispatcher.js — this mutation "
        "test is stale and is no longer proving anything"
    )
    path = tmp_path / "command-dispatcher.js"
    path.write_text(src.replace(old, new, 1), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The real dispatcher
# ---------------------------------------------------------------------------

def test_roster_drives_routing_fails_closed_and_refetches():
    proc = _run()
    assert proc.returncode == 0, (
        f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    assert "ALL OK" in proc.stdout, proc.stdout


# ---------------------------------------------------------------------------
# Mutation verification — the two security scenarios must be able to fail.
# ---------------------------------------------------------------------------

_GATE = """            const roster = await this._readyRoster();
            if (!roster) {
                this._explainMissingRoster(cmd);
                return;
            }"""

_CLIENT_BRANCH = "            if (entry && entry.dispatch === 'client') {"


class TestMutationFailClosed:
    def test_removing_the_gate_is_caught(self, tmp_path):
        """Fail OPEN — the roster gate degrades to an empty roster and the
        dispatcher forwards whatever it could not classify. That is the
        exact regression that would POST `/token set <secret>`."""
        mutant = _mutant(
            tmp_path, _GATE,
            "            const roster = (await this._readyRoster()) "
            "|| { resolve: () => null };",
        )
        proc = _run(mutant)
        assert proc.returncode != 0, (
            "the fail-closed scenario PASSED against a dispatcher with no gate — "
            f"the test proves nothing.\nSTDOUT: {proc.stdout}"
        )
        assert "FAIL-OPEN" in proc.stderr, proc.stderr


class TestMutationClientDispatchedNeverPosted:
    def test_bypassing_the_client_branch_is_caught(self, tmp_path):
        """A client-dispatched command that falls through to the factory
        POST is the "forward it and let the server refuse" posture ADR 0007
        explicitly rejects (the secret is already in the body by then)."""
        mutant = _mutant(
            tmp_path, _CLIENT_BRANCH,
            "            if (false && entry && entry.dispatch === 'client') {",
        )
        proc = _run(mutant)
        assert proc.returncode != 0, (
            "the never-POST scenario PASSED against a dispatcher that forwards "
            f"client-dispatched commands.\nSTDOUT: {proc.stdout}"
        )
        assert "hit the network" in proc.stderr, proc.stderr

"""Behavioral tests for the web client's sensitive-argument rule (ADR 0007 step 3a-sec).

Companion to `tests/test_web_command_roster_dispatch_behavior.py`, same
idiom: drive the REAL `ppxai/web/shared/command-roster.js` and
`command-dispatcher.js` under Node against a fake roster payload and a
call-logging fake `ApiClient`, because these are RUNTIME guarantees that
a source-text read cannot see.

What is pinned:

  1. **The rule is DATA.** `isSensitive` / `redact` answer from the
     roster's per-subcommand `sensitive` flag — the same flag
     `CommandFactory.roster()` publishes from
     `CommandSpec.sensitive_subcommands`. Flip the flag in the payload
     and the answer flips; no client code names `/token` or `set`.
  2. **The truth table matches Python's** `redact_sensitive`, decision
     for decision: case-insensitive on command AND subcommand,
     whitespace-tolerant, a VALUE is required (so `/token se` still
     completes to `set`), the `> ` echo marker is tolerated, plain chat
     is untouched, and nothing raises on odd input.
  3. **FAIL CLOSED with no roster**, consistently with the dispatcher's
     dispatch gate: the args of ANY slash command are treated as secret.
  4. **The dispatcher's chat echo is redacted** before it is rendered or
     mirrored to `POST /client-log` — the actual leak this step closes.

(3) and (4) are MUTATION-VERIFIED: scratch copies with the behaviour
removed must FAIL the same harness. Nothing is left behind — the mutants
live and die in pytest's tmp dir.

Skips cleanly where Node isn't available.
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

MASK = "••••"

_HARNESS = r"""
const { CommandRoster, SENSITIVE_MASK } = require(process.env.PPXAI_ROSTER);
const { SideEffectsHandler } = require(process.env.PPXAI_SIDE_EFFECTS);

global.CommandRoster = CommandRoster;
global.SideEffectsHandler = SideEffectsHandler;
global.ResultRenderer = function ResultRenderer() { this.render = () => {}; };
global.TaskController = function TaskController(app) {
    this.handle = async () => { app._actions.push(['task']); };
};
global.RunController = function RunController(app) {
    this.handle = async () => { app._actions.push(['run']); };
};
global.localStorage = {
    _d: {},
    getItem(k) { return k in this._d ? this._d[k] : null; },
    setItem(k, v) { this._d[k] = String(v); },
    removeItem(k) { delete this._d[k]; },
};

const { CommandDispatcher } = require(process.env.PPXAI_DISPATCHER);

const M = SENSITIVE_MASK;

// Shaped exactly like CommandFactory.roster('web'): `sensitive` is a
// per-subcommand field, aliases are a field on the canonical entry.
const PAYLOAD = {
    version: 3,
    commands: [
        {
            name: 'token', aliases: ['tk'], description: 'tokens',
            usage: '/token', category: 'system', hidden: false,
            subcommands: [
                {name: 'status', description: 's', sensitive: false},
                {name: 'set', description: 's', sensitive: true},
                {name: 'mint', description: 's', sensitive: false},
                {name: 'clear', description: 's', sensitive: false},
            ],
            clients: ['web', 'vscode'], client_action: 'token.manage',
            client_action_clients: null, client_handled: true,
            dispatch: 'client',
        },
        {
            name: 'show', aliases: ['cat'], description: 'show',
            usage: '/show', category: 'display', hidden: false,
            subcommands: [], clients: null, client_action: null,
            client_action_clients: null, client_handled: false,
            dispatch: 'server',
        },
        {
            name: 'status', aliases: [], description: 'status',
            usage: '/status', category: 'system', hidden: false,
            subcommands: [], clients: null, client_action: null,
            client_action_clients: null, client_handled: false,
            dispatch: 'server',
        },
    ],
};

function makeApi(opts) {
    opts = opts || {};
    const api = {
        calls: [], apiToken: null,
        rosterFails: !!opts.rosterFails,
        payload: opts.payload || PAYLOAD,
        setApiToken(t) { api.apiToken = t || null; },
        async getCommandRoster(client) {
            api.calls.push({kind: 'roster', url: '/commands', client});
            if (api.rosterFails) throw new Error('HTTP 404 Not Found');
            return api.payload;
        },
        async executeCommand(name, args, client) {
            api.calls.push({kind: 'command', method: 'POST',
                            url: '/command/' + name, body: {args, client}});
            return {ok: true, result: {type: 'text', content: 'ok'},
                    side_effects: [], events: []};
        },
        async post(url, body) { api.calls.push({kind: 'post', url, body}); return {}; },
    };
    return api;
}

function makeApp(api) {
    const app = {
        _msgs: [], _errors: [], _actions: [], _chat: [],
        state: {isHandlingCommand: false, agentMode: false},
        apiClient: api,
        // The REAL sink shape: showSystemMessage renders AND mirrors to
        // POST /client-log, so whatever reaches it reaches the server log.
        showSystemMessage(m) {
            app._msgs.push(String(m));
            api.calls.push({kind: 'clientlog', method: 'POST',
                            url: '/client-log', body: {message: String(m)}});
        },
        showError(m) { app._errors.push(String(m)); },
        addMessage(role, c) { app._msgs.push(role + ':' + c); },
        async streamChat(t) { app._chat.push(t); },
        async toggleAgent() { app.state.agentMode = !app.state.agentMode; },
        handleStateSync() {}, processSseEvent() {},
    };
    app.commandRoster = new CommandRoster(api, 'web');
    app.commandDispatcher = new CommandDispatcher(app);
    return app;
}

function assert(cond, msg) { if (!cond) throw new Error('FAIL: ' + msg); }
function leaks(api, needle) { return api.calls.some((c) => JSON.stringify(c).includes(needle)); }

const SECRET = 'SECRET-BEARER-9f2a';

(async () => {
  // --- 1: the truth table, roster LOADED (mirrors the Python table) ---
  {
    const api = makeApi();
    const r = new CommandRoster(api, 'web');
    await r.load();

    const table = [
        // [input, expected redaction, expected isSensitive]
        ['/token set ' + SECRET,        '/token set ' + M,        true],
        ['> /token set ' + SECRET,      '> /token set ' + M,      true],
        ['>  /token set ' + SECRET,     '>  /token set ' + M,     true],
        ['/token set ' + SECRET + ' x', '/token set ' + M,        true],
        // Case-insensitive on BOTH, keeping the original text.
        ['/TOKEN SET ' + SECRET,        '/TOKEN SET ' + M,        true],
        ['/Token Set ' + SECRET,        '/Token Set ' + M,        true],
        // Whitespace-tolerant; only the separator before the mask normalises.
        ['/token  set   ' + SECRET,     '/token  set ' + M,       true],
        ['/token\tset\t' + SECRET,      '/token\tset ' + M,       true],
        ['   /token set ' + SECRET,     '   /token set ' + M,     true],
        // An ALIAS resolves — a hardcoded "/token" check would miss this.
        ['/tk set ' + SECRET,           '/tk set ' + M,           true],
        ['/TK SET ' + SECRET,           '/TK SET ' + M,           true],
        // A value is REQUIRED (this is what keeps `/token se` -> `set`).
        ['/token set',                  '/token set',             false],
        ['/token set   ',               '/token set   ',          false],
        ['/token se',                   '/token se',              false],
        ['/token se abc',               '/token se abc',          false],
        // Declared but not sensitive.
        ['/token status x',             '/token status x',        false],
        ['/token clear now',            '/token clear now',       false],
        // No sensitive subcommands at all / unknown / not a command.
        ['/show /etc/hosts',            '/show /etc/hosts',       false],
        ['/nosuch set abc',             '/nosuch set abc',        false],
        ['tell me about /token set x',  'tell me about /token set x', false],
        ['plain chat text',             'plain chat text',        false],
        ['',                            '',                       false],
        ['   ',                         '   ',                    false],
        ['/',                           '/',                      false],
        ['/token',                      '/token',                 false],
    ];
    for (const [input, expected, sensitive] of table) {
        const got = r.redact(input);
        assert(got === expected,
          'redact(' + JSON.stringify(input) + ') = ' + JSON.stringify(got) +
          ', expected ' + JSON.stringify(expected));
        assert(r.isSensitive(input) === sensitive,
          'isSensitive(' + JSON.stringify(input) + ') = ' + r.isSensitive(input));
        assert(!got.includes(SECRET) || !sensitive,
          'the secret survived redaction: ' + got);
    }

    // The mask is fixed, never derived from the secret's length.
    assert(r.redact('/token set a') === r.redact('/token set ' + 'a'.repeat(5000)),
      'the mask length depends on the secret');
    // Idempotent.
    const once = r.redact('/token set ' + SECRET);
    assert(r.redact(once) === once, 'redaction is not idempotent');
  }

  // --- 1b: the rule follows the DATA, not the name ---
  {
    const flipped = JSON.parse(JSON.stringify(PAYLOAD));
    for (const c of flipped.commands) {
      if (c.name === 'token') {
        for (const s of c.subcommands) s.sensitive = (s.name === 'status');
      }
    }
    const r = new CommandRoster(makeApi({payload: flipped}), 'web');
    await r.load();
    assert(r.isSensitive('/token set ' + SECRET) === false,
      'un-flagging `set` in the roster did not un-flag it on the client');
    assert(r.isSensitive('/token status ' + SECRET) === true,
      'flagging `status` in the roster did not flag it on the client');
    assert(r.redact('/token status ' + SECRET) === '/token status ' + M,
      'redaction did not follow the flipped flag');
  }

  // --- 2: FAIL CLOSED with no roster ---
  {
    const api = makeApi({rosterFails: true});
    const r = new CommandRoster(api, 'web');
    await r.load();
    assert(r.isLoaded() === false, 'the roster reported loaded after a failed fetch');

    // ANY slash command's args count as secret; the command NAME is kept.
    assert(r.redact('/token set ' + SECRET) === '/token ' + M,
      'no-roster redaction kept more than the command name');
    assert(r.redact('/show /etc/hosts') === '/show ' + M,
      'no-roster mode spared a command it cannot classify');
    assert(r.isSensitive('/token status') === true,
      'no-roster mode treated a slash command with args as safe');
    // ...but a bare command name is not a secret, so completing the NAME
    // still works even with no roster.
    assert(r.isSensitive('/tok') === false, 'no-roster mode blocked name completion');
    assert(r.isSensitive('/') === false, 'no-roster mode blocked the bare slash');
    // ...and plain chat is never touched, roster or no roster.
    assert(r.isSensitive('hello there') === false, 'plain chat classed as sensitive');
    assert(r.redact('hello /token set x') === 'hello /token set x',
      'no-roster mode mangled plain chat');

    // The instance-free form used when there is no roster OBJECT at all.
    assert(CommandRoster.redactWithoutRoster('/token set ' + SECRET) === '/token ' + M,
      'the instance-free fail-closed redaction disagrees');
  }

  // --- 3: nothing raises on odd input ---
  {
    const api = makeApi();
    const r = new CommandRoster(api, 'web');
    const odd = ['', ' ', '\t', '\n', '/', '//', '>', '> ', '>>>',
                 '/token set x', '/tökèn set x', '/токен сет x',
                 '/token set \u0000', '/token set 🔑🔑', '‮/token set x',
                 '/' + 'a'.repeat(10000) + ' set x', '/token set ' + 'x'.repeat(100000),
                 '> '.repeat(500) + '/token set x', '🔑', '/🔑 set x',
                 null, undefined, 42, {}, []];
    for (const pass of [0, 1]) {
      if (pass === 1) await r.load();
      for (const t of odd) {
        let out, sens;
        try { out = r.redact(t); sens = r.isSensitive(t); }
        catch (e) { throw new Error('FAIL: threw on ' + JSON.stringify(t) + ': ' + e.message); }
        assert(typeof sens === 'boolean', 'isSensitive returned a non-boolean');
        if (typeof t === 'string') assert(typeof out === 'string', 'redact lost the string');
      }
    }
  }

  // --- 4: the DISPATCHER echo is redacted (the leak this step closes) ---
  {
    const api = makeApi();
    const app = makeApp(api);
    await app.commandRoster.load();
    api.calls.length = 0;

    await app.commandDispatcher.dispatch('/token set ' + SECRET);

    const echo = app._msgs[0];
    assert(echo === '> /token set ' + M,
      'the chat echo was not redacted: ' + JSON.stringify(echo));
    assert(!leaks(api, SECRET),
      'the secret left the page: ' + JSON.stringify(api.calls));
    const clientlogs = api.calls.filter((c) => c.kind === 'clientlog');
    assert(clientlogs.length > 0, 'the echo mirror did not run — test proves nothing');
    assert(!clientlogs.some((c) => c.body.message.includes(SECRET)),
      'the secret reached POST /client-log');
    // The command still WORKED — redaction is not refusal.
    assert(api.apiToken === SECRET, 'the token was not stored client-side');
    // ...and the harmless form is untouched.
    await app.commandDispatcher.dispatch('/token status');
    assert(app._msgs.some((m) => m === '> /token status'),
      'a harmless echo was redacted: ' + JSON.stringify(app._msgs));
  }

  // --- 5: the echo is redacted with NO roster too (fail closed) ---
  {
    const api = makeApi({rosterFails: true});
    const app = makeApp(api);
    await app.commandRoster.load();
    api.calls.length = 0;

    await app.commandDispatcher.dispatch('/token set ' + SECRET);

    assert(app._msgs[0] === '> /token ' + M,
      'the no-roster echo was not redacted: ' + JSON.stringify(app._msgs[0]));
    assert(!leaks(api, SECRET),
      'FAIL-OPEN: the secret left the page with no roster: ' + JSON.stringify(api.calls));
    assert(app._errors.some((e) => /skew/i.test(e)), 'the fail-closed refusal is missing');
  }

  console.log("ALL OK");
})().catch((e) => { console.error(e.message || e); process.exit(1); });
"""


def _run(dispatcher: Path = DISPATCHER, roster: Path = ROSTER):
    env = dict(os.environ)
    env["PPXAI_DISPATCHER"] = str(dispatcher)
    env["PPXAI_ROSTER"] = str(roster)
    env["PPXAI_SIDE_EFFECTS"] = str(SIDE_EFFECTS)
    return subprocess.run(
        [NODE, "-e", _HARNESS], capture_output=True, text=True, timeout=60, env=env
    )


def _mutant(tmp_path: Path, source: Path, old: str, new: str) -> Path:
    """Write a scratch copy of `source` with `old` replaced.

    The repo copy is never touched; the mutant lives in pytest's tmp dir
    and is discarded with it.
    """
    src = source.read_text(encoding="utf-8")
    assert old in src, (
        f"mutation anchor not found in {source.name} — this mutation test "
        "is stale and is no longer proving anything"
    )
    path = tmp_path / source.name
    path.write_text(src.replace(old, new, 1), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The real modules
# ---------------------------------------------------------------------------

def test_sensitivity_is_roster_driven_and_fails_closed():
    proc = _run()
    assert proc.returncode == 0, (
        f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    assert "ALL OK" in proc.stdout, proc.stdout


# ---------------------------------------------------------------------------
# Mutation verification
# ---------------------------------------------------------------------------

_ECHO_CALL = "this.app.showSystemMessage(`> ${this._redactEcho(input)}`);"

_FAIL_CLOSED = "        if (!this._loaded) return { sensitive: true, cut: parsed.nameEnd };"


class TestMutationEchoRedaction:
    def test_an_unredacted_echo_is_caught(self, tmp_path):
        """The pre-fix behaviour, reproduced: the raw `> <input>` echo,
        which `showSystemMessage` mirrors to POST /client-log."""
        mutant = _mutant(
            tmp_path, DISPATCHER, _ECHO_CALL,
            "this.app.showSystemMessage(`> ${input}`);",
        )
        proc = _run(dispatcher=mutant)
        assert proc.returncode != 0, (
            "the echo-redaction scenario PASSED against a dispatcher that echoes "
            f"the raw input — the test proves nothing.\nSTDOUT: {proc.stdout}"
        )
        assert "not redacted" in proc.stderr or "reached POST /client-log" in proc.stderr, (
            proc.stderr
        )


class TestMutationFailClosed:
    def test_failing_open_with_no_roster_is_caught(self, tmp_path):
        """An unloaded roster that answers "not sensitive" is fail-OPEN:
        every slash command's args would be echoed and logged verbatim
        exactly when the client cannot classify them."""
        mutant = _mutant(
            tmp_path, ROSTER, _FAIL_CLOSED,
            "        if (!this._loaded) return { sensitive: false, cut: -1 };",
        )
        proc = _run(roster=mutant)
        assert proc.returncode != 0, (
            "the fail-closed scenario PASSED against a roster that fails open.\n"
            f"STDOUT: {proc.stdout}"
        )
        assert "FAIL" in proc.stderr, proc.stderr

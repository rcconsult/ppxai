"""Behavioral tests for the roster-driven VSCode router (ADR 0007 step 3b).

The other VSCode tests in this repo read source text — `npm run compile`
typechecks and the fences pin cross-client contracts. These do something
the repo had not done before: they **compile the real TypeScript and run
it under Node**, the way `tests/test_web_command_roster_dispatch_behavior
.py` drives the real web dispatcher.

That is possible because `src/commandRoster.ts` and `src/commandRouter.ts`
import **no `vscode` module** — the same IoC shape as `taskController.ts`.
`vscode-extension/node_modules/.bin/esbuild` bundles them (plus
`sideEffectsHandler.ts`, whose one `vscode` import is aliased to a stub)
into a scratch CommonJS file in pytest's tmp dir; nothing is written to
the repo and no `npm` script is invoked.

What is pinned, and why a source read could not see it:

  1. **Routing is DATA.** Each of the eight `client_action` names the
     server declares for vscode — `token.manage`, `task.controller`,
     `run.controller`, `auto.loop`, `coding.stream`, `coding.convert`,
     `preview.panel`, `help.augment` — reaches its bundled implementation
     because the ROSTER says `dispatch === "client"`. Flip the roster and
     the routing flips.
  2. **`coding.stream` is ONE action shared by SIX commands** and the
     implementation receives the resolved CANONICAL name — which is what
     replaced `CHAT_SHAPED_TASKS`' router role. Aliases resolve too
     (`/gen` -> `generate`), which the deleted Map could not do.
  3. **Server dispatch carries `client: "vscode"`**, which is what lets
     the server stop over-listing `/help` for the web+vscode union.
  4. **An action the roster names that this client does not implement is
     an ERROR, never a silent forward.**
  5. **The five acknowledged-legacy intercepts still work** — and only
     after the fail-closed gate.
  6. **FAIL CLOSED.** With NO roster, `/token set <secret>` reaches no
     network call at all, the secret is in no payload, the echo is
     masked and the raw line is purged from the ↑ history. The extension
     and `ppxai-server` version independently, so a 404 on
     `GET /commands` is a realistic production state.
  7. **The redaction truth table is identical to Python's**
     `CommandFactory.redact_sensitive` — compared case by case against
     the real function, over the real `CommandFactory.roster("vscode")`
     payload, rather than restated by hand.
  8. **`refresh_command_roster` reaches the host**, so `/reload` refetches.

(6) and the never-POST half of (1) are MUTATION-VERIFIED: a scratch copy
of the TypeScript with the behaviour removed is compiled and the same
harness must FAIL against it.

Skips cleanly where Node or the extension's esbuild is unavailable (same
env contract as tests/test_agent_run_controller_behavior.py).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import ppxai.commands.handler  # noqa: F401  (populates CommandFactory)
from ppxai.commands.factory import CommandFactory

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "vscode-extension"
SRC = EXT / "src"
ESBUILD = EXT / "node_modules" / ".bin" / "esbuild"
NODE = shutil.which("node")

#: The modules bundled for the harness. The first two are `vscode`-free
#: by design; the third needs the stub below.
_MODULES = ("commandRoster.ts", "commandRouter.ts", "sideEffectsHandler.ts")

pytestmark = pytest.mark.skipif(
    NODE is None or not ESBUILD.exists(),
    reason="node and vscode-extension/node_modules/.bin/esbuild are required",
)

MASK = "••••"

_VSCODE_STUB = """
const noop = () => undefined;
module.exports = {
    Uri: { file: (p) => ({ fsPath: p, toString: () => p }) },
    window: {
        showInformationMessage: noop, showWarningMessage: noop,
        showErrorMessage: noop, showQuickPick: async () => undefined,
        showInputBox: async () => undefined,
        createTerminal: () => ({ show: noop, sendText: noop }),
        showTextDocument: async () => ({}),
    },
    workspace: { openTextDocument: async () => ({}), workspaceFolders: undefined },
    commands: { executeCommand: async () => undefined },
    env: { clipboard: { writeText: async () => undefined },
           openExternal: async () => undefined },
    ViewColumn: { One: 1, Two: 2 },
    ThemeIcon: function ThemeIcon() {},
    Position: function Position() {},
    Range: function Range() {},
    Selection: function Selection() {},
    TextEditorRevealType: { InCenter: 2 },
};
"""

_ENTRY = """
export * from './commandRoster';
export * from './commandRouter';
export { SideEffectsHandler, KIND } from './sideEffectsHandler';
"""


def _bundle(tmp_path: Path, mutations: dict[str, tuple[str, str]] | None = None) -> Path:
    """Compile the real TS modules into a scratch CJS bundle.

    `mutations` maps a module filename to an (old, new) source
    replacement applied to the COPY — the repo files are never touched.
    A missing anchor fails loudly, so a stale mutation cannot quietly
    stop proving anything.
    """
    work = tmp_path / "bundle-src"
    work.mkdir(parents=True, exist_ok=True)
    for name in _MODULES:
        text = (SRC / name).read_text(encoding="utf-8")
        if mutations and name in mutations:
            old, new = mutations[name]
            assert old in text, (
                f"mutation anchor not found in {name} — this mutation test is "
                "stale and is no longer proving anything"
            )
            text = text.replace(old, new, 1)
        (work / name).write_text(text, encoding="utf-8")
    (work / "vscodeStub.js").write_text(_VSCODE_STUB, encoding="utf-8")
    (work / "entry.ts").write_text(_ENTRY, encoding="utf-8")
    out = tmp_path / "bundle.js"
    proc = subprocess.run(
        [
            str(ESBUILD), str(work / "entry.ts"), "--bundle", "--format=cjs",
            "--platform=node", "--target=node18",
            f"--alias:vscode={work / 'vscodeStub.js'}",
            f"--outfile={out}",
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"esbuild failed:\n{proc.stderr}"
    return out


# ---------------------------------------------------------------------------
# Harness 1 — routing, fail-closed, legacy, side effect
# ---------------------------------------------------------------------------

_HARNESS = r"""
const B = require(process.env.PPXAI_BUNDLE);
const { CommandRoster, buildCommandRouter, CLIENT_ACTIONS, LEGACY_INTERCEPTS,
        LEGACY_HANDLERS, SideEffectsHandler } = B;
const MASK = '••••';

// The REAL CommandFactory.roster('vscode') payload, handed over by the
// Python side — so the harness routes on what the server actually serves.
const REAL = JSON.parse(process.env.PPXAI_ROSTER_PAYLOAD);

function assert(cond, msg) { if (!cond) throw new Error('FAIL: ' + msg); }

function makeBackend(opts) {
    opts = opts || {};
    const backend = {
        calls: [],
        fails: !!opts.fails,
        payload: opts.payload || REAL,
        async getCommandRoster(client) {
            backend.calls.push({kind: 'roster', method: 'GET',
                                url: '/commands', client});
            if (backend.fails) {
                const e = new Error('GET /commands failed: 404 Not Found');
                e.status = 404; throw e;
            }
            return backend.payload;
        },
    };
    return backend;
}

function makeOps(backend) {
    const ops = {
        ran: [], echoes: [], errors: [], forgotten: [], stored: null,
        handleToken(args) {
            ops.ran.push(['token.manage', args]);
            // The real handler stores the value client-side; model that so
            // "no POST" and "was it stored" are distinguishable.
            const parts = args.trim().split(/\s+/);
            if (parts[0] === 'set' && parts[1]) { ops.stored = parts.slice(1).join(' '); }
        },
        handleTask(args) { ops.ran.push(['task.controller', args]); },
        handleRun(args) { ops.ran.push(['run.controller', args]); },
        handleAuto(argv) { ops.ran.push(['auto.loop', argv.join(' ')]); },
        handleCodingTask(taskType, content) {
            ops.ran.push(['coding.stream', taskType, content]);
        },
        handleConvert(argv) { ops.ran.push(['coding.convert', argv.join(' ')]); },
        handlePreview(argv) { ops.ran.push(['preview.panel', argv.join(' ')]); },
        showHelp(args) { ops.ran.push(['help.augment', args]); },
        handleTools(argv) { ops.ran.push(['legacy:tools', argv.join(' ')]); },
        handleCheckpoint(argv) { ops.ran.push(['legacy:checkpoint', argv.join(' ')]); },
        handleContext(argv) { ops.ran.push(['legacy:context', argv.join(' ')]); },
        handleLs(argv) { ops.ran.push(['legacy:ls', argv.join(' ')]); },
        handleTree(argv) { ops.ran.push(['legacy:tree', argv.join(' ')]); },
        echo(text, sensitive, raw) {
            ops.echoes.push(text);
            if (sensitive) { ops.forgotten.push(raw); }
        },
        showError(message) { ops.errors.push(message); },
        async dispatchToFactory(name, args) {
            backend.calls.push({kind: 'command', method: 'POST',
                                url: '/command/' + name,
                                body: {args, client: 'vscode'}});
        },
    };
    return ops;
}

function make(opts) {
    const backend = makeBackend(opts);
    const roster = new CommandRoster(backend, 'vscode');
    const ops = makeOps(backend);
    return {backend, roster, ops, router: buildCommandRouter(roster, ops)};
}

function posts(backend) { return backend.calls.filter((c) => c.method === 'POST'); }
function leaks(backend, needle) {
    return backend.calls.some((c) => JSON.stringify(c).includes(needle));
}
function ranNames(ops) { return ops.ran.map((r) => r[0]); }

(async () => {
  // --- 0: the registry implements exactly the declared vocabulary ---
  {
    const declared = JSON.parse(process.env.PPXAI_VSCODE_ACTIONS);
    const impl = Object.keys(CLIENT_ACTIONS).sort();
    assert(JSON.stringify(impl) === JSON.stringify(declared.sort()),
      'CLIENT_ACTIONS != the actions Python declares for vscode: impl=' +
      JSON.stringify(impl) + ' declared=' + JSON.stringify(declared));
    assert(JSON.stringify(Object.keys(LEGACY_HANDLERS).sort()) ===
           JSON.stringify([...LEGACY_INTERCEPTS].sort()),
      'LEGACY_HANDLERS keys != LEGACY_INTERCEPTS');
  }

  // --- 1: every declared client action is routed by the roster ---
  {
    const {backend, roster, ops} = make();
    await roster.load();
    const before = backend.calls.length;
    const router = buildCommandRouter(roster, ops);

    await router.route('/token status');
    await router.route('/task ls --json');
    await router.route('/run ls');
    await router.route('/auto on');
    await router.route('/convert python rust @a.py');
    await router.route('/preview index.html');
    await router.route('/help');

    const after = backend.calls.slice(before);
    assert(after.length === 0,
      'a dispatch==="client" command hit the network: ' + JSON.stringify(after));
    for (const name of ['token.manage', 'task.controller', 'run.controller',
                        'auto.loop', 'coding.convert', 'preview.panel',
                        'help.augment']) {
      assert(ranNames(ops).includes(name), name + ' impl not reached');
    }
    const taskArgs = ops.ran.find((r) => r[0] === 'task.controller')[1];
    assert(taskArgs === 'ls --json', 'arg string not forwarded verbatim: ' + taskArgs);
  }

  // --- 2: coding.stream — ONE action, SIX commands, canonical name ---
  {
    const {backend, roster, ops} = make();
    await roster.load();
    const router = buildCommandRouter(roster, ops);
    const six = ['generate', 'explain', 'test', 'docs', 'debug', 'implement'];
    for (const cmd of six) { await router.route('/' + cmd + ' do the thing'); }
    const seen = ops.ran.filter((r) => r[0] === 'coding.stream');
    assert(seen.length === 6,
      'expected six coding.stream dispatches, got ' + seen.length +
      ': ' + JSON.stringify(ops.ran));
    assert(JSON.stringify(seen.map((r) => r[1])) === JSON.stringify(six),
      'coding.stream did not receive the resolved command name: ' +
      JSON.stringify(seen.map((r) => r[1])));
    assert(seen.every((r) => r[2] === 'do the thing'),
      'coding.stream args mangled: ' + JSON.stringify(seen));
    assert(posts(backend).length === 0, 'a coding command was POSTed');

    // ...and ALIASES reach it too, resolving to the canonical name. The
    // deleted CHAT_SHAPED_TASKS map keyed on canonical names only, so
    // /gen and /impl silently fell through to the factory.
    ops.ran.length = 0;
    await router.route('/gen a helper');
    await router.route('/impl the parser');
    assert(JSON.stringify(ops.ran) ===
           JSON.stringify([['coding.stream', 'generate', 'a helper'],
                           ['coding.stream', 'implement', 'the parser']]),
      'aliases did not resolve to the canonical coding command: ' +
      JSON.stringify(ops.ran));
  }

  // --- 3: routing follows the DATA, not the name ---
  {
    const flipped = JSON.parse(process.env.PPXAI_ROSTER_PAYLOAD);
    for (const c of flipped.commands) {
      if (c.name === 'task') { c.dispatch = 'server'; c.client_action = null; }
    }
    const {backend, roster, ops} = make({payload: flipped});
    await roster.load();
    const router = buildCommandRouter(roster, ops);
    await router.route('/task ls');
    const cmds = backend.calls.filter((c) => c.kind === 'command');
    assert(cmds.length === 1 && cmds[0].url === '/command/task',
      'flipping the roster did not flip routing: ' + JSON.stringify(backend.calls));
    assert(ops.ran.length === 0, 'client impl ran despite dispatch==="server"');
  }

  // --- 4: alias resolution + canonical name + client:"vscode" body ---
  {
    const {backend, roster, ops} = make();
    await roster.load();
    const router = buildCommandRouter(roster, ops);
    await router.route('/cat /tmp/x.txt');
    const cmds = backend.calls.filter((c) => c.kind === 'command');
    assert(cmds.length === 1, 'expected exactly one command POST, got ' + cmds.length);
    assert(cmds[0].url === '/command/show',
      'alias /cat did not resolve to canonical show: ' + cmds[0].url);
    assert(cmds[0].body.args === '/tmp/x.txt', 'args mangled: ' + cmds[0].body.args);
    assert(cmds[0].body.client === 'vscode', 'POST body is missing client:"vscode"');
  }

  // --- 5: an action the roster names but this client does not implement ---
  {
    const grown = JSON.parse(process.env.PPXAI_ROSTER_PAYLOAD);
    grown.commands.push({name: 'future', aliases: [], description: 'x',
                         usage: '/future', category: 'other', hidden: false,
                         subcommands: [], clients: null,
                         client_action: 'future.thing',
                         client_action_clients: ['vscode'],
                         client_handled: true, dispatch: 'client'});
    const {backend, roster, ops} = make({payload: grown});
    await roster.load();
    const router = buildCommandRouter(roster, ops);
    await router.route('/future whatever');
    assert(posts(backend).length === 0,
      'an unimplemented client action was silently forwarded: ' +
      JSON.stringify(posts(backend)));
    assert(ops.errors.some((m) => /future\.thing/.test(m)),
      'no clear error naming the unimplemented action: ' + JSON.stringify(ops.errors));
  }

  // --- 6: the five acknowledged-legacy intercepts still work ---
  {
    const {backend, roster, ops} = make();
    await roster.load();
    const router = buildCommandRouter(roster, ops);
    for (const name of LEGACY_INTERCEPTS) { await router.route('/' + name + ' status'); }
    assert(JSON.stringify(ranNames(ops)) ===
           JSON.stringify(LEGACY_INTERCEPTS.map((n) => 'legacy:' + n)),
      'the legacy five were not intercepted: ' + JSON.stringify(ops.ran));
    assert(posts(backend).length === 0, 'a legacy command was POSTed to the factory');
    assert(ops.ran.every((r) => r[1] === 'status'), 'legacy argv mangled');
  }

  // --- 7: NO ROSTER -> fail closed, zero leakage, nothing remembered ---
  {
    const SECRET = 'TOP-SECRET-42';
    const {backend, roster, ops} = make({fails: true});
    const ok = await roster.load();
    assert(ok === false, 'load() reported success despite a failing fetch');
    backend.calls.length = 0;
    const router = buildCommandRouter(roster, ops);

    await router.route('/token set ' + SECRET);

    assert(posts(backend).length === 0,
      'FAIL-OPEN: a request was issued with no roster: ' + JSON.stringify(backend.calls));
    assert(!leaks(backend, SECRET),
      'the secret appeared in an outgoing request with no roster');
    const nonRoster = backend.calls.filter((c) => c.kind !== 'roster');
    assert(nonRoster.length === 0,
      'with no roster the only permitted call is the roster retry; got ' +
      JSON.stringify(nonRoster));
    assert(backend.calls.filter((c) => c.kind === 'roster').length === 1,
      'the router did not retry the roster fetch');
    assert(ops.stored === null, 'the secret was stored despite the refusal');
    assert(ops.ran.length === 0, 'a client action ran with no roster');
    assert(ops.echoes[0] === '/token ' + MASK,
      'the no-roster echo was not masked: ' + JSON.stringify(ops.echoes[0]));
    assert(ops.forgotten[0] === '/token set ' + SECRET,
      'the raw line was not purged from the input history');
    const err = ops.errors.join('\n');
    assert(/skew/i.test(err), 'the refusal does not name the version-skew possibility');
    assert(/ppxai-server/.test(err), 'the refusal does not name the server binary');

    // Fail closed means CLOSED: a plain server command, a legacy
    // intercept and a chat-shaped command are all refused too.
    await router.route('/status');
    await router.route('/tools status');
    await router.route('/explain this code');
    assert(posts(backend).length === 0, 'a command was forwarded with no roster');
    assert(ops.ran.length === 0, 'an implementation ran with no roster');
  }

  // --- 8: self-heal once the server comes back ---
  {
    const {backend, roster, ops} = make({fails: true});
    await roster.load();
    backend.fails = false;
    const router = buildCommandRouter(roster, ops);
    await router.route('/status');
    const cmds = backend.calls.filter((c) => c.kind === 'command');
    assert(cmds.length === 1 && cmds[0].url === '/command/status',
      'the router did not self-heal once the roster became reachable');
  }

  // --- 9: unload() reverts to fail-closed (server stopped) ---
  {
    const {backend, roster, ops} = make();
    await roster.load();
    roster.unload();
    assert(!roster.isLoaded(), 'unload() left the roster loaded');
    backend.fails = true;
    backend.calls.length = 0;
    const router = buildCommandRouter(roster, ops);
    await router.route('/token set AFTER-DISCONNECT');
    assert(!leaks(backend, 'AFTER-DISCONNECT'),
      'a dropped roster still forwarded a secret');
    assert(ops.errors.length > 0, 'no refusal after unload()');
  }

  // --- 10: refresh_command_roster reaches the host (the /reload signal) ---
  {
    const got = [];
    const handler = new SideEffectsHandler({
        getWorkingDirHint: () => undefined,
        openHtmlPreviewFromSideEffect: () => {},
        postToWebview: () => {},
        dispatchCommandFromSideEffect: async () => {},
        refreshCommandRoster: (version) => { got.push(version); },
    });
    await handler.apply([{kind: 'refresh_command_roster', version: 9}]);
    assert(JSON.stringify(got) === '[9]',
      'refresh_command_roster did not reach the host: ' + JSON.stringify(got));

    // ...and a roster that refetches keeps working; a FAILED refresh
    // keeps the roster it already had (no downgrade to fail-closed).
    const {backend, roster} = make();
    await roster.load();
    const v = roster.version;
    backend.fails = true;
    const still = await roster.load();
    assert(still === true, 'a failed refresh un-loaded a working roster');
    assert(roster.isLoaded() && roster.version === v,
      'a failed refresh corrupted the held roster');
  }

  console.log("ALL OK");
})().catch((e) => { console.error(e.message || e); process.exit(1); });
"""


# ---------------------------------------------------------------------------
# Harness 2 — the redaction truth table, compared against Python
# ---------------------------------------------------------------------------

_TRUTH_HARNESS = r"""
const { CommandRoster } = require(process.env.PPXAI_BUNDLE);
const payload = JSON.parse(process.env.PPXAI_ROSTER_PAYLOAD);
const cases = JSON.parse(process.env.PPXAI_CASES);

const loaded = new CommandRoster({async getCommandRoster() { return payload; }}, 'vscode');
const out = {loaded: [], unloaded: [], noInstance: []};

(async () => {
  await loaded.load();
  const empty = new CommandRoster({async getCommandRoster() { throw new Error('x'); }}, 'vscode');
  await empty.load();
  for (const c of cases) {
    out.loaded.push(loaded.redact(c));
    out.unloaded.push(empty.redact(c));
    out.noInstance.push(CommandRoster.redactWithoutRoster(c));
  }
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e.message || e); process.exit(1); });
"""


def _roster_payload() -> str:
    return json.dumps(CommandFactory.roster("vscode"))


def _vscode_actions() -> list[str]:
    """Every `client_action` Python declares for the vscode client.

    Read off the registry, not hand-copied — this is a miniature of ADR
    0007 step 5's parity fence, matching what step 3a did for web.
    """
    actions = {
        info.client_action
        for info in CommandFactory.iter_completion_specs()
        if info.client_action
        and (info.client_action_clients is None
             or "vscode" in info.client_action_clients)
        and (info.clients is None or "vscode" in info.clients)
    }
    return sorted(actions)


def _run(bundle: Path, harness: str = _HARNESS, **extra: str):
    env = dict(os.environ)
    env["PPXAI_BUNDLE"] = str(bundle)
    env["PPXAI_ROSTER_PAYLOAD"] = _roster_payload()
    env["PPXAI_VSCODE_ACTIONS"] = json.dumps(_vscode_actions())
    env.update(extra)
    return subprocess.run(
        [NODE, "-e", harness], capture_output=True, text=True, timeout=120, env=env
    )


# ---------------------------------------------------------------------------
# The real modules
# ---------------------------------------------------------------------------

def test_roster_drives_routing_fails_closed_and_refreshes(tmp_path):
    proc = _run(_bundle(tmp_path))
    assert proc.returncode == 0, (
        f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    assert "ALL OK" in proc.stdout, proc.stdout


#: Every decision `CommandFactory.redact_sensitive` makes, plus the odd
#: inputs that must not raise. Compared against the real Python function
#: rather than a restated expectation.
_TRUTH_CASES = [
    "/token set abc",
    "/token set abc def",
    "/TOKEN SET abc",
    "/Token Set AbC",
    "/token\tset\tabc",
    "/token   set   abc",
    "   /token set abc",
    "> /token set abc",
    ">  /token set abc",
    "/token set",
    "/token set   ",
    "/token se",
    "/token status",
    "/token status extra",
    "/token mint",
    "/token clear",
    "/tok set abc",
    "/status",
    "/show /tmp/x",
    "/cat /tmp/x",
    "hello world",
    "just /not a command",
    "",
    "   ",
    "/",
    "/token",
    "/generate write /token set abc",
]


def test_redaction_truth_table_matches_python(tmp_path):
    """The JS rule and `CommandFactory.redact_sensitive` must agree line
    for line, over the roster the server really serves.

    The web client's copy is held to the same reference
    (tests/test_web_sensitive_redaction_behavior.py), so all three
    implementations are pinned to one declaration.
    """
    proc = _run(
        _bundle(tmp_path), harness=_TRUTH_HARNESS,
        PPXAI_CASES=json.dumps(_TRUTH_CASES),
    )
    assert proc.returncode == 0, f"harness failed:\n{proc.stderr}"
    got = json.loads(proc.stdout)
    expected = [CommandFactory.redact_sensitive(c) for c in _TRUTH_CASES]
    mismatches = [
        (case, py, js)
        for case, py, js in zip(_TRUTH_CASES, expected, got["loaded"])
        if py != js
    ]
    assert not mismatches, (
        "the VSCode redaction rule disagrees with CommandFactory."
        f"redact_sensitive: {mismatches}"
    )


def test_multi_slash_is_masked_more_aggressively_than_python(tmp_path):
    """A deliberate, fail-SAFE divergence — found while writing this test,
    and true of the web client too.

    `//token set abc` is left alone by `CommandFactory.redact_sensitive`
    (its parsed name is `/token`, which resolves to nothing). Both JS
    clients strip leading slashes in `resolve()`, so they mask it — and
    they are right to, because they also ROUTE it: `route()` strips the
    same slashes, so `//token set abc` really does reach `token.manage`
    and store the value. The client masking a line the client executes is
    the correct asymmetry; the server-side helper never sees this input
    because a client-dispatched command is never POSTed.
    """
    proc = _run(
        _bundle(tmp_path), harness=_TRUTH_HARNESS,
        PPXAI_CASES=json.dumps(["//token set abc"]),
    )
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)
    assert got["loaded"] == [f"//token set {MASK}"], got
    assert CommandFactory.redact_sensitive("//token set abc") == "//token set abc"


def test_redaction_fails_closed_without_a_roster(tmp_path):
    """With no roster the args of ANY slash command are masked — the
    command NAME survives, so `/tok` is still completable and the
    refusal message can name what it refused."""
    proc = _run(
        _bundle(tmp_path), harness=_TRUTH_HARNESS,
        PPXAI_CASES=json.dumps(_TRUTH_CASES),
    )
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)
    for case, unloaded, no_instance in zip(
        _TRUTH_CASES, got["unloaded"], got["noInstance"]
    ):
        assert unloaded == no_instance, (
            f"an unloaded roster and no roster at all disagree for {case!r}: "
            f"{unloaded!r} vs {no_instance!r}"
        )
        # The parse tolerates the `> ` echo marker, so strip it the same
        # way before deciding what the expectation is.
        body = case.lstrip().lstrip(">").lstrip()
        if body.startswith("/") and len(body.split()) > 1:
            assert MASK in unloaded, f"fail-open with no roster for {case!r}"
        else:
            assert unloaded == case, f"a non-command was altered: {case!r}"


# ---------------------------------------------------------------------------
# Mutation verification — the security scenarios must be able to fail.
# ---------------------------------------------------------------------------

_GATE = """        const roster = await this._readyRoster();
        if (!roster) {
            this._explainMissingRoster(typed);
            return;
        }"""

_CLIENT_BRANCH = "        if (entry && entry.dispatch === 'client') {"

_FAIL_CLOSED_CLASSIFY = (
    "        if (!this._loaded) { return { sensitive: true, cut: parsed.nameEnd }; }"
)


class TestMutationFailClosed:
    def test_removing_the_gate_is_caught(self, tmp_path):
        """Fail OPEN — the gate degrades to an empty roster and the router
        forwards whatever it could not classify. That is the exact
        regression that would POST `/token set <secret>`."""
        bundle = _bundle(tmp_path, {"commandRouter.ts": (
            _GATE,
            "        const roster = (await this._readyRoster()) "
            "|| ({ resolve: () => null } as any);",
        )})
        proc = _run(bundle)
        assert proc.returncode != 0, (
            "the fail-closed scenario PASSED against a router with no gate — "
            f"the test proves nothing.\nSTDOUT: {proc.stdout}"
        )
        assert "FAIL-OPEN" in proc.stderr, proc.stderr


class TestMutationClientDispatchedNeverPosted:
    def test_bypassing_the_client_branch_is_caught(self, tmp_path):
        """A client-dispatched command falling through to the factory POST
        is the "forward it and let the server refuse" posture ADR 0007
        explicitly rejects — the secret is already in the body by then."""
        bundle = _bundle(tmp_path, {"commandRouter.ts": (
            _CLIENT_BRANCH,
            "        if (false && entry && entry.dispatch === 'client') {",
        )})
        proc = _run(bundle)
        assert proc.returncode != 0, (
            "the never-POST scenario PASSED against a router that forwards "
            f"client-dispatched commands.\nSTDOUT: {proc.stdout}"
        )
        assert "hit the network" in proc.stderr, proc.stderr


class TestMutationRedactionFailsClosed:
    def test_classify_failing_open_is_caught(self, tmp_path):
        """An unloaded roster answering "not sensitive" would echo — and
        remember — every slash command's args verbatim exactly when the
        client cannot classify them."""
        bundle = _bundle(tmp_path, {"commandRoster.ts": (
            _FAIL_CLOSED_CLASSIFY,
            "        if (!this._loaded) { return { sensitive: false, cut: -1 }; }",
        )})
        proc = _run(bundle)
        assert proc.returncode != 0, (
            "the no-roster echo scenario PASSED against a roster that fails "
            f"open.\nSTDOUT: {proc.stdout}"
        )
        assert "FAIL" in proc.stderr, proc.stderr

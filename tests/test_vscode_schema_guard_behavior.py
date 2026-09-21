"""Behavioural fence for the VSCode run-time AppState schema check.

Same idiom as `tests/test_vscode_command_roster_behavior.py`: the real
TypeScript is compiled with the extension's own esbuild and driven under
plain Node. That is possible because `src/schemaGuard.ts` and
`src/appState.ts` import no `vscode` module — the host's four editor-side
capabilities (adopt, resetAdopted, log, warnUser) are injected.

What is pinned, and why a source read could not see it
------------------------------------------------------

  1. **Identical is SILENT.** The normal case — a matched extension and
     server — must produce no log line and no notification at all.
  2. **A NEWER server is adopted, not warned about.** Fields the server
     declares and this build does not know get a name-map entry and their
     server-declared default, so a subsequent `updateFromPython` STORES
     them instead of dropping each one with a per-push `console.warn`.
     Exactly one log line, zero user-visible warnings.
  3. **A field this build was COMPILED against going missing — or
     changing type or client name — is the broken guarantee** and is
     surfaced VISIBLY, exactly once, naming the fields and both versions.
  4. **A 404 does not throw and does not block.** The roster fails
     closed; state must not. `AppState` is constructed before a server
     exists and already holds a complete bundled schema, and a server too
     old to serve the endpoint is still a usable server.
  5. **Adoption is per connection.** Reconnecting to a server that does
     NOT declare the adopted field leaves no trace of it — no value, no
     name-map entry, and a push of it warns as unknown again. This is the
     reason the Python→TS map moved from a static to a per-instance one.
  6. **`version` alone is not the verdict.** `ppxai/engine/
     app_state_schema.json` has read `"version": "1.0"` since it was
     created (`86adf127`) and was not bumped by any of the five commits
     that added or changed fields since. A version-only difference is
     therefore treated as identical — and reported in the message when
     something else IS wrong.

(2), (4) and (5) are MUTATION-VERIFIED: a scratch copy of the TypeScript
with the behaviour removed is compiled and the same harness must FAIL.

Skips cleanly where Node or the extension's esbuild is unavailable (same
env contract as tests/test_vscode_command_roster_behavior.py).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "vscode-extension"
SRC = EXT / "src"
ESBUILD = EXT / "node_modules" / ".bin" / "esbuild"
NODE = shutil.which("node")
CANONICAL = ROOT / "ppxai" / "engine" / "app_state_schema.json"

#: Bundled together because `appState.ts` is half the behaviour under test
#: (adoption, reset, updateFromPython) and `schemaGuard.ts` is the other.
_MODULES = (
    "appState.ts",
    "appState.generated.ts",
    "appStateTypes.ts",
    "schemaGuard.ts",
)

pytestmark = pytest.mark.skipif(
    NODE is None or not ESBUILD.exists(),
    reason="node and vscode-extension/node_modules/.bin/esbuild are required",
)

_ENTRY = """
export { AppState } from './appState';
export { SchemaGuard, compareSchemas, describeIncompatibility } from './schemaGuard';
"""


def _bundle(tmp_path: Path, mutations: dict[str, tuple[str, str]] | None = None) -> Path:
    """Compile the real TS modules into a scratch CJS bundle.

    The bundle lands in `<tmp>/out/` and the canonical schema is copied to
    `<tmp>/resources/` so `appState.ts::_loadSchema` — which resolves
    `__dirname/../resources/app-state-schema.json` — finds it exactly the
    way it does inside an installed extension.

    `mutations` maps a module filename to an (old, new) source replacement
    applied to the COPY — the repo files are never touched. A missing
    anchor fails loudly, so a stale mutation cannot quietly stop proving
    anything.
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
    (work / "entry.ts").write_text(_ENTRY, encoding="utf-8")

    resources = tmp_path / "resources"
    resources.mkdir(parents=True, exist_ok=True)
    (resources / "app-state-schema.json").write_bytes(CANONICAL.read_bytes())

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "bundle.js"
    proc = subprocess.run(
        [
            str(ESBUILD), str(work / "entry.ts"), "--bundle", "--format=cjs",
            "--platform=node", "--target=node18", f"--outfile={out}",
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"esbuild failed:\n{proc.stderr}"
    return out


_HARNESS = r"""
const B = require(process.env.PPXAI_BUNDLE);
const { AppState, SchemaGuard, compareSchemas } = B;

const CANONICAL = JSON.parse(process.env.PPXAI_CANONICAL_SCHEMA);

function assert(cond, msg) { if (!cond) throw new Error('FAIL: ' + msg); }
function clone(o) { return JSON.parse(JSON.stringify(o)); }

/** A server schema built by mutating a copy of the canonical one. */
function serverSchema(mutate) {
    const s = clone(CANONICAL);
    if (mutate) { mutate(s); }
    return s;
}

function make(served) {
    const state = new AppState();
    const host = {
        logs: [], warns: [], resets: 0, adoptCalls: 0,
        adopt(fields) { host.adoptCalls++; return state.adoptFields(fields); },
        resetAdopted() { host.resets++; state.resetAdoptedFields(); },
        log(m) { host.logs.push(m); },
        warnUser(m) { host.warns.push(m); },
        extensionVersion: '1.19.3',
        async serverVersion() { return '1.17.0'; },
    };
    const backend = {
        calls: 0,
        served,
        async getAppStateSchema() {
            backend.calls++;
            if (backend.served instanceof Error) { throw backend.served; }
            return backend.served;
        },
    };
    const guard = new SchemaGuard(backend, AppState.BUNDLED_SCHEMA, host);
    return { state, host, backend, guard };
}

(async () => {

  // --- 1: identical server -> completely silent ------------------------
  {
    const { host, guard } = make(serverSchema());
    const diff = await guard.check();
    assert(diff.verdict === 'identical', 'verdict was ' + diff.verdict);
    assert(host.logs.length === 0, 'a matched pair logged: ' + host.logs.join(' | '));
    assert(host.warns.length === 0, 'a matched pair warned the user');
    assert(host.adoptCalls === 0, 'a matched pair adopted something');
  }

  // --- 2: version differs, fields identical -> still silent ------------
  // The canonical `version` string has never been bumped (see the module
  // docstring); making it the verdict would report nothing at all, and
  // making it a warning would cry wolf on every release.
  {
    const { host, guard } = make(serverSchema((s) => { s.version = '9.9'; }));
    const diff = await guard.check();
    assert(diff.verdict === 'identical',
      'a version-only difference was classified ' + diff.verdict);
    assert(diff.versionDiffers === true, 'versionDiffers was not reported');
    assert(host.warns.length === 0, 'a version-only difference warned the user');
    assert(host.logs.length === 0, 'a version-only difference logged');
  }

  // --- 3: NEWER server -> adopted, one log, no user warning ------------
  {
    const served = serverSchema((s) => {
      s.fields.brand_new_thing = {
        client: 'brandNewThing', type: 'string', default: 'seed',
        group: 'core', doc: 'from a newer server',
      };
    });
    const { state, host, guard } = make(served);
    const diff = await guard.check();

    assert(diff.verdict === 'extra-only', 'verdict was ' + diff.verdict);
    assert(JSON.stringify(diff.extra) === '["brand_new_thing"]',
      'extra was ' + JSON.stringify(diff.extra));
    assert(diff.missing.length === 0 && diff.changed.length === 0,
      'a purely additive server was also reported as broken');
    assert(host.warns.length === 0,
      'harmless skew produced a USER-VISIBLE warning: ' + host.warns.join(' | '));
    assert(host.logs.length === 1,
      'expected exactly one log, got ' + host.logs.length + ': ' + host.logs.join(' | '));
    assert(host.logs[0].includes('brand_new_thing'),
      'the log does not name the field: ' + host.logs[0]);

    // The adopted field must now be STORED, not dropped with a warning.
    assert(state.adoptedFields().indexOf('brandNewThing') !== -1,
      'adoptedFields() does not list it: ' + JSON.stringify(state.adoptedFields()));
    assert(state.getRaw('brandNewThing') === 'seed',
      'the server-declared default was not seeded: ' + state.getRaw('brandNewThing'));
    state.updateFromPython({ provider: 'openai', brand_new_thing: 'pushed' });
    assert(state.get('currentProvider') === 'openai', 'known field broke');
    assert(state.getRaw('brandNewThing') === 'pushed',
      'updateFromPython DROPPED the adopted field: ' + state.getRaw('brandNewThing'));
    assert(state.snapshot().brandNewThing === 'pushed',
      'snapshot() does not carry the adopted field');

    // A second check inside the same connection must not re-announce.
    await guard.check();
    assert(host.logs.length === 1,
      'a second check in the same connection logged again: ' + host.logs.length);
  }

  // --- 4: OLDER server, compiled-against field missing -> visible ------
  {
    const served = serverSchema((s) => {
      delete s.fields.model_supports_vision;
      delete s.fields.last_message_role;
    });
    const { host, guard } = make(served);
    const diff = await guard.check();

    assert(diff.verdict === 'incompatible', 'verdict was ' + diff.verdict);
    assert(JSON.stringify(diff.missing) ===
           JSON.stringify(['last_message_role', 'model_supports_vision']),
      'missing was ' + JSON.stringify(diff.missing));
    assert(host.warns.length === 1,
      'expected exactly one user-visible warning, got ' + host.warns.length);
    const w = host.warns[0];
    assert(w.includes('last_message_role') && w.includes('model_supports_vision'),
      'the warning does not name the fields: ' + w);
    assert(w.includes('1.19.3'), 'the warning does not name the extension version: ' + w);
    assert(w.includes('1.17.0'), 'the warning does not name the server version: ' + w);
    assert(host.logs.length === 1, 'the warning was not also logged');

    // Once per connection, not once per check.
    await guard.check();
    assert(host.warns.length === 1,
      'a second check re-warned the user: ' + host.warns.length);
    // ...until the connection boundary re-arms it.
    guard.reset();
    await guard.check();
    assert(host.warns.length === 2,
      'a NEW connection did not re-warn: ' + host.warns.length);
  }

  // --- 5: retyped / renamed compiled-against field -> visible ----------
  {
    const served = serverSchema((s) => {
      s.fields.estimated_cost.type = 'string';
      s.fields.session_name.client = 'sessionTitle';
    });
    const { host, guard } = make(served);
    const diff = await guard.check();
    assert(diff.verdict === 'incompatible', 'verdict was ' + diff.verdict);
    const names = diff.changed.map((c) => c.field).sort();
    assert(JSON.stringify(names) === '["estimated_cost","session_name"]',
      'changed was ' + JSON.stringify(names));
    const kinds = {};
    for (const c of diff.changed) { kinds[c.field] = c.what; }
    assert(kinds.estimated_cost === 'type', 'estimated_cost: ' + kinds.estimated_cost);
    assert(kinds.session_name === 'client', 'session_name: ' + kinds.session_name);
    assert(host.warns.length === 1, 'expected one warning, got ' + host.warns.length);
    assert(host.warns[0].includes('estimated_cost')
           && host.warns[0].includes('session_name'),
      'the warning does not name the changed fields: ' + host.warns[0]);
  }

  // --- 6: endpoint missing (404) -> no throw, one log, no warning ------
  {
    const err = new Error('GET /schema/app-state failed: 404 Not Found');
    err.status = 404;
    const { state, host, guard } = make(err);
    let threw = null;
    let diff = null;
    try { diff = await guard.check(); } catch (e) { threw = e; }
    assert(threw === null, 'check() THREW on a 404: ' + threw);
    assert(diff.verdict === 'unverified', 'verdict was ' + diff.verdict);
    assert(host.warns.length === 0,
      'an unverifiable shape produced a user-visible warning: ' + host.warns.join(' | '));
    assert(host.logs.length === 1,
      'expected exactly one log, got ' + host.logs.length);
    assert(host.logs[0].toLowerCase().includes('could not verify'),
      'the log does not say the shape could not be verified: ' + host.logs[0]);
    // State keeps working off the bundled schema.
    state.updateFromPython({ provider: 'perplexity' });
    assert(state.get('currentProvider') === 'perplexity',
      'state stopped working after an unverified check');
  }

  // --- 7: reconnect to a server WITHOUT the extra field ----------------
  {
    const withExtra = serverSchema((s) => {
      s.fields.brand_new_thing = {
        client: 'brandNewThing', type: 'string', default: 'seed',
        group: 'core', doc: 'from a newer server',
      };
    });
    const { state, host, backend, guard } = make(withExtra);
    await guard.check();
    state.updateFromPython({ brand_new_thing: 'pushed' });
    assert(state.getRaw('brandNewThing') === 'pushed', 'setup failed');

    // Connection drops, then comes back on a DIFFERENT server.
    guard.reset();
    assert(state.adoptedFields().length === 0,
      'reset() left adopted fields behind: ' + JSON.stringify(state.adoptedFields()));
    backend.served = serverSchema();
    const diff = await guard.check();

    assert(diff.verdict === 'identical', 'verdict was ' + diff.verdict);
    assert(state.adoptedFields().length === 0,
      'adoption survived a reconnect to a server without the field: '
      + JSON.stringify(state.adoptedFields()));
    assert(state.getRaw('brandNewThing') === undefined,
      'the adopted VALUE survived the reconnect: ' + state.getRaw('brandNewThing'));
    assert(!('brandNewThing' in state.snapshot()),
      'snapshot() still carries the stale adopted field');
    // And the name mapping is gone too: a push is unknown again.
    const mapped = state.updateFromPython({ brand_new_thing: 'again' });
    assert(!('brandNewThing' in mapped),
      'the stale name mapping survived: ' + JSON.stringify(mapped));

    // 7b: the SAME guarantee without an explicit reset() — the server
    // restarted under us on one URL and the panel saw no disconnect. A
    // check() must re-derive adoption from scratch, never accumulate it.
    backend.served = withExtra;
    await guard.check();
    assert(state.getRaw('brandNewThing') === 'seed', '7b setup failed');
    backend.served = serverSchema();
    await guard.check();
    assert(state.adoptedFields().length === 0,
      're-checking against a server without the field left adoption behind: '
      + JSON.stringify(state.adoptedFields()));
    assert(state.getRaw('brandNewThing') === undefined,
      'the adopted value survived a re-check: ' + state.getRaw('brandNewThing'));
  }

  // --- 8: compareSchemas is pure -------------------------------------
  {
    const a = serverSchema();
    const before = JSON.stringify(a);
    compareSchemas(AppState.BUNDLED_SCHEMA, a);
    assert(JSON.stringify(a) === before, 'compareSchemas mutated its input');
    const empty = compareSchemas(null, null);
    assert(empty.verdict === 'identical', 'null/null was ' + empty.verdict);
  }

  console.log('ALL OK');
})().catch((e) => { console.error(e.message); process.exit(1); });
"""


def _run(bundle: Path, harness: str = _HARNESS, **extra: str):
    env = dict(os.environ)
    env["PPXAI_BUNDLE"] = str(bundle)
    env["PPXAI_CANONICAL_SCHEMA"] = CANONICAL.read_text(encoding="utf-8")
    env.update(extra)
    return subprocess.run(
        [NODE, "-e", harness], capture_output=True, text=True, timeout=120, env=env
    )


# ---------------------------------------------------------------------------
# The real modules
# ---------------------------------------------------------------------------

def test_schema_guard_classifies_and_acts(tmp_path):
    proc = _run(_bundle(tmp_path))
    assert proc.returncode == 0, (
        f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    assert "ALL OK" in proc.stdout, proc.stdout


# ---------------------------------------------------------------------------
# Mutations — each removes one behaviour and the harness must reject it
# ---------------------------------------------------------------------------

_FAIL_SOFT = """        } catch (e: any) {
            const message = e?.message ?? String(e);"""

_CLEAR_ADOPTION = "        this._clearAdoption();"

_BROKEN_RULE = (
    "    const broken = missing.length > 0 || changed.length > 0;"
)

_ADOPT_BRANCH = "            const adopted = this._host.adopt(diff.adoptable);"


class TestMutationDoesNotFailClosed:
    def test_throwing_on_a_missing_endpoint_is_caught(self, tmp_path):
        """Failing closed here is the `commandRoster` posture applied where
        it does not belong: an older server that 404s is still a usable
        server, and `AppState` already holds a complete bundled schema."""
        bundle = _bundle(tmp_path, {"schemaGuard.ts": (
            _FAIL_SOFT,
            "        } catch (e: any) {\n            throw e;\n            "
            "const message = e?.message ?? String(e);",
        )})
        proc = _run(bundle)
        assert proc.returncode != 0, (
            "the 404 scenario PASSED against a guard that rethrows — the test "
            f"proves nothing.\nSTDOUT: {proc.stdout}"
        )
        assert "THREW on a 404" in proc.stderr, proc.stderr


class TestMutationAdoptionIsPerConnection:
    def test_not_clearing_adoption_is_caught(self, tmp_path):
        """Without the clear, reconnecting to a server that never declared
        the field leaves it in the store as a ghost of the previous one."""
        bundle = _bundle(tmp_path, {"schemaGuard.ts": (
            _CLEAR_ADOPTION,
            "        // mutation: adoption deliberately not cleared",
        )})
        proc = _run(bundle)
        assert proc.returncode != 0, (
            "the re-check scenario PASSED against a guard that never clears "
            f"adoption.\nSTDOUT: {proc.stdout}"
        )
        assert "left adoption behind" in proc.stderr, proc.stderr

    def test_not_restoring_the_name_map_is_caught(self, tmp_path):
        """Dropping the VALUES but keeping the NAME MAPPING is the subtle
        half: the store looks clean, and then the next server's push of an
        unrelated field lands under a camelCase name this build has no
        type for and nobody declared."""
        bundle = _bundle(tmp_path, {"appState.ts": (
            "        this._adopted = [];\n"
            "        this._pythonToTs = { ...AppState.PYTHON_TO_TS };",
            "        this._adopted = [];",
        )})
        proc = _run(bundle)
        assert proc.returncode != 0, (
            "the reconnect scenario PASSED against an AppState that never "
            f"restores its compile-time name map.\nSTDOUT: {proc.stdout}"
        )
        assert "stale name mapping survived" in proc.stderr, proc.stderr


class TestMutationHarmlessSkewIsNotAnAlarm:
    def test_classifying_extra_fields_as_broken_is_caught(self, tmp_path):
        """A newer server is the ROUTINE skew (a user updates the server
        first). Popping a modal for it trains everyone to dismiss the one
        that matters."""
        bundle = _bundle(tmp_path, {"schemaGuard.ts": (
            _BROKEN_RULE,
            "    const broken = missing.length > 0 || changed.length > 0 "
            "|| extra.length > 0;",
        )})
        proc = _run(bundle)
        assert proc.returncode != 0, (
            "the harmless-skew scenario PASSED against a guard that calls "
            f"extra fields incompatible.\nSTDOUT: {proc.stdout}"
        )
        assert "verdict was incompatible" in proc.stderr, proc.stderr

    def test_not_adopting_extra_fields_is_caught(self, tmp_path):
        """Without adoption, every state_sync carrying the new field logs a
        fresh `unknown field` warning — once per push, forever."""
        bundle = _bundle(tmp_path, {"schemaGuard.ts": (
            _ADOPT_BRANCH,
            "            const adopted: string[] = [];",
        )})
        proc = _run(bundle)
        assert proc.returncode != 0, (
            "the adoption scenario PASSED against a guard that never adopts."
            f"\nSTDOUT: {proc.stdout}"
        )
        assert "DROPPED the adopted field" in proc.stderr or \
               "adoptedFields() does not list it" in proc.stderr, proc.stderr

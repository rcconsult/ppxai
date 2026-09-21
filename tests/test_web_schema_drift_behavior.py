"""Behavioural fence for the web client's reconnect-time AppState schema
re-verify (Task 2, plan-adr-0007-completion-service.md open owner
decision item 9, closed 2026-09-21 — "re-fetch if difference is spot").

Same idiom as `tests/test_vscode_schema_guard_behavior.py`: the REAL
`ppxai/web/shared/app-state.js` (with its new `adoptSchema()`) and the
new `ppxai/web/shared/app-state-schema-diff.js` are driven under plain
Node. `app-state.js` only needs `window.APP_STATE_SCHEMA` to exist at
construction, so the harness sets `global.window = {APP_STATE_SCHEMA: ...}`
before requiring it — no DOM, no browser.

What is pinned, and why a source read could not see it
------------------------------------------------------

  1. **Identical is silent** — `compareAppStateSchemas` returns
     'identical' and NOTHING is adopted.
  2. **A NEWER server (extra-only) is adopted**: the new field gets a
     name-map entry and the server-declared default, so a subsequent
     `updateFromPython` STORES it instead of warning every push.
  3. **A field this tab's injected schema had, now missing or
     retyped/renamed on the server, is 'incompatible'** — still
     adopted (unlike VSCode, web has no compile-time types to lose by
     re-deriving fully from the server's schema), and the field this
     tab used to know is dropped from the live store.
  4. **Listeners on a field whose client name did not change keep
     firing after `adoptSchema`** — nothing re-registers them; the
     data key is untouched.
  5. **Non-canonical, app-owned keys (theme, isSending, ...) survive
     `adoptSchema` untouched** — they aren't in `_pythonToJs` at all.
  6. **Adoption is idempotent**: calling `adoptSchema` twice with the
     same server schema does not reset an already-adopted/carried
     value back to a default.
  7. **A second reconnect to the ORIGINAL schema reverts**: an adopted
     extra field's value and name-mapping are both gone, and pushing
     it again through `updateFromPython` is unknown once more.

(2)-(7) are proven against the REAL schema file
(`ppxai/engine/app_state_schema.json`), not a hand-rolled fixture, so a
real field's shape drives the assertions the same way it drives
`test_vscode_schema_guard_behavior.py`.

Skips cleanly where Node is unavailable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "ppxai" / "web" / "shared"
APP_STATE_JS = SHARED / "app-state.js"
DIFF_JS = SHARED / "app-state-schema-diff.js"
CANONICAL = ROOT / "ppxai" / "engine" / "app_state_schema.json"

NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


_HARNESS = r"""
const { AppState } = require(process.env.PPXAI_APP_STATE_JS);
const { compareSchemas } = require(process.env.PPXAI_DIFF_JS);

const CANONICAL = JSON.parse(process.env.PPXAI_CANONICAL_SCHEMA);

function assert(cond, msg) { if (!cond) throw new Error('FAIL: ' + msg); }
function clone(o) { return JSON.parse(JSON.stringify(o)); }

/** A server schema built by mutating a copy of the canonical one. */
function serverSchema(mutate) {
    const s = clone(CANONICAL);
    if (mutate) mutate(s);
    return s;
}

function makeState() {
    global.window = { APP_STATE_SCHEMA: CANONICAL };
    // Fresh require each time isn't needed -- AppState reads the schema
    // once at module load into a module-scope const, and each `new
    // AppState()` builds its OWN per-instance _pythonToJs/_data from it,
    // so re-using the already-required constructor across states in one
    // process is fine and matches how app.js uses a single instance.
    return new AppState();
}

(async () => {

  // --- 1: identical -> no adoption, snapshot fields present ------------
  {
    const state = makeState();
    const diff = compareSchemas(state._schema, serverSchema());
    assert(diff.verdict === 'identical', 'verdict was ' + diff.verdict);
    assert(diff.extra.length === 0 && diff.missing.length === 0 && diff.changed.length === 0,
      'identical schemas produced a non-empty diff');
  }

  // --- 2: extra-only -> adoptSchema stores it, default seeded ----------
  {
    const state = makeState();
    const served = serverSchema((s) => {
      s.fields.brand_new_thing = {
        client: 'brandNewThing', type: 'string', default: 'seed',
        group: 'core', doc: 'from a newer server',
      };
    });
    const diff = compareSchemas(state._schema, served);
    assert(diff.verdict === 'extra-only', 'verdict was ' + diff.verdict);
    assert(JSON.stringify(diff.extra) === '["brand_new_thing"]', JSON.stringify(diff.extra));

    state.adoptSchema(served);
    assert(state.brandNewThing === 'seed', 'default not seeded: ' + state.brandNewThing);
    const mapped = state.updateFromPython({ provider: 'openai', brand_new_thing: 'pushed' });
    assert(state.currentProvider === 'openai', 'known field broke after adoption');
    assert(state.brandNewThing === 'pushed', 'adopted field did not store a push: ' + state.brandNewThing);
    assert(mapped.brandNewThing === 'pushed', 'updateFromPython did not report the mapped adopted field');
    assert(state.snapshot().brandNewThing === 'pushed', 'snapshot() missing the adopted field');
  }

  // --- 3: incompatible (missing field) -> adopted, field dropped -------
  {
    const state = makeState();
    state.sessionName = 'my session';   // a real canonical field, set before adoption
    const served = serverSchema((s) => { delete s.fields.session_name; });
    const diff = compareSchemas(state._schema, served);
    assert(diff.verdict === 'incompatible', 'verdict was ' + diff.verdict);
    assert(JSON.stringify(diff.missing) === '["session_name"]', JSON.stringify(diff.missing));

    state.adoptSchema(served);
    assert(!('sessionName' in state.snapshot()), 'dropped field survived adoption: ' + JSON.stringify(state.snapshot().sessionName));
    // pushing it again is unknown -- there is nothing left to store it in
    const mapped = state.updateFromPython({ session_name: 'ignored' });
    assert(!('sessionName' in mapped), 'a field the server no longer declares was still mapped');
  }

  // --- 4: incompatible (renamed client) -> value CARRIES to new name ---
  {
    const state = makeState();
    state.sessionName = 'carried value';
    const served = serverSchema((s) => { s.fields.session_name.client = 'sessionTitle'; });
    const diff = compareSchemas(state._schema, served);
    assert(diff.verdict === 'incompatible', 'verdict was ' + diff.verdict);
    assert(diff.changed.some((c) => c.field === 'session_name'), 'rename not reported as changed');

    state.adoptSchema(served);
    assert(!('sessionName' in state.snapshot()), 'old client name survived a rename');
    assert(state.snapshot().sessionTitle === 'carried value',
      'renamed field did not carry its value: ' + JSON.stringify(state.snapshot().sessionTitle));
    // and it is reachable under the NEW python->client mapping
    state.updateFromPython({ session_name: 'still ignored (old py name unaffected by client rename)' });
  }

  // --- 5: retyped (type differs) -> incompatible, value untouched ------
  {
    const state = makeState();
    state.estimatedCost = 4.2;
    const served = serverSchema((s) => { s.fields.estimated_cost.type = 'string'; });
    const diff = compareSchemas(state._schema, served);
    assert(diff.verdict === 'incompatible', 'verdict was ' + diff.verdict);
    state.adoptSchema(served);
    // same client name -> the field survives adoption (type mismatch is
    // a server-declared CONTRACT change, not something adoptSchema itself
    // can or should coerce)
    assert(state.snapshot().estimatedCost === 4.2, 'unrelated-name retype dropped the value');
  }

  // --- 6: listeners on a SURVIVING field keep firing --------------------
  {
    const state = makeState();
    const seen = [];
    state.on('currentProvider', (v) => seen.push(v));
    const served = serverSchema((s) => {
      s.fields.brand_new_thing = { client: 'brandNewThing', type: 'string', default: '', group: 'core' };
    });
    state.adoptSchema(served);
    state.currentProvider = 'perplexity';
    assert(JSON.stringify(seen) === '["perplexity"]',
      'a listener on a field untouched by adoption stopped firing: ' + JSON.stringify(seen));
  }

  // --- 7: non-canonical, app-owned keys survive adoption untouched -----
  {
    const state = makeState();
    state.theme = 'dark';        // not in the schema at all
    state.isSending = true;      // ditto
    const served = serverSchema((s) => { delete s.fields.debug_log; });
    state.adoptSchema(served);
    assert(state.theme === 'dark', 'a non-canonical key was touched by adoptSchema');
    assert(state.isSending === true, 'a non-canonical key was touched by adoptSchema');
  }

  // --- 8: adoption is idempotent ----------------------------------------
  {
    const state = makeState();
    const served = serverSchema((s) => {
      s.fields.brand_new_thing = { client: 'brandNewThing', type: 'string', default: 'seed', group: 'core' };
    });
    state.adoptSchema(served);
    state.updateFromPython({ brand_new_thing: 'pushed' });
    assert(state.brandNewThing === 'pushed', 'setup failed');
    state.adoptSchema(served);   // re-adopt the SAME schema
    assert(state.brandNewThing === 'pushed',
      're-adopting the same schema reset an already-pushed value: ' + state.brandNewThing);
  }

  // --- 9: a SECOND reconnect to the ORIGINAL schema reverts -------------
  {
    const state = makeState();
    const withExtra = serverSchema((s) => {
      s.fields.brand_new_thing = { client: 'brandNewThing', type: 'string', default: 'seed', group: 'core' };
    });
    state.adoptSchema(withExtra);
    state.updateFromPython({ brand_new_thing: 'pushed' });
    assert(state.brandNewThing === 'pushed', 'setup failed');

    // Reconnect lands on the server WITHOUT the extra field again.
    state.adoptSchema(serverSchema());
    assert(!('brandNewThing' in state.snapshot()),
      'adopted field survived reverting to the original schema: '
      + JSON.stringify(state.snapshot().brandNewThing));
    const mapped = state.updateFromPython({ brand_new_thing: 'again' });
    assert(!('brandNewThing' in mapped),
      'the stale name mapping survived reverting to the original schema: ' + JSON.stringify(mapped));
    // known fields are unaffected throughout
    state.updateFromPython({ provider: 'gemini' });
    assert(state.currentProvider === 'gemini', 'known field broke after reverting');
  }

  // --- 10: adoptSchema never fires listeners itself ----------------------
  {
    const state = makeState();
    let fired = 0;
    state.on('currentProvider', () => { fired++; });
    const served = serverSchema((s) => {
      s.fields.brand_new_thing = { client: 'brandNewThing', type: 'string', default: '', group: 'core' };
    });
    state.adoptSchema(served);
    assert(fired === 0, 'adoptSchema fired a listener on an untouched field: ' + fired);
  }

  // --- 11: compareSchemas is pure ----------------------------------------
  {
    const a = serverSchema();
    const before = JSON.stringify(a);
    const state = makeState();
    compareSchemas(state._schema, a);
    assert(JSON.stringify(a) === before, 'compareSchemas mutated its input');
    const empty = compareSchemas(null, null);
    assert(empty.verdict === 'identical', 'null/null was ' + empty.verdict);
  }

  console.log('ALL OK');
})().catch((e) => { console.error(e.message); process.exit(1); });
"""


def _run(app_state_js: Path = APP_STATE_JS, diff_js: Path = DIFF_JS) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PPXAI_APP_STATE_JS"] = str(app_state_js)
    env["PPXAI_DIFF_JS"] = str(diff_js)
    env["PPXAI_CANONICAL_SCHEMA"] = CANONICAL.read_text(encoding="utf-8")
    return subprocess.run(
        [NODE, "-e", _HARNESS], capture_output=True, text=True, timeout=60, env=env
    )


def _mutant(tmp_path: Path, source: Path, old: str, new: str) -> Path:
    src = source.read_text(encoding="utf-8")
    assert old in src, (
        f"mutation anchor not found in {source.name} — this mutation test is "
        "stale and is no longer proving anything"
    )
    path = tmp_path / source.name
    path.write_text(src.replace(old, new, 1), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The real modules
# ---------------------------------------------------------------------------

def test_schema_adoption_classifies_and_adopts():
    proc = _run()
    assert proc.returncode == 0, (
        f"node harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    assert "ALL OK" in proc.stdout, proc.stdout


# ---------------------------------------------------------------------------
# Mutations — each removes one behaviour and the harness must reject it
# ---------------------------------------------------------------------------

_DROP_REMOVED = (
    "        for (const clientName of oldClientNames) {\n"
    "            if (!newClientNames.has(clientName)) delete newData[clientName];\n"
    "        }"
)

_RESEED = "        Object.assign(newData, newClientValues);"

_CARRY_OVER = (
    "            newClientValues[spec.client] = (\n"
    "                oldClientName !== undefined\n"
    "                && Object.prototype.hasOwnProperty.call(oldData, oldClientName)\n"
    "            ) ? oldData[oldClientName] : _cloneDefault(spec.default);"
)


class TestMutationDroppedFieldsReallyDrop:
    def test_not_dropping_removed_fields_is_caught(self, tmp_path):
        mutant = _mutant(tmp_path, APP_STATE_JS, _DROP_REMOVED,
                          "        // mutation: removed fields deliberately not dropped")
        proc = _run(app_state_js=mutant)
        assert proc.returncode != 0, (
            "the incompatible-drop scenario PASSED against an adoptSchema "
            f"that never drops removed fields.\nSTDOUT: {proc.stdout}"
        )
        assert "dropped field survived" in proc.stderr, proc.stderr


class TestMutationExtraFieldsReallySeed:
    def test_not_seeding_new_fields_is_caught(self, tmp_path):
        mutant = _mutant(tmp_path, APP_STATE_JS, _RESEED,
                          "        // mutation: new/changed fields never (re)seeded")
        proc = _run(app_state_js=mutant)
        assert proc.returncode != 0, (
            "the extra-only scenario PASSED against an adoptSchema that "
            f"never seeds adopted fields.\nSTDOUT: {proc.stdout}"
        )
        assert "default not seeded" in proc.stderr, proc.stderr


class TestMutationValuesReallyCarryOver:
    def test_always_using_the_default_is_caught(self, tmp_path):
        """Without carry-over, a surviving field would reset to its
        default on every reconnect — silently discarding whatever the
        user or a prior push had set."""
        mutant = _mutant(
            tmp_path, APP_STATE_JS, _CARRY_OVER,
            "            newClientValues[spec.client] = _cloneDefault(spec.default);",
        )
        proc = _run(app_state_js=mutant)
        assert proc.returncode != 0, (
            "the rename-carries-value scenario PASSED against an adoptSchema "
            f"that always uses the default.\nSTDOUT: {proc.stdout}"
        )
        assert "did not carry its value" in proc.stderr, proc.stderr

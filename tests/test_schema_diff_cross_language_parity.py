"""Cross-language parity: web's `compareAppStateSchemas` and VSCode's
`compareSchemas` must agree.

Task 2 (plan-adr-0007-completion-service.md open owner decision item 9)
re-implements `vscode-extension/src/schemaGuard.ts::compareSchemas` in
plain JS at `ppxai/web/shared/app-state-schema-diff.js`, deliberately —
the web client never imports compiled TypeScript. Two independent
implementations of the same classification is exactly the shape that
drifts silently, so this module feeds the SAME fixture schemas to both
(the real TS, compiled under the extension's own esbuild — same idiom
as `tests/test_vscode_schema_guard_behavior.py` — and the real web JS,
`require()`d directly) and asserts identical verdicts and field lists.

Skips cleanly where Node or the extension's esbuild is unavailable.
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
WEB_DIFF_JS = ROOT / "ppxai" / "web" / "shared" / "app-state-schema-diff.js"

pytestmark = pytest.mark.skipif(
    NODE is None or not ESBUILD.exists(),
    reason="node and vscode-extension/node_modules/.bin/esbuild are required",
)

_ENTRY = "export { compareSchemas } from './schemaGuard';\n"


def _bundle_ts(tmp_path: Path) -> Path:
    """Compile the real `compareSchemas` (schemaGuard.ts) to a scratch
    CJS bundle, same technique as test_vscode_schema_guard_behavior.py."""
    work = tmp_path / "bundle-src"
    work.mkdir(parents=True, exist_ok=True)
    (work / "schemaGuard.ts").write_bytes((SRC / "schemaGuard.ts").read_bytes())
    (work / "entry.ts").write_text(_ENTRY, encoding="utf-8")

    out = tmp_path / "out" / "bundle.js"
    out.parent.mkdir(parents=True, exist_ok=True)
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
const { compareSchemas: tsCompare } = require(process.env.PPXAI_TS_BUNDLE);
const { compareSchemas: jsCompare } = require(process.env.PPXAI_WEB_DIFF_JS);

const CANONICAL = JSON.parse(process.env.PPXAI_CANONICAL_SCHEMA);

function assert(cond, msg) { if (!cond) throw new Error('FAIL: ' + msg); }
function clone(o) { return JSON.parse(JSON.stringify(o)); }

function serverSchema(mutate) {
    const s = clone(CANONICAL);
    if (mutate) mutate(s);
    return s;
}

/** Normalise both results to the fields that matter for parity: verdict
 * and the three field-name lists. `adoptable` carries whole field specs
 * (order-insensitive object) and is compared as a sorted key list. */
function normalise(diff) {
    return {
        verdict: diff.verdict,
        extra: diff.extra,
        missing: diff.missing,
        changed: diff.changed.map((c) => ({ field: c.field, what: c.what })),
        adoptableKeys: Object.keys(diff.adoptable).sort(),
    };
}

function assertParity(label, bundled, server) {
    const ts = normalise(tsCompare(bundled, server));
    const js = normalise(jsCompare(bundled, server));
    assert(JSON.stringify(ts) === JSON.stringify(js),
      `${label}: TS and web JS disagree\n  ts: ${JSON.stringify(ts)}\n  js: ${JSON.stringify(js)}`);
    return ts;
}

const FIXTURES = [
  ['identical', serverSchema(), serverSchema()],
  ['extra field', serverSchema(), serverSchema((s) => {
    s.fields.brand_new_thing = { client: 'brandNewThing', type: 'string', default: 'x', group: 'core' };
  })],
  ['missing field', serverSchema(), serverSchema((s) => { delete s.fields.session_name; })],
  ['retyped field', serverSchema(), serverSchema((s) => { s.fields.estimated_cost.type = 'string'; })],
  ['renamed client', serverSchema(), serverSchema((s) => { s.fields.session_name.client = 'sessionTitle'; })],
  ['both missing and extra', serverSchema(), serverSchema((s) => {
    delete s.fields.debug_log;
    s.fields.another_new_one = { client: 'anotherNewOne', type: 'boolean', default: false, group: 'core' };
  })],
  ['version differs only', serverSchema(), serverSchema((s) => { s.version = '9.9'; })],
  ['null bundled', null, serverSchema()],
  ['null server', serverSchema(), null],
  ['both null', null, null],
];

let checked = 0;
for (const [label, bundled, server] of FIXTURES) {
    const result = assertParity(label, bundled, server);
    checked++;
}
assert(checked === FIXTURES.length, 'not all fixtures ran');

// Spot-check the classification actually differentiates (a parity test
// that only ever sees 'identical' proves nothing).
const verdicts = new Set(FIXTURES.map(([label, b, s]) => tsCompare(b, s).verdict));
assert(verdicts.has('identical') && verdicts.has('extra-only') && verdicts.has('incompatible'),
  'fixtures did not exercise all three verdicts: ' + JSON.stringify([...verdicts]));

console.log('ALL OK ' + checked);
"""


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    ts_bundle = _bundle_ts(tmp_path)
    env = dict(os.environ)
    env["PPXAI_TS_BUNDLE"] = str(ts_bundle)
    env["PPXAI_WEB_DIFF_JS"] = str(WEB_DIFF_JS)
    env["PPXAI_CANONICAL_SCHEMA"] = CANONICAL.read_text(encoding="utf-8")
    return subprocess.run(
        [NODE, "-e", _HARNESS], capture_output=True, text=True, timeout=60, env=env
    )


def test_web_and_vscode_schema_diff_agree(tmp_path):
    proc = _run(tmp_path)
    assert proc.returncode == 0, (
        f"cross-language parity harness failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    assert "ALL OK" in proc.stdout, proc.stdout

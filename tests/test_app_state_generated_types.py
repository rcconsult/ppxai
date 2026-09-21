"""The VSCode AppState TYPE layer is generated, not hand-written.

Background (measured 2026-09-21, before this fence existed)
----------------------------------------------------------
`vscode-extension/src/appState.ts` carried a hand-written
`export interface AppStateFields` described in its own header as
"hand-maintained ... checked at runtime by a constructor assertion".

Both halves were false:

* The canonical schema declared **22** fields; the interface declared
  **20**. `lastMessageRole` (added v1.18.0) and `modelSupportsVision`
  (added v1.18.6) were never typed, so nothing in the extension could
  read either by name — while `ppxai/web/app.js` had been using
  `modelSupportsVision` to gate the attach badge since v1.18.6.
* There was no constructor assertion. The constructor cast
  (`as AppStateFields`) and nothing compared the interface with the
  schema — not at build time, not at run time, and not in any test.

The header also promised that "the v1.18.x schema generator will
auto-generate `AppStateFields`". It never shipped.

What this module pins
---------------------
1. `appState.ts` declares no `AppStateFields` interface — the hand-written
   one cannot come back by being retyped.
2. `src/appState.generated.ts` is byte-identical to a fresh generation
   from `ppxai/engine/app_state_schema.json`, using the REAL generator.
3. Every schema field appears in the generated type and vice versa, in
   schema order.
4. The refinement map is honest: it may only name fields that exist and
   whose canonical type is a container (`array` / `object`).
5. The connect path actually CALLS the run-time guard (fence 4) — a
   consumer test that stays green with the call deleted proves nothing,
   so the call site itself is pinned and the pin is mutation-verified.

The tracked-vs-generated choice follows the precedent already set for
`vscode-extension/resources/app-state-schema.json`: the artefact is
TRACKED and a test pins it. `tsc --noEmit` must not depend on a file that
only exists after someone remembers to run a script.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "vscode-extension"
SRC = EXT / "src"
GENERATOR = EXT / "scripts" / "sync-schema.js"
GENERATED = SRC / "appState.generated.ts"
APPSTATE_TS = SRC / "appState.ts"
CHAT_PANEL_TS = SRC / "chatPanel.ts"
HTTP_CLIENT_TS = SRC / "httpClient.ts"
CANONICAL = ROOT / "ppxai" / "engine" / "app_state_schema.json"

NODE = shutil.which("node")

needs_node = pytest.mark.skipif(NODE is None, reason="node is required")

#: The two fields the hand-written interface had lost. Pinned by NAME so a
#: regression that drops them again fails here with the history attached,
#: not with a generic count mismatch.
_DRIFTED_AWAY = ("lastMessageRole", "modelSupportsVision")

#: `<indent><clientName>: <type>;` — the generated interface's member lines.
_MEMBER = re.compile(r"^    ([A-Za-z][A-Za-z0-9]*): (.+);$")

#: Field types a TYPE_REFINEMENTS entry may narrow.
_CONTAINER_TYPES = {"array", "object"}


def _schema() -> dict:
    return json.loads(CANONICAL.read_text(encoding="utf-8"))


def _node(script: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PPXAI_GENERATOR"] = str(GENERATOR)
    env.update(env_extra)
    return subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, timeout=120, env=env
    )


_RENDER = r"""
const gen = require(process.env.PPXAI_GENERATOR);
const schema = JSON.parse(process.env.PPXAI_SCHEMA_JSON);
const extra = JSON.parse(process.env.PPXAI_EXTRA_REFINEMENTS || '{}');
for (const [key, value] of Object.entries(extra)) {
    gen.TYPE_REFINEMENTS[key] = value;
}
process.stdout.write(gen.renderGeneratedTypes(schema));
"""


def _generate(schema: dict, extra_refinements: dict | None = None) -> subprocess.CompletedProcess:
    """Run the REAL generator over `schema` and return the completed process."""
    return _node(
        _RENDER,
        PPXAI_SCHEMA_JSON=json.dumps(schema),
        PPXAI_EXTRA_REFINEMENTS=json.dumps(extra_refinements or {}),
    )


def _equality_failure(tracked: str, fresh: str) -> str | None:
    """The one comparison this module's fence rests on.

    Returns None when the tracked file is a faithful generation, else the
    failure message. Shared by the real test and the mutation tests so a
    mutation is checked against the SAME code path, not a restatement.
    """
    if tracked == fresh:
        return None
    return (
        f"{GENERATED.relative_to(ROOT)} is not what the generator produces "
        f"from {CANONICAL.relative_to(ROOT)}. It is GENERATED — do not hand-edit "
        f"it. Run `npm run sync-schema` from vscode-extension/ and commit the "
        f"result (`npm run compile` does it too).\n"
        f"  tracked: {len(tracked)} bytes, {tracked.count(chr(10))} lines\n"
        f"  fresh:   {len(fresh)} bytes, {fresh.count(chr(10))} lines"
    )


def _members(text: str) -> list[tuple[str, str]]:
    """`[(clientName, tsType), ...]` in file order."""
    out: list[tuple[str, str]] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("export interface AppStateFields {"):
            inside = True
            continue
        if inside and line == "}":
            break
        if inside:
            m = _MEMBER.match(line)
            if m:
                out.append((m.group(1), m.group(2)))
    return out


def _function_body(text: str, signature: str) -> str:
    """The brace-matched body of the method whose line contains `signature`.

    A plain `in` check on the whole file would be satisfied by the call
    appearing ANYWHERE — including in a comment at the bottom. The fence
    is only worth having if it reads the right function.
    """
    start = text.find(signature)
    assert start != -1, (
        f"{signature!r} not found — this fence is pinned to a call site that "
        f"no longer exists. Re-point it at the current one rather than "
        f"deleting it."
    )
    open_brace = text.find("{", start)
    assert open_brace != -1, f"no body found for {signature!r}"
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace:i + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


# ---------------------------------------------------------------------------
# 1 — the hand-written interface is gone and cannot come back
# ---------------------------------------------------------------------------

class TestNoHandWrittenInterface:
    def test_app_state_ts_does_not_declare_the_interface(self):
        text = APPSTATE_TS.read_text(encoding="utf-8")
        assert "interface AppStateFields" not in text, (
            "vscode-extension/src/appState.ts declares `AppStateFields` again. "
            "That interface is GENERATED into src/appState.generated.ts by "
            "scripts/sync-schema.js — a hand-written copy is exactly the drift "
            "this fence exists to stop (it had lost "
            f"{', '.join(_DRIFTED_AWAY)} by 2026-09-21). Import the generated "
            "type instead."
        )

    def test_exactly_one_file_declares_it(self):
        declaring = [
            path.relative_to(ROOT)
            for path in sorted(SRC.rglob("*.ts"))
            if "interface AppStateFields" in path.read_text(encoding="utf-8")
        ]
        assert declaring == [GENERATED.relative_to(ROOT)], (
            "`AppStateFields` must be declared in exactly one file, the "
            f"generated one ({GENERATED.relative_to(ROOT)}). Found: "
            f"{[str(p) for p in declaring]}"
        )

    def test_app_state_ts_imports_the_generated_type(self):
        text = APPSTATE_TS.read_text(encoding="utf-8")
        assert "from './appState.generated'" in text, (
            "appState.ts no longer imports the generated type. If the "
            "generator was replaced, re-point this fence; if it was dropped, "
            "the hand-written drift is back."
        )

    def test_the_generated_file_is_tracked(self):
        proc = subprocess.run(
            ["git", "ls-files", "--error-unmatch",
             str(GENERATED.relative_to(ROOT))],
            cwd=ROOT, capture_output=True, text=True,
        )
        assert proc.returncode == 0, (
            f"{GENERATED.relative_to(ROOT)} is not tracked by git. It must be: "
            "`tsc --noEmit` and a fresh clone must not depend on someone "
            "having run a build script first — the same precedent as "
            "vscode-extension/resources/app-state-schema.json."
        )

    def test_header_says_generated_and_names_its_source(self):
        head = GENERATED.read_text(encoding="utf-8").split("\n\n")[0]
        assert "GENERATED FILE. DO NOT EDIT." in head, head
        assert "ppxai/engine/app_state_schema.json" in head, head
        assert "vscode-extension/scripts/sync-schema.js" in head, head
        assert f"schema version {_schema()['version']}" in head, head

    def test_generated_file_carries_no_timestamp(self):
        """Byte-stability is what lets the equality fence exist at all."""
        text = GENERATED.read_text(encoding="utf-8")
        assert not re.search(r"\b20\d\d-\d\d-\d\dT?\d*", text), (
            "the generated file contains something that looks like a "
            "timestamp. It must be byte-stable across runs or the equality "
            "fence below turns into a false failure on every regeneration."
        )


# ---------------------------------------------------------------------------
# 2 — the tracked file IS a faithful generation
# ---------------------------------------------------------------------------

@needs_node
class TestGeneratedFileMatchesSchema:
    def test_byte_identical_to_a_fresh_generation(self):
        proc = _generate(_schema())
        assert proc.returncode == 0, proc.stderr
        failure = _equality_failure(
            GENERATED.read_text(encoding="utf-8"), proc.stdout
        )
        assert failure is None, failure

    def test_every_schema_field_is_typed(self):
        members = dict(_members(GENERATED.read_text(encoding="utf-8")))
        for py_name, spec in _schema()["fields"].items():
            assert spec["client"] in members, (
                f"canonical field '{py_name}' (client '{spec['client']}') has "
                f"no entry in the generated type. Run `npm run sync-schema`."
            )

    def test_no_field_the_schema_does_not_declare(self):
        declared = {s["client"] for s in _schema()["fields"].values()}
        for name, _ in _members(GENERATED.read_text(encoding="utf-8")):
            assert name in declared, (
                f"the generated type declares '{name}', which is not a field "
                f"in {CANONICAL.relative_to(ROOT)}. The generator derives its "
                f"members from the schema, so this means the file was "
                f"hand-edited."
            )

    def test_order_matches_schema_order(self):
        expected = [s["client"] for s in _schema()["fields"].values()]
        actual = [name for name, _ in _members(GENERATED.read_text(encoding="utf-8"))]
        assert actual == expected

    def test_the_two_fields_the_hand_written_interface_lost_are_present(self):
        members = dict(_members(GENERATED.read_text(encoding="utf-8")))
        for name in _DRIFTED_AWAY:
            assert name in members, (
                f"'{name}' is missing again. It is exactly the drift that "
                f"motivated generating this file: the hand-written interface "
                f"was two fields behind the schema for four minor versions."
            )
        assert members["lastMessageRole"] == "string"
        assert members["modelSupportsVision"] == "boolean"

    def test_container_fields_are_refined_or_safely_generic(self):
        members = dict(_members(GENERATED.read_text(encoding="utf-8")))
        for py_name, spec in _schema()["fields"].items():
            if spec["type"] not in _CONTAINER_TYPES:
                continue
            ts_type = members[spec["client"]]
            assert ts_type not in ("any", "any[]", "object"), (
                f"container field '{py_name}' got type '{ts_type}' — the "
                f"unrefined fallback must stay `unknown[]` / "
                f"`Record<string, unknown>`, which forces a narrowing at the "
                f"call site instead of silently allowing anything."
            )


# ---------------------------------------------------------------------------
# 3 — refinement honesty
# ---------------------------------------------------------------------------

@needs_node
class TestRefinementHonesty:
    def test_declared_refinements_all_name_container_fields(self):
        proc = _node(
            "const g = require(process.env.PPXAI_GENERATOR);"
            "process.stdout.write(JSON.stringify(Object.keys(g.TYPE_REFINEMENTS)));"
        )
        assert proc.returncode == 0, proc.stderr
        refined = json.loads(proc.stdout)
        by_client = {s["client"]: s for s in _schema()["fields"].values()}
        for name in refined:
            assert name in by_client, (
                f"TYPE_REFINEMENTS refines '{name}', which is not a field in "
                f"{CANONICAL.relative_to(ROOT)}."
            )
            assert by_client[name]["type"] in _CONTAINER_TYPES, (
                f"TYPE_REFINEMENTS refines '{name}', whose canonical type is "
                f"'{by_client[name]['type']}' — only "
                f"{sorted(_CONTAINER_TYPES)} may be refined."
            )

    def test_refining_an_unknown_field_is_rejected(self):
        proc = _generate(_schema(), {
            "noSuchField": {"type": "string[]", "imports": []},
        })
        assert proc.returncode != 0, (
            "the generator ACCEPTED a refinement naming a field that does not "
            f"exist — nothing is checking the map.\nSTDOUT: {proc.stdout[:400]}"
        )
        assert "not a field in" in proc.stderr, proc.stderr

    def test_refining_a_scalar_field_is_rejected(self):
        proc = _generate(_schema(), {
            "currentProvider": {"type": "'perplexity' | 'openai'", "imports": []},
        })
        assert proc.returncode != 0, (
            "the generator ACCEPTED a refinement of a `string` field — a "
            "client-side narrowing of a rule the canonical schema does not "
            f"make.\nSTDOUT: {proc.stdout[:400]}"
        )
        assert "Only array/object fields may be refined" in proc.stderr, proc.stderr


# ---------------------------------------------------------------------------
# 4 — mutations: the equality fence really bites
# ---------------------------------------------------------------------------

@needs_node
class TestMutationGenerationIsPinned:
    def test_a_new_schema_field_fails_until_regenerated(self):
        """Add a field to a scratch copy of the schema. The tracked file is
        now stale, and the fence must say so."""
        schema = _schema()
        schema["fields"]["scratch_probe"] = {
            "client": "scratchProbe", "type": "string", "default": "",
            "group": "core", "doc": "planted by the fence",
        }
        proc = _generate(schema)
        assert proc.returncode == 0, proc.stderr
        assert "scratchProbe: string;" in proc.stdout, proc.stdout[:400]
        failure = _equality_failure(
            GENERATED.read_text(encoding="utf-8"), proc.stdout
        )
        assert failure is not None, (
            "a schema field that is NOT in the tracked generated file passed "
            "the equality check — the fence proves nothing."
        )
        assert "npm run sync-schema" in failure

    def test_hand_editing_the_generated_file_is_caught(self):
        proc = _generate(_schema())
        assert proc.returncode == 0, proc.stderr
        tampered = GENERATED.read_text(encoding="utf-8").replace(
            "    lastMessageRole: string;",
            "    lastMessageRole: 'user' | 'assistant';",
            1,
        )
        assert tampered != GENERATED.read_text(encoding="utf-8"), (
            "the mutation anchor is stale — it edited nothing"
        )
        failure = _equality_failure(tampered, proc.stdout)
        assert failure is not None, (
            "a hand-edited generated file passed the equality check."
        )
        assert "do not hand-edit" in failure

    def test_removing_a_field_from_the_generation_is_caught(self):
        schema = _schema()
        del schema["fields"]["model_supports_vision"]
        proc = _generate(schema)
        assert proc.returncode == 0, proc.stderr
        assert "modelSupportsVision" not in proc.stdout
        failure = _equality_failure(
            GENERATED.read_text(encoding="utf-8"), proc.stdout
        )
        assert failure is not None


# ---------------------------------------------------------------------------
# 5 — the connect path actually calls the run-time guard
# ---------------------------------------------------------------------------

class TestConnectPathCallsTheGuard:
    """Fence 4. A behavioural test of `SchemaGuard` stays green when the
    extension never calls it — the module is perfectly correct and simply
    unreachable. `chatPanel.ts` imports `vscode`, so it cannot be driven
    under Node; the call sites are pinned in source instead, read out of
    the RIGHT function body rather than anywhere in the file.

    Mutation-verified by deleting each call and re-running.
    """

    def test_initialize_backend_checks_the_schema(self):
        body = _function_body(
            CHAT_PANEL_TS.read_text(encoding="utf-8"),
            "private async initializeBackend(",
        )
        assert "this._schemaGuard.check()" in body, (
            "initializeBackend() no longer calls `this._schemaGuard.check()`. "
            "Without that call the run-time half of the AppState contract is "
            "dead code: the extension would go on trusting its build-time "
            "schema against whatever server it reached. Restore the call next "
            "to `this._commandRoster.load()`."
        )

    def test_check_runs_after_the_roster_load(self):
        body = _function_body(
            CHAT_PANEL_TS.read_text(encoding="utf-8"),
            "private async initializeBackend(",
        )
        assert body.index("this._commandRoster.load()") < body.index(
            "this._schemaGuard.check()"
        ), (
            "the schema check must come after the roster load: the roster is "
            "fail-closed and gates command dispatch, the schema check is "
            "advisory. Ordering them the other way delays the gate for a "
            "diagnostic."
        )

    def test_disconnect_resets_adoption(self):
        body = _function_body(
            CHAT_PANEL_TS.read_text(encoding="utf-8"),
            "public updateServerStatus(",
        )
        assert "this._schemaGuard.reset()" in body, (
            "updateServerStatus() no longer resets the schema guard on "
            "disconnect. Fields adopted from one server would survive a "
            "reconnect to a different one — the exact stale-state bug the "
            "per-instance mapping was built to avoid. Reset it next to "
            "`this._commandRoster.unload()`."
        )

    def test_http_client_exposes_the_endpoint(self):
        text = HTTP_CLIENT_TS.read_text(encoding="utf-8")
        assert "async getAppStateSchema(" in text
        assert "/schema/app-state" in text, (
            "httpClient no longer fetches GET /schema/app-state — the "
            "endpoint is back to having no consumer, which is the state ADR "
            "0007 recorded as an open finding."
        )

    def test_the_guard_module_is_vscode_free(self):
        text = (SRC / "schemaGuard.ts").read_text(encoding="utf-8")
        assert "from 'vscode'" not in text and 'from "vscode"' not in text, (
            "schemaGuard.ts imports `vscode`. It must not: the behavioural "
            "fence drives the REAL compiled module under plain Node, the same "
            "IoC shape as commandRoster.ts and taskController.ts."
        )

"""Static structural tests for VSCode Step 5c (v1.18.1).

5c lands two state-sync determinism phases on the VSCode side:

  Phase B — REST piggyback events[].
    The factory's command envelope ships `events: [...]` drained from
    the engine's side-channel queue. Without a consumer they sit until
    the next /chat opens an SSE generator. The dispatcher must drain
    them through the same EventBus subscribers the live SSE pipeline
    uses, so AppState catches up immediately after a state-mutating
    REST call.

  Phase D — cwd_anchor 409 recovery helper.
    /files/read|write|image accept an optional `cwd_anchor` (the
    working_dir the client thinks it captured the relpath against).
    The server returns 409 + {expected, actual, events[]} on drift.
    httpClient surfaces it as a structured Error; chatPanel exposes
    `handleCwdAnchorMismatch(err)` that drains the events and shows a
    notice. Mirrors web's `app.handleCwdAnchorMismatch`.

Cross-client parity test in `test_state_sync_phase_d_parity.py`
(if present) keeps web and VSCode in lockstep on the recovery shape.

Tests pin these contracts so 5c remains stable under future edits.
"""

from __future__ import annotations

import re
from pathlib import Path

EXT_SRC = Path(__file__).resolve().parents[1] / "vscode-extension" / "src"


def _read(rel: str) -> str:
    return (EXT_SRC / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase B: dispatchFactoryCommand drains envelope.events
# ---------------------------------------------------------------------------

def _dispatcher_body(src: str) -> str:
    m = re.search(
        r"private\s+async\s+dispatchFactoryCommand[\s\S]*?\n\s{4}\}",
        src,
    )
    assert m, "dispatchFactoryCommand not found"
    return m.group(0)


class TestPhaseBPiggybackDrain:
    def test_drainer_method_exists(self):
        src = _read("chatPanel.ts")
        assert "_drainEnvelopeEvents" in src, (
            "chatPanel must expose _drainEnvelopeEvents to consume "
            "envelope.events from REST piggyback"
        )

    def test_dispatcher_calls_drainer(self):
        body = _dispatcher_body(_read("chatPanel.ts"))
        assert "_drainEnvelopeEvents" in body, (
            "dispatchFactoryCommand must drain envelope.events via "
            "_drainEnvelopeEvents — without this REST mutations are "
            "invisible to clients until the next /chat"
        )

    def test_drainer_handles_state_sync(self):
        src = _read("chatPanel.ts")
        # Find the _drainEnvelopeEvents body
        m = re.search(
            r"_drainEnvelopeEvents\s*\([^)]*\):\s*void\s*\{([\s\S]*?)\n\s{4}\}",
            src,
        )
        assert m, "_drainEnvelopeEvents body not found"
        body = m.group(1)
        # Per ppxai/server/state.py::with_drained_events, the drained
        # events arrive as {type, data, metadata?} objects with `data`
        # already an object. state_sync events go through the EventBus.
        assert "'state_sync'" in body, (
            "drainer must dispatch on type === 'state_sync'"
        )
        assert "'state:sync'" in body, (
            "state_sync events should fire 'state:sync' on the EventBus "
            "(same path as live SSE)"
        )

    def test_drainer_handles_working_dir_changed(self):
        src = _read("chatPanel.ts")
        m = re.search(
            r"_drainEnvelopeEvents\s*\([^)]*\):\s*void\s*\{([\s\S]*?)\n\s{4}\}",
            src,
        )
        assert m
        body = m.group(1)
        assert "'working_dir_changed'" in body, (
            "drainer must dispatch on type === 'working_dir_changed' "
            "to update the workspace badge"
        )
        assert "'ui:working_dir_changed'" in body, (
            "working_dir_changed events should fire "
            "'ui:working_dir_changed' on the EventBus"
        )

    def test_drainer_tolerates_missing_events(self):
        """No events / null events shouldn't throw — the field is
        optional in the v1 envelope."""
        src = _read("chatPanel.ts")
        m = re.search(
            r"_drainEnvelopeEvents\s*\([^)]*\):\s*void\s*\{([\s\S]*?)\n\s{4}\}",
            src,
        )
        assert m
        body = m.group(1)
        assert ("Array.isArray" in body or "events?" in body), (
            "drainer must guard against undefined/null events arg"
        )


# ---------------------------------------------------------------------------
# Phase D: cwd_anchor support in httpClient + recovery helper
# ---------------------------------------------------------------------------

class TestPhaseDHttpClient:
    def test_throwHttpError_helper_exists(self):
        src = _read("httpClient.ts")
        assert "_throwHttpError" in src, (
            "httpClient must define _throwHttpError to attach status, "
            "expected, actual, events to non-OK responses"
        )

    def test_throwHttpError_attaches_anchor_fields(self):
        src = _read("httpClient.ts")
        m = re.search(
            r"_throwHttpError\s*\([\s\S]*?(?=\n\s{4}\b(?:async|public|private|/\*\*|\}))",
            src,
        )
        assert m, "_throwHttpError body not located"
        body = m.group(0)
        for field in ("err.status", "err.expected", "err.actual", "err.events"):
            assert field in body, (
                f"_throwHttpError must set {field} so the cwd-anchor "
                f"recovery helper can read it"
            )

    def test_readFile_method_exists(self):
        src = _read("httpClient.ts")
        assert re.search(
            r"async\s+readFile\s*\([^)]*cwdAnchor", src
        ), (
            "httpClient.readFile(filepath, cwdAnchor?) must exist — "
            "matches the API surface web provides via api-client.js"
        )

    def test_writeFile_accepts_cwd_anchor(self):
        src = _read("httpClient.ts")
        # writeFile signature should now include cwdAnchor
        m = re.search(
            r"async\s+writeFile\s*\([^)]*\)",
            src,
        )
        assert m
        sig = m.group(0)
        assert "cwdAnchor" in sig, (
            "writeFile must accept an optional cwdAnchor argument "
            "(v1.18.1 Phase D drift detection)"
        )

    def test_writeFile_passes_cwd_anchor_in_body(self):
        src = _read("httpClient.ts")
        # Find the writeFile body — strict boundary on the next
        # method/jsdoc to avoid leaking into the next method.
        m = re.search(
            r"async\s+writeFile\s*\([\s\S]*?(?=\n\s{4}\}\n\s*\n\s{4}/\*\*|\n\s{4}/\*\*\n\s+\*\s+(?:Get|Set|List|Read|Send|Generate))",
            src,
        )
        assert m, "writeFile body not located"
        body = m.group(0)
        assert "cwd_anchor" in body, (
            "writeFile must put cwdAnchor onto the request body as "
            "`cwd_anchor` (snake_case wire field)"
        )

    def test_readFile_uses_throwHttpError(self):
        src = _read("httpClient.ts")
        m = re.search(
            r"async\s+readFile[\s\S]*?(?=\n\s{4}\}\n\s*\n\s{4}/\*\*)",
            src,
        )
        assert m
        body = m.group(0)
        assert "_throwHttpError" in body, (
            "readFile must use _throwHttpError so 409 surfaces with "
            "expected/actual/events fields"
        )

    def test_writeFile_uses_throwHttpError(self):
        src = _read("httpClient.ts")
        m = re.search(
            r"async\s+writeFile[\s\S]*?(?=\n\s{4}\}\n\s*\n\s{4}/\*\*)",
            src,
        )
        assert m
        body = m.group(0)
        assert "_throwHttpError" in body, (
            "writeFile must use _throwHttpError so 409 surfaces with "
            "expected/actual/events fields"
        )


class TestPhaseDChatPanelHelper:
    def test_handle_cwd_anchor_mismatch_method_exists(self):
        src = _read("chatPanel.ts")
        assert "handleCwdAnchorMismatch" in src, (
            "chatPanel must expose handleCwdAnchorMismatch — symmetric "
            "with web's app.handleCwdAnchorMismatch"
        )

    def test_helper_returns_false_for_non_409(self):
        src = _read("chatPanel.ts")
        m = re.search(
            r"handleCwdAnchorMismatch\s*\([^)]*\):\s*boolean\s*\{([\s\S]*?)\n\s{4}\}",
            src,
        )
        assert m, "handleCwdAnchorMismatch body not located"
        body = m.group(1)
        # Guard: non-409 errors are NOT this helper's problem.
        assert "err.status !== 409" in body or "status !== 409" in body, (
            "helper must return false for non-409 errors so callers "
            "re-raise"
        )

    def test_helper_drains_events(self):
        src = _read("chatPanel.ts")
        m = re.search(
            r"handleCwdAnchorMismatch\s*\([^)]*\):\s*boolean\s*\{([\s\S]*?)\n\s{4}\}",
            src,
        )
        assert m
        body = m.group(1)
        assert "_drainEnvelopeEvents" in body, (
            "recovery must reuse the Phase B drainer so the AppState "
            "mirror catches up to the engine's actual cwd"
        )

    def test_helper_defense_in_depth_writes_actual(self):
        """If events[] was empty but err.actual is set, the helper
        must still update the workingDir mirror — defensive against
        servers that forgot to pack the events list."""
        src = _read("chatPanel.ts")
        m = re.search(
            r"handleCwdAnchorMismatch\s*\([^)]*\):\s*boolean\s*\{([\s\S]*?)\n\s{4}\}",
            src,
        )
        assert m
        body = m.group(1)
        assert "err.actual" in body, (
            "helper must read err.actual for the defense-in-depth path"
        )
        assert "_appState.set('workingDir'" in body, (
            "helper must write workingDir directly when events[] empty"
        )

    def test_helper_surfaces_user_notice(self):
        src = _read("chatPanel.ts")
        m = re.search(
            r"handleCwdAnchorMismatch\s*\([^)]*\):\s*boolean\s*\{([\s\S]*?)\n\s{4}\}",
            src,
        )
        assert m
        body = m.group(1)
        assert "Working directory changed" in body, (
            "helper must show a user-facing notice (mirrors web's "
            "system message)"
        )


# ---------------------------------------------------------------------------
# Cross-client parity check — VSCode helper has the same shape as web's
# ---------------------------------------------------------------------------

class TestPhaseDCrossClientParity:
    """Web and VSCode helpers should agree on the contract: same name,
    same return semantics, same recovery steps."""

    def test_method_names_match(self):
        web_app = (Path(__file__).resolve().parents[1] / "ppxai" / "web" / "app.js").read_text(encoding="utf-8")
        vscode_panel = _read("chatPanel.ts")
        assert "handleCwdAnchorMismatch" in web_app, (
            "web must define handleCwdAnchorMismatch (Phase D)"
        )
        assert "handleCwdAnchorMismatch" in vscode_panel, (
            "VSCode must define handleCwdAnchorMismatch with the same name"
        )

    def test_both_return_boolean(self):
        web_app = (Path(__file__).resolve().parents[1] / "ppxai" / "web" / "app.js").read_text(encoding="utf-8")
        vscode_panel = _read("chatPanel.ts")
        # web: `if (!err || err.status !== 409) return false;`
        # vscode: same shape
        assert "return false" in web_app[
            web_app.find("handleCwdAnchorMismatch"):
            web_app.find("handleCwdAnchorMismatch") + 800
        ], "web helper must early-return false for non-409"
        m = re.search(
            r"handleCwdAnchorMismatch\s*\([^)]*\):\s*boolean",
            vscode_panel,
        )
        assert m, "VSCode helper must declare `: boolean` return type"

    def test_both_drain_events(self):
        """Both implementations must consume err.events to update
        the AppState mirror — this is the actual recovery work."""
        web_app = (Path(__file__).resolve().parents[1] / "ppxai" / "web" / "app.js").read_text(encoding="utf-8")
        vscode_panel = _read("chatPanel.ts")
        # Web reads err.events directly
        web_section = web_app[
            web_app.find("handleCwdAnchorMismatch"):
            web_app.find("handleCwdAnchorMismatch") + 1500
        ]
        assert "err.events" in web_section, (
            "web helper must walk err.events"
        )
        # VSCode goes through _drainEnvelopeEvents (same effect)
        vscode_section = vscode_panel[
            vscode_panel.find("handleCwdAnchorMismatch"):
            vscode_panel.find("handleCwdAnchorMismatch") + 1500
        ]
        assert "_drainEnvelopeEvents" in vscode_section, (
            "VSCode helper must drain events (via _drainEnvelopeEvents)"
        )

"""Static structural tests for the web-app visibility re-anchor (v1.18.1).

State-sync determinism Phase A. The web mirror of AppState drifts when
the tab is backgrounded — heartbeat reconnect only fires after two
consecutive `/health` failures, but tab sleep / focus restore /
back-forward navigation don't trigger that. The fix is a
`visibilitychange` listener that calls `GET /state` and feeds the
snapshot through `state.updateFromPython()` whenever the tab returns
to visible.

These tests don't run JS — they assert the wiring is present in
`ppxai/web/app.js`. Runtime correctness is covered by the e2e suite
(Step 6 of the v1.18.1 plan: drift simulation against a real
spawned server).

Why structural-only here:
  - The behavior is a single fetch + facade write. Mocking
    `document.visibilitychange` and `apiClient.getState()` from
    Python adds no signal beyond "did we wire the listener" — the
    e2e test will catch real drift.
  - The expensive part (a second JS test runner) doesn't pay off
    for a 5-line listener.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "ppxai" / "web" / "app.js"


def _read_app_js() -> str:
    return APP_JS.read_text(encoding="utf-8")


class TestVisibilityReanchorWiring:
    def test_visibilitychange_listener_registered(self):
        """The PpxaiApp constructor (or init flow) must add a
        `visibilitychange` listener. Without it, AppState drift
        on tab restore goes undetected."""
        src = _read_app_js()
        assert re.search(
            r"addEventListener\(\s*['\"]visibilitychange['\"]",
            src,
        ), "visibilitychange listener not found in app.js"

    def test_listener_calls_reanchor_on_visible(self):
        """The listener body must check `document.visibilityState
        === 'visible'` and invoke `_reanchorFromServer`."""
        src = _read_app_js()
        # Find the visibilitychange handler block
        match = re.search(
            r"addEventListener\(\s*['\"]visibilitychange['\"][\s\S]*?\}\)",
            src,
        )
        assert match, "visibilitychange handler block not found"
        block = match.group(0)
        assert "visibilityState" in block, (
            "handler must check document.visibilityState"
        )
        assert "'visible'" in block or '"visible"' in block, (
            "handler must guard on visibilityState === 'visible'"
        )
        assert "_reanchorFromServer" in block, (
            "handler must call _reanchorFromServer()"
        )

    def test_reanchor_helper_is_defined(self):
        """`_reanchorFromServer` must exist as an instance method
        on PpxaiApp (or wherever the listener calls it from). It
        does the GET /state + updateFromPython work."""
        src = _read_app_js()
        assert re.search(
            r"async\s+_reanchorFromServer\s*\(",
            src,
        ), "_reanchorFromServer method not found"

    def test_reanchor_uses_apiclient_getstate(self):
        """The helper must call `apiClient.getState()` (the
        existing `/state` snapshot endpoint), not invent a new
        path or call individual endpoints piecemeal."""
        src = _read_app_js()
        # Find the _reanchorFromServer body
        match = re.search(
            r"async\s+_reanchorFromServer\s*\([\s\S]*?\n    \}",
            src,
        )
        assert match, "could not extract _reanchorFromServer body"
        body = match.group(0)
        assert "apiClient.getState" in body, (
            "_reanchorFromServer must call apiClient.getState()"
        )
        assert "updateFromPython" in body, (
            "_reanchorFromServer must call state.updateFromPython()"
        )

    def test_heartbeat_reconnect_uses_shared_helper(self):
        """The heartbeat path that fires on reconnect must call the
        same `_reanchorFromServer` helper rather than duplicating
        the getState + updateFromPython logic. Drift fence: if the
        listener and the heartbeat path diverge in what they
        re-anchor, drift fixes won't compose."""
        src = _read_app_js()
        # Find the _heartbeat method
        match = re.search(
            r"async\s+_heartbeat\s*\([\s\S]*?\n    \}",
            src,
        )
        assert match, "could not extract _heartbeat body"
        body = match.group(0)
        # The reconnect branch should delegate to the helper.
        assert "_reanchorFromServer" in body, (
            "_heartbeat reconnect path must use _reanchorFromServer"
        )

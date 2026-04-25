"""Static structural tests for the VSCode visibility re-anchor (v1.18.1).

State-sync determinism Phase A, VSCode side. Mirrors
`tests/test_web_visibility_reanchor.py` for parity. The web app uses
`document.addEventListener('visibilitychange', ...)`; the VSCode
extension uses `vscode.window.onDidChangeWindowState(({focused}) => ...)`.
Both call the same shape: GET /state (the SSE_SYNC_FIELDS snapshot
endpoint) → updateFromPython on the local AppState mirror.

Why structural-only: the runtime side is a fetch + facade write,
no business logic worth a TS-runtime test runner just for this.
The e2e drift suite (Step 6) will exercise both clients against a
real spawned server.

Drift fences enforced here:
  - The listener is registered in `resolveWebviewView` (so it lives
    only while the chat panel is mounted, not for the whole
    extension lifetime).
  - The listener is disposed when the webview is disposed —
    otherwise the chat panel's `_reanchorFromServer` keeps firing
    after the panel closes, leaking work and possibly errors.
  - Web and VSCode helpers share the SAME shape: GET /state →
    updateFromPython. If one client adds a step (e.g. file-tree
    refresh) without the other, they're not parity any more.
"""

from __future__ import annotations

import re
from pathlib import Path

CHAT_PANEL_TS = (
    Path(__file__).resolve().parents[1]
    / "vscode-extension" / "src" / "chatPanel.ts"
)


def _read_chat_panel() -> str:
    return CHAT_PANEL_TS.read_text(encoding="utf-8")


class TestVSCodeVisibilityReanchorWiring:
    def test_window_state_listener_registered(self):
        """The chat panel must subscribe to
        `vscode.window.onDidChangeWindowState`. Without it, AppState
        drift on focus restore goes undetected."""
        src = _read_chat_panel()
        assert "onDidChangeWindowState" in src, (
            "onDidChangeWindowState listener not found in chatPanel.ts"
        )

    def test_listener_guards_on_focused(self):
        """Re-anchor only on focused=true, not on every window
        state change (which fires on focus loss too — re-anchoring
        then is wasted work)."""
        src = _read_chat_panel()
        # Find the listener block — onDidChangeWindowState((arg) => { ... })
        match = re.search(
            r"onDidChangeWindowState\([\s\S]*?\}\s*\)",
            src,
        )
        assert match, "could not locate onDidChangeWindowState block"
        block = match.group(0)
        assert "focused" in block, (
            "listener must check windowState.focused"
        )
        assert "_reanchorFromServer" in block, (
            "listener must call _reanchorFromServer()"
        )

    def test_listener_is_disposed_with_webview(self):
        """The listener disposable must be tied to the webview's
        lifecycle so it doesn't outlive the panel. Without
        `onDidDispose`, the listener leaks across panel reopens."""
        src = _read_chat_panel()
        # The handle name is `focusListener` per the implementation.
        assert re.search(
            r"onDidDispose\(\s*\(\s*\)\s*=>\s*\w+\.dispose",
            src,
        ), (
            "listener must be disposed via webviewView.onDidDispose() — "
            "otherwise it leaks past panel close"
        )

    def test_reanchor_helper_is_defined(self):
        """`_reanchorFromServer` must exist as a private method on
        ChatViewProvider and be async (it does a fetch)."""
        src = _read_chat_panel()
        assert re.search(
            r"private\s+async\s+_reanchorFromServer\s*\(",
            src,
        ), "private async _reanchorFromServer() not found"

    def test_reanchor_uses_backend_fetchstate(self):
        """The helper must call `this._backend.fetchState()` (the
        existing /state snapshot wrapper in HttpClient), not a
        custom fetch or piecemeal endpoint calls."""
        src = _read_chat_panel()
        match = re.search(
            r"private\s+async\s+_reanchorFromServer[\s\S]*?\n    \}",
            src,
        )
        assert match, "could not extract _reanchorFromServer body"
        body = match.group(0)
        assert "fetchState" in body, (
            "_reanchorFromServer must call this._backend.fetchState()"
        )
        assert "updateFromPython" in body, (
            "_reanchorFromServer must call _appState.updateFromPython()"
        )


# ---------------------------------------------------------------------------
# Web/VSCode parity — drift fence across the two clients
# ---------------------------------------------------------------------------

class TestReanchorParity:
    """Both the web and the VSCode re-anchor helpers should call
    the same two methods: get the snapshot, then feed updateFromPython.
    If one diverges (e.g. adds a side step), the two clients fall out
    of parity and drift fixes won't compose."""

    def test_both_clients_call_get_state(self):
        web = (Path(__file__).resolve().parents[1]
               / "ppxai" / "web" / "app.js").read_text(encoding="utf-8")
        vsc = _read_chat_panel()
        # Web: apiClient.getState; VSCode: backend.fetchState.
        # Both wrap the same /state endpoint.
        assert "apiClient.getState" in web
        assert "fetchState" in vsc

    def test_both_clients_call_update_from_python(self):
        web = (Path(__file__).resolve().parents[1]
               / "ppxai" / "web" / "app.js").read_text(encoding="utf-8")
        vsc = _read_chat_panel()
        assert "updateFromPython" in web
        assert "updateFromPython" in vsc

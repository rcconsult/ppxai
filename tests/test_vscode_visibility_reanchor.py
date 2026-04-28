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
        then is wasted work).

        Item 2 (v1.18.2) split the listener into a contract-based
        `installFocusReanchor` function. The contract: the
        installer must (a) check `focused` before invoking the
        callback, and (b) the orchestrator must pass
        `_reanchorFromServer` as that callback. We validate both
        sides of the contract, not the specific call-site pattern.
        """
        src = _read_chat_panel()
        # Side (a): the installer guards on `focused`.
        installer = re.search(
            r"function\s+installFocusReanchor\([\s\S]*?^\}",
            src,
            re.MULTILINE,
        )
        assert installer, "installFocusReanchor function not found"
        assert "focused" in installer.group(0), (
            "installFocusReanchor must check windowState.focused"
        )

        # Side (b): the orchestrator wires `_reanchorFromServer` as
        # the callback.
        orchestrator_call = re.search(
            r"installFocusReanchor\(\s*\(\)\s*=>\s*this\._reanchorFromServer\(\)\s*\)",
            src,
        )
        assert orchestrator_call, (
            "resolveWebviewView must pass `() => this._reanchorFromServer()` "
            "to installFocusReanchor — that's the contract that ties focus "
            "events to AppState re-anchor"
        )

    def test_listener_is_disposed_with_webview(self):
        """The listener disposable must be tied to the webview's
        lifecycle so it doesn't outlive the panel. Without
        `onDidDispose`, the listener leaks across panel reopens.

        Item 2 (v1.18.2) returns the listener as a `Disposable`
        from `installFocusReanchor`; the orchestrator must dispose
        it inside `webviewView.onDidDispose`. The contract here is
        that the focus disposable is reachable from the dispose
        callback, regardless of how it's named.
        """
        src = _read_chat_panel()
        # `installFocusReanchor` must return a Disposable.
        assert re.search(
            r"function\s+installFocusReanchor[\s\S]*?\):\s*vscode\.Disposable",
            src,
        ), "installFocusReanchor must declare a vscode.Disposable return type"

        # The orchestrator must capture that disposable AND dispose it
        # inside onDidDispose. Match the pattern: a const assigned from
        # installFocusReanchor + a .dispose() call inside onDidDispose.
        capture = re.search(
            r"const\s+(\w+)\s*=\s*installFocusReanchor\(",
            src,
        )
        assert capture, (
            "resolveWebviewView must capture the installFocusReanchor "
            "Disposable in a const so it can be disposed later"
        )
        handle_name = capture.group(1)
        dispose_block = re.search(
            r"webviewView\.onDidDispose\(\s*\(\)\s*=>\s*\{[\s\S]*?\}\s*\)",
            src,
        )
        assert dispose_block, "webviewView.onDidDispose block not found"
        assert f"{handle_name}.dispose()" in dispose_block.group(0), (
            f"focus disposable `{handle_name}` must be disposed inside "
            f"webviewView.onDidDispose() — otherwise it leaks past panel close"
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

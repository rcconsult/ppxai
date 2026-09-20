"""Pin the two GUI session-ending UI-button workflows.

Owner decision (2026-09-20): `/quit` is now a **terminal-only** slash
command (rich + textual). In the GUIs — the web app and the VSCode
extension — ending a session is a **UI button workflow**, not a slash
command, and that workflow must keep working exactly as today. This file
pins the two workflows so a later refactor (e.g. of `app.js`, the shared
`ApiClient`, the FastAPI routes, or the VSCode extension's command
registrations) cannot silently break either one.

1. **Web app header button** (`id="quitBtn"` in `ppxai/web/index.html`,
   wired in `ppxai/web/app.js`). `handleQuit()` has TWO modes:
     - **Desktop/local mode**: after a `confirm(...)`, it calls
       `this.apiClient.shutdown()`, which POSTs to `/shutdown`
       (`ppxai/web/shared/api-client.js`) — a route genuinely registered
       on the FastAPI app (`ppxai/server/routes/config.py`).
     - **Coder/hosted mode** (URL path prefix `/s/<id>`): after a
       `confirm(...)` it redirects to `/login` and returns WITHOUT
       calling shutdown, deliberately, so a shared server survives one
       tenant leaving. That redirect-and-return sits *inside* the
       path-prefix branch and precedes the local-mode `shutdown()` call
       in the function body.

   Per the concurrent-edit note: another agent is changing ONLY the
   button's visible label ("Quit" -> "Leave") and its `title` tooltip in
   `index.html`/`app.js`. Nothing here asserts on visible text or
   tooltip — only the element id, the click wiring, the two-branch
   control flow inside `handleQuit()`, and the `/shutdown` POST target.

2. **VSCode extension start/stop server commands**
   (`vscode-extension/package.json` declares `ppxai.startServer` /
   `ppxai.stopServer`; `vscode-extension/src/extension.ts` registers
   both and implements `startServer()` / `stopServer()`). `stopServer()`
   reaches the same `/shutdown` HTTP endpoint via `backend.shutdown()`
   (`httpClient.ts`), mirroring the web app's local-mode path.

Every assertion below is written as a small helper that takes SOURCE
TEXT (or parsed JSON / a list of route tuples) and raises
`AssertionError` on violation. Each helper is exercised against the real
files AND mutation-verified against a deliberately broken string
modeled on the exact regression it exists to catch — a check that
cannot fail is worse than none. The idiom (helper-plus-mutation, source
read via `Path.read_text`, brace-depth function-body extraction) follows
`tests/test_web_shared_modules.py` and the untracked
`tests/test_client_handled_commands_contract.py`; the extractor here is
a standalone copy, not an import, so this file stands alone.

Do NOT modify `ppxai/web/index.html` or `ppxai/web/app.js` from this
file's test run — they are being edited concurrently elsewhere.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import ppxai.server.http as http_module

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "ppxai" / "web"
INDEX_HTML_PATH = WEB_DIR / "index.html"
APP_JS_PATH = WEB_DIR / "app.js"
API_CLIENT_PATH = WEB_DIR / "shared" / "api-client.js"
VSCODE_PACKAGE_JSON_PATH = REPO_ROOT / "vscode-extension" / "package.json"
VSCODE_EXTENSION_TS_PATH = REPO_ROOT / "vscode-extension" / "src" / "extension.ts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# Standalone brace-depth extractor (mirrors the idiom in
# tests/test_client_handled_commands_contract.py; not imported from it).
# =============================================================================


def _extract_braced_body(src: str, signature_pattern: str) -> str:
    """Return the `{ ... }` body of the first construct whose signature
    matches `signature_pattern`, using brace-depth counting that skips
    over string/template literals and comments."""
    m = re.search(signature_pattern, src)
    if not m:
        raise AssertionError(f"signature not found: {signature_pattern!r}")
    start = src.index("{", m.end())
    i = start
    depth = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":
            quote = c
            i += 1
            while i < n and src[i] != quote:
                if src[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces: body for {signature_pattern!r} never closed")


# =============================================================================
# Part 1 — Web: quitBtn element + wiring
# =============================================================================


def assert_quit_button_element_declared(html_src: str) -> None:
    """A <button ... id="quitBtn" ...> must exist in the markup — the
    visible label/tooltip text is deliberately NOT checked here."""
    if not re.search(r"<button\b[^>]*\bid=\"quitBtn\"[^>]*>", html_src):
        raise AssertionError('no <button ... id="quitBtn" ...> found in index.html')


class TestQuitButtonElement:
    def test_real_index_html_declares_quit_button(self):
        src = _read(INDEX_HTML_PATH)
        assert_quit_button_element_declared(src)


class TestMutationQuitButtonElement:
    def test_rejects_missing_id(self):
        broken = '<button class="header-btn quit-btn" title="Leave">Leave</button>'
        with pytest.raises(AssertionError):
            assert_quit_button_element_declared(broken)

    def test_rejects_renamed_id(self):
        broken = '<button class="header-btn" id="leaveBtn" title="Leave">Leave</button>'
        with pytest.raises(AssertionError):
            assert_quit_button_element_declared(broken)

    def test_accepts_the_real_shape(self):
        ok = '<button class="header-btn quit-btn" id="quitBtn" title="anything">Leave</button>'
        assert_quit_button_element_declared(ok)  # must not raise


def assert_quit_button_looked_up(app_js_src: str) -> None:
    """`app.js` must look up `quitBtn` via `getElementById('quitBtn')`."""
    if not re.search(
        r"quitBtn\s*:\s*document\.getElementById\(\s*['\"]quitBtn['\"]\s*\)", app_js_src
    ):
        raise AssertionError("no quitBtn: document.getElementById('quitBtn') found in app.js")


def assert_quit_button_wired_to_handle_quit(app_js_src: str) -> None:
    """The `quitBtn` element's click listener must call `this.handleQuit()`."""
    if not re.search(
        r"this\.elements\.quitBtn\.addEventListener\(\s*['\"]click['\"]\s*,"
        r"\s*\(\)\s*=>\s*this\.handleQuit\(\)\s*\)",
        app_js_src,
    ):
        raise AssertionError(
            "quitBtn's click listener must call this.handleQuit() "
            "(this.elements.quitBtn.addEventListener('click', () => this.handleQuit()))"
        )


class TestQuitButtonWiring:
    def test_real_app_js_looks_up_quit_button(self):
        src = _read(APP_JS_PATH)
        assert_quit_button_looked_up(src)

    def test_real_app_js_wires_click_to_handle_quit(self):
        src = _read(APP_JS_PATH)
        assert_quit_button_wired_to_handle_quit(src)


class TestMutationQuitButtonWiring:
    def test_lookup_rejects_wrong_id(self):
        broken = "quitBtn: document.getElementById('leaveBtn'),"
        with pytest.raises(AssertionError):
            assert_quit_button_looked_up(broken)

    def test_lookup_accepts_real_shape(self):
        ok = "quitBtn: document.getElementById('quitBtn'),"
        assert_quit_button_looked_up(ok)  # must not raise

    def test_wiring_rejects_wrong_handler(self):
        broken = "this.elements.quitBtn.addEventListener('click', () => this.clearConversation());"
        with pytest.raises(AssertionError):
            assert_quit_button_wired_to_handle_quit(broken)

    def test_wiring_rejects_missing_listener(self):
        broken = "// quit button intentionally left unwired"
        with pytest.raises(AssertionError):
            assert_quit_button_wired_to_handle_quit(broken)

    def test_wiring_accepts_real_shape(self):
        ok = "this.elements.quitBtn.addEventListener('click', () => this.handleQuit());"
        assert_quit_button_wired_to_handle_quit(ok)  # must not raise


# =============================================================================
# Part 2 — Web: handleQuit() two-branch control flow
# =============================================================================


def _extract_if_block(src: str, condition_pattern: str) -> tuple[str, int, int]:
    """Return (block_text_including_braces, start_index, end_index) for the
    first `if (<condition_pattern>) { ... }` block in `src`."""
    m = re.search(condition_pattern, src)
    if not m:
        raise AssertionError(f"if-condition not found: {condition_pattern!r}")
    start = src.index("{", m.end())
    i = start
    depth = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":
            quote = c
            i += 1
            while i < n and src[i] != quote:
                if src[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1], start, i + 1
        i += 1
    raise AssertionError(f"unbalanced braces: if-block for {condition_pattern!r} never closed")


def assert_hosted_branch_redirects_and_returns_before_shutdown(handle_quit_body: str) -> None:
    """Inside `if (pathPrefix) { ... }`: must redirect to '/login' and
    `return`, must NOT call apiClient.shutdown() itself, and the whole
    if-block must appear BEFORE the local-mode `apiClient.shutdown()`
    call in the function body (so the hosted branch exits first)."""
    if_block, if_start, _if_end = _extract_if_block(handle_quit_body, r"if\s*\(\s*pathPrefix\s*\)\s*")

    login_match = re.search(r"/login", if_block)
    if not login_match:
        raise AssertionError("hosted-mode branch (if (pathPrefix)) must redirect to '/login'")
    # "return" must appear AFTER the redirect, not merely anywhere in the
    # block (an earlier "if (!confirmed) return;" for the confirm-cancel
    # path doesn't count — that's a different early exit).
    if "return" not in if_block[login_match.end() :]:
        raise AssertionError(
            "hosted-mode branch (if (pathPrefix)) must return AFTER the "
            "'/login' redirect, or it falls through to the local-mode "
            "shutdown() call"
        )
    if "apiClient.shutdown" in if_block:
        raise AssertionError(
            "hosted-mode branch (if (pathPrefix)) must NOT call apiClient.shutdown() "
            "— a shared/hosted server must not be killed by one tenant leaving"
        )

    shutdown_match = re.search(r"apiClient\.shutdown\(\)", handle_quit_body)
    if not shutdown_match:
        raise AssertionError("no apiClient.shutdown() call found in handleQuit() at all")
    if not if_start < shutdown_match.start():
        raise AssertionError(
            "the if (pathPrefix) hosted-mode branch must appear BEFORE the "
            "local-mode apiClient.shutdown() call in handleQuit()"
        )


def assert_local_branch_calls_shutdown(handle_quit_body: str) -> None:
    """Outside the hosted branch, `handleQuit()` must call
    `this.apiClient.shutdown()` (desktop/local mode)."""
    if not re.search(r"this\.apiClient\.shutdown\(\)", handle_quit_body):
        raise AssertionError(
            "handleQuit() must call this.apiClient.shutdown() in the "
            "desktop/local-mode branch"
        )


class TestHandleQuitControlFlow:
    def _body(self) -> str:
        src = _read(APP_JS_PATH)
        return _extract_braced_body(src, r"async handleQuit\(\)\s*")

    def test_hosted_branch_redirects_and_returns_before_shutdown(self):
        assert_hosted_branch_redirects_and_returns_before_shutdown(self._body())

    def test_local_branch_calls_shutdown(self):
        assert_local_branch_calls_shutdown(self._body())


class TestMutationHandleQuitControlFlow:
    _REAL_SHAPE = """
    async handleQuit() {
        const pathPrefix = window.location.pathname.match(/^(\\/s\\/[^/]+)/)?.[1] || '';

        if (pathPrefix) {
            const confirmed = confirm('Leave this session and return to login?');
            if (!confirmed) return;
            window.location.href = '/login';
            return;
        }

        const confirmed = confirm('Stop the ppxai server and close this tab?');
        if (!confirmed) return;

        try {
            await this.apiClient.shutdown();
        } catch (error) {
            console.log('Server shutdown (connection closed as expected)');
        }

        window.close();
    }
    """

    def test_accepts_the_real_shape_hosted(self):
        body = _extract_braced_body(self._REAL_SHAPE, r"async handleQuit\(\)\s*")
        assert_hosted_branch_redirects_and_returns_before_shutdown(body)  # must not raise

    def test_accepts_the_real_shape_local(self):
        body = _extract_braced_body(self._REAL_SHAPE, r"async handleQuit\(\)\s*")
        assert_local_branch_calls_shutdown(body)  # must not raise

    def test_rejects_hosted_branch_missing_return(self):
        broken = self._REAL_SHAPE.replace(
            "window.location.href = '/login';\n            return;",
            "window.location.href = '/login';",
        )
        body = _extract_braced_body(broken, r"async handleQuit\(\)\s*")
        with pytest.raises(AssertionError):
            assert_hosted_branch_redirects_and_returns_before_shutdown(body)

    def test_rejects_hosted_branch_missing_redirect(self):
        broken = self._REAL_SHAPE.replace("window.location.href = '/login';\n            ", "")
        body = _extract_braced_body(broken, r"async handleQuit\(\)\s*")
        with pytest.raises(AssertionError):
            assert_hosted_branch_redirects_and_returns_before_shutdown(body)

    def test_rejects_hosted_branch_that_also_shuts_down(self):
        broken = self._REAL_SHAPE.replace(
            "window.location.href = '/login';\n            return;",
            "window.location.href = '/login';\n            await this.apiClient.shutdown();\n            return;",
        )
        body = _extract_braced_body(broken, r"async handleQuit\(\)\s*")
        with pytest.raises(AssertionError):
            assert_hosted_branch_redirects_and_returns_before_shutdown(body)

    def test_rejects_shutdown_call_moved_before_hosted_branch(self):
        broken = """
        async handleQuit() {
            await this.apiClient.shutdown();
            const pathPrefix = window.location.pathname.match(/^(\\/s\\/[^/]+)/)?.[1] || '';
            if (pathPrefix) {
                window.location.href = '/login';
                return;
            }
        }
        """
        body = _extract_braced_body(broken, r"async handleQuit\(\)\s*")
        with pytest.raises(AssertionError):
            assert_hosted_branch_redirects_and_returns_before_shutdown(body)

    def test_rejects_missing_local_shutdown_call(self):
        broken = self._REAL_SHAPE.replace("await this.apiClient.shutdown();", "// removed")
        body = _extract_braced_body(broken, r"async handleQuit\(\)\s*")
        with pytest.raises(AssertionError):
            assert_local_branch_calls_shutdown(body)


# =============================================================================
# Part 3 — Web: ApiClient.shutdown() -> POST /shutdown
# =============================================================================


def assert_shutdown_posts_to_shutdown_endpoint(shutdown_method_body: str) -> None:
    if not re.search(r"this\.post\(\s*['\"]/shutdown['\"]\s*\)", shutdown_method_body):
        raise AssertionError("ApiClient.shutdown() must call this.post('/shutdown')")


class TestApiClientShutdown:
    def test_real_shutdown_posts_to_shutdown_endpoint(self):
        src = _read(API_CLIENT_PATH)
        body = _extract_braced_body(src, r"async shutdown\(\)\s*")
        assert_shutdown_posts_to_shutdown_endpoint(body)


class TestMutationApiClientShutdown:
    def test_rejects_wrong_endpoint(self):
        broken = "async shutdown() {\n        return this.post('/stop');\n    }"
        body = _extract_braced_body(broken, r"async shutdown\(\)\s*")
        with pytest.raises(AssertionError):
            assert_shutdown_posts_to_shutdown_endpoint(body)

    def test_rejects_get_instead_of_post(self):
        broken = "async shutdown() {\n        return this.get('/shutdown');\n    }"
        body = _extract_braced_body(broken, r"async shutdown\(\)\s*")
        with pytest.raises(AssertionError):
            assert_shutdown_posts_to_shutdown_endpoint(body)

    def test_accepts_the_real_shape(self):
        ok = "async shutdown() {\n        return this.post('/shutdown');\n    }"
        body = _extract_braced_body(ok, r"async shutdown\(\)\s*")
        assert_shutdown_posts_to_shutdown_endpoint(body)  # must not raise


# =============================================================================
# Part 4 — Server: POST /shutdown is a genuinely registered FastAPI route.
#
# Prefer a real route check over source text (per task instructions): the
# helper takes a list of (path, methods) tuples so it can be exercised
# against a real FastAPI app's routes AND a mutation-test fake list, but
# the real-route test below extracts that list from the live app object,
# never from source text.
# =============================================================================


def assert_shutdown_route_registered(routes: list[tuple[str, frozenset[str]]]) -> None:
    for path, methods in routes:
        if path == "/shutdown" and "POST" in methods:
            return
    raise AssertionError("no POST /shutdown route registered")


class TestShutdownRouteRegistered:
    def test_real_app_registers_post_shutdown(self):
        pytest.importorskip("fastapi")

        routes = [
            (getattr(r, "path", None), frozenset(getattr(r, "methods", None) or ()))
            for r in http_module.app.routes
        ]
        assert_shutdown_route_registered(routes)


class TestMutationShutdownRouteRegistered:
    def test_rejects_missing_route(self):
        fake_routes = [("/health", frozenset({"GET"})), ("/status", frozenset({"GET"}))]
        with pytest.raises(AssertionError):
            assert_shutdown_route_registered(fake_routes)

    def test_rejects_shutdown_without_post(self):
        fake_routes = [("/shutdown", frozenset({"GET"}))]
        with pytest.raises(AssertionError):
            assert_shutdown_route_registered(fake_routes)

    def test_accepts_the_real_shape(self):
        fake_routes = [("/health", frozenset({"GET"})), ("/shutdown", frozenset({"POST"}))]
        assert_shutdown_route_registered(fake_routes)  # must not raise


# =============================================================================
# Part 5 — VSCode: package.json declares startServer/stopServer commands.
# =============================================================================


def assert_commands_declared(commands: list[dict], expected_ids: set[str]) -> None:
    declared = {c.get("command") for c in commands if isinstance(c, dict)}
    missing = expected_ids - declared
    if missing:
        raise AssertionError(f"package.json contributes.commands missing: {sorted(missing)}")


class TestVscodePackageJsonCommands:
    def test_real_package_json_declares_start_and_stop(self):
        data = json.loads(_read(VSCODE_PACKAGE_JSON_PATH))
        commands = data["contributes"]["commands"]
        assert_commands_declared(commands, {"ppxai.startServer", "ppxai.stopServer"})


class TestMutationVscodePackageJsonCommands:
    def test_rejects_missing_stop_server(self):
        commands = [{"command": "ppxai.startServer", "title": "Start Server"}]
        with pytest.raises(AssertionError):
            assert_commands_declared(commands, {"ppxai.startServer", "ppxai.stopServer"})

    def test_rejects_missing_start_server(self):
        commands = [{"command": "ppxai.stopServer", "title": "Stop Server"}]
        with pytest.raises(AssertionError):
            assert_commands_declared(commands, {"ppxai.startServer", "ppxai.stopServer"})

    def test_accepts_the_real_shape(self):
        commands = [
            {"command": "ppxai.startServer", "title": "Start Server"},
            {"command": "ppxai.stopServer", "title": "Stop Server"},
        ]
        assert_commands_declared(commands, {"ppxai.startServer", "ppxai.stopServer"})  # must not raise


# =============================================================================
# Part 6 — VSCode: registerCommand handlers reach start/stop, and
# stopServer() reaches the /shutdown HTTP call (mirrors the web app's
# local-mode path via the shared backend.shutdown()).
# =============================================================================


def _extract_register_command_body(src: str, command_id: str) -> str:
    pattern = r"registerCommand\(\s*['\"]" + re.escape(command_id) + r"['\"]"
    return _extract_braced_body(src, pattern)


def assert_register_command_calls(handler_body: str, called_fn: str) -> None:
    if called_fn + "(" not in handler_body:
        raise AssertionError(f"registerCommand handler body must call {called_fn}(...)")


def assert_stop_server_reaches_shutdown(stop_server_body: str) -> None:
    if "backend.shutdown()" not in stop_server_body:
        raise AssertionError(
            "stopServer() must call backend.shutdown() (the same HTTP "
            "/shutdown path the web app's local-mode handleQuit() uses)"
        )


class TestVscodeCommandRegistrations:
    def test_start_server_command_calls_start_server(self):
        src = _read(VSCODE_EXTENSION_TS_PATH)
        body = _extract_register_command_body(src, "ppxai.startServer")
        assert_register_command_calls(body, "startServer")

    def test_stop_server_command_calls_stop_server(self):
        src = _read(VSCODE_EXTENSION_TS_PATH)
        body = _extract_register_command_body(src, "ppxai.stopServer")
        assert_register_command_calls(body, "stopServer")

    def test_stop_server_function_reaches_backend_shutdown(self):
        src = _read(VSCODE_EXTENSION_TS_PATH)
        body = _extract_braced_body(src, r"export async function stopServer\(\)[^{]*")
        assert_stop_server_reaches_shutdown(body)

    def test_start_server_function_calls_backend_start(self):
        """Sibling fact, pinned alongside stop: startServer() must reach
        backend.start() (not just spawn a terminal)."""
        src = _read(VSCODE_EXTENSION_TS_PATH)
        body = _extract_braced_body(src, r"export async function startServer\(\)[^{]*")
        if "backend.start()" not in body:
            raise AssertionError("startServer() must call backend.start()")


class TestVscodeToggleAndStatusAffordances:
    """The extension exposes no commands literally named "connect"/
    "disconnect"; the closest affordances beyond startServer/stopServer
    are ppxai.toggleServer (flips start<->stop) and ppxai.serverStatus
    (reports status, offers a "Start Server" action when down). Pinned
    here so their existence and wiring is not lost to a future refactor
    even though the task's minimum bar was startServer/stopServer."""

    def test_toggle_server_command_calls_toggle_server(self):
        src = _read(VSCODE_EXTENSION_TS_PATH)
        body = _extract_register_command_body(src, "ppxai.toggleServer")
        assert_register_command_calls(body, "toggleServer")

    def test_toggle_server_function_calls_both_start_and_stop(self):
        src = _read(VSCODE_EXTENSION_TS_PATH)
        body = _extract_braced_body(src, r"export async function toggleServer\(\)[^{]*")
        if "stopServer()" not in body or "startServer()" not in body:
            raise AssertionError("toggleServer() must call both stopServer() and startServer()")

    def test_server_status_command_registered(self):
        src = _read(VSCODE_EXTENSION_TS_PATH)
        # Just existence + that it can offer to start the server when down.
        body = _extract_register_command_body(src, "ppxai.serverStatus")
        if "startServer()" not in body:
            raise AssertionError(
                "ppxai.serverStatus handler should offer to startServer() when not running"
            )


class TestMutationVscodeCommandRegistrations:
    def test_rejects_handler_that_never_calls_stop_server(self):
        broken = """
        vscode.commands.registerCommand('ppxai.stopServer', async () => {
            vscode.window.showInformationMessage('stopping (not really)');
        })
        """
        body = _extract_register_command_body(broken, "ppxai.stopServer")
        with pytest.raises(AssertionError):
            assert_register_command_calls(body, "stopServer")

    def test_rejects_handler_that_calls_wrong_function(self):
        broken = """
        vscode.commands.registerCommand('ppxai.startServer', async () => {
            await stopServer();
        })
        """
        body = _extract_register_command_body(broken, "ppxai.startServer")
        with pytest.raises(AssertionError):
            assert_register_command_calls(body, "startServer")

    def test_accepts_the_real_stop_shape(self):
        ok = """
        vscode.commands.registerCommand('ppxai.stopServer', async () => {
            await stopServer();
        })
        """
        body = _extract_register_command_body(ok, "ppxai.stopServer")
        assert_register_command_calls(body, "stopServer")  # must not raise

    def test_rejects_stop_server_that_drops_backend_shutdown(self):
        broken = """
        export async function stopServer(): Promise<void> {
            if (serverTerminal) {
                serverTerminal.dispose();
                serverTerminal = undefined;
            }
            notifyServerStatus(false);
        }
        """
        body = _extract_braced_body(broken, r"export async function stopServer\(\)[^{]*")
        with pytest.raises(AssertionError):
            assert_stop_server_reaches_shutdown(body)

    def test_accepts_the_real_stop_server_shape(self):
        ok = """
        export async function stopServer(): Promise<void> {
            try {
                await backend.shutdown();
            } catch (error) {
                console.log('already down');
            }
            notifyServerStatus(false);
        }
        """
        body = _extract_braced_body(ok, r"export async function stopServer\(\)[^{]*")
        assert_stop_server_reaches_shutdown(body)  # must not raise

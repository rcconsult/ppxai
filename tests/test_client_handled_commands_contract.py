"""Characterization tests for the client-handled commands, pre-migration.

`docs/plan-adr-0007-completion-service.md` §"Migrating the client-handled
commands — the correctness contract" is about to move `/token` (and the
other client-side commands) into the Python `CommandFactory` registry. That
move is only "correct" if four behaviours survive unchanged; this file pins
**behaviours 1 and 4** from that section BEFORE the migration lands, so a
regression shows up as a failing test here rather than as a discovered
production incident.

Behaviour 1 — client gating (`ppxai/engine/completion.py`):
`_client_allows()` fails OPEN for `client=None` (legacy/unknown callers see
everything). That is deliberate, not an oversight, and the plan says it
"moves onto the spec unchanged, or it is changed deliberately — not by
accident." Part A pins the gate: `/token` is `{web, vscode}`-only, and
`/quit` is `{rich, textual}`-only (owner decision, 2026-09-20 — REVERSES
the earlier "universal" call: in a GUI, ending the session is a UI button
workflow, not a command), and `complete()` reflects both end to end. ADR
0007 step 1b moved WHERE the gate is stored (from the hand-written
`_CLIENT_GATES` table to `CommandSpec.clients`, read via `_gate_for`);
every assertion in Part A except `/quit`'s gate table is unchanged, which
is the point — `client=None` still fails OPEN.

Behaviour 4 — `/token set <value>` never transits command dispatch. The
handler treats the value as a secret (bare `/token set` uses a masked
prompt instead of inline text specifically so the value is never echoed).
If a registered spec caused `/token set <value>` to be POSTed to
`/command/token`, the secret would land in a command body and in server
logs (every dispatched line is echoed to the debug log). `client_handled`
must mean "dispatch happens in the client", not "forward to the server and
let it refuse". Part B pins this as a SOURCE-TEXT contract against
`ppxai/web/shared/command-dispatcher.js` and
`vscode-extension/src/chatPanel.ts`, following the source-reading idiom in
`tests/test_web_shared_modules.py` (plain `Path.read_text`, structural
regex/substring assertions — no JS runtime).

Every Part B assertion is written as a small helper that takes SOURCE TEXT
in and raises `AssertionError` on violation, then mutation-verified in this
same file: each helper is fed a deliberately broken string modeled on the
exact regression it exists to catch (branch order swapped, an extra
dispatch-to-factory call injected, an extra network call added) and must
reject it. A check that cannot fail is worse than none — this repo's
convention (`tests/test_no_new_lazy_imports.py`) is that guards are tested
first. Part A's equivalent liveness proof is a `monkeypatch` on
`_gate_for`: it shows the gating assertions track live state rather
than being vacuously true.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Trigger side-effect registrations so CommandFactory is populated (same
# idiom as tests/test_completion_provider.py) — needed for complete() end
# to end even though Part A's unit-level checks don't touch the factory.
import ppxai.commands.handler  # noqa: F401
import ppxai.engine.completion as completion_mod
from ppxai.engine.completion import _client_allows, complete

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DISPATCHER_PATH = REPO_ROOT / "ppxai" / "web" / "shared" / "command-dispatcher.js"
VSCODE_CHATPANEL_PATH = REPO_ROOT / "vscode-extension" / "src" / "chatPanel.ts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# Part A — client gating (ppxai/engine/completion.py)
# =============================================================================


class TestClientAllowsFailsOpenForNone:
    """`client=None` (legacy/unknown caller) must see everything, unchanged."""

    def test_gated_name_allowed_for_none_client(self):
        assert _client_allows("token", None) is True

    def test_other_gated_name_allowed_for_none_client(self):
        # Owner decision (2026-09-20) gated /quit to {rich, textual}, so
        # it no longer illustrates the "ungated name" case; the fail-open
        # semantics for client=None is unchanged and still worth pinning
        # against a second, independently-gated command.
        assert _client_allows("quit", None) is True


class TestTokenGateTable:
    """`/token` is web+vscode-only today; rich/textual are denied."""

    def test_token_allowed_for_web(self):
        assert _client_allows("token", "web") is True

    def test_token_allowed_for_vscode(self):
        assert _client_allows("token", "vscode") is True

    def test_token_denied_for_rich(self):
        assert _client_allows("token", "rich") is False

    def test_token_denied_for_textual(self):
        assert _client_allows("token", "textual") is False


class TestQuitGateTable:
    """`/quit` is rich+textual-only (owner decision, 2026-09-20): ending a
    GUI session is a button workflow, not a command. `client=None` still
    fails open (legacy/unknown callers see everything)."""

    def test_quit_allowed_for_rich(self):
        assert _client_allows("quit", "rich") is True

    def test_quit_allowed_for_textual(self):
        assert _client_allows("quit", "textual") is True

    def test_quit_allowed_for_none(self):
        assert _client_allows("quit", None) is True

    def test_quit_denied_for_web(self):
        assert _client_allows("quit", "web") is False

    def test_quit_denied_for_vscode(self):
        assert _client_allows("quit", "vscode") is False


class TestCompleteEndToEnd:
    """`complete()` must apply the same gate through the public entry point,
    not just at the `_client_allows` unit level. Items are dicts with a
    stable `text` key (see the module docstring's schema)."""

    def test_token_prefix_surfaces_for_web_vscode_and_none(self):
        for client in ("web", "vscode", None):
            items = complete("/tok", client=client)
            texts = {i["text"] for i in items}
            assert "/token" in texts, (client, texts)

    def test_token_prefix_absent_for_rich_and_textual(self):
        for client in ("rich", "textual"):
            items = complete("/tok", client=client)
            texts = {i["text"] for i in items}
            assert "/token" not in texts, (client, texts)

    def test_quit_prefix_surfaces_for_rich_textual_and_none(self):
        # Owner decision (2026-09-20): /quit is rich+textual-only.
        for client in ("rich", "textual", None):
            items = complete("/qu", client=client)
            texts = {i["text"] for i in items}
            assert "/quit" in texts, (client, texts)

    def test_quit_prefix_absent_for_web_and_vscode(self):
        for client in ("web", "vscode"):
            items = complete("/qu", client=client)
            texts = {i["text"] for i in items}
            assert "/quit" not in texts, (client, texts)


def _rich_only_gate(name: str):
    """Stand-in for `completion._gate_for` that inverts `/token`'s gate."""
    return frozenset({"rich"}) if name == "token" else None


class TestGatingAssertionsAreLive:
    """Prove the assertions above are exercising the live gate, not just
    passing by accident, by monkeypatching it and showing the outcome
    changes — both at the `_client_allows` level and through `complete()`.

    ADR 0007 step 1b changed the lever, not the check: the gate table
    `_CLIENT_GATES` (built from the hand-written
    `_BUILTIN_SPECIAL_COMMANDS` roster) is gone, and `_client_allows`
    now reads `CommandSpec.clients` off the registry through
    `_gate_for(name)`. Patching that function is the same proof, one
    level down.
    """

    def test_monkeypatched_gate_flips_client_allows(self, monkeypatch):
        monkeypatch.setattr(completion_mod, "_gate_for", _rich_only_gate)
        assert _client_allows("token", "rich") is True
        assert _client_allows("token", "web") is False

    def test_monkeypatched_gate_flips_complete(self, monkeypatch):
        monkeypatch.setattr(completion_mod, "_gate_for", _rich_only_gate)
        rich_texts = {i["text"] for i in complete("/tok", client="rich")}
        web_texts = {i["text"] for i in complete("/tok", client="web")}
        assert "/token" in rich_texts
        assert "/token" not in web_texts


# =============================================================================
# Part B — `/token` never transits command dispatch (source-text contract)
# =============================================================================
#
# The idiom (from tests/test_web_shared_modules.py): read the real source
# file as text and assert structurally, without a JS/TS runtime. Each
# assertion below is factored into a helper that takes SOURCE TEXT and
# raises AssertionError on violation, so it can be exercised both against
# the real file (below) and against a deliberately broken string (mutation
# tests further down) to prove it can actually fail.


def _extract_braced_body(src: str, signature_pattern: str) -> str:
    """Return the `{ ... }` body of the first function/method whose
    signature matches `signature_pattern`, using brace-depth counting that
    skips over string/template literals and comments (so a stray `{`/`}`
    inside a message string, e.g. an emoji status line with a template
    literal, can't unbalance the count).
    """
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


def assert_web_token_branch_precedes_factory_dispatch(dispatch_body: str) -> None:
    """`cmd === '/token'` must appear (and return) before the default
    `_dispatchToFactory(` fallthrough inside `dispatch()`."""
    token_match = re.search(r"cmd === '/token'", dispatch_body)
    factory_match = re.search(r"_dispatchToFactory\(", dispatch_body)
    if not token_match:
        raise AssertionError("no \"cmd === '/token'\" branch found in dispatch()")
    if not factory_match:
        raise AssertionError("no _dispatchToFactory( call found in dispatch()")
    if not token_match.start() < factory_match.start():
        raise AssertionError(
            "the /token branch must appear BEFORE the default _dispatchToFactory( "
            "dispatch, or /token set <value> could be forwarded to "
            "POST /command/token"
        )
    between = dispatch_body[token_match.start() : factory_match.start()]
    if "return" not in between:
        raise AssertionError(
            "the /token branch does not return before falling through to "
            "_dispatchToFactory("
        )


def assert_web_token_handler_never_calls_factory_dispatch(handler_body: str) -> None:
    """`_handleTokenCommand`'s body must never call `_dispatchToFactory(`
    and must never reference a `/command/` URL."""
    if "_dispatchToFactory(" in handler_body:
        raise AssertionError("_handleTokenCommand must never call _dispatchToFactory(")
    if "/command/" in handler_body:
        raise AssertionError("_handleTokenCommand must never reference a /command/ URL")


def assert_web_token_handler_single_network_call(handler_body: str) -> None:
    """`_handleTokenCommand`'s only network path must be the `mint` verb's
    `POST /v1/tokens` (loopback bootstrap). Everything else in the method
    (status/set/clear) is local (localStorage + in-memory ApiClient)."""
    api_calls = re.findall(
        r"\bapi\.(post|get|put|delete|patch)\(\s*['\"]([^'\"]+)['\"]", handler_body
    )
    fetch_calls = re.findall(r"\bfetch\(", handler_body)
    total = len(api_calls) + len(fetch_calls)
    if total != 1:
        raise AssertionError(
            "_handleTokenCommand must have exactly ONE network call "
            f"(mint -> POST /v1/tokens); found {total}: "
            f"api calls={api_calls!r}, fetch calls={len(fetch_calls)}"
        )
    if api_calls != [("post", "/v1/tokens")]:
        raise AssertionError(
            f"the one network call must be api.post('/v1/tokens', ...); found {api_calls!r}"
        )


def assert_vscode_token_branch_precedes_factory_dispatch(method_body: str) -> None:
    """`command === 'token'` must appear (and return) before
    `dispatchFactoryCommand(command, argsText)` inside `handleSlashCommand`."""
    token_match = re.search(r"command === 'token'", method_body)
    factory_match = re.search(
        r"dispatchFactoryCommand\(command, argsText\)", method_body
    )
    if not token_match:
        raise AssertionError("no \"command === 'token'\" branch found in handleSlashCommand()")
    if not factory_match:
        raise AssertionError(
            "no dispatchFactoryCommand(command, argsText) call found in handleSlashCommand()"
        )
    if not token_match.start() < factory_match.start():
        raise AssertionError(
            "the command === 'token' branch must appear BEFORE "
            "dispatchFactoryCommand(command, argsText), or /token set <value> "
            "could be forwarded to POST /command/token"
        )
    between = method_body[token_match.start() : factory_match.start()]
    if "return" not in between:
        raise AssertionError(
            "the command === 'token' branch does not return before falling "
            "through to dispatchFactoryCommand"
        )


def assert_vscode_token_handler_never_calls_factory_dispatch(handler_body: str) -> None:
    """`handleTokenCommand`'s body must never call `dispatchFactoryCommand`."""
    if "dispatchFactoryCommand" in handler_body:
        raise AssertionError("handleTokenCommand must never call dispatchFactoryCommand")


# -----------------------------------------------------------------------
# Real-source pins
# -----------------------------------------------------------------------


class TestWebDispatcherSourceExists:
    def test_file_exists(self):
        assert WEB_DISPATCHER_PATH.exists()


class TestWebTokenBranchOrder:
    def test_token_branch_precedes_factory_dispatch(self):
        src = _read(WEB_DISPATCHER_PATH)
        dispatch_body = _extract_braced_body(src, r"async dispatch\(input\)\s*")
        assert_web_token_branch_precedes_factory_dispatch(dispatch_body)

    def test_extraction_stops_at_dispatch_method_end(self):
        """Sanity check on the extractor itself: the extracted dispatch()
        body must not bleed into the next method's own body (proves the
        brace-depth counter is bounding the right method, not just finding
        the first `return` anywhere in the file)."""
        src = _read(WEB_DISPATCHER_PATH)
        dispatch_body = _extract_braced_body(src, r"async dispatch\(input\)\s*")
        # _dispatchAgent's own doc comment text lives strictly after
        # dispatch() closes.
        assert "/auto has three shapes" not in dispatch_body


class TestWebTokenHandlerNeverDispatchesToFactory:
    def test_handler_body(self):
        src = _read(WEB_DISPATCHER_PATH)
        handler_body = _extract_braced_body(src, r"async _handleTokenCommand\(args\)\s*")
        assert_web_token_handler_never_calls_factory_dispatch(handler_body)

    def test_handler_single_network_call(self):
        src = _read(WEB_DISPATCHER_PATH)
        handler_body = _extract_braced_body(src, r"async _handleTokenCommand\(args\)\s*")
        assert_web_token_handler_single_network_call(handler_body)


class TestVscodeChatPanelSourceExists:
    def test_file_exists(self):
        assert VSCODE_CHATPANEL_PATH.exists()


class TestVscodeTokenBranchOrder:
    def test_token_branch_precedes_factory_dispatch(self):
        src = _read(VSCODE_CHATPANEL_PATH)
        method_body = _extract_braced_body(
            src, r"private async handleSlashCommand\(input: string\)\s*"
        )
        assert_vscode_token_branch_precedes_factory_dispatch(method_body)


class TestVscodeTokenHandlerNeverDispatchesToFactory:
    def test_handler_body(self):
        src = _read(VSCODE_CHATPANEL_PATH)
        handler_body = _extract_braced_body(
            src, r"private async handleTokenCommand\(argsText: string\): Promise<void>\s*"
        )
        assert_vscode_token_handler_never_calls_factory_dispatch(handler_body)


# =============================================================================
# Mutation verification — every Part B assertion must be able to fail.
# =============================================================================
#
# Each helper above is fed a deliberately broken string modeled on the
# exact regression it exists to catch, and must reject it. A guard that
# only ever sees passing input is not a guard.


class TestMutationWebTokenBranchOrder:
    def test_rejects_branch_after_factory_dispatch(self):
        broken = """
        async dispatch(input) {
            await this._dispatchToFactory(cmd.slice(1), args);
            if (cmd === '/token') {
                await this._handleTokenCommand(args);
                return;
            }
        }
        """
        with pytest.raises(AssertionError):
            assert_web_token_branch_precedes_factory_dispatch(broken)

    def test_rejects_branch_that_falls_through_without_return(self):
        broken = """
        async dispatch(input) {
            if (cmd === '/token') {
                await this._handleTokenCommand(args);
            }
            await this._dispatchToFactory(cmd.slice(1), args);
        }
        """
        with pytest.raises(AssertionError):
            assert_web_token_branch_precedes_factory_dispatch(broken)

    def test_rejects_missing_token_branch(self):
        broken = """
        async dispatch(input) {
            await this._dispatchToFactory(cmd.slice(1), args);
        }
        """
        with pytest.raises(AssertionError):
            assert_web_token_branch_precedes_factory_dispatch(broken)

    def test_accepts_the_real_shape(self):
        ok = """
        async dispatch(input) {
            if (cmd === '/token') {
                await this._handleTokenCommand(args);
                return;
            }
            await this._dispatchToFactory(cmd.slice(1), args);
        }
        """
        assert_web_token_branch_precedes_factory_dispatch(ok)  # must not raise


class TestMutationWebTokenHandlerNeverDispatches:
    def test_rejects_injected_factory_dispatch_call(self):
        broken = """
        async _handleTokenCommand(args) {
            switch (verb) {
                case 'status':
                    return;
                default:
                    await this._dispatchToFactory('token', args);
            }
        }
        """
        with pytest.raises(AssertionError):
            assert_web_token_handler_never_calls_factory_dispatch(broken)

    def test_rejects_injected_command_url(self):
        broken = """
        async _handleTokenCommand(args) {
            await fetch('/command/token', { method: 'POST' });
        }
        """
        with pytest.raises(AssertionError):
            assert_web_token_handler_never_calls_factory_dispatch(broken)

    def test_accepts_the_real_shape(self):
        ok = """
        async _handleTokenCommand(args) {
            const resp = await api.post('/v1/tokens', { owner: 'web-local' });
        }
        """
        assert_web_token_handler_never_calls_factory_dispatch(ok)  # must not raise


class TestMutationWebTokenHandlerSingleNetworkCall:
    def test_rejects_a_second_network_call(self):
        broken = """
        async _handleTokenCommand(args) {
            const resp = await api.post('/v1/tokens', { owner: 'web-local' });
            await api.post('/v1/audit', { event: 'token_mint' });
        }
        """
        with pytest.raises(AssertionError):
            assert_web_token_handler_single_network_call(broken)

    def test_rejects_wrong_url(self):
        broken = """
        async _handleTokenCommand(args) {
            const resp = await api.post('/command/token', { verb: 'mint' });
        }
        """
        with pytest.raises(AssertionError):
            assert_web_token_handler_single_network_call(broken)

    def test_rejects_zero_network_calls(self):
        broken = """
        async _handleTokenCommand(args) {
            this.app.showSystemMessage('no network here');
        }
        """
        with pytest.raises(AssertionError):
            assert_web_token_handler_single_network_call(broken)

    def test_accepts_the_real_shape(self):
        ok = """
        async _handleTokenCommand(args) {
            const resp = await api.post('/v1/tokens', { owner: 'web-local', roles: [] });
        }
        """
        assert_web_token_handler_single_network_call(ok)  # must not raise


class TestMutationVscodeTokenBranchOrder:
    def test_rejects_branch_after_factory_dispatch(self):
        broken = """
        private async handleSlashCommand(input: string) {
            await this.dispatchFactoryCommand(command, argsText);
            if (command === 'token') {
                await this.handleTokenCommand(argsText);
                return;
            }
        }
        """
        with pytest.raises(AssertionError):
            assert_vscode_token_branch_precedes_factory_dispatch(broken)

    def test_rejects_branch_that_falls_through_without_return(self):
        broken = """
        private async handleSlashCommand(input: string) {
            if (command === 'token') {
                await this.handleTokenCommand(argsText);
            }
            await this.dispatchFactoryCommand(command, argsText);
        }
        """
        with pytest.raises(AssertionError):
            assert_vscode_token_branch_precedes_factory_dispatch(broken)

    def test_accepts_the_real_shape(self):
        ok = """
        private async handleSlashCommand(input: string) {
            if (command === 'token') {
                await this.handleTokenCommand(argsText);
                return;
            }
            await this.dispatchFactoryCommand(command, argsText);
        }
        """
        assert_vscode_token_branch_precedes_factory_dispatch(ok)  # must not raise


class TestMutationVscodeTokenHandlerNeverDispatches:
    def test_rejects_injected_factory_dispatch_call(self):
        broken = """
        private async handleTokenCommand(argsText: string): Promise<void> {
            switch (verb) {
                default:
                    await this.dispatchFactoryCommand('token', argsText);
            }
        }
        """
        with pytest.raises(AssertionError):
            assert_vscode_token_handler_never_calls_factory_dispatch(broken)

    def test_accepts_the_real_shape(self):
        ok = """
        private async handleTokenCommand(argsText: string): Promise<void> {
            const resp = await this._backend.mintApiToken('vscode-local');
        }
        """
        assert_vscode_token_handler_never_calls_factory_dispatch(ok)  # must not raise


class TestExtractBracedBodyMutationSafety:
    """The extractor itself must not be fooled by braces inside strings or
    template literals — otherwise a message string containing `{`/`}`
    could truncate the extracted body early and hide a real violation
    living later in the method."""

    def test_stray_braces_in_template_literal_do_not_unbalance(self):
        src = """
        async _handleTokenCommand(args) {
            this.app.showSystemMessage(`token ${masked(t)} } { stray`);
            await this._dispatchToFactory('token', args);
        }
        """
        body = _extract_braced_body(src, r"async _handleTokenCommand\(args\)\s*")
        assert "_dispatchToFactory" in body

    def test_stray_brace_in_plain_string_does_not_unbalance(self):
        src = """
        async _handleTokenCommand(args) {
            const weird = '}';
            await this._dispatchToFactory('token', args);
        }
        """
        body = _extract_braced_body(src, r"async _handleTokenCommand\(args\)\s*")
        assert "_dispatchToFactory" in body

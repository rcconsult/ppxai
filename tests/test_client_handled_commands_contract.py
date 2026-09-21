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

**The WEB half of Part B was rewritten for ADR 0007 step 3a
(2026-09-21).** It used to pin `cmd === '/token'` appearing before the
default `_dispatchToFactory(` fallthrough — i.e. the guarantee was BRANCH
ORDER in a hardcoded `if`-chain. Step 3a deleted that chain: routing is
now the fetched roster's `dispatch` field, so the same guarantee has a
different shape and this file pins the new one:

  1. the FAIL-CLOSED gate (no roster → refuse) precedes every dispatch
     path in `dispatch()`, so with no roster NOTHING is POSTed;
  2. the `entry.dispatch === 'client'` branch precedes (and returns
     before) the default `_dispatchToFactory(`, so a command the roster
     marks client-dispatched is never POSTed;
  3. there is NO hardcoded `cmd === '/token'` escape hatch — a per-name
     special case would be exactly the second roster the record removes;
  4. the action registry implements every `client_action` web is
     declared for; and
  5. (unchanged) `_handleTokenCommand`'s only network path is still
     `POST /v1/tokens`.

Runtime behaviour of all of this — including "with no roster, `/token set
SECRET` makes zero requests and SECRET appears in no outgoing body" — is
exercised against the REAL dispatcher under Node in
`tests/test_web_command_roster_dispatch_behavior.py`. Source text and
runtime are deliberately both pinned: the source checks catch a
refactor that keeps the behaviour but loses the ordering guarantee, the
Node checks catch the reverse.

**Step 3b (2026-09-21) did the same to the VSCode half**, so the old
invariant here — `command === 'token'` precedes `dispatchFactoryCommand`
— deliberately no longer exists: `chatPanel.ts` has no per-command
branches left at all. The VSCode assertions below are the same five,
read off `vscode-extension/src/commandRouter.ts` (`route()`, the
`CLIENT_ACTIONS` registry) and `chatPanel.ts` (`handleTokenCommand`),
with ONE addition the web half does not need: the five
**acknowledged-legacy** intercepts (`/tools`, `/checkpoint`, `/context`,
`/ls`, `/tree`) have no `client_action` by owner decision ("do not bless
debt"), so they are consulted from a NAMED table after the gate. That
table is asserted to hold exactly those five and none of the declared
commands — it is step 5's shrinking baseline, and the assertion is what
stops it growing. Runtime behaviour is in
`tests/test_vscode_command_roster_behavior.py`, which compiles the real
TypeScript and drives it under Node.

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
from ppxai.commands.factory import CommandFactory
from ppxai.engine.completion import _client_allows, complete

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DISPATCHER_PATH = REPO_ROOT / "ppxai" / "web" / "shared" / "command-dispatcher.js"
VSCODE_CHATPANEL_PATH = REPO_ROOT / "vscode-extension" / "src" / "chatPanel.ts"
VSCODE_ROUTER_PATH = REPO_ROOT / "vscode-extension" / "src" / "commandRouter.ts"
VSCODE_ROSTER_PATH = REPO_ROOT / "vscode-extension" / "src" / "commandRoster.ts"

#: The five commands ADR 0007 step 3b keeps intercepting WITHOUT a
#: declared `client_action` ("do not bless debt"). Step 5's parity fence
#: inherits this as its baseline; it may only shrink.
LEGACY_INTERCEPT_BASELINE = frozenset(
    {"tools", "checkpoint", "context", "ls", "tree"}
)


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


#: Every outbound path `dispatch()` can take. The fail-closed gate must
#: precede all of them, so "no roster" means "nothing leaves the client".
_WEB_DISPATCH_PATHS = (
    r"_dispatchToFactory\(",
    r"_dispatchClientAction\(",
    r"streamChat\(",
)


def assert_web_fail_closed_gate_precedes_every_dispatch(dispatch_body: str) -> None:
    """The roster gate must be the FIRST thing `dispatch()` can leave on.

    ADR 0007 step 3a: routing is the fetched roster's `dispatch` field.
    With no roster the client cannot tell a client-handled command from a
    forwardable one, so it must refuse — not guess. Any dispatch path
    reachable before the gate reopens the `/token set <value>` leak.
    """
    gate = re.search(r"_readyRoster\(\)", dispatch_body)
    if not gate:
        raise AssertionError(
            "no _readyRoster() call found in dispatch() — the fail-closed gate is gone"
        )
    refusal = re.search(r"if \(!roster\)", dispatch_body[gate.end():])
    if not refusal:
        raise AssertionError(
            "dispatch() never checks the gate's result (`if (!roster)`) — a failed "
            "roster fetch would fall through to real dispatch"
        )
    refusal_end = gate.end() + refusal.end()
    if "return" not in dispatch_body[refusal_end: refusal_end + 200]:
        raise AssertionError(
            "the no-roster branch does not return — it must refuse, not fall through"
        )
    for pattern in _WEB_DISPATCH_PATHS:
        m = re.search(pattern, dispatch_body)
        if m and m.start() < gate.start():
            raise AssertionError(
                f"dispatch path {pattern!r} is reachable BEFORE the _readyRoster() "
                "gate; with no roster it would still send the command"
            )


def assert_web_client_dispatch_precedes_factory_dispatch(dispatch_body: str) -> None:
    """A roster entry with `dispatch === 'client'` must be routed to the
    bundled implementation (and returned from) BEFORE the default
    `_dispatchToFactory(` fallthrough."""
    client_match = re.search(r"entry\.dispatch === 'client'", dispatch_body)
    factory_match = re.search(r"_dispatchToFactory\(", dispatch_body)
    if not client_match:
        raise AssertionError(
            "no \"entry.dispatch === 'client'\" branch found in dispatch() — routing "
            "is no longer roster-driven"
        )
    if not factory_match:
        raise AssertionError("no _dispatchToFactory( call found in dispatch()")
    if not client_match.start() < factory_match.start():
        raise AssertionError(
            "the roster's client-dispatch branch must appear BEFORE the default "
            "_dispatchToFactory(, or a client-handled command (e.g. /token set "
            "<value>) could be forwarded to POST /command/<name>"
        )
    between = dispatch_body[client_match.start(): factory_match.start()]
    if "return" not in between:
        raise AssertionError(
            "the client-dispatch branch does not return before falling through to "
            "_dispatchToFactory("
        )


def assert_web_has_no_per_name_escape_hatch(src: str) -> None:
    """No hardcoded `cmd === '/<name>'` branch may survive in the
    dispatcher.

    A "just for /token" special case would be a second roster — one name
    whose routing lives in JS again — which is the exact duplication ADR
    0007 exists to remove. Fail-closed is what protects `/token` now.
    """
    found = sorted(set(re.findall(r"cmd === '(/[a-z-]+)'", src)))
    if found:
        raise AssertionError(
            f"hardcoded per-command branches found in the dispatcher: {found}. "
            "Routing must come from the roster; a per-name escape hatch is a "
            "second source of truth."
        )


def assert_web_action_registry_implements(src: str, actions: set[str]) -> None:
    """`CommandDispatcher.CLIENT_ACTIONS` must implement every named
    `client_action` the server declares for web."""
    m = re.search(r"CommandDispatcher\.CLIENT_ACTIONS = \{(.*?)\n\s*\};", src, re.S)
    if not m:
        raise AssertionError("CommandDispatcher.CLIENT_ACTIONS registry not found")
    declared = set(re.findall(r"'([a-z]+\.[a-z]+)'\s*\(", m.group(1)))
    missing = actions - declared
    if missing:
        raise AssertionError(
            f"client actions declared in Python but not implemented by web: "
            f"{sorted(missing)} (registry has {sorted(declared)})"
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


#: Every outbound path `CommandRouter.route()` can take. The fail-closed
#: gate must precede all of them.
_VSCODE_DISPATCH_PATHS = (
    r"dispatchToFactory\(",
    r"_dispatchClientAction\(",
    r"this\._host\.legacy\[",
)


def assert_vscode_fail_closed_gate_precedes_every_dispatch(route_body: str) -> None:
    """The roster gate must be the FIRST thing `route()` can leave on.

    Same property step 3a gave web, and it matters MORE here: the
    extension host is a Node process with the developer's full
    privileges, and the extension versions independently of the server,
    so "older server, newer client" is an everyday state rather than an
    edge case.
    """
    gate = re.search(r"_readyRoster\(\)", route_body)
    if not gate:
        raise AssertionError(
            "no _readyRoster() call found in route() — the fail-closed gate is gone"
        )
    refusal = re.search(r"if \(!roster\)", route_body[gate.end():])
    if not refusal:
        raise AssertionError(
            "route() never checks the gate's result (`if (!roster)`) — a failed "
            "roster fetch would fall through to real dispatch"
        )
    refusal_end = gate.end() + refusal.end()
    if "return" not in route_body[refusal_end: refusal_end + 200]:
        raise AssertionError(
            "the no-roster branch does not return — it must refuse, not fall through"
        )
    for pattern in _VSCODE_DISPATCH_PATHS:
        m = re.search(pattern, route_body)
        if m and m.start() < gate.start():
            raise AssertionError(
                f"dispatch path {pattern!r} is reachable BEFORE the _readyRoster() "
                "gate; with no roster it would still run the command"
            )


def assert_vscode_client_dispatch_precedes_factory_dispatch(route_body: str) -> None:
    """A roster entry with `dispatch === 'client'` must be routed to the
    bundled implementation (and returned from) BEFORE the default
    `dispatchToFactory(` fallthrough."""
    client_match = re.search(r"entry\.dispatch === 'client'", route_body)
    factory_match = re.search(r"dispatchToFactory\(", route_body)
    if not client_match:
        raise AssertionError(
            "no \"entry.dispatch === 'client'\" branch found in route() — routing "
            "is no longer roster-driven"
        )
    if not factory_match:
        raise AssertionError("no dispatchToFactory( call found in route()")
    if not client_match.start() < factory_match.start():
        raise AssertionError(
            "the roster's client-dispatch branch must appear BEFORE the default "
            "dispatchToFactory(, or a client-handled command (e.g. /token set "
            "<value>) could be forwarded to POST /command/<name>"
        )
    between = route_body[client_match.start(): factory_match.start()]
    if "return" not in between:
        raise AssertionError(
            "the client-dispatch branch does not return before falling through to "
            "dispatchToFactory("
        )


def assert_vscode_has_no_per_name_escape_hatch(src: str) -> None:
    """No hardcoded `command === '<name>'` branch may survive in
    `chatPanel.ts`.

    A "just for /token" special case would be a second roster — one name
    whose routing lives in TS again. Fail-closed is what protects
    `/token` now. (`subcommand === '…'` inside a handler is a different
    thing and is excluded, exactly as the plan's grep recipe does.)
    """
    found = sorted(set(re.findall(
        r"(?:^|[^A-Za-z])command === '([a-z?-]+)'", src, re.M)))
    if found:
        raise AssertionError(
            f"hardcoded per-command branches found in chatPanel.ts: {found}. "
            "Routing must come from the roster; a per-name escape hatch is a "
            "second source of truth."
        )


def assert_vscode_legacy_table_is_exactly(src: str, expected: set[str]) -> None:
    """The named legacy table must hold EXACTLY the acknowledged five.

    Growing it would launder a new client-side intercept as debt; the
    owner's instruction was "do not bless debt", and step 5 inherits
    this list as a baseline that may only shrink. A declared command
    appearing here would also shadow its own `client_action`.
    """
    m = re.search(
        r"export const LEGACY_INTERCEPTS: readonly string\[\] = \[(.*?)\];",
        src, re.S)
    if not m:
        raise AssertionError("LEGACY_INTERCEPTS table not found in commandRouter.ts")
    names = set(re.findall(r"'([a-z-]+)'", m.group(1)))
    if names != expected:
        raise AssertionError(
            f"the legacy intercept table changed: {sorted(names)} "
            f"(baseline {sorted(expected)}). It may only SHRINK, and only by "
            "migrating a command to factory routing."
        )


def assert_vscode_action_registry_implements(src: str, actions: set[str]) -> None:
    """`CLIENT_ACTIONS` must implement every named `client_action` the
    server declares for vscode."""
    m = re.search(
        r"export const CLIENT_ACTIONS: Record<string, OpsAction> = \{(.*?)\n\s*\};",
        src, re.S)
    if not m:
        raise AssertionError("the CLIENT_ACTIONS registry was not found")
    declared = set(re.findall(r"'([a-z]+\.[a-z]+)':", m.group(1)))
    missing = actions - declared
    if missing:
        raise AssertionError(
            f"client actions declared in Python but not implemented by VSCode: "
            f"{sorted(missing)} (registry has {sorted(declared)})"
        )
    overlap = declared & LEGACY_INTERCEPT_BASELINE
    if overlap:
        raise AssertionError(
            f"a legacy name leaked into the action registry: {sorted(overlap)}"
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


class TestWebRosterDrivenDispatchOrder:
    """ADR 0007 step 3a replaced branch order with roster data; these pin
    the two orderings that still carry the `/token` guarantee."""

    def test_fail_closed_gate_precedes_every_dispatch_path(self):
        src = _read(WEB_DISPATCHER_PATH)
        dispatch_body = _extract_braced_body(src, r"async dispatch\(input\)\s*")
        assert_web_fail_closed_gate_precedes_every_dispatch(dispatch_body)

    def test_client_dispatch_precedes_factory_dispatch(self):
        src = _read(WEB_DISPATCHER_PATH)
        dispatch_body = _extract_braced_body(src, r"async dispatch\(input\)\s*")
        assert_web_client_dispatch_precedes_factory_dispatch(dispatch_body)

    def test_no_per_name_escape_hatch_remains(self):
        assert_web_has_no_per_name_escape_hatch(_read(WEB_DISPATCHER_PATH))

    def test_action_registry_implements_every_web_action(self):
        """Read the Python declaration, not a hand-copied list: every spec
        whose `client_action_clients` includes "web" must have a web
        implementation. This is a miniature of step 5's parity fence."""
        specs = CommandFactory.iter_completion_specs()
        web_actions = {
            info.client_action for info in specs
            if info.client_action
            and (info.client_action_clients is None
                 or "web" in info.client_action_clients)
            and (info.clients is None or "web" in info.clients)
        }
        assert web_actions, "no web client actions declared — declaration drift?"
        assert_web_action_registry_implements(_read(WEB_DISPATCHER_PATH), web_actions)

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


class TestVscodeRouterSourceExists:
    def test_router_and_roster_exist(self):
        assert VSCODE_ROUTER_PATH.exists()
        assert VSCODE_ROSTER_PATH.exists()

    def test_the_hand_written_roster_is_deleted(self):
        """ADR 0007 step 3b's headline deletion. `commands.ts` was the
        SIXTH roster the record counts, and the one whose drift was
        worst (no /run, /task or /token)."""
        assert not (REPO_ROOT / "vscode-extension" / "src" / "shared"
                    / "commands.ts").exists()


class TestVscodeRosterDrivenDispatchOrder:
    """Step 3b replaced branch order with roster data; these pin the two
    orderings that still carry the `/token` guarantee, plus the legacy
    table that must not grow."""

    def _route_body(self) -> str:
        return _extract_braced_body(
            _read(VSCODE_ROUTER_PATH), r"async route\(input: string\): Promise<void>\s*"
        )

    def test_fail_closed_gate_precedes_every_dispatch_path(self):
        assert_vscode_fail_closed_gate_precedes_every_dispatch(self._route_body())

    def test_client_dispatch_precedes_factory_dispatch(self):
        assert_vscode_client_dispatch_precedes_factory_dispatch(self._route_body())

    def test_no_per_name_escape_hatch_remains(self):
        assert_vscode_has_no_per_name_escape_hatch(_read(VSCODE_CHATPANEL_PATH))

    def test_legacy_table_holds_exactly_the_acknowledged_five(self):
        assert_vscode_legacy_table_is_exactly(
            _read(VSCODE_ROUTER_PATH), set(LEGACY_INTERCEPT_BASELINE))

    def test_no_declared_command_sits_in_the_legacy_table(self):
        """The other direction: a command Python declares a
        `client_action` for must be routed by the roster, never by the
        legacy table."""
        declared = {
            info.canonical for info in CommandFactory.iter_completion_specs()
            if info.client_action
            and (info.client_action_clients is None
                 or "vscode" in info.client_action_clients)
        }
        overlap = declared & LEGACY_INTERCEPT_BASELINE
        assert not overlap, (
            f"{sorted(overlap)} have a client_action AND sit in the legacy "
            "table — remove them from the table, that is the shrink"
        )

    def test_action_registry_implements_every_vscode_action(self):
        """Read the Python declaration, not a hand-copied list: every spec
        whose `client_action_clients` includes "vscode" must have an
        implementation. A miniature of step 5's parity fence."""
        specs = CommandFactory.iter_completion_specs()
        vscode_actions = {
            info.client_action for info in specs
            if info.client_action
            and (info.client_action_clients is None
                 or "vscode" in info.client_action_clients)
            and (info.clients is None or "vscode" in info.clients)
        }
        assert vscode_actions, "no vscode client actions declared — declaration drift?"
        assert_vscode_action_registry_implements(
            _read(VSCODE_ROUTER_PATH), vscode_actions)

    def test_extraction_stops_at_route_method_end(self):
        """Sanity check on the extractor: the extracted route() body must
        not bleed into the next method."""
        assert "Return the loaded roster" not in self._route_body()


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


_REAL_SHAPE = """
        async dispatch(input) {
            const roster = await this._readyRoster();
            if (!roster) {
                this._explainMissingRoster(cmd);
                return;
            }
            if (STREAMING_COMMANDS.has(cmd)) {
                await this.app.streamChat(input);
                return;
            }
            const entry = roster.resolve(cmd);
            if (entry && entry.dispatch === 'client') {
                await this._dispatchClientAction(entry, args, input);
                return;
            }
            await this._dispatchToFactory(entry ? entry.name : cmd.slice(1), args);
        }
        """


class TestMutationWebFailClosedGate:
    def test_rejects_missing_gate(self):
        broken = """
        async dispatch(input) {
            const entry = this.app.commandRoster.resolve(cmd);
            await this._dispatchToFactory(cmd.slice(1), args);
        }
        """
        with pytest.raises(AssertionError):
            assert_web_fail_closed_gate_precedes_every_dispatch(broken)

    def test_rejects_gate_whose_result_is_never_checked(self):
        broken = """
        async dispatch(input) {
            const roster = await this._readyRoster();
            await this._dispatchToFactory(cmd.slice(1), args);
        }
        """
        with pytest.raises(AssertionError):
            assert_web_fail_closed_gate_precedes_every_dispatch(broken)

    def test_rejects_gate_that_falls_through_without_return(self):
        broken = """
        async dispatch(input) {
            const roster = await this._readyRoster();
            if (!roster) { this._explainMissingRoster(cmd); }
            await this._dispatchToFactory(cmd.slice(1), args);
        }
        """
        with pytest.raises(AssertionError):
            assert_web_fail_closed_gate_precedes_every_dispatch(broken)

    def test_rejects_a_dispatch_path_reachable_before_the_gate(self):
        """The exact regression: streaming commands hoisted above the gate,
        so a slash command still leaves the client with no roster."""
        broken = """
        async dispatch(input) {
            if (STREAMING_COMMANDS.has(cmd)) {
                await this.app.streamChat(input);
                return;
            }
            const roster = await this._readyRoster();
            if (!roster) {
                this._explainMissingRoster(cmd);
                return;
            }
            await this._dispatchToFactory(cmd.slice(1), args);
        }
        """
        with pytest.raises(AssertionError):
            assert_web_fail_closed_gate_precedes_every_dispatch(broken)

    def test_accepts_the_real_shape(self):
        assert_web_fail_closed_gate_precedes_every_dispatch(_REAL_SHAPE)


class TestMutationWebClientDispatchOrder:
    def test_rejects_client_branch_after_factory_dispatch(self):
        broken = """
        async dispatch(input) {
            await this._dispatchToFactory(cmd.slice(1), args);
            if (entry && entry.dispatch === 'client') {
                await this._dispatchClientAction(entry, args, input);
                return;
            }
        }
        """
        with pytest.raises(AssertionError):
            assert_web_client_dispatch_precedes_factory_dispatch(broken)

    def test_rejects_client_branch_without_return(self):
        broken = """
        async dispatch(input) {
            if (entry && entry.dispatch === 'client') {
                await this._dispatchClientAction(entry, args, input);
            }
            await this._dispatchToFactory(cmd.slice(1), args);
        }
        """
        with pytest.raises(AssertionError):
            assert_web_client_dispatch_precedes_factory_dispatch(broken)

    def test_rejects_routing_that_stopped_reading_the_roster(self):
        broken = """
        async dispatch(input) {
            await this._dispatchToFactory(cmd.slice(1), args);
        }
        """
        with pytest.raises(AssertionError):
            assert_web_client_dispatch_precedes_factory_dispatch(broken)

    def test_accepts_the_real_shape(self):
        assert_web_client_dispatch_precedes_factory_dispatch(_REAL_SHAPE)


class TestMutationWebEscapeHatch:
    def test_rejects_a_reintroduced_token_branch(self):
        broken = """
        async dispatch(input) {
            if (cmd === '/token') { await this._handleTokenCommand(args); return; }
            await this._dispatchToFactory(cmd.slice(1), args);
        }
        """
        with pytest.raises(AssertionError):
            assert_web_has_no_per_name_escape_hatch(broken)

    def test_accepts_the_real_shape(self):
        assert_web_has_no_per_name_escape_hatch(_REAL_SHAPE)


class TestMutationWebActionRegistry:
    def test_rejects_a_registry_missing_an_action(self):
        broken = """
        CommandDispatcher.CLIENT_ACTIONS = {
            'token.manage'({ args }) { return this._handleTokenCommand(args); },
        };
        """
        with pytest.raises(AssertionError):
            assert_web_action_registry_implements(broken, {"token.manage", "auto.loop"})

    def test_rejects_a_missing_registry(self):
        with pytest.raises(AssertionError):
            assert_web_action_registry_implements("const x = 1;", {"token.manage"})

    def test_accepts_a_complete_registry(self):
        ok = """
        CommandDispatcher.CLIENT_ACTIONS = {
            'token.manage'({ args }) { return this._handleTokenCommand(args); },
            'auto.loop'({ args, input }) { return this._dispatchAgent(args, input); },
        };
        """
        assert_web_action_registry_implements(ok, {"token.manage", "auto.loop"})


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


_VSCODE_REAL_SHAPE = """
        async route(input: string): Promise<void> {
            this._host.echo(redacted, verdict.sensitive, input);
            const roster = await this._readyRoster();
            if (!roster) {
                this._explainMissingRoster(typed);
                return;
            }
            const entry = roster.resolve(typed);
            if (entry && entry.dispatch === 'client') {
                await this._dispatchClientAction(entry, ctx);
                return;
            }
            const legacy = this._host.legacy[name];
            if (legacy) { await legacy(ctx); return; }
            await this._host.dispatchToFactory(name, args);
        }
        """


class TestMutationVscodeFailClosedGate:
    def test_rejects_missing_gate(self):
        broken = """
        async route(input: string): Promise<void> {
            const entry = this._host.roster.resolve(typed);
            await this._host.dispatchToFactory(name, args);
        }
        """
        with pytest.raises(AssertionError):
            assert_vscode_fail_closed_gate_precedes_every_dispatch(broken)

    def test_rejects_gate_whose_result_is_never_checked(self):
        broken = """
        async route(input: string): Promise<void> {
            const roster = await this._readyRoster();
            await this._host.dispatchToFactory(name, args);
        }
        """
        with pytest.raises(AssertionError):
            assert_vscode_fail_closed_gate_precedes_every_dispatch(broken)

    def test_rejects_gate_that_falls_through_without_return(self):
        broken = """
        async route(input: string): Promise<void> {
            const roster = await this._readyRoster();
            if (!roster) { this._explainMissingRoster(typed); }
            await this._host.dispatchToFactory(name, args);
        }
        """
        with pytest.raises(AssertionError):
            assert_vscode_fail_closed_gate_precedes_every_dispatch(broken)

    def test_rejects_a_legacy_intercept_hoisted_above_the_gate(self):
        """The exact regression to fear here: the five legacy intercepts
        put back at the top, so `/tools` (and anything else) runs with no
        roster — the escape-hatch shape step 3b removed."""
        broken = """
        async route(input: string): Promise<void> {
            const legacy = this._host.legacy[typed];
            if (legacy) { await legacy(ctx); return; }
            const roster = await this._readyRoster();
            if (!roster) {
                this._explainMissingRoster(typed);
                return;
            }
            await this._host.dispatchToFactory(name, args);
        }
        """
        with pytest.raises(AssertionError):
            assert_vscode_fail_closed_gate_precedes_every_dispatch(broken)

    def test_accepts_the_real_shape(self):
        assert_vscode_fail_closed_gate_precedes_every_dispatch(_VSCODE_REAL_SHAPE)


class TestMutationVscodeClientDispatchOrder:
    def test_rejects_client_branch_after_factory_dispatch(self):
        broken = """
        async route(input: string): Promise<void> {
            await this._host.dispatchToFactory(name, args);
            if (entry && entry.dispatch === 'client') {
                await this._dispatchClientAction(entry, ctx);
                return;
            }
        }
        """
        with pytest.raises(AssertionError):
            assert_vscode_client_dispatch_precedes_factory_dispatch(broken)

    def test_rejects_client_branch_without_return(self):
        broken = """
        async route(input: string): Promise<void> {
            if (entry && entry.dispatch === 'client') {
                await this._dispatchClientAction(entry, ctx);
            }
            await this._host.dispatchToFactory(name, args);
        }
        """
        with pytest.raises(AssertionError):
            assert_vscode_client_dispatch_precedes_factory_dispatch(broken)

    def test_rejects_routing_that_stopped_reading_the_roster(self):
        broken = """
        async route(input: string): Promise<void> {
            await this._host.dispatchToFactory(name, args);
        }
        """
        with pytest.raises(AssertionError):
            assert_vscode_client_dispatch_precedes_factory_dispatch(broken)

    def test_accepts_the_real_shape(self):
        assert_vscode_client_dispatch_precedes_factory_dispatch(_VSCODE_REAL_SHAPE)


class TestMutationVscodeEscapeHatch:
    def test_rejects_a_reintroduced_token_branch(self):
        broken = """
        private async handleSlashCommand(input: string) {
            if (command === 'token') { await this.handleTokenCommand(args); return; }
            await this.getCommandRouter().route(input);
        }
        """
        with pytest.raises(AssertionError):
            assert_vscode_has_no_per_name_escape_hatch(broken)

    def test_accepts_a_subcommand_comparison(self):
        """`subcommand === 'clear'` inside handleContextCommand is not an
        intercept — excluding it is the same `grep -v subcommand` the
        plan's own recipe uses."""
        ok = "if (subcommand === 'clear') { await this.clearContext(); }"
        assert_vscode_has_no_per_name_escape_hatch(ok)  # must not raise


class TestMutationVscodeLegacyTable:
    def test_rejects_a_grown_table(self):
        broken = """
        export const LEGACY_INTERCEPTS: readonly string[] = [
            'tools', 'checkpoint', 'context', 'ls', 'tree', 'newthing',
        ];
        """
        with pytest.raises(AssertionError):
            assert_vscode_legacy_table_is_exactly(
                broken, set(LEGACY_INTERCEPT_BASELINE))

    def test_rejects_a_missing_table(self):
        with pytest.raises(AssertionError):
            assert_vscode_legacy_table_is_exactly(
                "const x = 1;", set(LEGACY_INTERCEPT_BASELINE))

    def test_accepts_the_baseline(self):
        ok = """
        export const LEGACY_INTERCEPTS: readonly string[] = [
            'tools',
            'checkpoint',
            'context',
            'ls',
            'tree',
        ];
        """
        assert_vscode_legacy_table_is_exactly(ok, set(LEGACY_INTERCEPT_BASELINE))


class TestMutationVscodeActionRegistry:
    def test_rejects_a_registry_missing_an_action(self):
        broken = """
        export const CLIENT_ACTIONS: Record<string, OpsAction> = {
            'token.manage': (ops, ctx) => ops.handleToken(ctx.args),
        };
        """
        with pytest.raises(AssertionError):
            assert_vscode_action_registry_implements(
                broken, {"token.manage", "coding.stream"})

    def test_rejects_a_missing_registry(self):
        with pytest.raises(AssertionError):
            assert_vscode_action_registry_implements("const x = 1;", {"token.manage"})

    def test_accepts_a_complete_registry(self):
        ok = """
        export const CLIENT_ACTIONS: Record<string, OpsAction> = {
            'token.manage': (ops, ctx) => ops.handleToken(ctx.args),
            'coding.stream': (ops, ctx) => ops.handleCodingTask(ctx.name, ctx.args),
        };
        """
        assert_vscode_action_registry_implements(
            ok, {"token.manage", "coding.stream"})


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

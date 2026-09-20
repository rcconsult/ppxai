"""Client-handled commands as registered specs (ADR 0007 step 1b).

`/quit` (alias `/exit`) and `/token` used to live in
`engine/completion.py::_BUILTIN_SPECIAL_COMMANDS`, outside the registry,
because a `CommandSpec` could not express a command with no server
handler. Step 1a gave it `client_action` / `client_action_clients` /
`clients`; step 1b registers the two specs and retires the hand-written
roster.

That makes `POST /command/token` REACHABLE for the first time. The plan's
behaviour 2 says it must answer with a clear "handled by the client"
envelope — not execute, not 404, not 500 — and behaviour 4 says the
arguments must never be echoed or logged, because `/token set <value>`
carries a bearer token.

This file covers:
  - both specs are registered with the decided fields, and `/exit`
    resolves to `/quit` (one spec, not two);
  - the route's client-handled envelope for `/token` and `/quit`;
  - the security contract — `set SECRET123` appears nowhere in the
    response and nowhere in the server log — with the assertion helper
    MUTATION-VERIFIED against a real, deliberately-echoing command on the
    same route, so it is proven able to fail;
  - completion surfaces each command exactly ONCE per client (a leftover
    second roster would double-list them);
  - Rich and Textual answer `/token` with a message instead of crashing
    on `spec.handler(...)` where `handler is None`.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import asyncio

from fastapi.testclient import TestClient

import ppxai.commands.handler as rich_handler_mod
import ppxai.server.http as http_module
from ppxai.commands.client_handled import client_handled_message
from ppxai.commands.factory import SERVER_CLIENTS, CommandFactory, CommandSpec, client_sees
from ppxai.commands.results import NotificationResult, ResultStatus
from ppxai.common.logger import get_logger
from ppxai.engine.completion import complete
from ppxai.tui.app import PPXAIDEApp

SECRET = "SECRET123"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestSpecsAreRegistered:
    def test_quit_spec_fields(self):
        spec = CommandFactory.get("quit")
        assert spec is not None
        assert spec.handler is None
        assert spec.client_action == "app.quit"
        assert spec.aliases == ["exit"]
        assert spec.description == "Exit the application"
        # Owner decision (2026-09-20, reverses the earlier "universal"
        # call): gated to the terminal clients. Ending a GUI session is a
        # UI button workflow (web's header button, VSCode's Disconnect),
        # not a command.
        assert spec.clients == frozenset({"rich", "textual"})
        assert spec.client_action_clients is None
        assert spec.is_client_handled is True

    def test_token_spec_fields(self):
        spec = CommandFactory.get("token")
        assert spec is not None
        assert spec.handler is None
        assert spec.client_action == "token.manage"
        assert spec.clients == frozenset({"web", "vscode"})
        assert spec.client_action_clients is None
        assert spec.usage == "/token [status|set|mint|clear]"
        assert [name for name, _ in spec.subcommands] == [
            "status", "set", "mint", "clear"
        ]
        assert all(desc for _, desc in spec.subcommands)
        assert spec.is_client_handled is True

    def test_exit_resolves_to_quit(self):
        """One spec, not two — `/exit` is an alias (owner decision)."""
        assert CommandFactory.get("exit") is CommandFactory.get("quit")
        assert "exit" not in CommandFactory.list_all()

    def test_dispatches_in_client(self):
        """`client_action_clients` absent => every client that SEES it —
        and, since the 2026-09-20 decision, /quit is only seen by
        rich/textual."""
        quit_spec = CommandFactory.get("quit")
        token_spec = CommandFactory.get("token")
        for client in ("rich", "textual"):
            assert quit_spec.dispatches_in_client(client) is True, client
        for client in ("web", "vscode"):
            assert quit_spec.dispatches_in_client(client) is False, client
        assert token_spec.dispatches_in_client("web") is True
        assert token_spec.dispatches_in_client("rich") is False

    def test_factory_dispatch_refuses_without_echoing_args(self):
        """`CommandFactory.dispatch` must not call a None handler — and its
        error must not quote the arguments."""
        with pytest.raises(ValueError) as exc:
            CommandFactory.dispatch("token", SimpleNamespace(), f"set {SECRET}")
        assert SECRET not in str(exc.value)
        assert "client-handled" in str(exc.value)


# ---------------------------------------------------------------------------
# HTTP route — the client-handled envelope
# ---------------------------------------------------------------------------

@pytest.fixture
def http_client():
    """TestClient against the FastAPI app (idiom from
    tests/test_command_envelope.py). Context-managed so the app gets one
    persistent event loop — see docs/lessons/testclient-per-request-event-loop.md."""
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def echo_command():
    """A NORMAL (server-handled) command that echoes its args back.

    The mutation lever for the security assertions below: run the same
    helper against this and it must FAIL, proving it can detect a leak
    through the real route rather than passing vacuously.
    """
    name = "_client_handled_echo_probe"

    def handler(ctx, args):
        return NotificationResult(status=ResultStatus.SUCCESS, message=f"args={args}")

    CommandFactory.register(CommandSpec(
        name=name,
        description="echo probe",
        handler=handler,
    ))
    yield name
    CommandFactory.unregister(name)


@pytest.fixture
def quiet_command():
    """A server-handled command that does NOT echo its args back.

    Isolates the log-only leak: the response is clean, but the route's own
    `args=...` info line carries the arguments.
    """
    name = "_client_handled_quiet_probe"

    def handler(ctx, args):
        return NotificationResult(status=ResultStatus.SUCCESS, message="ok")

    CommandFactory.register(CommandSpec(
        name=name,
        description="quiet probe",
        handler=handler,
    ))
    yield name
    CommandFactory.unregister(name)


def assert_args_not_leaked(response, caplog, secret: str) -> None:
    """Neither the response body nor any log record may carry `secret`."""
    body = response.text
    if secret in body:
        raise AssertionError(f"secret leaked into the response body: {body!r}")
    for record in caplog.records:
        if secret in record.getMessage():
            raise AssertionError(
                f"secret leaked into a log line: {record.getMessage()!r}"
            )


@pytest.fixture
def server_logging(tmp_path, monkeypatch):
    """Force the server Logger on so caplog sees the route's lines.

    Same shape as tests/test_command_envelope.py::TestRouteLogging — the
    `ppxai.common.Logger` wrapper is a no-op until enabled, so without
    this the "no secret in the log" assertion would pass vacuously.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    log = get_logger("server")
    was_enabled = log.enabled
    if not was_enabled:
        log.enable()
    yield
    if not was_enabled and hasattr(log, "disable"):
        log.disable()


class TestClientHandledEnvelope:
    @pytest.mark.parametrize("name", ["token", "quit"])
    def test_envelope_shape(self, http_client, name):
        resp = http_client.post(f"/command/{name}", json={"args": ""})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body.keys()) == {
            "ok", "result", "side_effects", "events", "version"
        }
        assert body["version"] == 1
        assert body["ok"] is False
        assert body["side_effects"] == []

    @pytest.mark.parametrize("name,action", [("token", "token.manage"),
                                             ("quit", "app.quit")])
    def test_result_carries_machine_readable_marker(self, http_client, name, action):
        body = http_client.post(f"/command/{name}", json={"args": ""}).json()
        result = body["result"]
        assert result["status"] == "error"
        meta = result["metadata"]
        assert meta["client_handled"] is True
        assert meta["command"] == name
        assert meta["client_action"] == action

    def test_token_names_the_clients_that_implement_it(self, http_client):
        body = http_client.post("/command/token", json={"args": ""}).json()
        assert body["result"]["metadata"]["clients"] == ["vscode", "web"]
        assert "web" in body["result"]["message"]

    def test_not_confused_with_an_unknown_command(self, http_client):
        """404 is reserved for names the registry does not have. A
        client-handled command EXISTS; it is just not ours to run."""
        assert http_client.post("/command/token", json={"args": ""}).status_code == 200
        unknown = http_client.post("/command/__nope__", json={"args": ""})
        assert unknown.status_code == 404

    def test_alias_takes_the_same_path(self, http_client):
        body = http_client.post("/command/exit", json={"args": ""}).json()
        assert body["result"]["metadata"]["client_handled"] is True
        assert body["result"]["metadata"]["command"] == "quit"


class TestSecretNeverEchoed:
    """`/token set <value>` carries a bearer token (plan behaviour 4)."""

    def test_response_and_log_are_clean(self, http_client, server_logging, caplog):
        with caplog.at_level(logging.DEBUG, logger="ppxai.server"):
            resp = http_client.post("/command/token", json={"args": f"set {SECRET}"})
        assert resp.status_code == 200
        assert_args_not_leaked(resp, caplog, SECRET)

    def test_mutation_the_assertion_can_fail(self, http_client, server_logging,
                                             caplog, echo_command):
        """Mutation-verification: the SAME helper, against a command that
        DOES echo its args through the real route, must raise. Without
        this, a helper that quietly stopped checking would look green."""
        with caplog.at_level(logging.DEBUG, logger="ppxai.server"):
            resp = http_client.post(f"/command/{echo_command}",
                                    json={"args": f"set {SECRET}"})
        assert SECRET in resp.text, "probe did not echo — mutation is not exercised"
        with pytest.raises(AssertionError):
            assert_args_not_leaked(resp, caplog, SECRET)

    def test_mutation_detects_a_log_only_leak(self, http_client, server_logging,
                                              caplog, quiet_command):
        """The route logs `args_preview` for every server-handled command —
        that line sat BEFORE the dispatch lookup until step 1b moved it
        below the client-handled branch. A command whose RESPONSE is clean
        but whose args reach that log line is the log-only leak, and the
        helper must catch it."""
        with caplog.at_level(logging.DEBUG, logger="ppxai.server"):
            resp = http_client.post(f"/command/{quiet_command}",
                                    json={"args": f"set {SECRET}"})
        assert SECRET not in resp.text, "probe echoed into the body; not log-only"
        assert any(SECRET in r.getMessage() for r in caplog.records), (
            "probe did not reach the route's args log line — mutation is not exercised"
        )
        with pytest.raises(AssertionError):
            assert_args_not_leaked(resp, caplog, SECRET)


# ---------------------------------------------------------------------------
# Completion — exactly once per client, no second roster
# ---------------------------------------------------------------------------

class TestCompletionListsEachCommandOnce:
    @pytest.mark.parametrize("client", ["web", "vscode", "rich", "textual", None])
    def test_no_duplicates_in_the_whole_catalog(self, client):
        texts = [i["text"] for i in complete("/", client=client)]
        dupes = {t for t in texts if texts.count(t) > 1}
        assert not dupes, (client, dupes)

    @pytest.mark.parametrize("client", ["rich", "textual", None])
    def test_quit_and_exit_surface_exactly_once(self, client):
        texts = [i["text"] for i in complete("/", client=client)]
        assert texts.count("/quit") == 1, (client, texts)
        assert texts.count("/exit") == 1, (client, texts)

    @pytest.mark.parametrize("client", ["web", "vscode"])
    def test_quit_and_exit_absent_from_gui_clients(self, client):
        # Owner decision (2026-09-20): ending a GUI session is a button
        # workflow, not a command — /quit and /exit must not complete.
        texts = [i["text"] for i in complete("/", client=client)]
        assert "/quit" not in texts, (client, texts)
        assert "/exit" not in texts, (client, texts)

    def test_token_surfaces_once_where_implemented(self):
        for client in ("web", "vscode", None):
            texts = [i["text"] for i in complete("/", client=client)]
            assert texts.count("/token") == 1, client

    def test_token_absent_from_the_tuis(self):
        for client in ("rich", "textual"):
            texts = [i["text"] for i in complete("/", client=client)]
            assert "/token" not in texts, client

    def test_token_subcommands_come_from_the_spec(self):
        """The `_TOKEN_SUBCOMMANDS` table is gone; the four rows now live
        on the spec and completion reads them there."""
        spec = CommandFactory.get("token")
        offered = [i["text"] for i in complete("/token ", client="web")]
        assert offered == [name for name, _ in spec.subcommands]


# ---------------------------------------------------------------------------
# /help scoping
# ---------------------------------------------------------------------------

class TestHelpScoping:
    def test_help_lists_quit_for_terminal_clients_and_none(self):
        # client=None fails open (legacy/unknown callers see everything).
        for client in ("rich", "textual", None):
            assert "/quit" in CommandFactory.generate_help(client=client), client

    def test_help_hides_quit_from_the_gui_clients(self):
        # Owner decision (2026-09-20): /quit is a UI button workflow in a
        # GUI (web's header button, VSCode's Disconnect), not a command —
        # it must not appear in /help there.
        #
        # This calls generate_help(client="web") DIRECTLY with a real
        # client id, which is correct for a caller that knows its
        # audience. It does NOT exercise the real server path — that
        # path is ServerCommandContext, which does not know which of
        # web/vscode it is serving and used to fail open with
        # client=None. This test alone was green while the server route
        # was still leaking /quit into GUI help: see
        # TestServerHelpUsesTheCandidateSet below for the route-level
        # regression test.
        for client in ("web", "vscode"):
            assert "/quit" not in CommandFactory.generate_help(client=client), client

    def test_help_hides_token_from_the_tuis(self):
        for client in ("rich", "textual"):
            assert "/token" not in CommandFactory.generate_help(client=client), client

    def test_help_lists_token_for_web_and_vscode(self):
        for client in ("web", "vscode", None):
            assert "/token" in CommandFactory.generate_help(client=client), client

    def test_detailed_help_follows_the_same_gate(self):
        assert CommandFactory.get_command_help("token", client="rich") is None
        assert CommandFactory.get_command_help("token", client="web") is not None
        assert CommandFactory.get_command_help("quit", client="rich") is not None
        assert CommandFactory.get_command_help("quit", client="web") is None


class TestServerHelpUsesTheCandidateSet:
    """The real server path: `POST /command/help` through
    `ServerCommandContext`, which serves both web and VSCode and cannot
    tell them apart. `_help_client` gates on `SERVER_CLIENTS` — the
    candidate set `{"web", "vscode"}` — not `None`, so a command gated
    away from BOTH (`/quit`, Rich/Textual-only) is hidden, while a
    command visible to either candidate (`/token`, web/vscode-only)
    still shows.
    """

    def test_quit_and_exit_absent_from_the_route(self, http_client):
        body = http_client.post("/command/help", json={"args": ""}).json()
        content = body["result"]["content"]
        assert "/quit" not in content
        assert "/exit" not in content

    def test_token_present_on_the_route(self, http_client):
        body = http_client.post("/command/help", json={"args": ""}).json()
        content = body["result"]["content"]
        assert "/token" in content

    def test_detailed_help_for_quit_is_not_found_through_the_route(self, http_client):
        body = http_client.post("/command/help", json={"args": "quit"}).json()
        assert "Unknown command" in body["result"]["message"]

    def test_in_process_rich_and_textual_help_are_unaffected(self):
        # Rich and Textual DO know their own client id (RichCommandContext
        # returns "rich" directly; any other in-process context is
        # Textual) — those paths were never the buggy one, and this fix
        # must not change them: /quit stays, /token stays hidden.
        for client in ("rich", "textual"):
            help_text = CommandFactory.generate_help(client=client)
            assert "/quit" in help_text, client
            assert "/token" not in help_text, client


class TestClientSeesCandidateSet:
    """Truth table for `client_sees`'s three `client` shapes."""

    def test_none_clients_is_universal_for_a_set_candidate(self):
        assert client_sees(None, frozenset({"web", "vscode"})) is True

    def test_disjoint_sets_are_not_visible(self):
        assert client_sees(frozenset({"rich", "textual"}),
                           frozenset({"web", "vscode"})) is False

    def test_overlapping_sets_are_visible(self):
        assert client_sees(frozenset({"web"}), frozenset({"web", "vscode"})) is True

    def test_client_none_still_fails_open_for_a_gated_command(self):
        # Fail-open pinned: a legacy/unknown caller (client=None) sees a
        # gated command regardless of how narrowly it is gated.
        assert client_sees(frozenset({"rich"}), None) is True

    def test_a_command_gated_to_only_vscode_is_over_listed_for_the_server_set(self):
        # Documented, known limitation (not a bug): SERVER_CLIENTS can't
        # distinguish web from vscode, so a command gated to ONLY vscode
        # is still visible to the server's candidate set. This is the
        # remaining over-listing case called out in
        # commands/system.py::_help_client's docstring.
        assert client_sees(frozenset({"vscode"}), SERVER_CLIENTS) is True


# ---------------------------------------------------------------------------
# In-process clients must not call a None handler
# ---------------------------------------------------------------------------

class TestRichPathDoesNotCrash:
    def test_token_reports_instead_of_calling_none(self, capsys):
        """`CommandHandler.handle_command` reaches the factory lookup with
        no engine access needed for this branch, so an empty stand-in
        `self` exercises exactly the dispatch decision."""
        result = rich_handler_mod.CommandHandler.handle_command(
            SimpleNamespace(), f"/token set {SECRET}"
        )
        assert result is False
        out = capsys.readouterr().out
        assert "handled by the client" in out
        assert SECRET not in out

    def test_quit_still_intercepted_before_the_factory(self):
        """`/quit` and `/exit` are handled by `handle_quit()` ABOVE the
        factory lookup — registering the spec must not change that."""
        calls = []

        stub = SimpleNamespace(handle_quit=lambda: calls.append(True) or True)
        for text in ("/quit", "/exit"):
            assert rich_handler_mod.CommandHandler.handle_command(stub, text) is True
        assert len(calls) == 2


class TestTextualPathDoesNotCrash:
    def test_token_reports_instead_of_calling_none(self):
        pytest.importorskip("textual")


        messages: list[str] = []
        stub = SimpleNamespace(
            _chat_view=SimpleNamespace(add_system_message=messages.append),
        )
        asyncio.run(PPXAIDEApp._handle_command(stub, f"/token set {SECRET}"))
        assert messages, "no message rendered"
        assert "handled by the client" in messages[0]
        assert SECRET not in messages[0]


class TestClientHandledMessage:
    def test_message_names_the_clients_and_hides_args(self):
        msg = client_handled_message(CommandFactory.get("token"))
        assert "vscode" in msg and "web" in msg
        assert SECRET not in msg

    def test_gated_command_message_names_its_clients(self):
        # Owner decision (2026-09-20) gated /quit to {rich, textual}, so
        # it now carries a client list like /token — no longer the
        # "universal, no list" example.
        msg = client_handled_message(CommandFactory.get("quit"))
        assert "available in" in msg
        assert "rich" in msg and "textual" in msg

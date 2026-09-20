"""`GET /commands` — the command roster endpoint (ADR 0007 step 2).

Step 2 is SERVER-ONLY: it builds the read half of the `/command*`
resource plus the change signal, and touches no JS/TS consumer (that is
step 3). What it must get right:

  - **One serializer.** `CommandFactory.roster()` is the single place a
    spec becomes JSON. The endpoint returns it verbatim, and the
    in-process TUIs can call the same method — so there is no second
    shape to drift.
  - **One entry per CANONICAL command.** Aliases are a FIELD, not extra
    rows; restating an alias as its own entry is precisely the
    `web/shared/commands.js` duplication this record removes, so `exit`
    must appear only inside `/quit`'s `aliases`.
  - **Nothing callable crosses the wire.** `CommandSpec.handler` has no
    representation in the payload. Asserted with a helper that is
    MUTATION-VERIFIED against a deliberately-poisoned payload, so it
    cannot pass vacuously.
  - **Per-client gating and `dispatch` routing.** `client=web` must not
    see `/quit`; `client=rich` must not see `/token`; and `dispatch`
    tells the requesting client where the command actually runs.
  - **A version that moves only when the roster does**, so a
    fetch-once client can detect staleness — and `/reload`, the one
    thing that changes the roster at runtime, carries the
    `refresh_command_roster` side effect.
  - **The same auth posture as its sibling UI routes.** Asserted by
    running the identical request against `POST /complete`.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

import ppxai.server.http as http_module
import ppxai.server.state as state
from ppxai.commands.factory import (
    KNOWN_CLIENTS,
    SERVER_CLIENTS,
    CommandFactory,
    CommandSpec,
    client_sees,
)
from ppxai.commands.results import NotificationResult, ResultStatus, SideEffectKind
from ppxai.server.secrets import EnvSecretProvider, ProviderChain

ROSTER_FIELDS = {
    "name",
    "aliases",
    "description",
    "usage",
    "category",
    "hidden",
    "subcommands",
    "clients",
    "client_action",
    "client_action_clients",
    "client_handled",
    "dispatch",
}


@pytest.fixture
def http_client():
    """TestClient against the FastAPI app (idiom from
    tests/test_client_handled_dispatch.py). Context-managed so the app
    gets one persistent event loop — see
    docs/lessons/testclient-per-request-event-loop.md."""
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


def fetch(http_client, client: str | None = None) -> dict:
    """GET the roster, assert 200, return the decoded payload."""
    params = {} if client is None else {"client": client}
    resp = http_client.get("/commands", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def entry(payload: dict, name: str) -> dict | None:
    for command in payload["commands"]:
        if command["name"] == name:
            return command
    return None


def names(payload: dict) -> list[str]:
    return [c["name"] for c in payload["commands"]]


def assert_no_callables(node, path: str = "$") -> None:
    """Recursively assert nothing in the payload is callable.

    The security-shaped assertion of this step: a spec carries a real
    function in `handler`, and the serializer must have no path that
    lets one reach the wire. MUTATION-VERIFIED below against a payload
    with a function planted in it.
    """
    if callable(node):
        raise AssertionError(f"callable leaked into the roster at {path}: {node!r}")
    if isinstance(node, dict):
        for key, value in node.items():
            assert_no_callables(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            assert_no_callables(value, f"{path}[{index}]")


def assert_absent(payload: dict, name: str) -> None:
    """Assert `name` is neither a command entry nor anyone's alias.

    Checking both halves matters: hiding a command's row while still
    publishing its name in an alias list would leak it just the same.
    MUTATION-VERIFIED below against a name that IS present.
    """
    if name in names(payload):
        raise AssertionError(f"/{name} is listed as a command entry")
    for command in payload["commands"]:
        if name in command["aliases"]:
            raise AssertionError(
                f"/{name} is published as an alias of /{command['name']}"
            )


# ---------------------------------------------------------------------------
# Payload shape
# ---------------------------------------------------------------------------

class TestPayloadShape:
    def test_top_level_keys(self, http_client):
        payload = fetch(http_client)
        assert set(payload.keys()) == {"version", "commands"}
        assert isinstance(payload["version"], int)
        assert isinstance(payload["commands"], list)
        assert payload["commands"]

    def test_every_entry_has_exactly_the_declared_fields(self, http_client):
        for command in fetch(http_client)["commands"]:
            assert set(command.keys()) == ROSTER_FIELDS, command["name"]

    def test_field_types(self, http_client):
        for command in fetch(http_client)["commands"]:
            where = command["name"]
            assert isinstance(command["name"], str), where
            assert isinstance(command["aliases"], list), where
            assert isinstance(command["description"], str), where
            assert isinstance(command["usage"], str), where
            assert isinstance(command["category"], str), where
            assert isinstance(command["hidden"], bool), where
            assert isinstance(command["client_handled"], bool), where
            assert command["dispatch"] in ("client", "server"), where
            assert command["clients"] is None or isinstance(command["clients"], list)
            assert (command["client_action_clients"] is None
                    or isinstance(command["client_action_clients"], list))
            for sub in command["subcommands"]:
                assert set(sub.keys()) == {"name", "description"}, where

    def test_no_handler_field(self, http_client):
        for command in fetch(http_client)["commands"]:
            assert "handler" not in command, command["name"]

    def test_no_callable_leaks(self, http_client):
        # The endpoint's JSON can't hold a callable, so probe the
        # in-process serializer too — that is where a leak would start.
        assert_no_callables(fetch(http_client))
        assert_no_callables(CommandFactory.roster())

    def test_mutation_the_callable_assertion_can_fail(self, http_client):
        """Prove `assert_no_callables` detects a planted function."""
        payload = fetch(http_client)
        payload["commands"][0]["handler"] = lambda ctx, args: None
        with pytest.raises(AssertionError, match="callable leaked"):
            assert_no_callables(payload)


# ---------------------------------------------------------------------------
# One entry per canonical command; aliases folded in
# ---------------------------------------------------------------------------

class TestCanonicalEntriesOnly:
    def test_names_are_unique(self, http_client):
        listed = names(fetch(http_client))
        assert len(listed) == len(set(listed))

    def test_no_alias_has_its_own_entry(self, http_client):
        payload = fetch(http_client)
        listed = set(names(payload))
        for command in payload["commands"]:
            for alias in command["aliases"]:
                assert alias not in listed, (
                    f"alias {alias!r} of /{command['name']} is ALSO a "
                    f"standalone entry — that is the commands.js "
                    f"duplication ADR 0007 removes"
                )

    def test_exit_appears_only_inside_quits_aliases(self, http_client):
        payload = fetch(http_client, client="rich")
        assert entry(payload, "exit") is None
        assert entry(payload, "quit")["aliases"] == ["exit"]

    def test_entries_match_the_registry_canonicals(self, http_client):
        listed = set(names(fetch(http_client, client="rich")))
        registered = {
            name for name in CommandFactory.list_all()
            if client_sees(CommandFactory.get(name).clients, "rich")
        }
        assert listed == registered

    def test_hidden_commands_are_published_with_the_flag(self, http_client):
        """The roster is the full DECLARATION — a client filters on
        `hidden`, it is not filtered out here. Completion and /help both
        need to know a hidden command exists (it is still dispatchable)."""
        payload = fetch(http_client, client="rich")
        hidden_in_registry = {
            name for name in CommandFactory.list_all()
            if CommandFactory.get(name).hidden
            and client_sees(CommandFactory.get(name).clients, "rich")
        }
        hidden_in_payload = {c["name"] for c in payload["commands"] if c["hidden"]}
        assert hidden_in_payload == hidden_in_registry


# ---------------------------------------------------------------------------
# Per-client gating + dispatch routing
# ---------------------------------------------------------------------------

class TestClientGating:
    def test_web_hides_quit_and_exit(self, http_client):
        payload = fetch(http_client, client="web")
        assert_absent(payload, "quit")
        assert_absent(payload, "exit")

    def test_mutation_the_absence_assertion_can_fail(self, http_client):
        """Prove `assert_absent` fails for something that IS listed —
        both through a command entry and through an alias."""
        payload = fetch(http_client, client="rich")
        with pytest.raises(AssertionError, match="command entry"):
            assert_absent(payload, "quit")
        with pytest.raises(AssertionError, match="alias"):
            assert_absent(payload, "exit")

    def test_web_sees_token_dispatching_in_the_client(self, http_client):
        token = entry(fetch(http_client, client="web"), "token")
        assert token is not None
        assert token["dispatch"] == "client"
        assert token["client_handled"] is True
        assert token["client_action"] == "token.manage"
        assert token["clients"] == ["vscode", "web"]
        assert [s["name"] for s in token["subcommands"]] == [
            "status", "set", "mint", "clear"
        ]

    def test_rich_is_the_reverse(self, http_client):
        payload = fetch(http_client, client="rich")
        assert_absent(payload, "token")
        quit_entry = entry(payload, "quit")
        assert quit_entry is not None
        assert quit_entry["dispatch"] == "client"
        assert quit_entry["client_action"] == "app.quit"
        assert quit_entry["clients"] == ["rich", "textual"]

    def test_vscode_matches_web_for_the_client_handled_pair(self, http_client):
        payload = fetch(http_client, client="vscode")
        assert entry(payload, "token") is not None
        assert_absent(payload, "quit")

    def test_textual_matches_rich_for_the_client_handled_pair(self, http_client):
        payload = fetch(http_client, client="textual")
        assert entry(payload, "quit") is not None
        assert_absent(payload, "token")

    def test_server_commands_dispatch_server_side(self, http_client):
        # A plain registered command (handler, no client_action) always
        # routes to the server, for every client.
        for client in sorted(KNOWN_CLIENTS):
            help_entry = entry(fetch(http_client, client=client), "help")
            assert help_entry["dispatch"] == "server", client
            assert help_entry["client_handled"] is False, client
            assert help_entry["client_action"] is None, client

    def test_hybrid_family_still_dispatches_server_side(self, http_client):
        # /task and /run have a real Python handler and no client_action
        # yet (their client actions arrive with the parity fence, step
        # 5). Until then the roster must say "server" rather than
        # guessing — a wrong "client" would break dispatch.
        payload = fetch(http_client, client="web")
        for name in ("task", "run"):
            command = entry(payload, name)
            assert command is not None, name
            assert command["dispatch"] == "server", name


class TestAbsentClientUsesTheCandidateSet:
    def test_absent_matches_the_server_clients_union(self, http_client):
        absent = fetch(http_client)
        expected = CommandFactory.roster(SERVER_CLIENTS)
        assert absent == expected

    def test_absent_still_hides_a_command_gated_away_from_both(self, http_client):
        # /quit is rich+textual only: disjoint from {web, vscode}, so
        # the candidate set hides it even without an explicit id. This
        # is the step-1b fix, re-asserted through the new endpoint.
        assert_absent(fetch(http_client), "quit")

    def test_absent_over_lists_a_single_client_command(self, http_client):
        # The known cost of the candidate set, unchanged: a vscode-only
        # command is visible to it. An explicit `client=web` is exact.
        name = "_roster_endpoint_vscode_only"
        CommandFactory.register(CommandSpec(
            name=name,
            description="vscode-only probe",
            handler=lambda ctx, args: None,
            clients=frozenset({"vscode"}),
        ))
        try:
            assert entry(fetch(http_client), name) is not None
            assert_absent(fetch(http_client, client="web"), name)
            assert entry(fetch(http_client, client="vscode"), name) is not None
        finally:
            CommandFactory.unregister(name)


class TestUnknownClientIsRejected:
    @pytest.mark.parametrize("bad", ["emacs", "WEB", "", "rich,textual"])
    def test_400(self, http_client, bad):
        resp = http_client.get("/commands", params={"client": bad})
        assert resp.status_code == 400, resp.text
        detail = resp.json()["detail"]
        assert "rich" in detail and "vscode" in detail

    def test_every_known_client_is_accepted(self, http_client):
        for client in sorted(KNOWN_CLIENTS):
            assert http_client.get(
                "/commands", params={"client": client}
            ).status_code == 200, client


# ---------------------------------------------------------------------------
# Determinism + the one-serializer property
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_entries_are_sorted_by_name(self, http_client):
        listed = names(fetch(http_client))
        assert listed == sorted(listed)

    def test_repeated_fetches_are_byte_identical(self, http_client):
        first = http_client.get("/commands").text
        second = http_client.get("/commands").text
        assert first == second

    @pytest.mark.parametrize("client", [None, "rich", "textual", "web", "vscode"])
    def test_endpoint_equals_the_in_process_serializer(self, http_client, client):
        """The ONE serializer: HTTP and in-process must not diverge."""
        audience = SERVER_CLIENTS if client is None else client
        assert fetch(http_client, client=client) == CommandFactory.roster(audience)


class TestETag:
    def test_etag_present_and_stable(self, http_client):
        first = http_client.get("/commands")
        second = http_client.get("/commands")
        assert first.headers["etag"]
        assert first.headers["etag"] == second.headers["etag"]

    def test_if_none_match_gets_304_without_a_body(self, http_client):
        etag = http_client.get("/commands").headers["etag"]
        resp = http_client.get("/commands", headers={"If-None-Match": etag})
        assert resp.status_code == 304
        assert resp.headers["etag"] == etag
        assert not resp.content

    def test_etag_differs_per_client(self, http_client):
        web = http_client.get("/commands", params={"client": "web"})
        rich = http_client.get("/commands", params={"client": "rich"})
        assert web.headers["etag"] != rich.headers["etag"]

    def test_stale_etag_gets_a_fresh_200(self, http_client):
        resp = http_client.get(
            "/commands", headers={"If-None-Match": 'W/"commands-0-server"'}
        )
        assert resp.status_code == 200
        assert resp.json()["commands"]


# ---------------------------------------------------------------------------
# Roster version
# ---------------------------------------------------------------------------

class TestRosterVersion:
    def test_stable_without_a_mutation(self, http_client):
        assert fetch(http_client)["version"] == fetch(http_client)["version"]

    def test_register_and_unregister_both_bump(self, http_client):
        before = fetch(http_client)["version"]
        name = "_roster_version_probe"
        CommandFactory.register(CommandSpec(
            name=name, description="probe", handler=lambda ctx, args: None,
        ))
        try:
            after_register = fetch(http_client)["version"]
            assert after_register > before
        finally:
            CommandFactory.unregister(name)
        assert fetch(http_client)["version"] > after_register

    def test_unregistering_a_missing_command_does_not_bump(self, http_client):
        before = fetch(http_client)["version"]
        assert CommandFactory.unregister("_roster_version_not_there") is False
        assert fetch(http_client)["version"] == before

    def test_reload_user_commands_bumps(self, http_client, monkeypatch, tmp_path):
        """`/reload` unregisters the previous custom commands, so the
        version moves even when the user directory is empty."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        name = "_roster_custom_probe"
        CommandFactory.register(CommandSpec(
            name=name,
            description="custom probe",
            handler=lambda ctx, args: None,
            category="custom",
        ))
        before = fetch(http_client)["version"]
        try:
            CommandFactory.reload_user_commands()
        finally:
            CommandFactory.unregister(name)
        assert fetch(http_client)["version"] > before
        assert entry(fetch(http_client), name) is None

    def test_etag_moves_with_the_version(self, http_client):
        before = http_client.get("/commands").headers["etag"]
        name = "_roster_etag_probe"
        CommandFactory.register(CommandSpec(
            name=name, description="probe", handler=lambda ctx, args: None,
        ))
        try:
            assert http_client.get("/commands").headers["etag"] != before
        finally:
            CommandFactory.unregister(name)


# ---------------------------------------------------------------------------
# The change signal: /reload's envelope
# ---------------------------------------------------------------------------

class TestReloadSignalsTheRoster:
    def test_kind_constant_exists(self):
        assert SideEffectKind.REFRESH_COMMAND_ROSTER == "refresh_command_roster"

    def test_envelope_carries_the_kind_and_version(
        self, http_client, monkeypatch, tmp_path
    ):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        body = http_client.post("/command/reload", json={"args": ""}).json()
        kinds = [se["kind"] for se in body["side_effects"]]
        assert SideEffectKind.REFRESH_COMMAND_ROSTER in kinds
        # `SideEffect.to_dict()` flattens the payload alongside `kind`.
        signal = next(se for se in body["side_effects"]
                      if se["kind"] == SideEffectKind.REFRESH_COMMAND_ROSTER)
        assert isinstance(signal["version"], int)
        assert signal["version"] == fetch(http_client)["version"]


# ---------------------------------------------------------------------------
# Auth posture — identical to the sibling UI routes
# ---------------------------------------------------------------------------

@pytest.fixture
def env_only_chain(monkeypatch):
    """Pin auth to env-only so the host's own config can't decide the
    outcome (same idiom as tests/test_auth_middleware.py)."""

    monkeypatch.setattr(
        state, "_secret_provider", ProviderChain([EnvSecretProvider()])
    )
    yield
    state._secret_provider = None


class TestAuthPostureMatchesComplete:
    """`GET /commands` must sit in exactly the same auth class as the
    sibling UI routes web/VSCode already call. Auth is global middleware
    (`server/http.py::auth_middleware`), so this is a property of the
    path, not of the route function — and the path is under neither
    `/v1/agent` nor `/v1/tokens`, the two prefixes that stay protected
    even from loopback. Asserted by running the same request against
    `POST /complete` and comparing.
    """

    COMPLETE_BODY = {"buffer": "/he", "cursor": 3}

    def test_auth_off_both_pass(self, env_only_chain, http_client, monkeypatch):
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        assert http_client.get("/commands").status_code == 200
        assert http_client.post("/complete", json=self.COMPLETE_BODY).status_code == 200

    def test_auth_on_without_bearer_both_401(
        self, env_only_chain, http_client, monkeypatch
    ):
        monkeypatch.setenv("PPXAI_API_TOKEN", "roster-test-token")
        roster = http_client.get("/commands")
        complete = http_client.post("/complete", json=self.COMPLETE_BODY)
        assert roster.status_code == complete.status_code == 401
        assert roster.headers.get("www-authenticate") == \
            complete.headers.get("www-authenticate")

    def test_auth_on_with_bearer_both_pass(
        self, env_only_chain, http_client, monkeypatch
    ):
        monkeypatch.setenv("PPXAI_API_TOKEN", "roster-test-token")
        headers = {"Authorization": "Bearer roster-test-token"}
        assert http_client.get("/commands", headers=headers).status_code == 200
        assert http_client.post(
            "/complete", json=self.COMPLETE_BODY, headers=headers
        ).status_code == 200

    def test_auth_on_with_a_wrong_bearer_both_401(
        self, env_only_chain, http_client, monkeypatch
    ):
        monkeypatch.setenv("PPXAI_API_TOKEN", "roster-test-token")
        headers = {"Authorization": "Bearer not-the-token"}
        assert http_client.get("/commands", headers=headers).status_code == 401
        assert http_client.post(
            "/complete", json=self.COMPLETE_BODY, headers=headers
        ).status_code == 401


# ---------------------------------------------------------------------------
# POST /command/{name} — the explicit client id (step-1b limitation closed)
# ---------------------------------------------------------------------------

class TestCommandRequestClientField:
    """The `client` body field is ADDITIVE: an existing client sends no
    such field and must behave exactly as before."""

    @pytest.fixture
    def probe(self):
        name = "_roster_request_client_probe"

        def handler(ctx, args):
            return NotificationResult(
                status=ResultStatus.SUCCESS, message=f"seen={ctx.client!r}"
            )

        CommandFactory.register(CommandSpec(
            name=name, description="client-id probe", handler=handler,
        ))
        yield name
        CommandFactory.unregister(name)

    def test_absent_field_reaches_the_handler_as_none(self, http_client, probe):
        body = http_client.post(f"/command/{probe}", json={"args": ""}).json()
        assert body["result"]["message"] == "seen=None"

    def test_explicit_field_reaches_the_handler(self, http_client, probe):
        body = http_client.post(
            f"/command/{probe}", json={"args": "", "client": "web"}
        ).json()
        assert body["result"]["message"] == "seen='web'"

    def test_unknown_client_is_rejected_before_dispatch(self, http_client, probe):
        resp = http_client.post(
            f"/command/{probe}", json={"args": "", "client": "emacs"}
        )
        assert resp.status_code == 400

    def test_bad_client_never_echoes_args(self, http_client, probe):
        """A request-shape rejection must not quote the arguments — a
        typo'd client on a `/token set <value>` body is still a secret."""
        secret = "ROSTER_SECRET_42"
        resp = http_client.post(
            "/command/token", json={"args": f"set {secret}", "client": "emacs"}
        )
        assert resp.status_code == 400
        assert secret not in resp.text

    def test_help_is_unchanged_without_the_field(self, http_client):
        """Regression pin for every shipped client: no `client` field
        means the SERVER_CLIENTS candidate set, exactly as in step 1b."""
        content = http_client.post(
            "/command/help", json={"args": ""}
        ).json()["result"]["content"]
        assert "/token" in content
        assert "/quit" not in content
